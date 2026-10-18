"""Admin tanlaydigan 10x chegaralar va rollarga xos in-bot yo'riqnoma."""

from __future__ import annotations

from decimal import Decimal

import pytest
from aiogram.types import Chat
from sqlalchemy import select

from app.constants import (
    BROADCAST_RATE_PER_SEC,
    MAX_PHOTOS_PER_ALBUM,
    AdminRole,
    PaymentStatus,
    PermissionKind,
    SellerStatus,
)
from app.db.models import ActionLog, Admin, GroupSettings, Permission, Seller
from app.keyboards.admin import admin_main_kb
from app.keyboards.callbacks import AdminCB, GroupCB, GuideCB, SellerPanelCB, TariffCB
from app.keyboards.guide import GUIDES, guide_kb, user_start_kb
from app.keyboards.seller_panel import seller_menu_kb
from app.services import (
    counter_service as counters,
)
from app.services import (
    group_policy_service as policies,
)
from app.services import (
    group_service,
    payment_service,
    referral_service,
    seller_service,
    subscription_service,
    tariff_service,
)
from tests.fake_telegram import (
    ADMIN_ID,
    FakeSession,
    callback_update,
    make_bot,
    make_dispatcher,
    reset_dispatcher_state,
    text_update,
)


def test_group_boundaries_and_hard_limits_unchanged() -> None:
    assert tariff_service.validate_interval(600) == 600
    with pytest.raises(ValueError):
        tariff_service.validate_interval(86401)
    # Botda Telegram albom/broadcast texnik himoyasi saqlanadi.
    assert MAX_PHOTOS_PER_ALBUM == tariff_service.MAX_PHOTOS == 10
    assert BROADCAST_RATE_PER_SEC == 25


async def test_policy_bounds_are_ten_times_larger_and_group_local(session) -> None:
    one = await group_service.get_or_create_group(session, Chat(id=-10012220001, type="supergroup", title="Birinchi"))
    two = await group_service.get_or_create_group(session, Chat(id=-10012220002, type="supergroup", title="Ikkinchi"))
    actor = ADMIN_ID
    for key, maximum in (("warn_limit", 200), ("mute_minutes", 100800), ("warn_window_hours", 7200)):
        await policies.edit_guard(session, one, key, str(maximum), actor)
        with pytest.raises(ValueError):
            await policies.edit_guard(session, one, key, str(maximum + 1), actor)
    words = ",".join(f"word{i}" for i in range(300))
    domains = ",".join(f"d{i}.uz" for i in range(300))
    await policies.edit_guard(session, one, "banned_words", words, actor)
    await policies.edit_guard(session, one, "allowed_domains", domains, actor)
    assert len((await policies.ensure_guard(session, one.id)).banned_words) == 300
    assert len((await policies.ensure_guard(session, one.id)).allowed_domains) == 300
    with pytest.raises(ValueError):
        policies.parse_words(words + ",extra")
    with pytest.raises(ValueError):
        policies.parse_domains(domains + ",extra.uz")
    for key, maximum in (("keep_last_ads", 200), ("delete_after_seconds", 36000)):
        await policies.edit_cleaner(session, one, key, str(maximum), actor)
        with pytest.raises(ValueError):
            await policies.edit_cleaner(session, one, key, str(maximum + 1), actor)

    for key, (minimum, maximum) in counters.NUMBERS.items():
        await counters.edit_counter(session, one, key, str(maximum), actor)
        with pytest.raises(ValueError):
            await counters.edit_counter(session, one, key, str(maximum + 1), actor)
        assert minimum in {0, 1}
    assert counters.NUMBERS == {"required_n": (0, 1000), "min_stay_minutes": (0, 100800)}
    with pytest.raises(ValueError):
        await counters.edit_counter(session, one, "link_member_limit", 20, actor)
    with pytest.raises(ValueError):
        await counters.edit_counter(session, one, "source", "link", actor)
    assert (await counters.ensure_counter(session, two.id)).required_n == 3
    assert (await policies.ensure_guard(session, two.id)).warn_limit == 3
    assert (await policies.ensure_cleaner(session, two.id)).keep_last_ads == 1
    assert not two.settings.counter_enabled and not one.settings.counter_enabled
    assert (await session.execute(select(ActionLog).where(ActionLog.group_id == one.id))).scalars().all()
    assert not (await session.execute(select(ActionLog).where(ActionLog.group_id == two.id))).scalars().all()

    grant = await policies.grant_permission(
        session, group_id=one.id, user_id=908081, kind=PermissionKind.GUARD_EXEMPT,
        days=3650, reason="Sinov muddati", actor_id=actor,
    )
    assert isinstance(grant, Permission) and grant.group_id == one.id
    with pytest.raises(ValueError):
        await policies.grant_permission(
            session, group_id=one.id, user_id=908082, kind=PermissionKind.GUARD_EXEMPT,
            days=3651, reason="Sinov muddati", actor_id=actor,
        )


async def test_counter_manual_adjust_keeps_audit_and_new_limit(session) -> None:
    group = await group_service.get_or_create_group(session, Chat(id=-10012220003, type="supergroup", title="Sanoq"))
    assert counters.MAX_MANUAL_ADJUST == 10000
    count = await counters.adjust(session, group_id=group.id, user_id=765456, delta=10000,
                                  actor_id=ADMIN_ID, reason="Sinov hisobini tuzatish")
    assert count == 10000
    with pytest.raises(ValueError):
        await counters.adjust(session, group_id=group.id, user_id=765456, delta=10001,
                              actor_id=ADMIN_ID, reason="Ruxsat etilmagan")
    assert (await session.execute(select(ActionLog).where(ActionLog.action == "counter_adjust"))).scalars().one()


async def test_tariff_price_checkout_and_subscription_new_limits(session) -> None:
    assert tariff_service.MAX_DURATION_DAYS == 36500
    assert tariff_service.MAX_ADS == 10000
    assert subscription_service.MAX_ADS_LIMIT == 1000000
    assert tariff_service.MAX_PRICE == Decimal("9999999990")
    assert tariff_service.parse_price("9999999991") is None

    seller, _ = await seller_service.get_or_create_seller(session, 712345, display_name="Sinov")
    tariff = await tariff_service.create_tariff(
        session, name="Chegara", price=str(tariff_service.MAX_PRICE),
        duration_days=36500, max_ads=10000,
    )
    assert tariff and tariff.duration_days == 36500 and tariff.max_ads == 10000
    method = await payment_service.create_method(session, name="Sinov bank", card_number="8600123456789012")
    quote = await referral_service.quote_for(session, seller, tariff)
    payment = await payment_service.submit_receipt(
        session, seller=seller, tariff=tariff, method=method, file_id="receipt-max",
        file_unique_id="unique-max", quote=quote, quoted_amount=quote.bank, quoted_currency="UZS",
    )
    assert payment.amount == tariff.price and payment.status == PaymentStatus.PENDING
    with pytest.raises(ValueError):
        await payment_service.submit_receipt(
            session, seller=seller, tariff=tariff, method=method, file_id="receipt-too-much",
            file_unique_id="unique-too-much", quoted_amount=tariff_service.MAX_PRICE + 1,
        )
    # Qo'lda limitni ko'tarish sotuvchining o'tgan foydalanish sonini o'zgartirmaydi.
    subscription = await subscription_service.grant(session, seller, tariff)
    subscription.ads_used = 2
    assert await subscription_service.set_ads_limit(session, subscription, 1000000)
    assert subscription.ads_limit == 1000000 and subscription.ads_used == 2


def test_referral_new_bounds_but_discount_stays_safe() -> None:
    refs = referral_service
    with pytest.raises(ValueError, match="sozlamasi yo.q"):
        refs.validate("daily_limit", "500")
    for bonus, allowed, rejected in (("days", "3650", "3651"),
                                     ("balance", "10000000", "10000001"),
                                     ("discount", "50", "51")):
        assert refs.validate("bonus_value", allowed, bonus_type=bonus) == allowed
        with pytest.raises(ValueError):
            refs.validate("bonus_value", rejected, bonus_type=bonus)
    assert refs.validate("min_payment", str(tariff_service.MAX_PRICE)) == str(tariff_service.MAX_PRICE)
    with pytest.raises(ValueError, match="Minimal chek"):
        refs.validate("min_payment", str(tariff_service.MAX_PRICE + 1))


async def test_tariff_interval_is_editable_but_old_group_control_is_not(session) -> None:
    session.add(Admin(user_id=ADMIN_ID, role=AdminRole.SUPER))
    group = await group_service.get_or_create_group(
        session, Chat(id=-10012220004, type="supergroup", title="Sinov intervali")
    )
    tariff = await tariff_service.create_tariff(session, name="Oraliq", price=123000)
    group_id, tariff_id = group.id, tariff.id
    await session.commit()
    await reset_dispatcher_state()
    fake = FakeSession()
    bot = make_bot(fake)
    dp = make_dispatcher()

    async def feed(update):
        await dp.feed_update(bot, update)
        session.expire_all()

    try:
        await feed(callback_update(GroupCB(action="interval", group_id=group_id).pack(), update_id=30))
        await feed(text_update("600", update_id=31))
        assert (await session.get(GroupSettings, group_id)).interval_sec == 1800

        await feed(callback_update(TariffCB(action="interval", tariff_id=tariff_id).pack(), update_id=32))
        await feed(text_update("1441", update_id=33))
        assert any("1–1440" in text for text in fake.sent_texts())
        await feed(text_update("10", update_id=34))
        assert (await tariff_service.get_tariff(session, tariff_id)).interval_sec == 600
    finally:
        await bot.session.close()
        await reset_dispatcher_state()


def test_guide_buttons_and_safe_page_sizes() -> None:
    def buttons(markup):
        return [b for row in markup.inline_keyboard for b in row]

    for markup in (user_start_kb("@admin"), admin_main_kb("super"), admin_main_kb("moderator"),
                   seller_menu_kb(has_subscription=False), seller_menu_kb(has_subscription=True)):
        assert GuideCB().pack() in {button.callback_data for button in buttons(markup)}
    for profile, pages in GUIDES.items():
        for key, (_, text) in pages.items():
            assert len(text) < 4096
            kb = guide_kb(profile, key)
            assert len(buttons(kb)) > 0
        back = buttons(guide_kb(profile, "home"))[-1].callback_data
        assert back == (AdminCB(action="menu").pack() if profile in {"admin", "moderator"}
                        else SellerPanelCB(action="menu").pack() if profile == "seller"
                        else GuideCB(page="back").pack())


async def test_guide_dispatch_reads_real_role_not_callback_page(session) -> None:
    user_id, seller_uid, moderator_uid = 900080, 900081, 900082
    session.add_all([Admin(user_id=ADMIN_ID, role=AdminRole.SUPER),
                     Admin(user_id=moderator_uid, role=AdminRole.MODERATOR)])
    seller, _ = await seller_service.get_or_create_seller(session, seller_uid, display_name="Sotuvchi")
    assert isinstance(seller, Seller)
    await session.commit()
    await reset_dispatcher_state()
    fake = FakeSession()
    bot = make_bot(fake)
    dp = make_dispatcher()
    try:
        await dp.feed_update(bot, text_update("/start", user_id=user_id, update_id=1))
        assert "Assalomu" in fake.sent_texts()[-1]
        assert GuideCB().pack() in str(fake.called("SendMessage")[-1]["reply_markup"])
        await dp.feed_update(bot, callback_update(GuideCB(page="sales").pack(), user_id=user_id, update_id=2))
        assert "foydalanuvchi" in fake.edited_texts()[-1] and "botni boshqarish" not in fake.edited_texts()[-1].lower()
        await dp.feed_update(bot, callback_update(GuideCB(page="counter").pack(), user_id=user_id, update_id=3))
        assert "Guruhga qo'shilgan a'zolar" in fake.edited_texts()[-1]
        await dp.feed_update(bot, callback_update(GuideCB(page="back").pack(), user_id=user_id, update_id=4))
        assert "Assalomu" in fake.edited_texts()[-1]

        await dp.feed_update(bot, text_update("/start", user_id=ADMIN_ID, update_id=5))
        assert GuideCB().pack() in str(fake.called("SendMessage")[-1]["reply_markup"])
        await dp.feed_update(bot, callback_update(GuideCB(page="safety").pack(), update_id=6))
        assert "Posbon" in fake.edited_texts()[-1]
        await dp.feed_update(bot, text_update("/start", user_id=seller_uid, update_id=7))
        assert GuideCB().pack() in str(fake.called("SendMessage")[-1]["reply_markup"])
        await dp.feed_update(bot, callback_update(GuideCB(page="payments").pack(), user_id=seller_uid, update_id=8))
        assert "Chek obunani" in fake.edited_texts()[-1]
        await dp.feed_update(bot, callback_update(GuideCB(page="back").pack(), user_id=seller_uid, update_id=9))
        assert "Botdan foydalanish — sotuvchi" in fake.edited_texts()[-1]
        await dp.feed_update(bot, callback_update(GuideCB(page="sales").pack(), user_id=moderator_uid, update_id=10))
        assert "moderator" in fake.edited_texts()[-1].lower()
        assert "bank kirimini" not in fake.edited_texts()[-1]

        # O'chirilgan sotuvchida eskirgan menyu qolishi mumkin; callback panelni qayta ochmasin.
        seller.status = SellerStatus.DELETED
        await session.commit()
        await dp.feed_update(bot, text_update("/start", user_id=seller_uid, update_id=11))
        assert GuideCB().pack() in str(fake.called("SendMessage")[-1]["reply_markup"])
        await dp.feed_update(bot, callback_update(GuideCB(page="ads").pack(), user_id=seller_uid, update_id=12))
        assert "foydalanuvchi" in fake.edited_texts()[-1]
    finally:
        await bot.session.close()
        await reset_dispatcher_state()
