#!/usr/bin/env python3
"""Bazani boshlang'ich ma'lumotlar bilan to'ldirish (seed).

Nima qiladi:
  * `.env` dagi ADMIN_IDS ni super admin sifatida qo'shadi
  * standart global sozlamalarni yozadi (DEFAULTS)
  * standart bot matnlarini yozadi
  * namuna uchun 3 ta tarif yaratadi (xohlasa panel orqali o'zgartiriladi)

Ishlatish:
    python -m scripts.seed            # mavjudlarini saqlab qo'shadi
    python -m scripts.seed --reset-texts   # matnlarni zavod holatiga qaytaradi
"""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal

from loguru import logger
from sqlalchemy import select

from app.config import get_settings
from app.db.base import dispose_engine, session_scope
from app.db.models import BotText, Setting, Tariff
from app.logging_setup import setup_logging
from app.services.notify import ensure_super_admins
from app.services.settings_service import DEFAULTS
from app.services.text_service import DEFAULT_TEXTS

SAMPLE_TARIFFS = [
    {
        "name": "🟢 Boshlang'ich",
        "description": "Kichik biznes uchun: 3 ta e'lon, har birida 2 rasm.",
        "price": Decimal("150000"),
        "duration_days": 30,
        "max_ads": 3,
        "max_photos": 2,
        "position": 1000,
    },
    {
        "name": "🔵 Biznes",
        "description": "O'rtacha sotuvchilar uchun: 10 ta e'lon, har birida 5 rasm.",
        "price": Decimal("400000"),
        "duration_days": 30,
        "max_ads": 10,
        "max_photos": 5,
        "position": 2000,
    },
    {
        "name": "🔴 Premium",
        "description": "Maksimal ko'rinish: 30 ta e'lon, har birida 10 rasm.",
        "price": Decimal("900000"),
        "duration_days": 30,
        "max_ads": 30,
        "max_photos": 10,
        "position": 3000,
    },
]


async def seed(reset_texts: bool = False) -> None:
    async with session_scope() as session:
        # 1) Super adminlar
        created_admins = await ensure_super_admins(session)
        logger.info("Super adminlar: {} ta qo'shildi", created_admins)

        # 2) Global sozlamalar
        existing_settings = {
            row.key for row in (await session.execute(select(Setting))).scalars().all()
        }
        added_settings = 0
        for key, value in DEFAULTS.items():
            if key not in existing_settings:
                session.add(Setting(key=key, value=value, comment="seed orqali qo'shildi"))
                added_settings += 1
        logger.info("Sozlamalar: {} ta qo'shildi (jami {})", added_settings, len(DEFAULTS))

        # 3) Bot matnlari
        existing_texts = {
            (row.key, row.lang) for row in (await session.execute(select(BotText))).scalars().all()
        }
        added_texts = 0
        for key, text in DEFAULT_TEXTS.items():
            if reset_texts and (key, "uz") in existing_texts:
                row = (
                    await session.execute(
                        select(BotText).where(BotText.key == key, BotText.lang == "uz")
                    )
                ).scalar_one()
                row.text = text
                row.is_custom = False
                continue
            if (key, "uz") not in existing_texts:
                session.add(BotText(key=key, lang="uz", text=text, is_custom=False))
                added_texts += 1
        logger.info("Bot matnlari: {} ta qo'shildi (jami {})", added_texts, len(DEFAULT_TEXTS))

        # 4) Namuna tariflar
        existing_tariffs = (
            await session.execute(select(Tariff.name))
        ).scalars().all()
        added_tariffs = 0
        for tariff in SAMPLE_TARIFFS:
            if tariff["name"] not in existing_tariffs:
                session.add(Tariff(**tariff))
                added_tariffs += 1
        logger.info("Tariflar: {} ta qo'shildi", added_tariffs)

    logger.info("✅ Seed tugadi")


def main() -> None:
    parser = argparse.ArgumentParser(description="SHOP-BOT bazasini to'ldirish")
    parser.add_argument(
        "--reset-texts", action="store_true", help="Bot matnlarini zavod holatiga qaytarish"
    )
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level, settings.log_dir, to_file=False)

    try:
        asyncio.run(seed(reset_texts=args.reset_texts))
    finally:
        with __import__("contextlib").suppress(Exception):
            asyncio.run(dispose_engine())


if __name__ == "__main__":
    main()
