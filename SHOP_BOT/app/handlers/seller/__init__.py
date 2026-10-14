"""🛒 Sotuvchi paneli (Phase 2 → 3).

Phase 2 da to'liq ishlaydigan qism:
  * 📅 Mening tarifim — tarif, muddat, qolgan kun, limit, eslatma holati
  * 💳 Tariflarni ko'rish — katalog (to'lov va chek Phase 5 da)
  * ☎️ Yordam — admin bilan bog'lanish
  * 🎁 Referal — kod va havola (bonuslar Phase 8 da)

Phase 3 da qo'shiladi: e'lon qo'shish ustasi va "Mening e'lonlarim".

Diqqat: sotuvchi yozuvi `seller_service.get_seller()` orqali olinadi —
`users` jadvali bilan FK yo'q (REJA.md 4.3), shuning uchun middleware
faqat `user` ni beradi.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Seller
from app.filters import IsSeller, PrivateChat
from app.keyboards.callbacks import SellerPanelCB
from app.keyboards.seller_panel import (
    back_to_menu_kb,
    seller_menu_kb,
    tariff_screen_kb,
    tariffs_catalog_kb,
)
from app.services import seller_service, subscription_service, tariff_service
from app.services.settings_service import settings_service
from app.utils.text import escape_html, fmt_amount, truncate
from app.utils.time import days_left, fmt_date
from app.utils.tg import alert, render

seller_router = Router(name="seller")
# Faqat sotuvchi, faqat shaxsiy chat, faqat sotuvchi paneli callback'lari
seller_router.callback_query.filter(SellerPanelCB.filter(), PrivateChat(), IsSeller())

PENDING_PHASES = {
    "ads": ("📢 Mening e'lonlarim", 3),
    "new_ad": ("➕ Yangi e'lon", 3),
}


# ═══════════════════════════ Yordamchilar ═════════════════════════
async def _seller_of(callback: CallbackQuery, session: AsyncSession) -> Seller | None:
    """Callback egasining sotuvchi yozuvi (bo'lmasa ogohlantiradi)."""
    seller = await seller_service.get_seller(session, callback.from_user.id)
    if seller is None:
        await alert(callback, "⚠️ Siz sotuvchi sifatida ro'yxatdan o'tmagansiz.", show=True)
        return None
    return seller


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
            "Tarif olish uchun admin bilan bog'laning — tarif berilgach e'lon "
            "joylash imkoniyati ochiladi.",
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
            "Admin bilan bog'laning."
        )

    return "\n".join(lines), active is not None


async def _catalog_text(session: AsyncSession) -> str:
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
        f"Tarif olish uchun: <b>{escape_html(str(support))}</b>\n"
        "<i>To'lov va chek yuborish Phase 5 da qo'shiladi.</i>"
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
async def on_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Sotuvchi menyusi (tarif holatiga qarab tugmalar)."""
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
            "Yangilash uchun admin bilan bog'laning."
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
async def on_tariff(callback: CallbackQuery, session: AsyncSession) -> None:
    """📅 Mening tarifim."""
    seller = await _seller_of(callback, session)
    if seller is None:
        return

    text, has_active = await _tariff_text(seller, session)
    await render(callback, text, tariff_screen_kb(has_subscription=has_active))
    await alert(callback, "")


@seller_router.callback_query(SellerPanelCB.filter(F.action == "tariffs"))
async def on_catalog(callback: CallbackQuery, session: AsyncSession) -> None:
    """💳 Tariflar katalogi."""
    await render(callback, await _catalog_text(session), tariffs_catalog_kb())
    await alert(callback, "")


@seller_router.callback_query(SellerPanelCB.filter(F.action == "referral"))
async def on_referral(callback: CallbackQuery, session: AsyncSession) -> None:
    seller = await _seller_of(callback, session)
    if seller is None:
        return
    await render(callback, await _referral_text(seller, session), back_to_menu_kb())
    await alert(callback, "")


@seller_router.callback_query(SellerPanelCB.filter(F.action == "support"))
async def on_support(callback: CallbackQuery, session: AsyncSession) -> None:
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


@seller_router.callback_query(SellerPanelCB.filter(F.action.in_(set(PENDING_PHASES))))
async def on_pending_sections(callback: CallbackQuery, callback_data: SellerPanelCB) -> None:
    """E'lon bo'limlari — Phase 3 da to'liq ishga tushadi."""
    title, phase = PENDING_PHASES[callback_data.action]
    await alert(callback, f"{title} — Phase {phase} da qo'shiladi.", show=True)


# ═══════════════════ Tashqi foydalanish uchun ══════════════════════
async def seller_status_text(seller: Seller, session: AsyncSession) -> str:
    """`/start` uchun qisqa tarif holati satri."""
    subscription = await subscription_service.active_for(session, seller.id)
    if subscription is None:
        latest = await subscription_service.latest_for(session, seller.id)
        if latest is None:
            return "⛔️ Tarif berilmagan — admin bilan bog'laning."
        return f"🔴 Tarif muddati tugagan ({fmt_date(latest.expires_at)}) — yangilash kerak."

    tariff_name = subscription.tariff.name if subscription.tariff else "—"
    left = days_left(subscription.expires_at)
    return (
        f"💳 <b>{escape_html(tariff_name)}</b>\n"
        f"🕒 Qolgan: <b>{max(0, left)} kun</b>  ·  📢 {subscription.ads_used}/{subscription.ads_limit}"
    )


def seller_balance_line(seller: Seller) -> str:
    return f"💵 Balans: {fmt_amount(seller.balance)}"


__all__ = ["seller_balance_line", "seller_router", "seller_status_text"]
_ = logger
