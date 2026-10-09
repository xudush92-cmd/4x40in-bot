"""
bot.py — Haydovchilar boti (yagona Telegram guruh uchun).

Ishga tushirish:
    pip install -r requirements.txt
    cp .env.example .env   # va to'ldiring
    python bot.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from board import BoardManager
from config import ADMIN_ID, BOT_TOKEN, DB_PATH, GROUP_CHAT_ID
from db import Database
from handlers import (
    cmd_group_refresh,
    cmd_start,
    on_callback,
    on_group_message,
    on_private_contact,
    on_private_text,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("haydovchi")

AUTO_STOP_CHECK_SEC = 60


async def _auto_stop_loop(app: Application) -> None:
    """Haydovchi uzoq yangilamagan e'lonlarni avtomatik to'xtatadi."""
    db: Database = app.bot_data["db"]
    board: BoardManager = app.bot_data["board"]
    while True:
        try:
            hours = await db.auto_stop_hours()
            cutoff = int(time.time()) - hours * 3600
            stale = await db.stale_entries(cutoff)
            routes_stopped = []
            for e in stale:
                await db.stop_entry(e["id"])
                routes_stopped.append(e)
            for e in routes_stopped:
                try:
                    await app.bot.send_message(
                        chat_id=e["driver_id"],
                        text=(
                            f"⏰ {e['from_place']} → {e['to_place']} yo'nalishidagi e'loningiz "
                            f"{hours} soat yangilanmagani uchun to'xtatildi.\n"
                            "Qayta boshlash uchun 🟢 Ishni boshlash tugmasini bosing."
                        ),
                    )
                except TelegramError as err:
                    log.info("Haydovchiga xabar yuborilmadi (%s): %s", e["driver_id"], err)
            if routes_stopped:
                log.info("Avtomatik to'xtatildi: %d ta e'lon", len(routes_stopped))
                board.request_update()
        except Exception:
            log.exception("Avto-to'xtash tsiklida xato")
        await asyncio.sleep(AUTO_STOP_CHECK_SEC)


async def _periodic_loop(app: Application) -> None:
    """Guruhda yangi xabar bo'lsa, oynani vaqti-vaqti bilan tekshiradi."""
    db: Database = app.bot_data["db"]
    board: BoardManager = app.bot_data["board"]
    while True:
        try:
            minutes = await db.periodic_minutes()
        except Exception:
            minutes = 15
        await asyncio.sleep(minutes * 60)
        try:
            await board.periodic_check()
        except Exception:
            log.exception("Davriy tekshiruvda xato")


async def post_init(app: Application) -> None:
    db = Database(DB_PATH)
    await db.open()
    me = await app.bot.get_me()
    board = BoardManager(app.bot, db, GROUP_CHAT_ID, me.username)
    app.bot_data["db"] = db
    app.bot_data["board"] = board
    app.bot_data["tasks"] = [
        asyncio.create_task(_auto_stop_loop(app)),
        asyncio.create_task(_periodic_loop(app)),
    ]
    # Qayta ishga tushganda oynani darhol holatga keltiramiz
    board.request_update(delay=5)
    log.info("Bot ishga tushdi: @%s, guruh=%s", me.username, GROUP_CHAT_ID)


async def post_shutdown(app: Application) -> None:
    for t in app.bot_data.get("tasks", []):
        t.cancel()
    db = app.bot_data.get("db")
    if db:
        await db.close()
    log.info("Bot to'xtatildi.")


def build_app() -> Application:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Shaxsiy chat
    app.add_handler(CommandHandler("start", cmd_start, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("menu", cmd_start, filters=filters.ChatType.PRIVATE))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.CONTACT, on_private_contact))
    app.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, on_private_text)
    )

    # Guruh
    group = filters.Chat(chat_id=GROUP_CHAT_ID)
    app.add_handler(CommandHandler("yangila", cmd_group_refresh, filters=group))
    app.add_handler(MessageHandler(group & ~filters.COMMAND, on_group_message))

    # Inline tugmalar (haydovchi va admin)
    app.add_handler(CallbackQueryHandler(on_callback))
    return app


def main() -> None:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    log.info("Super admin ID: %s", ADMIN_ID)
    build_app().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
