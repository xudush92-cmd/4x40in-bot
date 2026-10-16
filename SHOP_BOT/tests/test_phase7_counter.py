"""Phase 7: real Dispatcher + SQLite + soxta Telegram bilan sanoqchi oqimlari."""

from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.methods import CreateChatInviteLink, DeleteMessage
from aiogram.types import (
    Chat,
    ChatInviteLink,
    ChatJoinRequest,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberUpdated,
    Message,
    Update,
)
from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.constants import AdminRole, CounterMode, InviteSource, PermissionKind
from app.db.models import (
    ActionLog,
    Admin,
    CleanerSetting,
    CounterAudit,
    CounterJoinRequest,
    CounterMessageCheck,
    CounterRestriction,
    CounterSetting,
    CounterTotal,
    GroupMessageAction,
    InviteEvent,
    InviteLink,
    Permission,
    RequiredChannel,
    Restriction,
    Setting,
    Warning,
)
from app.handlers.group import counter as handler
from app.keyboards.callbacks import AdminCB, CounterAdminCB, CounterCB, FeatureCB
from app.scheduler.jobs import retention_job
from app.scheduler.runner import build_scheduler
from app.services import counter_service as counters
from app.services import group_service
from app.services.settings_service import settings_service
from app.utils.time import utcnow
from tests.fake_telegram import (
    ADMIN_ID,
    BOT_ID,
    GROUP_CHAT_ID,
    FakeSession,
    bot_member,
    callback_update,
    group_chat,
    make_bot,
    make_dispatcher,
    reset_dispatcher_state,
    text_update,
)

INVITER = 50001
INVITEE = 60001
OTHER = -1007891234567
CHANNEL = -1009871234567


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


def user(uid: int) -> TgUser:
    return TgUser(id=uid, is_bot=False, first_name="Sinov a'zosi")


def subscribed(fake: FakeSession):
    """Bot kanalda/guruhda admin; oddiy a'zolar a'zo."""
    def _answer(payload):
        if payload["user_id"] == BOT_ID:
            return bot_member()
        return ChatMemberMember(user=user(payload["user_id"]), status="member")
    fake.overrides["GetChatMember"] = _answer


def message(mid: int, *, chat_id: int = GROUP_CHAT_ID, uid: int = INVITER,
            text: str = "xabar", **extra) -> Update:
    chat = group_chat() if chat_id == GROUP_CHAT_ID else Chat(
        id=chat_id, type="supergroup", title="Ikkinchi guruh",
    )
    return Update(update_id=mid, message=Message(
        message_id=mid, date=utcnow(), chat=chat, from_user=user(uid), text=text, **extra,
    ))


def membership(uid: int, *, inviter: int = INVITER, link: str | None = None,
               old: bool = False, update_id: int = 4000) -> Update:
    from aiogram.types import ChatInviteLink

    ref = ChatInviteLink(invite_link=link, creator=user(inviter),
                         creates_join_request=False, is_primary=False, is_revoked=False) if link else None
    return Update(update_id=update_id, chat_member=ChatMemberUpdated(
        chat=group_chat(), from_user=user(inviter), date=utcnow(),
        old_chat_member=(ChatMemberMember(user=user(uid), status="member") if old
                         else ChatMemberLeft(user=user(uid), status="left")),
        new_chat_member=(ChatMemberLeft(user=user(uid), status="left") if old
                         else ChatMemberMember(user=user(uid), status="member")),
        invite_link=ref,
    ))


async def setup_group(session, *, chat_id: int = GROUP_CHAT_ID) -> int:
    chat = group_chat() if chat_id == GROUP_CHAT_ID else Chat(
        id=chat_id, type="supergroup", title="Ikkinchi guruh",
    )
    group = await group_service.get_or_create_group(session, chat)
    group.bot_is_admin = True
    group.bot_rights = {"can_delete_messages": True, "can_restrict_members": True,
                        "can_invite_users": True}
    await session.commit()
    return group.id


async def enable(session, gid: int, *, dry_run: bool = True, hard: bool = False,
                 n: int = 1, subscribe: bool = False):
    group = await group_service.get_group(session, gid)
    row = await counters.ensure_counter(session, gid)
    group.settings.counter_enabled = row.enabled = True
    row.dry_run, row.required_n, row.require_subscription = dry_run, n, subscribe
    row.mode = CounterMode.HARD if hard else CounterMode.SOFT
    row.min_stay_minutes = 1
    row.count_sources = {"link": True, "added_by": False}
    await session.commit()
    return row


async def send(session, dp, bot, update: Update):
    await dp.feed_update(bot, update)
    session.expire_all()


async def test_settings_are_scoped_safe_and_audited(session):
    one = await setup_group(session)
    two = await setup_group(session, chat_id=OTHER)
    group1, group2 = await group_service.get_group(session, one), await group_service.get_group(session, two)
    policy = await counters.ensure_counter(session, one)
    assert not policy.enabled and policy.dry_run and policy.mode == "soft"
    assert policy.required_n == 3 and policy.min_stay_minutes == 10
    assert not group1.settings.counter_enabled and not group2.settings.counter_enabled
    assert await group_service.set_feature(session, group1, "counter", True, actor_id=ADMIN_ID)
    assert policy.enabled and policy.dry_run and group1.settings.counter_enabled
    await counters.edit_counter(session, group1, "required_n", "5", ADMIN_ID)
    await counters.edit_counter(session, group1, "source", "added_by", ADMIN_ID)
    await counters.edit_counter(session, group1, "mode", "hard", ADMIN_ID)
    assert policy.dry_run and policy.mode == "hard" and policy.count_sources["added_by"]
    await counters.edit_counter(session, group1, "dry_run", False, ADMIN_ID)
    await group_service.set_feature(session, group1, "counter", False, actor_id=ADMIN_ID)
    await group_service.set_feature(session, group1, "counter", True, actor_id=ADMIN_ID)
    assert policy.dry_run and policy.enabled and not group2.settings.counter_enabled
    for field, value in [("required_n", 1001), ("min_stay_minutes", "-1"),
                         ("mode", "ban"), ("dry_run", "false"), ("source", "fake")]:
        with pytest.raises(ValueError):
            await counters.edit_counter(session, group1, field, value, ADMIN_ID)
    assert len((await session.execute(select(ActionLog).where(
        ActionLog.group_id == one, ActionLog.action.in_({"counter_setting", "counter_switch"}),
    ))).scalars().all()) >= 5


async def test_join_request_fallback_link_priority_once_stay_and_daily_quota(session):
    gid = await setup_group(session)
    setting = await enable(session, gid)
    setting.count_sources = {"link": True, "added_by": True}
    setting.max_per_day = 1
    link = InviteLink(group_id=gid, user_id=INVITER, invite_link="https://t.me/+first",
                      is_active=True, join_count=0)
    session.add(link)
    await session.commit()

    assert await counters.record_request(session, group_id=gid, user_id=INVITEE,
                                         invite_link=link.invite_link)
    assert not (await session.execute(select(InviteEvent))).scalars().all()
    assert await counters.request_link(session, gid, INVITEE) == link.invite_link
    assert await counters.request_link(session, gid, INVITEE) is None
    assert await counters.reserve_join(session, group_id=gid, inviter_id=INVITEE,
                                       invitee_id=INVITEE, source=InviteSource.ADDED_BY) is None
    fallback = await counters.reserve_join(session, group_id=gid, inviter_id=INVITER + 1,
                                           invitee_id=INVITEE, source=InviteSource.ADDED_BY)
    final = await counters.reserve_join(session, group_id=gid, inviter_id=INVITER,
                                        invitee_id=INVITEE, source=InviteSource.LINK,
                                        invite_link=link.invite_link)
    assert final.id == fallback.id and final.inviter_id == INVITER and final.source == "link"
    assert await counters.reserve_join(session, group_id=gid, inviter_id=INVITER,
                                       invitee_id=INVITEE, source=InviteSource.LINK,
                                       invite_link=link.invite_link) is None
    await session.refresh(link)
    assert link.join_count == 1
    await session.commit()
    assert await counters.claim_due() == []  # minimal qolish muddati hali o'tmagan

    final.created_at = utcnow() - timedelta(minutes=5)
    final.updated_at = utcnow() - timedelta(minutes=5)
    await session.commit()
    assert await counters.claim_due() == [final.id]
    assert await counters.claim_due() == []  # CAS: worker bir marta oladi
    assert await counters.credit_join(session, final.id, still_member=True) == 1
    assert await counters.credit_join(session, final.id, still_member=True) is None
    await session.commit()
    assert await counters.total_for(session, gid, INVITER) == 1

    second = await counters.reserve_join(session, group_id=gid, inviter_id=INVITER,
                                         invitee_id=INVITEE + 1, source=InviteSource.LINK,
                                         invite_link=link.invite_link)
    second.created_at = utcnow() - timedelta(minutes=5)
    second.updated_at = utcnow() - timedelta(minutes=5)
    await session.commit()
    assert await counters.claim_due() == [second.id]
    assert await counters.credit_join(session, second.id, still_member=True) == 0
    assert second.reject_reason == "daily_limit"

    third = await counters.reserve_join(session, group_id=gid, inviter_id=INVITER,
                                        invitee_id=INVITEE + 2, source=InviteSource.LINK,
                                        invite_link=link.invite_link)
    assert await counters.abandon_early(session, group_id=gid, invitee_id=third.invitee_id)
    assert not await counters.abandon_early(session, group_id=gid, invitee_id=third.invitee_id)
    assert third.reject_reason == "left_early"
    assert await counters.total_for(session, gid, INVITER) == 1


async def test_links_reservation_unique_audit_and_api_fails_closed(session, tg):
    fake, bot, _ = tg
    gid = await setup_group(session)
    await enable(session, gid)
    subscribed(fake)
    link = await handler._personal_link(bot, await group_service.get_group(session, gid),
                                        await session.get(CounterSetting, gid), INVITER)
    assert link and link.startswith("https://t.me/")
    assert len(fake.called("CreateChatInviteLink")) == 1
    again = await handler._personal_link(bot, await group_service.get_group(session, gid),
                                         await session.get(CounterSetting, gid), INVITER)
    assert again == link and len(fake.called("CreateChatInviteLink")) == 1
    active = (await session.execute(select(InviteLink).where(
        InviteLink.group_id == gid, InviteLink.is_active.is_(True),
    ))).scalar_one()
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(InviteLink(group_id=gid, user_id=INVITER,
                                   invite_link="https://t.me/+duplicate", is_active=True))
            await session.flush()
    active.join_count = 20
    await session.commit()
    rotated = await handler._personal_link(bot, await group_service.get_group(session, gid),
                                           await session.get(CounterSetting, gid), INVITER)
    assert rotated != link and len(fake.called("CreateChatInviteLink")) == 2
    assert fake.called("RevokeChatInviteLink")[-1]["invite_link"] == link
    session.expire_all()
    row = (await session.execute(select(InviteLink).where(
        InviteLink.group_id == gid, InviteLink.is_active.is_(True),
    ))).scalar_one()
    assert row.invite_link == rotated

    fake.errors["CreateChatInviteLink"] = TelegramNetworkError(
        CreateChatInviteLink(chat_id=GROUP_CHAT_ID), "connection lost",
    )
    lost = await handler._personal_link(bot, await group_service.get_group(session, gid),
                                        await session.get(CounterSetting, gid), INVITER + 1)
    assert lost is None
    pending = (await session.execute(select(InviteLink).where(
        InviteLink.group_id == gid, InviteLink.user_id == INVITER + 1, InviteLink.is_active.is_(True),
    ))).scalar_one()
    assert pending.invite_link.startswith("pending:")
    await handler._personal_link(bot, await group_service.get_group(session, gid),
                                 await session.get(CounterSetting, gid), INVITER + 1)
    assert len(fake.called("CreateChatInviteLink")) == 3
    await counters.cancel_personal_link(session, pending, ADMIN_ID)
    await session.commit()
    assert len((await session.execute(select(ActionLog).where(
        ActionLog.group_id == gid, ActionLog.action == "invite_cancel",
    ))).scalars().all()) == 1


async def test_counter_dry_run_soft_delete_guard_overlap_duplicate_and_pause(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable(session, gid, dry_run=True)
    group = await group_service.get_group(session, gid)
    group.settings.guard_enabled = True
    from app.services.group_policy_service import ensure_guard
    guard = await ensure_guard(session, gid)
    guard.enabled, guard.dry_run = True, True
    await session.commit()
    subscribed(fake)

    await send(session, dp, bot, message(101, text="https://spam.uz/reklama"))
    check = (await session.execute(select(CounterMessageCheck))).scalar_one()
    assert check.status == "dry_run"
    action = (await session.execute(select(GroupMessageAction))).scalar_one()
    assert action.source == "guard" and action.is_dry_run
    assert not fake.called("DeleteMessage")

    row = await session.get(CounterSetting, gid)
    row.dry_run = False
    await session.commit()
    await send(session, dp, bot, message(102, text="https://spam.uz/reklama"))
    await send(session, dp, bot, message(102, text="https://spam.uz/reklama"))
    assert len(fake.called("DeleteMessage")) == 1
    action = (await session.execute(select(GroupMessageAction).where(
        GroupMessageAction.message_id == 102,
    ))).scalar_one()
    assert action.source == "counter" and action.status == "done"
    assert (await session.execute(select(CounterMessageCheck).where(
        CounterMessageCheck.message_id == 102,
    ))).scalar_one().status == "deleted"
    assert not (await session.execute(select(Warning))).scalars().all()

    await send(session, dp, bot, message(103, text="oddiy", chat_id=OTHER))
    assert len(fake.called("DeleteMessage")) == 1
    group = await group_service.get_group(session, gid)
    group.is_active = False
    group.paused_reason = "manual"
    await session.commit()
    await send(session, dp, bot, message(104))
    assert len(fake.called("DeleteMessage")) == 1


async def test_channel_n_unknown_permissions_and_global_kill(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable(session, gid, dry_run=False, subscribe=True, n=1)
    await counters.add_channel(session, group_id=None, channel_id=CHANNEL,
                               username="kanalnam", title="Global kanal",
                               invite_link="https://t.me/kanalnam", actor_id=ADMIN_ID)
    await session.commit()

    def status(payload):
        uid = payload["user_id"]
        if uid == BOT_ID:
            return bot_member()
        if payload["chat_id"] == CHANNEL:
            return ChatMemberLeft(user=user(uid), status="left")
        return ChatMemberMember(user=user(uid), status="member")
    fake.overrides["GetChatMember"] = status
    await send(session, dp, bot, message(110))
    assert len(fake.called("DeleteMessage")) == 1
    check = (await session.execute(select(CounterMessageCheck).where(
        CounterMessageCheck.message_id == 110,
    ))).scalar_one()
    assert check.issue == "not_subscribed"
    fake.errors["GetChatMember"] = TelegramBadRequest(DeleteMessage(chat_id=CHANNEL, message_id=1),
                                                      "not admin")
    await send(session, dp, bot, message(111))
    assert len(fake.called("DeleteMessage")) == 1  # noma'lum holatda jazo yo'q
    fake.errors.clear()
    subscribed(fake)
    await send(session, dp, bot, message(112))
    assert len(fake.called("DeleteMessage")) == 2
    check = (await session.execute(select(CounterMessageCheck).where(
        CounterMessageCheck.message_id == 112,
    ))).scalar_one()
    assert check.issue == "counter_not_done"

    session.add(Permission(group_id=gid, user_id=INVITER, kind=PermissionKind.COUNTER_EXEMPT,
                           reason="tekshirildi", granted_by=ADMIN_ID, is_active=True))
    await session.commit()
    await send(session, dp, bot, message(113))
    assert len(fake.called("DeleteMessage")) == 2
    fake.overrides["GetChatMember"] = status
    await send(session, dp, bot, message(114))
    assert len(fake.called("DeleteMessage")) == 2  # ijobiy kesh: 60s fail-open
    handler._membership_cache.clear()  # TTL o'tishini simulyatsiya qilish
    await send(session, dp, bot, message(115))
    assert len(fake.called("DeleteMessage")) == 3  # counter_exempt kanalni bekor qilmaydi
    session.add(Setting(key="kill_switch", value=True, updated_by=ADMIN_ID))
    await session.commit()
    await send(session, dp, bot, message(116))
    assert len(fake.called("DeleteMessage")) == 3


async def test_hard_member_event_scheduler_credit_unlock_and_external_mute(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable(session, gid, dry_run=False, hard=True)
    subscribed(fake)
    url = "https://t.me/+inviteowner"
    session.add(InviteLink(group_id=gid, user_id=INVITER,
                           invite_link=url, is_active=True, join_count=0))
    await session.commit()
    assert await handler._restrict(bot, gid, INVITER, "counter_not_done")
    assert len(fake.called("RestrictChatMember")) == 1
    await send(session, dp, bot, membership(INVITEE, link=url))
    join = (await session.execute(select(InviteEvent))).scalar_one()
    assert join.source == "link" and join.inviter_id == INVITER
    assert not join.counted
    await send(session, dp, bot, membership(INVITEE, link=url, update_id=4001))
    assert len((await session.execute(select(InviteEvent))).scalars().all()) == 1
    join.created_at = utcnow() - timedelta(minutes=5)
    join.updated_at = utcnow() - timedelta(minutes=5)
    await session.commit()
    assert await handler.process_due(bot) == 1
    session.expire_all()
    assert await counters.total_for(session, gid, INVITER) == 1
    assert (await session.get(CounterRestriction, (gid, INVITER))).status == "released"
    assert len(fake.called("RestrictChatMember")) >= 3  # inviter + invitee mute, inviter unlock
    assert await handler.process_due(bot) == 0

    # Posbonning boshqa mute'i bo'lsa, sanoqchi uni ochib yubormaydi.
    group = await group_service.get_group(session, gid)
    group.settings.counter_enabled = True
    setting = await session.get(CounterSetting, gid)
    setting.required_n = 2
    session.add(Restriction(group_id=gid, user_id=INVITER, kind="mute",
                            reason="guard (xabar #1)", is_active=True))
    await session.commit()
    assert not await handler._restrict(bot, gid, INVITER, "counter_not_done")
    setting.required_n = 1  # hisob yetarli bo'ldi, lekin guard mute'i alohida
    own_restriction = await session.get(CounterRestriction, (gid, INVITER))
    own_restriction.status = "active"
    await session.commit()
    before = len(fake.called("RestrictChatMember"))
    assert not await handler._unlock(bot, gid, INVITER)
    assert len(fake.called("RestrictChatMember")) == before


async def test_member_self_fallback_request_and_service_cleaner(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable(session, gid)
    group = await group_service.get_group(session, gid)
    group.settings.cleaner_enabled = True
    cleaner = CleanerSetting(group_id=gid, enabled=True, dry_run=False, delete_join_leave=True)
    session.add(cleaner)
    session.add(InviteLink(group_id=gid, user_id=INVITER,
                           invite_link="https://t.me/+joinrequest", is_active=True))
    await session.commit()
    subscribed(fake)
    request = ChatJoinRequest(chat=group_chat(), from_user=user(INVITEE),
                              user_chat_id=INVITEE, date=utcnow(),
                              invite_link=ChatInviteLink(
                                  invite_link="https://t.me/+joinrequest", creator=user(INVITER),
                                  creates_join_request=True, is_primary=False, is_revoked=False,
                              ))
    await send(session, dp, bot, Update(update_id=2000, chat_join_request=request))
    assert not (await session.execute(select(InviteEvent))).scalars().all()
    # Oddiy join xizmat xabarida actor=kirgan odam: UNIQUE ishlatilmaydi.
    await send(session, dp, bot, message(120, uid=INVITEE, text=None,
                                         new_chat_members=[user(INVITEE)]))
    assert not (await session.execute(select(InviteEvent))).scalars().all()
    assert len(fake.called("DeleteMessage")) == 1  # Phase 6 xizmat tozalash davom etdi
    await send(session, dp, bot, membership(INVITEE, inviter=BOT_ID, update_id=2001))
    join = (await session.execute(select(InviteEvent))).scalar_one()
    assert join.inviter_id == INVITER and join.source == "link"
    join_id = join.id
    await send(session, dp, bot, membership(INVITEE, old=True, update_id=2002))
    assert (await session.get(InviteEvent, join_id)).reject_reason == "left_early"


async def test_admin_ui_live_confirmation_channels_adjust_and_global_scope(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    subscribed(fake)
    row = await counters.ensure_counter(session, gid)
    assert not row.enabled
    await session.commit()
    await send(session, dp, bot, callback_update(CounterAdminCB(action="home", group_id=gid).pack(),
                                                  update_id=901))
    assert any("SINOV" in text for text in fake.sent_texts())
    await send(session, dp, bot, callback_update(CounterAdminCB(
        action="toggle", group_id=gid, value="enabled",
    ).pack(), update_id=902))
    assert (await session.get(CounterSetting, gid)).dry_run
    await send(session, dp, bot, callback_update(CounterAdminCB(
        action="live", group_id=gid,
    ).pack(), update_id=903))
    assert (await session.get(CounterSetting, gid)).dry_run  # faqat ogohlantirish
    confirmation = fake.called("EditMessageText")[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    await send(session, dp, bot, callback_update(confirmation, update_id=904))
    assert not (await session.get(CounterSetting, gid)).dry_run
    await send(session, dp, bot, callback_update(CounterAdminCB(
        action="mode", group_id=gid, value="hard",
    ).pack(), update_id=905))
    assert (await session.get(CounterSetting, gid)).dry_run  # HARD qayta tasdiq
    await send(session, dp, bot, callback_update(confirmation, update_id=919))  # eski SOFT tasdig'i
    assert (await session.get(CounterSetting, gid)).dry_run

    # FSM: guruhga xos raqam kiritish, xato qiymat saqlanmaydi.
    await send(session, dp, bot, callback_update(CounterAdminCB(
        action="number", group_id=gid, value="required_n",
    ).pack(), update_id=906))
    await send(session, dp, bot, text_update("1005", update_id=907))
    assert (await session.get(CounterSetting, gid)).required_n == 3
    await send(session, dp, bot, text_update("2", update_id=908))
    assert (await session.get(CounterSetting, gid)).required_n == 2
    await send(session, dp, bot, callback_update(CounterAdminCB(
        action="user", group_id=gid,
    ).pack(), update_id=909))
    await send(session, dp, bot, text_update(str(INVITER), update_id=910))
    await send(session, dp, bot, callback_update(CounterAdminCB(
        action="adjust", group_id=gid, value=f"p{INVITER}",
    ).pack(), update_id=911))
    await send(session, dp, bot, text_update("3 qo'lda tekshirildi", update_id=912))
    assert await counters.total_for(session, gid, INVITER) == 3
    await send(session, dp, bot, callback_update(CounterAdminCB(
        action="zero_ask", group_id=gid, value=str(INVITER),
    ).pack(), update_id=913))
    await send(session, dp, bot, callback_update(CounterAdminCB(
        action="zero_confirm", group_id=gid, value=str(INVITER),
    ).pack(), update_id=914))
    assert await counters.total_for(session, gid, INVITER) == 0
    changes = (await session.execute(select(CounterAudit).where(CounterAudit.group_id == gid))).scalars().all()
    assert [c.delta for c in changes] == [3, -3]

    fake.overrides["GetChat"] = lambda p: (Chat(id=CHANNEL, type="channel", title="Tasdiq",
                                              username="tasdiqkanal")
                                            if p["chat_id"] == "@tasdiqkanal" or p["chat_id"] == CHANNEL
                                            else group_chat())
    await send(session, dp, bot, callback_update(CounterAdminCB(
        action="channel_add", group_id=0,
    ).pack(), update_id=915))
    await send(session, dp, bot, text_update("@tasdiqkanal", update_id=916))
    channel = (await session.execute(select(RequiredChannel))).scalar_one()
    channel_id = channel.id
    assert channel.group_id is None and channel.channel_tg_id == CHANNEL
    assert len(await counters.applicable_channels(session, gid)) == 1
    await send(session, dp, bot, callback_update(CounterAdminCB(
        action="channel_ask", group_id=0, value=str(channel_id),
    ).pack(), update_id=917))
    await send(session, dp, bot, callback_update(CounterAdminCB(
        action="channel_remove", group_id=0, value=str(channel_id),
    ).pack(), update_id=918))
    assert not (await session.get(RequiredChannel, channel_id)).is_active

    scheduler = build_scheduler(get_settings(), bot)
    assert scheduler.get_job("counter") is not None
    assert {"message", "chat_member", "chat_join_request"}.issubset(dp.resolve_used_update_types())


async def test_group_matrix_switch_requires_admin_and_resets_dry_run(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable(session, gid, dry_run=False, hard=True)
    await send(session, dp, bot, callback_update(FeatureCB(
        group_id=gid, feature="counter", enabled=False, origin="feats",
    ).pack(), update_id=980))
    assert not (await session.get(CounterSetting, gid)).enabled
    await send(session, dp, bot, callback_update(FeatureCB(
        group_id=gid, feature="counter", enabled=True, origin="feats",
    ).pack(), update_id=981))
    assert (await session.get(CounterSetting, gid)).dry_run
    assert not fake.called("DeleteMessage")

async def test_user_private_command_and_personal_link_owner_only(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable(session, gid)
    subscribed(fake)
    await send(session, dp, bot, text_update("/takliflarim", user_id=INVITER, update_id=2200))
    assert any("Guruhni tanlang" in text for text in fake.sent_texts())
    await send(session, dp, bot, callback_update(CounterCB(
        action="mine", group_id=gid,
    ).pack(), user_id=INVITER, update_id=2201))
    assert any("Takliflar:" in text for text in fake.edited_texts())
    await send(session, dp, bot, callback_update(CounterCB(
        action="link", group_id=gid,
    ).pack(), user_id=INVITER, update_id=2202))
    assert len(fake.called("CreateChatInviteLink")) == 1
    assert any("Shaxsiy havola" in text for text in fake.edited_texts())
    await send(session, dp, bot, callback_update(CounterCB(
        action="link", group_id=gid,
    ).pack(), user_id=INVITER, update_id=2203))
    assert len(fake.called("CreateChatInviteLink")) == 1
    link = (await session.execute(select(InviteLink).where(
        InviteLink.group_id == gid, InviteLink.user_id == INVITER,
    ))).scalar_one()
    assert link.is_active
    url = link.invite_link
    # Guruhdagi buyruq xususiy URLni hammaga oshkor qilmaydi.
    await send(session, dp, bot, message(2204, text="/takliflarim", uid=INVITER))
    group_replies = [p["text"] for p in fake.called("SendMessage") if p["chat_id"] == GROUP_CHAT_ID]
    assert any("shaxsiy chatda" in text for text in group_replies)
    assert not any(url in text for text in group_replies)
    # Boshqa odamning tugmasini bosish link egasini almashtirmaydi.
    fake.overrides["GetChatMember"] = lambda p: (
        ChatMemberLeft(user=user(p["user_id"]), status="left") if p["user_id"] == INVITEE
        else ChatMemberMember(user=user(p["user_id"]), status="member")
    )
    await send(session, dp, bot, callback_update(CounterCB(
        action="link", group_id=gid,
    ).pack(), user_id=INVITEE, update_id=2205))
    assert len(fake.called("CreateChatInviteLink")) == 1
    assert len((await session.execute(select(InviteLink))).scalars().all()) == 1


async def test_admin_menu_global_stop_and_role_guard(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    await send(session, dp, bot, callback_update(AdminCB(
        action="section", value="counter",
    ).pack(), update_id=2301))
    assert any("Guruh sanoqchisini tanlang" in text for text in fake.edited_texts())
    await send(session, dp, bot, callback_update(CounterAdminCB(
        action="home", group_id=gid,
    ).pack(), update_id=2302))
    session.add(Admin(user_id=456123, role=AdminRole.MODERATOR))
    await session.commit()
    await reset_dispatcher_state()
    await send(session, dp, bot, callback_update(CounterAdminCB(
        action="toggle", group_id=gid, value="enabled",
    ).pack(), user_id=456123, update_id=2303))
    assert not (await session.get(CounterSetting, gid)).enabled
    await send(session, dp, bot, callback_update(FeatureCB(
        feature="counter", group_id=gid, enabled=True,
    ).pack(), user_id=456123, update_id=2304))
    assert not (await session.get(CounterSetting, gid)).enabled

    # Global kill switch alohida, guruh konfiguratsiyasini o'zgartirmaydi.
    await send(session, dp, bot, callback_update(AdminCB(
        action="toggle", value="counter_enabled_global",
    ).pack(), update_id=2305))
    assert not await settings_service.is_feature_enabled_fresh("counter")
    await send(session, dp, bot, callback_update(AdminCB(
        action="toggle", value="counter_enabled_global",
    ).pack(), update_id=2306))
    assert not await settings_service.is_feature_enabled_fresh("counter")  # tasdiq kutilmoqda
    await send(session, dp, bot, callback_update(AdminCB(
        action="resume_policy", value="counter_enabled_global",
    ).pack(), update_id=2307))
    assert await settings_service.is_feature_enabled_fresh("counter")
    assert not (await session.get(CounterSetting, gid)).enabled


async def test_live_validation_missing_channel_and_bot_rights(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    row = await enable(session, gid, hard=True, subscribe=True)
    revision = row.updated_at.strftime("%Y%m%d%H%M%S%f")
    subscribed(fake)
    code = CounterAdminCB(action="live_confirm", group_id=gid, value=revision).pack()
    await send(session, dp, bot, callback_update(code, update_id=2401))
    assert (await session.get(CounterSetting, gid)).dry_run
    assert any("kanal" in text.lower() for text in fake.answers())

    await counters.add_channel(session, group_id=gid, channel_id=CHANNEL,
                               username="tasdiqkanal", title="Tasdiq",
                               invite_link="https://t.me/tasdiqkanal", actor_id=ADMIN_ID)
    await session.commit()
    fake.overrides["GetChat"] = lambda p: (Chat(id=CHANNEL, type="channel", title="Tasdiq")
                                            if p["chat_id"] == CHANNEL else group_chat())
    fake.overrides["GetChatMember"] = lambda p: (
        ChatMemberMember(user=user(BOT_ID), status="member") if p["chat_id"] == CHANNEL
        and p["user_id"] == BOT_ID else bot_member())
    await send(session, dp, bot, callback_update(code, update_id=2402))
    assert (await session.get(CounterSetting, gid)).dry_run
    assert any("admin" in text.lower() for text in fake.answers())
    subscribed(fake)
    await send(session, dp, bot, callback_update(code, update_id=2403))
    assert not (await session.get(CounterSetting, gid)).dry_run


async def test_counter_failure_pause_and_reconcile_mute(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable(session, gid, dry_run=False, hard=True)
    subscribed(fake)
    fake.errors["DeleteMessage"] = TelegramBadRequest(
        DeleteMessage(chat_id=GROUP_CHAT_ID, message_id=3001), "message cannot be deleted")
    await send(session, dp, bot, message(3001))
    assert (await session.execute(select(CounterMessageCheck))).scalar_one().status == "failed"
    assert (await session.execute(select(GroupMessageAction))).scalar_one().status == "failed"
    assert not fake.called("RestrictChatMember") and not (await session.execute(select(Warning))).scalars().all()
    fake.errors["DeleteMessage"] = TelegramForbiddenError(
        DeleteMessage(chat_id=GROUP_CHAT_ID, message_id=3002), "not enough rights")
    await send(session, dp, bot, message(3002))
    group = await group_service.get_group(session, gid)
    assert not group.is_active and group.paused_reason == "no_rights"
    assert len(fake.called("DeleteMessage")) == 2
    fake.errors.clear()
    await send(session, dp, bot, message(3003))
    assert len(fake.called("DeleteMessage")) == 2

    group.is_active = True
    group.paused_reason = None
    await session.commit()
    assert await handler._restrict(bot, gid, INVITER, "counter_not_done")
    before = len(fake.called("RestrictChatMember"))
    group.is_active = False
    group.paused_reason = "manual"
    await session.commit()
    assert await handler.process_restrictions(bot) >= 1
    session.expire_all()
    assert (await session.get(CounterRestriction, (gid, INVITER))).status == "released"
    assert len(fake.called("RestrictChatMember")) == before + 1
    assert not (await session.execute(select(Restriction).where(
        Restriction.reason == "counter_gate", Restriction.is_active.is_(True),
    ))).scalars().all()


async def test_counter_retention_only_completed_logs(session):
    gid = await setup_group(session)
    await enable(session, gid)
    old = utcnow() - timedelta(days=100)
    session.add_all([
        CounterMessageCheck(group_id=gid, message_id=3, user_id=INVITER,
                            issue="counter_not_done", status="dry_run", created_at=old),
        CounterMessageCheck(group_id=gid, message_id=4, user_id=INVITER,
                            issue="counter_not_done", status="running", created_at=old),
        CounterJoinRequest(group_id=gid, user_id=INVITEE,
                           invite_link="https://t.me/+test", expires_at=old),
        InviteEvent(group_id=gid, invitee_id=INVITEE, inviter_id=INVITER,
                    source="link", counted=True, created_at=old),
    ])
    await session.commit()
    await retention_job()
    session.expire_all()
    checks = (await session.execute(select(CounterMessageCheck))).scalars().all()
    assert [entry.message_id for entry in checks] == [4]
    assert not (await session.execute(select(CounterJoinRequest))).scalars().all()
    assert (await session.execute(select(InviteEvent))).scalars().all()  # bir-marta sanash saqlanadi

async def test_lost_channel_admin_fails_open_before_delete(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable(session, gid, subscribe=True, dry_run=False)
    await counters.add_channel(session, group_id=gid, channel_id=CHANNEL,
                               username="somechannel", title="Kanal",
                               invite_link="https://t.me/somechannel", actor_id=ADMIN_ID)
    await session.commit()

    def user_or_bot(payload):
        if payload["chat_id"] == CHANNEL and payload["user_id"] == BOT_ID:
            return ChatMemberMember(user=user(BOT_ID), status="member")  # adminlik yo'q
        if payload["chat_id"] == CHANNEL:
            return ChatMemberLeft(user=user(payload["user_id"]), status="left")
        return ChatMemberMember(user=user(payload["user_id"]), status="member")
    fake.overrides["GetChatMember"] = user_or_bot
    await send(session, dp, bot, message(3500))
    assert not fake.called("DeleteMessage")
    check = (await session.execute(select(CounterMessageCheck))).scalar_one()
    assert check.status == "skipped"  # tekshiruv API oldidan qayta o'tdi
    assert (await session.execute(select(GroupMessageAction))).scalar_one().status == "skipped"


async def test_large_manual_reset_stays_group_scoped(session):
    gid, other = await setup_group(session), await setup_group(session, chat_id=OTHER)
    await enable(session, gid)
    await enable(session, other)
    for _ in range(2):
        await counters.adjust(session, group_id=gid, user_id=INVITER,
                              delta=900, actor_id=ADMIN_ID, reason="Hisobni tekshirib qo'shdim")
    await counters.adjust(session, group_id=other, user_id=INVITER,
                          delta=1, actor_id=ADMIN_ID, reason="Boshqa guruh")
    assert await counters.reset_count(session, group_id=gid, user_id=INVITER, actor_id=ADMIN_ID)
    assert not await counters.reset_count(session, group_id=gid, user_id=INVITER, actor_id=ADMIN_ID)
    assert await counters.total_for(session, gid, INVITER) == 0
    assert await counters.total_for(session, other, INVITER) == 1
    audits = (await session.execute(select(CounterAudit).where(
        CounterAudit.group_id == gid,
    ).order_by(CounterAudit.id))).scalars().all()
    assert [row.delta for row in audits] == [900, 900, -1800]

async def test_group_quota_change_refreshes_only_local_unlock_status(session):
    gid, other = await setup_group(session), await setup_group(session, chat_id=OTHER)
    await enable(session, gid, n=3)
    await enable(session, other, n=1)
    await counters.adjust(session, group_id=gid, user_id=INVITER, delta=2,
                          actor_id=ADMIN_ID, reason="Ikki taklif qo'shildi")
    await counters.adjust(session, group_id=other, user_id=INVITER, delta=2,
                          actor_id=ADMIN_ID, reason="Ikki taklif qo'shildi")
    await session.commit()
    one, two = await session.get(CounterTotal, (gid, INVITER)), await session.get(CounterTotal, (other, INVITER))
    assert not one.is_unlocked and two.is_unlocked
    before = two.unlocked_at
    group = await group_service.get_group(session, gid)
    await counters.edit_counter(session, group, "required_n", 2, ADMIN_ID)
    await session.refresh(one)
    assert one.is_unlocked and one.unlocked_at and two.unlocked_at == before
    await counters.edit_counter(session, group, "required_n", 5, ADMIN_ID)
    await session.refresh(one)
    assert not one.is_unlocked and one.unlocked_at is None
    assert two.is_unlocked
    await counters.edit_counter(session, group, "required_n", 0, ADMIN_ID)
    assert await counters.reset_count(session, group_id=gid, user_id=INVITER, actor_id=ADMIN_ID)
    await session.refresh(one)
    assert one.counted == 0 and one.is_unlocked and one.unlocked_at
    assert two.counted == 2 and two.is_unlocked
