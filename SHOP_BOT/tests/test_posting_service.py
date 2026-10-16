"""Phase 4: DB navbati, vaqt cheklovlari va worker claim (Telegram'siz)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from app.constants import AdStatus, SellerStatus
from app.db.models import (
    Ad,
    Category,
    CategoryRotation,
    ErrorLog,
    Group,
    GroupRotation,
    GroupSettings,
    PostLog,
    Seller,
    Subscription,
    Tariff,
)
from app.services import ad_service, category_service
from app.services import posting_service as p
from app.utils.time import ensure_aware, utcnow

CHAT_ID = -1002003004000


async def setup(session, *, count: int = 3, interval: int = 1800,
                now: datetime | None = None):
    now = now or utcnow()
    group = Group(
        tg_chat_id=CHAT_ID, title="Telefonlar", is_supergroup=True, bot_is_admin=True,
        is_active=True,
        settings=GroupSettings(posting_enabled=True, interval_sec=interval, jitter_percent=0),
        rotation=GroupRotation(next_post_at=now - timedelta(seconds=5)),
    )
    session.add(group)
    await session.flush()
    cat = Category(name="Telefonlar", group_id=group.id, position=1000,
                   rotation=CategoryRotation(is_paused=False))
    seller = Seller(user_id=987654321, status=SellerStatus.ACTIVE)
    tariff = Tariff(name="Test", max_ads=count, max_photos=3)
    session.add_all([cat, seller, tariff])
    await session.flush()
    subscription = Subscription(
        seller_id=seller.id, tariff_id=tariff.id,
        starts_at=now - timedelta(days=1), expires_at=now + timedelta(days=30),
        ads_limit=count, ads_used=count,
    )
    session.add(subscription)
    ads = [
        Ad(seller_id=seller.id, category_id=cat.id, group_id=group.id,
           title=f"E'lon {i}", status=AdStatus.ACTIVE, position=i * 100)
        for i in range(1, count + 1)
    ]
    session.add_all(ads)
    await session.flush()
    return group, cat, ads, seller, tariff, subscription


async def test_round_robin_skips_paused_and_wraps(session) -> None:
    _, category, ads, _, _, _ = await setup(session)
    category.rotation.cursor_ad_id = ads[0].id
    assert await p.eligible_ad(session, category, utcnow()) == (ads[1].id, False)
    ads[1].status = AdStatus.PAUSED
    await session.flush()  # sessiya autoflush=False; production status servislari flush qiladi
    assert await p.eligible_ad(session, category, utcnow()) == (ads[2].id, False)
    category.rotation.cursor_ad_id = ads[2].id
    assert await p.eligible_ad(session, category, utcnow()) == (ads[0].id, True)
    # Kursor e'lon butunlay o'chirilsa boshidan ketadi.
    category.rotation.cursor_ad_id = 999999
    assert await p.eligible_ad(session, category, utcnow()) == (ads[0].id, False)


async def test_duplicate_positions_can_still_be_swapped(session) -> None:
    _, cat, ads, _, _, _ = await setup(session, count=2)
    ads[1].position = ads[0].position
    await session.flush()
    assert await ad_service.move(session, ads[1], "up") is True
    assert ads[1].position < ads[0].position
    assert await ad_service.move(session, ads[1], "nonsense") is False


async def test_reattached_category_updates_old_ads_denormalized_group(session) -> None:
    group, cat, ads, _, _, _ = await setup(session, count=1)
    new_group = Group(tg_chat_id=CHAT_ID - 1, title="Yangi", is_supergroup=True)
    session.add(new_group)
    await session.flush()
    await category_service.attach_group(session, cat, new_group.id)
    assert ads[0].group_id == new_group.id
    assert await p.eligible_ad(session, cat, utcnow()) == (ads[0].id, False)


async def test_paid_last_slot_still_posts_and_tariff_rules(session) -> None:
    group, cat, ads, seller, tariff, subscription = await setup(session, count=1)
    assert subscription.ads_left == 0  # yangi e'lon sloti tugagan, lekin eski e'lon pullik
    assert await p.eligible_ad(session, cat, utcnow()) == (ads[0].id, False)
    tariff.allowed_group_ids = []
    await session.flush()
    assert await p.eligible_ad(session, cat, utcnow()) == (None, False)
    tariff.allowed_group_ids = [str(group.id)]
    tariff.allowed_category_ids = [cat.id]
    await session.flush()
    assert await p.eligible_ad(session, cat, utcnow()) == (ads[0].id, False)
    tariff.allowed_category_ids = [123456]
    await session.flush()
    assert await p.eligible_ad(session, cat, utcnow()) == (None, False)
    tariff.allowed_category_ids = None
    seller.status = SellerStatus.BLOCKED
    await session.flush()
    assert await p.eligible_ad(session, cat, utcnow()) == (None, False)
    seller.status = SellerStatus.ACTIVE
    ads[0].next_eligible_at = utcnow() + timedelta(minutes=5)
    await session.flush()
    assert await p.eligible_ad(session, cat, utcnow()) == (None, False)


async def test_subscription_must_be_valid_even_before_expiry_job(session) -> None:
    _, cat, ads, _, _, sub = await setup(session, count=1)
    sub.expires_at = utcnow() - timedelta(seconds=1)
    await session.flush()
    assert await p.eligible_ad(session, cat, utcnow()) == (None, False)
    sub.expires_at = utcnow() + timedelta(days=1)
    sub.ads_limit = 0
    await session.flush()
    assert await p.eligible_ad(session, cat, utcnow()) == (None, False)
    sub.ads_limit = 1
    sub.ads_used = 2
    await session.flush()
    assert await p.eligible_ad(session, cat, utcnow()) == (None, False)


def test_time_math_quiet_day_night_and_minimum(monkeypatch) -> None:
    tz = p.timezone_for("Asia/Tashkent")
    # 18:30 UTC = 23:30 Toshkent, ertalab 08:00 da ochiladi.
    now = datetime(2026, 10, 15, 18, 30, tzinfo=UTC)
    assert p.quiet_until(now, "23:00", "08:00", tz) == datetime(2026, 10, 16, 3, tzinfo=UTC)
    assert p.tomorrow(now, tz) == datetime(2026, 10, 15, 19, tzinfo=UTC)
    assert p.quiet_until(now, "09:00", "17:00", tz) is None
    assert p.quiet_until(datetime(2026, 10, 15, 7, tzinfo=UTC), "09:00", "17:00", tz) == datetime(2026, 10, 15, 12, tzinfo=UTC)
    assert p.quiet_until(now, "23:00", "23:00", tz) is None
    monkeypatch.setattr(p.random, "uniform", lambda low, high: low)
    assert p.next_interval(now, 60, 30) == now + timedelta(seconds=60)
    assert p.next_interval(now, 100, 10) == now + timedelta(seconds=90)
    monkeypatch.setattr(p.random, "uniform", lambda low, high: high)
    assert p.next_interval(now, 100, 10) == now + timedelta(seconds=110)


async def test_claim_is_atomic_and_stale_sending_never_resends(session) -> None:
    group, cat, ads, _, _, _ = await setup(session)
    now = utcnow()
    claim, result = await p.claim_post(session, group.id, now)
    assert result.status == "claimed" and claim and claim.ad_id == ads[0].id
    await session.commit()  # haqiqiy poster Telegram'dan OLDIN commit qiladi
    again, result = await p.claim_post(session, group.id, now + timedelta(seconds=1), force_ad_id=ads[0].id)
    assert again is None and result.status == "busy"
    assert len((await session.execute(select(PostLog))).scalars().all()) == 1
    stale, result = await p.claim_post(session, group.id, claim.lease_until + timedelta(seconds=1))
    assert stale is None and result.status == "uncertain" and result.notify
    assert group.is_active is False
    assert group.rotation.next_post_at is None
    assert (await session.execute(select(PostLog))).scalar_one().status == "uncertain"
    await session.flush()
    assert (await session.execute(select(func.count()).select_from(ErrorLog))).scalar_one() == 1


async def test_category_moved_during_send_marks_ids_uncertain(session) -> None:
    group, category, ads, _, _, _ = await setup(session)
    now = utcnow()
    claim, _ = await p.claim_post(session, group.id, now)
    assert claim is not None
    category.group_id = None  # admin uni yuborish davomida boshqa guruhga o'tkazdi
    result = await p.finish_post(session, claim, [421, 422], now)
    await session.flush()
    assert result.status == "uncertain" and result.message_ids == (421, 422)
    assert not group.is_active and group.paused_reason == "error"
    assert ads[0].post_count == 0
    assert (await session.get(PostLog, claim.log_id)).message_ids == [421, 422]
    assert (await session.execute(select(ErrorLog))).scalar_one().is_critical


async def test_log_changed_during_send_never_reports_success(session) -> None:
    group, _, _, _, _, _ = await setup(session)
    claim, _ = await p.claim_post(session, group.id, utcnow())
    assert claim is not None
    log = await session.get(PostLog, claim.log_id)
    log.status = "skipped"
    result = await p.finish_post(session, claim, [567], utcnow())
    assert result.status == "uncertain" and result.message_ids == (567,)
    assert log.status == "uncertain" and log.message_ids == [567]
    assert not group.is_active


async def test_cas_rejects_stale_timestamp(session) -> None:
    group, _, _, _, _, _ = await setup(session)
    rotation = group.rotation
    old = rotation.next_post_at
    await session.execute(
        update(GroupRotation)
        .where(GroupRotation.group_id == group.id)
        .values(next_post_at=utcnow() + timedelta(hours=2))
        .execution_options(synchronize_session=False)
    )
    # Boshqa worker vaqtni almashtirgandek: eski qiymat bilan UPDATE ta'sir qilmaydi.
    assert await p._cas_next(session, rotation, utcnow() + timedelta(minutes=1)) is False
    assert rotation.next_post_at == old


async def test_three_known_send_errors_trigger_auto_pause(session) -> None:
    group, _, _, _, _, _ = await setup(session)
    now = utcnow()
    for attempt in range(1, 4):
        claim, _ = await p.claim_post(session, group.id, now)
        assert claim is not None
        result = await p.fail_post(session, claim, "Known delivery failure", now)
        await session.flush()  # har amalda alohida commit qiladigan poster bilan mos
        assert result.status == "error"
        assert group.rotation.error_streak == attempt
        if attempt < 3:
            assert group.is_active and not result.notify
            now = ensure_aware(group.rotation.next_post_at) + timedelta(seconds=1)
        else:
            assert not group.is_active and result.notify
            assert group.paused_reason == "error" and group.rotation.next_post_at is None


async def test_quiet_hours_and_daily_cap_defer_without_claim(session) -> None:
    now = datetime(2026, 10, 15, 18, 30, tzinfo=UTC)
    group, _, _, _, _, _ = await setup(session, now=now)
    group.settings.quiet_start = "23:00"
    group.settings.quiet_end = "08:00"
    claim, result = await p.claim_post(session, group.id, now)
    assert claim is None and result.status == "deferred"
    assert ensure_aware(group.rotation.next_post_at) == datetime(2026, 10, 16, 3, tzinfo=UTC)
    group.settings.quiet_start = None
    group.settings.quiet_end = None
    group.rotation.next_post_at = now - timedelta(seconds=1)
    group.rotation.today_date = p.local_day(now, p.timezone_for("Asia/Tashkent"))
    group.rotation.today_count = group.settings.daily_post_limit
    await session.flush()
    claim, result = await p.claim_post(session, group.id, now)
    assert claim is None and result.status == "deferred"
    assert ensure_aware(group.rotation.next_post_at) == p.tomorrow(now, p.timezone_for("Asia/Tashkent"))
    assert (await session.execute(select(func.count()).select_from(PostLog))).scalar_one() == 0


async def test_empty_queue_pauses_but_future_eligible_defers(session) -> None:
    group, _, ads, _, _, _ = await setup(session, count=1)
    now = utcnow()
    ads[0].next_eligible_at = now + timedelta(minutes=10)
    await session.flush()
    claim, result = await p.claim_post(session, group.id, now)
    assert claim is None and result.status == "deferred"
    assert group.is_active is True
    assert ensure_aware(group.rotation.next_post_at) == ads[0].next_eligible_at
    ads[0].status = AdStatus.PAUSED
    group.rotation.next_post_at = now - timedelta(seconds=1)
    await session.flush()
    claim, result = await p.claim_post(session, group.id, now)
    assert claim is None and result.status == "empty" and result.notify
    assert group.is_active is False and group.settings.posting_enabled is False
    await session.flush()
    assert (await session.execute(select(PostLog))).scalar_one().status == "skipped"


async def test_manual_claim_validates_group_and_minute_gap(session) -> None:
    group, cat, ads, _, _, _ = await setup(session, count=1)
    now = utcnow()
    group.rotation.next_post_at = now + timedelta(days=1)
    await session.flush()
    claim, result = await p.claim_post(session, group.id, now, force_ad_id=ads[0].id)
    assert claim and result.status == "claimed"  # vaqtni chetlab o'tadi
    await p.abandon_post(session, claim, now)
    group.rotation.last_post_at = now
    await session.flush()
    claim, result = await p.claim_post(session, group.id, now + timedelta(seconds=1), force_ad_id=ads[0].id)
    assert claim is None and result.status == "deferred"
    group.rotation.last_post_at = None
    ads[0].status = AdStatus.PAUSED
    await session.flush()
    claim, result = await p.claim_post(session, group.id, now, force_ad_id=ads[0].id)
    assert claim is None and result.status == "invalid" and group.is_active
