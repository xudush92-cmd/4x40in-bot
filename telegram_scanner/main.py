"""Serverda ishga tushirish: bot + barcha foydalanuvchilar sessiyalari.

    python main.py

- bot.py — boshqaruv/foydalanuvchi boti (aiogram)
- scanner_manager — har bir foydalanuvchining alohida Telethon sessiyasi
  (o'z guruhlarini kuzatadi, xabar faqat egasiga boradi)
"""
import asyncio
import logging

from config import missing_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🧾 Diagnostika: oxirgi log qatorlari xotirada turadi va admin tugma
# bilan .txt fayl qilib oladi (telefon raqamlar yopiladi).
import logbuffer  # noqa: E402

logbuffer.install()


async def run_all():
    # Sozlamalar tekshiruvi import'dan OLDIN bajarilishi kerak: bot va
    # scanner_manager import qilinganda Telethon klienti yaratiladi va
    # API_ID/API_HASH bo'sh bo'lsa xom traceback chiqadi.
    missing = missing_settings()
    if missing:
        raise SystemExit(
            "❌ Quyidagi sozlamalar topilmadi: "
            + ", ".join(missing)
            + "\nServerda muhit o'zgaruvchilari (environment) ga shu nomlar "
            "bilan qo'shing (yoki telegram_scanner/.env fayl yozing)."
        )

    import bot as bot_module
    import scanner_manager

    logger.info("Bot va sessiya manageri birgalikda ishga tushmoqda...")
    await asyncio.gather(
        bot_module.main(),
        scanner_manager.run(),
    )


if __name__ == "__main__":
    asyncio.run(run_all())
