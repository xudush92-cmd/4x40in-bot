"""Guruh ichidagi «A'zo qo'shish» va oddiy a'zoga qisqa izoh (oflayn)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest_asyncio
from aiogram.types import Chat, ChatMemberLeft, ChatMemberMember, ChatMemberUpdated, Update
from sqlalchemy import select

from app.constants import AdminRole, SellerStatus, SubscriptionStatus
from app.db.models import Admin, Category, CounterSetting, InviteEvent, Seller, Subscription, Tariff
from app.handlers.admin import counter as admin_counter
from app.handlers.group import counter as handler
from app.services import counter_service as counters
from app.services import group_service
from app.utils.time import utcnow
from tests.fake_telegram import (
    ADMIN_ID,
    GROUP_CHAT_ID,
    FakeSession,
    make_bot,
    make_dispatcher,
    reset_dispatcher_state,
)
from tests.test_group_service import _admin_member
from tests.test_phase7_counter import (
    INVITEE,
    INVITER,
    OTHER,
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


async def enable_direct(session, group_id: int, *, n: int = 1) -> CounterSetting:
    group = await group_service.get_group(session, group_id)
    setting = await counters.ensure_counter(session, group_id)
    assert setting.count_sources["added_by"] and not setting.notify_inviter
    assert not setting.enabled and setting.dry_run  # jonli cheklash yashirincha yoqilmaydi
    group.settings.counter_enabled = setting.enabled = True
    setting.dry_run = False  # adminning testdagi jonli tasdig'i
    setting.required_n = n
    setting.min_stay_minutes = 0
    await session.commit()
    return setting


async def finish_join(session, bot, *, group_id: int, invitee_id: int) -> None:
    event = (await session.execute(select(InviteEvent).where(
        InviteEvent.group_id == group_id, InviteEvent.invitee_id == invitee_id,
    ))).scalar_one()
    event.created_at = utcnow() - timedelta(minutes=1)
    event.updated_at = utcnow() - timedelta(minutes=1)
    await session.commit()
    assert await handler.process_due(bot) == 1


async def test_live_direct_counter_does_not_require_bot_to_create_invite_links(session, tg):
    fake, bot, _ = tg
    gid = await setup_group(session)
    group = await group_service.get_group(session, gid)
    setting = await counters.ensure_counter(session, gid)
    group.settings.counter_enabled = setting.enabled = True
    await session.commit()
    fake.overrides["GetChatMember"] = _admin_member(can_invite=False)

    await admin_counter._validate_live(bot, session, group, setting)
    assert not group.bot_rights["can_invite_users"]
    assert setting.count_sources == {"link": False, "added_by": True}


async def test_direct_add_button_unlocks_without_personal_link_or_bot_menu(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable_direct(session, gid)
    subscribed(fake)

    await send(session, dp, bot, message(9101))
    assert fake.called("DeleteMessage") == [{"chat_id": GROUP_CHAT_ID, "message_id": 9101}]
    assert [p["text"] for p in fake.called("SendMessage")] == [
        "Guruhga yozish uchun odam qo‘shing.",
    ]

    # Hatto eski guruhda DM switchi yoqilgan bo'lsa ham qo'lda qo'shgan
    # odam botga kirishga majbur bo'lmaydi va unga ortiqcha xabar bormaydi.
    setting = await session.get(CounterSetting, gid)
    setting.notify_inviter = True
    await session.commit()
    # Telegram guruhidagi «A'zo qo'shish»: actor boshqa odam, invite_link yo'q.
    await send(session, dp, bot, membership(INVITEE, update_id=9102))
    event = (await session.execute(select(InviteEvent))).scalar_one()
    assert event.group_id == gid and event.inviter_id == INVITER
    assert event.invitee_id == INVITEE and event.source == "added_by"
    assert not event.counted and event.invite_link is None
    await send(session, dp, bot, membership(INVITEE, update_id=9103))
    assert len((await session.execute(select(InviteEvent))).scalars().all()) == 1
    await finish_join(session, bot, group_id=gid, invitee_id=INVITEE)
    assert await counters.total_for(session, gid, INVITER) == 1
    await send(session, dp, bot, message(9104))
    assert len(fake.called("DeleteMessage")) == 1  # yozish huquqi ochildi
    assert not fake.called("CreateChatInviteLink")
    assert not any(p["chat_id"] == INVITER for p in fake.called("SendMessage"))


async def test_direct_add_is_scoped_to_group_and_self_join_is_not_counted(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    other_gid = await setup_group(session, chat_id=OTHER)
    await enable_direct(session, gid)
    await enable_direct(session, other_gid)
    subscribed(fake)

    await send(session, dp, bot, membership(INVITEE, inviter=INVITEE, update_id=9201))
    assert not (await session.execute(select(InviteEvent))).scalars().all()
    await send(session, dp, bot, membership(INVITEE, update_id=9202))
    await finish_join(session, bot, group_id=gid, invitee_id=INVITEE)
    assert await counters.total_for(session, other_gid, INVITER) == 0
    await send(session, dp, bot, message(9203, chat_id=OTHER))
    assert [p["text"] for p in fake.called("SendMessage") if p["chat_id"] == OTHER] == [
        "Guruhga yozish uchun odam qo‘shing.",
    ]

    other_chat = Chat(id=OTHER, type="supergroup", title="Ikkinchi guruh")
    other_join = Update(update_id=9204, chat_member=ChatMemberUpdated(
        chat=other_chat, from_user=user(INVITER), date=utcnow(),
        old_chat_member=ChatMemberLeft(user=user(INVITEE + 1), status="left"),
        new_chat_member=ChatMemberMember(user=user(INVITEE + 1), status="member"),
    ))
    await send(session, dp, bot, other_join)
    await finish_join(session, bot, group_id=other_gid, invitee_id=INVITEE + 1)
    assert await counters.total_for(session, other_gid, INVITER) == 1
    assert await counters.total_for(session, gid, INVITER) == 1
    await send(session, dp, bot, message(9205, chat_id=OTHER))
    assert [p["message_id"] for p in fake.called("DeleteMessage") if p["chat_id"] == OTHER] == [9203]


async def test_join_request_approver_is_not_treated_as_direct_inviter(session, tg):
    _, bot, dp = tg
    gid = await setup_group(session)
    await enable_direct(session, gid)
    event = Update(update_id=9240, chat_member=ChatMemberUpdated(
        chat=Chat(id=GROUP_CHAT_ID, type="supergroup", title="Telefonlar"),
        from_user=user(INVITER), date=utcnow(),
        old_chat_member=ChatMemberLeft(user=user(INVITEE), status="left"),
        new_chat_member=ChatMemberMember(user=user(INVITEE), status="member"),
        via_join_request=True,
    ))
    # Xizmat xabari oldin kelsa actor admin deb ko'rinishi mumkin; keyingi
    # join-request update'i uning kreditga o'tishini taqiqlaydi.
    await send(session, dp, bot, message(9239, uid=INVITER, text=None,
                                         new_chat_members=[user(INVITEE)]))
    assert (await session.execute(select(InviteEvent))).scalar_one().source == "added_by"
    await send(session, dp, bot, event)
    entry = (await session.execute(select(InviteEvent))).scalar_one()
    assert entry.reject_reason == "unattributed_join" and not entry.counted
    entry.created_at = utcnow() - timedelta(minutes=1)
    entry.updated_at = utcnow() - timedelta(minutes=1)
    await session.commit()
    assert await handler.process_due(bot) == 0
    assert await counters.total_for(session, gid, INVITER) == 0


async def test_public_link_join_does_not_inherit_service_message_actor(session, tg):
    _, bot, dp = tg
    gid = await setup_group(session)
    await enable_direct(session, gid)
    await send(session, dp, bot, message(9241, uid=INVITER, text=None,
                                         new_chat_members=[user(INVITEE)]))
    await send(session, dp, bot, membership(INVITEE, link="https://t.me/+common",
                                            update_id=9242))
    entry = (await session.execute(select(InviteEvent))).scalar_one()
    assert entry.reject_reason == "unattributed_join" and not entry.counted
    assert await counters.total_for(session, gid, INVITER) == 0


async def test_service_message_direct_add_is_counted_once_without_chat_member_update(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable_direct(session, gid)
    subscribed(fake)

    # Telegram ayrim qo'shishlarni xizmat xabari sifatida ham yuboradi.
    await send(session, dp, bot, message(9251, uid=INVITER, text=None,
                                         new_chat_members=[user(INVITEE)]))
    event = (await session.execute(select(InviteEvent))).scalar_one()
    assert event.source == "added_by" and event.inviter_id == INVITER
    await send(session, dp, bot, membership(INVITEE, update_id=9252))
    assert len((await session.execute(select(InviteEvent))).scalars().all()) == 1
    await finish_join(session, bot, group_id=gid, invitee_id=INVITEE)
    assert await counters.total_for(session, gid, INVITER) == 1
    assert not fake.called("CreateChatInviteLink")
    assert not any(p["chat_id"] == INVITER for p in fake.called("SendMessage"))


async def test_paid_subscription_exempts_only_its_groups_and_expires(session, tg):
    fake, bot, dp = tg
    gid = await setup_group(session)
    other_gid = await setup_group(session, chat_id=OTHER)
    await enable_direct(session, gid)
    await enable_direct(session, other_gid)
    category = Category(group_id=gid, name="Telefonlar", is_active=True)
    other_category = Category(group_id=other_gid, name="Ustalar", is_active=True)
    seller = Seller(user_id=INVITER, display_name="E'lon beruvchi", status=SellerStatus.ACTIVE)
    session.add_all([category, other_category, seller])
    await session.flush()
    tariff = Tariff(name="Pullik", price=Decimal("100000"), duration_days=30,
                    max_ads=1, max_photos=1, is_trial=False,
                    allowed_group_ids=[gid], allowed_category_ids=[category.id])
    session.add(tariff)
    await session.flush()
    sub = Subscription(seller_id=seller.id, tariff_id=tariff.id,
                       starts_at=utcnow() - timedelta(days=1),
                       expires_at=utcnow() + timedelta(days=1),
                       status=SubscriptionStatus.ACTIVE, ads_limit=1)
    session.add(sub)
    await session.commit()

    assert await counters.paid_for_group(session, gid, INVITER)
    assert not await counters.paid_for_group(session, other_gid, INVITER)
    await send(session, dp, bot, message(9301))
    assert not fake.called("DeleteMessage")  # pullikda taklif sharti yo'q
    await send(session, dp, bot, message(9302, chat_id=OTHER))
    assert fake.called("DeleteMessage") == [{"chat_id": OTHER, "message_id": 9302}]

    sub.expires_at = utcnow() - timedelta(seconds=1)
    await session.commit()
    assert not await counters.paid_for_group(session, gid, INVITER)
    await send(session, dp, bot, message(9303))
    assert fake.called("DeleteMessage")[-1] == {"chat_id": GROUP_CHAT_ID, "message_id": 9303}

    sub.expires_at = utcnow() + timedelta(days=1)
    tariff.is_trial = True
    await session.commit()
    assert not await counters.paid_for_group(session, gid, INVITER)
    tariff.is_trial = False
    tariff.price = Decimal("0")
    await session.commit()
    assert not await counters.paid_for_group(session, gid, INVITER)
