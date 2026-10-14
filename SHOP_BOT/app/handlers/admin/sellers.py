"""🛒 Sotuvchilar bo'limi (Phase 2).

Imkoniyatlar:
  * ro'yxat (holat filtri, sahifalash), qidiruv (ID yoki ism bo'yicha)
  * qo'shish: user_id → ism → telefon → kontakt → izoh (FSM)
  * kartochka: obuna holati, e'lonlar, to'lovlar, blok/tasdiq/o'chirish
  * tarif berish (uzaytirish yoki almashtirish), qo'lda muddat/limit
  * obunalar tarixi
"""

from __future__ import annotations

from math import ceil

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole, SellerStatus
from app.db.models import Seller
from app.filters import IsAdmin
from app.keyboards.callbacks import AdminCB, SellerCB
from app.keyboards.common import PER_PAGE_SELLERS
from app.keyboards.sellers import (
    block_reasons_kb,
    cancel_kb,
    confirm_kb,
    grant_tariffs_kb,
    profile_kb,
    seller_card_kb,
    sellers_list_kb,
)
from app.services import seller_service, subscription_service, tariff_service
from app.states import AdminSellerStates
from app.utils.text import escape_html, fmt_amount, human_int, truncate
from app.utils.time import fmt_date, human_delta, utcnow
from app.utils.tg import alert, render

router = Router(name="admin:sellers")
# Sotuvchilar bo'limi — admin va super admin uchun (moderatorlarsiz)
router.message.filter(IsAdmin(AdminRole.ADMIN))
router.callback_query.filter(IsAdmin(AdminRole.ADMIN))

BLOCK_REASONS = {
    "fraud": "Qoidabuzarlik (firibgarlik)",
    "no_pay": "To'lov qilinmagan",
    "complaints": "Shikoyatlar ko'p",
    "other": "Admin qaroriga ko'ra",
}


# ═══════════════════════════ Matnlar ═══════════════════════════════
def _list_text(counts: dict[str, int], total: int, status: str | None, page: int, pages: int, query: str | None) -> str:
    lines = [
        "🛒 <b>Sotuvchilar</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Jami: <b>{counts.get('total', 0)}</b>  ·  🟢 Faol: <b>{counts.get('active', 0)}</b>  ·  "
        f"🕓 Tarifsiz: <b>{counts.get('pending', 0)}</b>  ·  🚫 Blok: <b>{counts.get('blocked', 0)}</b>",
        f"🔎 Filtr: <b>{seller_service.status_filter_label(status)}</b>",
    ]
    if query:
        lines.append(f"🔍 Qidiruv: <b>{escape_html(truncate(query, 20))}</b>")
    lines.append("")
    if total == 0:
        lines.append("📭 Hech narsa topilmadi.")
        if query:
            lines.append("<i>Boshqa so'z bilan urinib ko'ring yoki «➕ Sotuvchi qo'shish».</i>")
    else:
        lines.append(f"<i>Ko'rsatilgan: {total} ta · sahifa {page + 1}/{pages}. Sotuvchini bosib ochasiz.</i>")
    return "\n".join(lines)


def _card_text(seller: Seller, stats: dict[str, int], subscription, days_left: int, tariff_name: str | None) -> str:
    lines = [
        f"🛒 <b>{escape_html(seller.display_name or 'Nomsiz')}</b>"
        + (" ✅" if seller.is_verified else ""),
        "━━━━━━━━━━━━━━━━━━━━",
        f"🆔 Telegram ID: <code>{seller.user_id}</code>",
        f"📌 Holat: <b>{seller_service.status_badge(seller)}</b>",
    ]

    if seller.phone:
        lines.append(f"📞 Telefon: <code>{escape_html(seller.phone)}</code>")
    if seller.contact:
        lines.append(f"🔗 Kontakt: {escape_html(seller.contact)}")
    if seller.referral_code:
        lines.append(f"🎁 Referal kodi: <code>{seller.referral_code}</code>")

    lines.append("━━━━━━━━━━━━━━━━━━━━")

    if subscription is None:
        lines.append("💳 Obuna: <b>yo'q</b>")
        if seller.status == SellerStatus.PENDING:
            lines.append("<i>«💳 Tarif berish» tugmasi bilan tarif bering.</i>")
    else:
        left = days_left
        when = "o'tgan" if left < 0 else f"{left} kun qoldi"
        lines.append(
            f"💳 Obuna: <b>{subscription_service.status_title(subscription)}</b>\n"
            f"   ├ Tarif: <b>{escape_html(tariff_name or '—')}</b>\n"
            f"   ├ Muddat: {fmt_date(subscription.starts_at)} → <b>{fmt_date(subscription.expires_at)}</b> ({when})\n"
            f"   └ 🎯 Limit: <b>{subscription.ads_used}/{subscription.ads_limit}</b> e'lon "
            f"(qoldi {subscription.ads_left})"
        )

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        f"📢 E'lonlar: <b>{stats['ads_total']}</b> (faol {stats['ads_active']})  ·  "
        f"💰 To'lovlar: <b>{stats['payments']}</b>  ·  🕘 Obunalar: <b>{stats['subscriptions']}</b>"
    )
    lines.append(f"💵 Balans: <b>{fmt_amount(seller.balance)}</b>")

    if seller.blocked_reason:
        lines.append(f"\n🚫 Sabab: {escape_html(truncate(seller.blocked_reason, 120))}")
    if seller.note:
        lines.append(f"\n🗒 <i>{escape_html(truncate(seller.note, 200))}</i>")
    return "\n".join(lines)


def _profile_text(seller: Seller) -> str:
    return (
        f"📝 <b>Profil</b> — {escape_html(seller.display_name or 'Nomsiz')}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <code>{seller.user_id}</code>\n"
        f"👤 Ism: <b>{escape_html(seller.display_name or '—')}</b>\n"
        f"📞 Telefon: <b>{escape_html(seller.phone or '—')}</b>\n"
        f"🔗 Kontakt: <b>{escape_html(seller.contact or '—')}</b>\n"
        f"🗒 Izoh: {escape_html(seller.note or '—')}\n\n"
        "<i>Maydonni bosib o'zgartirasiz.</i>"
    )


# ══════════════════════════ Renderlar ══════════════════════════════
def _parse_page(value: str) -> tuple[int, str | None]:
    """`"2|active"` → (2, "active")."""
    page_text, _, status = (value or "0|all").partition("|")
    try:
        page = max(0, int(page_text))
    except ValueError:
        page = 0
    return page, (None if status in ("", "all") else status)


async def render_list(
    target, session: AsyncSession, page: int = 0, *, status: str | None = None, query: str | None = None
) -> None:
    counts = await seller_service.count_sellers_by_status(session)
    total = await seller_service.count_sellers(session, status=status, query=query)
    pages = max(1, ceil(total / PER_PAGE_SELLERS))
    page = max(0, min(page, pages - 1))

    sellers = await seller_service.list_sellers(
        session, offset=page * PER_PAGE_SELLERS, limit=PER_PAGE_SELLERS, status=status, query=query
    )
    active_ids: set[int] = set()
    for seller in sellers:
        if await subscription_service.active_for(session, seller.id) is not None:
            active_ids.add(seller.id)

    await render(
        target,
        _list_text(counts, total, status, page, pages, query),
        sellers_list_kb(sellers, page, pages, status=status, active_ids=active_ids),
    )


async def render_card(target, session: AsyncSession, seller_id: int) -> bool:
    seller = await seller_service.get_seller_by_id(session, seller_id)
    if seller is None:
        await render(target, "⚠️ Sotuvchi topilmadi.")
        return False

    subscription = await subscription_service.latest_for(session, seller.id)
    active = await subscription_service.active_for(session, seller.id)
    tariff_name = None
    if subscription is not None:
        tariff = await tariff_service.get_tariff(session, subscription.tariff_id)
        tariff_name = tariff.name if tariff else None

    stats = await seller_service.get_seller_stats(session, seller)
    await render(
        target,
        _card_text(seller, stats, subscription, subscription_service.days_left(subscription), tariff_name),
        seller_card_kb(seller, has_subscription=subscription is not None),
    )
    _ = active
    return True


async def render_profile(target, session: AsyncSession, seller_id: int) -> None:
    seller = await seller_service.get_seller_by_id(session, seller_id)
    if seller is None:
        await render(target, "⚠️ Sotuvchi topilmadi.")
        return
    await render(target, _profile_text(seller), profile_kb(seller))


# ══════════════════════ Ko'rish (navigatsiya) ══════════════════════
@router.callback_query(SellerCB.filter(F.action == "list"))
async def on_list(callback: CallbackQuery, callback_data: SellerCB, session: AsyncSession) -> None:
    page, status = _parse_page(callback_data.value)
    await render_list(callback, session, page, status=status)
    await alert(callback, "")


@router.callback_query(SellerCB.filter(F.action == "filter"))
async def on_filter(callback: CallbackQuery, callback_data: SellerCB, session: AsyncSession) -> None:
    status = None if callback_data.value in ("", "all") else callback_data.value
    await render_list(callback, session, 0, status=status)
    await alert(callback, f"Filtr: {seller_service.status_filter_label(status)}")


@router.callback_query(SellerCB.filter(F.action == "card"))
async def on_card(callback: CallbackQuery, callback_data: SellerCB, session: AsyncSession) -> None:
    ok = await render_card(callback, session, callback_data.seller_id)
    await alert(callback, "" if ok else "Sotuvchi topilmadi")


@router.callback_query(SellerCB.filter(F.action == "profile"))
async def on_profile(callback: CallbackQuery, callback_data: SellerCB, session: AsyncSession) -> None:
    await render_profile(callback, session, callback_data.seller_id)
    await alert(callback, "")


# ═══════════════════════ Holat (blok/tasdiq) ═══════════════════════
@router.callback_query(SellerCB.filter(F.action == "block"))
async def on_block(callback: CallbackQuery, callback_data: SellerCB, session: AsyncSession) -> None:
    seller = await seller_service.get_seller_by_id(session, callback_data.seller_id)
    if seller is None:
        await alert(callback, "⚠️ Sotuvchi topilmadi", show=True)
        return
    await render(
        callback,
        f"🚫 <b>{escape_html(seller.display_name or 'Nomsiz')}</b> — bloklash sababini tanlang.\n"
        "Bloklanganda sotuvchi panelga kira olmaydi va e'lonlari to'xtatiladi.",
        block_reasons_kb(seller.id),
    )
    await alert(callback, "")


@router.callback_query(SellerCB.filter(F.action == "block_confirm"))
async def on_block_confirm(
    callback: CallbackQuery, callback_data: SellerCB, session: AsyncSession, bot
) -> None:
    seller = await seller_service.get_seller_by_id(session, callback_data.seller_id)
    if seller is None:
        await alert(callback, "⚠️ Sotuvchi topilmadi", show=True)
        return

    reason = BLOCK_REASONS.get(callback_data.value, "Admin qaroriga ko'ra")
    await seller_service.set_status(session, seller, SellerStatus.BLOCKED, reason=reason)
    await _notify_seller(bot, seller.user_id, f"🚫 Hisobingiz bloklandi.\nSabab: {reason}")
    await render_card(callback, session, seller.id)
    await alert(callback, f"🚫 Bloklandi: {reason}", show=True)


@router.callback_query(SellerCB.filter(F.action == "unblock"))
async def on_unblock(callback: CallbackQuery, callback_data: SellerCB, session: AsyncSession, bot) -> None:
    seller = await seller_service.get_seller_by_id(session, callback_data.seller_id)
    if seller is None:
        await alert(callback, "⚠️ Sotuvchi topilmadi", show=True)
        return

    subscription = await subscription_service.active_for(session, seller.id)
    new_status = SellerStatus.ACTIVE if subscription is not None else SellerStatus.PENDING
    await seller_service.set_status(session, seller, new_status)
    await _notify_seller(bot, seller.user_id, "✅ Hisobingiz blokdan chiqarildi.")
    await render_card(callback, session, seller.id)
    await alert(callback, "✅ Blokdan chiqarildi", show=True)


@router.callback_query(SellerCB.filter(F.action == "verify"))
async def on_verify(callback: CallbackQuery, callback_data: SellerCB, session: AsyncSession) -> None:
    seller = await seller_service.get_seller_by_id(session, callback_data.seller_id)
    if seller is None:
        await alert(callback, "⚠️ Sotuvchi topilmadi", show=True)
        return

    value = not seller.is_verified
    await seller_service.set_verified(session, seller, value)
    await render_card(callback, session, seller.id)
    await alert(callback, "✅ Tasdiqlangan" if value else "☑️ Tasdiq olindi")


@router.callback_query(SellerCB.filter(F.action == "delete"))
async def on_delete(callback: CallbackQuery, callback_data: SellerCB, session: AsyncSession) -> None:
    seller = await seller_service.get_seller_by_id(session, callback_data.seller_id)
    if seller is None:
        await alert(callback, "⚠️ Sotuvchi topilmadi", show=True)
        return

    stats = await seller_service.get_seller_stats(session, seller)
    await render(
        callback,
        f"🗑 <b>{escape_html(seller.display_name or 'Nomsiz')}</b> o'chirilsinmi?\n\n"
        f"📢 E'lonlari: <b>{stats['ads_total']}</b>\n"
        f"🕘 Obunalari: <b>{stats['subscriptions']}</b>\n\n"
        "⚠️ Yozuv tarix uchun saqlanadi, lekin sotuvchi panelga kira olmaydi. "
        "Tiklash uchun qayta qo'shish mumkin.",
        confirm_kb("delete", seller.id),
    )
    await alert(callback, "")


@router.callback_query(SellerCB.filter(F.action == "delete_confirm"))
async def on_delete_confirm(callback: CallbackQuery, callback_data: SellerCB, session: AsyncSession) -> None:
    seller = await seller_service.get_seller_by_id(session, callback_data.seller_id)
    if seller is None:
        await alert(callback, "⚠️ Sotuvchi topilmadi", show=True)
        return

    name = seller.display_name or str(seller.user_id)
    await seller_service.soft_delete(session, seller)
    await render_list(callback, session, 0)
    await alert(callback, f"🗑 «{name}» o'chirildi", show=True)


# ═══════════════════════ Obuna berish ══════════════════════════════
@router.callback_query(SellerCB.filter(F.action == "grant"))
async def on_grant(callback: CallbackQuery, callback_data: SellerCB, session: AsyncSession) -> None:
    seller = await seller_service.get_seller_by_id(session, callback_data.seller_id)
    if seller is None:
        await alert(callback, "⚠️ Sotuvchi topilmadi", show=True)
        return

    tariffs = await tariff_service.list_all_active(session)
    text = (
        f"💳 <b>{escape_html(seller.display_name or 'Nomsiz')}</b> — tarif tanlang\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    )
    if tariffs:
        for tariff in tariffs:
            text += (
                f"\n<b>{escape_html(tariff.name)}</b>\n"
                f"   └ {tariff_service.limits_line(tariff)}\n"
            )
        text += (
            "\n<i>Agar sotuvchining amaldagi tarifi bir xil bo'lsa — muddat va limit "
            "qo'shiladi (uzaytirish). Boshqa tarif bo'lsa — yangisi bugundan boshlanadi.</i>"
        )
    else:
        text += "⚠️ Faol tarif yo'q. Avval «💳 Tariflar» bo'limida tarif yarating."

    await render(callback, text, grant_tariffs_kb(tariffs, seller.id))
    await alert(callback, "")


@router.callback_query(SellerCB.filter(F.action == "grant_tariff"))
async def on_grant_tariff(
    callback: CallbackQuery, callback_data: SellerCB, session: AsyncSession, bot, role: str | None
) -> None:
    seller = await seller_service.get_seller_by_id(session, callback_data.seller_id)
    tariff = await tariff_service.get_tariff(session, int(callback_data.value or 0))
    if seller is None or tariff is None:
        await alert(callback, "⚠️ Topilmadi", show=True)
        return

    subscription = await subscription_service.grant(
        session, seller, tariff, granted_by=callback.from_user.id
    )
    _ = role

    await _notify_seller(
        bot,
        seller.user_id,
        "🎉 <b>Tarifingiz faollashtirildi!</b>\n\n"
        f"💳 Tarif: <b>{tariff.name}</b>\n"
        f"📅 Muddat: <b>{tariff.duration_days} kun</b> ({fmt_date(subscription.expires_at)} gacha)\n"
        f"📢 E'lon limiti: <b>{subscription.ads_limit}</b> ta\n"
        f"🖼 Har e'londa rasm: <b>{tariff.max_photos}</b> tagacha\n\n"
        "Endi sotuvchi panelidan e'lon qo'shishingiz mumkin.",
    )

    await render_card(callback, session, seller.id)
    await alert(
        callback,
        f"✅ «{tariff.name}» berildi ({subscription.ads_limit} e'lon, {fmt_date(subscription.expires_at)} gacha)",
        show=True,
    )


@router.callback_query(SellerCB.filter(F.action == "extend"))
async def on_extend(callback: CallbackQuery, callback_data: SellerCB, session: AsyncSession, bot) -> None:
    seller = await seller_service.get_seller_by_id(session, callback_data.seller_id)
    if seller is None:
        await alert(callback, "⚠️ Sotuvchi topilmadi", show=True)
        return

    subscription = await subscription_service.active_for(session, seller.id)
    if subscription is None:
        await alert(callback, "⚠️ Faol obuna yo'q — avval tarif bering", show=True)
        return

    days = int(callback_data.value or 30)
    await subscription_service.extend(session, subscription, days)
    await _notify_seller(
        bot,
        seller.user_id,
        f"✅ Tarifingiz {days} kunga uzaytirildi.\n📅 Yangi muddat: <b>{fmt_date(subscription.expires_at)}</b>",
    )
    await render_card(callback, session, seller.id)
    await alert(callback, f"✅ +{days} kun", show=True)


@router.callback_query(SellerCB.filter(F.action == "subs"))
async def on_subs(callback: CallbackQuery, callback_data: SellerCB, session: AsyncSession) -> None:
    seller = await seller_service.get_seller_by_id(session, callback_data.seller_id)
    if seller is None:
        await alert(callback, "⚠️ Sotuvchi topilmadi", show=True)
        return

    items = await subscription_service.history(session, seller.id, limit=10)
    lines = [
        f"🕘 <b>Obunalar tarixi</b> — {escape_html(seller.display_name or 'Nomsiz')}",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if not items:
        lines.append("📭 Obunalar yo'q.")
    else:
        for subscription in items:
            tariff = await tariff_service.get_tariff(session, subscription.tariff_id)
            stats = await subscription_service.stats(session, subscription)
            lines.append(
                f"• <b>{escape_html(tariff.name if tariff else '—')}</b> — "
                f"{subscription_service.status_title(subscription)}\n"
                f"   └ {fmt_date(subscription.starts_at)} → {fmt_date(subscription.expires_at)} · "
                f"📢 {subscription.ads_used}/{subscription.ads_limit} "
                f"(yaratilgan: {stats['ads_created']})"
            )

    await render(
        callback,
        "\n".join(lines),
        _back_to_card(seller.id),
    )
    await alert(callback, "")


def _back_to_card(seller_id: int):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="◀️ Orqaga", callback_data=SellerCB(action="card", seller_id=seller_id).pack()
                )
            ]
        ]
    )


# ═══════════════════════ Qo'shish (FSM) ════════════════════════════
@router.callback_query(SellerCB.filter(F.action == "add"))
async def start_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AdminSellerStates.waiting_user_id)
    await render(
        callback,
        "➕ <b>Yangi sotuvchi</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ Sotuvchining <b>Telegram ID</b> sini yuboring.\n\n"
        "<i>ID ni bilish uchun sotuvchi botga /id yozib yuborishi mumkin.</i>\n"
        "Bekor qilish uchun /cancel",
        cancel_kb(),
    )
    await alert(callback, "")


@router.message(StateFilter(AdminSellerStates.waiting_user_id), F.text)
async def apply_user_id(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip().lstrip("@")
    if not raw.isdigit():
        await message.answer("⚠️ Faqat raqam (Telegram ID) yuboring. Bekor qilish: /cancel")
        return

    user_id = int(raw)
    existing = await seller_service.get_seller(session, user_id)
    if existing is not None and existing.status != SellerStatus.DELETED:
        await state.clear()
        await message.answer(
            f"ℹ️ Bu ID allaqachon sotuvchi: <b>{escape_html(existing.display_name or '—')}</b> "
            f"({seller_service.status_badge(existing)})"
        )
        await render_card(message, session, existing.id)
        return

    await state.update_data(user_id=user_id)
    await state.set_state(AdminSellerStates.waiting_name)
    await message.answer(
        f"2️⃣ Sotuvchi ismini (yoki do'kon nomini) yuboring.\nID: <code>{user_id}</code>\n"
        "Bekor qilish uchun /cancel"
    )


@router.message(StateFilter(AdminSellerStates.waiting_name), F.text)
async def apply_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("⚠️ Ism juda qisqa. Qaytadan yuboring. Bekor qilish: /cancel")
        return
    await state.update_data(display_name=name)
    await state.set_state(AdminSellerStates.waiting_phone)
    await message.answer(
        "3️⃣ Telefon raqamini yuboring (masalan <code>+998901234567</code>).\n"
        "Kerak bo'lmasa <code>-</code> yuboring.\nBekor qilish uchun /cancel"
    )


@router.message(StateFilter(AdminSellerStates.waiting_phone), F.text)
async def apply_phone(message: Message, state: FSMContext) -> None:
    phone = seller_service.normalize_phone(message.text)
    await state.update_data(phone=phone)
    await state.set_state(AdminSellerStates.waiting_contact)
    await message.answer(
        "4️⃣ Kontakt (Telegram @username yoki havola) yuboring.\n"
        "Kerak bo'lmasa <code>-</code> yuboring.\nBekor qilish uchun /cancel"
    )


@router.message(StateFilter(AdminSellerStates.waiting_contact), F.text)
async def apply_contact(message: Message, state: FSMContext, session: AsyncSession) -> None:
    contact = seller_service.normalize_contact(message.text)
    data = await state.get_data()
    await state.clear()

    seller, created = await seller_service.get_or_create_seller(
        session,
        int(data.get("user_id") or 0),
        display_name=data.get("display_name"),
        phone=data.get("phone"),
        contact=contact,
        added_by=message.from_user.id,
    )

    verb = "qo'shildi" if created else "yangilandi"
    await message.answer(
        f"✅ Sotuvchi {verb}: <b>{escape_html(seller.display_name or '—')}</b>\n"
        f"🆔 <code>{seller.user_id}</code>\n"
        f"🎁 Referal kodi: <code>{seller.referral_code}</code>\n\n"
        "Endi «💳 Tarif berish» orqali tarif bering."
    )
    await render_card(message, session, seller.id)


@router.callback_query(AdminCB.filter(F.action == "noop"))
async def noop(callback: CallbackQuery) -> None:
    await alert(callback, "")


# ════════════════ Qidiruv va qo'lda kiritish (FSM) ═════════════════
@router.callback_query(SellerCB.filter(F.action == "search"))
async def start_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AdminSellerStates.waiting_search)
    await render(
        callback,
        "🔍 <b>Qidiruv</b>\nSotuvchining ID si yoki ismidan parcha yuboring.\n"
        "Bekor qilish uchun /cancel",
        cancel_kb(),
    )
    await alert(callback, "")


@router.message(StateFilter(AdminSellerStates.waiting_search), F.text)
async def apply_search(message: Message, state: FSMContext, session: AsyncSession) -> None:
    query = (message.text or "").strip()
    await state.clear()
    await render_list(message, session, 0, query=query)


@router.callback_query(SellerCB.filter(F.action == "days"))
async def start_days(callback: CallbackQuery, callback_data: SellerCB, state: FSMContext, session: AsyncSession) -> None:
    seller = await seller_service.get_seller_by_id(session, callback_data.seller_id)
    if seller is None:
        await alert(callback, "⚠️ Sotuvchi topilmadi", show=True)
        return

    await state.clear()
    await state.update_data(seller_id=seller.id)
    await state.set_state(AdminSellerStates.waiting_days)
    await render(
        callback,
        "⏱ <b>Muddatni qo'lda o'zgartirish</b>\n\n"
        "Necha kun qo'shilishini yuboring (masalan <code>15</code>).\n"
        "Bekor qilish uchun /cancel",
        cancel_kb(seller.id),
    )
    await alert(callback, "")


@router.message(StateFilter(AdminSellerStates.waiting_days), F.text)
async def apply_days(message: Message, state: FSMContext, session: AsyncSession, bot) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 1 or int(raw) > 3650:
        await message.answer("⚠️ 1–3650 orasida kun yuboring. Bekor qilish: /cancel")
        return

    data = await state.get_data()
    await state.clear()
    seller = await seller_service.get_seller_by_id(session, int(data.get("seller_id") or 0))
    if seller is None:
        await message.answer("⚠️ Sotuvchi topilmadi.")
        return

    subscription = await subscription_service.active_for(session, seller.id)
    if subscription is None:
        await message.answer("⚠️ Faol obuna yo'q — avval tarif bering.")
        await render_card(message, session, seller.id)
        return

    await subscription_service.extend(session, subscription, int(raw))
    await _notify_seller(
        bot, seller.user_id, f"✅ Tarifingiz {raw} kunga uzaytirildi.\n📅 {fmt_date(subscription.expires_at)}"
    )
    await message.answer(f"✅ +{raw} kun. Yangi muddat: <b>{fmt_date(subscription.expires_at)}</b>")
    await render_card(message, session, seller.id)


@router.callback_query(SellerCB.filter(F.action == "limit"))
async def start_limit(callback: CallbackQuery, callback_data: SellerCB, state: FSMContext, session: AsyncSession) -> None:
    seller = await seller_service.get_seller_by_id(session, callback_data.seller_id)
    subscription = await subscription_service.active_for(session, seller.id) if seller else None
    if seller is None or subscription is None:
        await alert(callback, "⚠️ Faol obuna yo'q", show=True)
        return

    await state.clear()
    await state.update_data(seller_id=seller.id)
    await state.set_state(AdminSellerStates.waiting_ads_limit)
    await render(
        callback,
        "📢 <b>E'lon limiti</b>\n\n"
        f"Hozirgi: <b>{subscription.ads_used}/{subscription.ads_limit}</b>\n"
        "Yangi limitni yuboring (foydalanilgan hisob saqlanadi).\n"
        "Bekor qilish uchun /cancel",
        cancel_kb(seller.id),
    )
    await alert(callback, "")


@router.message(StateFilter(AdminSellerStates.waiting_ads_limit), F.text)
async def apply_limit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 0 or int(raw) > 100000:
        await message.answer("⚠️ 0–100000 orasida son yuboring. Bekor qilish: /cancel")
        return

    data = await state.get_data()
    await state.clear()
    seller = await seller_service.get_seller_by_id(session, int(data.get("seller_id") or 0))
    subscription = await subscription_service.active_for(session, seller.id) if seller else None
    if seller is None or subscription is None:
        await message.answer("⚠️ Faol obuna yo'q.")
        return

    await subscription_service.set_ads_limit(session, subscription, int(raw))
    await message.answer(
        f"✅ Yangi limit: <b>{subscription.ads_used}/{subscription.ads_limit}</b> e'lon"
    )
    await render_card(message, session, seller.id)


# ═══════════════ Profilni tahrirlash (FSM) ═════════════════════════
PROFILE_PROMPTS = {
    "edit_name": ("👤 Yangi ismni yuboring.", AdminSellerStates.editing_name),
    "edit_phone": ("📞 Yangi telefon raqamni yuboring (<code>-</code> — tozalash).", AdminSellerStates.editing_phone),
    "edit_contact": ("🔗 Yangi kontaktni yuboring (<code>-</code> — tozalash).", AdminSellerStates.editing_contact),
    "note": ("🗒 Izoh yozing (<code>-</code> — tozalash).", AdminSellerStates.editing_note),
}


@router.callback_query(SellerCB.filter(F.action.in_(set(PROFILE_PROMPTS))))
async def start_profile_edit(
    callback: CallbackQuery, callback_data: SellerCB, state: FSMContext, session: AsyncSession
) -> None:
    seller = await seller_service.get_seller_by_id(session, callback_data.seller_id)
    if seller is None:
        await alert(callback, "⚠️ Sotuvchi topilmadi", show=True)
        return

    prompt, next_state = PROFILE_PROMPTS[callback_data.action]
    await state.clear()
    await state.update_data(seller_id=seller.id, field=callback_data.action)
    await state.set_state(next_state)
    await render(callback, f"{prompt}\nBekor qilish uchun /cancel", cancel_kb(seller.id))
    await alert(callback, "")


@router.message(
    StateFilter(
        AdminSellerStates.editing_name,
        AdminSellerStates.editing_phone,
        AdminSellerStates.editing_contact,
        AdminSellerStates.editing_note,
    )
)
async def apply_profile_edit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Profil maydonini saqlash (FSM `field` bo'yicha)."""
    data = await state.get_data()
    field = data.get("field")
    seller = await seller_service.get_seller_by_id(session, int(data.get("seller_id") or 0))
    await state.clear()

    if seller is None or not field:
        await message.answer("⚠️ Sotuvchi topilmadi.")
        return

    raw = (message.text or "").strip()
    value: str | None = raw
    if raw in ("-", "yo'q", "tozalash"):
        value = None

    mapping = {
        "edit_name": "display_name",
        "edit_phone": "phone",
        "edit_contact": "contact",
        "note": "note",
    }
    key = mapping.get(field)
    if key is None:
        await message.answer("⚠️ Noma'lum maydon.")
        return

    await seller_service.update_profile(session, seller, **{key: value})
    await message.answer("✅ Saqlandi.")
    await render_card(message, session, seller.id)


@router.message(StateFilter(AdminSellerStates), Command("cancel"))
async def cancel_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    await state.clear()
    seller_id = int(data.get("seller_id") or 0)
    if seller_id:
        await render_card(message, session, seller_id)
    else:
        await render_list(message, session, 0)


# ══════════════════════════ Yordamchi ═════════════════════════════
async def _notify_seller(bot, user_id: int, text: str) -> None:
    """Sotuvchiga shaxsiy xabar (bloklagan bo'lsa jim o'tiladi)."""
    from aiogram.exceptions import TelegramAPIError

    try:
        await bot.send_message(user_id, text, disable_web_page_preview=True)
    except TelegramAPIError as exc:
        logger.debug("Sotuvchi {} ga xabar yuborilmadi: {}", user_id, exc)


__all__ = ["render_card", "render_list", "router"]
_ = (human_int, utcnow, human_delta, AdminCB, PER_PAGE_SELLERS)
