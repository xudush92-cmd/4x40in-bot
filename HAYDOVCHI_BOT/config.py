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


def _group_ids() -> list[int]:
    """
    Boshlang'ich guruhlar (ixtiyoriy). Guruhlarni asosan admin botning o'zidan qo'shadi.
    GROUP_CHAT_IDS=-100111,-100222
    """
    raw = os.getenv("GROUP_CHAT_IDS") or os.getenv("GROUP_CHAT_ID") or ""
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


GROUP_CHAT_IDS: list[int] = _group_ids()
DB_PATH: str = os.getenv("DB_PATH", os.path.join("data", "haydovchi.db"))
