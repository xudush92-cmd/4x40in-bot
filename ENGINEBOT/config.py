"""
config.py — markaziy sozlamalar va konstantalar.

Bu modulda ENV oʻzgaruvchilarini oʻqish va loyiha boʻylab ishlatiladigan
barcha konstantalar joylashgan. Hech qaysi modul oʻz konstantalarini
alohida elon qilmaydi — hammasi shu yerda.

V1 SODDALASHTIRILGAN MODEL:
───────────────────────────
- 4 asosiy rol: SUPER_ADMIN, TENANT, USER, GUEST
- USER ichida 2 ta sub-rol: POSTER (eʼlon beruvchi) va CUSTOMER (mijoz)
- Bitta odam ikkala sub-rolda boʻlishi mumkin (taksist mijoz ham)
- Per-poster rotation: har poster oʻz intervalini belgilaydi (min 10 daq)
- Erkin matn eʼlon (taxi shabloni emas)
- 12 standart kategoriya (taxi, usta, ishchi va h.k.)

Konstantalar 8 turga boʻlinadi:
1. ENV oʻzgaruvchilari (sirli)   — token, ID, parollar
2. Tizim sozlamalari              — DB yoʻli, log
3. Tarif limitlari                — bronze/silver/gold
4. Aylanish (Rotation)            — interval, eʼlon yashash muddati
5. Umumiy Limitlar                — uzunlik cheklovlari
6. Statuslar                       — DB string literallari
7. Rollar                          — panel turlari
8. Brending                        — nom, tagline, versiya
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────────────
# .env yuklash
# ─────────────────────────────────────────────────────────────────────
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
# 3. Tarif limitlari (V1 — kengroq)
# ─────────────────────────────────────────────────────────────────────
class Tariff:
    """Tarif rejasi va cheklovlari."""
    TRIAL: Final[str] = "trial"
    BRONZE: Final[str] = "bronze"
    SILVER: Final[str] = "silver"
    GOLD: Final[str] = "gold"
    ALL: Final[tuple[str, ...]] = (TRIAL, BRONZE, SILVER, GOLD)


# Tarif boʻyicha limitlar (max qiymatlar).
#
# MUHIM: ENGINEBOT'da PUL TIZIMI YO'Q!
# To'lov og'zaki kelishuv asosida bo'ladi. Super admin tenant'ga
# muddat belgilaydi (qancha kun ishlaydi). Muddat tugagach — pause.
# `description` faqat UI'da ko'rsatish uchun.
TARIFF_LIMITS: Final[dict[str, dict]] = {
    Tariff.TRIAL: {
        "description": "🆓 Trial — sinov muddati",
        "max_channels": 1,
        "max_users": 50,
        "max_posts_per_day": 100,
        "max_active_posts_per_user": 5,
        "duration_days": 7,
    },
    Tariff.BRONZE: {
        "description": "🥉 Bronze — kichik guruh",
        "max_channels": 1,
        "max_users": 200,
        "max_posts_per_day": 200,
        "max_active_posts_per_user": 10,
        "duration_days": 30,
    },
    Tariff.SILVER: {
        "description": "🥈 Silver — o'rta guruh",
        "max_channels": 3,
        "max_users": 1000,
        "max_posts_per_day": 1000,
        "max_active_posts_per_user": 20,
        "duration_days": 30,
    },
    Tariff.GOLD: {
        "description": "🥇 Gold — katta guruh",
        "max_channels": 999,
        "max_users": 99999,
        "max_posts_per_day": 99999,
        "max_active_posts_per_user": 100,
        "duration_days": 30,
    },
}

TRIAL_DAYS: Final[int] = _env_int("TRIAL_DAYS", 7)
BILLING_REMINDER_DAYS: Final[int] = _env_int("BILLING_REMINDER_DAYS", 3)


# ─────────────────────────────────────────────────────────────────────
# 4. Aylanish (Rotation) — V1 PER-POSTER MODELI
# ─────────────────────────────────────────────────────────────────────
class Rotation:
    """
    Eʼlon aylanish (rotation) parametrlari.

    V1 model: HAR POSTER OʻZ INTERVALINI belgilaydi.
    Tenant darajasidagi global rotation YOʻQ — faqat min limit cheklovi.
    """

    # Per-poster uchun min interval — qatʼiy qoida (foydalanuvchi talabi)
    MIN_INTERVAL_MIN: Final[int] = 10
    MAX_INTERVAL_MIN: Final[int] = 24 * 60      # 24 soat
    DEFAULT_INTERVAL_MIN: Final[int] = 10        # default — eng kichik

    # Default holat — OFF (poster qoʻlda START bosadi)
    DEFAULT_ENABLED: Final[bool] = False

    # Tezkor variantlar (UI uchun)
    QUICK_INTERVALS: Final[tuple[int, ...]] = (10, 15, 30, 60, 120, 180, 360, 720, 1440)

    # Eʼlon yashash muddati (soat) — vaqti tugagandan keyin avto-oʻchadi
    MIN_LIFETIME_HOURS: Final[int] = 1
    MAX_LIFETIME_HOURS: Final[int] = 7 * 24
    DEFAULT_LIFETIME_HOURS: Final[int] = 24

    # Birinchi eʼlon — DARHOL chiqadi (foydalanuvchi tasdiqi)
    # Keyingilari interval kutadi
    FIRST_POST_IMMEDIATE: Final[bool] = True

    # Ikki post orasidagi minimal kechikish (anti-flood)
    SEND_DELAY_S: Final[int] = 3


# ─────────────────────────────────────────────────────────────────────
# 5. Umumiy Limitlar
# ─────────────────────────────────────────────────────────────────────
class Limits:
    """Umumiy limitlar (tarifdan qatʼi nazar)."""
    # Roʻyxat maydonlari
    MAX_NAME_LEN: Final[int] = 100
    MAX_PHONE_LEN: Final[int] = 20
    MAX_USERNAME_LEN: Final[int] = 50

    # Eʼlon matni va rasmlar
    MAX_POST_TEXT_LEN: Final[int] = 2000
    MAX_PHOTOS_PER_POST: Final[int] = 3

    # Ogohlantirishlar — qancha boʻlsa avtomatik block
    MAX_WARNINGS_BEFORE_BLOCK: Final[int] = 3

    # Sessiya timeout (foydalanuvchi yarim yoʻlda qoldirsa)
    SESSION_TIMEOUT_S: Final[int] = 300  # 5 daqiqa

    # Anti-flood: 1 daqiqada poster max nechta yangi eʼlon yarata oladi
    MAX_NEW_POSTS_PER_MINUTE: Final[int] = 3


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
    QUEUED: Final[str] = "queued"       # galada, navbati kutilmoqda
    ACTIVE: Final[str] = "active"       # kanalga joylangan, aktiv
    PAUSED: Final[str] = "paused"       # vaqtincha toʻxtatilgan
    EXPIRED: Final[str] = "expired"     # vaqti tugagan
    DELETED: Final[str] = "deleted"     # oʻchirilgan


# ─────────────────────────────────────────────────────────────────────
# 7. Rollar (panel turlari)
# ─────────────────────────────────────────────────────────────────────
class Role:
    """Asosiy rollar — panel marshrutlash uchun."""
    SUPER_ADMIN: Final[str] = "super_admin"
    TENANT: Final[str] = "tenant"
    MODERATOR: Final[str] = "moderator"  # v1.5+ uchun zaxira
    USER: Final[str] = "user"
    GUEST: Final[str] = "guest"          # roʻyxatdan oʻtmagan


class UserRole:
    """USER ichidagi sub-rollar (DB users.user_role ustunida saqlanadi)."""
    POSTER: Final[str] = "poster"        # eʼlon beruvchi (taksist, usta)
    CUSTOMER: Final[str] = "customer"    # mijoz (qidiruvchi)
    BOTH: Final[str] = "both"            # ikkala rolda
    ALL: Final[tuple[str, ...]] = (POSTER, CUSTOMER, BOTH)


# ─────────────────────────────────────────────────────────────────────
# 8. Brending
# ─────────────────────────────────────────────────────────────────────
BRAND_NAME: Final[str] = "ENGINEBOT"
BRAND_TAGLINE: Final[str] = "Eʼlonlar mexanizmi"
BRAND_VERSION: Final[str] = "1.1.0-redesign"


def get_brand_footer() -> str:
    """Eʼlonlar ostidagi brend matni."""
    return f"\n\n⚙️ {BRAND_NAME}"


# ─────────────────────────────────────────────────────────────────────
# 9. Yordamchilar
# ─────────────────────────────────────────────────────────────────────
def is_super_admin(user_id: int) -> bool:
    """Foydalanuvchi super admin (siz) ekanligini tekshirish."""
    return user_id == SUPER_ADMIN_ID


def get_tariff_limit(tariff: str, key: str, default=None):
    """Tarif uchun belgilangan limit qiymatini olish."""
    return TARIFF_LIMITS.get(tariff, {}).get(key, default)
