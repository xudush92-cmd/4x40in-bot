"""Phase 6: Phase 4 eski e'lon tozalashiga global/guruh siyosati qo'llanishi."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.base import session_scope
from app.db.models import CleanerSetting, CleanupLog, Group, PostedMessage
from app.scheduler import poster
from app.services.settings_service import settings_service
from app.utils.time import utcnow
from tests.fake_telegram import FakeSession, make_bot
from tests.test_phase4_poster import prepared


@pytest.fixture(autouse=True)
def _no_rate_sleep(monkeypatch):
    async def fast(*args, **kwargs):
        pass
    monkeypatch.setattr(poster.posting_limiter, "acquire", fast)


async def test_old_ads_dry_run_pinned_and_global_stop(clean_db) -> None:
    gid, _, _ = await prepared()
    async with session_scope() as session:
        group = await session.get(Group, gid)
        group.settings.cleaner_enabled = True
        session.add(CleanerSetting(group_id=gid, enabled=True, dry_run=True,
                                   delete_old_ads=True, keep_last_ads=1))
    fake = FakeSession()
    bot = make_bot(fake)
    now = utcnow()
    try:
        assert (await poster.post_group(bot, gid, now=now)).status == "sent"
        assert (await poster.post_group(bot, gid, now=now + timedelta(minutes=31))).status == "sent"
        assert not fake.called("DeleteMessage")
        async with session_scope() as session:
            logs = (await session.execute(select(CleanupLog).where(CleanupLog.kind == "old_ad"))).scalars().all()
            assert len(logs) == 1 and logs[0].deleted_count == 0 and logs[0].details["dry_run"]
            policy = await session.get(CleanerSetting, gid)
            policy.dry_run = False
        # Bitta albom pin qilingan: o'shani qoldiradi, boshqa eskisini o'chiradi.
        fake.overrides["GetChat"] = SimpleNamespace(pinned_message=SimpleNamespace(message_id=501))
        assert (await poster.post_group(bot, gid, now=now + timedelta(minutes=62))).status == "sent"
        assert len(fake.called("DeleteMessage")) == 3
        async with session_scope() as session:
            posts = (await session.execute(select(PostedMessage).order_by(PostedMessage.id))).scalars().all()
            assert not posts[0].is_deleted and posts[1].is_deleted and not posts[2].is_deleted
            skipped = (await session.execute(select(CleanupLog).where(CleanupLog.kind == "old_ad"
            ))).scalars().all()
            assert any((x.details or {}).get("skipped") == "pinned" for x in skipped)
            await settings_service.set(session, "cleaner_enabled_global", False)
        fake.reset()
        assert (await poster.post_group(bot, gid, now=now + timedelta(minutes=93))).status == "sent"
        assert not fake.called("DeleteMessage")
    finally:
        await bot.session.close()


async def test_old_ads_group_switch_prevents_cleanup(clean_db) -> None:
    gid, _, _ = await prepared()
    async with session_scope() as session:
        group = await session.get(Group, gid)
        group.settings.cleaner_enabled = False
        session.add(CleanerSetting(group_id=gid, enabled=True, dry_run=False,
                                   delete_old_ads=True, keep_last_ads=1))
    fake = FakeSession()
    bot = make_bot(fake)
    now = utcnow()
    try:
        assert (await poster.post_group(bot, gid, now=now)).status == "sent"
        assert (await poster.post_group(bot, gid, now=now + timedelta(minutes=31))).status == "sent"
        assert not fake.called("DeleteMessage")
    finally:
        await bot.session.close()
