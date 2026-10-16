"""Tariflar servisi (Phase 2).

Tarif — sotuvchi sotib oladigan paket: narx, muddat, e'lon va rasm limitlari,
ruxsat etilgan guruh/toifalar (`None` = cheklovsiz).

Muhim: tarif **o'chirilmaydi**, agar unga bog'langan obuna/to'lov bo'lsa —
o'rniga `is_active = False` qilinadi (tarix saqlanadi, FK RESTRICT buzilmaydi).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActionLog, Category, Group, Payment, Subscription, Tariff
from app.utils.text import clean_text, fmt_amount, truncate

MAX_NAME_LEN = 64
MAX_DESC_LEN = 500

# Validatsiya chegaralari
MIN_DURATION_DAYS, MAX_DURATION_DAYS = 1, 36500
MIN_ADS, MAX_ADS = 1, 10000
MIN_PHOTOS, MAX_PHOTOS = 1, 10  # Telegram albomi: oshirilmaydi
# Numeric(12, 2) maydonining 10 xonali butun qismiga sig'adi.
MAX_PRICE = Decimal("9999999990")


# ─────────────────────────── O'qish ────────────────────────────────
async def get_tariff(session: AsyncSession, tariff_id: int) -> Tariff | None:
    return await session.get(Tariff, tariff_id)


async def list_tariffs(
    session: AsyncSession,
    *,
    offset: int = 0,
    limit: int = 6,
    active_only: bool = False,
) -> list[Tariff]:
    stmt = select(Tariff).order_by(Tariff.position, Tariff.id)
    if active_only:
        stmt = stmt.where(Tariff.is_active.is_(True))
    return list((await session.execute(stmt.offset(offset).limit(limit))).scalars().all())


async def list_all_active(session: AsyncSession) -> list[Tariff]:
    """Katalog uchun: barcha faol tariflar."""
    return list(
        (
            await session.execute(
                select(Tariff).where(Tariff.is_active.is_(True)).order_by(Tariff.position, Tariff.id)
            )
        ).scalars().all()
    )


async def count_tariffs(session: AsyncSession, *, active_only: bool = False) -> int:
    stmt = select(func.count()).select_from(Tariff)
    if active_only:
        stmt = stmt.where(Tariff.is_active.is_(True))
    return int((await session.execute(stmt)).scalar_one())


async def subscription_count(session: AsyncSession, tariff_id: int) -> int:
    """Shu tarifga bog'langan obunalar soni (o'chirish mumkinmi — shuni aniqlaydi)."""
    return int(
        (
            await session.execute(
                select(func.count()).select_from(Subscription).where(Subscription.tariff_id == tariff_id)
            )
        ).scalar_one()
    )


async def get_stats(session: AsyncSession, tariff: Tariff) -> dict[str, int]:
    """Tarif kartochkasi uchun raqamlar."""
    subs = await subscription_count(session, tariff.id)
    active = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Subscription)
                .where(Subscription.tariff_id == tariff.id, Subscription.status == "active")
            )
        ).scalar_one()
    )
    payments = int(
        (
            await session.execute(
                select(func.count()).select_from(Payment).where(Payment.tariff_id == tariff.id)
            )
        ).scalar_one()
    )
    return {"subscriptions": subs, "active": active, "payments": payments}


# ───────────────────────── Yozish ──────────────────────────────────
async def create_tariff(
    session: AsyncSession,
    *,
    name: str,
    price: Decimal | str | float | int = 0,
    duration_days: int = 30,
    max_ads: int = 5,
    max_photos: int = 3,
    description: str | None = None,
    is_trial: bool = False,
    created_by: int | None = None,  # kelajak uchun (audit)
) -> Tariff | None:
    """Yangi tarif yaratish. Nom noto'g'ri bo'lsa `None`."""
    clean_name = clean_text(name, limit=MAX_NAME_LEN)
    if not clean_name or len(clean_name) < 2:
        return None

    price_value = parse_price(price)
    if price_value is None:
        return None

    tariff = Tariff(
        name=clean_name,
        description=clean_text(description, limit=MAX_DESC_LEN),
        price=price_value,
        duration_days=validate_days(duration_days),
        max_ads=validate_ads(max_ads),
        max_photos=validate_photos(max_photos),
        is_active=True,
        is_trial=bool(is_trial),
        position=await _next_position(session),
    )
    session.add(tariff)
    await session.flush()
    logger.info("Yangi tarif: {} ({})", tariff.name, tariff.price)
    _ = created_by
    return tariff


async def update_tariff(session: AsyncSession, tariff: Tariff, **fields: Any) -> bool:
    """Maydonlarni yangilash (faqat ruxsat etilganlari). O'zgarish bo'lsa True."""
    changed = False

    if (value := fields.get("name")) is not None:
        clean_name = clean_text(str(value), limit=MAX_NAME_LEN)
        if clean_name and len(clean_name) >= 2 and tariff.name != clean_name:
            tariff.name = clean_name
            changed = True

    if (value := fields.get("description")) is not None:
        clean_desc = clean_text(str(value), limit=MAX_DESC_LEN)
        if tariff.description != clean_desc:
            tariff.description = clean_desc
            changed = True

    if (value := fields.get("price")) is not None:
        price_value = parse_price(value)
        if price_value is not None and tariff.price != price_value:
            tariff.price = price_value
            changed = True

    if (value := fields.get("duration_days")) is not None:
        days = validate_days(int(value))
        if tariff.duration_days != days:
            tariff.duration_days = days
            changed = True

    if (value := fields.get("max_ads")) is not None:
        ads = validate_ads(int(value))
        if tariff.max_ads != ads:
            tariff.max_ads = ads
            changed = True

    if (value := fields.get("max_photos")) is not None:
        photos = validate_photos(int(value))
        if tariff.max_photos != photos:
            tariff.max_photos = photos
            changed = True

    if (value := fields.get("is_trial")) is not None:
        if tariff.is_trial != bool(value):
            tariff.is_trial = bool(value)
            changed = True

    if changed:
        await session.flush()
    return changed


async def set_restriction(session: AsyncSession, tariff_id: int, field: str,
                          item_id: int | None, actor_id: int) -> Tariff:
    """Bir guruh/toifani yoqish/o'chirish yoki cheklovni to'liq olib tashlash.

    None — barcha guruh/toifalar; [] — hozircha hech biri (xavfsiz pauza).
    Keraksiz ID'ni saqlamaydi; barcha o'zgarishlar auditda aks etadi.
    """
    if field not in {"allowed_category_ids", "allowed_group_ids"}:
        raise ValueError("Tarif cheklovi noto'g'ri.")
    row = (await session.execute(select(Tariff).where(Tariff.id == tariff_id)
                                 .with_for_update())).scalar_one_or_none()
    if row is None:
        raise ValueError("Tarif topilmadi.")
    old = getattr(row, field)
    if item_id is None:
        new = None
    else:
        model = Category if field == "allowed_category_ids" else Group
        if item_id <= 0 or await session.get(model, item_id) is None:
            raise ValueError("Toifa/guruh topilmadi.")
        current = set(old or [])
        if item_id in current:
            current.remove(item_id)
        else:
            current.add(item_id)
        new = sorted(current)
    if old != new:
        setattr(row, field, new)
        session.add(ActionLog(actor_id=actor_id, action="tariff_restriction", entity="tariff",
                              entity_id=tariff_id, before={field: old}, after={field: new}))
        await session.flush()
    return row


async def set_active(session: AsyncSession, tariff: Tariff, value: bool) -> bool:
    if tariff.is_active == value:
        return False
    tariff.is_active = value
    await session.flush()
    logger.info("Tarif '{}' {}", tariff.name, "yoqildi" if value else "to'xtatildi")
    return True


async def move(session: AsyncSession, tariff: Tariff, direction: str) -> bool:
    """Tartibni almashtirish (⬆️/⬇️). Chegarada bo'lsa False."""
    tariffs = list(
        (await session.execute(select(Tariff).order_by(Tariff.position, Tariff.id))).scalars().all()
    )
    index = next((i for i, item in enumerate(tariffs) if item.id == tariff.id), None)
    if index is None:
        return False

    swap_index = index - 1 if direction == "up" else index + 1
    if swap_index < 0 or swap_index >= len(tariffs):
        return False

    other = tariffs[swap_index]
    if tariff.position == other.position:
        # Bir xil pozitsiya bo'lsa — ketma-ket qayta raqamlaymiz
        for order, item in enumerate(tariffs, start=1):
            item.position = order * 1000
        await session.flush()
        return await move(session, tariff, direction)

    tariff.position, other.position = other.position, tariff.position
    await session.flush()
    return True


async def delete_tariff(session: AsyncSession, tariff: Tariff) -> tuple[bool, str]:
    """Tarifni o'chirish. Bog'langan obuna/to'lov bo'lsa — faqat to'xtatiladi.

    Qaytaradi: (butunlay_o'chirildi, izoh).
    """
    subs = await subscription_count(session, tariff.id)
    payments = int(
        (
            await session.execute(
                select(func.count()).select_from(Payment).where(Payment.tariff_id == tariff.id)
            )
        ).scalar_one()
    )

    if subs or payments:
        tariff.is_active = False
        await session.flush()
        logger.info("Tarif '{}' o'chirilmadi (bog'langan yozuvlar bor) — to'xtatildi", tariff.name)
        return False, f"⚠️ Bu tarifga {subs} obuna va {payments} to'lov bog'langan — o'chirish o'rniga to'xtatildi (tarix saqlanadi)."

    name = tariff.name
    await session.delete(tariff)
    await session.flush()
    logger.info("Tarif o'chirildi: {}", name)
    return True, f"🗑 «{name}» tarifi o'chirildi."


async def _next_position(session: AsyncSession) -> int:
    max_pos = (
        await session.execute(select(func.coalesce(func.max(Tariff.position), 0)))
    ).scalar_one()
    return int(max_pos) + 1000


# ─────────────────────── Validatsiya / formatlash ───────────────────
def parse_price(value: Decimal | str | float | int | None) -> Decimal | None:
    """Narxni Decimal'ga o'girish.

    Qabul qilinadi: `150000`, `150 000`, `150,000`, `150.000`, `150000 so'm`,
    `150000.50` (kasr). O'zbekiston sharoitida narx butun so'mda bo'ladi,
    shuning uchun 3 xonali ajratgich **minglik** deb hisoblanadi.
    """
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        parsed = value
    else:
        text = str(value).strip().lower().replace(" ", "").replace("so'm", "").replace("сум", "")
        if not text:
            return Decimal("0.00")
        text = _normalize_separators(text)
        try:
            parsed = Decimal(text)
        except (InvalidOperation, ValueError):
            return None

    if parsed < 0 or parsed > MAX_PRICE:
        return None
    return parsed.quantize(Decimal("0.01"))


def _normalize_separators(text: str) -> str:
    """Minglik va kasr ajratgichlarini bir normaga keltirish."""
    if "," in text and "." in text:
        # Oxirgi ajratgich — kasr, qolgani minglik
        if text.rfind(",") > text.rfind("."):
            return text.replace(".", "").replace(",", ".")
        return text.replace(",", "")

    if "," in text:
        head, _, tail = text.rpartition(",")
        if head and len(tail) == 3:      # 150,000 → minglik
            return head + tail
        return text.replace(",", ".")

    if "." in text:
        head, _, tail = text.rpartition(".")
        if head and len(tail) == 3:      # 150.000 → minglik
            return head + tail

    return text


def validate_days(value: int) -> int:
    return max(MIN_DURATION_DAYS, min(MAX_DURATION_DAYS, int(value)))


def validate_ads(value: int) -> int:
    return max(MIN_ADS, min(MAX_ADS, int(value)))


def validate_photos(value: int) -> int:
    return max(MIN_PHOTOS, min(MAX_PHOTOS, int(value)))


def format_price(tariff: Tariff) -> str:
    # Eslatma: bazaga yozilmagan obyektda `currency` bo'sh bo'lishi mumkin
    return fmt_amount(tariff.price, tariff.currency or "UZS")


def tariffs_label(tariff: Tariff, limit: int = 22) -> str:
    # `is None` — bazaga hali yozilmagan obyekt (default'lar qo'llanmagan)
    badge = " ⏸" if tariff.is_active is False else ""
    trial = " 🎁" if tariff.is_trial else ""
    return f"{truncate(tariff.name, limit)}{trial}{badge}"


def limits_line(tariff: Tariff) -> str:
    return (
        f"{format_price(tariff)} · {tariff.duration_days} kun · "
        f"📢 {tariff.max_ads} e'lon · 🖼 {tariff.max_photos} rasm"
    )


__all__ = [
    "create_tariff",
    "delete_tariff",
    "format_price",
    "get_stats",
    "get_tariff",
    "limits_line",
    "list_all_active",
    "list_tariffs",
    "move",
    "parse_price",
    "set_active",
    "set_restriction",
    "tariffs_label",
    "update_tariff",
    "validate_ads",
    "validate_days",
    "validate_photos",
]
