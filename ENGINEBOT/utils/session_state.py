"""
utils/session_state.py — per-user conversation state izolyatsiyasi.

MAQSAD:
───────
Bot bilan suhbat ko'p qadamli (masalan: yo'nalish → vaqt → narx).
Har foydalanuvchi o'z holatida turishi kerak — boshqasiga ta'sir
qilmasligi shart.

PRINSIPLAR:
───────────
1. PER-USER: dict[uid → state]. Bitta foydalanuvchi state'i —
   boshqasidan ajralgan.

2. PER-USER LOCK: ikki concurrent message bir userdan kelsa —
   serial qayta ishlanadi (race-free).

3. AUTO-EXPIRE: 5 daqiqa hech narsa qilmasa — state tozalanadi.
   Aks holda RAM tugaydi.

4. TYPED: SessionData dataclass — har step uchun field nomi aniq.

USAGE:
──────
    state = await session.get(uid)
    state.step = "asking_destination"
    state.data["from_city"] = "Toshkent"
    await session.set(uid, state)

    # Lock orqali atomic operatsiya:
    async with session.lock(uid):
        s = await session.get(uid)
        ...
        await session.set(uid, s)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from config import Limits

logger = logging.getLogger("enginebot.session")


# ─────────────────────────────────────────────────────────────────────
# SessionData — bitta foydalanuvchi state
# ─────────────────────────────────────────────────────────────────────
@dataclass
class SessionData:
    """
    Bitta foydalanuvchining hozirgi suhbat holati.

    step    : qaysi qadamda turibdi ("asking_phone", "confirming" va h.k.)
    data    : qadamlar davomida yig'ilgan ma'lumotlar (dict)
    tenant_id : qaysi tenant kontekstida (None = global)
    updated : oxirgi yangilanish (auto-expire uchun)
    """
    step: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    tenant_id: Optional[int] = None
    updated: float = field(default_factory=time.time)

    def touch(self) -> None:
        """Vaqtni yangilash (har set'da avtomatik chaqiriladi)."""
        self.updated = time.time()

    def reset(self) -> None:
        """Holatni tozalash (suhbat tugagan, /cancel bosilgan va h.k.)."""
        self.step = ""
        self.data.clear()
        self.tenant_id = None
        self.touch()

    def is_expired(self, timeout: int = Limits.SESSION_TIMEOUT_S) -> bool:
        return (time.time() - self.updated) > timeout


# ─────────────────────────────────────────────────────────────────────
# SessionStore — barcha userlar uchun
# ─────────────────────────────────────────────────────────────────────
class SessionStore:
    """In-memory per-user state. Bot restart'da tozalanadi (specifications)."""

    def __init__(self) -> None:
        self._states: Dict[int, SessionData] = {}
        self._locks: Dict[int, asyncio.Lock] = {}
        self._janitor_task: Optional[asyncio.Task] = None

    async def get(self, uid: int) -> SessionData:
        """User state'ini olish (yo'q bo'lsa yangi yaratadi)."""
        s = self._states.get(uid)
        if s is None:
            s = SessionData()
            self._states[uid] = s
        elif s.is_expired():
            # Eskirgan — yangi state qaytaramiz
            logger.debug(f"session expired for {uid}, resetting")
            s.reset()
        return s

    async def set(self, uid: int, state: SessionData) -> None:
        """User state'ini saqlash (vaqtni avtomatik yangilaydi)."""
        state.touch()
        self._states[uid] = state

    async def update(self, uid: int, **fields) -> SessionData:
        """State maydonlarini qisman yangilash (qulay shorthand)."""
        s = await self.get(uid)
        for k, v in fields.items():
            if k == "data" and isinstance(v, dict):
                s.data.update(v)
            else:
                setattr(s, k, v)
        s.touch()
        self._states[uid] = s
        return s

    async def reset(self, uid: int, *, keep_tenant: bool = False) -> None:
        """
        Userning state'ini tozalash.

        keep_tenant=True boʻlsa — tenant_id saqlanadi (foydalanuvchining
        tanlangan guruh kontekstidan chiqib ketmasligi uchun).
        """
        s = self._states.get(uid)
        if s:
            saved_tenant = s.tenant_id if keep_tenant else None
            s.reset()
            if saved_tenant is not None:
                s.tenant_id = saved_tenant
                s.touch()
        # Ehtiyojidan kelib chiqib, lock'ni saqlab qolamiz

    async def remove(self, uid: int) -> None:
        """Userni butunlay olib tashlash (logout)."""
        self._states.pop(uid, None)
        self._locks.pop(uid, None)

    def lock(self, uid: int) -> asyncio.Lock:
        """
        Bitta user uchun lock — concurrent xabarlarni serializatsiya qiladi.

        Misol:
            async with session.lock(uid):
                state = await session.get(uid)
                ...
                await session.set(uid, state)
        """
        lk = self._locks.get(uid)
        if lk is None:
            lk = asyncio.Lock()
            self._locks[uid] = lk
        return lk

    # ─── Janitor — eskirgan state'larni tozalash ─────────────────────
    async def _janitor_loop(self) -> None:
        """Har 60 soniyada eskirgan state'larni tozalaydi."""
        while True:
            try:
                await asyncio.sleep(60)
                expired = [
                    uid for uid, s in list(self._states.items()) if s.is_expired()
                ]
                for uid in expired:
                    self._states.pop(uid, None)
                    # lock'ni saqlab qolamiz — keyinchalik ishlatilishi mumkin
                if expired:
                    logger.debug(f"session janitor: cleaned {len(expired)} expired")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"session janitor error: {type(e).__name__}: {e}")

    def start_janitor(self) -> None:
        """Janitor taskini ishga tushirish (main.py'da chaqiriladi)."""
        if self._janitor_task is None or self._janitor_task.done():
            self._janitor_task = asyncio.create_task(
                self._janitor_loop(), name="session-janitor"
            )

    async def stop_janitor(self) -> None:
        if self._janitor_task and not self._janitor_task.done():
            self._janitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._janitor_task

    def stats(self) -> dict:
        return {
            "active_sessions": len(self._states),
            "active_locks": len(self._locks),
        }


# ─────────────────────────────────────────────────────────────────────
# Global instance
# ─────────────────────────────────────────────────────────────────────
session = SessionStore()
