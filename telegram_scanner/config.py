"""Sozlamalar.

Qiymatlar avval shu papkadagi `.env` fayldan, keyin muhit (environment)
o'zgaruvchilaridan o'qiladi. Haqiqiy tokenlarni kodga yozmang!
Namuna: `.env.example` fayliga qarang.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Qo'shimcha kutubxonasiz oddiy .env o'quvchi (KEY=VALUE)."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(
            key.strip(), value.strip().strip("'\"")
        )


_load_dotenv(BASE_DIR / ".env")


def _get_int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


# my.telegram.org saytidan olinadi
API_ID = _get_int("API_ID")
API_HASH = os.getenv("API_HASH", "")

# @BotFather dan olinadi
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Shaxsiy Telegram ID (@userinfobot orqali bilish mumkin)
ADMIN_ID = _get_int("ADMIN_ID")

# Ma'lumotlar bazasi — har doim shu papka ichida (qayerdan ishga
# tushirilishidan qat'iy nazar bot va userbot bitta bazani ko'radi)
DB_NAME = os.getenv("SCANNER_DB_PATH") or str(BASE_DIR / "scanner.db")

# Diqqat: markaziy "userbot_session" fayli ishlatilmaydi — har bir
# foydalanuvchi sessiyasi bazada shifrlangan holda saqlanadi.


def missing_settings() -> list[str]:
    """To'ldirilmagan majburiy sozlamalar ro'yxati."""
    missing = []
    if not API_ID:
        missing.append("API_ID")
    if not API_HASH:
        missing.append("API_HASH")
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not ADMIN_ID:
        missing.append("ADMIN_ID")
    return missing
