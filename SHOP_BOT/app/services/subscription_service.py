"""Obunalar servisi (Phase 2).

Obuna = sotuvchining tarifi: muddat + limitlar. Bu yerdagi mantiq Phase 3
(e'lon qo'shish) va Phase 5 (to'lov tasdiqlanganda avtomatik obuna) tomonidan
ishlatiladi.

Qoidalar (REJA.md 4.3, 8.2):
  * Obunani faqat admin beradi (yoki to'lov tasdiqlanganda tizim).
  * Bir xil tarifni qayta berish → **uzaytirish** (muddat va limit qo'shiladi).
  * Boshqa tarifga o'tish → eski obuna `cancelled`, yangisi bugundan boshlanadi.
  * Muddati o'tsa → `grace` (agar sozlamada kun berilgan bo'lsa) → `expired`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import SellerStatus, SubscriptionStatus
from app.db.models import Ad, Seller, Subscription, SubscriptionGrant, Tariff
from app.utils.time import ensure_aware, utcnow

MAX_ADS_LIMIT = 1000000  # qo'lda beriladigan obuna kvotasining yuqori chegarasi
ACTIVE_STATUSES = (SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE)


def tariff_terms(tariff: Tariff, *, ads_limit: int | None = None,
                 duration_days: int | None = None) -> dict[str, Any]:
    """Xarid paytidagi narx/huquq nusxasi; JSONda Decimal saqlanmaydi."""
    return {
        "name": tariff.name, "price": str(tariff.price or 0),
        "currency": tariff.currency or "UZS",
        "is_trial": bool(tariff.is_trial),
        "duration_days": duration_days if duration_days is not None else tariff.duration_days,
        "max_ads": ads_limit if ads_limit is not None else tariff.max_ads,
        "max_photos": tariff.max_photos,
        "interval_sec": tariff.interval_sec or 1800,
        "allowed_group_ids": tariff.allowed_group_ids,
        "allowed_category_ids": tariff.allowed_category_ids,
    }


def terms_for(subscription: Subscription) -> dict[str, Any]:
    """Eski test/sxema yozuvi uchun fallback; migratsiya haqiqiylarini to'ldiradi."""
    return subscription.terms or tariff_terms(subscription.tariff, ads_limit=subscription.ads_limit)


def interval_for(subscription: Subscription) -> int:
    return max(60, int(terms_for(subscription).get("interval_sec") or 1800))


# ─────────────────────────── O'qish ────────────────────────────────
async def get_subscription(session: AsyncSession, subscription_id: int) -> Subscription | None:
    return await session.get(Subscription, subscription_id)


async def active_for(session: AsyncSession, seller_id: int) -> Subscription | None:
    """Sotuvchining amaldagi (muddati o'tmagan) obunasi."""
    now = utcnow()
    stmt = (
        select(Subscription)
        .where(
            Subscription.seller_id == seller_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.expires_at > now,
        )
        .order_by(Subscription.expires_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def latest_for(session: AsyncSession, seller_id: int) -> Subscription | None:
    """Eng oxirgi obuna (muddati o'tgan bo'lsa ham) — kartochka uchun."""
    stmt = (
        select(Subscription)
        .where(Subscription.seller_id == seller_id)
        .order_by(Subscription.created_at.desc(), Subscription.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def history(session: AsyncSession, seller_id: int, limit: int = 10) -> list[Subscription]:
    stmt = (
        select(Subscription)
        .where(Subscription.seller_id == seller_id)
        .order_by(Subscription.created_at.desc(), Subscription.id.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_active(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Subscription)
                .where(
                    Subscription.status == SubscriptionStatus.ACTIVE,
                    Subscription.expires_at > utcnow(),
                )
            )
        ).scalar_one()
    )


async def stats(session: AsyncSession, subscription: Subscription) -> dict[str, int]:
    """Obuna kartochkasi uchun raqamlar.

    `ads` jadvalida obunaga to'g'ridan-to'g'ri havola yo'q (ataylab) —
    shu sababli limit hisobi obuna davrida yaratilgan e'lonlar bo'yicha.
    """
    starts = ensure_aware(subscription.starts_at) or utcnow()
    created_in_window = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Ad)
                .where(
                    Ad.seller_id == subscription.seller_id,
                    Ad.created_at >= starts,
                )
            )
        ).scalar_one()
    )
    return {
        "ads_created": created_in_window,
        "ads_used": subscription.ads_used,
        "ads_left": subscription.ads_left,
    }


def days_left(subscription: Subscription | None) -> int:
    """Muddat tugashiga qolgan kun (manfiy — o'tib ketgan)."""
    if subscription is None:
        return 0
    expires = ensure_aware(subscription.expires_at)
    if expires is None:
        return 0
    delta = expires - utcnow()
    seconds = delta.total_seconds()
    if seconds >= 0:
        return int(seconds // 86400)
    return -int((-seconds + 86399) // 86400)


def is_expired(subscription: Subscription | None) -> bool:
    if subscription is None:
        return True
    expires = ensure_aware(subscription.expires_at)
    return expires is None or expires <= utcnow()


# ───────────────────────── Berish ──────────────────────────────────
async def grant(
    session: AsyncSession,
    seller: Seller,
    tariff: Tariff,
    *,
    granted_by: int | None = None,
    days: int | None = None,
    ads_limit: int | None = None,
    payment_id: int | None = None,
    terms_override: dict[str, Any] | None = None,
) -> Subscription:
    """Tarif berish yoki mavjud obunani uzaytirish.

    Bir xil tarif → muddat va limit qo'shiladi (uzaytirish).
    Boshqa tarif → eski obuna yopiladi, yangisi bugundan boshlanadi.
    """
    purchased = terms_override or {}
    duration = int(days or purchased.get("duration_days") or tariff.duration_days)
    limit = int(ads_limit if ads_limit is not None else purchased.get("max_ads") or tariff.max_ads)
    now = utcnow()

    new_terms = (dict(purchased) if purchased else
                 tariff_terms(tariff, ads_limit=limit, duration_days=duration))
    current = await active_for(session, seller.id)
    same_terms = (current is not None and current.tariff_id == tariff.id
                  and terms_for(current) == new_terms)
    grant_starts = max(now, ensure_aware(current.expires_at)) if same_terms else now

    if same_terms:
        # Xuddi shu shartlar: sotib olingan yangi davr va kvotani qo'shish.
        current.expires_at = grant_starts + timedelta(days=duration)
        current.ads_limit = min(MAX_ADS_LIMIT, current.ads_limit + limit)
        current.status = SubscriptionStatus.ACTIVE
        current.reminder_sent_at = None
        current.expired_notified_at = None
        if payment_id is not None:
            current.payment_id = payment_id
        subscription = current
    else:
        if current is not None:
            # Tarif tahrirlangan bo'lsa eski xarid snapshoti va obuna tarixda
            # saqlanadi; faqat yangi xarid yangi shartlarni kuchga kiritadi.
            current.status = SubscriptionStatus.CANCELLED
        expiry_base = max(now, ensure_aware(current.expires_at)) if current is not None else now
        subscription = Subscription(
            seller_id=seller.id, tariff_id=tariff.id,
            status=SubscriptionStatus.ACTIVE, starts_at=now,
            expires_at=expiry_base + timedelta(days=duration),
            ads_limit=min(MAX_ADS_LIMIT, limit + (current.ads_limit - current.ads_used
                           if current is not None and current.tariff_id == tariff.id else 0)),
            ads_used=current.ads_used if current is not None and current.tariff_id == tariff.id else 0,
            terms=new_terms, granted_by=granted_by, payment_id=payment_id,
        )
        session.add(subscription)
        for ad in (await session.execute(select(Ad).where(
            Ad.seller_id == seller.id, Ad.status == "active",
        ))).scalars():
            ad.next_eligible_at = now + timedelta(seconds=interval_for(subscription))
    await session.flush()
    session.add(SubscriptionGrant(
        subscription_id=subscription.id, user_id=seller.user_id, tariff_id=tariff.id,
        terms=new_terms, starts_at=grant_starts, expires_at=subscription.expires_at,
        payment_id=payment_id, granted_by=granted_by,
    ))
    await session.flush()

    if seller.status in (SellerStatus.PENDING, SellerStatus.BLOCKED):
        seller.status = SellerStatus.ACTIVE
        seller.blocked_reason = None
        await session.flush()

    return subscription


async def extend(session: AsyncSession, subscription: Subscription, days: int) -> Subscription:
    """Muddatni qo'shish (tarif o'zgarmaydi)."""
    days = max(1, int(days))
    now = utcnow()
    base = ensure_aware(subscription.expires_at) or now
    base = max(base, now)
    subscription.expires_at = base + timedelta(days=days)
    if subscription.status in (SubscriptionStatus.EXPIRED, SubscriptionStatus.CANCELLED):
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.starts_at = now
    subscription.reminder_sent_at = None
    subscription.expired_notified_at = None
    await session.flush()
    seller = await session.get(Seller, subscription.seller_id)
    if seller is not None:
        session.add(SubscriptionGrant(
            subscription_id=subscription.id, user_id=seller.user_id,
            tariff_id=subscription.tariff_id, terms=terms_for(subscription),
            starts_at=base, expires_at=subscription.expires_at,
            payment_id=None, granted_by=None,
        ))
        await session.flush()
    logger.info("Obuna #{} uzaytirildi: +{} kun", subscription.id, days)
    return subscription


async def set_ads_limit(session: AsyncSession, subscription: Subscription, limit: int) -> bool:
    value = max(0, min(MAX_ADS_LIMIT, int(limit)))
    if subscription.ads_limit == value:
        return False
    subscription.ads_limit = value
    await session.flush()
    return True


async def cancel(session: AsyncSession, subscription: Subscription, *, reason: str | None = None) -> None:
    """Obunani bekor qilish (muddatdan oldin)."""
    subscription.status = SubscriptionStatus.CANCELLED
    await session.flush()
    logger.info("Obuna #{} bekor qilindi ({})", subscription.id, reason or "sababsiz")


def mark_expired(subscription: Subscription) -> None:
    """Muddati o'tgan deb belgilash (flush chaqiruvchi tomonda)."""
    subscription.status = SubscriptionStatus.EXPIRED


# ─────────────────── Limitlar va ruxsat (Phase 3 uchun) ─────────────
async def can_publish(session: AsyncSession, seller: Seller) -> tuple[bool, str]:
    """Sotuvchi e'lon joylay oladimi. (mumkinmi, sabab)."""
    if seller.status == SellerStatus.BLOCKED:
        return False, "🚫 Sizning hisobingiz bloklangan. Admin bilan bog'laning."
    if seller.status == SellerStatus.DELETED:
        return False, "🚫 Hisob o'chirilgan."
    if seller.status == SellerStatus.PENDING:
        return False, "🕓 Sizga hali tarif berilmagan. Admin bilan bog'laning."

    subscription = await active_for(session, seller.id)
    if subscription is None:
        return False, "⏰ Tarifingiz muddati tugagan. Iltimos, tarifni yangilang."

    if subscription.ads_left <= 0:
        return False, (
            f"📢 E'lon limiti tugadi ({subscription.ads_used}/{subscription.ads_limit}). "
            "Tarifni yangilang."
        )
    return True, ""


async def consume_slot(session: AsyncSession, subscription: Subscription, count: int = 1) -> bool:
    """E'lon joylanganda limitdan hisoblash (Phase 3 chaqiradi)."""
    if subscription.ads_left < count:
        return False
    subscription.ads_used += count
    await session.flush()
    return True


async def release_slot(session: AsyncSession, subscription: Subscription, count: int = 1) -> None:
    """E'lon o'chirilganda limitni qaytarish."""
    subscription.ads_used = max(0, subscription.ads_used - count)
    await session.flush()


# ─────────────────── Rejalashtirilgan vazifalar uchun ───────────────
async def reminders_due(session: AsyncSession, *, days: int = 3, limit: int = 200) -> list[Subscription]:
    """Muddati `days` kun ichida tugaydigan va hali eslatilmagan obunalar."""
    now = utcnow()
    threshold = now + timedelta(days=max(0, days))
    stmt = (
        select(Subscription)
        .where(
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.expires_at > now,
            Subscription.expires_at <= threshold,
            Subscription.reminder_sent_at.is_(None),
        )
        .order_by(Subscription.expires_at)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


def mark_reminded(subscription: Subscription) -> None:
    subscription.reminder_sent_at = utcnow()


async def expire_due(session: AsyncSession, *, grace_days: int = 0, limit: int = 500) -> list[Subscription]:
    """Muddati o'tgan obunalarni `grace` yoki `expired` holatiga o'tkazish.

    `grace_days = 0` → darhol `expired`. Aks holda avval `grace`,
    `grace_days` kundan keyin `expired`.
    """
    now = utcnow()
    changed: list[Subscription] = []

    # 1) active → grace / expired
    active_expired = (
        await session.execute(
            select(Subscription)
            .where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at <= now,
            )
            .order_by(Subscription.expires_at)
            .limit(limit)
        )
    ).scalars().all()

    for subscription in active_expired:
        if grace_days > 0:
            subscription.status = SubscriptionStatus.GRACE
        else:
            subscription.status = SubscriptionStatus.EXPIRED
        changed.append(subscription)

    # 2) grace → expired (grace muddati tugagach)
    if grace_days > 0:
        grace_deadline = now - timedelta(days=grace_days)
        grace_expired = (
            await session.execute(
                select(Subscription).where(
                    Subscription.status == SubscriptionStatus.GRACE,
                    Subscription.expires_at <= grace_deadline,
                )
            )
        ).scalars().all()
        for subscription in grace_expired:
            subscription.status = SubscriptionStatus.EXPIRED
            subscription.expired_notified_at = None
            changed.append(subscription)

    if changed:
        await session.flush()
        logger.info("Obunalar holati yangilandi: {} ta", len(changed))
    return changed


async def expired_without_notice(session: AsyncSession, limit: int = 200) -> list[Subscription]:
    """Sotuvchiga xabar berilmagan muddati o'tgan obunalar."""
    stmt = (
        select(Subscription)
        .where(
            Subscription.status == SubscriptionStatus.EXPIRED,
            Subscription.expired_notified_at.is_(None),
        )
        .order_by(Subscription.expires_at)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


def mark_expired_notified(subscription: Subscription) -> None:
    subscription.expired_notified_at = utcnow()


def summary_line(subscription: Subscription | None, tariff: Tariff | None = None) -> str:
    """Qisqa holat satri: '🟢 Biznes · 12 kun qoldi · 📢 3/10'."""
    if subscription is None:
        return "— tarif yo'q"
    name = tariff.name if tariff is not None else f"tarif #{subscription.tariff_id}"
    left = days_left(subscription)
    return f"{name} · {max(0, left)} kun · 📢 {subscription.ads_used}/{subscription.ads_limit}"


def status_title(subscription: Subscription | None) -> str:
    if subscription is None:
        return "⛔️ Obuna yo'q"
    mapping: dict[str, str] = {
        SubscriptionStatus.ACTIVE: "🟢 Faol",
        SubscriptionStatus.GRACE: "🟡 Muddati o'tdi (grace)",
        SubscriptionStatus.EXPIRED: "🔴 Muddati tugagan",
        SubscriptionStatus.CANCELLED: "⚪️ Bekor qilingan",
    }
    return mapping.get(subscription.status, subscription.status)


def as_dict(subscription: Subscription) -> dict[str, Any]:
    """Log/eksport uchun xavfsiz tasvir."""
    return {
        "id": subscription.id,
        "seller_id": subscription.seller_id,
        "tariff_id": subscription.tariff_id,
        "status": subscription.status,
        "starts_at": subscription.starts_at,
        "expires_at": subscription.expires_at,
        "ads_limit": subscription.ads_limit,
        "ads_used": subscription.ads_used,
    }


__all__ = [
    "active_for",
    "can_publish",
    "cancel",
    "consume_slot",
    "count_active",
    "days_left",
    "expire_due",
    "expired_without_notice",
    "get_subscription",
    "grant",
    "history",
    "is_expired",
    "latest_for",
    "release_slot",
    "reminders_due",
    "set_ads_limit",
    "summary_line",
]
