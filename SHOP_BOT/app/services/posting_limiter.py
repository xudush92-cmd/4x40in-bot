"""Post yuborishda guruh va bot bo'yicha xabar sonini cheklash.

Redis borida ikkala token bucket BIR Lua chaqiruvda atomar band qilinadi
(ko'p poster process uchun). Redis bo'lmasa dev muhitida xotira cheklovi;
guruhni ikki marta post qilishdan DB claim baribir himoya qiladi.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from loguru import logger

from app.constants import GROUP_RATE_MIN_GAP_SEC
from app.redis_client import redis_manager

# Telegram: guruhga taxminan 20 xabar/daq, botga ~30 xabar/sek.
GROUP_CAPACITY = 20.0
GROUP_PER_MS = GROUP_CAPACITY / 60_000
GLOBAL_CAPACITY = 25.0
GLOBAL_PER_MS = GLOBAL_CAPACITY / 1_000

_RESERVE_LUA = """
local now_pair = redis.call('TIME')
local now = tonumber(now_pair[1]) * 1000 + math.floor(tonumber(now_pair[2]) / 1000)
local cost = tonumber(ARGV[1])
local gap = tonumber(ARGV[2])
local global = redis.call('HMGET', KEYS[1], 'tokens', 'at', 'last')
local group = redis.call('HMGET', KEYS[2], 'tokens', 'at', 'last')
local gt = math.min(25, tonumber(global[1] or 25) + math.max(0, now - tonumber(global[2] or now)) * 0.025)
local ct = math.min(20, tonumber(group[1] or 20) + math.max(0, now - tonumber(group[2] or now)) / 3000)
local wait_global = math.max(0, (cost - gt) / 0.025)
local wait_group = math.max(0, (cost - ct) * 3000)
local wait_gap = math.max(0, tonumber(group[3] or 0) + gap - now)
local wait = math.max(wait_global, wait_group, wait_gap)
if wait > 0 then return math.ceil(wait) end
redis.call('HSET', KEYS[1], 'tokens', gt - cost, 'at', now, 'last', now)
redis.call('HSET', KEYS[2], 'tokens', ct - cost, 'at', now, 'last', now)
redis.call('PEXPIRE', KEYS[1], 120000)
redis.call('PEXPIRE', KEYS[2], 120000)
return 0
"""


@dataclass
class _Bucket:
    tokens: float
    at: float
    last: float = 0.0


class PostingRateLimiter:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._global = _Bucket(GLOBAL_CAPACITY, time.monotonic())
        self._groups: dict[int, _Bucket] = {}

    async def _local_reserve(self, chat_id: int, cost: int) -> float:
        """Xotiradagi ikki bucket uchun umumiy atomar qaror; kutish sekundda."""
        async with self._lock:
            now = time.monotonic()
            global_bucket = self._global
            group = self._groups.setdefault(chat_id, _Bucket(GROUP_CAPACITY, now))
            gt = min(GLOBAL_CAPACITY, global_bucket.tokens + max(0, now - global_bucket.at) * 25)
            ct = min(GROUP_CAPACITY, group.tokens + max(0, now - group.at) * (GROUP_CAPACITY / 60))
            wait = max(
                max(0.0, cost - gt) / 25,
                max(0.0, cost - ct) / (GROUP_CAPACITY / 60),
                max(0.0, group.last + GROUP_RATE_MIN_GAP_SEC - now) if group.last else 0.0,
            )
            if wait:
                return wait
            global_bucket.tokens, global_bucket.at = gt - cost, now
            group.tokens, group.at, group.last = ct - cost, now, now
            return 0.0

    async def acquire(self, chat_id: int, cost: int = 1) -> None:
        """1..10 elementli albom bir nechta xabar hisoblanadi.

        Kutish tranzaksiyadan TASHQARIDA amalga oshiriladi. Abort qilingan
        so'rov ham token yutishi mumkin (xavfsiz tomonga xato).
        """
        cost = max(1, min(20, int(cost)))
        while True:
            client = redis_manager.client if redis_manager.available else None
            if client is not None:
                try:
                    wait_ms = int(await client.eval(
                        _RESERVE_LUA, 2,
                        "shopbot:post:global", f"shopbot:post:group:{chat_id}",
                        cost, round(GROUP_RATE_MIN_GAP_SEC * 1000),
                    ))
                    wait = wait_ms / 1000
                except Exception as exc:
                    logger.warning("Post limiter Redis xatosi; lokal rejim: {}", exc)
                    wait = await self._local_reserve(chat_id, cost)
            else:
                wait = await self._local_reserve(chat_id, cost)
            if wait <= 0:
                return
            await asyncio.sleep(wait)


posting_limiter = PostingRateLimiter()
