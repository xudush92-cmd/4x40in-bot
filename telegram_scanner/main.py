"""Serverda ishga tushirish: bot + barcha foydalanuvchilar sessiyalari.

    python main.py

- bot.py — boshqaruv/foydalanuvchi boti (aiogram)
- scanner_manager — har bir foydalanuvchining alohida Telethon sessiyasi
  (o'z guruhlarini kuzatadi, xabar faqat egasiga boradi)
"""
import asyncio
import logging

import bot as bot_module
import scanner_manager
from config import missing_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_all():
    missing = missing_settings()
    if missing:
        raise SystemExit(
            "❌ Quyidagi sozlamalar topilmadi: "
            + ", ".join(missing)
            + "\nServerda muhit o'zgaruvchilari (environment) ga shu nomlar "
            "bilan qo'shing (yoki telegram_scanner/.env fayl yozing)."
        )

    logger.info("Bot va sessiya manageri birgalikda ishga tushmoqda...")
    await asyncio.gather(
        bot_module.main(),
        scanner_manager.run(),
    )


if __name__ == "__main__":
    asyncio.run(run_all())
