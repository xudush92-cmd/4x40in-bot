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

    async def acquire(self, uid: int, session_string: str) -> TelegramClient | None:
        """
        Client olish. Agar pool'da bo'lsa — qayta ishlatadi.
        Bo'lmasa — yangi yaratadi. Xatolik bo'lsa None qaytaradi.

        Returns:
            TelegramClient yoki None (sessiya yaroqsiz)
        """
        async with self._lock:
            pc = self._clients.get(uid)

            if pc is not None:
                # Mavjud clientni qayta ishlatish
                try:
                    if not pc.client.is_connected():
                        await asyncio.wait_for(
                            pc.client.connect(), timeout=CONNECT_TIMEOUT_S
                        )
                    if not await pc.client.is_user_authorized():
                        # Sessiya yaroqsiz — o'chiramiz
                        await self._disconnect(pc)
                        del self._clients[uid]
                        return None
                    pc.last_used = time.time()
                    pc.in_use = True
                    return pc.client
                except (AuthKeyUnregisteredError, UserDeactivatedBanError):
                    await self._disconnect(pc)
                    del self._clients[uid]
                    return None
                except (asyncio.TimeoutError, OSError):
                    # Ulanish muammo — qayta urinish uchun tozalaymiz
                    await self._disconnect(pc)
                    del self._clients[uid]
                    # Davom etib yangi yaratamiz (pastda)

            # Yangi client yaratish
            # Agar pool to'la bo'lsa — eng eski idle clientni yoqamiz
            if len(self._clients) >= self.max_clients:
                freed = await self._evict_idle()
                if not freed:
                    # Barcha clientlar band — kutish kerak
                    return None

            client = TelegramClient(
                StringSession(session_string), self.api_id, self.api_hash
            )
            try:
                await asyncio.wait_for(client.connect(), timeout=CONNECT_TIMEOUT_S)
                if not await client.is_user_authorized():
                    with contextlib.suppress(Exception):
                        await client.disconnect()
                    return None
            except (AuthKeyUnregisteredError, UserDeactivatedBanError):
                with contextlib.suppress(Exception):
                    await client.disconnect()
                return None
            except (asyncio.TimeoutError, OSError):
                with contextlib.suppress(Exception):
                    await client.disconnect()
                return None

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
            if pc:
                await self._disconnect(pc)

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

    async def _evict_idle(self) -> bool:
        """Eng uzoq idle turgan clientni o'chirish. True = joy ochildi."""
        idle_clients = [
            (uid, pc) for uid, pc in self._clients.items() if not pc.in_use
        ]
        if not idle_clients:
            return False

        # Eng eski idle clientni topamiz
        oldest_uid, oldest_pc = min(idle_clients, key=lambda x: x[1].last_used)
        await self._disconnect(oldest_pc)
        del self._clients[oldest_uid]
        return True

    async def _cleanup_loop(self) -> None:
        """Har 60 soniyada idle clientlarni tozalash."""
        while True:
            await asyncio.sleep(60)
            now = time.time()
            async with self._lock:
                to_remove = [
                    uid
                    for uid, pc in self._clients.items()
                    if not pc.in_use
                    and (now - pc.last_used) > CLIENT_IDLE_TIMEOUT_S
                ]
                for uid in to_remove:
                    pc = self._clients.pop(uid)
                    await self._disconnect(pc)
