"""Phase 4: haqiqiy Bot API metodlari FakeSession bilan (tarmoq/Redis yo'q)."""

from __future__ import annotations

from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from sqlalchemy import select

from app.db.base import session_scope
from app.db.models import (
    Ad,
    AdPhoto,
    Category,
    CategoryRotation,
    CleanerSetting,
    ErrorLog,
    Group,
    PostedMessage,
    PostLog,
    StatsDaily,
    Subscription,
)
from app.scheduler import jobs, poster
from app.services import posting_service as p
from app.services import stats_service
from app.services.settings_service import settings_service
from app.utils.time import ensure_aware, utcnow
from tests.fake_telegram import FakeSession, make_bot
from tests.test_posting_service import CHAT_ID, setup


@pytest.fixture(autouse=True)
def _no_real_rate_sleep(monkeypatch):
    async def fast(*args, **kwargs):
        pass
    monkeypatch.setattr(poster.posting_limiter, "acquire", fast)


async def prepared(*, photos: int = 2, ads: int = 1):
    async with session_scope() as session:
        group, category, items, _, _, _ = await setup(session, count=ads)
        for ad in items:
            ad.contact_type = "username"
            ad.contact_value = "@sotuvchi_admin"
            for i in range(photos):
                session.add(AdPhoto(ad_id=ad.id, file_id=f"photo-{ad.id}-{i}", position=i))
        await session.flush()
        return group.id, category.id, [ad.id for ad in items]


async def test_album_reply_statistics_and_persisted_ids(clean_db) -> None:
    group_id, cat_id, [ad_id] = await prepared()
    fake = FakeSession()
    bot = make_bot(fake)
    try:
        result = await poster.post_group(bot, group_id)
        assert result.status == "sent" and result.ad_id == ad_id
        assert result.message_ids == (500, 501, 502)
        media = fake.called("SendMediaGroup")
        assert len(media) == 1 and len(media[0]["media"]) == 2
        assert media[0]["chat_id"] == CHAT_ID
        assert media[0]["media"][0]["caption"].startswith("<b>E'lon 1</b>")
        replies = fake.called("SendMessage")
        assert len(replies) == 1 and replies[0]["reply_to_message_id"] == 500
        assert replies[0]["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://t.me/sotuvchi_admin"
        async with session_scope() as session:
            ad = await session.get(Ad, ad_id)
            group = await session.get(Group, group_id)
            assert ad.post_count == 1 and ad.last_posted_at is not None
            assert ensure_aware(group.rotation.next_post_at) > ensure_aware(group.rotation.last_post_at)
            assert group.rotation.today_count == 1 and group.rotation.error_streak == 0
            log = (await session.execute(select(PostLog))).scalar_one()
            post = (await session.execute(select(PostedMessage))).scalar_one()
            assert log.status == "ok" and log.message_ids == [500, 501, 502]
            assert post.message_ids == [500, 501, 502] and post.category_id == cat_id
    finally:
        await bot.session.close()


async def test_two_ads_rotate_and_manual_force_moves_cursor(clean_db) -> None:
    group_id, cat_id, [first, second] = await prepared(photos=1, ads=2)
    fake = FakeSession()
    bot = make_bot(fake)
    # Interval 31 minut: lokal yarim tun yaqinida today_count reseti tabiiy.
    # Test esa aynan bitta kunlik aylanishni tekshiradi, shuning uchun tush.
    now = (utcnow().astimezone(ZoneInfo("Asia/Tashkent")) + timedelta(days=1)).replace(
        hour=12, minute=0, second=0, microsecond=0,
    ).astimezone(UTC)
    try:
        one = await poster.post_group(bot, group_id, now=now)
        assert one.status == "sent" and one.ad_id == first
        # Guruh/tarif intervali o'tgach adolatli keyingisi ketadi.
        two = await poster.post_group(bot, group_id, now=now + timedelta(minutes=31))
        assert two.status == "sent" and two.ad_id == second
        async with session_scope() as session:
            group = await session.get(Group, group_id)
            cat = await session.get(p.Category, cat_id)
            assert cat.rotation.cursor_ad_id == second
            assert group.rotation.today_count == 2
        forced = await poster.post_group(bot, group_id, force_ad_id=first, now=now + timedelta(minutes=33))
        assert forced.status == "sent" and forced.ad_id == first
        wrapped = await poster.post_group(bot, group_id, now=now + timedelta(minutes=65))
        assert wrapped.status == "sent" and wrapped.ad_id == second
    finally:
        await bot.session.close()


async def test_two_categories_use_round_robin_and_override_interval(clean_db) -> None:
    group_id, cat_id, [ad_id] = await prepared(photos=1)
    async with session_scope() as session:
        cat = await session.get(Category, cat_id)
        cat.interval_override = 120
        second = Category(name="Noutbuklar", group_id=group_id, position=2000,
                          rotation=CategoryRotation(is_paused=False))
        session.add(second)
        await session.flush()
        first = await session.get(Ad, ad_id)
        ad2 = Ad(seller_id=first.seller_id, category_id=second.id, group_id=group_id,
                 title="Noutbuk", position=100, status="active")
        session.add(ad2)
        sub = (await session.execute(select(Subscription))).scalar_one()
        sub.ads_limit = sub.ads_used = 2
        await session.flush()
        ad2_id, second_id = ad2.id, second.id
    fake = FakeSession()
    bot = make_bot(fake)
    now = utcnow()
    try:
        one = await poster.post_group(bot, group_id, now=now)
        assert one.status == "sent" and one.ad_id == ad_id
        async with session_scope() as session:
            group = await session.get(Group, group_id)
            assert ensure_aware(group.rotation.next_post_at) == now + timedelta(seconds=60)
        two = await poster.post_group(bot, group_id, now=now + timedelta(seconds=61))
        assert two.status == "sent" and two.ad_id == ad2_id
        three = await poster.post_group(bot, group_id, now=now + timedelta(seconds=122))
        assert three.status == "sent" and three.ad_id == ad_id
        async with session_scope() as session:
            cat = await session.get(Category, cat_id)
            other = await session.get(Category, second_id)
            assert cat.rotation.cycle_count == 1 and other.rotation.cycle_count == 0
            assert (await session.get(Group, group_id)).rotation.cycle_count == 1
    finally:
        await bot.session.close()


async def test_single_photo_phone_copy_button_and_protection(clean_db) -> None:
    group_id, _, [ad_id] = await prepared(photos=1)
    async with session_scope() as session:
        ad = await session.get(Ad, ad_id)
        group = await session.get(Group, group_id)
        ad.contact_type = "phone"
        ad.contact_value = "+998901112233"
        group.settings.protect_content = True
    fake = FakeSession()
    bot = make_bot(fake)
    try:
        result = await poster.post_group(bot, group_id)
        assert result.status == "sent"
        assert fake.called("SendPhoto")[0]["protect_content"] is True
        reply = fake.called("SendMessage")[0]
        assert reply["reply_markup"]["inline_keyboard"][0][0]["copy_text"]["text"] == "+998901112233"
        assert "+998901112233" in reply["text"]
    finally:
        await bot.session.close()


async def test_more_than_ten_photos_split_into_albums(clean_db) -> None:
    group_id, _, [ad_id] = await prepared(photos=11)
    fake = FakeSession()
    bot = make_bot(fake)
    try:
        result = await poster.post_group(bot, group_id)
        assert result.status == "sent" and len(result.message_ids) == 12
        assert len(fake.called("SendMediaGroup")[0]["media"]) == 10
        assert len(fake.called("SendPhoto")) == 1
        assert len(fake.called("SendMessage")) == 1
        assert fake.called("SendMessage")[0]["reply_to_message_id"] == result.message_ids[0]
    finally:
        await bot.session.close()


def test_caption_escapes_user_html_and_keeps_entities_whole() -> None:
    ad = Ad(title="<b>& test", description="<img> & " * 250, status="active")
    assert "&lt;b&gt;&amp;" in poster.format_caption(ad)
    assert "<img>" not in poster.format_caption(ad)
    assert len(poster.format_caption(ad)) <= 1024
    ad.contact_type, ad.contact_value = "url", "javascript:alert(1)"
    assert poster.contact_markup(ad) is None
    ad.contact_value = "https://[broken"
    assert poster.contact_markup(ad) is None


async def test_retry_after_only_reschedules_its_group(clean_db) -> None:
    group_id, _, [ad_id] = await prepared()
    fake = FakeSession()
    fake.errors["SendMediaGroup"] = TelegramRetryAfter(
        SendMessage(chat_id=CHAT_ID, text="x"), "rate limited", retry_after=35
    )
    bot = make_bot(fake)
    now = utcnow()
    try:
        result = await poster.post_group(bot, group_id, now=now)
        assert result.status == "retry" and not result.notify
        assert not fake.called("SendMessage")  # adminga ham xato yuborilmaydi
        async with session_scope() as session:
            group = await session.get(Group, group_id)
            assert group.is_active and group.rotation.error_streak == 0
            assert ensure_aware(group.rotation.next_post_at) >= now + timedelta(seconds=35)
            log = (await session.execute(select(PostLog))).scalar_one()
            assert log.status == "skipped" and log.ad_id == ad_id
    finally:
        await bot.session.close()


async def test_forbidden_pauses_and_notifies_admins(clean_db) -> None:
    group_id, _, _ = await prepared()
    fake = FakeSession()
    fake.errors["SendMediaGroup"] = TelegramForbiddenError(SendMessage(chat_id=CHAT_ID, text="x"), "bot was kicked")
    bot = make_bot(fake)
    try:
        result = await poster.post_group(bot, group_id)
        assert result.status == "error" and result.notify
        async with session_scope() as session:
            group = await session.get(Group, group_id)
            assert not group.is_active and not group.settings.posting_enabled
            assert group.paused_reason == "error" and group.rotation.error_streak == 1
            assert (await session.execute(select(PostLog))).scalar_one().status == "error"
            assert len((await session.execute(select(ErrorLog))).scalars().all()) == 1
        assert any("to'xtatildi" in row["text"] for row in fake.called("SendMessage"))
    finally:
        await bot.session.close()


async def test_partial_send_cleanup_and_uncertain_if_deletion_fails(clean_db) -> None:
    group_id, _, _ = await prepared()
    fake = FakeSession()
    fake.errors["SendMessage"] = TelegramBadRequest(SendMessage(chat_id=CHAT_ID, text="x"), "reply failed")
    bot = make_bot(fake)
    try:
        result = await poster.post_group(bot, group_id)
        assert result.status == "error" and fake.called("DeleteMessage")
        async with session_scope() as session:
            assert (await session.execute(select(PostedMessage))).scalars().first() is None
            assert (await session.execute(select(PostLog))).scalar_one().status == "error"
    finally:
        await bot.session.close()



async def test_partial_send_deletion_failure_pauses_without_retry(clean_db) -> None:
    # Qisman yuborilgan xabarni o'chira olmasak: at-most-once, admin tekshiradi.
    group_id, _, _ = await prepared()
    fake = FakeSession()
    fake.errors["SendMessage"] = TelegramBadRequest(SendMessage(chat_id=CHAT_ID, text="x"), "reply failed")
    fake.errors["DeleteMessage"] = TelegramForbiddenError(SendMessage(chat_id=CHAT_ID, text="x"), "cannot delete")
    bot = make_bot(fake)
    try:
        result = await poster.post_group(bot, group_id)
        assert result.status == "uncertain" and result.notify
        async with session_scope() as session:
            assert (await session.execute(select(PostLog).order_by(PostLog.id.desc()))).scalars().first().status == "uncertain"
            assert (await session.get(Group, group_id)).is_active is False
    finally:
        await bot.session.close()


async def test_unknown_network_failure_is_uncertain_not_retried(clean_db) -> None:
    group_id, _, _ = await prepared()
    fake = FakeSession()
    fake.errors["SendMediaGroup"] = TimeoutError("connection lost after request")
    bot = make_bot(fake)
    try:
        result = await poster.post_group(bot, group_id)
        assert result.status == "uncertain" and result.notify
        async with session_scope() as session:
            group = await session.get(Group, group_id)
            assert not group.is_active and group.paused_reason == "error"
            assert (await session.execute(select(PostLog))).scalar_one().status == "uncertain"
        assert len(fake.called("SendMediaGroup")) == 1
    finally:
        await bot.session.close()


async def test_global_pause_after_album_cleans_partial(monkeypatch, clean_db) -> None:
    group_id, _, [ad_id] = await prepared()
    calls = [0]

    async def enabled():
        calls[0] += 1
        return calls[0] <= 3  # albomdan keyin, reply'dan oldin pauza

    monkeypatch.setattr(poster, "_enabled", enabled)
    fake = FakeSession()
    bot = make_bot(fake)
    try:
        result = await poster.post_group(bot, group_id)
        assert result.status == "unavailable"
        assert len(fake.called("DeleteMessage")) == 2
        async with session_scope() as session:
            assert (await session.execute(select(PostLog))).scalar_one().status == "skipped"
            assert (await session.get(Group, group_id)).rotation.error_streak == 0
            assert (await session.get(Ad, ad_id)).post_count == 0
    finally:
        await bot.session.close()


async def test_old_post_cleanup_keeps_last_and_records_errors(clean_db) -> None:
    group_id, _, [ad_id] = await prepared()
    async with session_scope() as session:
        group = await session.get(Group, group_id)
        group.settings.cleaner_enabled = True
        session.add(CleanerSetting(
            group_id=group_id, enabled=True, dry_run=False, delete_old_ads=True, keep_last_ads=1,
        ))
    fake = FakeSession()
    bot = make_bot(fake)
    now = utcnow()
    try:
        assert (await poster.post_group(bot, group_id, now=now)).status == "sent"
        assert (await poster.post_group(bot, group_id, now=now + timedelta(minutes=31))).status == "sent"
        async with session_scope() as session:
            posts = (await session.execute(select(PostedMessage).order_by(PostedMessage.id))).scalars().all()
            assert len(posts) == 2 and posts[0].is_deleted and not posts[1].is_deleted
        assert len(fake.called("DeleteMessage")) == 3  # 2 rasm + CTA
    finally:
        await bot.session.close()


async def test_stats_count_only_successful_posts(clean_db) -> None:
    group_id, _, _ = await prepared()
    now = utcnow()
    async with session_scope() as session:
        session.add_all([
            PostLog(group_id=group_id, status="ok", created_at=now),
            PostLog(group_id=group_id, status="error", created_at=now),
            PostLog(group_id=group_id, status="ok", created_at=now - timedelta(days=1)),
            PostLog(group_id=group_id, status="skipped", created_at=now - timedelta(days=1)),
        ])
    async with session_scope() as session:
        overview = await stats_service.get_overview(session)
        assert overview["posts_24h"] == 1
    await jobs.daily_stats_job()
    async with session_scope() as session:
        day = (now - timedelta(days=1)).date()
        assert (await session.get(StatsDaily, {"day": day, "group_id": 0})).posts == 1


async def test_kill_switch_rebases_due_without_sending(clean_db) -> None:
    group_id, _, _ = await prepared()
    async with session_scope() as session:
        await settings_service.set(session, "kill_switch", True)
    settings_service.invalidate()
    fake = FakeSession()
    bot = make_bot(fake)
    try:
        await jobs.posting_tick_job(bot)
        assert not fake.called("SendMediaGroup")
        async with session_scope() as session:
            group = await session.get(Group, group_id)
            assert ensure_aware(group.rotation.next_post_at) > utcnow()
        assert (await poster.post_group(bot, group_id)).status == "unavailable"
    finally:
        await bot.session.close()
