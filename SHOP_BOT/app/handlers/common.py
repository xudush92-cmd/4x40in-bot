"""Umumiy handler'lar: /start, /help, /id, /ping va noma'lum xabarlar."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.constants import SellerStatus
from app.db.models import User
from app.keyboards import AdminCB, admin_main_kb
from app.services.seller_service import get_seller
from app.services.settings_service import settings_service
from app.services.text_service import text_service
from app.utils.time import fmt_date

router = Router(name="common")

UNKNOWN_CB_TEXT = "⚠️ Bu tugma eskirgan. /start ni bosing."


def seller_menu_kb() -> InlineKeyboardMarkup:
    """Sotuvchi paneli klaviaturasi (Phase 2-3 da to'ldiriladi)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Tarif va to'lov", callback_data="sm:tariff")],
            [InlineKeyboardButton(text="📢 Mening e'lonlarim", callback_data="sm:ads")],
            [InlineKeyboardButton(text="📅 Mening tarifim", callback_data="sm:my_tariff")],
            [InlineKeyboardButton(text="🎁 Referal", callback_data="sm:referral")],
        ]
    )


async def _seller_status_text(seller) -> str:
    """Sotuvchi uchun tarif holati matni."""
    sub = seller.active_subscription
    if sub is None:
        return "⚠️ Faol tarifingiz yo'q. Iltimos, tarif tanlang."
    tariff_name = sub.tariff.name if sub.tariff else "—"
    return (
        f"📅 Tarifingiz: <b>{tariff_name}</b>\n"
        f"⏳ Tugash sanasi: <b>{fmt_date(sub.expires_at)}</b>\n"
        f"📢 Limit: <b>{sub.ads_used}/{sub.ads_limit}</b> e'lon"
    )


@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(
    message: Message,
    user: User | None,
    is_admin: bool,
    role: str | None,
    session: AsyncSession,
    command: CommandObject | None = None,
) -> None:
    """Bot bilan tanishish. Deep-link: /start ref_<kod>, /start ad_<id> (keyingi bosqichlarda)."""
    name = (user.first_name if user else None) or message.from_user.first_name or "do'st"

    payload = (command.args or "").strip() if command else ""
    if payload:
        # ref_ → Phase 8 (referal), ad_ → Phase 3 (e'lon)
        logger.debug("/start deep-link: {} (user {})", payload, message.from_user.id)

    if is_admin:
        text = await text_service.get("start.admin", ism=name)
        await message.answer(text, reply_markup=admin_main_kb(role))
        return

    seller = await get_seller(session, message.from_user.id)
    if seller is not None and seller.status != SellerStatus.BLOCKED:
        text = await text_service.get("start.seller", ism=name, tarif_holati=await _seller_status_text(seller))
        await message.answer(text, reply_markup=seller_menu_kb())
        return

    support = await settings_service.get("support_contact", "@admin", session)
    text = await text_service.get("start.user", ism=name, yordam=support)
    await message.answer(
        text,
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
        f"☎️ Yordam: {support}",
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


@router.message(F.chat.type == "private")
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


__all__ = ["router", "seller_menu_kb"]
