"""Tarif snapshoti, shaxsiy navbat va foydalanuvchilar katalogi regressiyasi."""

from __future__ import annotations

from datetime import timedelta

from aiogram.types import Chat
from sqlalchemy import select

from app.constants import AdminRole, AdStatus, SubscriptionStatus
from app.db.models import (
    Ad,
    Admin,
    FreeAd,
    FreeEntitlement,
    SubscriptionGrant,
    User,
)
from app.keyboards.callbacks import AdCB, FreeCB, FreeModCB, PolicyCB, SellerPanelCB
from app.services import (
    ad_service,
    category_service,
    free_ad_service,
    group_service,
    payment_service,
    posting_service,
    seller_service,
    subscription_service,
    tariff_service,
    user_directory,
)
from app.services.settings_service import settings_service
from app.utils.time import ensure_aware, utcnow
from tests.fake_telegram import (
    ADMIN_ID,
    FakeSession,
    callback_update,
    make_bot,
    make_dispatcher,
    reset_dispatcher_state,
    text_update,
)
from tests.test_free_group_ads import credit, free_draft, setup_free
from tests.test_phase7_counter import INVITER, OTHER, subscribed


async def _group(session, chat_id: int):
    group = await group_service.get_or_create_group(
        session, Chat(id=chat_id, type="supergroup", title=f"Bozor {chat_id}"),
    )
    group.bot_is_admin = True
    group.settings.posting_enabled = True
    category = await category_service.create_category(
        session, name=f"Bo'lim {chat_id}", group_id=group.id,
    )
    return group, category


async def _ad(session, seller, category, *, title: str = "Tasdiqlangan e'lon"):
    ad = await ad_service.create_draft(session, seller, category)
    await ad_service.set_title(session, ad, title)
    await ad_service.add_photo(session, ad, file_id=f"photo-{seller.id}")
    assert (await ad_service.submit(session, seller, ad)) == (True, AdStatus.PENDING)
    assert await ad_service.approve(session, ad, ADMIN_ID)
    return ad  # admin tasdig'idan keyin sotuvchi o'zi Start qiladi


async def test_receipt_snapshot_survives_admin_tariff_edits_and_grant_history(session) -> None:
    group, category = await _group(session, -1001005001)
    seller, _ = await seller_service.get_or_create_seller(session, 80001, display_name="Telefonchi")
    tariff = await tariff_service.create_tariff(
        session, name="5 daqiqa", price="100000", duration_days=7,
        max_ads=2, max_photos=1, interval_sec=300,
    )
    method = await payment_service.create_method(session, name="Karta", card_number="8600123456789012")
    receipt = await payment_service.submit_receipt(
        session, seller=seller, tariff=tariff, method=method,
        file_id="receipt-1", file_unique_id="unique-1",
    )
    assert receipt.status == "pending" and receipt.terms["interval_sec"] == 300
    assert receipt.terms["max_photos"] == 1 and receipt.terms["max_ads"] == 2
    assert receipt.terms["price"] == "100000.00" and not receipt.terms["is_trial"]
    assert await subscription_service.active_for(session, seller.id) is None
    assert not (await session.execute(select(SubscriptionGrant))).scalars().all()

    # Chek ko'rilguncha katalogdagi narx, surat, muddat va oralig'ini o'zgartiramiz.
    await tariff_service.update_tariff(
        session, tariff, name="10 daqiqa", price="200000", duration_days=30,
        max_ads=3, max_photos=2, interval_sec=600,
    )
    tariff.allowed_group_ids = []
    await session.flush()
    decided = await payment_service.decide(session, receipt.id, admin_id=ADMIN_ID, approve=True)
    assert decided.status == "approved"
    old = await subscription_service.active_for(session, seller.id)
    assert old and old.ads_limit == 2 and old.terms == receipt.terms
    assert subscription_service.interval_for(old) == 300
    assert 6 <= subscription_service.days_left(old) <= 7
    assert await ad_service.photo_limit(session, seller) == 1
    first_grant = (await session.execute(select(SubscriptionGrant))).scalar_one()
    assert first_grant.payment_id == receipt.id and first_grant.user_id == seller.user_id
    assert first_grant.terms == receipt.terms

    # Tasdiqlangan eski xaridor yangi katalogdagi cheklovdan ta'sirlanmaydi.
    ad = await _ad(session, seller, category)
    assert ad.status == AdStatus.PAUSED and ad.next_eligible_at is None
    start_at = utcnow()
    assert await ad_service.resume(session, ad)
    assert 300 <= (ensure_aware(ad.next_eligible_at) - start_at).total_seconds() <= 302
    assert group.settings.interval_sec == 1800
    assert await posting_service.eligible_ad(
        session, category, ensure_aware(ad.next_eligible_at) + timedelta(seconds=1),
    ) == (ad.id, False)
    claim, result = await posting_service.claim_post(
        session, group.id, ensure_aware(ad.next_eligible_at) + timedelta(seconds=1),
    )
    assert claim and result.status == "claimed" and claim.ad_id == ad.id
    await posting_service.finish_post(session, claim, [100], ensure_aware(ad.next_eligible_at))

    # Keyingi chek esa yangi shartlarga ega; avvalgi grant va obuna tarixi qoladi.
    second = await payment_service.submit_receipt(
        session, seller=seller, tariff=tariff, method=method,
        file_id="receipt-2", file_unique_id="unique-2",
    )
    assert second.terms["interval_sec"] == 600 and second.terms["allowed_group_ids"] == []
    assert (await payment_service.decide(session, second.id, admin_id=ADMIN_ID, approve=True)).status == "approved"
    new = await subscription_service.active_for(session, seller.id)
    assert new.id != old.id and new.terms == second.terms
    assert subscription_service.interval_for(new) == 600
    assert old.status == SubscriptionStatus.CANCELLED and old.terms == first_grant.terms
    grants = list((await session.execute(select(SubscriptionGrant).order_by(SubscriptionGrant.id))).scalars())
    assert [g.payment_id for g in grants] == [receipt.id, second.id]
    assert [g.terms["interval_sec"] for g in grants] == [300, 600]


async def test_two_paid_personal_timers_share_only_technical_group_lease(session) -> None:
    group, category = await _group(session, -1001005002)
    sellers = []
    for uid, gap in ((80002, 300), (80003, 600)):
        seller, _ = await seller_service.get_or_create_seller(session, uid, display_name=f"Do'kon {uid}")
        plan = await tariff_service.create_tariff(
            session, name=f"Oraliq {gap}", price="50000", interval_sec=gap,
        )
        await subscription_service.grant(session, seller, plan)
        sellers.append(await _ad(session, seller, category, title=f"E'lon {uid}"))
    fast, slow = sellers
    assert fast.next_eligible_at is None and slow.next_eligible_at is None
    # Admin tasdig'i 5/10 daqiqadan keyin ham Start'siz post qilolmaydi.
    assert await posting_service.eligible_ad(
        session, category, utcnow() + timedelta(minutes=11),
    ) == (None, False)
    start_at = utcnow()
    assert await ad_service.resume(session, fast)
    assert await ad_service.resume(session, slow)
    first_due, second_due = ensure_aware(fast.next_eligible_at), ensure_aware(slow.next_eligible_at)
    assert 300 <= (first_due - start_at).total_seconds() < 302
    assert 600 <= (second_due - start_at).total_seconds() < 602
    now = first_due + timedelta(seconds=1)
    assert (await posting_service.due_group_ids(session, now)) == [group.id]
    claim, result = await posting_service.claim_post(session, group.id, now)
    assert claim and result.status == "claimed" and claim.ad_id == fast.id
    # Bir guruhdagi ikkinchi post sending log tugamaguncha o'tmaydi.
    blocked, busy = await posting_service.claim_post(session, group.id, now, force_ad_id=slow.id)
    assert blocked is None and busy.status == "busy"
    assert (await posting_service.finish_post(session, claim, [201], now)).status == "sent"
    assert ensure_aware(slow.next_eligible_at) == second_due
    assert ensure_aware(fast.next_eligible_at) == now + timedelta(seconds=300)
    assert await ad_service.pause(session, slow)
    assert await ad_service.resume(session, slow)
    assert ensure_aware(slow.next_eligible_at) > second_due
    assert (ensure_aware(slow.next_eligible_at) - utcnow()).total_seconds() > 590


async def test_admin_directory_list_search_page_and_user_group_card(session) -> None:
    session.add(Admin(user_id=ADMIN_ID, role=AdminRole.SUPER))
    for i in range(13):
        session.add(User(user_id=81000 + i, first_name=f"Ali {i:02d}", username=f"ali{i:02d}"))
    buyer_id = 81999
    session.add(User(user_id=buyer_id, first_name="Ishbilarmon", username="dukonchi"))
    group_a, category = await _group(session, -1001005003)
    group_b, _ = await _group(session, -1001005004)
    seller, _ = await seller_service.get_or_create_seller(session, buyer_id, display_name="Biznes <Bozor>")
    orphan, _ = await seller_service.get_or_create_seller(session, 81030, display_name="Yolg'iz sotuvchi")
    plan = await tariff_service.create_tariff(session, name="Xarid", price=150000, interval_sec=300)
    await subscription_service.grant(session, seller, plan)
    paid = await _ad(session, seller, category)
    free = FreeAd(user_id=buyer_id, group_id=group_b.id, approved_photo_id="bepul-photo",
                  approved_caption="Bepul e'lon matni", review_status="approved", revision=1,
                  desired_running=False)
    session.add(free)
    await session.flush()
    session.add(FreeEntitlement(user_id=buyer_id, group_id=group_b.id, period=1,
                                valid_from=utcnow(), expires_at=utcnow() + timedelta(days=30)))
    paid_id, free_id = paid.id, free.id
    await session.commit()

    entries, total = await user_directory.list_users(session, search="sotuvchi")
    assert total == 1 and entries[0].user_id == orphan.user_id
    entries, total = await user_directory.list_users(session, search="@dukonchi")
    assert total == 1 and entries[0].user_id == buyer_id
    assert len((await user_directory.list_users(session, search="Ali"))[0]) == 10
    assert len((await user_directory.list_users(session, page=1, search="Ali"))[0]) == 3

    await reset_dispatcher_state()
    fake = FakeSession()
    bot, dp = make_bot(fake), make_dispatcher()
    try:
        async def callback(data, n):
            await dp.feed_update(bot, callback_update(data, update_id=n))
            session.expire_all()

        await callback(PolicyCB(action="users", value="0").pack(), 1)
        assert "sahifa 1/2" in fake.edited_texts()[-1]
        markup = str(fake.called("EditMessageText")[-1]["reply_markup"])
        assert "Ali" in markup and "Foydalanuvchilar ro'yxati" not in markup
        await callback(PolicyCB(action="user_find").pack(), 2)
        await dp.feed_update(bot, text_update("Ali", update_id=3))
        session.expire_all()
        assert "qidiruv: Ali" in fake.sent_texts()[-1]
        await callback(PolicyCB(action="users", value="q1").pack(), 4)
        assert "qidiruv: Ali" in fake.edited_texts()[-1] and "sahifa 2/2" in fake.edited_texts()[-1]
        await callback(PolicyCB(action="user_find").pack(), 5)
        await dp.feed_update(bot, text_update("@dukonchi", update_id=6))
        session.expire_all()
        assert "Ishbilarmon" in str(fake.called("SendMessage")[-1]["reply_markup"])
        # Eski 2-sahifa tugmasi filtrda faqat bitta natija qolsa, boshiga qaytsin.
        await callback(PolicyCB(action="users", value="q200").pack(), 7)
        assert "sahifa 1/1" in fake.edited_texts()[-1]
        assert "Ishbilarmon" in str(fake.called("EditMessageText")[-1]["reply_markup"])
        await callback(PolicyCB(action="user_profile", value=str(buyer_id)).pack(), 8)
        card = fake.edited_texts()[-1]
        assert "Xarid" in card and "oralig'i 5 min" in card
        assert "Pullik e'lonlar: 1 ta" in card and "bepul: 1 ta" in card
        assert "guruhlar: 2 ta" in card and f"#{paid_id}" in card and f"#{free_id}" in card
        markup = str(fake.called("EditMessageText")[-1]["reply_markup"])
        assert FreeModCB(action="card", ad_id=free_id).pack() in markup
    finally:
        await bot.session.close()
        await reset_dispatcher_state()


async def test_free_admin_pause_does_not_override_user_stop_or_expired_n(session) -> None:
    first = await setup_free(session, n=1, chat_id=-1002003004000)
    second = await setup_free(session, n=1, chat_id=OTHER)
    await credit(session, first, INVITER, 1, start=11101)
    await credit(session, second, INVITER, 1, start=11102)
    ad_a = await free_draft(session, first, INVITER)
    ad_b = await free_draft(session, second, INVITER)
    assert await free_ad_service.maybe_activate(session, ad_a, utcnow(), member_ok=True)
    assert await free_ad_service.maybe_activate(session, ad_b, utcnow(), member_ok=True)
    old_access = await free_ad_service.entitlement(session, INVITER, first)
    other_due = ad_b.next_post_at
    await free_ad_service.set_running(session, ad_a, False)
    await free_ad_service.set_admin_pause(session, ad_a.id, ad_a.revision, ADMIN_ID, True)
    await free_ad_service.set_admin_pause(session, ad_a.id, ad_a.revision, ADMIN_ID, False)
    assert not ad_a.desired_running and ad_a.next_post_at is None
    assert ad_a.review_status == "approved" and ad_a.approved_photo_id == "test-photo"
    assert ad_b.next_post_at == other_due and not ad_b.admin_paused
    assert (await free_ad_service.entitlement(session, INVITER, first)).expires_at == old_access.expires_at

    await free_ad_service.set_running(session, ad_a, True)
    assert not await free_ad_service.maybe_activate(session, ad_a, utcnow(), member_ok=False)
    assert ad_a.next_post_at is None
    assert not await free_ad_service.maybe_activate(session, ad_a, utcnow(), member_ok=True)
    assert ad_a.next_post_at is not None  # eski huquq bor, yangi N talab qilinmaydi
    old_access.expires_at = utcnow() - timedelta(seconds=1)
    await free_ad_service.set_admin_pause(session, ad_a.id, ad_a.revision, ADMIN_ID, True)
    await free_ad_service.set_admin_pause(session, ad_a.id, ad_a.revision, ADMIN_ID, False)
    assert not await free_ad_service.maybe_activate(session, ad_a, utcnow(), member_ok=True)
    assert ad_a.next_post_at is None and ad_a.review_status == "approved"


async def test_regular_user_paid_checkout_and_real_start_status(session) -> None:
    group, category = await _group(session, -1001005005)
    group.settings.free_ads_enabled = True
    session.add(User(user_id=81222, first_name="Mijoz", username="mijoz"))
    plan = await tariff_service.create_tariff(
        session, name="Besh daqiqa", price=120000, interval_sec=300,
    )
    await payment_service.create_method(session, name="Karta", card_number="8600123456789012")
    gid, cid, tariff_id = group.id, category.id, plan.id
    await session.commit()
    await reset_dispatcher_state()
    fake = FakeSession()
    subscribed(fake)
    bot, dp = make_bot(fake), make_dispatcher()
    try:
        async def feed(update):
            await dp.feed_update(bot, update)
            session.expire_all()

        await feed(text_update("/start", user_id=81222, update_id=1))
        home = fake.sent_texts()[-1]
        assert "0</b> e'lon" in home and "shart emas" in home
        await feed(callback_update(FreeCB(action="paid", group_id=gid).pack(),
                                   user_id=81222, update_id=2))
        assert "Besh daqiqa" in fake.edited_texts()[-1] and "5 daqiqa" in fake.edited_texts()[-1]
        assert (await seller_service.get_seller(session, 81222)) is not None
        await feed(callback_update(SellerPanelCB(action="pay", value=str(tariff_id)).pack(),
                                   user_id=81222, update_id=3))
        assert "To'lov rekviziti" in fake.edited_texts()[-1]
        # /start kampaniya Start tugmasi emas: muddatli obuna va ad due o'zgarmaydi.
        seller = await seller_service.get_seller(session, 81222)
        await subscription_service.grant(session, seller, await tariff_service.get_tariff(session, tariff_id))
        ad = await _ad(session, seller, await category_service.get_category(session, cid))
        aid = ad.id
        assert ad.status == AdStatus.PAUSED and ad.next_eligible_at is None
        await session.commit()
        await feed(text_update("/start", user_id=81222, update_id=4))
        assert "5 daqiqa" in fake.sent_texts()[-1] and "0</b> pullik" in fake.sent_texts()[-1]
        assert "E'lon guruhlari: <b>1</b>" in fake.sent_texts()[-1]
        assert (await session.get(Ad, aid)).next_eligible_at is None
        start_at = utcnow()
        await feed(callback_update(AdCB(action="resume", ad_id=aid).pack(),
                                   user_id=81222, update_id=5))
        due = (await session.get(Ad, aid)).next_eligible_at
        assert 300 <= (ensure_aware(due) - start_at).total_seconds() < 303
        await feed(text_update("/start", user_id=81222, update_id=6))
        assert "1</b> pullik" in fake.sent_texts()[-1]
        assert ensure_aware((await session.get(Ad, aid)).next_eligible_at) == ensure_aware(due)
        await settings_service.set(session, "posting_enabled_global", False)
        await session.commit()
        await feed(text_update("/start", user_id=81222, update_id=7))
        assert "0</b> pullik" in fake.sent_texts()[-1]
    finally:
        await bot.session.close()
        await reset_dispatcher_state()
