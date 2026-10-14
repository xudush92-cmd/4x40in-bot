"""Model va sxema testlari."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select

from app.constants import AdStatus, SubscriptionStatus
from app.db.base import Base
from app.db.models import Ad, AdPhoto, Category, Group, GroupSettings, Seller, Subscription, Tariff, User
from app.utils.time import utcnow

# REJA.md 4-bo'limidagi jadvallar to'liq yaratilganini tekshirish
EXPECTED_TABLES = {
    # 4.1 Yadro
    "users", "admins", "group_admins", "settings", "bot_texts", "action_log", "error_log",
    # 4.2 Guruhlar / toifalar
    "groups", "group_settings", "group_rotation", "categories", "required_channels", "permissions",
    # 4.3 Sotuvchi / tarif / obuna
    "sellers", "tariffs", "subscriptions",
    # 4.4 E'lon / navbat
    "ads", "ad_photos", "category_rotation", "posted_messages", "moderation_log", "post_log",
    # 4.5 To'lov
    "payment_methods", "payments",
    # 4.6 Referal
    "referral_settings", "referrals", "referral_bonus_log",
    # 4.7 Sanoqchi
    "counter_settings", "invite_links", "invite_events", "counter_totals", "counter_audit",
    # 4.8 Posbon / tozalovchi
    "guard_settings", "warnings", "violations", "restrictions", "cleaner_settings", "cleanup_log",
    # 4.9 Statistika / broadcast
    "stats_daily", "broadcasts", "broadcast_targets",
}


def test_all_tables_defined() -> None:
    tables = set(Base.metadata.tables)
    missing = EXPECTED_TABLES - tables
    assert not missing, f"Yetishmayotgan jadvallar: {missing}"


def test_schema_creates_on_sqlite() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    assert len(engine.dialect.get_table_names(engine.connect())) == len(Base.metadata.tables)


def test_telegram_ids_are_bigint() -> None:
    """Telegram ID'lar BigInteger bo'lishi shart (int32 ga sig'maydi)."""
    from sqlalchemy import BigInteger

    for table_name, column_name in (
        ("users", "user_id"),
        ("groups", "tg_chat_id"),
        ("sellers", "user_id"),
        ("invite_events", "invitee_id"),
    ):
        column = Base.metadata.tables[table_name].c[column_name]
        assert isinstance(column.type, BigInteger), f"{table_name}.{column_name} BigInteger emas"


def test_unique_constraints() -> None:
    """Takrorlanishni to'sadigan asosiy cheklovlar joyidami."""
    constraints = {
        table: {c.name for c in Base.metadata.tables[table].constraints} for table in
        ("invite_events", "referrals", "payments", "group_admins")
    }
    assert "uq_invite_event_once" in constraints["invite_events"]
    assert "uq_referral_referee" in constraints["referrals"]
    assert "uq_payments_receipt_hash" in constraints["payments"]
    assert "uq_group_admin" in constraints["group_admins"]


async def test_group_settings_and_rotation_created(session) -> None:
    group = Group(tg_chat_id=-100123456789, title="Test guruh", is_supergroup=True)
    group.settings = GroupSettings()
    session.add(group)
    await session.flush()

    assert group.settings is not None
    assert group.settings.interval_sec == 1800
    assert group.settings.posting_enabled is False

    count = (await session.execute(select(func.count()).select_from(GroupSettings))).scalar_one()
    assert count == 1


async def test_ad_caption_rendering(session) -> None:
    user = User(user_id=999, first_name="Ali")
    session.add(user)
    await session.flush()
    seller = Seller(user_id=999, display_name="Ali", referral_code="abc123")
    session.add(seller)
    await session.flush()
    category = Category(name="Telefonlar", emoji="📱")
    session.add(category)
    await session.flush()

    # Bog'liq obyektlarni konstruktorda beramiz — async kontekstda
    # lazy-load (MissingGreenlet) bo'lmasligi uchun.
    ad = Ad(
        seller_id=seller.id,
        category_id=category.id,
        category=category,
        title="iPhone 15 Pro",
        description="Yangi, 256GB",
        price=Decimal("12500000"),
        currency="UZS",
        contact_type="username",
        contact_value="@ali_shop",
        status=AdStatus.ACTIVE,
        photos=[AdPhoto(file_id="AgAD_test", position=0)],
    )
    session.add(ad)
    await session.flush()

    caption = ad.caption
    assert "iPhone 15 Pro" in caption
    assert "12 500 000 UZS" in caption
    assert "#Telefonlar" in caption
    assert len(ad.photos) == 1


async def test_subscription_properties(session) -> None:
    user = User(user_id=777)
    session.add(user)
    await session.flush()
    seller = Seller(user_id=777, referral_code="xyz789")
    session.add(seller)
    await session.flush()
    tariff = Tariff(name="Test", price=Decimal("100000"), max_ads=5, max_photos=3)
    session.add(tariff)
    await session.flush()

    sub = Subscription(
        seller_id=seller.id,
        tariff_id=tariff.id,
        status=SubscriptionStatus.ACTIVE,
        starts_at=utcnow(),
        expires_at=utcnow() + timedelta(days=30),
        ads_limit=5,
        ads_used=2,
    )
    session.add(sub)
    await session.flush()
    await session.refresh(seller, ["subscriptions"])

    assert sub.is_valid is True
    assert sub.ads_left == 3
    assert seller.active_subscription is not None
    assert seller.active_subscription.id == sub.id


async def test_expired_subscription_not_valid(session) -> None:
    user = User(user_id=555)
    session.add(user)
    await session.flush()
    seller = Seller(user_id=555, referral_code="exp1")
    session.add(seller)
    await session.flush()
    tariff = Tariff(name="Eski", max_ads=1)
    session.add(tariff)
    await session.flush()

    sub = Subscription(
        seller_id=seller.id,
        tariff_id=tariff.id,
        status=SubscriptionStatus.ACTIVE,
        starts_at=utcnow() - timedelta(days=60),
        expires_at=utcnow() - timedelta(days=1),
        ads_limit=1,
    )
    session.add(sub)
    await session.flush()
    await session.refresh(seller, ["subscriptions"])

    assert sub.is_valid is False
    assert seller.active_subscription is None


def test_groups_table_name_is_safe_for_postgres() -> None:
    """`groups` jadvali PostgreSQL reserved so'zlar bilan muammo bermasligi."""
    from sqlalchemy.dialects import postgresql

    preparer = postgresql.dialect().identifier_preparer
    assert preparer.quote("groups") in ("groups", '"groups"')
    # DDL to'liq tayyor bo'lishi kerak (xato bermasligi)
    from sqlalchemy.schema import CreateTable

    ddl = str(CreateTable(Base.metadata.tables["groups"]).compile(dialect=postgresql.dialect()))
    assert "CREATE TABLE" in ddl


@pytest.mark.parametrize("status", [AdStatus.DRAFT, AdStatus.PENDING, AdStatus.PAUSED])
def test_ad_status_values_are_strings(status) -> None:
    assert isinstance(str(status), str)
    assert status == status.value
