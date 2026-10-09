"""
bot.py — Haydovchilar boti (bir nechta Telegram guruh uchun).

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

from board import BoardHub, BoardManager
from config import ADMIN_ID, BOT_TOKEN, DB_PATH, GROUP_CHAT_IDS
from db import WARN_BEFORE_SEC, Database, ts_to_date_str
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

CHECK_SEC = 60  # avto-to'xtash va obuna tekshiruvi oralig'i


async def _notify_driver(app: Application, uid: int, text: str) -> None:
    try:
        await app.bot.send_message(chat_id=uid, text=text)
    except TelegramError as err:
        log.info("Haydovchiga xabar yuborilmadi (%s): %s", uid, err)


async def _maintenance_loop(app: Application) -> None:
    """
    Har daqiqada:
    1) Uzoq yangilanmagan e'lonlarni avtomatik to'xtatadi.
    2) Obuna muddati tugagan haydovchilarning e'lonlarini to'xtatadi.
    3) Obuna tugashiga 3 kun qolganda ogohlantiradi.
    """
    db: Database = app.bot_data["db"]
    hub: BoardHub = app.bot_data["hub"]
    while True:
        try:
            now = int(time.time())
            changed = False

            hours = await db.auto_stop_hours()
            stale = await db.stale_entries(now - hours * 3600)
            for e in stale:
                await db.stop_entry(e["id"])
                await _notify_driver(
                    app, e["driver_id"],
                    f"⏰ {e['from_place']} → {e['to_place']} yo'nalishidagi e'loningiz "
                    f"{hours} soat yangilanmagani uchun to'xtatildi.\n"
                    "Qayta boshlash uchun 🟢 Ishni boshlash tugmasini bosing.",
                )
                changed = True

            expired = await db.subscription_expired_with_entries(now)
            for e in expired:
                await db.stop_entry(e["id"])
                await _notify_driver(
                    app, e["driver_id"],
                    f"⛔ Obuna muddati tugagani uchun {e['from_place']} → {e['to_place']} "
                    "e'loningiz to'xtatildi. Obunani uzaytirish uchun admin bilan bog'laning.",
                )
                changed = True

            for u in await db.subscription_expiring(now):
                left_days = max(1, (u.paid_until - now) // 86400)
                await _notify_driver(
                    app, u.tg_id,
                    f"📅 Obuna muddatingiz {ts_to_date_str(u.paid_until)} da tugaydi "
                    f"(taxminan {left_days} kun qoldi). Uzaytirish uchun admin bilan bog'laning.",
                )
                await db.update_user_fields(u.tg_id, warned_for=u.paid_until)

            if changed:
                log.info("Avtomatik to'xtatildi: %d ta e'lon", len(stale) + len(expired))
                hub.request_update_all()
        except Exception:
            log.exception("Tekshiruv tsiklida xato")
        await asyncio.sleep(CHECK_SEC)


async def _periodic_loop(app: Application) -> None:
    """Guruhlarda yangi xabar bo'lsa, oynalarni vaqti-vaqti bilan tekshiradi."""
    db: Database = app.bot_data["db"]
    hub: BoardHub = app.bot_data["hub"]
    while True:
        try:
            minutes = await db.periodic_minutes()
        except Exception:
            minutes = 15
        await asyncio.sleep(minutes * 60)
        await hub.periodic_all()


async def post_init(app: Application) -> None:
    db = Database(DB_PATH)
    await db.open()
    me = await app.bot.get_me()
    # .env dagi boshlang'ich guruhlarni bazaga qo'shamiz (agar yo'q bo'lsa)
    for chat_id in GROUP_CHAT_IDS:
        await db.add_group(chat_id, "")
    hub = BoardHub()
    for chat_id in await db.group_ids():
        hub.add(BoardManager(app.bot, db, chat_id, me.username))
    app.bot_data["db"] = db
    app.bot_data["hub"] = hub
    app.bot_data["tasks"] = [
        asyncio.create_task(_maintenance_loop(app)),
        asyncio.create_task(_periodic_loop(app)),
    ]
    # Qayta ishga tushganda oynalarni darhol holatga keltiramiz
    hub.request_update_all()
    log.info("Bot ishga tushdi: @%s, guruhlar=%s", me.username, await db.group_ids())


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

    # Guruhlar: qaysi guruhlar boshqarilishi admin tomonidan botda belgilanadi
    groups = filters.ChatType.GROUPS
    app.add_handler(CommandHandler("yangila", cmd_group_refresh, filters=groups))
    app.add_handler(MessageHandler(groups & ~filters.COMMAND, on_group_message))

    # Inline tugmalar
    app.add_handler(CallbackQueryHandler(on_callback))
    return app


def main() -> None:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    log.info("Super admin ID: %s | Obuna ogohlantirish: %d kun oldin",
             ADMIN_ID, WARN_BEFORE_SEC // 86400)
    build_app().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
