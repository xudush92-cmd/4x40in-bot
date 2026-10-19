"""Ikkalasini bitta jarayonda ishga tushirish (Replit uchun qulay).

    python main.py

bot.py (boshqaruv boti) va userbot.py (skaner) bir vaqtda ishlaydi.

MUHIM: Birinchi marta avval userbotni alohida ishga tushirib,
Telegramga kiring (telefon + kod) — sessiya saqlanib qoladi:

    python userbot.py   # telefon raqami, kod (va 2FA parol) kiriting
    # kirgach Ctrl+C bosib to'xtating, keyin: python main.py
"""
import asyncio
import logging

import bot as bot_module
import userbot as userbot_module
from config import missing_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_all():
    missing = missing_settings()
    if missing:
        raise SystemExit(
            "❌ Quyidagi sozlamalar topilmadi: "
            + ", ".join(missing)
            + "\nReplitda: Secrets (🔒) bo'limiga shu nomlar bilan qo'shing "
            "(yoki telegram_scanner/.env fayl yozing)."
        )

    logger.info("Bot va userbot birgalikda ishga tushmoqda...")
    await asyncio.gather(
        bot_module.main(),
        userbot_module.main(),
    )


if __name__ == "__main__":
    asyncio.run(run_all())
