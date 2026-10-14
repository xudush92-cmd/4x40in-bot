"""Guruh hayoti: bot qo'shildi / chiqarildi / huquqlari o'zgardi.

REJA.md 8.7 va 1.2/#11: bot huquqini yo'qotsa — guruh avtomatik pauza
bo'ladi va adminga xabar beriladi.
"""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.types import ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.group_service import pause_group, sync_bot_status
from app.services.notify import notify_admins
from app.services.settings_service import settings_service
from app.services.text_service import text_service

router = Router(name="group:lifecycle")


@router.my_chat_member()
async def on_my_chat_member(
    event: ChatMemberUpdated,
    bot: Bot,
    session: AsyncSession,
) -> None:
    chat = event.chat
    if chat.type not in ("group", "supergroup"):
        return

    status = event.new_chat_member.status
    group, missing = await sync_bot_status(session, event)

    # ── Bot guruhga qo'shildi / admin qilindi ─────────────────
    if status in ("member", "administrator"):
        is_admin = status == "administrator"
        logger.info(
            "Bot '{}' guruhiga {} (supergroup={})",
            chat.title,
            "admin qilib qo'shildi" if is_admin else "a'zo sifatida qo'shildi",
            chat.type == "supergroup",
        )

        # Guruhga qisqa javob (admin panelga yo'naltirish)
        text = await text_service.get("group.added", guruh=chat.title or str(chat.id))
        try:
            await bot.send_message(chat.id, text)
        except Exception as exc:  # pragma: no cover
            logger.debug("Guruhga xabar yuborilmadi: {}", exc)

        # Muammolar haqida adminga xabar
        problems: list[str] = []
        if not is_admin:
            problems.append("❌ Bot guruhda <b>admin emas</b> — funksiyalar ishlamaydi.")
        if missing:
            problems.append("⚠️ Yetishmayotgan huquqlar: " + ", ".join(missing))
        if chat.type != "supergroup":
            problems.append(
                "⚠️ Bu <b>oddiy guruh</b>. Mute/ban va to'liq nazorat uchun "
                "<b>supergroup</b>ga aylantirish kerak (Guruh sozlamalari → Chat history → Supergroup)."
            )
        if not group.is_supergroup:
            problems.append("ℹ️ bot Privacy Mode o'chirilganiga ishonch qiling (@BotFather → /setprivacy).")

        members = await _member_count(bot, chat.id)
        text_for_admin = (
            f"👥 <b>Guruh: {chat.title}</b>\n"
            f"🆔 <code>{chat.id}</code>\n"
            f"👤 A'zolar: {members}\n"
            f"🛠 Bot admin: {'✅' if is_admin else '❌'}\n"
        )
        if problems:
            text_for_admin += "\n" + "\n".join(problems)

        await notify_admins(
            bot,
            text_for_admin,
            session=session,
        )
        return

    # ── Bot guruhdan chiqarildi / chiqdi ──────────────────────
    if status in ("left", "kicked"):
        logger.warning("Bot '{}' guruhidan chiqarildi ({})", chat.title, status)
        await pause_group(session, group, reason="bot_left")
        await notify_admins(
            bot,
            await text_service.get("notify.bot_kicked", guruh=chat.title or str(chat.id)),
            session=session,
        )


async def _member_count(bot: Bot, chat_id: int) -> int | str:
    try:
        return await bot.get_chat_member_count(chat_id)
    except Exception:  # pragma: no cover
        return "—"


@router.chat_member()
async def on_chat_member(event: ChatMemberUpdated) -> None:
    """A'zolar holati o'zgarishi — Phase 7 da sanoqchi uchun ishlatiladi."""
    _ = event


def group_admin_button(group_id: int) -> InlineKeyboardMarkup:
    """Guruhni panelda ochish tugmasi (Phase 1 da ishlaydi)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Guruh sozlamalari", callback_data=f"grp:open:{group_id}")]
        ]
    )


__all__ = ["router"]
_ = settings_service
