"""
config.py — POSTCHI_BOT konstantalari va muhit o'zgaruvchilari.

Barcha sozlamalar shu yerda — bitta joyda. Tugma matnlari ham shu yerda
konstanta sifatida saqlanadi: shunda menyu va handlerlar har doim
bir xil matndan foydalanadi (mos kelmaslik xatosi bo'lmaydi).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(
            f"Environment variable '{name}' yo'q. .env faylini tekshiring."
        )
    return v


# ─────────────────────────────────────────────────────────────────────────
# MUHIT
# ─────────────────────────────────────────────────────────────────────────
BOT_TOKEN = _require_env("BOT_TOKEN")
SUPER_ADMIN = int(_require_env("ADMIN_ID"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "postchi_bot").lstrip("@")
ADMIN_CONTACT_PHONE = os.getenv("ADMIN_CONTACT_PHONE", "")

# ─────────────────────────────────────────────────────────────────────────
# KONSTANTALAR
# ─────────────────────────────────────────────────────────────────────────
DB_PATH = os.path.join("data", "postchi_bot.db")
MEDIA_DIR = "media"
LOG_FILE = "postchi_bot.log"

# Interval (daqiqa)
DEFAULT_INTERVAL_MIN = 10     # admin guruhga interval bermasa
MIN_INTERVAL_MIN = 1
MAX_INTERVAL_MIN = 1440       # 24 soat

# Yuborish (flood himoya)
SEND_DELAY_S = 4              # guruhlar orasidagi kutish (soniya)
SEND_TIMEOUT_S = 20          # bitta yuborishga maksimal vaqt
MAX_GROUP_FAILS = 3          # ketma-ket xato → guruh nofaol qilinadi

# Cheklovlar
MAX_ADS_PER_USER = 5         # foydalanuvchi 5 tagacha e'lon saqlaydi

# Worker
WORKER_TICK_S = 30           # worker har necha soniyada navbatni tekshiradi


# ─────────────────────────────────────────────────────────────────────────
# TUGMA MATNLARI (konstanta — menyu va handler bir xil ishlatadi)
# ─────────────────────────────────────────────────────────────────────────
# Umumiy
BTN_BACK = "◀️ Orqaga"

# Ro'yxatdan o'tish
BTN_PHONE = "📱 Raqamni yuborish"

# Foydalanuvchi menyusi
BTN_ADS = "📢 E'lonlarim"
BTN_REGION = "🗺 Viloyat tanlash"
BTN_START = "▶️ Boshlash"
BTN_STOP = "⛔ To'xtatish"
BTN_STATUS = "📊 Holat"
BTN_STATS = "📈 Statistika"
BTN_REFERRAL = "👥 Referal"
BTN_LOGOUT = "🚪 Chiqish"

# Super admin menyusi
BTN_ADMIN_REGIONS = "🗺 Viloyatlar"
BTN_ADMIN_GROUPS = "👥 Guruhlar"
BTN_ADMIN_USERS = "👤 Foydalanuvchilar"
BTN_ADMIN_STATS = "📊 Statistika"
BTN_ADMIN_SETTINGS = "⚙️ Sozlamalar"

# Guruh egasi menyusi
BTN_OWNER_GROUPS = "🏢 Mening guruhlarim"

# E'lon ostidagi inline tugmalar
BTN_CONTACT = "📞 Bog'lanish"
BTN_POST_AD = "📢 E'lon berish"
