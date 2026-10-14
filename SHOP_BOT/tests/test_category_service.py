"""Kategoriya (toifa) servisi testlari — Phase 1."""

from __future__ import annotations

from aiogram.types import Chat

from app.db.models import Ad, Category, CategoryRotation, Group, GroupSettings
from app.services import category_service, group_service

TENANT = -1001111222333


async def _make_group(session, title: str = "Telefonlar bozori") -> Group:
    group = await group_service.get_or_create_group(
        session, Chat(id=TENANT, type="supergroup", title=title)
    )
    await session.flush()
    return group


async def test_create_category_with_emoji_in_name(session) -> None:
    category = await category_service.create_category(session, name="📱 Telefonlar", created_by=1)

    assert category is not None
    assert category.name == "Telefonlar"
    assert category.emoji == "📱"
    assert category.is_active is True
    assert category.group_id is None
    assert category.position > 0


async def test_create_category_without_emoji(session) -> None:
    category = await category_service.create_category(session, name="Avtomobillar")
    assert category is not None
    assert category.emoji is None
    assert category.name == "Avtomobillar"


async def test_create_category_rejects_empty_name(session) -> None:
    assert await category_service.create_category(session, name="   ") is None
    assert await category_service.create_category(session, name="") is None


async def test_create_category_trims_long_name(session) -> None:
    long_name = "A" * 300
    category = await category_service.create_category(session, name=long_name)
    assert category is not None
    assert len(category.name) <= 101  # cheklov + ellipsis


async def test_create_category_with_group_creates_rotation(session) -> None:
    group = await _make_group(session)
    category = await category_service.create_category(
        session, name="Telefonlar", group_id=group.id
    )
    assert category is not None
    assert category.rotation is not None
    assert category.rotation.category_id == category.id

    # Bazada ham mavjud
    rotations = list((await session.execute(CategoryRotation.__table__.select())).all())
    assert len(rotations) == 1


async def test_attach_and_detach_group(session) -> None:
    group = await _make_group(session)
    category = await category_service.create_category(session, name="Kiyimlar")
    assert category is not None

    await category_service.attach_group(session, category, group.id)
    assert category.group_id == group.id
    assert category.rotation is not None
    assert category.rotation.is_paused is False

    title = await category_service.group_title(session, category.group_id)
    assert title == "Telefonlar bozori"

    await category_service.attach_group(session, category, None)
    assert category.group_id is None
    assert category.rotation is not None
    assert category.rotation.is_paused is True

    assert await category_service.group_title(session, None) is None


async def test_positions_increase_on_create(session) -> None:
    first = await category_service.create_category(session, name="Birinchi")
    second = await category_service.create_category(session, name="Ikkinchi")
    third = await category_service.create_category(session, name="Uchinchi")

    assert first and second and third
    assert first.position < second.position < third.position


async def test_move_changes_order(session) -> None:
    first = await category_service.create_category(session, name="A")
    second = await category_service.create_category(session, name="B")
    assert first and second

    moved = await category_service.move(session, second, "up")
    assert moved is True

    ordered = await category_service.list_categories(session)
    assert [c.id for c in ordered] == [second.id, first.id]

    # Birinchi elementни yuqoriga surib bo'lmaydi
    assert await category_service.move(session, second, "up") is False


async def test_rename_category_extracts_emoji(session) -> None:
    category = await category_service.create_category(session, name="Telefonlar")
    assert category is not None

    updated = await category_service.rename_category(session, category, "💻 Kompyuterlar")
    assert updated is not None
    assert updated.name == "Kompyuterlar"
    assert updated.emoji == "💻"

    assert await category_service.rename_category(session, category, "  ") is None


async def test_toggles(session) -> None:
    group = await _make_group(session)
    category = await category_service.create_category(session, name="Xizmatlar", group_id=group.id)
    assert category is not None

    await category_service.set_active(session, category, False)
    assert category.is_active is False

    await category_service.set_moderation(session, category, True)
    assert category.moderation_required is True

    await category_service.set_interval_override(session, category, 600)
    assert category.interval_override == 600

    await category_service.set_interval_override(session, category, None)
    assert category.interval_override is None


async def test_stats_and_counts(session) -> None:
    group = await _make_group(session)
    attached = await category_service.create_category(session, name="Attached", group_id=group.id)
    await category_service.create_category(session, name="Free")
    assert attached is not None

    stats = await category_service.count_categories_stats(session)
    assert stats == {"total": 2, "attached": 1, "free": 1}

    detail = await category_service.get_category_stats(session, attached.id)
    assert detail == {"total": 0, "active": 0, "pending": 0}


async def test_delete_category(session) -> None:
    category = await category_service.create_category(session, name="Vaqtinchalik")
    assert category is not None
    category_id = category.id

    await category_service.delete_category(session, category)
    assert await category_service.get_category(session, category_id) is None


async def test_list_for_group(session) -> None:
    group = await _make_group(session)
    await category_service.create_category(session, name="A", group_id=group.id)
    await category_service.create_category(session, name="B")  # guruhsiz

    for_group = await category_service.list_categories_for_group(session, group.id)
    assert len(for_group) == 1
    assert for_group[0].name == "A"


async def test_display_name(session) -> None:
    with_emoji = await category_service.create_category(session, name="📱 Telefonlar")
    without = await category_service.create_category(session, name="Boshqa")
    assert with_emoji and without

    assert category_service.display_name(with_emoji) == "📱 Telefonlar"
    assert category_service.display_name(without) == "Boshqa"


async def test_group_stats_counts_categories_and_ads(session) -> None:
    from decimal import Decimal

    from app.constants import AdStatus
    from app.db.models import Seller

    group = await _make_group(session)
    category = await category_service.create_category(session, name="Telefonlar", group_id=group.id)
    assert category is not None

    seller = Seller(user_id=555, referral_code="grpsts")
    session.add(seller)
    await session.flush()

    session.add(
        Ad(
            seller_id=seller.id,
            category_id=category.id,
            group_id=group.id,
            title="Test e'lon",
            price=Decimal("1000"),
            status=AdStatus.ACTIVE,
        )
    )
    await session.flush()

    stats = await group_service.get_group_stats(session, group)
    assert stats == {"categories": 1, "ads": 1}


async def test_group_settings_has_defaults_for_new_group(session) -> None:
    group = await _make_group(session)
    settings = await session.get(GroupSettings, group.id)
    assert settings is not None
    assert settings.posting_enabled is False
