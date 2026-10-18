"""Sotuvchilar bilan ishlash servisi (Phase 2).

Asosiy qoidalar:
  * Sotuvchini faqat **admin** qo'shadi (o'z-o'zidan ro'yxatdan o'tish yo'q).
  * `users` jadvali bilan FK yo'q (ataylab) — sotuvchi `user_id` bo'yicha topiladi.
  * Holatlar: `pending` (tarif berilmagan) → `active` (tarif berilgan) →
    `blocked` (admin to'xtatgan) / `deleted` (yumshoq o'chirish).
"""

from __future__ import annotations

import secrets
from typing import Any

from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdStatus, SellerStatus
from app.db.models import Ad, Payment, Seller, Subscription
from app.utils.text import clean_text, truncate

# Referal kodi alifbosi (chalkash belgilar yo'q: 0/O, 1/I/l)
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8

MAX_NAME_LEN = 64
MAX_PHONE_LEN = 32
MAX_CONTACT_LEN = 64
MAX_NOTE_LEN = 500


# ─────────────────────────── O'qish ────────────────────────────────
async def get_seller(session: AsyncSession, user_id: int) -> Seller | None:
    """Foydalanuvchining sotuvchi yozuvini olish (bo'lmasa None)."""
    return (
        await session.execute(select(Seller).where(Seller.user_id == user_id))
    ).scalar_one_or_none()


async def get_seller_by_id(session: AsyncSession, seller_id: int) -> Seller | None:
    return await session.get(Seller, seller_id)


async def is_active_seller(session: AsyncSession, user_id: int) -> bool:
    """Sotuvchi panelidan foydalanishi mumkinmi (bloklanmagan/o'chirilmagan)."""
    seller = await get_seller(session, user_id)
    return seller is not None and seller.status not in (SellerStatus.BLOCKED, SellerStatus.DELETED)


async def get_seller_by_referral_code(session: AsyncSession, code: str) -> Seller | None:
    """Referal kodi bo'yicha sotuvchini topish (Phase 8)."""
    return (
        await session.execute(select(Seller).where(Seller.referral_code == code.upper()))
    ).scalar_one_or_none()


async def list_sellers(
    session: AsyncSession,
    *,
    offset: int = 0,
    limit: int = 6,
    status: str | None = None,
    query: str | None = None,
) -> list[Seller]:
    """Sotuvchilar ro'yxati (holat bo'yicha filtr + qidiruv)."""
    stmt = select(Seller).order_by(Seller.created_at.desc(), Seller.id.desc())
    stmt = _apply_filters(stmt, status=status, query=query)
    return list((await session.execute(stmt.offset(offset).limit(limit))).scalars().all())


async def count_sellers(
    session: AsyncSession, *, status: str | None = None, query: str | None = None
) -> int:
    stmt = select(func.count()).select_from(Seller)
    stmt = _apply_filters(stmt, status=status, query=query)
    return int((await session.execute(stmt)).scalar_one())


def _apply_filters(stmt: Any, *, status: str | None, query: str | None) -> Any:
    if status and status != "all":
        stmt = stmt.where(Seller.status == status)
    else:
        # O'chirilganlar ro'yxatda ko'rinmaydi
        stmt = stmt.where(Seller.status != SellerStatus.DELETED)

    text = (query or "").strip().lstrip("@")
    if text:
        if text.isdigit():
            stmt = stmt.where(
                or_(
                    Seller.user_id == int(text),
                    Seller.id == int(text),
                )
            )
        else:
            stmt = stmt.where(Seller.display_name.ilike(f"%{text}%"))
    return stmt


async def count_sellers_by_status(session: AsyncSession) -> dict[str, int]:
    """Holatlar kesimida son (ro'yxat sarlavhasi uchun)."""
    rows = (
        await session.execute(select(Seller.status, func.count()).group_by(Seller.status))
    ).all()
    counts = {status: int(count) for status, count in rows}
    counts["total"] = sum(
        counts.get(status, 0)
        for status in (SellerStatus.PENDING, SellerStatus.ACTIVE, SellerStatus.BLOCKED)
    )
    return counts


async def get_seller_stats(session: AsyncSession, seller: Seller) -> dict[str, int]:
    """Sotuvchi kartochkasi uchun raqamlar."""
    ads_total = int(
        (
            await session.execute(
                select(func.count()).select_from(Ad).where(Ad.seller_id == seller.id)
            )
        ).scalar_one()
    )
    ads_active = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Ad)
                .where(Ad.seller_id == seller.id, Ad.status == AdStatus.ACTIVE)
            )
        ).scalar_one()
    )
    payments = int(
        (
            await session.execute(
                select(func.count()).select_from(Payment).where(Payment.seller_id == seller.id)
            )
        ).scalar_one()
    )
    subscriptions = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Subscription)
                .where(Subscription.seller_id == seller.id)
            )
        ).scalar_one()
    )
    return {
        "ads_total": ads_total,
        "ads_active": ads_active,
        "payments": payments,
        "subscriptions": subscriptions,
    }


# ───────────────────────── Yozish ──────────────────────────────────
async def get_or_create_seller(
    session: AsyncSession,
    user_id: int,
    *,
    display_name: str | None = None,
    phone: str | None = None,
    contact: str | None = None,
    note: str | None = None,
    added_by: int | None = None,
) -> tuple[Seller, bool]:
    """Sotuvchini qo'shish yoki mavjudini yangilash. (seller, yangi_yaratildi)."""
    seller = await get_seller(session, user_id)
    if seller is None:
        seller = Seller(
            user_id=user_id,
            display_name=normalize_name(display_name) or f"ID {user_id}",
            phone=normalize_phone(phone),
            contact=normalize_contact(contact),
            note=clean_text(note, limit=MAX_NOTE_LEN),
            status=SellerStatus.PENDING,
            added_by=added_by,
            referral_code=await generate_referral_code(session),
        )
        session.add(seller)
        await session.flush()
        logger.info("Yangi sotuvchi qo'shildi: {} ({})", seller.display_name, seller.user_id)
        return seller, True

    # Mavjud sotuvchi: kelgan ma'lumotlarni yangilaymiz (bo'sh bo'lmasa)
    changed = False
    if normalize_name(display_name):
        seller.display_name = normalize_name(display_name)
        changed = True
    if normalize_phone(phone):
        seller.phone = normalize_phone(phone)
        changed = True
    if normalize_contact(contact):
        seller.contact = normalize_contact(contact)
        changed = True
    if clean_text(note, limit=MAX_NOTE_LEN):
        seller.note = clean_text(note, limit=MAX_NOTE_LEN)
        changed = True
    if seller.status == SellerStatus.DELETED:
        seller.status = SellerStatus.PENDING
        changed = True
    if changed:
        await session.flush()
        logger.info("Sotuvchi ma'lumotlari yangilandi: {} ({})", seller.display_name, seller.user_id)

    return seller, False


async def update_profile(
    session: AsyncSession,
    seller: Seller,
    *,
    display_name: str | None = None,
    phone: str | None = None,
    contact: str | None = None,
    note: str | None = None,
) -> bool:
    """Profil maydonlarini yangilash. `None` — o'zgartirmaslik."""
    changed = False

    if display_name is not None:
        name = normalize_name(display_name)
        if name and seller.display_name != name:
            seller.display_name = name
            changed = True
    if phone is not None:
        value = normalize_phone(phone)
        if seller.phone != value:
            seller.phone = value
            changed = True
    if contact is not None:
        value = normalize_contact(contact)
        if seller.contact != value:
            seller.contact = value
            changed = True
    if note is not None:
        value = clean_text(note, limit=MAX_NOTE_LEN)
        if seller.note != value:
            seller.note = value
            changed = True

    if changed:
        await session.flush()
    return changed


async def set_status(
    session: AsyncSession, seller: Seller, status: str, *, reason: str | None = None
) -> bool:
    """Holatni o'zgartirish (bloklash/blokdan chiqarish)."""
    if status not in set(SellerStatus):
        logger.warning("Noma'lum sotuvchi holati: {}", status)
        return False
    if seller.status == status:
        return False

    seller.status = status
    if status == SellerStatus.BLOCKED:
        seller.blocked_reason = reason or "Admin tomonidan bloklandi"
    elif status != SellerStatus.BLOCKED:
        seller.blocked_reason = None

    await session.flush()
    logger.info("Sotuvchi {} holati: {} → {}", seller.user_id, seller.display_name, status)
    return True


async def set_verified(session: AsyncSession, seller: Seller, value: bool) -> bool:
    if seller.is_verified == value:
        return False
    seller.is_verified = value
    await session.flush()
    return True


async def soft_delete(session: AsyncSession, seller: Seller) -> None:
    """Sotuvchini ro'yxatdan olib tashlash (yozuv tarix uchun qoladi)."""
    from app.services import subscription_service

    seller.status = SellerStatus.DELETED
    seller.referral_code = None
    for sub in await subscription_service.history(session, seller.id, limit=50):
        if sub.status in ("active", "grace"):
            subscription_service.mark_expired(sub)
    await session.flush()
    logger.info("Sotuvchi o'chirildi (soft): {} ({})", seller.display_name, seller.user_id)


# ─────────────────────── Referal va yordamchilar ────────────────────
async def generate_referral_code(session: AsyncSession) -> str:
    """Takrorlanmaydigan referal kodi (8 belgi)."""
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        exists = (
            await session.execute(select(Seller.id).where(Seller.referral_code == code))
        ).scalar_one_or_none()
        if exists is None:
            return code
    # Amalda bo'lmaydi: 32^8 ≈ 1.1e12 kombinatsiya
    return f"S{secrets.token_hex(6).upper()}"


async def ensure_referral_code(session: AsyncSession, seller: Seller) -> str:
    if not seller.referral_code:
        seller.referral_code = await generate_referral_code(session)
        await session.flush()
    return seller.referral_code


def normalize_name(value: str | None) -> str | None:
    text = clean_text(value, limit=MAX_NAME_LEN)
    return text or None


def normalize_phone(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text or text.lower() in ("-", "yo'q", "yoq", "skip", "o'tkazib yuborish"):
        return None
    # Faqat raqamlar va boshidagi "+" qoladi (ko'rsatish uchun qulay)
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    cleaned = f"+{digits}" if text.startswith("+") else digits
    return cleaned[:MAX_PHONE_LEN]


def normalize_contact(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text or text.lower() in ("-", "yo'q", "yoq", "skip", "o'tkazib yuborish"):
        return None
    if text.startswith("https://t.me/"):
        text = "@" + text.removeprefix("https://t.me/")
    text = text[:MAX_CONTACT_LEN]
    return text or None


def seller_label(seller: Seller, limit: int = 24) -> str:
    """Ro'yxat/tugmalar uchun qisqa nom."""
    name = seller.display_name or f"ID {seller.user_id}"
    return truncate(name, limit)


def status_badge(seller: Seller) -> str:
    return {
        SellerStatus.PENDING: "🕓 Tarif yo'q",
        SellerStatus.ACTIVE: "🟢 Faol",
        SellerStatus.BLOCKED: "🚫 Bloklangan",
        SellerStatus.DELETED: "🗑 O'chirilgan",
    }.get(seller.status, seller.status)


def status_filter_label(status: str | None) -> str:
    return {
        None: "Hammasi",
        "all": "Hammasi",
        SellerStatus.PENDING: "🕓 Tarif yo'q",
        SellerStatus.ACTIVE: "🟢 Faol",
        SellerStatus.BLOCKED: "🚫 Bloklangan",
    }.get(status, str(status))


__all__ = [
    "CODE_ALPHABET",
    "get_or_create_seller",
    "get_seller",
    "get_seller_by_id",
    "get_seller_by_referral_code",
    "get_seller_stats",
    "is_active_seller",
    "normalize_contact",
    "normalize_name",
    "normalize_phone",
    "seller_label",
    "set_status",
    "set_verified",
    "soft_delete",
    "status_badge",
    "update_profile",
]
