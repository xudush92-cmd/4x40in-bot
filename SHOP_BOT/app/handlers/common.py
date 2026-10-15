"""Umumiy handler'lar: /start, /help, /id, /ping va noma'lum xabarlar."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.constants import SellerStatus
from app.db.models import User
from app.filters import PrivateChat
from app.handlers.seller import seller_status_text
from app.keyboards import AdminCB, admin_main_kb
from app.keyboards.seller_panel import seller_menu_kb
from app.services import broadcast_service, referral_service, seller_service, subscription_service
from app.services.seller_service import get_seller
from app.services.settings_service import settings_service
from app.services.text_service import text_service
from app.utils.text import escape_html
from app.utils.time import utcnow

router = Router(name="common")

UNKNOWN_CB_TEXT = "⚠️ Bu tugma eskirgan. /start ni bosing."


@router.message(CommandStart(), PrivateChat())
async def cmd_start(
    message: Message,
    user: User | None,
    is_admin: bool,
    role: str | None,
    session: AsyncSession,
    user_is_new: bool = False,
    command: CommandObject | None = None,
) -> None:
    """Bot bilan tanishish. ref_<kod> faqat yangi foydalanuvchiga yoziladi."""
    name = escape_html((user.first_name if user else None) or message.from_user.first_name or "do'st")
    first_private_start = user is not None and user.private_started_at is None
    if first_private_start:
        user.private_started_at = utcnow()  # guruh a'zolariga avtomatik DM yuborilmaydi

    payload = (command.args or "").strip() if command else ""
    referral_note = ""
    if payload.startswith("ref_") and not is_admin:
        record = await referral_service.register(
            session, code=payload[4:], referee_id=message.from_user.id,
            user_is_new=first_private_start and user is not None and not user.referral_legacy,
        )
        if record is not None:
            await session.commit()  # xabar yuborilishidan oldin UNIQUE va bonus yoziladi
            referral_note = "\n\n🎁 Referal kodingiz qayd qilindi. Bonus admin belgilagan shart bajarilgach beriladi."
    elif payload:
        logger.debug("/start deep-link: {} (user {})", payload, message.from_user.id)

    if is_admin:
        text = await text_service.get("start.admin", ism=name)
        await message.answer(text, reply_markup=admin_main_kb(role))
        return

    seller = await get_seller(session, message.from_user.id)
    if seller is not None and seller.status != SellerStatus.BLOCKED:
        text = await text_service.get(
            "start.seller", ism=name, tarif_holati=await seller_status_text(seller, session)
        )
        active = await subscription_service.active_for(session, seller.id)
        stats = await seller_service.get_seller_stats(session, seller)
        await message.answer(
            text + referral_note,
            reply_markup=seller_menu_kb(
                has_subscription=active is not None, ads_count=stats["ads_active"]
            ),
        )
        return

    support = await settings_service.get("support_contact", "@admin", session)
    text = await text_service.get("start.user", ism=name, yordam=escape_html(str(support)))
    await message.answer(
        text + referral_note,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="☎️ Yordam",
                        url=f"https://t.me/{str(support).lstrip('@')}",
                    )
                ]
            ]
        ),
        disable_web_page_preview=True,
    )


@router.message(CommandStart())
async def cmd_start_in_group(message: Message) -> None:
    """Guruhda /start — qisqa javob (asosiy ish shaxsiy chatda)."""
    await message.reply(
        "🤖 Men bu guruhda avtomatik ishlayman: e'lon joylash va tartib nazorati.\n"
        "Sozlash uchun admin panel orqali boshqarilaman."
    )


@router.message(Command("help"))
async def cmd_help(message: Message, is_admin: bool) -> None:
    support = await settings_service.get("support_contact", "@admin")
    lines = [
        "ℹ️ <b>Yordam</b>",
        "",
        "Bu bot — guruhlar uchun onlayn do'kon uslubidagi e'lonlar tizimi.",
        "",
        "📌 <b>Buyruqlar:</b>",
        "/start — boshlash",
        "/help — yordam",
        "/id — Telegram ID'ingizni ko'rish",
        "/ping — bot ishlayotganini tekshirish",
        "/takliflarim — guruh sanoqchisi, obuna holati va shaxsiy havola",
        "/xabarlar_stop — ommaviy xabarlardan chiqish (qayta /xabarlar_on)",
        f"☎️ Yordam: {escape_html(str(support))}",
    ]
    if is_admin:
        lines.append("/admin — boshqaruv paneli")
    await message.answer("\n".join(lines))


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(
        f"🆔 Sizning Telegram ID: <code>{message.from_user.id}</code>\n"
        f"💬 Chat ID: <code>{message.chat.id}</code>"
    )


@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    await message.answer(f"🏓 Pong! Bot ishlayapti (v{__version__})")


@router.message(Command("admin"))
async def cmd_admin(message: Message, is_admin: bool, role: str | None) -> None:
    if not is_admin:
        await message.answer(await text_service.get("common.not_admin"))
        return
    await message.answer(
        "🛠 <b>Boshqaruv paneli</b>\nKerakli bo'limni tanlang:",
        reply_markup=admin_main_kb(role),
    )


@router.message(Command("xabarlar_stop"), PrivateChat())
async def broadcast_stop(message: Message, user: User, session: AsyncSession) -> None:
    await broadcast_service.opt_out(session, user, enabled=True)
    await message.answer("🔕 Ommaviy xabarlar o'chirildi. Qayta yoqish: /xabarlar_on")


@router.message(Command("xabarlar_on"), PrivateChat())
async def broadcast_start(message: Message, user: User, session: AsyncSession) -> None:
    await broadcast_service.opt_out(session, user, enabled=False)
    await message.answer("🔔 Ommaviy xabarlar yoqildi. Istalgan payt /xabarlar_stop")


@router.message(PrivateChat())
async def unknown_message(message: Message, is_admin: bool, role: str | None) -> None:
    """Noma'lum xabar: foydalanuvchi "yo'qolib" qolmasligi uchun yumshoq javob."""
    text = await text_service.get("common.unknown_command")
    await message.answer(text, reply_markup=admin_main_kb(role) if is_admin else None)


@router.callback_query(AdminCB.filter())
async def unknown_callback(callback: CallbackQuery, callback_data: AdminCB) -> None:
    """Tanilmagan admin callback'i (eski xabardagi klaviatura bo'lishi mumkin)."""
    logger.debug("Noma'lum callback: {}:{}", callback_data.action, callback_data.value)
    await callback.answer(UNKNOWN_CB_TEXT, show_alert=False)


@router.message()
async def group_fallback(message: Message) -> None:
    """Guruhlardagi boshqa xabarlar.

    Phase 6 da aynan shu nuqtaga posbon va tozalovchi ulanadi
    (REJA.md 8.5, 8.6).
    """
    logger.trace("Guruh xabari qayd etildi: chat={} id={}", message.chat.id, message.message_id)


__all__ = ["router"]
