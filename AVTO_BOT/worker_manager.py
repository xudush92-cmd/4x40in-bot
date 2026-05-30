"""
worker_manager.py — Worker boshqaruvchi (Posting tasklar).

Muammo: Cheksiz worker yaratish — RAM tugaydi, CPU overload.

Yechim: WorkerManager — bir vaqtda max N ta worker ishlashini
ta'minlaydi, ortiqchasi queue'da kutadi. Graceful shutdown —
SIGTERM/SIGINT signalida barcha workerlar xavfsiz to'xtaydi.

Afzalliklari:
- Max concurrent workers limit (server overload oldini olish)
- Graceful shutdown (data yo'qolmaydi)
- Worker lifecycle monitoring (start/stop/crash logging)
- Race-free start/stop (stopping state — yangi worker yaratishni bloklaydi)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable

logger = logging.getLogger("AvtoBot")

# ─────────────────────────────────────────────────────────────────────────
# KONFIGURATSIYA
# ─────────────────────────────────────────────────────────────────────────
# MAX_CONCURRENT_WORKERS — bir vaqtda max ishlaydigan workerlar (= faol userlar).
# HISOB (1 GB RAM EC2 Free Tier):
#   Jami RAM 1024 MB − tizim ~200 MB = ~824 MB bo'sh.
#   Har faol user (Telethon client) ~20 MB → 824/20 ≈ 41 nazariy maksimal.
#   Xavfsizlik zaxirasi (zaxira RAM, OOM oldini olish) → 35.
# Limitга yetganda 36-chi user "Tizim band, kuting" xabarini oladi (OOM emas).
# Server RAM ko'paysa (2 GB→75, 4 GB→150) bu qiymatni oshirish mumkin.
MAX_CONCURRENT_WORKERS = 35
WORKER_STOP_TIMEOUT_S = 15      # worker to'xtashi uchun kutish vaqti


@dataclass
class WorkerInfo:
    """Bitta worker haqida ma'lumot."""
    uid: int
    task: asyncio.Task
    stop_event: asyncio.Event
    started_at: float = field(default_factory=time.time)
    stopping: bool = False  # True bo'lsa, yangi start_worker bloklanadi


class WorkerManager:
    """Posting workerlarni boshqaruvchi."""

    def __init__(
        self,
        max_workers: int = MAX_CONCURRENT_WORKERS,
        worker_factory: Callable[[int, asyncio.Event], Awaitable[None]] | None = None,
    ):
        self.max_workers = max_workers
        self._worker_factory = worker_factory
        self._workers: dict[int, WorkerInfo] = {}
        self._shutting_down = False
        self._shutdown_event = asyncio.Event()
        # Worker yaratish/o'chirishda race oldini olish uchun
        self._lock = asyncio.Lock()

    def set_worker_factory(self, factory: Callable[[int, asyncio.Event], Awaitable[None]]) -> None:
        """Worker yaratish funksiyasini sozlash (posting_loop)."""
        self._worker_factory = factory

    @property
    def active_count(self) -> int:
        """Hozir ishlaydigan workerlar soni (stopping ham hisoblanadi)."""
        return len(self._workers)

    @property
    def is_shutting_down(self) -> bool:
        return self._shutting_down

    def is_running(self, uid: int) -> bool:
        """
        Foydalanuvchining workeri faol ishlamoqdami?
        Stopping yoki done bo'lsa False.
        """
        wi = self._workers.get(uid)
        if wi is None:
            return False
        if wi.stopping:
            return False
        if wi.task.done():
            return False
        return True

    async def start_worker(self, uid: int) -> bool:
        """
        Worker boshlash.
        Returns: True = boshlandi, False = limit yoki allaqachon ishlayapti
        """
        async with self._lock:
            if self._shutting_down:
                return False

            existing = self._workers.get(uid)
            if existing is not None:
                # Mavjud worker bor — stopping bo'lsa kutib turamiz
                if existing.stopping:
                    # Stop tugashini lock tashqarisida kutamiz
                    pass
                elif not existing.task.done():
                    # Hali ishlamoqda — qayta start kerak emas
                    return True
                else:
                    # Done bo'lib qolgan, lekin pop bo'lmagan — tozalaymiz
                    self._workers.pop(uid, None)

            # Stopping holatidagi worker tugashini lock tashqarisida kutamiz
            if existing is not None and existing.stopping:
                # Lock-ni vaqtincha bo'shatish — stop_worker tugashi uchun
                pass

        # Stopping worker tugashini kutamiz (lock'siz, deadlockni oldini olish)
        if uid in self._workers and self._workers[uid].stopping:
            wi = self._workers[uid]
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(wi.task, timeout=WORKER_STOP_TIMEOUT_S)

        async with self._lock:
            if self._shutting_down:
                return False

            # Stopping yakunlanganidan keyin tozalaymiz
            existing = self._workers.get(uid)
            if existing is not None and (existing.stopping or existing.task.done()):
                self._workers.pop(uid, None)
            elif existing is not None:
                # Boshqa thread tomonidan qayta yaratilgan
                return True

            if len(self._workers) >= self.max_workers:
                logger.warning(f"⚠️ Worker limit ({self.max_workers}) — {uid} boshlab bo'lmaydi")
                return False

            if self._worker_factory is None:
                logger.error("❌ Worker factory sozlanmagan!")
                return False

            stop_event = asyncio.Event()
            task = asyncio.create_task(
                self._run_worker(uid, stop_event),
                name=f"worker-{uid}",
            )
            self._workers[uid] = WorkerInfo(
                uid=uid, task=task, stop_event=stop_event
            )
            logger.info(f"🟢 Worker boshlandi: {uid} (jami: {self.active_count})")
            return True

    async def stop_worker(self, uid: int) -> bool:
        """
        Worker to'xtatish (graceful, race-safe).
        Returns: True = to'xtatildi, False = topilmadi
        """
        async with self._lock:
            wi = self._workers.get(uid)
            if wi is None or wi.stopping:
                return False
            wi.stopping = True
            wi.stop_event.set()
            task = wi.task

        # Lock tashqarisida task tugashini kutamiz
        try:
            await asyncio.wait_for(task, timeout=WORKER_STOP_TIMEOUT_S)
        except asyncio.TimeoutError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            logger.warning(f"⚠️ Worker {uid} force-cancel (timeout)")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"💥 Worker {uid} stop xato: {type(e).__name__}: {e}")

        # _run_worker finally allaqachon pop qilgan, lekin defensive
        async with self._lock:
            self._workers.pop(uid, None)

        logger.info(f"🔴 Worker to'xtatildi: {uid} (jami: {self.active_count})")
        return True

    async def stop_all(self) -> None:
        """Barcha workerlarni graceful to'xtatish."""
        async with self._lock:
            self._shutting_down = True
            uids = list(self._workers.keys())
            tasks: list[asyncio.Task] = []
            for uid in uids:
                wi = self._workers.get(uid)
                if wi and not wi.stopping:
                    wi.stopping = True
                    wi.stop_event.set()
                    tasks.append(wi.task)

        if not tasks:
            return

        logger.info(f"🛑 {len(tasks)} ta worker to'xtatilmoqda...")

        done, pending = await asyncio.wait(tasks, timeout=WORKER_STOP_TIMEOUT_S)
        for t in pending:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t

        async with self._lock:
            self._workers.clear()
        logger.info("✅ Barcha workerlar to'xtatildi")

    async def shutdown(self) -> None:
        """To'liq shutdown — signal handler uchun."""
        await self.stop_all()
        self._shutdown_event.set()

    async def wait_shutdown(self) -> None:
        """Shutdown signalini kutish."""
        await self._shutdown_event.wait()

    def setup_signals(self) -> None:
        """
        SIGTERM/SIGINT uchun graceful shutdown sozlash.
        async kontekstda chaqirilishi kutiladi (main() ichida).
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Running loop yo'q (sinov yoki Windows) — signal handler
            # sozlamasdan tinch chiqamiz
            return

        def _handle_signal(sig):
            logger.info(f"📡 Signal qabul qilindi: {sig.name}")
            asyncio.create_task(self.shutdown())

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, lambda s=sig: _handle_signal(s))
            except (NotImplementedError, RuntimeError):
                # Windows yoki cheklangan loop — pass
                pass

    def stats(self) -> dict:
        """Worker statistikasi."""
        now = time.time()
        workers_info = []
        for uid, wi in self._workers.items():
            workers_info.append({
                "uid": uid,
                "uptime_s": int(now - wi.started_at),
                "running": not wi.task.done(),
                "stopping": wi.stopping,
            })
        return {
            "active": self.active_count,
            "max": self.max_workers,
            "shutting_down": self._shutting_down,
            "workers": workers_info,
        }

    # ─── Internal ────────────────────────────────────────────────────────

    async def _run_worker(self, uid: int, stop_event: asyncio.Event) -> None:
        """Worker wrapper — crash bo'lsa log qiladi va tozalaydi."""
        try:
            await self._worker_factory(uid, stop_event)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"💥 Worker {uid} crash: {type(e).__name__}: {e}")
        finally:
            # Worker tugaganda — ro'yxatdan o'chirish (lock olishga
            # ehtiyoj yo'q, dict.pop atomic)
            self._workers.pop(uid, None)
