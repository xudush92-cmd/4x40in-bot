"""Global sozlamalar servisi: DB + kesh + Redis versiya.

Maqsad (REJA.md "asosiy qoida"): admin panelda sozlama o'zgartirilganda u
**darhol** kuchga kiradi, botni qayta yoqish shart emas.

Ishlash tartibi:
  1. Sozlamalar DB'da (`settings` jadvali) saqlanadi.
  2. Process xotirada snapshot saqlaydi.
  3. O'zgarishda Redis'dagi `settings:version` oshadi → barcha processlar
     (bot, poster) 15 sekund ichida yangi qiymatni ko'radi.
  4. Redis bo'lmasa ham 15 sekundlik TTL kafolat beradi.
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import GroupFeature, RedisKey
from app.db.base import session_scope
from app.db.models import ActionLog, Setting
from app.redis_client import redis_manager

# Standart qiymatlar — DB'da yo'q bo'lsa ishlatiladi
DEFAULTS: dict[str, Any] = {
    # Xavfsizlik / umumiy
    "kill_switch": False,            # 🛑 hamma narsani to'xtatish
    "maintenance_mode": False,       # faqat adminlar ishlaydi
    "support_contact": "@admin",
    "timezone": "Asia/Tashkent",
    # Funksiyalarning global kalitlari (guruh sozlamasi ustidan turadi)
    "posting_enabled_global": True,
    "counter_enabled_global": True,
    "guard_enabled_global": True,
    "cleaner_enabled_global": True,
    "welcome_enabled_global": True,
    # Joylash
    "default_interval_sec": 1800,
    "default_jitter_percent": 10,
    "default_daily_post_limit": 50,
    "min_interval_sec": 60,
    # Sotuvchi / obuna (Phase 2)
    "bot_username": "",                # @username — referal havolasi uchun (Phase 8)
    "subscription_reminder_days": 3,   # muddati tugashidan necha kun oldin eslatma
    "subscription_grace_days": 0,      # muddati o'tgach necha kun "grace" holatida turadi
    # Moderatsiya / limitlar
    "moderation_required_default": False,
    "default_max_photos": 3,
    "default_max_ads": 5,
    "receipt_required": True,        # chek rasmini majburiy qilish
    "receipt_duplicate_check": True,
    # Referal
    "referral_enabled": False,
    # Xizmat
    "log_retention_days": 90,
    "broadcast_rate_per_sec": 25,
    "warn_first_delay_sec": 300,     # yangi a'zo necha sekunddan keyin ogohlantiriladi
}

# Funksiya kaliti → global sozlamadagi kalit
FEATURE_SETTING_KEYS: dict[str, str] = {
    GroupFeature.POSTING: "posting_enabled_global",
    GroupFeature.COUNTER: "counter_enabled_global",
    GroupFeature.GUARD: "guard_enabled_global",
    GroupFeature.CLEANER: "cleaner_enabled_global",
    GroupFeature.WELCOME: "welcome_enabled_global",
}

_CACHE_TTL_SEC = 15.0


class SettingsService:
    """Keshlangan global sozlamalar."""

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._version: int | None = None
        self._last_check: float = 0.0
        self._loaded: bool = False

    # ── Ichki ─────────────────────────────────────────────────
    async def _load_from_db(self, session: AsyncSession | None = None) -> dict[str, Any]:
        data = dict(DEFAULTS)
        if session is not None:
            rows = (await session.execute(select(Setting))).scalars().all()
        else:
            async with session_scope() as own_session:
                rows = (await own_session.execute(select(Setting))).scalars().all()
        for row in rows:
            data[row.key] = row.value
        return data

    async def _maybe_refresh(self, session: AsyncSession | None = None) -> None:
        """Versiya o'zgargan yoki TTL o'tgan bo'lsa — qayta yuklash."""
        if not self._loaded:
            self._cache = await self._load_from_db(session)
            self._loaded = True
            self._version = await redis_manager.get_int(RedisKey.SETTINGS_VERSION)
            self._last_check = time.monotonic()
            return

        now = time.monotonic()
        if now - self._last_check < _CACHE_TTL_SEC:
            return

        self._last_check = now
        redis_version = await redis_manager.get_int(RedisKey.SETTINGS_VERSION)
        if redis_version is not None and redis_version != self._version:
            self._cache = await self._load_from_db(session)
            self._version = redis_version
            logger.info("Global sozlamalar yangilandi (versiya {})", redis_version)
        elif redis_version is None:
            # Redis yo'q — TTL bo'yicha yangilaymiz (baribir 15 sekundda)
            self._cache = await self._load_from_db(session)

    # ── Ommaviy API ───────────────────────────────────────────
    async def get_all(self, session: AsyncSession | None = None) -> dict[str, Any]:
        await self._maybe_refresh(session)
        return dict(self._cache)

    async def get(self, key: str, default: Any = None, session: AsyncSession | None = None) -> Any:
        await self._maybe_refresh(session)
        if key in self._cache:
            return self._cache[key]
        return DEFAULTS.get(key, default)

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        await self._maybe_refresh(None)
        return {k: self._cache.get(k, DEFAULTS.get(k)) for k in keys}

    async def set(
        self,
        session: AsyncSession,
        key: str,
        value: Any,
        *,
        updated_by: int | None = None,
        comment: str | None = None,
    ) -> None:
        """Sozlamani yozish va keshni darhol yangilash (versiyani oshirish)."""
        row = await session.get(Setting, key)
        before = row.value if row else DEFAULTS.get(key)
        if row is None:
            row = Setting(key=key, value=value, updated_by=updated_by, comment=comment)
            session.add(row)
        else:
            row.value = value
            row.updated_by = updated_by
            if comment is not None:
                row.comment = comment
        if key in {"counter_enabled_global", "guard_enabled_global", "cleaner_enabled_global", "kill_switch", "maintenance_mode"} and before != value:
            session.add(ActionLog(actor_id=updated_by, action="global_policy_switch",
                                  entity="setting", before={key: before}, after={key: value}))
        await session.flush()

        # Keshni darhol yangilash + boshqa processlarga xabar berish
        self._cache[key] = value
        await redis_manager.incr(RedisKey.SETTINGS_VERSION)
        logger.info("Sozlama o'zgardi: {} = {} (admin {})", key, value, updated_by)

    async def is_feature_enabled(self, feature: str | GroupFeature) -> bool:
        """Funksiya global darajada yoqilganmi (kill switch hisobga olinadi)."""
        await self._maybe_refresh(None)
        if self._cache.get("kill_switch", False):
            return False
        key = FEATURE_SETTING_KEYS.get(str(feature), f"{feature}_enabled_global")
        return bool(self._cache.get(key, DEFAULTS.get(key, True)))

    async def is_feature_enabled_fresh(self, feature: str | GroupFeature) -> bool:
        """Telegram amali oldidan DB'dan xavfsizlik switch'ini bevosita o'qish.

        Oddiy kesh ko'pi bilan 15 sekund kechikishi mumkin; favqulodda
        global pauza/mode shu oynada ham xabar o'chirmasligi kerak.
        """
        keys = ["kill_switch", "maintenance_mode", FEATURE_SETTING_KEYS.get(
            str(feature), f"{feature}_enabled_global"
        )]
        async with session_scope() as session:
            rows = (await session.execute(select(Setting).where(Setting.key.in_(keys)))).scalars().all()
        values = {row.key: row.value for row in rows}
        return not bool(values.get("kill_switch", DEFAULTS["kill_switch"])) and not bool(
            values.get("maintenance_mode", DEFAULTS["maintenance_mode"])
        ) and bool(values.get(keys[2], DEFAULTS.get(keys[2], True)))

    async def is_kill_switch_on(self) -> bool:
        return bool(await self.get("kill_switch", False))

    def invalidate(self) -> None:
        """Keshni majburiy tashlab yuborish (testlar/admin amali uchun)."""
        self._loaded = False
        self._last_check = 0.0


# Global nusxa
settings_service = SettingsService()
