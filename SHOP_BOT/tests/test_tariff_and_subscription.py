"""Tarif va obuna servislari testlari (Phase 2)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.constants import AdStatus, SellerStatus, SubscriptionStatus
from app.db.models import Ad, Category, Tariff
from app.services import seller_service, subscription_service, tariff_service
from app.utils.time import utcnow

SELLER_UID = 777000111


# ═══════════════════════════ Tariflar ══════════════════════════════
async def test_create_tariff(session) -> None:
    tariff = await tariff_service.create_tariff(
        session, name="🟢 Boshlang'ich", price="150000", duration_days=30, max_ads=3, max_photos=2
    )

    assert tariff is not None
    assert tariff.name == "🟢 Boshlang'ich"
    assert tariff.price == Decimal("150000.00")
    assert tariff.currency == "UZS"
    assert tariff.max_photos == 2
    assert tariff.is_active is True
    assert tariff.position == 1000


async def test_create_tariff_validation(session) -> None:
    assert await tariff_service.create_tariff(session, name="A") is None            # juda qisqa
    assert await tariff_service.create_tariff(session, name="  ") is None
    assert await tariff_service.create_tariff(session, name="Test", price="salom") is None
    assert await tariff_service.create_tariff(session, name="Test", price=-5) is None


def test_parse_price_formats() -> None:
    assert tariff_service.parse_price("150 000 so'm") == Decimal("150000.00")
    assert tariff_service.parse_price("150,000") == Decimal("150000.00")
    assert tariff_service.parse_price("0") == Decimal("0.00")
    assert tariff_service.parse_price("") == Decimal("0.00")
    assert tariff_service.parse_price("abc") is None
    assert tariff_service.parse_price(-1) is None
    assert tariff_service.parse_price(Decimal("99.999")) == Decimal("100.00")


def test_validators_clamp() -> None:
    assert tariff_service.validate_days(0) == 1
    assert tariff_service.validate_days(99999) == 3650
    assert tariff_service.validate_ads(0) == 1
    assert tariff_service.validate_photos(99) == 10


async def test_positions_and_move(session) -> None:
    first = await tariff_service.create_tariff(session, name="Birinchi")
    second = await tariff_service.create_tariff(session, name="Ikkinchi")
    third = await tariff_service.create_tariff(session, name="Uchinchi")
    assert first and second and third
    assert first.position < second.position < third.position

    assert await tariff_service.move(session, third, "up") is True
    ordered = [t.name for t in await tariff_service.list_tariffs(session)]
    assert ordered == ["Birinchi", "Uchinchi", "Ikkinchi"]

    assert await tariff_service.move(session, third, "up") is True
    assert [t.name for t in await tariff_service.list_tariffs(session)] == ["Uchinchi", "Birinchi", "Ikkinchi"]

    # Chegarada
    assert await tariff_service.move(session, third, "up") is False


async def test_update_tariff_fields(session) -> None:
    tariff = await tariff_service.create_tariff(session, name="Test", price="100000")
    assert tariff

    assert await tariff_service.update_tariff(session, tariff, price="200000", max_ads=50) is True
    assert tariff.price == Decimal("200000.00")
    assert tariff.max_ads == 50

    # Nomni yangilash
    assert await tariff_service.update_tariff(session, tariff, name="Yangi nom") is True
    assert tariff.name == "Yangi nom"

    # O'zgarmasa False
    assert await tariff_service.update_tariff(session, tariff, max_ads=50) is False

    # Noto'g'ri narx — o'zgarmaydi
    assert await tariff_service.update_tariff(session, tariff, price="salom") is False
    assert tariff.price == Decimal("200000.00")


async def test_toggle_active_and_trial(session) -> None:
    tariff = await tariff_service.create_tariff(session, name="Sinov", is_trial=True)
    assert tariff and tariff.is_trial is True

    assert await tariff_service.set_active(session, tariff, False) is True
    assert tariff.is_active is False
    assert await tariff_service.count_tariffs(session, active_only=True) == 0
    assert await tariff_service.list_all_active(session) == []

    assert await tariff_service.set_active(session, tariff, True) is True
    assert len(await tariff_service.list_all_active(session)) == 1


async def test_delete_tariff_without_links(session) -> None:
    tariff = await tariff_service.create_tariff(session, name="Vaqtinchalik")
    assert tariff
    tariff_id = tariff.id

    deleted, message = await tariff_service.delete_tariff(session, tariff)
    assert deleted is True
    assert "o'chirildi" in message
    assert await tariff_service.get_tariff(session, tariff_id) is None


async def test_delete_tariff_with_subscriptions_only_deactivates(session) -> None:
    seller, _ = await seller_service.get_or_create_seller(session, SELLER_UID, display_name="Sotuvchi")
    tariff = await tariff_service.create_tariff(session, name="Band tarif", max_ads=5)
    assert tariff

    await subscription_service.grant(session, seller, tariff)
    deleted, message = await tariff_service.delete_tariff(session, tariff)

    assert deleted is False
    assert "to'xtatildi" in message
    assert tariff.is_active is False
    assert await tariff_service.get_tariff(session, tariff.id) is not None  # yozuv qoldi


async def test_tariff_stats(session) -> None:
    seller, _ = await seller_service.get_or_create_seller(session, SELLER_UID)
    tariff = await tariff_service.create_tariff(session, name="Statistika", max_ads=10)
    assert tariff

    await subscription_service.grant(session, seller, tariff)
    stats = await tariff_service.get_stats(session, tariff)

    assert stats["subscriptions"] == 1
    assert stats["active"] == 1
    assert stats["payments"] == 0


# ═══════════════════════════ Obunalar ══════════════════════════════
async def _seller_and_tariff(session, *, max_ads: int = 5, days: int = 30):
    seller, _ = await seller_service.get_or_create_seller(session, SELLER_UID, display_name="Sotuvchi")
    tariff = await tariff_service.create_tariff(
        session, name="Tarif", price="100000", duration_days=days, max_ads=max_ads
    )
    assert tariff is not None
    return seller, tariff


async def test_grant_creates_subscription_and_activates_seller(session) -> None:
    seller, tariff = await _seller_and_tariff(session, max_ads=10)
    assert seller.status == SellerStatus.PENDING

    subscription = await subscription_service.grant(session, seller, tariff, granted_by=999)

    assert subscription.status == SubscriptionStatus.ACTIVE
    assert subscription.ads_limit == 10
    assert subscription.ads_used == 0
    assert subscription.granted_by == 999
    assert subscription_service.days_left(subscription) in (29, 30)
    assert seller.status == SellerStatus.ACTIVE
    assert subscription.is_valid is True


async def test_grant_same_tariff_extends(session) -> None:
    seller, tariff = await _seller_and_tariff(session, max_ads=5, days=30)

    first = await subscription_service.grant(session, seller, tariff)
    first_expires = first.expires_at

    second = await subscription_service.grant(session, seller, tariff)

    assert second.id == first.id                      # yangi yozuv yaratilmaydi
    assert second.ads_limit == 10                     # limitlar qo'shiladi
    assert second.expires_at > first_expires          # muddat uzaytirildi

    history = await subscription_service.history(session, seller.id)
    assert len(history) == 1


async def test_grant_other_tariff_replaces(session) -> None:
    seller, tariff = await _seller_and_tariff(session, max_ads=5)
    premium = await tariff_service.create_tariff(session, name="Premium", max_ads=30)
    assert premium is not None

    first = await subscription_service.grant(session, seller, tariff)
    second = await subscription_service.grant(session, seller, premium)

    assert second.id != first.id
    assert second.tariff_id == premium.id
    assert second.ads_limit == 30

    history = await subscription_service.history(session, seller.id)
    assert len(history) == 2
    assert history[1].status == SubscriptionStatus.CANCELLED   # eski obuna yopildi


async def test_grant_after_expiry_starts_new(session) -> None:
    seller, tariff = await _seller_and_tariff(session, max_ads=5)
    first = await subscription_service.grant(session, seller, tariff)
    first.expires_at = utcnow() - timedelta(days=1)
    await session.flush()

    assert await subscription_service.active_for(session, seller.id) is None
    assert subscription_service.is_expired(first) is True

    second = await subscription_service.grant(session, seller, tariff)
    assert second.id != first.id
    assert subscription_service.days_left(second) in (29, 30)


async def test_extend_and_cancel(session) -> None:
    seller, tariff = await _seller_and_tariff(session, days=30)
    subscription = await subscription_service.grant(session, seller, tariff)
    before = subscription.expires_at

    await subscription_service.extend(session, subscription, 15)
    assert subscription.expires_at > before

    # Muddati o'tgan obunani uzaytirish — qayta faollashadi
    subscription.expires_at = utcnow() - timedelta(days=5)
    subscription.status = SubscriptionStatus.EXPIRED
    await session.flush()

    await subscription_service.extend(session, subscription, 10)
    assert subscription.status == SubscriptionStatus.ACTIVE
    assert subscription_service.days_left(subscription) in (9, 10)

    await subscription_service.cancel(session, subscription, reason="test")
    assert subscription.status == SubscriptionStatus.CANCELLED


async def test_can_publish_and_limits(session) -> None:
    seller, tariff = await _seller_and_tariff(session, max_ads=2)

    allowed, reason = await subscription_service.can_publish(session, seller)
    assert allowed is False and "tarif berilmagan" in reason.lower()

    await subscription_service.grant(session, seller, tariff)

    allowed, reason = await subscription_service.can_publish(session, seller)
    assert allowed is True and reason == ""

    # Limitdan foydalanish
    subscription = await subscription_service.active_for(session, seller.id)
    assert subscription is not None
    assert await subscription_service.consume_slot(session, subscription) is True
    assert subscription.ads_used == 1
    assert subscription.ads_left == 1

    assert await subscription_service.consume_slot(session, subscription) is True
    allowed, reason = await subscription_service.can_publish(session, seller)
    assert allowed is False and "limit" in reason.lower()

    # Limitni qo'lda ko'paytirish
    await subscription_service.set_ads_limit(session, subscription, 5)
    assert (await subscription_service.can_publish(session, seller))[0] is True

    # Limitni qaytarish (e'lon o'chirilganda)
    await subscription_service.release_slot(session, subscription)
    assert subscription.ads_used == 1

    # Bloklangan sotuvchi
    await seller_service.set_status(session, seller, SellerStatus.BLOCKED)
    allowed, reason = await subscription_service.can_publish(session, seller)
    assert allowed is False and "bloklangan" in reason.lower()


async def test_can_publish_expired(session) -> None:
    seller, tariff = await _seller_and_tariff(session)
    subscription = await subscription_service.grant(session, seller, tariff)
    subscription.expires_at = utcnow() - timedelta(hours=1)
    await session.flush()

    allowed, reason = await subscription_service.can_publish(session, seller)
    assert allowed is False and "muddati" in reason.lower()


async def test_expire_due_with_and_without_grace(session) -> None:
    seller, tariff = await _seller_and_tariff(session)
    active = await subscription_service.grant(session, seller, tariff)
    active.expires_at = utcnow() - timedelta(hours=1)

    seller2, _ = await seller_service.get_or_create_seller(session, SELLER_UID + 1, display_name="Ikkinchi")
    second = await subscription_service.grant(session, seller2, tariff)
    second.expires_at = utcnow() - timedelta(hours=1)
    await session.flush()

    # grace_days = 3 → ikkalasi "grace" holatiga o'tadi
    changed = await subscription_service.expire_due(session, grace_days=3)
    assert len(changed) == 2
    assert active.status == SubscriptionStatus.GRACE
    assert second.status == SubscriptionStatus.GRACE

    # grace muddati ham o'tdi → expired
    active.expires_at = utcnow() - timedelta(days=5)
    second.expires_at = utcnow() - timedelta(days=5)
    await session.flush()

    changed = await subscription_service.expire_due(session, grace_days=3)
    assert {sub.status for sub in changed} == {SubscriptionStatus.EXPIRED}


async def test_expire_due_without_grace(session) -> None:
    seller, tariff = await _seller_and_tariff(session)
    subscription = await subscription_service.grant(session, seller, tariff)
    subscription.expires_at = utcnow() - timedelta(minutes=1)
    await session.flush()

    changed = await subscription_service.expire_due(session, grace_days=0)
    assert len(changed) == 1
    assert subscription.status == SubscriptionStatus.EXPIRED


async def test_reminders_due(session) -> None:
    seller, tariff = await _seller_and_tariff(session, days=30)
    subscription = await subscription_service.grant(session, seller, tariff)

    # Muddat yaqin emas — eslatma yo'q
    assert await subscription_service.reminders_due(session, days=3) == []

    # Muddatni 2 kunga tushiramiz
    subscription.expires_at = utcnow() + timedelta(days=2)
    await session.flush()

    due = await subscription_service.reminders_due(session, days=3)
    assert [sub.id for sub in due] == [subscription.id]

    # Belgilangach qayta chiqmaydi
    subscription_service.mark_reminded(subscription)
    await session.flush()
    assert await subscription_service.reminders_due(session, days=3) == []

    # Muddati o'tganlar ro'yxatiga tushadi (xabar berilmagan)
    subscription.status = SubscriptionStatus.EXPIRED
    await session.flush()
    assert [sub.id for sub in await subscription_service.expired_without_notice(session)] == [
        subscription.id
    ]
    subscription_service.mark_expired_notified(subscription)
    await session.flush()
    assert await subscription_service.expired_without_notice(session) == []


async def test_summary_helpers(session) -> None:
    seller, tariff = await _seller_and_tariff(session, max_ads=5)
    assert "tarif yo'q" in subscription_service.summary_line(None)
    assert subscription_service.status_title(None) == "⛔️ Obuna yo'q"

    subscription = await subscription_service.grant(session, seller, tariff)
    line = subscription_service.summary_line(subscription, tariff)
    assert "Tarif" in line and "5" in line
    assert "Faol" in subscription_service.status_title(subscription)
    assert subscription_service.as_dict(subscription)["status"] == SubscriptionStatus.ACTIVE


async def test_count_active(session) -> None:
    seller, tariff = await _seller_and_tariff(session)
    assert await subscription_service.count_active(session) == 0

    subscription = await subscription_service.grant(session, seller, tariff)
    assert await subscription_service.count_active(session) == 1

    subscription.expires_at = utcnow() - timedelta(days=1)
    await session.flush()
    assert await subscription_service.count_active(session) == 0


async def test_stats_counts_ads_in_window(session) -> None:
    seller, tariff = await _seller_and_tariff(session)
    subscription = await subscription_service.grant(session, seller, tariff)

    category = Category(name="Telefonlar", position=1000)
    session.add(category)
    await session.flush()

    session.add(
        Ad(
            seller_id=seller.id,
            category_id=category.id,
            title="Eski e'lon (obunadan oldin)",
            status=AdStatus.ACTIVE,
            created_at=subscription.starts_at - timedelta(days=3),
        )
    )
    session.add(
        Ad(
            seller_id=seller.id,
            category_id=category.id,
            title="Yangi e'lon",
            status=AdStatus.ACTIVE,
        )
    )
    await session.flush()

    stats = await subscription_service.stats(session, subscription)
    assert stats["ads_created"] == 1            # faqat obuna davrida yaratilgani
    assert stats["ads_used"] == subscription.ads_used == 0
    assert stats["ads_left"] == tariff.max_ads


async def test_tariff_model_and_label() -> None:
    tariff = Tariff(name="Test tarif", price=Decimal("50000"), duration_days=30, max_ads=5, max_photos=3)
    assert tariff_service.format_price(tariff) == "50 000 so'm"
    assert "5 e'lon" in tariff_service.limits_line(tariff)
    assert tariff_service.tariffs_label(tariff, 20) == "Test tarif"
