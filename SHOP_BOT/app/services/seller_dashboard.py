"""UX-3: sotuvchining birinchi ekranida mavjud holatlarni jamlash.

E'lonlar soni umumiy status agregatidan, limit esa aynan faol obuna
`ads_used/ads_limit` maydonidan olinadi. Ikkisi teng bo'lishi shart emas:
qoralama va tarixiy e'lonlar yangi obuna limitiga qo'shilmaydi.
"""

from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdStatus, PaymentStatus, SellerStatus, SubscriptionStatus
from app.db.models import Ad, Category, FreeAd, FreeEntitlement, Group, Payment, Seller
from app.services import ad_service, free_ad_service, payment_service, subscription_service
from app.services.posting_service import _allowed
from app.services.settings_service import settings_service
from app.utils.text import escape_html, truncate
from app.utils.time import ensure_aware, fmt_date, utcnow


@dataclass(frozen=True)
class SellerOverview:
    text: str
    has_subscription: bool
    can_create_ad: bool
    ads_count: int  # faol e'lonlar (tugmadagi sanoq)


def _payment_line(payment: Payment | None) -> str:
    if payment is None:
        return "🧾 Oxirgi chek: yuborilmagan"
    label = {
        PaymentStatus.PENDING: "🕓 Tekshiruvda",
        PaymentStatus.APPROVED: "✅ Tasdiqlangan",
        PaymentStatus.REJECTED: "❌ Rad etilgan",
        PaymentStatus.CANCELLED: "⏸ Bekor qilingan",
    }.get(payment.status, "Noma'lum holat")
    line = f"🧾 Oxirgi chek #{payment.id}: <b>{label}</b>"
    if payment.status == PaymentStatus.REJECTED and payment.reason:
        line += f" · Sabab: {escape_html(truncate(payment.reason, 160))}"
    return line


async def get_overview(session: AsyncSession, seller: Seller, bot: Bot | None = None) -> SellerOverview:
    """/start va «kabinet» callback'ida aynan bir xil hisoblagich/ustuvorlik."""
    active = await subscription_service.active_for(session, seller.id)
    stats = await ad_service.seller_ads_stats(session, seller.id)
    payments = await payment_service.list_payments(session, seller_id=seller.id, limit=1)
    payment = payments[0] if payments else None
    can_create, reason = await subscription_service.can_publish(session, seller)

    lines = ["👤 Holat: <b>✅ Sotuvchi paneli ochiq</b> (tarif alohida)"]
    if active is None:
        latest = await subscription_service.latest_for(session, seller.id)
        if latest is None:
            lines.append("💳 Tarif yo'q — Tarifingiz hali berilmagan.")
        elif latest.status == SubscriptionStatus.CANCELLED:
            lines.append("💳 Tarif: <b>faol emas</b> (oldingi obuna bekor qilingan).")
        elif latest.status == SubscriptionStatus.EXPIRED or subscription_service.is_expired(latest):
            lines.append(f"💳 Tarif: <b>muddati tugagan</b> ({fmt_date(latest.expires_at)}).")
        else:
            lines.append(f"💳 Tarif: <b>faol emas</b> ({subscription_service.status_title(latest)}).")
        lines.append("📢 E'lon limiti: faol tarif yo'q — yangi e'lon yuborib bo'lmaydi.")
    else:
        plan = subscription_service.terms_for(active)
        tariff_name = str(plan.get("name") or "—")
        days = max(0, subscription_service.days_left(active))
        lines += [
            f"💳 Tarif: <b>{escape_html(tariff_name)}</b> · {days} kun qoldi "
            f"({fmt_date(active.expires_at)} gacha)",
            f"📢 E'lon limiti: <b>{active.ads_used}/{active.ads_limit}</b> ishlatilgan "
            f"· <b>{active.ads_left}</b> ta qolgan",
            f"⏱ Shaxsiy joylash oralig'i: <b>{subscription_service.interval_for(active) // 60} daqiqa</b> "
            "(Startdan keyin birinchi post shu vaqtda)",
        ]

    lines += [
        f"📢 E'lonlar: <b>{stats[AdStatus.ACTIVE]}</b> faol · "
        f"<b>{stats[AdStatus.PENDING]}</b> tekshiruvda · "
        f"<b>{stats[AdStatus.REJECTED]}</b> rad · "
        f"<b>{stats[AdStatus.DRAFT]}</b> qoralama",
        _payment_line(payment),
    ]
    paid_ads = (await session.execute(select(Ad, Category, Group)
        .join(Category, Category.id == Ad.category_id)
        .outerjoin(Group, Group.id == Category.group_id)
        .where(Ad.seller_id == seller.id, Ad.status.in_((AdStatus.ACTIVE, AdStatus.PENDING,
                                                          AdStatus.PAUSED))))).all()
    free_ads = (await session.execute(select(FreeAd, Group, FreeEntitlement)
        .join(Group, Group.id == FreeAd.group_id)
        .outerjoin(FreeEntitlement,
            (FreeEntitlement.user_id == FreeAd.user_id)
            & (FreeEntitlement.group_id == FreeAd.group_id))
        .where(FreeAd.user_id == seller.user_id))).all()
    groups = {category.group_id for _, category, _ in paid_ads if category.group_id is not None}
    groups.update(ad.group_id for ad, _, _ in free_ads)
    values = await settings_service.get_all(session)
    global_on = not (values["kill_switch"] or values["maintenance_mode"])
    paid_terms = subscription_service.terms_for(active) if active else {}
    paid_on = bool(global_on and values["posting_enabled_global"] and active
                   and seller.status == SellerStatus.ACTIVE
                   and not paid_terms.get("is_trial")
                   and float(paid_terms.get("price") or 0) > 0)
    paid_running = sum(bool(paid_on and ad.status == AdStatus.ACTIVE
                            and not ad.admin_paused and ad.next_eligible_at
                            and category.is_active and category.rotation
                            and not category.rotation.is_paused
                            and _allowed(paid_terms.get("allowed_category_ids"), category.id)
                            and _allowed(paid_terms.get("allowed_group_ids"), category.group_id)
                            and chat and chat.is_active and chat.bot_is_admin
                            and chat.settings and chat.settings.posting_enabled)
                       for ad, category, chat in paid_ads)
    now = utcnow()
    free_running = 0
    if bot and global_on and values["posting_enabled_global"] and values["free_plan_enabled"]:
        for ad, chat, access in free_ads:
            if (ad.review_status == "approved" and ad.desired_running
                    and not ad.admin_paused and ad.next_post_at
                    and access and ensure_aware(access.expires_at) > now
                    and free_ad_service.ready_group(chat)
                    and await free_ad_service.is_member(bot, chat.tg_chat_id, seller.user_id)):
                free_running += 1
    lines.append(f"👥 E'lon guruhlari: <b>{len(groups)}</b> ta · "
                 f"🎁 bepul e'lon: <b>{len(free_ads)}</b> ta")
    lines.append(f"▶️ Haqiqiy navbat: <b>{paid_running}</b> pullik, <b>{free_running}</b> bepul "
                 + ("ishlayapti" if paid_running or free_running else "to'xtagan/kutmoqda"))
    if free_ads:
        lines.append("🎁 Bepul navbatda admin tasdig'i, N/davr va Telegram a'zoligi tekshiriladi.")
    if stats[AdStatus.PAUSED] or stats[AdStatus.EXPIRED]:
        lines.append(f"⏸ Qo'shimcha: {stats[AdStatus.PAUSED]} pauzada · "
                     f"{stats[AdStatus.EXPIRED]} muddati o'tgan")

    if seller.status in {SellerStatus.BLOCKED, SellerStatus.DELETED}:
        next_step = "☎️ Hisob cheklangan. Yordam orqali adminga yozing."
    elif active is None:
        if payment and payment.status == PaymentStatus.PENDING:
            next_step = "🕓 Chek tekshiruvda. Admin qarorini kuting; tarif faollashmaguncha e'lon yubormang."
        elif payment and payment.status == PaymentStatus.REJECTED:
            next_step = "🧾 Rad sababini «To'lovlarim»da ko'ring va to'g'ri chek yuboring."
        else:
            next_step = "💳 Katalogdan tarifni tanlang; chekni admin tasdiqlagach e'lon yuborishingiz mumkin."
    elif not can_create:
        if active.ads_left <= 0:
            next_step = "📢 Limit tugadi. Tarifni uzaytiring yoki mavjud e'lonlarni boshqaring."
        else:
            next_step = f"☎️ {escape_html(reason)}"
    elif payment and payment.status == PaymentStatus.REJECTED:
        next_step = "🧾 Oxirgi chek rad etilgan; sababni «To'lovlarim»da ko'ring. Faol tarif limiti alohida."
    elif stats[AdStatus.REJECTED]:
        next_step = "✏️ Rad etilgan e'lonni «Mening e'lonlarim»da tuzating."
    elif stats[AdStatus.PENDING]:
        next_step = "🕓 E'lon admin tekshiruvida; natijani kuting yoki qolgan limitdan foydalaning."
    elif stats[AdStatus.DRAFT]:
        next_step = "✏️ Qoralamani yakunlang yoki yangi e'lon yarating."
    elif subscription_service.days_left(active) <= 3:
        next_step = "⏳ Tarif tez tugaydi; muddatni uzaytirishni rejalashtiring."
    else:
        next_step = "➕ Yangi e'lon yarating yoki mavjudlarini boshqaring."
    lines.append(f"\n➡️ <b>Keyingi qadam:</b> {next_step}")
    return SellerOverview(
        text="\n".join(lines), has_subscription=active is not None,
        can_create_ad=can_create, ads_count=stats[AdStatus.ACTIVE],
    )
