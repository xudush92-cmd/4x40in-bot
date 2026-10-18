"""Umumiy handler'lar: /start, /help, /id, /ping va noma'lum xabarlar."""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.constants import AdminRole, SellerStatus
from app.db.models import FreeAd, FreeEntitlement, Group, Seller, User
from app.filters import PrivateChat
from app.keyboards import AdminCB, GuideCB, admin_main_kb
from app.keyboards.guide import GUIDES, guide_kb, user_start_kb
from app.keyboards.seller_panel import seller_menu_kb
from app.services import (
    broadcast_service,
    free_ad_service,
    referral_service,
    seller_dashboard,
)
from app.services.seller_service import get_seller
from app.services.settings_service import settings_service
from app.services.stats_service import get_menu_counts
from app.services.text_service import text_service
from app.states import (
    AdminApplicationStates,
    FreeAdStates,
    SellerAdStates,
    SellerApplicationStates,
    SellerPaymentStates,
)
from app.utils.text import escape_html
from app.utils.tg import alert, render
from app.utils.time import ensure_aware, utcnow

router = Router(name="common")

UNKNOWN_CB_TEXT = "⚠️ Bu tugma eskirgan. /start ni bosing."


async def user_home(
    session: AsyncSession, user_id: int, name: str, seller: Seller | None = None,
    bot: Bot | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Oddiy /start: bepul davr va tekshirilgan navbat (shaxsiy chat)."""
    support = str(await settings_service.get("support_contact", "@admin", session))
    text = await text_service.get("start.user", ism=name, yordam=escape_html(support))
    for old in ("📌 Sotuvchi bo'lish uchun administrator bilan bog'laning.",
                "📌 Sotuvchi bo'lish uchun pastdagi arizani yuboring; admin ko'rib chiqadi."):
        text = text.replace(old, "")  # eski seed matni, admin matnining qolgan qismi saqlanadi
    if seller is not None:  # BLOCKED/DELETED: yangi xarid bilan aylanib o'tolmaydi
        reason = f" Sabab: {escape_html(seller.blocked_reason)}" if seller.blocked_reason else ""
        text += f"\n\n🚫 Hisobingiz cheklangan.{reason} Tiklash uchun adminga yozing."
        return text, user_start_kb(support, can_apply=False)
    ads = (await session.execute(select(FreeAd, Group)
        .join(Group, Group.id == FreeAd.group_id)
        .where(FreeAd.user_id == user_id))).all()
    access = {row.group_id: row for row in (await session.execute(select(FreeEntitlement).where(
        FreeEntitlement.user_id == user_id,
    ))).scalars()}
    now = utcnow()
    values = await settings_service.get_all(session)
    global_on = not (values["kill_switch"] or values["maintenance_mode"])
    global_on = global_on and values["posting_enabled_global"] and values["free_plan_enabled"]
    running = 0
    for ad, group in ads:
        ent = access.get(ad.group_id)
        if (global_on and bot and ad.desired_running and not ad.admin_paused
                and ad.next_post_at and ad.review_status == "approved"
                and ent and ensure_aware(ent.expires_at) > now
                and free_ad_service.ready_group(group)
                and await free_ad_service.is_member(bot, group.tg_chat_id, user_id)):
            running += 1
    remaining = [int((ensure_aware(ent.expires_at) - now).total_seconds() // 86400)
                 for ent in access.values() if ensure_aware(ent.expires_at) > now]
    interval = int(await settings_service.get("free_interval_sec", 1800, session)) // 60
    text += (f"\n\n🎁 Bepul: <b>{len(ads)}</b> e'lon / <b>{len({ad.group_id for ad, _ in ads})}</b> guruh "
             f"· huquq muddati <b>{max(remaining) if remaining else 0} kun</b> "
             f"· shaxsiy oralig'i <b>{interval} min</b>.\n"
             f"▶️ Hozir ishlayotgan: <b>{running}</b> ta "
             "(a'zolik, admin, muddat, Stop va guruh holati tekshirildi).\n"
             "💳 Pullik tarifga oldindan sotuvchilik arizasi shart emas; "
             "guruhni tanlab tarif xarid qilasiz.")
    return text, user_start_kb(support, can_apply=False)


@router.message(CommandStart(), PrivateChat())
async def cmd_start(
    message: Message,
    user: User | None,
    is_admin: bool,
    role: str | None,
    session: AsyncSession,
    bot: Bot,
    user_is_new: bool = False,
    command: CommandObject | None = None,
    state: FSMContext | None = None,
) -> None:
    """Bot bilan tanishish. ref_<kod> faqat yangi foydalanuvchiga yoziladi."""
    cancellable_steps = (*SellerApplicationStates.__all_states__, AdminApplicationStates.waiting_reason,
                         *SellerAdStates.__all_states__, *SellerPaymentStates.__all_states__,
                         *FreeAdStates.__all_states__)
    if state and await state.get_state() in {step.state for step in cancellable_steps}:
        await state.clear()  # eski ariza/e'lon/chek matni yangi /start'ni yutib yubormasin
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
        from app.handlers.admin.panel import menu_text

        counts = await get_menu_counts(session)
        text = await text_service.get("start.admin", ism=name)
        await message.answer(text + "\n\n" + menu_text(counts, role),
                             reply_markup=admin_main_kb(role, counts))
        return

    seller = await get_seller(session, message.from_user.id)
    if seller is not None and seller.status in {SellerStatus.PENDING, SellerStatus.ACTIVE}:
        overview = await seller_dashboard.get_overview(session, seller, bot=bot)
        text = await text_service.get("start.seller", ism=name, tarif_holati=overview.text)
        await message.answer(
            text + referral_note,
            reply_markup=seller_menu_kb(
                has_subscription=overview.has_subscription, ads_count=overview.ads_count,
                can_create_ad=overview.can_create_ad,
            ),
        )
        return

    text, markup = await user_home(session, message.from_user.id, name, seller, bot)
    await message.answer(text + referral_note, reply_markup=markup, disable_web_page_preview=True)


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
        "/elon — guruhni tanlab bepul e'lon yuborish",
        "/help — yordam",
        "/id — Telegram ID'ingizni ko'rish",
        "/ping — bot ishlayotganini tekshirish",
        "/takliflarim — har guruhdagi haqiqiy takliflar va N holati",
        "/xabarlar_stop — ommaviy xabarlardan chiqish (qayta /xabarlar_on)",
        f"☎️ Yordam: {escape_html(str(support))}",
    ]
    if is_admin:
        lines.append("/admin — boshqaruv paneli")
    await message.answer("\n".join(lines))


@router.callback_query(GuideCB.filter(), PrivateChat())
async def open_guide(
    callback: CallbackQuery, callback_data: GuideCB, session: AsyncSession,
    user: User | None, is_admin: bool, role: str | None, bot: Bot,
) -> None:
    """Faqat haqiqiy rolning yo'riqnomasi; callback'dagi sahifaga ishonilmaydi."""
    if is_admin:
        profile = "moderator" if role == AdminRole.MODERATOR else "admin"
    else:
        seller = await get_seller(session, callback.from_user.id)
        profile = "seller" if seller and seller.status in {SellerStatus.PENDING, SellerStatus.ACTIVE} else "user"

    if callback_data.page == "support" and profile == "user":
        support = str(await settings_service.get("support_contact", "@admin", session))
        await render(callback, "☎️ <b>Aloqa va yordam</b>\n\n"
                     f"Admin bilan bog'lanish: {escape_html(support)}",
                     user_start_kb(support))
    elif callback_data.page == "back" and profile == "user":
        name = escape_html((user.first_name if user else None) or callback.from_user.first_name or "do'st")
        seller = await get_seller(session, callback.from_user.id)
        text, markup = await user_home(session, callback.from_user.id, name, seller, bot)
        await render(callback, text, markup)
    else:
        pages = GUIDES[profile]
        page = callback_data.page if callback_data.page in pages else "home"
        await render(callback, pages[page][1], guide_kb(profile, page))
    await alert(callback, "")


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
async def cmd_admin(message: Message, is_admin: bool, role: str | None,
                    session: AsyncSession) -> None:
    if not is_admin:
        await message.answer(await text_service.get("common.not_admin"))
        return
    from app.handlers.admin.panel import menu_text

    counts = await get_menu_counts(session)
    await message.answer(menu_text(counts, role), reply_markup=admin_main_kb(role, counts))


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
