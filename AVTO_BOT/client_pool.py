"""
client_pool.py — Telethon client pool.

Muammo: Har foydalanuvchi uchun alohida TelegramClient yaratish —
RAM isrof va connection leak xavfi.

Yechim: ClientPool — clientlarni qayta ishlatadi, idle bo'lganlarni
vaqt bilan yopadi, bir vaqtda max N ta ulangan client bo'lishini
ta'minlaydi.

Afzalliklari:
- RAM tejash (idle clientlar yopiladi)
- Connection leak yo'q (auto-disconnect)
- Max concurrent limit (server overload oldini olish)
- Graceful shutdown (barcha clientlarni tozalab yopish)
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field

from telethon import TelegramClient
from telethon.errors import AuthKeyUnregisteredError, UserDeactivatedBanError
from telethon.sessions import StringSession

# ─────────────────────────────────────────────────────────────────────────
# KONFIGURATSIYA
# ─────────────────────────────────────────────────────────────────────────
MAX_CONCURRENT_CLIENTS = 50      # bir vaqtda max ulangan clientlar
CLIENT_IDLE_TIMEOUT_S = 300      # 5 daqiqa idle bo'lsa — disconnect
CONNECT_TIMEOUT_S = 20           # ulanish timeout


# ─────────────────────────────────────────────────────────────────────────
# EXCEPTIONS — acquire() natijasini aniq farqlash uchun
#
# MUHIM: ilgari acquire() barcha xatoda None qaytarardi va chaqiruvchi
# uni "sessiya o'ldi" deb hisoblab sessiyani o'chirib yuborardi. Bu
# pool to'lganda yoki vaqtinchalik tarmoq uzilishida ham sessiyani
# noto'g'ri o'chirishga olib kelardi. Endi ikki holat aniq ajratiladi.
# ─────────────────────────────────────────────────────────────────────────
class SessionInvalidError(Exception):
    """Sessiya Telegram tomonidan bekor qilingan yoki hisob bloklangan.
    Chaqiruvchi del_session qilishi va foydalanuvchini login'ga yo'naltirishi kerak."""


class PoolBusyError(Exception):
    """Pool to'la yoki vaqtinchalik tarmoq xatosi — sessiya BUTUN.
    Chaqiruvchi sessiyani o'chirmasdan keyinroq qayta urinishi kerak."""


@dataclass
class PooledClient:
    """Pool'dagi bitta client haqida ma'lumot."""
    uid: int
    client: TelegramClient
    last_used: float = field(default_factory=time.time)
    in_use: bool = False


class ClientPool:
    """Telethon clientlarni boshqaruvchi pool."""

    def __init__(self, api_id: int, api_hash: str, max_clients: int = MAX_CONCURRENT_CLIENTS):
        self.api_id = api_id
        self.api_hash = api_hash
        self.max_clients = max_clients
        self._clients: dict[int, PooledClient] = {}
        self._lock = asyncio.Lock()
        # Per-uid lock: bir foydalanuvchi uchun bir vaqtda bitta acquire.
        # Global _lock faqat _clients dict'ini o'qish/yozish uchun (qisqa),
        # tarmoq I/O (connect/authorize) uning TASHQARISIDA bajariladi.
        self._uid_locks: dict[int, asyncio.Lock] = {}
        self._cleanup_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Pool'ni ishga tushirish (cleanup taskni boshlash)."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(
                self._cleanup_loop(), name="client-pool-cleanup"
            )

    async def stop(self) -> None:
        """Pool'ni to'xtatish va barcha clientlarni yopish."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
            self._cleanup_task = None

        async with self._lock:
            for pc in list(self._clients.values()):
                await self._disconnect(pc)
            self._clients.clear()

    def _uid_lock(self, uid: int) -> asyncio.Lock:
        """Foydalanuvchi uchun acquire'ni serial qiluvchi lock.
        Bitta event loop'da get→set orasida await yo'q, shu sababli atomik."""
        lock = self._uid_locks.get(uid)
        if lock is None:
            lock = asyncio.Lock()
            self._uid_locks[uid] = lock
        return lock

    async def acquire(self, uid: int, session_string: str) -> TelegramClient:
        """
        Client olish. Agar pool'da bo'lsa — qayta ishlatadi, bo'lmasa yangi yaratadi.

        Tarmoq I/O (connect/authorize) global lock TASHQARISIDA bajariladi —
        shu sababli bir foydalanuvchining ulanishi (20s gacha) boshqa
        foydalanuvchilarni bloklamaydi. Bir uid uchun bir vaqtda faqat
        bitta acquire ishlaydi (per-uid lock).

        Raises:
            SessionInvalidError — sessiya bekor/hisob bloklangan
                                  (chaqiruvchi del_session qilsin)
            PoolBusyError       — pool to'la yoki vaqtinchalik tarmoq xatosi
                                  (chaqiruvchi sessiyani saqlab, keyin qayta urinsin)
        """
        async with self._uid_lock(uid):
            # 1) Mavjud client bormi? (qisqa lock — faqat dict o'qish)
            async with self._lock:
                pc = self._clients.get(uid)

            if pc is not None:
                # Tarmoq I/O lock TASHQARISIDA
                try:
                    if not pc.client.is_connected():
                        await asyncio.wait_for(
                            pc.client.connect(), timeout=CONNECT_TIMEOUT_S
                        )
                    if not await pc.client.is_user_authorized():
                        await self.remove(uid)
                        raise SessionInvalidError()
                    async with self._lock:
                        # Race himoyasi: pc'ni cleanup_loop idle deb evict
                        # qilgan bo'lishi mumkin. Hali ham aynan o'sha
                        # client bo'lsagina ishlatamiz; aks holda pastda
                        # yangi client yaratamiz.
                        current = self._clients.get(uid)
                        if current is pc:
                            pc.last_used = time.time()
                            pc.in_use = True
                            return pc.client
                    # pc evict qilingan — yangisini yaratishga o'tamiz (pastda)
                except (AuthKeyUnregisteredError, UserDeactivatedBanError):
                    await self.remove(uid)
                    raise SessionInvalidError()
                except (asyncio.TimeoutError, OSError):
                    # Vaqtinchalik muammo — eski clientni tozalaymiz,
                    # sessiyaga TEGMAYMIZ. Worker keyin qayta urinadi.
                    await self.remove(uid)
                    raise PoolBusyError()

            # 2) Yangi client kerak. Joy bormi? (qisqa lock)
            victim: PooledClient | None = None
            async with self._lock:
                if len(self._clients) >= self.max_clients:
                    victim = self._pop_idle_victim()
                    if victim is None:
                        # Barcha clientlar band — vaqtinchalik
                        raise PoolBusyError()

            # Evict qilingan idle clientni lock TASHQARISIDA yopamiz
            if victim is not None:
                await self._disconnect(victim)

            # Yangi clientni lock TASHQARISIDA ulaymiz
            client = TelegramClient(
                StringSession(session_string), self.api_id, self.api_hash
            )
            try:
                await asyncio.wait_for(client.connect(), timeout=CONNECT_TIMEOUT_S)
                if not await client.is_user_authorized():
                    with contextlib.suppress(Exception):
                        await client.disconnect()
                    raise SessionInvalidError()
            except (AuthKeyUnregisteredError, UserDeactivatedBanError):
                with contextlib.suppress(Exception):
                    await client.disconnect()
                raise SessionInvalidError()
            except (asyncio.TimeoutError, OSError):
                with contextlib.suppress(Exception):
                    await client.disconnect()
                raise PoolBusyError()

            async with self._lock:
                pc = PooledClient(uid=uid, client=client, in_use=True)
                self._clients[uid] = pc
            return client

    async def release(self, uid: int) -> None:
        """Clientni 'bo'sh' deb belgilash (boshqalar ishlatishi mumkin)."""
        async with self._lock:
            pc = self._clients.get(uid)
            if pc:
                pc.in_use = False
                pc.last_used = time.time()

    async def remove(self, uid: int) -> None:
        """Foydalanuvchi logout qilganda yoki sessiya bekor bo'lganda."""
        async with self._lock:
            pc = self._clients.pop(uid, None)
        # Disconnect lock TASHQARISIDA
        if pc:
            await self._disconnect(pc)
        # Ishlatilmayotgan uid lock'ni tozalaymiz (xotira tejash).
        # Agar lock hozir band bo'lsa (acquire ichidan chaqirilgan) — tegmaymiz.
        lock = self._uid_locks.get(uid)
        if lock is not None and not lock.locked():
            self._uid_locks.pop(uid, None)

    @property
    def active_count(self) -> int:
        """Hozir band (in_use) clientlar soni."""
        return sum(1 for pc in self._clients.values() if pc.in_use)

    @property
    def total_count(self) -> int:
        """Jami ulangan clientlar soni."""
        return len(self._clients)

    def stats(self) -> dict:
        """Pool statistikasi."""
        return {
            "total": self.total_count,
            "active": self.active_count,
            "idle": self.total_count - self.active_count,
            "max": self.max_clients,
        }

    # ─── Internal ────────────────────────────────────────────────────────

    async def _disconnect(self, pc: PooledClient) -> None:
        """Clientni xavfsiz disconnect qilish."""
        with contextlib.suppress(Exception):
            if pc.client.is_connected():
                await pc.client.disconnect()

    def _pop_idle_victim(self) -> PooledClient | None:
        """Eng eski idle clientni dict'dan olib tashlaydi va qaytaradi.

        self._lock ICHIDA chaqiriladi (sync — I/O yo'q). Disconnect
        chaqiruvchi tomonidan lock TASHQARISIDA bajariladi."""
        idle_clients = [
            (uid, pc) for uid, pc in self._clients.items() if not pc.in_use
        ]
        if not idle_clients:
            return None
        oldest_uid, _ = min(idle_clients, key=lambda x: x[1].last_used)
        return self._clients.pop(oldest_uid)

    async def _cleanup_loop(self) -> None:
        """Har 60 soniyada idle clientlarni va bo'sh uid lock'larni tozalash."""
        while True:
            await asyncio.sleep(60)
            now = time.time()
            to_disconnect: list[PooledClient] = []
            async with self._lock:
                to_remove = [
                    uid
                    for uid, pc in self._clients.items()
                    if not pc.in_use
                    and (now - pc.last_used) > CLIENT_IDLE_TIMEOUT_S
                ]
                for uid in to_remove:
                    to_disconnect.append(self._clients.pop(uid))
            # Disconnect lock TASHQARISIDA
            for pc in to_disconnect:
                await self._disconnect(pc)
            # Bo'sh (band emas, ulanmagan) uid lock'larni tozalaymiz
            for uid in list(self._uid_locks.keys()):
                lock = self._uid_locks.get(uid)
                if lock is not None and not lock.locked() and uid not in self._clients:
                    self._uid_locks.pop(uid, None)
