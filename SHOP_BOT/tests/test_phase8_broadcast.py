"""Phase 8: broadcast manzil snapshot'i, admin roziligi, xato va opt-out."""

from __future__ import annotations

from datetime import timedelta

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from sqlalchemy import select

from app.constants import AdminRole
from app.db.base import session_scope
from app.db.models import ActionLog, Admin, Broadcast, BroadcastTarget, User
from app.keyboards.callbacks import AdminCB, BroadcastCB
from app.services import broadcast_service as bs
from app.services import seller_service
from app.utils.time import utcnow
from tests.fake_telegram import (
    ADMIN_ID,
    FakeSession,
    callback_update,
    make_bot,
    make_dispatcher,
    reset_dispatcher_state,
    text_update,
)


async def add_user(session, user_id: int, *, started: bool = True, blocked: bool = False,
                   opt_out: bool = False):
    session.add(User(user_id=user_id, first_name="Foydalanuvchi",
                     private_started_at=utcnow() if started else None,
                     is_blocked=blocked, broadcast_opt_out=opt_out))
    await session.flush()


async def test_snapshot_approval_rate_optout_and_exactly_once(session):
    for uid in (1001, 1002, 1003):
        await add_user(session, uid)
    await add_user(session, 1004, started=False)  # faqat guruhda ko'ringan, DM mumkin emas
    await add_user(session, 1005, blocked=True)
    await add_user(session, 1006, opt_out=True)
    draft = await bs.create_draft(session, ADMIN_ID, "all", "Salom <b> & do'stlar")
    bid = draft.id
    assert draft.text == "Salom &lt;b&gt; &amp; do'stlar"
    assert await bs.eligible_count(session, "all") == 3
    assert not (await session.execute(select(BroadcastTarget))).scalars().all()
    await bs.confirm(session, bid, ADMIN_ID)
    assert draft.total == 3 and draft.status == "queued"
    await add_user(session, 1010)  # tasdiqdan keyin yangi foydalanuvchi ro'yxatga qo'shilmaydi
    with pytest.raises(bs.BroadcastError):
        await bs.confirm(session, bid, ADMIN_ID)
    await session.commit()
    fake = FakeSession()
    bot = make_bot(fake)
    assert await bs.deliver_tick(bot, max_targets=3) == 3
    session.expire_all()
    assert (await session.get(Broadcast, bid)).status == "finished"
    targets = (await session.execute(select(BroadcastTarget).where(
        BroadcastTarget.broadcast_id == bid))).scalars().all()
    assert {t.user_id for t in targets} == {1001, 1002, 1003}
    assert all(t.status == "sent" and t.attempts == 1 and t.telegram_message_id for t in targets)
    assert len([p for p in fake.called("SendMessage") if p.get("chat_id") in (1001, 1002, 1003)]) == 3
    assert await bs.deliver_tick(bot) == 0  # tugagan target qayta yuborilmaydi
    await bot.session.close()


async def test_floodwait_pause_cancel_and_no_duplicate_delivery(session):
    await add_user(session, 2001)
    row = await bs.create_draft(session, ADMIN_ID, "all", "E'lon", "photo-id")
    bid = row.id
    await bs.confirm(session, bid, ADMIN_ID)
    await session.commit()
    fake = FakeSession()
    bot = make_bot(fake)
    fake.errors["SendPhoto"] = TelegramRetryAfter(
        SendMessage(chat_id=2001, text="x"), "Retry", retry_after=2)
    assert await bs.deliver_tick(bot) == 0
    session.expire_all()
    row = await session.get(Broadcast, bid)
    assert row.next_attempt_at is not None and row.sent == 0
    target = (await session.execute(select(BroadcastTarget))).scalar_one()
    assert target.status == "pending" and target.attempts == 1
    fake.errors.clear()
    await bs.change_status(session, bid, ADMIN_ID, "pause")
    row.next_attempt_at = utcnow() - timedelta(seconds=10)
    await session.commit()
    assert await bs.deliver_tick(bot) == 0  # admin pauzasi faqat nomigagina emas
    async with session_scope() as other:
        await bs.change_status(other, bid, ADMIN_ID, "resume")
    assert await bs.deliver_tick(bot) == 1
    session.expire_all()
    row = await session.get(Broadcast, bid)
    assert row.status == "finished" and row.sent == 1 and row.failed == 0
    assert len(fake.called("SendPhoto")) == 2  # birinchi FloodWait, ikkinchisi haqiqiy
    await bot.session.close()


async def test_permanent_error_network_uncertain_and_manual_resolution(session):
    await add_user(session, 3001)
    row = await bs.create_draft(session, ADMIN_ID, "all", "x")
    bid = row.id
    await bs.confirm(session, bid, ADMIN_ID)
    await session.commit()
    fake = FakeSession()
    bot = make_bot(fake)
    fake.errors["SendMessage"] = TelegramForbiddenError(
        SendMessage(chat_id=3001, text="x"), "bot was blocked")
    assert await bs.deliver_tick(bot) == 1
    session.expire_all()
    assert (await session.get(Broadcast, bid)).failed == 1
    assert (await session.get(Broadcast, bid)).status == "finished"

    fake.errors.clear()
    next_draft = await bs.create_draft(session, ADMIN_ID, "all", "second")
    bid2 = next_draft.id
    await bs.confirm(session, bid2, ADMIN_ID)
    await session.commit()
    # API chaqiruvidan keyin worker yiqilsa: kimga yetgani noma'lum.
    async with session_scope() as other:
        claim = await bs.claim_next(other)
        assert claim and claim[1] == 3001
    session.expire_all()
    target = (await session.execute(select(BroadcastTarget).where(
        BroadcastTarget.broadcast_id == bid2))).scalar_one()
    target.claimed_at = utcnow() - timedelta(minutes=6)
    await session.commit()
    async with session_scope() as other:
        assert await bs.reconcile_stale(other) == 1
    session.expire_all()
    assert (await session.get(Broadcast, bid2)).status == "needs_review"
    assert await bs.deliver_tick(bot) == 0
    await bs.change_status(session, bid2, ADMIN_ID, "resolve")
    await session.commit()
    session.expire_all()
    assert (await session.get(Broadcast, bid2)).status == "finished"
    assert (await session.get(Broadcast, bid2)).failed == 1
    actions = (await session.execute(select(ActionLog).where(
        ActionLog.action == "broadcast_resolve"))).scalars().all()
    assert len(actions) == 1
    await bot.session.close()


async def test_admin_preview_confirm_and_private_start_optout_dispatcher(session):
    await add_user(session, 4011)
    await add_user(session, 4012, started=False)
    await seller_service.get_or_create_seller(session, 4011, display_name="Sotuvchi")
    session.add(Admin(user_id=ADMIN_ID, role=AdminRole.SUPER))
    await session.commit()
    await reset_dispatcher_state()
    fake = FakeSession()
    bot = make_bot(fake)
    dp = make_dispatcher()

    async def click(action, n, *, bid=0, target="all"):
        await dp.feed_update(bot, callback_update(
            BroadcastCB(action=action, broadcast_id=bid, target=target).pack(), update_id=n))
        session.expire_all()

    await dp.feed_update(bot, callback_update(AdminCB(action="section", value="broadcast").pack(),
                                              update_id=1))
    assert "Broadcast" in fake.edited_texts()[-1]
    await click("new", 2, target="sellers")
    await dp.feed_update(bot, text_update("Salom <do'stlar>", update_id=3))
    session.expire_all()
    draft = (await session.execute(select(Broadcast))).scalar_one()
    bc_id = draft.id
    assert draft.status == "draft"
    await click("test", 4, bid=bc_id)
    assert any(p["chat_id"] == ADMIN_ID for p in fake.called("SendMessage"))
    assert not any(p["chat_id"] == 4011 for p in fake.called("SendMessage"))
    await click("ask", 5, bid=bc_id)
    await click("confirm", 6, bid=bc_id)
    assert (await session.get(Broadcast, bc_id)).total == 1
    assert not any(p["chat_id"] == 4011 for p in fake.called("SendMessage"))
    assert await bs.deliver_tick(bot) == 1
    assert any(p["chat_id"] == 4011 for p in fake.called("SendMessage"))

    await dp.feed_update(bot, text_update("/xabarlar_stop", update_id=7, user_id=4011))
    session.expire_all()
    assert (await session.get(User, 4011)).broadcast_opt_out
    assert await bs.eligible_count(session, "sellers") == 0
    await dp.feed_update(bot, text_update("/xabarlar_on", update_id=8, user_id=4011))
    session.expire_all()
    assert await bs.eligible_count(session, "sellers") == 1
    await bot.session.close()
    await reset_dispatcher_state()
