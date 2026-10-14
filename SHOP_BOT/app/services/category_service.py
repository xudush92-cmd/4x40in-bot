"""Toifalar servisi: yaratish, tahrirlash, guruhga biriktirish, tartib, o'chirish."""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdStatus
from app.db.models import Ad, Category, CategoryRotation, Group
from app.utils.text import clean_text, split_name_emoji

POSITION_STEP = 1000


# ──────────────────────────── O'qish ───────────────────────────────
async def get_category(session: AsyncSession, category_id: int) -> Category | None:
    return (await session.execute(select(Category).where(Category.id == category_id))).scalar_one_or_none()


async def count_categories(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(Category))).scalar_one())


async def count_categories_stats(session: AsyncSession) -> dict[str, int]:
    """(guruhga biriktirilgan, biriktirilmagan) toifalar soni."""
    total = await count_categories(session)
    attached = int(
        (
            await session.execute(
                select(func.count()).select_from(Category).where(Category.group_id.is_not(None))
            )
        ).scalar_one()
    )
    return {"total": total, "attached": attached, "free": total - attached}


async def list_categories(session: AsyncSession, *, offset: int = 0, limit: int = 8) -> list[Category]:
    return list(
        (
            await session.execute(
                select(Category)
                .order_by(Category.position.asc(), Category.id.asc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
    )


async def list_categories_for_group(session: AsyncSession, group_id: int) -> list[Category]:
    return list(
        (
            await session.execute(
                select(Category)
                .where(Category.group_id == group_id)
                .order_by(Category.position.asc(), Category.id.asc())
            )
        ).scalars().all()
    )


async def get_category_stats(session: AsyncSession, category_id: int) -> dict[str, int]:
    """Toifa bo'yicha e'lonlar statistikasi."""
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(Ad).where(Ad.category_id == category_id)
            )
        ).scalar_one()
    )
    active = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Ad)
                .where(Ad.category_id == category_id, Ad.status == AdStatus.ACTIVE)
            )
        ).scalar_one()
    )
    pending = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Ad)
                .where(Ad.category_id == category_id, Ad.status == AdStatus.PENDING)
            )
        ).scalar_one()
    )
    return {"total": total, "active": active, "pending": pending}


# ──────────────────────────── Yozish ───────────────────────────────
async def _next_position(session: AsyncSession) -> int:
    max_position = (
        await session.execute(select(func.max(Category.position)))
    ).scalar_one()
    return int(max_position or 0) + POSITION_STEP


async def create_category(
    session: AsyncSession,
    *,
    name: str,
    emoji: str | None = None,
    group_id: int | None = None,
    description: str | None = None,
    moderation_required: bool = False,
    created_by: int | None = None,
) -> Category | None:
    """Toifa yaratish. Nom bo'sh bo'lsa None qaytaradi."""
    clean_name = clean_text(name, limit=120)
    if not clean_name:
        return None

    # Nom ichida emoji bo'lsa — ajratib olamiz ("📱 Telefonlar" → 📱 + Telefonlar)
    detected_emoji, title = split_name_emoji(clean_name)
    emoji = (emoji or detected_emoji) or None
    title = clean_text(title, limit=100) or clean_name

    category = Category(
        name=title,
        emoji=emoji,
        description=clean_text(description, limit=500),
        group_id=group_id,
        moderation_required=moderation_required,
        position=await _next_position(session),
        created_by=created_by,
        is_active=True,
    )
    session.add(category)
    await session.flush()

    if group_id is not None:
        await _ensure_rotation(session, category)

    logger.info("Toifa yaratildi: {}{} (guruh: {})", emoji or "", title, group_id)
    return category


async def rename_category(
    session: AsyncSession, category: Category, name: str
) -> Category | None:
    """Nomni (va emojini) yangilash."""
    clean_name = clean_text(name, limit=120)
    if not clean_name:
        return None

    emoji, title = split_name_emoji(clean_name)
    category.emoji = emoji
    category.name = clean_text(title, limit=100) or clean_name
    await session.flush()
    return category


async def set_description(session: AsyncSession, category: Category, description: str | None) -> None:
    category.description = clean_text(description, limit=500)
    await session.flush()


async def attach_group(
    session: AsyncSession, category: Category, group_id: int | None
) -> None:
    """Guruhga biriktirish (yoki biriktirilishini olib tashlash)."""
    category.group_id = group_id
    await session.flush()

    if group_id is not None:
        await _ensure_rotation(session, category)
    else:
        # Guruhsiz toifa navbatda ishtirok etmaydi
        rotation = await _get_rotation(session, category.id)
        if rotation is not None:
            rotation.next_post_at = None
            rotation.is_paused = True
            await session.flush()
        await _reload_rotation(session, category)

    logger.info(
        "Toifa '{}' {} guruhiga biriktirildi",
        category.name,
        group_id if group_id is not None else "—",
    )


async def _get_rotation(session: AsyncSession, category_id: int) -> CategoryRotation | None:
    """Navbat kursori yozuvini to'g'ridan-to'g'ri so'rov bilan olish
    (relationship'ga tegish async lazy-load xatosini keltirmaydi)."""
    return (
        await session.execute(
            select(CategoryRotation).where(CategoryRotation.category_id == category_id)
        )
    ).scalar_one_or_none()


async def _reload_rotation(session: AsyncSession, category: Category) -> None:
    """`category.rotation` ni xavfsiz (IO ruxsat etilgan holda) yangilash."""
    try:
        await session.refresh(category, ["rotation"])
    except Exception:  # pragma: no cover — yangi obyekt uchun kerak bo'lmasligi mumkin
        pass


async def _ensure_rotation(session: AsyncSession, category: Category) -> CategoryRotation:
    """Toifa uchun navbat kursori yozuvi borligini ta'minlash."""
    rotation = await _get_rotation(session, category.id)
    if rotation is None:
        rotation = CategoryRotation(category_id=category.id, is_paused=False)
        session.add(rotation)
    rotation.is_paused = False
    await session.flush()
    await _reload_rotation(session, category)
    return rotation


async def set_active(session: AsyncSession, category: Category, active: bool) -> None:
    category.is_active = active
    await session.flush()


async def set_moderation(session: AsyncSession, category: Category, required: bool) -> None:
    category.moderation_required = required
    await session.flush()


async def set_interval_override(session: AsyncSession, category: Category, seconds: int | None) -> None:
    """Toifa uchun alohida interval (None = guruh intervali)."""
    category.interval_override = seconds
    await session.flush()


async def move(session: AsyncSession, category: Category, direction: str) -> bool:
    """Tartibni o'zgartirish: 'up' | 'down'. Qaytaradi: o'zgardimi."""
    ordered = await list_categories(session, offset=0, limit=1000)
    index = next((i for i, item in enumerate(ordered) if item.id == category.id), None)
    if index is None:
        return False

    target_index = index - 1 if direction == "up" else index + 1
    if target_index < 0 or target_index >= len(ordered):
        return False

    other = ordered[target_index]
    category.position, other.position = other.position, category.position
    await session.flush()
    return True


async def delete_category(session: AsyncSession, category: Category) -> None:
    """Toifani o'chirish (e'lonlar ham CASCADE bilan o'chadi)."""
    logger.warning("Toifa o'chirildi: {} (id={})", category.name, category.id)
    await session.delete(category)
    await session.flush()


async def group_title(session: AsyncSession, group_id: int | None) -> str | None:
    """Toifa biriktirilgan guruh nomi."""
    if group_id is None:
        return None
    group = (await session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
    return group.display if group else None


def display_name(category: Category) -> str:
    """'📱 Telefonlar' ko'rinishidagi nom."""
    return f"{category.emoji or ''} {category.name}".strip()


async def delete_many(session: AsyncSession, categories: list[Category]) -> int:
    """Bir necha toifani o'chirish (admin amali)."""
    for category in categories:
        await session.delete(category)
    await session.flush()
    return len(categories)


__all__ = [
    "POSITION_STEP",
    "attach_group",
    "count_categories",
    "count_categories_stats",
    "create_category",
    "delete_category",
    "delete_many",
    "display_name",
    "get_category",
    "get_category_stats",
    "group_title",
    "list_categories",
    "list_categories_for_group",
    "move",
    "rename_category",
    "set_active",
    "set_description",
    "set_interval_override",
    "set_moderation",
]


def _typing_guard() -> Any:  # pragma: no cover — faqat tip ko'rsatkichi
    return None
