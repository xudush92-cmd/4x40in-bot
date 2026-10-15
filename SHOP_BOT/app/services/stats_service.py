"""Statistika: admin panel uchun jamlanma ko'rsatkichlar."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdStatus, PaymentStatus, SellerStatus, SubscriptionStatus
from app.db.models import (
    Ad,
    Category,
    ErrorLog,
    Group,
    Payment,
    PostLog,
    Seller,
    Subscription,
    User,
    Violation,
)
from app.utils.time import utcnow


async def _count(session: AsyncSession, model: Any, *where: Any) -> int:
    stmt = select(func.count()).select_from(model)
    if where:
        stmt = stmt.where(*where)
    return int((await session.execute(stmt)).scalar_one())


async def get_overview(session: AsyncSession) -> dict[str, Any]:
    """Umumiy ko'rsatkichlar (asosiy panel ekrani uchun)."""
    now = utcnow()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    approved_sum = (
        await session.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.status == PaymentStatus.APPROVED,
                Payment.decided_at >= week_ago,
            )
        )
    ).scalar_one()

    return {
        "users": await _count(session, User),
        "users_new_24h": await _count(session, User, User.created_at >= day_ago),
        "sellers": await _count(session, Seller, Seller.status == SellerStatus.ACTIVE),
        "sellers_pending": await _count(session, Seller, Seller.status == SellerStatus.PENDING),
        "sellers_blocked": await _count(session, Seller, Seller.status == SellerStatus.BLOCKED),
        "groups": await _count(session, Group),
        "groups_active": await _count(session, Group, Group.is_active.is_(True)),
        "groups_paused": await _count(session, Group, Group.is_active.is_(False)),
        "categories": await _count(session, Category),
        "ads_total": await _count(session, Ad),
        "ads_active": await _count(session, Ad, Ad.status == AdStatus.ACTIVE),
        "ads_pending": await _count(session, Ad, Ad.status == AdStatus.PENDING),
        "ads_paused": await _count(session, Ad, Ad.status == AdStatus.PAUSED),
        "subscriptions_active": await _count(
            session, Subscription,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.expires_at > now,
        ),
        "payments_pending": await _count(session, Payment, Payment.status == PaymentStatus.PENDING),
        "payments_week_sum": float(approved_sum or 0),
        "posts_24h": await _count(session, PostLog, PostLog.status == "ok", PostLog.created_at >= day_ago),
        "violations_24h": await _count(session, Violation, Violation.created_at >= day_ago),
        "errors_unresolved": await _count(session, ErrorLog, ErrorLog.resolved_at.is_(None)),
    }


async def get_menu_counts(session: AsyncSession) -> dict[str, int]:
    """Asosiy panel tugmalaridagi hisoblagichlar (arzon so'rovlar)."""
    from app.db.models import ErrorLog

    return {
        "groups": await _count(session, Group),
        "categories": await _count(session, Category),
        "sellers": await _count(session, Seller),
        "ads": await _count(session, Ad),
        "moderation": await _count(session, Ad, Ad.status == AdStatus.PENDING),
        "payments": await _count(session, Payment, Payment.status == PaymentStatus.PENDING),
        "users": await _count(session, User),
        "errors": await _count(session, ErrorLog, ErrorLog.resolved_at.is_(None)),
    }


def format_overview(data: dict[str, Any]) -> str:
    """Statistikani Telegram uchun matnga aylantirish."""
    return (
        "📊 <b>Statistika</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Foydalanuvchilar: <b>{data['users']:,}</b>  "
        f"(+{data['users_new_24h']:,} / 24 soat)\n"
        f"🛒 Sotuvchilar: <b>{data['sellers']:,}</b> faol, "
        f"{data['sellers_pending']:,} kutilmoqda, {data['sellers_blocked']:,} bloklangan\n"
        f"📅 Faol obunalar: <b>{data['subscriptions_active']:,}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Guruhlar: <b>{data['groups']:,}</b> "
        f"(✅ {data['groups_active']:,} / ⏸ {data['groups_paused']:,})\n"
        f"🗂 Toifalar: <b>{data['categories']:,}</b>\n"
        f"📢 E'lonlar: <b>{data['ads_total']:,}</b> "
        f"(faol {data['ads_active']:,}, moderatsiyada {data['ads_pending']:,}, "
        f"pauzada {data['ads_paused']:,})\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 Joylangan xabarlar (24 soat): <b>{data['posts_24h']:,}</b>\n"
        f"⚠️ Qoidabuzarlik (24 soat): <b>{data['violations_24h']:,}</b>\n"
        f"🧾 Kutilayotgan cheklar: <b>{data['payments_pending']:,}</b>\n"
        f"💰 Tasdiqlangan to'lov (7 kun): <b>{data['payments_week_sum']:,.0f} so'm</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🐞 Hal qilinmagan xatolar: <b>{data['errors_unresolved']:,}</b>"
    ).replace(",", " ")
