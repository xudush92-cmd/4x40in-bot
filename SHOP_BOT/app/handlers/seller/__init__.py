"""🛒 Sotuvchi paneli (Phase 2 → 3).

Ishlaydigan qismlar:
  * 📅 Mening tarifim — tarif, muddat, qolgan kun, limit, eslatma holati
  * 📢 Mening e'lonlarim — ro'yxat, kartochka, statistika (Phase 3)
  * ➕ Yangi e'lon — usta: toifa → matn → narx → aloqa → rasmlar → yuborish (Phase 3)
  * 💳 Tariflarni ko'rish — katalog → To'lash → chek (Phase 5)
  * ☎️ Yordam — admin bilan bog'lanish
  * 🎁 Referal — kod va havola (bonuslar Phase 8 da)

Diqqat: sotuvchi yozuvi `seller_service.get_seller()` orqali olinadi —
`users` jadvali bilan FK yo'q (REJA.md 4.3), shuning uchun middleware
faqat `user` ni beradi.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Seller, Tariff
from app.filters import IsSeller, PrivateChat
from app.handlers.seller import ads as ad_handlers
from app.keyboards.callbacks import SellerPanelCB
from app.keyboards.seller_panel import (
    back_to_menu_kb,
    seller_menu_kb,
    tariff_screen_kb,
    tariffs_catalog_kb,
)
from app.services import seller_service, subscription_service, tariff_service
from app.services.settings_service import settings_service
from app.states import SellerPaymentStates
from app.utils.text import escape_html, fmt_amount, truncate
from app.utils.tg import alert, render
from app.utils.time import days_left, fmt_date

seller_router = Router(name="seller")
# Faqat sotuvchi, faqat shaxsiy chat, faqat sotuvchi paneli callback'lari
seller_router.callback_query.filter(SellerPanelCB.filter(), PrivateChat(), IsSeller())

# Eslatma: `ad_handlers.router` SHU router ichiga qo'shilmaydi!
# `seller_router.callback_query.filter(SellerPanelCB...)` — router darajasidagi
# filtr bo'lib, u **barcha** ichki router'larga ham qo'llanadi (aiogram:
# `check_root_filters` sub-router'lardan oldin ishlaydi). Shuning uchun e'lon
# router'i `app/handlers/__init__.py` da alohida ulanadi.


# ═══════════════════════════ Yordamchilar ═════════════════════════
async def _seller_of(callback: CallbackQuery, session: AsyncSession) -> Seller | None:
    """Callback egasining sotuvchi yozuvi (bo'lmasa ogohlantiradi)."""
    seller = await seller_service.get_seller(session, callback.from_user.id)
    if seller is None:
        await alert(callback, "⚠️ Siz sotuvchi sifatida ro'yxatdan o'tmagansiz.", show=True)
        return None
    return seller


async def _leave_payment(state: FSMContext) -> None:
    """Boshqa bo'limga chiqishda eski chek kutish holati tasodifan ishlamasin."""
    if await state.get_state() == SellerPaymentStates.waiting_receipt.state:
        await state.clear()


# ═══════════════════════════ Matnlar ═══════════════════════════════
async def _tariff_text(seller: Seller, session: AsyncSession) -> tuple[str, bool]:
    """«Mening tarifim» ekrani. (matn, faol_obuna_bormi)."""
    latest = await subscription_service.latest_for(session, seller.id)
    active = await subscription_service.active_for(session, seller.id)

    lines = ["📅 <b>Mening tarifim</b>", "━━━━━━━━━━━━━━━━━━━━"]

    if latest is None:
        lines += [
            "⛔️ <b>Hozircha tarifingiz yo'q</b>",
            "",
            "Tarif olish uchun katalogdan «To'lash»ni tanlang yoki admin bilan bog'laning. "
            "Obuna faqat admin to'lovni tasdiqlagach faollashadi.",
        ]
        return "\n".join(lines), False

    tariff = await tariff_service.get_tariff(session, latest.tariff_id)
    left = subscription_service.days_left(latest)

    lines += [
        f"💳 Tarif: <b>{escape_html(tariff.name if tariff else '—')}</b>",
        f"📌 Holat: <b>{subscription_service.status_title(latest)}</b>",
        f"📆 Boshlangan: {fmt_date(latest.starts_at)}",
        f"⏳ Tugash sanasi: <b>{fmt_date(latest.expires_at)}</b>",
    ]

    if left >= 0:
        warning = "  ⚠️ tez tugaydi!" if left <= 3 else ""
        lines.append(f"🕒 Qolgan muddat: <b>{left} kun</b>{warning}")
    else:
        lines.append("🔴 <b>Muddati o'tgan</b> — tarifni yangilash kerak.")

    lines += [
        "━━━━━━━━━━━━━━━━━━━━",
        f"📢 E'lon limiti: <b>{latest.ads_used}/{latest.ads_limit}</b> (qoldi {latest.ads_left})",
    ]
    if tariff is not None:
        lines.append(f"🖼 Har e'londa rasm: <b>{tariff.max_photos}</b> tagacha")
        if tariff.description:
            lines.append(f"\n📝 {escape_html(truncate(tariff.description, 200))}")

    if latest.reminder_sent_at is not None and left >= 0:
        lines.append("\n🔔 <i>Tarif tugashi haqida eslatma yuborilgan.</i>")

    if active is None:
        lines.append(
            "\n⚠️ <b>E'lon joylash vaqtincha to'xtatilgan</b> (muddat tugagan). "
            "Katalogdan tarif sotib oling yoki admin bilan bog'laning."
        )

    return "\n".join(lines), active is not None


async def _catalog_text(session: AsyncSession, tariffs: list[Tariff] | None = None) -> str:
    if tariffs is None:
        tariffs = await tariff_service.list_all_active(session)
    lines = ["💳 <b>Tariflar</b>", "━━━━━━━━━━━━━━━━━━━━"]
    if not tariffs:
        lines.append("📭 Hozircha faol tarif yo'q. Admin bilan bog'laning.")
        return "\n".join(lines)

    support = await settings_service.get("support_contact", "@admin", session)
    for tariff in tariffs:
        trial = " 🎁 <b>sinov</b>" if tariff.is_trial else ""
        lines.append(
            f"\n<b>{escape_html(tariff.name)}</b>{trial}\n"
            f"   ├ 💰 {tariff_service.format_price(tariff)}\n"
            f"   ├ 📅 {tariff.duration_days} kun\n"
            f"   ├ 📢 {tariff.max_ads} ta e'lon\n"
            f"   └ 🖼 har birida {tariff.max_photos} ta rasm"
        )
        if tariff.description:
            lines.append(f"   <i>{escape_html(truncate(tariff.description, 120))}</i>")

    lines.append(
        "\n━━━━━━━━━━━━━━━━━━━━\n"
        "Tarif olish uchun «💳 To'lash» tugmasini bosing, rekvizitga pul o'tkazib "
        "chek rasmini yuboring. Obuna faqat admin tasdiqlagach faollashadi.\n"
        f"Muammo bo'lsa: <b>{escape_html(str(support))}</b>"
    )
    return "\n".join(lines)


async def _referral_text(seller: Seller, session: AsyncSession) -> str:
    code = await seller_service.ensure_referral_code(session, seller)
    bot_username = await settings_service.get("bot_username", "", session)
    link = f"https://t.me/{bot_username}?start=ref_{code}" if bot_username else f"ref_{code}"
    return (
        "🎁 <b>Referal</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🔑 Sizning kodingiz: <code>{code}</code>\n"
        f"🔗 Havola: <code>{link}</code>\n\n"
        "<i>Havoladan kelgan har bir sotuvchi uchun bonus tizimi Phase 8 da "
        "(«🤝 Referal» bo'limi) ishga tushadi.</i>"
    )


# ══════════════════════════ Callback'lar ═══════════════════════════
@seller_router.callback_query(SellerPanelCB.filter(F.action == "menu"))
async def on_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Sotuvchi menyusi (tarif holatiga qarab tugmalar)."""
    await _leave_payment(state)
    seller = await _seller_of(callback, session)
    if seller is None:
        return

    active = await subscription_service.active_for(session, seller.id)
    latest = await subscription_service.latest_for(session, seller.id)
    stats = await seller_service.get_seller_stats(session, seller)

    if latest is None:
        header = "🛒 <b>Sotuvchi paneli</b>\n\n⛔️ Tarifingiz hali berilmagan."
    elif active is None:
        header = (
            "🛒 <b>Sotuvchi paneli</b>\n\n"
            f"⚠️ Tarif muddati tugagan ({fmt_date(latest.expires_at)}).\n"
            "Yangilash uchun katalogdan tarifni tanlang yoki admin bilan bog'laning."
        )
    else:
        left = subscription_service.days_left(active)
        tariff_name = active.tariff.name if active.tariff else "—"
        header = (
            "🛒 <b>Sotuvchi paneli</b>\n\n"
            f"💳 Tarif: <b>{escape_html(tariff_name)}</b>\n"
            f"🕒 Qolgan: <b>{left} kun</b>  ·  📢 Limit: <b>{active.ads_used}/{active.ads_limit}</b>"
        )

    await render(
        callback,
        header,
        seller_menu_kb(has_subscription=active is not None, ads_count=stats["ads_active"]),
    )
    await alert(callback, "")


@seller_router.callback_query(SellerPanelCB.filter(F.action == "tariff"))
async def on_tariff(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """📅 Mening tarifim."""
    await _leave_payment(state)
    seller = await _seller_of(callback, session)
    if seller is None:
        return

    text, has_active = await _tariff_text(seller, session)
    await render(callback, text, tariff_screen_kb(has_subscription=has_active))
    await alert(callback, "")


@seller_router.callback_query(SellerPanelCB.filter(F.action == "tariffs"))
async def on_catalog(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """💳 Tariflar katalogi."""
    await _leave_payment(state)
    tariffs = await tariff_service.list_all_active(session)
    await render(callback, await _catalog_text(session, tariffs), tariffs_catalog_kb(tariffs))
    await alert(callback, "")


@seller_router.callback_query(SellerPanelCB.filter(F.action == "referral"))
async def on_referral(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await _leave_payment(state)
    seller = await _seller_of(callback, session)
    if seller is None:
        return
    await render(callback, await _referral_text(seller, session), back_to_menu_kb())
    await alert(callback, "")


@seller_router.callback_query(SellerPanelCB.filter(F.action == "support"))
async def on_support(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await _leave_payment(state)
    support = await settings_service.get("support_contact", "@admin", session)
    await render(
        callback,
        "☎️ <b>Yordam</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Admin bilan bog'lanish: <b>{escape_html(str(support))}</b>\n\n"
        "<i>Savol, tarif olish yoki muammo bo'lsa shu manzilga yozing.</i>",
        back_to_menu_kb(),
    )
    await alert(callback, "")


@seller_router.callback_query(SellerPanelCB.filter(F.action == "ads"))
async def on_my_ads(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """📢 Mening e'lonlarim (Phase 3)."""
    await _leave_payment(state)
    await ad_handlers.open_ads_list(callback, session)


@seller_router.callback_query(SellerPanelCB.filter(F.action == "new_ad"))
async def on_new_ad(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """➕ Yangi e'lon ustasi (Phase 3)."""
    await _leave_payment(state)
    await ad_handlers.start_ad_wizard(callback, session, state)


# ═══════════════════ Tashqi foydalanish uchun ══════════════════════
async def seller_status_text(seller: Seller, session: AsyncSession) -> str:
    """`/start` uchun qisqa tarif holati satri."""
    subscription = await subscription_service.active_for(session, seller.id)
    if subscription is None:
        latest = await subscription_service.latest_for(session, seller.id)
        if latest is None:
            return "⛔️ Tarif yo'q — katalogdan tanlang yoki admin bilan bog'laning."
        return f"🔴 Tarif muddati tugagan ({fmt_date(latest.expires_at)}) — yangilash kerak."

    tariff_name = subscription.tariff.name if subscription.tariff else "—"
    left = days_left(subscription.expires_at)
    return (
        f"💳 <b>{escape_html(tariff_name)}</b>\n"
        f"🕒 Qolgan: <b>{max(0, left)} kun</b>  ·  📢 {subscription.ads_used}/{subscription.ads_limit}"
    )


def seller_balance_line(seller: Seller) -> str:
    return f"💵 Balans: {fmt_amount(seller.balance)}"


__all__ = ["ad_handlers", "seller_balance_line", "seller_router", "seller_status_text"]
_ = logger
