"""
rate_limiter.py — Rate limiting va anti-abuse.

Har foydalanuvchi uchun vaqt oynasida max N ta amal cheklovini qo'yadi.
Spam, login spam va botni overload qilishdan himoya qiladi.

(AVTO_BOT dagi sinalgan versiya asosida.)
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class RateLimit:
    max_actions: int      # vaqt oynasida max amallar
    window_seconds: int   # vaqt oynasi (soniya)
    block_seconds: int    # cheklov buzilganda qancha vaqt bloklash


LIMITS = {
    # Buyruqlar (menyu tugmalari)
    "command": RateLimit(max_actions=30, window_seconds=60, block_seconds=30),
    # E'lon/viloyat o'zgartirish
    "modify": RateLimit(max_actions=20, window_seconds=60, block_seconds=60),
    # Umumiy xabarlar
    "message": RateLimit(max_actions=60, window_seconds=60, block_seconds=15),
}


class RateLimiter:
    """Foydalanuvchilar uchun rate limiting."""

    def __init__(self):
        self._actions: dict[int, dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._blocks: dict[int, dict[str, float]] = defaultdict(dict)
        self._last_cleanup = time.time()

    def is_allowed(self, uid: int, action: str) -> bool:
        now = time.time()

        if now - self._last_cleanup > 300:
            self._cleanup()
            self._last_cleanup = now

        block_until = self._blocks.get(uid, {}).get(action, 0)
        if now < block_until:
            return False

        limit = LIMITS.get(action)
        if limit is None:
            return True

        timestamps = self._actions[uid][action]
        cutoff = now - limit.window_seconds
        self._actions[uid][action] = [t for t in timestamps if t > cutoff]
        timestamps = self._actions[uid][action]

        if len(timestamps) >= limit.max_actions:
            self._blocks[uid][action] = now + limit.block_seconds
            return False

        timestamps.append(now)
        return True

    def get_wait_time(self, uid: int, action: str) -> int:
        now = time.time()
        block_until = self._blocks.get(uid, {}).get(action, 0)
        if now < block_until:
            return int(block_until - now) + 1
        return 0

    def reset(self, uid: int, action: str | None = None) -> None:
        if action:
            self._actions[uid].pop(action, None)
            self._blocks.get(uid, {}).pop(action, None)
        else:
            self._actions.pop(uid, None)
            self._blocks.pop(uid, None)

    def stats(self) -> dict:
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
        now = time.time()

        empty_uids = []
        for uid, actions in list(self._actions.items()):
            empty_actions = []
            for action, timestamps in list(actions.items()):
                limit = LIMITS.get(action)
                if limit:
                    cutoff = now - limit.window_seconds
                    actions[action] = [t for t in timestamps if t > cutoff]
                    if not actions[action]:
                        empty_actions.append(action)
            for a in empty_actions:
                actions.pop(a, None)
            if not actions:
                empty_uids.append(uid)
        for uid in empty_uids:
            self._actions.pop(uid, None)

        empty_block_uids = []
        for uid, blocks in list(self._blocks.items()):
            expired = [a for a, until in list(blocks.items()) if now >= until]
            for a in expired:
                blocks.pop(a, None)
            if not blocks:
                empty_block_uids.append(uid)
        for uid in empty_block_uids:
            self._blocks.pop(uid, None)
