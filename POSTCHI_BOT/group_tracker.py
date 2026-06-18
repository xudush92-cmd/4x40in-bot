"""
group_tracker.py — Bot guruh statusini kuzatadi (my_chat_member hodisasi).

Telegram bot o'z statusi o'zgarganda (a'zo → admin → chiqarilgan) avtomatik
ChatMemberUpdated hodisasini yuboradi. Shu orqali:

- Bot guruhga ADMIN qilinsa → bazaga qo'shamiz + super adminga so'rov yuboramiz
  ("qaysi viloyatga biriktiramiz?")
- Bot admin huquqini yo'qotsa yoki guruhdan chiqarilsa → guruhni NOFAOL qilamiz
  va super adminni ogohlantiramiz

Bu — loyihaning eng muhim avtomatik qismi: guruhlar qo'lda emas,
avtomatik aniqlanadi.
"""

from __future__ import annotations

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ChatMemberStatus

import database as db
from config import SUPER_ADMIN

logger = logging.getLogger("PostchiBot")

# Admin hisoblanadigan statuslar
_ADMIN_STATUSES = {ChatMemberStatus.ADMINISTRATOR}
# Guruhda "bor" hisoblanadigan statuslar (a'zo yoki admin)
_PRESENT_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
}


def _is_admin(status) -> bool:
    return status in _ADMIN_STATUSES


def _region_keyboard(chat_id: int, regions: list[dict]) -> InlineKeyboardMarkup:
    """Yangi guruh uchun viloyat tanlash tugmalari (2 ustun)."""
    rows = []
    row = []
    for r in regions:
        row.append(
            InlineKeyboardButton(r["name"], callback_data=f"setgr:{chat_id}:{r['id']}")
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [InlineKeyboardButton("⛔ Biriktirmaslik", callback_data=f"setgr:{chat_id}:skip")]
    )
    return InlineKeyboardMarkup(rows)


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bot o'z guruh statusini o'zgartirganda chaqiriladi."""
    member = update.my_chat_member
    if not member:
        return

    chat = member.chat
    # Faqat guruh/superguruh — shaxsiy chatlarni e'tiborsiz qoldiramiz
    if chat.type not in ("group", "supergroup"):
        return

    old_status = member.old_chat_member.status
    new_status = member.new_chat_member.status

    chat_id = chat.id
    title = chat.title or str(chat_id)

    # Botni kim qo'shgan/admin qilgan — guruh egasi sifatida saqlaymiz
    actor = member.from_user
    owner_uid = actor.id if actor else None

    became_admin = _is_admin(new_status) and not _is_admin(old_status)
    lost_admin = _is_admin(old_status) and not _is_admin(new_status)

    # ── BOT ADMIN BO'LDI ───────────────────────────────────────────────
    if became_admin:
        existing = await db.get_group_by_chat(chat_id)
        await db.upsert_group(chat_id, title, owner_uid)
        logger.info("Bot admin bo'ldi: %s (%s), egasi=%s", title, chat_id, owner_uid)

        # Agar allaqachon viloyatga biriktirilgan bo'lsa — qayta so'ramaymiz
        if existing and existing.get("region_id"):
            return

        # Super adminga so'rov: qaysi viloyatga biriktiramiz?
        regions = await db.get_regions()
        member_count = "?"
        try:
            member_count = await context.bot.get_chat_member_count(chat_id)
        except Exception:
            pass

        text = (
            "🔔 Yangi guruhga admin qilindim!\n\n"
            f"📛 Nomi: {title}\n"
            f"👥 A'zolar: {member_count}\n"
            f"🆔 ID: {chat_id}\n\n"
        )
        if regions:
            text += "Qaysi viloyatga biriktiramiz?"
            kb = _region_keyboard(chat_id, regions)
        else:
            text += (
                "⚠️ Hali viloyat yo'q. Avval 🗺 Viloyatlar bo'limidan viloyat "
                "qo'shing, keyin 👥 Guruhlar → biriktirilmaganlar dan biriktiring."
            )
            kb = None

        try:
            await context.bot.send_message(SUPER_ADMIN, text, reply_markup=kb)
        except Exception as e:
            logger.error("Super adminga xabar yuborilmadi: %s", e)
        return

    # ── BOT ADMIN HUQUQINI YO'QOTDI yoki CHIQARILDI ────────────────────
    if lost_admin or new_status in (
        ChatMemberStatus.LEFT,
        ChatMemberStatus.BANNED,
    ):
        existing = await db.get_group_by_chat(chat_id)
        if existing:
            await db.set_group_active(chat_id, False)
            logger.warning("Bot guruhda nofaol bo'ldi: %s (%s)", title, chat_id)
            try:
                await context.bot.send_message(
                    SUPER_ADMIN,
                    "⚠️ Guruhda admin huquqim olib tashlandi yoki chiqarildim:\n\n"
                    f"📛 {title}\n🆔 {chat_id}\n\n"
                    "Bu guruhga e'lon yuborish to'xtatildi.",
                )
            except Exception:
                pass
