"""Phase 8: referal yozuvi, bonus va to'lov rezervatsiyasi offline testlari."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.constants import AdminRole, ReferralTrigger
from app.db.models import Admin, Payment, Referral, ReferralBonusLog, Seller, User
from app.keyboards.admin import settings_kb
from app.keyboards.callbacks import AdminCB, ReferralAdminCB
from app.services import payment_service, seller_service, subscription_service, tariff_service
from app.services import referral_service as refs
from app.services.settings_service import settings_service
from app.utils.time import ensure_aware
from tests.fake_telegram import (
    FakeSession,
    callback_update,
    make_bot,
    make_dispatcher,
    reset_dispatcher_state,
    text_update,
)


async def sellers(session, tariff_price: str = "150000"):
    referrer, _ = await seller_service.get_or_create_seller(session, 10101, display_name="Taklifchi")
    referee, _ = await seller_service.get_or_create_seller(session, 20202, display_name="Do'st")
    tariff = await tariff_service.create_tariff(session, name="Sinov tarif", price=tariff_price)
    method = await payment_service.create_method(session, name="UZS", card_number="8600123456789012")
    await session.commit()
    return referrer, referee, tariff, method


async def enable(session, *, trigger=ReferralTrigger.SIGNUP, kind="balance", value="50000"):
    await refs.set_config(session, "trigger", trigger, 111111)
    await refs.set_config(session, "bonus_type", kind, 111111)
    await refs.set_config(session, "bonus_value", value, 111111)
    await settings_service.set(session, "referral_enabled", True, updated_by=111111)
    await session.commit()


async def test_referral_signup_antifraud_without_daily_quota_and_uniqueness(session):
    referrer, _, _, _ = await sellers(session)
    assert not await refs.register(session, code=referrer.referral_code, referee_id=40404, user_is_new=True)
    await enable(session)
    code = referrer.referral_code
    assert not await refs.register(session, code=code, referee_id=10101, user_is_new=True)  # o'zi
    assert not await refs.register(session, code=code, referee_id=30003, user_is_new=False)
    assert not await refs.register(session, code="BAD-CODE", referee_id=30003, user_is_new=True)
    row = await refs.register(session, code=code, referee_id=30003, user_is_new=True)
    assert row and row.status == "applied"
    assert (await session.get(Seller, referrer.id)).balance == Decimal("50000")
    assert not await refs.register(session, code=code, referee_id=30003, user_is_new=True)
    assert await refs.register(session, code=code, referee_id=30004, user_is_new=True)
    await session.commit()
    assert len((await session.execute(select(ReferralBonusLog))).scalars().all()) == 2
    assert (await session.get(Seller, referrer.id)).balance == Decimal("100000")
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(Referral(referrer_id=10101, referee_id=30003,
                                 code=code, trigger="signup", status="pending"))
            await session.flush()


async def test_first_approved_payment_only_and_deferred_days(session):
    referrer, referee, tariff, method = await sellers(session)
    await enable(session, trigger=ReferralTrigger.FIRST_PAYMENT, kind="days", value="7")
    row = await refs.register(session, code=referrer.referral_code, referee_id=referee.user_id,
                              user_is_new=True)
    assert row and row.status == "pending"
    assert referee.referred_by == referrer.user_id
    payment = await payment_service.submit_receipt(session, seller=referee, tariff=tariff, method=method,
                                                   file_id="file", file_unique_id="unique")
    assert (await payment_service.decide(session, payment.id, admin_id=111111, approve=True)).status == "approved"
    assert row.first_payment_id == payment.id and row.status == "pending"  # referrer obunasiz
    assert not await refs.first_payment(session, payment, referee)
    sub = await subscription_service.grant(session, referrer, tariff)
    original = ensure_aware(sub.expires_at)
    assert await refs.process_pending(session) == 1
    assert ensure_aware(sub.expires_at) == original + timedelta(days=7)
    assert row.status == "applied"
    assert await refs.process_pending(session) == 0
    assert (await session.execute(select(ReferralBonusLog))).scalar_one().bonus_type == "days"


async def test_discount_and_balance_reserve_refund_reuse_once(session):
    referrer, _, tariff, method = await sellers(session, tariff_price="100000")
    await enable(session, kind="discount", value="25")
    assert await refs.register(session, code=referrer.referral_code, referee_id=30003, user_is_new=True)
    referrer.balance = Decimal("20000")
    await session.commit()
    voucher = (await session.execute(select(ReferralBonusLog))).scalar_one()
    quote = await refs.quote_for(session, referrer, tariff)
    assert quote.discount_bonus_id == voucher.id
    assert (quote.base, quote.discount, quote.balance, quote.bank) == (
        Decimal("100000"), Decimal("25000"), Decimal("20000"), Decimal("55000"),
    )
    payment = await payment_service.submit_receipt(
        session, seller=referrer, tariff=tariff, method=method,
        file_id="chek1", file_unique_id="u1", quoted_amount=quote.bank, quote=quote,
    )
    first_id = payment.id
    assert payment.discount_bonus_id == voucher.id and voucher.reserved_payment_id == payment.id
    assert referrer.balance == 0
    with pytest.raises(ValueError):
        await payment_service.submit_receipt(session, seller=referrer, tariff=tariff, method=method,
                                             file_id="chek2", file_unique_id="u2",
                                             quoted_amount=quote.bank, quote=quote)
    assert (await payment_service.decide(session, first_id, admin_id=111111,
                                         approve=False, reason="Rasm noto'g'ri")).status == "rejected"
    assert referrer.balance == Decimal("20000")
    assert voucher.reserved_payment_id is None
    again = await refs.quote_for(session, referrer, tariff)
    assert again == quote
    newer = await payment_service.submit_receipt(session, seller=referrer, tariff=tariff,
                                                 method=method, file_id="chek3", file_unique_id="u3",
                                                 quoted_amount=again.bank, quote=again)
    assert (await payment_service.decide(session, newer.id, admin_id=111111, approve=True)).status == "approved"
    assert voucher.redeemed_at is not None and voucher.reserved_payment_id == newer.id
    assert await refs.quote_for(session, referrer, tariff) == refs.Quote(
        Decimal("100000"), Decimal("0"), Decimal("0"), Decimal("100000"), None,
    )
    assert payment.balance_used == Decimal("20000") and newer.base_amount == Decimal("100000")


async def test_balance_only_zero_bank_still_requires_admin_and_reject_refunds(session):
    referrer, _, tariff, _ = await sellers(session, tariff_price="50000")
    await enable(session, kind="balance", value="50000")
    assert await refs.register(session, code=referrer.referral_code, referee_id=30003, user_is_new=True)
    quote = await refs.quote_for(session, referrer, tariff)
    assert quote.bank == 0 and quote.balance == Decimal("50000")
    payment = await payment_service.submit_receipt(session, seller=referrer, tariff=tariff,
                                                   method=None, file_id=None, file_unique_id=None,
                                                   quoted_amount=Decimal("0"), quote=quote)
    pid = payment.id
    assert payment.status == "pending" and referrer.balance == 0
    await payment_service.decide(session, pid, admin_id=111111, approve=False, reason="Mijoz fikridan qaytdi")
    assert referrer.balance == Decimal("50000")
    again = await refs.quote_for(session, referrer, tariff)
    payment2 = await payment_service.submit_receipt(session, seller=referrer, tariff=tariff,
                                                    method=None, file_id=None, file_unique_id=None,
                                                    quoted_amount=again.bank, quote=again)
    assert payment2.amount == 0
    await payment_service.decide(session, payment2.id, admin_id=111111, approve=True)
    assert referrer.balance == 0
    assert (await session.execute(select(Payment).where(Payment.status == "approved"))).scalar_one().id == payment2.id


async def test_invalid_settings_and_referral_global_pause(session):
    referrer, _, _, _ = await sellers(session)
    await enable(session)
    for key, val in (("daily_limit", "0"), ("bonus_value", "nan"), ("bonus_type", "bad"),
                     ("min_payment", "1e309"), ("trigger", "arbitrary")):
        with pytest.raises(ValueError):
            await refs.set_config(session, key, val, 111111)
    await settings_service.set(session, "kill_switch", True, updated_by=111111)
    assert not await refs.register(session, code=referrer.referral_code, referee_id=90909, user_is_new=True)
    await settings_service.set(session, "kill_switch", False, updated_by=111111)
    assert (await refs.register(session, code=referrer.referral_code, referee_id=90909, user_is_new=True)) is not None


async def test_private_start_link_is_first_only_even_if_user_previously_seen_in_group(session):
    referrer, _, _, _ = await sellers(session)
    await enable(session, trigger=ReferralTrigger.SIGNUP, kind="balance", value="10000")
    # Guruh xabarida middleware User yaratgan, lekin shaxsiy /start hali yo'q.
    session.add(User(user_id=30303, first_name="Guruh a'zosi"))
    await session.commit()
    await reset_dispatcher_state()
    fake = FakeSession()
    bot, dp = make_bot(fake), make_dispatcher()
    code = referrer.referral_code
    assert code
    await dp.feed_update(bot, text_update(f"/start ref_{code}", user_id=30303, update_id=1))
    session.expire_all()
    rows = (await session.execute(select(Referral).where(Referral.referee_id == 30303))).scalars().all()
    assert len(rows) == 1 and rows[0].status == "applied"
    assert (await session.get(User, 30303)).private_started_at is not None
    assert any("Referal kodingiz qayd" in text for text in fake.sent_texts())
    await dp.feed_update(bot, text_update(f"/start ref_{code}", user_id=30303, update_id=2))
    session.expire_all()
    assert len((await session.execute(select(Referral).where(Referral.referee_id == 30303))).scalars().all()) == 1
    # Birinchi /start dan keyin boshqa kod bilan ham retroaktiv referal bo'lmaydi.
    await dp.feed_update(bot, text_update("/start", user_id=30304, update_id=3))
    await dp.feed_update(bot, text_update(f"/start ref_{code}", user_id=30304, update_id=4))
    session.expire_all()
    assert not (await session.execute(select(Referral).where(Referral.referee_id == 30304))).scalars().all()
    await bot.session.close()
    await reset_dispatcher_state()


async def test_referral_cannot_bypass_admin_confirmation_via_global_settings(session):
    session.add_all([Admin(user_id=80088, role=AdminRole.MODERATOR),
                     Admin(user_id=111111, role=AdminRole.SUPER)])
    await session.commit()
    for role in (AdminRole.MODERATOR, AdminRole.ADMIN):
        buttons = [btn.callback_data for row in settings_kb({}, role).inline_keyboard for btn in row]
        assert AdminCB(action="toggle", value="referral_enabled").pack() not in buttons
    await reset_dispatcher_state()
    fake = FakeSession()
    bot, dp = make_bot(fake), make_dispatcher()
    # Eski xabardagi tugma yoki qo'lda yasalgan callback ham rad qilinadi.
    for n, user_id in enumerate((80088, 111111), start=1):
        await dp.feed_update(bot, callback_update(
            AdminCB(action="toggle", value="referral_enabled").pack(),
            user_id=user_id, update_id=n))
        assert not await settings_service.get("referral_enabled", False, session)
    assert sum("o'zgartirib bo'lmaydi" in text for text in fake.answers()) == 2
    # Referal panelining admin-only tasdiqlash oqimi esa ishlaydi.
    await dp.feed_update(bot, callback_update(ReferralAdminCB(action="toggle_ask").pack(), update_id=3))
    assert not await settings_service.get("referral_enabled", False, session)
    assert "TASDIQ" not in fake.answers()  # xabar hali hech kimga bonus bermaydi
    await dp.feed_update(bot, callback_update(ReferralAdminCB(action="toggle", value="on").pack(), update_id=4))
    assert await settings_service.get("referral_enabled", False, session)
    await bot.session.close()
    await reset_dispatcher_state()


async def test_user_seen_before_migration_cannot_claim_retroactive_referral(session):
    referrer, _, _, _ = await sellers(session)
    await enable(session)
    # Migratsiya barcha mavjud userlarni legacy deb belgilaydi, chunki ularning
    # avval shaxsiy /start bosgan-bosmagani tarixiy jadvalda saqlanmagan.
    session.add(User(user_id=40404, first_name="Eski akkaunt", referral_legacy=True))
    await session.commit()
    await reset_dispatcher_state()
    fake = FakeSession()
    bot, dp = make_bot(fake), make_dispatcher()
    await dp.feed_update(bot, text_update(f"/start ref_{referrer.referral_code}",
                                          user_id=40404, update_id=1))
    session.expire_all()
    assert (await session.get(User, 40404)).private_started_at is not None
    assert not (await session.execute(select(Referral).where(Referral.referee_id == 40404))).scalars().all()
    assert not any("Referal kodingiz qayd" in text for text in fake.sent_texts())
    await bot.session.close()
    await reset_dispatcher_state()
