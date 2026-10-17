"""Sanoqchi izohi: guruhda sabab, spam cheklovi va 15s DB cleanup."""

from __future__ import annotations

from datetime import timedelta

import pytest_asyncio
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.methods import DeleteMessage, RestrictChatMember, SendMessage
from aiogram.types import ChatMemberLeft, ChatMemberMember
from sqlalchemy import select

from app.config import get_settings
from app.constants import AdminRole
from app.db.models import Admin, GroupMessageAction, Permission, Setting
from app.handlers.group import counter as handler
from app.handlers.group.policy import claim_due_actions
from app.scheduler.runner import build_scheduler
from app.services import counter_notice_service as notices
from app.services import counter_service as counters
from app.utils.time import ensure_aware, utcnow
from tests.fake_telegram import (
    ADMIN_ID,
    BOT_ID,
    GROUP_CHAT_ID,
    FakeSession,
    bot_member,
    make_bot,
    make_dispatcher,
    reset_dispatcher_state,
)
from tests.test_phase7_counter import (
    CHANNEL,
    INVITEE,
    INVITER,
    OTHER,
    enable,
    membership,
    message,
    send,
    setup_group,
    subscribed,
    user,
)


@pytest_asyncio.fixture
async def tg(session):
    session.add(Admin(user_id=ADMIN_ID, role=AdminRole.SUPER))
    await session.commit()
    await reset_dispatcher_state()
    handler._membership_cache.clear()
    fake = FakeSession()
    bot = make_bot(fake)
    dp = make_dispatcher()
    yield fake, bot, dp
    await bot.session.close()
    await reset_dispatcher_state()


def group_notices(fake):
    return [payload for payload in fake.called("SendMessage")
            if payload["chat_id"] in {GROUP_CHAT_ID, OTHER}]


async def notice_rows(session):
    session.expire_all()
    return (await session.execute(select(GroupMessageAction).where(
        GroupMessageAction.source == notices.NOTICE_SOURCE,
    ).order_by(GroupMessageAction.id))).scalars().all()


async def test_soft_shows_reason_in_group_when_dm_blocked_and_deletes_after_15s(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable(session, gid, dry_run=False, n=3)
    subscribed(fake)

    def blocked_dm(payload):
        if payload["chat_id"] == INVITER:
            raise TelegramForbiddenError(SendMessage(chat_id=INVITER, text="x"), "bot blocked")
        return fake._message(payload).as_(bot)

    fake.overrides["SendMessage"] = blocked_dm
    await send(session, dp, bot, message(8101))
    sent = group_notices(fake)
    assert len(sent) == 1
    text = sent[0]["text"]
    assert text == "Guruhga yozish uchun odam qo‘shing."
    assert "reply_markup" not in sent[0] and "parse_mode" not in sent[0]
    assert not any(p["chat_id"] == INVITER for p in fake.called("SendMessage"))
    assert not fake.called("GetMe")  # ortiqcha API kutishi ham, bot havolasi ham yo'q
    assert [entry["message_id"] for entry in fake.called("DeleteMessage")] == [8101]

    row = (await notice_rows(session))[0]
    assert row.group_id == gid and row.user_id == INVITER and row.status == "pending"
    assert row.message_id > 0
    assert 13 < (ensure_aware(row.due_at) - utcnow()).total_seconds() <= 15
    assert await notices.process_due_notices(bot) == 0  # 15s dan OLDIN o'chirmaydi
    row.due_at = utcnow() - timedelta(seconds=1)  # vaqtni kutmasdan simulyatsiya
    action_id, sent_id = row.id, row.message_id
    await session.commit()
    assert await claim_due_actions() == []  # Phase 6 cleaner bu xabarni olmasin
    restarted_fake = FakeSession()
    restarted_bot = make_bot(restarted_fake)  # xotiradagi holatsiz, faqat DB navbati
    try:
        assert await notices.process_due_notices(restarted_bot) == 1
        assert await notices.process_due_notices(restarted_bot) == 0
    finally:
        await restarted_bot.session.close()
    session.expire_all()
    assert (await session.get(GroupMessageAction, action_id)).status == "done"
    assert restarted_fake.called("DeleteMessage") == [
        {"chat_id": GROUP_CHAT_ID, "message_id": sent_id},
    ]


async def test_cooldown_is_per_group_per_member_and_recovers_after_60s(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    other_gid = await setup_group(session, chat_id=OTHER)
    await enable(session, gid, dry_run=False)
    await enable(session, other_gid, dry_run=False)
    subscribed(fake)

    await send(session, dp, bot, message(8201))
    await send(session, dp, bot, message(8202))  # o'sha a'zo: yana xabar yo'q
    await send(session, dp, bot, message(8203, uid=INVITEE))  # boshqa a'zo: bor
    await send(session, dp, bot, message(8204, chat_id=OTHER))  # boshqa guruh: bor
    assert [p["chat_id"] for p in group_notices(fake)] == [GROUP_CHAT_ID, GROUP_CHAT_ID, OTHER]
    rows = await notice_rows(session)
    assert {(row.group_id, row.user_id) for row in rows} == {
        (gid, INVITER), (gid, INVITEE), (other_gid, INVITER),
    }
    one = next(row for row in rows if row.group_id == gid and row.user_id == INVITER)
    one.created_at = utcnow() - timedelta(seconds=61)
    one.status = "done"  # eski izoh allaqachon tozalangan
    await session.commit()
    await send(session, dp, bot, message(8205))
    assert len(group_notices(fake)) == 4
    assert len(await notice_rows(session)) == 4


async def test_hard_join_warns_only_after_successful_mute(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable(session, gid, hard=True, dry_run=False, n=2)
    subscribed(fake)
    await send(session, dp, bot, membership(INVITEE, update_id=8301))
    assert fake.called("RestrictChatMember")
    assert len(group_notices(fake)) == 1
    assert group_notices(fake)[0]["text"] == "Guruhga yozish uchun odam qo‘shing."
    assert (await notice_rows(session))[0].status == "pending"
    await send(session, dp, bot, membership(INVITEE, update_id=8302))
    assert len(group_notices(fake)) == 1  # takroriy update/xuddi shu mute

    fake.errors["RestrictChatMember"] = TelegramBadRequest(
        RestrictChatMember(chat_id=GROUP_CHAT_ID, user_id=INVITEE + 1,
                           permissions={"can_send_messages": False}), "no restrict rights",
    )
    await send(session, dp, bot, membership(INVITEE + 1, update_id=8303))
    assert len(group_notices(fake)) == 1  # mute API rad etsa yolg'on izoh yo'q
    assert len(await notice_rows(session)) == 1
    assert gid == (await notice_rows(session))[0].group_id


async def test_dry_run_exemption_unknown_and_global_pause_have_no_notice(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    setting = await enable(session, gid, dry_run=True)
    subscribed(fake)
    await send(session, dp, bot, message(8401))
    setting.dry_run = False
    session.add(Permission(group_id=gid, user_id=INVITER, kind="full_exempt",
                           reason="istisno", granted_by=111111, is_active=True))
    await session.commit()
    await send(session, dp, bot, message(8402))
    row = (await session.execute(select(Permission))).scalar_one()
    row.is_active = False
    await session.commit()
    fake.errors["GetChatMember"] = TelegramNetworkError(
        DeleteMessage(chat_id=GROUP_CHAT_ID, message_id=8403), "unknown member",
    )
    await send(session, dp, bot, message(8403))
    fake.errors.clear()
    session.add(Setting(key="counter_enabled_global", value=False))
    await session.commit()
    await send(session, dp, bot, message(8404))
    assert not group_notices(fake) and not await notice_rows(session)
    assert not fake.called("DeleteMessage")


async def test_explicit_subscription_condition_is_explained_only_when_enabled(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable(session, gid, subscribe=True, dry_run=False)
    await counters.add_channel(session, group_id=gid, channel_id=CHANNEL,
                               username="alohida", title="Alohida kanal",
                               invite_link="https://t.me/alohida", actor_id=111111)
    await session.commit()

    def member(payload):
        uid = payload["user_id"]
        if uid == BOT_ID:
            return bot_member()
        if payload["chat_id"] == CHANNEL:
            return ChatMemberLeft(user=user(uid), status="left")
        return ChatMemberMember(user=user(uid), status="member")

    fake.overrides["GetChatMember"] = member
    await send(session, dp, bot, message(8501))
    assert len(group_notices(fake)) == 1
    assert group_notices(fake)[0]["text"] == "Guruhga yozish uchun obuna shartini bajaring."
    assert "reply_markup" not in group_notices(fake)[0]


async def test_failed_send_has_cooldown_and_network_delete_retries_even_during_pause(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable(session, gid, dry_run=False)
    subscribed(fake)
    fake.errors["SendMessage"] = TelegramForbiddenError(
        SendMessage(chat_id=GROUP_CHAT_ID, text="x"), "cannot send",
    )
    await send(session, dp, bot, message(8601))
    row = (await notice_rows(session))[0]
    assert row.status == "failed" and row.due_at is None
    assert row.message_id < 0
    await send(session, dp, bot, message(8602))
    assert len(group_notices(fake)) == 1  # birinchi urinish, qayta emas
    assert len(await notice_rows(session)) == 1

    fake.errors.clear()
    row.created_at = utcnow() - timedelta(seconds=61)
    await session.commit()
    await send(session, dp, bot, message(8603))
    row = (await notice_rows(session))[-1]
    assert row.status == "pending" and row.message_id > 0
    row.due_at = utcnow() - timedelta(seconds=1)
    await session.commit()
    fake.errors["DeleteMessage"] = TelegramNetworkError(
        DeleteMessage(chat_id=GROUP_CHAT_ID, message_id=row.message_id), "connection lost",
    )
    action_id, sent_id = row.id, row.message_id
    assert await notices.process_due_notices(bot) == 1
    session.expire_all()
    row = await session.get(GroupMessageAction, action_id)
    assert row.status == "pending"
    assert 28 <= (ensure_aware(row.due_at) - utcnow()).total_seconds() <= 30

    fake.errors.clear()
    row.status = "running"  # worker delete paytida o'chib qoldi
    row.due_at = utcnow() - timedelta(seconds=1)
    row.updated_at = utcnow() - timedelta(seconds=60)
    session.add(Setting(key="kill_switch", value=True))
    await session.commit()
    assert await notices.process_due_notices(bot) == 1  # switch o'chirilsa ham eski izoh o'chadi
    session.expire_all()
    assert (await session.get(GroupMessageAction, action_id)).status == "done"
    assert fake.called("DeleteMessage")[-1]["message_id"] == sent_id


def test_scheduler_has_one_second_notice_job_only_with_bot():
    scheduler = build_scheduler(get_settings(), object())
    assert scheduler.get_job("counter_notice_cleanup").trigger.interval == timedelta(seconds=1)
    assert scheduler.get_job("group_cleanup").trigger.interval == timedelta(seconds=5)
    assert build_scheduler(get_settings()).get_job("counter_notice_cleanup") is None
