"""
config.py — .env dan sozlamalarni o'qiydi.
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Environment o'zgaruvchisi '{name}' yo'q. .env faylini tekshiring.")
    return value


BOT_TOKEN: str = _require("BOT_TOKEN")
# Super admin Telegram ID (raqam). Telegram'da @userinfobot orqali bilish mumkin.
ADMIN_ID: int = int(_require("ADMIN_ID"))
# Yagona guruh ID si (manfiy raqam, masalan -1001234567890)
GROUP_CHAT_ID: int = int(_require("GROUP_CHAT_ID"))
DB_PATH: str = os.getenv("DB_PATH", os.path.join("data", "haydovchi.db"))
