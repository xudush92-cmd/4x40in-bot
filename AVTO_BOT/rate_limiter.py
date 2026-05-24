"""
rate_limiter.py — Rate limiting va anti-abuse.

Muammo: Bitta foydalanuvchi juda ko'p buyruq yuborishi,
login spamm qilishi yoki botni overload qilishi mumkin.

Yechim: RateLimiter — har foydalanuvchi uchun vaqt oynasida
max N ta amal (action) cheklovini qo'yadi.

Afzalliklari:
- Spam oldini olish (login, start/stop, post qo'shish)
- Telegram FloodWait'dan himoya (bot tezligini nazorat)
- Xotirada yengil (faqat timestamplar saqlanadi)
- Avtomatik tozalash (eski yozuvlar o'chiriladi)
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class RateLimit:
    """Bitta cheklov qoidasi."""
    max_actions: int      # vaqt oynasida max amallar
    window_seconds: int   # vaqt oynasi (soniya)
    block_seconds: int    # cheklov buzilganda qancha vaqt bloklash


# ─────────────────────────────────────────────────────────────────────────
# STANDART CHEKLOVLAR
# ─────────────────────────────────────────────────────────────────────────
LIMITS = {
    # Login — juda ko'p urinish Telegram'dan ban oladi
    "login": RateLimit(max_actions=3, window_seconds=300, block_seconds=600),

    # Buyruqlar (start, stop, status va h.k.)
    "command": RateLimit(max_actions=30, window_seconds=60, block_seconds=30),

    # Post/chat qo'shish
    "modify": RateLimit(max_actions=20, window_seconds=60, block_seconds=60),

    # Umumiy xabarlar
    "message": RateLimit(max_actions=60, window_seconds=60, block_seconds=15),
}


class RateLimiter:
    """Foydalanuvchilar uchun rate limiting."""

    def __init__(self):
        # {uid: {action_type: [timestamp, timestamp, ...]}}
        self._actions: dict[int, dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        # {uid: {action_type: block_until_timestamp}}
        self._blocks: dict[int, dict[str, float]] = defaultdict(dict)
        self._last_cleanup = time.time()

    def is_allowed(self, uid: int, action: str) -> bool:
        """
        Amal ruxsat etiladimi?
        True = ruxsat, False = cheklangan (juda ko'p)
        """
        now = time.time()

        # Har 5 daqiqada eski yozuvlarni tozalash
        if now - self._last_cleanup > 300:
            self._cleanup()
            self._last_cleanup = now

        # Bloklangan?
        block_until = self._blocks.get(uid, {}).get(action, 0)
        if now < block_until:
            return False

        limit = LIMITS.get(action)
        if limit is None:
            return True  # noma'lum action — cheklanmaydi

        # Eski timestamplarni tozalash (oynadan tashqaridagilar)
        timestamps = self._actions[uid][action]
        cutoff = now - limit.window_seconds
        self._actions[uid][action] = [t for t in timestamps if t > cutoff]
        timestamps = self._actions[uid][action]

        # Limit tekshirish
        if len(timestamps) >= limit.max_actions:
            # Bloklash
            self._blocks[uid][action] = now + limit.block_seconds
            return False

        # Ruxsat — yangi timestamp qo'shish
        timestamps.append(now)
        return True

    def get_wait_time(self, uid: int, action: str) -> int:
        """Agar bloklangan bo'lsa — qancha soniya kutish kerak. 0 = ruxsat."""
        now = time.time()
        block_until = self._blocks.get(uid, {}).get(action, 0)
        if now < block_until:
            return int(block_until - now) + 1
        return 0

    def reset(self, uid: int, action: str | None = None) -> None:
        """Foydalanuvchining cheklovlarini tozalash."""
        if action:
            self._actions[uid].pop(action, None)
            self._blocks.get(uid, {}).pop(action, None)
        else:
            self._actions.pop(uid, None)
            self._blocks.pop(uid, None)

    def stats(self) -> dict:
        """Umumiy statistika."""
        now = time.time()
        blocked_count = sum(
            1
            for uid_blocks in self._blocks.values()
            for until in uid_blocks.values()
            if now < until
        )
        return {
            "tracked_users": len(self._actions),
            "currently_blocked": blocked_count,
        }

    def _cleanup(self) -> None:
        """Eski yozuvlarni tozalash (xotira tejash)."""
        now = time.time()

        # Eski actionlarni tozalash
        empty_uids = []
        for uid, actions in self._actions.items():
            empty_actions = []
            for action, timestamps in actions.items():
                limit = LIMITS.get(action)
                if limit:
                    cutoff = now - limit.window_seconds
                    actions[action] = [t for t in timestamps if t > cutoff]
                    if not actions[action]:
                        empty_actions.append(action)
            for a in empty_actions:
                del actions[a]
            if not actions:
                empty_uids.append(uid)
        for uid in empty_uids:
            del self._actions[uid]

        # Eskirgan bloklarni tozalash
        empty_block_uids = []
        for uid, blocks in self._blocks.items():
            expired = [a for a, until in blocks.items() if now >= until]
            for a in expired:
                del blocks[a]
            if not blocks:
                empty_block_uids.append(uid)
        for uid in empty_block_uids:
            del self._blocks[uid]
