"""📢 E'lonlar servisi (Phase 3).

Bu qatlam e'lon hayot siklini boshqaradi:

    draft → (sotuvchi yuboradi) → pending → (admin) → active
                                          ↘ (rad) → rejected → qayta tahrir → draft

Muhim qoidalar (REJA.md 4.4 va 9-bo'lim):
  * Har toifada e'lonlar `position` bo'yicha tartiblanadi (100, 200, 300...).
    Oralariga qo'shish oson bo'lishi uchun qadam 100, lekin oraliq tugasa
    `renumber_category()` qayta raqamlaydi (Phase 4 navbat dvigateli ishlatadi).
  * Obuna limiti **yuborishda** hisoblanadi (`consume_slot`), rad etilganda
    yoki o'chirilganda qaytariladi (`release_slot`) — adolatli bo'lishi uchun.
  * Rasm limiti tarifdan olinadi (`max_photos`), tarif yo'q bo'lsa — global
    sozlamadan (`default_max_photos`).
  * Fayl saqlanmaydi — faqat Telegram `file_id` (REJA.md 4.4).
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from math import ceil
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdStatus
from app.db.models import Ad, AdPhoto, Category, ModerationLog, Seller
from app.services import subscription_service
from app.services.settings_service import settings_service
from app.utils.text import clean_text, truncate
from app.utils.time import utcnow

POSITION_GAP = 100
TITLE_MAX = 120
DESCRIPTION_MAX = 800
MAX_PHOTOS_HARD = 10          # Telegram albom chegarasi
PRICE_MAX = 10**12

# Tahrirlash mumkin bo'lgan maydonlar (sotuvchi tomonidan)
EDITABLE_FIELDS = {"title", "description", "price", "contact", "category_id"}

# Ro'yxat filtri: kalit → holatlar to'plami
STATUS_FILTERS: dict[str, tuple[str, ...]] = {
    "all": tuple(AdStatus),
    "active": (AdStatus.ACTIVE,),
    "pending": (AdStatus.PENDING,),
    "draft": (AdStatus.DRAFT,),
    "paused": (AdStatus.PAUSED,),
    "rejected": (AdStatus.REJECTED,),
    "archived": (AdStatus.EXPIRED, AdStatus.DELETED),
}

# Admin ro'yxati uchun (moderatsiya kutayotganlar alohida bo'limda)
ADMIN_FILTERS: dict[str, tuple[str, ...]] = {
    "all": tuple(AdStatus),
    "pending": (AdStatus.PENDING,),
    "active": (AdStatus.ACTIVE,),
    "paused": (AdStatus.PAUSED,),
    "rejected": (AdStatus.REJECTED,),
    "draft": (AdStatus.DRAFT,),
    "archived": (AdStatus.EXPIRED, AdStatus.DELETED),
}

STATUS_TITLES: dict[str, str] = {
    AdStatus.DRAFT: "✏️ Qoralama",
    AdStatus.PENDING: "🕓 Tekshiruvda",
    AdStatus.ACTIVE: "🟢 Faol (navbatda)",
    AdStatus.PAUSED: "⏸ To'xtatilgan",
    AdStatus.REJECTED: "❌ Rad etilgan",
    AdStatus.EXPIRED: "⌛️ Muddati tugagan",
    AdStatus.DELETED: "🗑 O'chirilgan",
}

STATUS_BADGES: dict[str, str] = {
    AdStatus.DRAFT: "✏️",
    AdStatus.PENDING: "🕓",
    AdStatus.ACTIVE: "🟢",
    AdStatus.PAUSED: "⏸",
    AdStatus.REJECTED: "❌",
    AdStatus.EXPIRED: "⌛️",
    AdStatus.DELETED: "🗑",
}

# Sotuvchi kartochkasida ko'rinadigan holatlar (o'chirilganlar ko'rinmaydi)
SELLER_STATUSES = (
    AdStatus.DRAFT,
    AdStatus.PENDING,
    AdStatus.ACTIVE,
    AdStatus.PAUSED,
    AdStatus.REJECTED,
    AdStatus.EXPIRED,
)

MIN_TITLE = 3
MIN_DESCRIPTION = 0


# ═══════════════════════════ Matn yordamchilari ════════════════════
def status_title(status: str) -> str:
    return STATUS_TITLES.get(status, status)


def status_badge(status: str) -> str:
    return STATUS_BADGES.get(status, "•")


def filter_label(key: str, *, admin: bool = False) -> str:
    table = ADMIN_FILTERS if admin else STATUS_FILTERS
    if key == "all":
        return "Hammasi"
    labels = {
        "active": "🟢 Faol",
        "pending": "🕓 Tekshiruvda",
        "draft": "✏️ Qoralama",
        "paused": "⏸ To'xtatilgan",
        "rejected": "❌ Rad etilgan",
        "archived": "🗑 Arxiv",
    }
    return labels.get(key, table.get(key, key))


def ad_label(ad: Ad, limit: int = 40) -> str:
    """Ro'yxatdagi qisqa nom: 1000 🟢 Telefon sotiladi..."""
    return f"{ad.id} {status_badge(ad.status)} {truncate(ad.title or '(nomsiz)', limit)}"


def photos_line(count: int, limit: int) -> str:
    return f"🖼 Rasmlar: <b>{count}/{limit}</b>"


def format_ad_price(ad: Ad) -> str:
    """Narxni chiroyli ko'rsatish: "12 500 000 so'm" yoki "Kelishiladi"."""
    from app.utils.text import fmt_amount

    if ad.price is None:
        return "Kelishiladi"
    return fmt_amount(ad.price, ad.currency or "UZS")


# ═══════════════════════════ O'qish ════════════════════════════════
async def get_ad(session: AsyncSession, ad_id: int, *, seller_id: int | None = None) -> Ad | None:
    """E'lonni olish. `seller_id` berilsa — egalik ham tekshiriladi."""
    stmt = select(Ad).where(Ad.id == ad_id)
    if seller_id is not None:
        stmt = stmt.where(Ad.seller_id == seller_id)
    return (await session.execute(stmt)).scalars().first()


async def photo_count(session: AsyncSession, ad_id: int) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).select_from(AdPhoto).where(AdPhoto.ad_id == ad_id)
            )
        ).scalar_one()
    )


async def list_seller_ads(
    session: AsyncSession,
    seller_id: int,
    *,
    status: str = "all",
    limit: int = 6,
    offset: int = 0,
) -> list[Ad]:
    statuses = STATUS_FILTERS.get(status, tuple(SELLER_STATUSES))
    statuses = tuple(s for s in statuses if s != AdStatus.DELETED)
    stmt = (
        select(Ad)
        .where(Ad.seller_id == seller_id, Ad.status.in_(statuses))
        .order_by(Ad.category_id, Ad.created_at.desc(), Ad.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_seller_ads(session: AsyncSession, seller_id: int, *, status: str = "all") -> int:
    statuses = STATUS_FILTERS.get(status, tuple(SELLER_STATUSES))
    statuses = tuple(s for s in statuses if s != AdStatus.DELETED)
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Ad)
                .where(Ad.seller_id == seller_id, Ad.status.in_(statuses))
            )
        ).scalar_one()
    )


async def seller_ads_stats(session: AsyncSession, seller_id: int) -> dict[str, int]:
    """Sotuvchi e'lonlarining holat bo'yicha soni."""
    rows = (
        await session.execute(
            select(Ad.status, func.count())
            .select_from(Ad)
            .where(Ad.seller_id == seller_id)
            .group_by(Ad.status)
        )
    ).all()
    stats = {status: 0 for status in SELLER_STATUSES}
    for status, count in rows:
        stats[str(status)] = int(count)
    stats["total"] = sum(stats.get(s, 0) for s in SELLER_STATUSES)
    return stats


async def list_ads(
    session: AsyncSession,
    *,
    status: str = "all",
    category_id: int | None = None,
    seller_id: int | None = None,
    limit: int = 8,
    offset: int = 0,
    admin: bool = True,
) -> list[Ad]:
    """Admin ro'yxati (holat/toifa/sotuvchi bo'yicha filtr)."""
    table = ADMIN_FILTERS if admin else STATUS_FILTERS
    statuses = table.get(status, tuple(table["all"]))
    stmt = select(Ad).where(Ad.status.in_(statuses))
    if category_id:
        stmt = stmt.where(Ad.category_id == category_id)
    if seller_id:
        stmt = stmt.where(Ad.seller_id == seller_id)
    stmt = stmt.order_by(Ad.created_at.desc(), Ad.id.desc()).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


async def count_ads(
    session: AsyncSession,
    *,
    status: str = "all",
    category_id: int | None = None,
    seller_id: int | None = None,
    admin: bool = True,
) -> int:
    table = ADMIN_FILTERS if admin else STATUS_FILTERS
    statuses = table.get(status, tuple(table["all"]))
    stmt = select(func.count()).select_from(Ad).where(Ad.status.in_(statuses))
    if category_id:
        stmt = stmt.where(Ad.category_id == category_id)
    if seller_id:
        stmt = stmt.where(Ad.seller_id == seller_id)
    return int((await session.execute(stmt)).scalar_one())


async def count_by_status(session: AsyncSession) -> dict[str, int]:
    """Barcha e'lonlarning holat bo'yicha soni (panel sarlavhasi uchun)."""
    rows = (
        await session.execute(select(Ad.status, func.count()).select_from(Ad).group_by(Ad.status))
    ).all()
    stats = {status: 0 for status in AdStatus}
    for status, count in rows:
        stats[str(status)] = int(count)
    stats["all"] = sum(int(c) for _, c in rows)
    return stats


async def pending_ads(session: AsyncSession, *, limit: int = 8, offset: int = 0) -> list[Ad]:
    stmt = (
        select(Ad)
        .where(Ad.status == AdStatus.PENDING)
        .order_by(Ad.submitted_at.asc().nullsfirst(), Ad.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_pending(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).select_from(Ad).where(Ad.status == AdStatus.PENDING)
            )
        ).scalar_one()
    )


async def moderation_history(session: AsyncSession, ad_id: int, limit: int = 8) -> list[ModerationLog]:
    stmt = (
        select(ModerationLog)
        .where(ModerationLog.ad_id == ad_id)
        .order_by(ModerationLog.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def ad_stats(session: AsyncSession, ad: Ad) -> dict[str, Any]:
    """E'lon statistikasi (joylashlar tarixidan)."""
    from app.db.models import PostLog

    posts = int(
        (
            await session.execute(
                select(func.count())
                .select_from(PostLog)
                .where(PostLog.ad_id == ad.id, PostLog.status == "ok")
            )
        ).scalar_one()
    )
    groups = int(
        (
            await session.execute(
                select(func.count(func.distinct(PostLog.group_id)))
                .select_from(PostLog)
                .where(PostLog.ad_id == ad.id, PostLog.status == "ok")
            )
        ).scalar_one()
    )
    return {
        "post_count": ad.post_count,
        "logged_posts": posts,
        "groups": groups,
        "photos": await photo_count(session, ad.id),
        "last_posted_at": ad.last_posted_at,
    }


async def daily_post_counts(session: AsyncSession, ad_id: int, days: int = 7) -> list[tuple[str, int]]:
    """E'lonning mahalliy kunlik muvaffaqiyatli postlari (bugun ham kiradi)."""
    from app.db.models import PostLog
    from app.services.report_service import report_timezone
    from app.utils.time import ensure_aware

    if days not in (7, 30):
        raise ValueError("Grafik davri 7 yoki 30 kun bo'lishi kerak.")
    tz = await report_timezone(session)
    end = utcnow().astimezone(tz).date()
    start = end - timedelta(days=days - 1)
    utc_start = datetime.combine(start, time.min, tzinfo=tz).astimezone(UTC)
    times = (await session.execute(select(PostLog.created_at).where(
        PostLog.ad_id == ad_id, PostLog.status == "ok", PostLog.created_at >= utc_start,
    ))).scalars().all()
    counts: dict[str, int] = {}
    for dt in times:
        key = ensure_aware(dt).astimezone(tz).date().isoformat()
        counts[key] = counts.get(key, 0) + 1
    return [((start + timedelta(days=i)).isoformat(),
             counts.get((start + timedelta(days=i)).isoformat(), 0)) for i in range(days)]


async def category_of(session: AsyncSession, ad: Ad) -> Category | None:
    if ad.category_id is None:
        return None
    return await session.get(Category, ad.category_id)


async def photo_limit(session: AsyncSession, seller: Seller) -> int:
    """Sotuvchining joriy tarifidagi rasm limiti (kvota)."""
    subscription = await subscription_service.active_for(session, seller.id)
    limit = None
    if subscription is not None:
        limit = subscription_service.terms_for(subscription).get("max_photos")
    if not limit:
        limit = int(await settings_service.get("default_max_photos", 3, session) or 3)
    return max(1, min(int(limit), MAX_PHOTOS_HARD))


async def moderation_required(session: AsyncSession, category: Category | None) -> bool:
    """Har yangi pullik e'lon mazmuni admin tasdig'ini kutadi.

    Eski toifa flagi tarixiy ma'lumot sifatida qoladi, ammo tasdiqni chetlab
    o'tadigan yo'l sifatida ishlamaydi.
    """
    return True


async def max_position(session: AsyncSession, category_id: int) -> int:
    value = (
        await session.execute(
            select(func.max(Ad.position)).where(
                Ad.category_id == category_id,
                Ad.status.notin_((AdStatus.DELETED,)),
            )
        )
    ).scalar_one_or_none()
    return int(value or 0)


async def next_position(session: AsyncSession, category_id: int) -> int:
    """Navbat oxiriga qo'shish uchun pozitsiya."""
    return await max_position(session, category_id) + POSITION_GAP


# ═══════════════════════════ Yaratish ═════════════════════════════
def default_contact(seller: Seller) -> tuple[str, str | None]:
    """Sotuvchi profilidan standart aloqa usuli.

    `@username` → `username`, telefon → `phone`, boshqa havola → `url`.
    Sotuvchi e'lon ustasida buni o'zgartira oladi.
    """
    contact = (seller.contact or "").strip()
    if contact.startswith("@") or contact.startswith("https://t.me/"):
        return "username", contact
    if not contact and seller.phone:
        return "phone", seller.phone
    if contact:
        return "url", contact
    if seller.phone:
        return "phone", seller.phone
    return "username", None


async def create_draft(
    session: AsyncSession,
    seller: Seller,
    category: Category,
    *,
    title: str | None = None,
) -> Ad:
    """Yangi e'lon (qoralama). Usta shu yozuvni to'ldirib boradi."""
    contact_type, contact_value = default_contact(seller)
    ad = Ad(
        seller_id=seller.id,
        category_id=category.id,
        group_id=category.group_id,  # toifa biriktirilgan guruhning denormalizatsiyasi
        title=(title or "").strip(),
        status=AdStatus.DRAFT,
        currency="UZS",
        contact_type=contact_type,
        contact_value=contact_value,
        position=await next_position(session, category.id),
    )
    session.add(ad)
    await session.flush()
    logger.info("Qoralama yaratildi: ad={} sotuvchi={} toifa={}", ad.id, seller.id, category.id)
    return ad


async def set_contact(
    session: AsyncSession,
    ad: Ad,
    *,
    contact_type: str,
    contact_value: str | None,
) -> None:
    """Aloqa usuli (username | url | phone) va qiymati."""
    ad.contact_type = contact_type
    ad.contact_value = clean_text(contact_value, limit=255)
    await session.flush()


async def set_category(session: AsyncSession, ad: Ad, category: Category) -> None:
    if ad.category_id != category.id:
        ad.category_id = category.id
        ad.position = await next_position(session, category.id)
    ad.group_id = category.group_id
    await session.flush()


async def add_photo(
    session: AsyncSession,
    ad: Ad,
    *,
    file_id: str,
    file_unique_id: str | None = None,
    width: int | None = None,
    height: int | None = None,
    limit: int | None = None,
) -> AdPhoto:
    """Rasm qo'shish. `limit` berilgan bo'lsa — oshib ketmaydi (ValueError)."""
    count = await photo_count(session, ad.id)
    if limit is not None and count >= limit:
        raise ValueError("photo_limit")

    photo = AdPhoto(
        ad_id=ad.id,
        file_id=file_id,
        file_unique_id=file_unique_id,
        position=count,
        width=width,
        height=height,
    )
    session.add(photo)
    await session.flush()
    return photo


async def remove_photo(session: AsyncSession, ad: Ad, position: int) -> bool:
    """Rasmni o'chirish va qolganlarini qayta raqamlash."""
    photo = (
        await session.execute(
            select(AdPhoto).where(AdPhoto.ad_id == ad.id, AdPhoto.position == position)
        )
    ).scalars().first()
    if photo is None:
        return False

    await session.delete(photo)
    await session.flush()

    rest = (
        await session.execute(
            select(AdPhoto).where(AdPhoto.ad_id == ad.id).order_by(AdPhoto.position)
        )
    ).scalars().all()
    for index, row in enumerate(rest):
        row.position = index
    await session.flush()
    return True


# ═══════════════════════════ Tahrirlash ═══════════════════════════
async def set_title(session: AsyncSession, ad: Ad, value: str) -> bool:
    title = clean_text(value, limit=TITLE_MAX)
    if not title or len(title) < MIN_TITLE:
        return False
    ad.title = title
    await session.flush()
    return True


async def set_description(session: AsyncSession, ad: Ad, value: str) -> bool:
    ad.description = clean_text(value, limit=DESCRIPTION_MAX)
    await session.flush()
    return True


async def set_price(session: AsyncSession, ad: Ad, value: int | float | None) -> bool:
    """Narxni yozish (None = «kelishiladi»)."""
    from decimal import Decimal

    if value is None:
        ad.price = None
        await session.flush()
        return True
    if value < 0 or value > PRICE_MAX:
        return False
    ad.price = Decimal(str(round(float(value), 2)))
    await session.flush()
    return True


async def edited(session: AsyncSession, ad: Ad, *, admin_id: int | None = None) -> None:
    """Tahrirdan keyingi holat mantiqi + moderatsiya jurnali.

      * `draft` / `rejected` — qoralama bo'lib qoladi (qayta yuborish kerak);
      * `pending` — qayta tekshiruvga tushadi (allaqachon navbatda edi);
      * `active` — tahrir darhol navbatdan chiqadi va qayta tasdiq kutadi;
      * `paused` — foydalanuvchi/admin Stop'i saqlanadi, Startdan so'ng tasdiq kutadi.
    """
    if ad.status == AdStatus.REJECTED:
        ad.status = AdStatus.DRAFT
        ad.reject_reason = None
    elif ad.status in (AdStatus.PENDING, AdStatus.ACTIVE, AdStatus.PAUSED):
        previous = ad.status
        if previous == AdStatus.ACTIVE:
            ad.status = AdStatus.PENDING
        ad.approved_at = None
        ad.approved_by = None
        ad.next_eligible_at = None
        ad.submitted_at = utcnow()
        if previous in (AdStatus.ACTIVE, AdStatus.PAUSED):
            session.add(ModerationLog(
                ad_id=ad.id, admin_id=admin_id, decision="revised",
                reason="Sotuvchi e'lonni tahrirladi; qayta tasdiq zarur",
            ))
    await session.flush()


# ═══════════════════════════ Tekshiruv ════════════════════════════
async def validate_for_submit(session: AsyncSession, ad: Ad) -> tuple[bool, str]:
    """Yuborishdan oldingi tekshiruv. (mumkinmi, sabab)."""
    category = await category_of(session, ad)
    title = (ad.title or "").strip()
    if not title or len(title) < MIN_TITLE:
        return False, f"✏️ Sarlavha juda qisqa (kamida {MIN_TITLE} belgi)."
    if category is None:
        return False, "🗂 Toifa tanlanmagan."
    if not category.is_active:
        return False, "🗂 Bu toifa hozircha faol emas. Boshqa toifa tanlang."
    if category.group_id is None:
        return False, (
            "🗂 Bu toifa hech qaysi guruhga biriktirilmagan — admin tez orada "
            "biriktiradi. Boshqa toifa tanlang."
        )
    photos = await photo_count(session, ad.id)
    if photos == 0:
        return False, "🖼 Kamida bitta rasm qo'shing."
    return True, ""


async def can_submit(
    session: AsyncSession, seller: Seller, ad: Ad
) -> tuple[bool, str]:
    """To'liq tekshiruv: obuna, limit, maydonlar."""
    ok, reason = await subscription_service.can_publish(session, seller)
    if not ok:
        return False, reason
    return await validate_for_submit(session, ad)


# ═══════════════════ Holatni o'zgartirish (sotuvchi) ═══════════════
async def submit(session: AsyncSession, seller: Seller, ad: Ad) -> tuple[bool, str]:
    """E'lonni yuborish: limitdan bir marta hisoblash va admin navbatiga qo'yish.

    Qaytaradi: (muvaffaqiyat, xabar/holat).
    """

    if ad.status != AdStatus.DRAFT or ad.seller_id != seller.id:
        return False, "Bu e'lon allaqachon yuborilgan; yangi tahrirni admin tasdiqlaydi."
    ok, reason = await can_submit(session, seller, ad)
    if not ok:
        return False, reason

    subscription = await subscription_service.active_for(session, seller.id)
    if subscription is None:  # can_publish allaqachon tekshirdi (xavfsizlik uchun)
        return False, "⏰ Faol obuna topilmadi."

    slot_ok = await subscription_service.consume_slot(session, subscription)
    if not slot_ok:
        return False, (
            f"📢 E'lon limiti tugadi ({subscription.ads_used}/{subscription.ads_limit}). "
            "Tarifni yangilang."
        )

    ad.submitted_at = utcnow()
    ad.status = AdStatus.PENDING
    ad.approved_at = None  # eski tasdiq rad/tahrir bilan qayta qo'llanmasin
    ad.approved_by = None
    ad.next_eligible_at = None
    ad.reject_reason = None

    await session.flush()
    logger.info(
        "E'lon yuborildi: ad={} sotuvchi={} holat={} (subscription={})",
        ad.id, seller.id, AdStatus.PENDING, subscription.id,
    )
    return True, AdStatus.PENDING


async def pause(session: AsyncSession, ad: Ad) -> bool:
    """⏸ E'lonni navbatdan chiqarish (faqat faol e'lon)."""
    if ad.status != AdStatus.ACTIVE:
        return False
    ad.status = AdStatus.PAUSED
    await session.flush()
    return True


async def resume(session: AsyncSession, ad: Ad) -> bool:
    """▶️ Pauzadan qaytarish (obuna faol bo'lishi shart)."""
    if ad.status != AdStatus.PAUSED or ad.admin_paused:
        return False
    subscription = await subscription_service.active_for(session, ad.seller_id)
    if subscription is None:
        return False
    if ad.approved_at is None:
        ad.status = AdStatus.PENDING
        ad.next_eligible_at = None
    else:
        ad.status = AdStatus.ACTIVE
        ad.next_eligible_at = utcnow() + timedelta(seconds=subscription_service.interval_for(subscription))
    await session.flush()
    return True


async def soft_delete(
    session: AsyncSession, seller: Seller, ad: Ad, *, release: bool = True
) -> bool:
    """🗑 E'lonni o'chirish (yozuv saqlanadi) + limitdan qaytarish."""
    if ad.status == AdStatus.DELETED:
        return False

    was_active = ad.status in (AdStatus.ACTIVE, AdStatus.PENDING, AdStatus.PAUSED)
    ad.status = AdStatus.DELETED
    ad.title = ad.title or "(o'chirilgan)"

    if release and was_active:
        subscription = await subscription_service.active_for(session, seller.id)
        if subscription is not None:
            await subscription_service.release_slot(session, subscription)

    await session.flush()
    logger.info("E'lon o'chirildi: ad={} sotuvchi={}", ad.id, seller.id)
    return True


async def hard_delete_empty_draft(session: AsyncSession, ad: Ad) -> bool:
    """Bo'sh qoralamani butunlay o'chirish (usta bekor qilinganda)."""
    photos = await photo_count(session, ad.id)
    if ad.status != AdStatus.DRAFT or photos or (ad.title or "").strip():
        return False
    await session.delete(ad)
    await session.flush()
    return True


# ═══════════════════ Moderatsiya (admin tomoni) ════════════════════
async def approve(session: AsyncSession, ad: Ad, admin_id: int | None) -> bool:
    """✅ Tasdiqlash → faqat sotuvchining ▶️ Startidan keyin navbatga qo'shiladi."""
    if ad.status != AdStatus.PENDING:
        return False
    valid, _ = await validate_for_submit(session, ad)
    if not valid:
        return False
    # Moderatsiya Start emas: sotuvchi Start bosguncha birinchi post bo'lmasin.
    ad.status = AdStatus.PAUSED
    ad.admin_paused = False
    ad.approved_by = admin_id
    ad.approved_at = utcnow()
    ad.next_eligible_at = None
    ad.reject_reason = None
    session.add(ModerationLog(ad_id=ad.id, admin_id=admin_id, decision="approved"))
    await session.flush()
    logger.info("E'lon tasdiqlandi: ad={} admin={}", ad.id, admin_id)
    return True


async def reject(
    session: AsyncSession, seller: Seller, ad: Ad, admin_id: int | None, reason: str | None
) -> bool:
    """❌ Rad etish + limitdan qaytarish (sotuvchi qayta yuborishi mumkin)."""
    if ad.status not in (AdStatus.PENDING, AdStatus.ACTIVE):
        return False
    ad.status = AdStatus.REJECTED
    ad.reject_reason = clean_text(reason, limit=500)
    session.add(
        ModerationLog(ad_id=ad.id, admin_id=admin_id, decision="rejected", reason=ad.reject_reason)
    )

    subscription = await subscription_service.active_for(session, seller.id)
    if subscription is not None:
        await subscription_service.release_slot(session, subscription)

    await session.flush()
    logger.info("E'lon rad etildi: ad={} admin={} sabab={}", ad.id, admin_id, ad.reject_reason)
    return True


async def admin_resume(session: AsyncSession, ad: Ad, admin_id: int | None) -> bool:
    """Admin pauzasini bekor qilish; tasdiq bo'lmagan e'lon navbatga kirmaydi."""
    if ad.status != AdStatus.PAUSED or not ad.admin_paused:
        return False
    ad.admin_paused = False
    subscription = await subscription_service.active_for(session, ad.seller_id)
    if ad.approved_at is None:
        ad.status = AdStatus.PENDING
        ad.next_eligible_at = None
    elif subscription is not None:
        ad.status = AdStatus.ACTIVE
        ad.next_eligible_at = utcnow() + timedelta(seconds=subscription_service.interval_for(subscription))
    # Obuna tugagan bo'lsa PAUSED qoladi; sotuvchi yangi tarifdan keyin Start qiladi.
    session.add(ModerationLog(ad_id=ad.id, admin_id=admin_id, decision="resumed"))
    await session.flush()
    return True


async def admin_pause(session: AsyncSession, ad: Ad, admin_id: int | None, reason: str | None = None) -> bool:
    """Admin tomonidan to'xtatish (shikoyat bo'lganda)."""
    if ad.status not in (AdStatus.ACTIVE, AdStatus.PENDING):
        return False
    ad.status = AdStatus.PAUSED
    ad.admin_paused = True
    session.add(
        ModerationLog(
            ad_id=ad.id, admin_id=admin_id, decision="paused", reason=clean_text(reason, limit=300)
        )
    )
    await session.flush()
    return True


# ═══════════════════════════ Navbat ═══════════════════════════════
async def renumber_category(session: AsyncSession, category_id: int) -> int:
    """Toifadagi e'lonlarni 100, 200, 300... qilib qayta raqamlash."""
    ads = (
        await session.execute(
            select(Ad)
            .where(Ad.category_id == category_id, Ad.status != AdStatus.DELETED)
            .order_by(Ad.position, Ad.id)
        )
    ).scalars().all()
    for index, ad in enumerate(ads, start=1):
        ad.position = index * POSITION_GAP
    await session.flush()
    return len(ads)


async def move(
    session: AsyncSession, ad: Ad, direction: str, *, page: int = 0, limit: int = 8
) -> bool:
    """Navbat tartibini o'zgartirish (⬆️ avvalroq / ⬇️ keyinroq) — Phase 4 qo'shimcha.

    Qo'shni (boshqa sahifada bo'lsa ham) e'lon bilan `position` almashadi.
    Eski ma'lumotda pozitsiyalar bir xil bo'lsa — oldin qayta raqamlanadi.
    """
    if direction not in ("up", "down") or ad.status not in (AdStatus.ACTIVE, AdStatus.PAUSED):
        return False

    siblings = (
        await session.execute(
            select(Ad)
            .where(
                Ad.category_id == ad.category_id,
                Ad.status.in_((AdStatus.ACTIVE, AdStatus.PAUSED)),
                Ad.id != ad.id,
            )
            .order_by(Ad.position, Ad.id)
        )
    ).scalars().all()

    ordered = sorted([*siblings, ad], key=lambda row: (row.position, row.id))
    index = ordered.index(ad)
    target = index - 1 if direction == "up" else index + 1
    if target < 0 or target >= len(ordered):
        return False

    neighbour = ordered[target]
    if ad.position == neighbour.position:
        await renumber_category(session, ad.category_id)
        ordered.sort(key=lambda row: (row.position, row.id))
        index = ordered.index(ad)
        target = index - 1 if direction == "up" else index + 1
        neighbour = ordered[target]
    ad.position, neighbour.position = neighbour.position, ad.position
    await session.flush()
    return True


def pages(count: int, per_page: int) -> int:
    return max(1, ceil(count / per_page)) if per_page else 1


__all__ = [
    "ADMIN_FILTERS",
    "EDITABLE_FIELDS",
    "MAX_PHOTOS_HARD",
    "POSITION_GAP",
    "SELLER_STATUSES",
    "STATUS_FILTERS",
    "ad_label",
    "ad_stats",
    "daily_post_counts",
    "add_photo",
    "admin_pause",
    "admin_resume",
    "approve",
    "can_submit",
    "category_of",
    "count_ads",
    "count_by_status",
    "count_pending",
    "count_seller_ads",
    "create_draft",
    "default_contact",
    "edited",
    "filter_label",
    "format_ad_price",
    "get_ad",
    "hard_delete_empty_draft",
    "list_ads",
    "list_seller_ads",
    "max_position",
    "moderation_history",
    "moderation_required",
    "move",
    "next_position",
    "pages",
    "pause",
    "pending_ads",
    "photo_count",
    "photo_limit",
    "photos_line",
    "reject",
    "remove_photo",
    "renumber_category",
    "resume",
    "seller_ads_stats",
    "set_category",
    "set_contact",
    "set_description",
    "set_price",
    "set_title",
    "soft_delete",
    "status_badge",
    "status_title",
    "submit",
    "validate_for_submit",
]
