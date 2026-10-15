"""Phase 5: karta navbati, cheklar, firibgarlik belgisi va obuna qarori."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.constants import PaymentStatus, SellerStatus, SubscriptionStatus
from app.db.models import ActionLog, Payment, Seller, Tariff
from app.services import payment_service as pay
from app.services import subscription_service
from app.services.settings_service import settings_service
from app.utils.time import ensure_aware


async def setup(session):
    seller = Seller(user_id=505050, display_name="Do'kon", status=SellerStatus.PENDING)
    tariff = Tariff(name="Biznes", price=Decimal("150000.00"), duration_days=30,
                    max_ads=4, max_photos=3, is_active=True)
    session.add_all([seller, tariff])
    await session.flush()
    method = await pay.create_method(
        session, name="Uzcard 1", card_number="8600 1234-5678 9012",
        holder="Sherzod <Test>", bank="Bank", note="Izoh",
    )
    return seller, tariff, method


def test_card_validation_mask_and_currency() -> None:
    assert pay.normalize_card(" 8600-1234 5678-9012 ") == "8600123456789012"
    assert pay.normalize_card("86001234x6789012") is None
    assert pay.normalize_card("٨٦٠٠١٢٣٤٥٦٧٨٩٠١٢") is None  # faqat ASCII raqam
    assert pay.mask_card("8600123456789012") == "•••• 9012"
    assert pay.display_card("8600123456789012") == "8600 1234 5678 9012"


async def test_methods_crud_and_round_robin(session) -> None:
    seller, tariff, first = await setup(session)
    second = await pay.create_method(session, name="Humo", card_number="9860123456789012")
    usd = await pay.create_method(session, name="Dollar", card_number="1234567890123456", currency="USD")
    assert await pay.choose_method(session, "UZS") == first
    assert await pay.choose_method(session, "USD") == usd

    one = await pay.submit_receipt(
        session, seller=seller, tariff=tariff, method=first, file_id="file1", file_unique_id="uniq1"
    )
    assert one.receipt_unique_hash and len(one.receipt_unique_hash) == 64
    assert await pay.choose_method(session, "UZS") == second
    await pay.submit_receipt(
        session, seller=seller, tariff=tariff, method=second, file_id="file2", file_unique_id="uniq2"
    )
    assert await pay.choose_method(session, "UZS") == first
    await pay.update_method(session, first, "note", "-")
    await pay.update_method(session, first, "name", "Yangi nom")
    assert first.note is None and first.name == "Yangi nom"
    assert await pay.move_method(session, second, "up")
    assert (await pay.list_methods(session))[0].id == second.id
    first.is_active = False
    await session.flush()
    assert await pay.choose_method(session, "UZS") == second
    assert (await pay.count_methods(session)) == 3
    assert len(await pay.list_methods(session, active_only=True)) == 2
    with pytest.raises(ValueError, match="16–19"):
        await pay.update_method(session, first, "card_number", "invalid")
    with pytest.raises(ValueError, match="Valyuta"):
        await pay.create_method(session, name="Bad", card_number="1234567890123456", currency="U-Z")


async def test_duplicate_receipt_flag_and_no_double_grant(session) -> None:
    seller, tariff, method = await setup(session)
    first = await pay.submit_receipt(
        session, seller=seller, tariff=tariff, method=method, file_id="id-v1", file_unique_id="same"
    )
    again = await pay.submit_receipt(
        session, seller=seller, tariff=tariff, method=method, file_id="id-v2", file_unique_id="same"
    )
    assert first.id != again.id
    assert first.receipt_unique_hash and again.receipt_unique_hash is None
    assert again.is_duplicate_receipt and not first.is_duplicate_receipt
    assert (await pay.decide(session, again.id, admin_id=111, approve=True)).status == "duplicate"
    assert (await pay.get_payment(session, again.id)).status == PaymentStatus.PENDING
    approved = await pay.decide(session, first.id, admin_id=111, approve=True)
    assert approved.status == "approved" and approved.subscription is not None
    assert seller.status == SellerStatus.ACTIVE
    assert first.subscription_id == approved.subscription.id
    assert approved.subscription.payment_id == first.id
    assert (await pay.decide(session, first.id, admin_id=222, approve=True)).status == "already"
    assert (await pay.decide(session, again.id, admin_id=111, approve=False, reason="Eski chek")).status == "rejected"
    assert again.reason == "Eski chek" and again.admin_id == 111
    assert len((await session.execute(select(ActionLog).where(ActionLog.entity == "payment"))).scalars().all()) == 2
    assert len((await session.execute(select(Payment))).scalars().all()) == 2
    assert (await pay.count_payments(session, status="pending")) == 0


async def test_same_tariff_extends_and_new_tariff_switches(session) -> None:
    seller, tariff, method = await setup(session)
    first = await pay.submit_receipt(
        session, seller=seller, tariff=tariff, method=method, file_id="a", file_unique_id="A"
    )
    first_sub = (await pay.decide(session, first.id, admin_id=111, approve=True)).subscription
    assert first_sub.ads_limit == 4
    baseline = ensure_aware(first_sub.expires_at)
    second = await pay.submit_receipt(
        session, seller=seller, tariff=tariff, method=method, file_id="b", file_unique_id="B"
    )
    second_sub = (await pay.decide(session, second.id, admin_id=111, approve=True)).subscription
    assert second_sub.id == first_sub.id and second_sub.ads_limit == 8
    assert ensure_aware(second_sub.expires_at) == baseline + timedelta(days=30)
    assert second.subscription_id == first.subscription_id

    premium = Tariff(name="Premium", price=Decimal("250000"), duration_days=90,
                     max_ads=20, max_photos=7, is_active=True)
    session.add(premium)
    await session.flush()
    third = await pay.submit_receipt(
        session, seller=seller, tariff=premium, method=method, file_id="c", file_unique_id="C"
    )
    third_sub = (await pay.decide(session, third.id, admin_id=222, approve=True)).subscription
    assert third_sub.tariff_id == premium.id and third_sub.id != first_sub.id
    assert first_sub.status == SubscriptionStatus.CANCELLED
    assert third_sub.ads_limit == 20


async def test_reject_requires_reason_and_blocked_seller_is_not_unblocked(session) -> None:
    seller, tariff, method = await setup(session)
    payment = await pay.submit_receipt(
        session, seller=seller, tariff=tariff, method=method, file_id="r", file_unique_id="reject"
    )
    assert (await pay.decide(session, payment.id, admin_id=111, approve=False, reason="-")).status == "invalid"
    seller.status = SellerStatus.BLOCKED
    assert (await pay.decide(session, payment.id, admin_id=111, approve=True)).status == "blocked"
    assert payment.status == PaymentStatus.PENDING and seller.status == SellerStatus.BLOCKED
    rejected = await pay.decide(session, payment.id, admin_id=111, approve=False, reason="Summa mos emas")
    assert rejected.status == "rejected" and rejected.payment.reason == "Summa mos emas"
    assert (await subscription_service.active_for(session, seller.id)) is None
    assert (await pay.decide(session, 9999, admin_id=111, approve=True)).status == "missing"


async def test_receipt_requirement_optional_and_tariff_snapshot(session) -> None:
    seller, tariff, method = await setup(session)
    with pytest.raises(ValueError, match="Chek rasmini"):
        await pay.submit_receipt(session, seller=seller, tariff=tariff, method=method,
                                 file_id=None, file_unique_id=None)
    await settings_service.set(session, "receipt_required", False)
    pay_without_photo = await pay.submit_receipt(
        session, seller=seller, tariff=tariff, method=method, file_id=None, file_unique_id=None
    )
    assert pay_without_photo.status == PaymentStatus.PENDING
    assert pay_without_photo.receipt_unique_hash is None
    tariff.price = Decimal("200000")
    assert pay_without_photo.amount == Decimal("150000")

    await settings_service.set(session, "receipt_duplicate_check", False)
    one = await pay.submit_receipt(
        session, seller=seller, tariff=tariff, method=method, file_id="dup1", file_unique_id="dup"
    )
    two = await pay.submit_receipt(
        session, seller=seller, tariff=tariff, method=method, file_id="dup2", file_unique_id="dup"
    )
    assert one.receipt_unique_hash is two.receipt_unique_hash is None
    assert not one.is_duplicate_receipt and not two.is_duplicate_receipt
    tariff.is_active = False
    with pytest.raises(ValueError, match="tarifni"):
        await pay.submit_receipt(
            session, seller=seller, tariff=tariff, method=method, file_id="c", file_unique_id="x"
        )


async def test_history_is_sorted_and_seller_scoped(session) -> None:
    seller, tariff, method = await setup(session)
    other = Seller(user_id=606060, display_name="Boshqa", status=SellerStatus.PENDING)
    session.add(other)
    await session.flush()
    one = await pay.submit_receipt(
        session, seller=seller, tariff=tariff, method=method, file_id="a", file_unique_id="a"
    )
    two = await pay.submit_receipt(
        session, seller=seller, tariff=tariff, method=method, file_id="b", file_unique_id="b"
    )
    await pay.submit_receipt(
        session, seller=other, tariff=tariff, method=method, file_id="c", file_unique_id="c"
    )
    assert [row.id for row in await pay.list_payments(session, seller_id=seller.id)] == [two.id, one.id]
    assert await pay.count_payments(session, seller_id=seller.id) == 2
    assert await pay.count_payments(session, seller_id=seller.id, status="approved") == 0
    assert await pay.count_payments(session, status="pending") == 3
