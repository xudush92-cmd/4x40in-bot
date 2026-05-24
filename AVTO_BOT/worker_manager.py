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
- Auto-restart crashed workers
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
MAX_CONCURRENT_WORKERS = 100     # bir vaqtda max ishlaydigan workerlar
WORKER_STOP_TIMEOUT_S = 15      # worker to'xtashi uchun kutish vaqti


@dataclass
class WorkerInfo:
    """Bitta worker haqida ma'lumot."""
    uid: int
    task: asyncio.Task
    stop_event: asyncio.Event
    started_at: float = field(default_factory=time.time)


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

    def set_worker_factory(self, factory: Callable[[int, asyncio.Event], Awaitable[None]]) -> None:
        """Worker yaratish funksiyasini sozlash (posting_loop)."""
        self._worker_factory = factory

    @property
    def active_count(self) -> int:
        """Hozir ishlaydigan workerlar soni."""
        return len(self._workers)

    @property
    def is_shutting_down(self) -> bool:
        return self._shutting_down

    def is_running(self, uid: int) -> bool:
        """Foydalanuvchining workeri ishlamoqdami?"""
        return uid in self._workers

    async def start_worker(self, uid: int) -> bool:
        """
        Worker boshlash. 
        Returns: True = boshlandi, False = limit yoki allaqachon ishlayapti
        """
        if self._shutting_down:
            return False

        if uid in self._workers:
            return True  # allaqachon ishlayapti

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
        self._workers[uid] = WorkerInfo(uid=uid, task=task, stop_event=stop_event)
        logger.info(f"🟢 Worker boshlandi: {uid} (jami: {self.active_count})")
        return True

    async def stop_worker(self, uid: int) -> bool:
        """
        Worker to'xtatish (graceful).
        Returns: True = to'xtatildi, False = topilmadi
        """
        wi = self._workers.pop(uid, None)
        if wi is None:
            return False

        wi.stop_event.set()
        try:
            await asyncio.wait_for(wi.task, timeout=WORKER_STOP_TIMEOUT_S)
        except asyncio.TimeoutError:
            wi.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await wi.task
            logger.warning(f"⚠️ Worker {uid} force-cancel (timeout)")
        except asyncio.CancelledError:
            pass

        logger.info(f"🔴 Worker to'xtatildi: {uid} (jami: {self.active_count})")
        return True

    async def stop_all(self) -> None:
        """Barcha workerlarni graceful to'xtatish."""
        self._shutting_down = True
        uids = list(self._workers.keys())

        if not uids:
            return

        logger.info(f"🛑 {len(uids)} ta worker to'xtatilmoqda...")

        # Barcha stop eventlarni set qilamiz
        for uid in uids:
            wi = self._workers.get(uid)
            if wi:
                wi.stop_event.set()

        # Barcha tasklarning tugashini kutamiz
        tasks = [self._workers[uid].task for uid in uids if uid in self._workers]
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=WORKER_STOP_TIMEOUT_S)
            for t in pending:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t

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
        """SIGTERM/SIGINT uchun graceful shutdown sozlash."""
        loop = asyncio.get_event_loop()

        def _handle_signal(sig):
            logger.info(f"📡 Signal qabul qilindi: {sig.name}")
            asyncio.create_task(self.shutdown())

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, lambda s=sig: _handle_signal(s))
            except (NotImplementedError, RuntimeError):
                # Windows'da signal handler ishlamaydi
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
            # Worker tugaganda — ro'yxatdan o'chirish
            self._workers.pop(uid, None)
