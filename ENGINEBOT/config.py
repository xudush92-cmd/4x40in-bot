"""
config.py — markaziy sozlamalar va konstantalar.

Bu modulda atrof-muhit oʻzgaruvchilarini oʻqish va loyiha boʻylab
ishlatiladigan barcha konstantalar joylashgan. Hech qaysi modul
oʻz konstantalarini alohida elon qilmaydi — hammasi shu yerda.

Konstantalar 4 turga boʻlinadi:
1. ENV oʻzgaruvchilari (sirli) — token, ID, parollar
2. Limitlar — tarif boʻyicha cheklovlar
3. Aylanish (rotation) — vaqt va interval default qiymatlari
4. Tizim — DB yoʻli, log darajasi, port
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────────────
# .env yuklash
# ─────────────────────────────────────────────────────────────────────
# Loyiha ildizidagi .env'ni qidiramiz (config.py qayerda boʻlsa ham).
_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")


def _require_env(name: str) -> str:
    """Majburiy ENV oʻzgaruvchisini olish, yoʻq boʻlsa xatolik."""
    val = os.getenv(name, "").strip()
    if not val:
        raise RuntimeError(
            f"Majburiy ENV oʻzgaruvchisi yoʻq: {name}\n"
            f".env faylini tekshiring (.env.example dan nusxa oling)."
        )
    return val


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        raise RuntimeError(f"ENV {name} butun son boʻlishi kerak, hozir: {val!r}")


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


# ─────────────────────────────────────────────────────────────────────
# 1. ENV oʻzgaruvchilari (MAJBURIY)
# ─────────────────────────────────────────────────────────────────────
BOT_TOKEN: Final[str] = _require_env("BOT_TOKEN")
SUPER_ADMIN_ID: Final[int] = int(_require_env("SUPER_ADMIN_ID"))


# ─────────────────────────────────────────────────────────────────────
# 2. Tizim sozlamalari
# ─────────────────────────────────────────────────────────────────────
DB_PATH: Final[str] = _env_str("DB_PATH", str(_PROJECT_ROOT / "data" / "enginebot.db"))
LOG_LEVEL: Final[str] = _env_str("LOG_LEVEL", "INFO").upper()
LOG_DIR: Final[Path] = _PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

HEALTH_PORT: Final[int] = _env_int("HEALTH_PORT", 8080)
HEALTH_HOST: Final[str] = _env_str("HEALTH_HOST", "0.0.0.0")
HEALTH_TOKEN: Final[str] = _env_str("HEALTH_TOKEN", "")

DEFAULT_TZ_OFFSET: Final[int] = _env_int("DEFAULT_TZ_OFFSET", 5)


# ─────────────────────────────────────────────────────────────────────
# 3. Tarif limitlari
# ─────────────────────────────────────────────────────────────────────
class Tariff:
    """Tarif rejasi va cheklovlari."""
    TRIAL: Final[str] = "trial"
    BRONZE: Final[str] = "bronze"
    SILVER: Final[str] = "silver"
    GOLD: Final[str] = "gold"
    ALL: Final[tuple[str, ...]] = (TRIAL, BRONZE, SILVER, GOLD)


# Tarif boʻyicha limitlar (max qiymatlar)
TARIFF_LIMITS: Final[dict[str, dict]] = {
    Tariff.TRIAL: {
        "max_channels": 1,
        "max_users": 20,
        "max_posts_per_day": 50,
        "max_active_posts_per_user": 1,
        "duration_days": 7,
        "price_uzs": 0,
    },
    Tariff.BRONZE: {
        "max_channels": 1,
        "max_users": 100,
        "max_posts_per_day": 50,
        "max_active_posts_per_user": 2,
        "duration_days": 30,
        "price_uzs": 50_000,
    },
    Tariff.SILVER: {
        "max_channels": 3,
        "max_users": 500,
        "max_posts_per_day": 200,
        "max_active_posts_per_user": 3,
        "duration_days": 30,
        "price_uzs": 150_000,
    },
    Tariff.GOLD: {
        "max_channels": 999,
        "max_users": 99999,
        "max_posts_per_day": 99999,
        "max_active_posts_per_user": 5,
        "duration_days": 30,
        "price_uzs": 300_000,
    },
}

TRIAL_DAYS: Final[int] = _env_int("TRIAL_DAYS", 7)
BILLING_REMINDER_DAYS: Final[int] = _env_int("BILLING_REMINDER_DAYS", 3)


# ─────────────────────────────────────────────────────────────────────
# 4. Aylanish (rotation) — default qiymatlar
# ─────────────────────────────────────────────────────────────────────
class Rotation:
    """Eʼlon aylanish (rotation) parametrlari."""
    # Default holat — OFF (foydalanuvchi qatʼiy talab qildi)
    DEFAULT_ENABLED: Final[bool] = False

    # Interval (daqiqa)
    MIN_INTERVAL_MIN: Final[int] = 10           # foydalanuvchi qatʼiy talab qildi
    MAX_INTERVAL_MIN: Final[int] = 24 * 60      # 24 soat
    DEFAULT_INTERVAL_MIN: Final[int] = 30

    # Tezkor variantlar (UI uchun)
    QUICK_INTERVALS: Final[tuple[int, ...]] = (10, 15, 30, 60, 120, 180, 360, 720, 1440)

    # Eʼlon yashash muddati (soat)
    MIN_LIFETIME_HOURS: Final[int] = 1
    MAX_LIFETIME_HOURS: Final[int] = 7 * 24
    DEFAULT_LIFETIME_HOURS: Final[int] = 24

    # Aktiv vaqt (kun davomida)
    DEFAULT_ACTIVE_FROM: Final[str] = "06:00"
    DEFAULT_ACTIVE_TO: Final[str] = "23:00"

    # Ikki post orasidagi minimal kechikish (anti-flood)
    SEND_DELAY_S: Final[int] = 3

    # Jitter — bir vaqtda hamma post chiqmasin (sekundda)
    INTERVAL_JITTER_S: Final[int] = 30


# ─────────────────────────────────────────────────────────────────────
# 5. Foydalanuvchi va eʼlon limitlari
# ─────────────────────────────────────────────────────────────────────
class Limits:
    """Umumiy limitlar (tarifdan qatʼi nazar)."""
    # Bir foydalanuvchi roʻyxatdan oʻtish maydonlari
    MAX_NAME_LEN: Final[int] = 100
    MAX_PHONE_LEN: Final[int] = 20
    MAX_USERNAME_LEN: Final[int] = 50

    # Eʼlon matni
    MAX_POST_TEXT_LEN: Final[int] = 1000

    # Ogohlantirishlar — qancha boʻlsa avtomatik block
    MAX_WARNINGS_BEFORE_BLOCK: Final[int] = 3

    # Sessiya timeout (foydalanuvchi yarim yoʻlda qoldirsa)
    SESSION_TIMEOUT_S: Final[int] = 300  # 5 daqiqa


# ─────────────────────────────────────────────────────────────────────
# 6. Statuslar (DB string literallari)
# ─────────────────────────────────────────────────────────────────────
class TenantStatus:
    PENDING: Final[str] = "pending"     # tasdiq kutilmoqda
    ACTIVE: Final[str] = "active"       # ishlamoqda
    PAUSED: Final[str] = "paused"       # toʻlov muddati tugagan
    BLOCKED: Final[str] = "blocked"     # super admin bloklagan
    DELETED: Final[str] = "deleted"     # oʻchirilgan


class UserStatus:
    PENDING: Final[str] = "pending"     # tenant tasdiqlashini kutmoqda
    ACTIVE: Final[str] = "active"       # ishlatishi mumkin
    BLOCKED: Final[str] = "blocked"     # tenant bloklagan


class PostStatus:
    DRAFT: Final[str] = "draft"         # yaratilayapti, hali yuborilmagan
    ACTIVE: Final[str] = "active"       # kanalga joylangan, aktiv
    PAUSED: Final[str] = "paused"       # vaqtincha toʻxtatilgan
    EXPIRED: Final[str] = "expired"     # vaqti tugagan
    DELETED: Final[str] = "deleted"     # oʻchirilgan


# ─────────────────────────────────────────────────────────────────────
# 7. Roller (panel turlari)
# ─────────────────────────────────────────────────────────────────────
class Role:
    SUPER_ADMIN: Final[str] = "super_admin"
    TENANT: Final[str] = "tenant"
    MODERATOR: Final[str] = "moderator"
    USER: Final[str] = "user"
    GUEST: Final[str] = "guest"  # roʻyxatdan oʻtmagan


# ─────────────────────────────────────────────────────────────────────
# 8. Brending
# ─────────────────────────────────────────────────────────────────────
BRAND_NAME: Final[str] = "ENGINEBOT"
BRAND_TAGLINE: Final[str] = "Eʼlonlar mexanizmi"
BRAND_VERSION: Final[str] = "1.0.0-mvp"


def get_brand_footer() -> str:
    """Eʼlonlar ostidagi brend matni."""
    return f"\n\n⚙️ {BRAND_NAME} — {BRAND_TAGLINE}"


# ─────────────────────────────────────────────────────────────────────
# 9. Yordamchilar
# ─────────────────────────────────────────────────────────────────────
def is_super_admin(user_id: int) -> bool:
    """Foydalanuvchi super admin (siz) ekanligini tekshirish."""
    return user_id == SUPER_ADMIN_ID


def get_tariff_limit(tariff: str, key: str, default=None):
    """Tarif uchun belgilangan limit qiymatini olish."""
    return TARIFF_LIMITS.get(tariff, {}).get(key, default)
