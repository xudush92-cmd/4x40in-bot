"""UX-1: besh yo'nalish, eski callbacklar, guruhga xos read-only diagnostika."""

from __future__ import annotations

from aiogram.types import Chat
from sqlalchemy import func, select

from app.constants import AdminRole
from app.db.models import Admin, CounterSetting, GuardSetting
from app.keyboards.callbacks import AdminCB, GroupCB
from app.services import counter_service, group_policy_service, group_service
from app.services.group_diagnostics import diagnostic_text
from tests.fake_telegram import (
    ADMIN_ID,
    FakeSession,
    callback_update,
    make_bot,
    make_dispatcher,
    reset_dispatcher_state,
)


async def test_diagnostics_are_group_local_and_read_only(session) -> None:
    one = await group_service.get_or_create_group(
        session, Chat(id=-10060123001, type="supergroup", title="Birinchi")
    )
    two = await group_service.get_or_create_group(
        session, Chat(id=-10060123002, type="supergroup", title="Ikkinchi")
    )
    one.is_supergroup = two.is_supergroup = True
    one.bot_is_admin = two.bot_is_admin = True
    one.bot_rights = {"can_delete_messages": True, "can_restrict_members": True,
                      "can_invite_users": True}
    await group_policy_service.edit_guard(session, one, "enabled", True, ADMIN_ID)
    await counter_service.edit_counter(session, one, "required_n", "20", ADMIN_ID)
    first = await diagnostic_text(session, one)
    second = await diagnostic_text(session, two)
    assert "Birinchi" in first and "N=20" in first and "🧪 sinovda" in first
    assert "Ikkinchi" in second and "N=3" in second and "shu guruh switchi o'chiq" in second
    assert (await session.execute(select(func.count()).select_from(GuardSetting))).scalar_one() == 1
    assert (await session.execute(select(func.count()).select_from(CounterSetting))).scalar_one() == 1
    assert not two.settings.guard_enabled and not two.settings.counter_enabled


async def test_admin_hubs_queue_and_legacy_callbacks_and_moderator_denial(session) -> None:
    mod_id = 990099
    session.add_all([Admin(user_id=ADMIN_ID, role=AdminRole.SUPER),
                     Admin(user_id=mod_id, role=AdminRole.MODERATOR)])
    group = await group_service.get_or_create_group(
        session, Chat(id=-10060123003, type="supergroup", title="Savdo guruh")
    )
    group_id = group.id
    await session.commit()
    await reset_dispatcher_state()
    fake = FakeSession()
    bot = make_bot(fake)
    dp = make_dispatcher()
    try:
        await dp.feed_update(bot, callback_update(AdminCB(action="menu").pack(), update_id=1))
        assert "Qaror kutayotganlar" in fake.edited_texts()[-1]
        await dp.feed_update(bot, callback_update(AdminCB(action="hub", value="system").pack(), update_id=2))
        assert "guruh qoidalarini o'zgartirmaydi" in fake.edited_texts()[-1]
        await dp.feed_update(bot, callback_update(AdminCB(action="all").pack(), update_id=3))
        assert AdminCB(action="section", value="guard").pack() in str(fake.called("EditMessageText")[-1]["reply_markup"])
        await dp.feed_update(bot, callback_update(AdminCB(action="section", value="groups").pack(), update_id=4))
        assert "Guruhlar" in fake.edited_texts()[-1]
        await dp.feed_update(bot, callback_update(GroupCB(action="card", group_id=group_id).pack(), update_id=5))
        markup = str(fake.called("EditMessageText")[-1]["reply_markup"])
        assert "Odam qo'shish sharti / Sanoqchi" in markup
        assert "Tozalash" in markup and "Xavfsizlik" in markup
        assert "Kanal a'zoligi" not in markup and "Nega ishlamayapti?" in markup
        await dp.feed_update(bot, callback_update(GroupCB(action="diagnostic", group_id=group_id).pack(), update_id=6))
        assert "Savdo guruh" in fake.edited_texts()[-1] and "huquqlari" in fake.edited_texts()[-1]

        await dp.feed_update(bot, callback_update(AdminCB(action="hub", value="sales").pack(),
                                                  user_id=mod_id, update_id=7))
        assert "ruxsat yo'q" in fake.answers()[-1]
        await dp.feed_update(bot, callback_update(AdminCB(action="section", value="payments").pack(),
                                                  user_id=mod_id, update_id=8))
        assert "faqat admin" in fake.answers()[-1]
        await dp.feed_update(bot, callback_update(GroupCB(action="diagnostic", group_id=group_id).pack(),
                                                  user_id=mod_id, update_id=9))
        assert "Savdo guruh" in fake.edited_texts()[-1]
        await dp.feed_update(bot, callback_update(GroupCB(action="pause", group_id=group_id).pack(),
                                                  user_id=mod_id, update_id=10))
        assert "faqat admin" in fake.answers()[-1]
        session.expire_all()
        assert (await group_service.get_group(session, group_id)).is_active
    finally:
        await bot.session.close()
        await reset_dispatcher_state()
