"""Redis bilan ishlash (kesh, FSM, lock, rate-limit).

Muhim: Redis ishlamasa ham bot **yiqilmaydi** — kesh o'rniga xotira,
FSM o'rniga MemoryStorage ishlatiladi (dev rejim uchun qulay).
"""

from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis
from loguru import logger

from app.config import get_settings


class RedisManager:
    """Redis ulanishini boshqaradi va qulay o'ram (wrapper) beradi."""

    def __init__(self, url: str | None = None) -> None:
        self._url = url or get_settings().redis_url
        self._client: aioredis.Redis | None = None
        self.available: bool = False

    # ── Ulanish ───────────────────────────────────────────────
    async def connect(self) -> bool:
        """Ulanishni o'rnatish va ping bilan tekshirish."""
        try:
            self._client = aioredis.from_url(
                self._url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                health_check_interval=30,
            )
            await self._client.ping()
            self.available = True
            logger.info("Redis ulandi: {}", _mask(self._url))
        except Exception as exc:  # noqa: BLE001 — Redis ixtiyoriy komponent
            self.available = False
            self._client = None
            logger.warning("Redis ulanmadi ({}). Kesh/FSM xotirada ishlaydi.", exc)
        return self.available

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # pragma: no cover
                pass
        self._client = None
        self.available = False

    @property
    def client(self) -> aioredis.Redis | None:
        return self._client

    async def is_healthy(self) -> bool:
        if self._client is None:
            return False
        try:
            await self._client.ping()
            return True
        except Exception:
            return False

    # ── Qulay metodlar (xatoga chidamli) ──────────────────────
    async def get(self, key: str) -> str | None:
        if not self._client:
            return None
        try:
            return await self._client.get(key)
        except Exception as exc:  # pragma: no cover
            logger.debug("Redis GET xatosi ({}): {}", key, exc)
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        if not self._client:
            return False
        try:
            await self._client.set(key, value, ex=ttl)
            return True
        except Exception as exc:  # pragma: no cover
            logger.debug("Redis SET xatosi ({}): {}", key, exc)
            return False

    async def delete(self, *keys: str) -> int:
        if not self._client or not keys:
            return 0
        try:
            return await self._client.delete(*keys)
        except Exception:  # pragma: no cover
            return 0

    async def incr(self, key: str) -> int | None:
        if not self._client:
            return None
        try:
            return int(await self._client.incr(key))
        except Exception:  # pragma: no cover
            return None

    async def get_int(self, key: str) -> int | None:
        raw = await self.get(key)
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None


def _mask(url: str) -> str:
    """Log uchun manzildagi parolni yashirish."""
    if "@" in url and "//" in url:
        scheme, rest = url.split("//", 1)
        if "@" in rest:
            creds, host = rest.split("@", 1)
            user = creds.split(":", 1)[0]
            return f"{scheme}//{user}:***@{host}"
    return url


# Global menejer (app.main da connect() chaqiriladi)
redis_manager = RedisManager()


async def make_fsm_storage() -> Any:
    """FSM uchun storage: Redis bo'lsa — RedisStorage, aks holda MemoryStorage.

    Redis tanlanganda FSM holati server qayta yonganda ham saqlanib qoladi
    (e'lon qo'shish jarayoni yo'qolmaydi) — REJA.md 1.3/#9.
    """
    from aiogram.fsm.storage.memory import MemoryStorage

    settings = get_settings()
    if redis_manager.client is not None and redis_manager.available:
        try:
            from aiogram.fsm.storage.redis import RedisStorage

            storage = RedisStorage.from_url(
                settings.redis_url,
                connection_kwargs={"decode_responses": True},
            )
            logger.info("FSM: RedisStorage ishlatiladi (restartga chidamli)")
            return storage
        except Exception as exc:  # pragma: no cover
            logger.warning("RedisStorage yaratilmadi ({}), MemoryStorage ishlatiladi", exc)

    if not settings.dev_mode:
        logger.warning(
            "FSM: MemoryStorage ishlatiladi — server qayta yonsa, tugallanmagan "
            "jarayonlar (masalan e'lon qo'shish) yo'qoladi!"
        )
    return MemoryStorage()
