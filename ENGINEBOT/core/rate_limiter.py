"""
core/rate_limiter.py — anti-spam va abuse himoya.

MAQSAD:
───────
Bitta foydalanuvchi juda koʻp soʻrov yuborib botni overload qilmasin,
yoki Telegram FloodWait ban yemasin.

ALGORITM: Sliding Window + Block
────────────────────────────────
Har action turi uchun:
  • max_actions  — vaqt oynasida ruxsat etilgan max amal
  • window_sec   — vaqt oynasi soniyada
  • block_sec    — limit buzilsa qancha vaqt bloklanadi

Limit buzilganda — foydalanuvchi block_sec gacha bloklanadi.
Qaysi action — qaysi limit:

  login    : 3 / 5 daq    (Telegram'dan ban yemaslik)
  command  : 30 / 1 daq   (UI komandalar)
  modify   : 20 / 1 daq   (post/chat qoʻshish)
  message  : 60 / 1 daq   (umumiy xabarlar)

PER-USER izolyatsiya: bitta userning limiti boshqaga taʼsir qilmaydi.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass

logger = logging.getLogger("enginebot.rate_limiter")


@dataclass(frozen=True)
class RateLimit:
    """Bitta cheklov qoidasi."""
    max_actions: int
    window_sec: int
    block_sec: int


# ─────────────────────────────────────────────────────────────────────
# Standart cheklovlar
# ─────────────────────────────────────────────────────────────────────
LIMITS: dict[str, RateLimit] = {
    "login":   RateLimit(max_actions=3,  window_sec=300, block_sec=600),
    "command": RateLimit(max_actions=30, window_sec=60,  block_sec=30),
    "modify":  RateLimit(max_actions=20, window_sec=60,  block_sec=60),
    "post":    RateLimit(max_actions=10, window_sec=60,  block_sec=120),
    "message": RateLimit(max_actions=60, window_sec=60,  block_sec=15),
}


# ─────────────────────────────────────────────────────────────────────
# RateLimiter
# ─────────────────────────────────────────────────────────────────────
class RateLimiter:
    """In-memory sliding-window rate limiter (per-user, per-action)."""

    def __init__(self) -> None:
        # {uid: {action: [ts1, ts2, ...]}}
        self._actions: dict[int, dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        # {uid: {action: block_until_ts}}
        self._blocks: dict[int, dict[str, float]] = defaultdict(dict)
        self._last_cleanup = time.time()

    def is_allowed(self, uid: int, action: str) -> bool:
        """
        Amal ruxsat etiladimi?

        True  — ruxsat (timestamp avtomatik qoʻshiladi)
        False — bloklangan yoki limit tugagan
        """
        now = time.time()

        # Har 5 daqiqada eski yozuvlarni tozalash
        if now - self._last_cleanup > 300:
            self._cleanup(now)
            self._last_cleanup = now

        # Bloklangan?
        block_until = self._blocks.get(uid, {}).get(action, 0)
        if now < block_until:
            return False

        limit = LIMITS.get(action)
        if limit is None:
            # Nomaʼlum action — cheklanmaydi
            return True

        # Eski timestamplarni tozalash
        timestamps = self._actions[uid][action]
        cutoff = now - limit.window_sec
        timestamps[:] = [t for t in timestamps if t > cutoff]

        # Limit tekshirish
        if len(timestamps) >= limit.max_actions:
            self._blocks[uid][action] = now + limit.block_sec
            logger.warning(
                f"rate limit hit: uid={uid} action={action} "
                f"({len(timestamps)}/{limit.max_actions} in {limit.window_sec}s)"
            )
            return False

        # Ruxsat — yangi timestamp qoʻshish
        timestamps.append(now)
        return True

    def get_wait_seconds(self, uid: int, action: str) -> int:
        """Bloklangan boʻlsa — qancha soniya kutish kerak (0 = ruxsat)."""
        now = time.time()
        block_until = self._blocks.get(uid, {}).get(action, 0)
        if now < block_until:
            return int(block_until - now) + 1
        return 0

    def reset(self, uid: int, action: str | None = None) -> None:
        """Foydalanuvchining cheklovini tozalash (admin tomonidan)."""
        if action:
            self._actions.get(uid, {}).pop(action, None)
            self._blocks.get(uid, {}).pop(action, None)
        else:
            self._actions.pop(uid, None)
            self._blocks.pop(uid, None)

    def stats(self) -> dict:
        """Umumiy statistika."""
        now = time.time()
        blocked = sum(
            1
            for blocks in self._blocks.values()
            for until in blocks.values()
            if now < until
        )
        return {
            "tracked_users": len(self._actions),
            "currently_blocked": blocked,
        }

    # ─── Internal ────────────────────────────────────────────────────
    def _cleanup(self, now: float) -> None:
        """Eski yozuvlarni tozalash (xotira tejash)."""
        # Eski actionlarni
        empty_uids = []
        for uid, actions in list(self._actions.items()):
            empty_actions = []
            for action, timestamps in list(actions.items()):
                limit = LIMITS.get(action)
                if limit:
                    cutoff = now - limit.window_sec
                    actions[action] = [t for t in timestamps if t > cutoff]
                    if not actions[action]:
                        empty_actions.append(action)
            for a in empty_actions:
                actions.pop(a, None)
            if not actions:
                empty_uids.append(uid)
        for uid in empty_uids:
            self._actions.pop(uid, None)

        # Eskirgan bloklarni
        empty_block_uids = []
        for uid, blocks in list(self._blocks.items()):
            expired = [a for a, until in list(blocks.items()) if now >= until]
            for a in expired:
                blocks.pop(a, None)
            if not blocks:
                empty_block_uids.append(uid)
        for uid in empty_block_uids:
            self._blocks.pop(uid, None)


# ─────────────────────────────────────────────────────────────────────
# Global instance
# ─────────────────────────────────────────────────────────────────────
limiter = RateLimiter()


# ─────────────────────────────────────────────────────────────────────
# Yordamchi: foydalanuvchiga koʻrsatiladigan xabar
# ─────────────────────────────────────────────────────────────────────
def get_block_message(uid: int, action: str) -> str | None:
    """Foydalanuvchi bloklangan boʻlsa, mos xabar qaytaradi."""
    wait = limiter.get_wait_seconds(uid, action)
    if wait <= 0:
        return None
    if wait < 60:
        return f"⏳ Juda koʻp soʻrov. {wait} soniya kuting."
    minutes = wait // 60
    return f"⏳ Juda koʻp soʻrov. {minutes} daqiqa kuting."
