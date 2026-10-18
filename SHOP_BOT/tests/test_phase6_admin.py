"""Phase 6: admin panelni FSM/callback/rol bilan offline E2E tekshirish."""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select

from app.constants import AdminRole
from app.db.models import (
    ActionLog,
    Admin,
    CleanerSetting,
    GroupMessageAction,
    GuardSetting,
    Permission,
    Restriction,
    Warning,
)
from app.handlers.group.policy import process_due_cleanup
from app.keyboards.callbacks import AdminCB, FeatureCB, GroupCB, PolicyCB
from app.services import group_service
from app.services.settings_service import settings_service
from tests.fake_telegram import (
    ADMIN_ID,
    FakeSession,
    bot_added_update,
    callback_update,
    make_bot,
    make_dispatcher,
    reset_dispatcher_state,
    text_update,
)
from tests.test_phase6_policy import OTHER_CHAT_ID, USER_ID, enable_cleaner, setup_group, update


@pytest_asyncio.fixture
async def tg(session):
    session.add(Admin(user_id=ADMIN_ID, role=AdminRole.SUPER))
    await session.commit()
    await reset_dispatcher_state()
    fake = FakeSession()
    bot = make_bot(fake)
    dp = make_dispatcher()
    yield fake, bot, dp
    await bot.session.close()
    await reset_dispatcher_state()


async def click(session, bot, dp, action: str, gid: int = 0, value: str = "-", *, n: int = 1,
                from_user: int = ADMIN_ID) -> None:
    await dp.feed_update(bot, callback_update(
        PolicyCB(action=action, group_id=gid, value=value).pack(), user_id=from_user, update_id=n,
    ))
    session.expire_all()


async def type_text(session, bot, dp, value: str, *, n: int, from_user: int = ADMIN_ID) -> None:
    await dp.feed_update(bot, text_update(value, update_id=n, user_id=from_user))
    session.expire_all()


async def test_group_guard_ui_isolated_live_confirm_and_emergency_pause(session, tg) -> None:
    fake, bot, dp = tg
    one, two = await setup_group(session), await setup_group(session, chat_id=OTHER_CHAT_ID)
    await dp.feed_update(bot, callback_update(GroupCB(action="card", group_id=one).pack()))
    assert "Xavfsizlik" in str(fake.called("EditMessageText")[-1]["reply_markup"])

    await click(session, bot, dp, "home", one, "guard", n=2)
    assert "sinov" in fake.edited_texts()[-1]
    row = await session.get(GuardSetting, one)
    assert row is not None and row.dry_run and not row.enabled
    await click(session, bot, dp, "gt", one, "enabled", n=3)
    assert (await session.get(GuardSetting, one)).enabled
    assert (await group_service.get_group(session, one)).settings.guard_enabled

    await click(session, bot, dp, "ge", one, "allowed_domains", n=4)
    await type_text(session, bot, dp, "t.me, shop.uz", n=5)
    assert (await session.get(GuardSetting, one)).allowed_domains == ["t.me", "shop.uz"]
    await click(session, bot, dp, "pen", one, "ban", n=6)
    assert (await session.get(GuardSetting, one)).penalty == "warn"  # tasdiqdan oldin
    await click(session, bot, dp, "ban_confirm", one, "ban", n=7)
    assert (await session.get(GuardSetting, one)).penalty == "ban"
    assert (await session.get(GuardSetting, one)).dry_run  # ban siyosati bo'lsa ham sinov
    await click(session, bot, dp, "live", one, "guard", n=8)
    assert (await session.get(GuardSetting, one)).dry_run
    await click(session, bot, dp, "live_confirm", one, "guard", n=9)
    assert not (await session.get(GuardSetting, one)).dry_run
    assert not (await session.get(GuardSetting, two))  # ikkinchi guruh o'zgarmagan

    await click(session, bot, dp, "pause_ask", one, n=10)
    await click(session, bot, dp, "pause_confirm", one, n=11)
    grp = await group_service.get_group(session, one)
    assert not grp.is_active and grp.paused_reason == "manual"
    assert (await session.get(GuardSetting, one)).enabled
    await dp.feed_update(bot, bot_added_update(is_admin=True, update_id=12))
    session.expire_all()
    assert not (await group_service.get_group(session, one)).is_active
    await dp.feed_update(bot, update(710, uid=13))
    assert not fake.called("DeleteMessage")
    actions = (await session.execute(select(ActionLog).where(
        ActionLog.action == "group_emergency_pause"
    ))).scalars().all()
    assert len(actions) == 1

    # Adminning o'zi guruh kartasida pauzadan chiqaradi.
    await dp.feed_update(bot, callback_update(GroupCB(action="pause", group_id=one).pack(), update_id=14))
    session.expire_all()
    assert (await group_service.get_group(session, one)).is_active
    await dp.feed_update(bot, update(711, uid=15))
    assert len(fake.called("DeleteMessage")) == 1


async def test_feature_matrix_always_reenables_dryrun_and_moderator_cannot_toggle(session, tg) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    await dp.feed_update(bot, callback_update(FeatureCB(group_id=gid, feature="guard", enabled=True).pack()))
    row = await session.get(GuardSetting, gid)
    assert row.enabled and row.dry_run
    row.dry_run = False
    await session.commit()
    await dp.feed_update(bot, callback_update(FeatureCB(group_id=gid, feature="guard", enabled=False).pack(), update_id=2))
    await dp.feed_update(bot, callback_update(FeatureCB(group_id=gid, feature="guard", enabled=True).pack(), update_id=3))
    session.expire_all()
    assert (await session.get(GuardSetting, gid)).dry_run
    admin = (await session.execute(select(Admin).where(Admin.user_id == ADMIN_ID))).scalar_one()
    admin.role = AdminRole.MODERATOR
    await session.commit()
    await reset_dispatcher_state()
    await click(session, bot, dp, "gt", gid, "link_filter", n=4)
    assert (await session.get(GuardSetting, gid)).link_filter
    await dp.feed_update(bot, callback_update(FeatureCB(group_id=gid, feature="guard", enabled=False).pack(), update_id=5))
    session.expire_all()
    assert (await session.get(GuardSetting, gid)).enabled
    assert any("faqat admin" in text.lower() for text in fake.answers())


async def test_cleaner_controls_old_ads_and_delay_per_group(session, tg) -> None:
    fake, bot, dp = tg
    one, two = await setup_group(session), await setup_group(session, chat_id=OTHER_CHAT_ID)
    await click(session, bot, dp, "home", one, "cleaner", n=1)
    assert "dry" not in fake.edited_texts()[-1].lower() or "sinov" in fake.edited_texts()[-1]
    row = await session.get(CleanerSetting, one)
    assert row.dry_run and not row.delete_join_leave and not row.delete_old_ads
    await click(session, bot, dp, "ct", one, "enabled", n=2)
    await click(session, bot, dp, "ct", one, "delete_links", n=3)
    await click(session, bot, dp, "ct", one, "delete_old_ads", n=4)
    await click(session, bot, dp, "ce", one, "delete_after_seconds", n=5)
    await type_text(session, bot, dp, "10", n=6)
    assert (await session.get(CleanerSetting, one)).delete_after_seconds == 10
    await click(session, bot, dp, "live", one, "cleaner", n=7)
    await click(session, bot, dp, "live_confirm", one, "cleaner", n=8)
    assert not (await session.get(CleanerSetting, one)).dry_run
    assert not (await session.get(CleanerSetting, two))

    # Eski Phase 4 tugmasi yangi guruhda xabarni jonli tasdiqsiz o'chirmaydi.
    await dp.feed_update(bot, callback_update(GroupCB(action="old_ads", group_id=two).pack(), update_id=9))
    session.expire_all()
    group = await group_service.get_group(session, two)
    policy = await session.get(CleanerSetting, two)
    assert policy.enabled and policy.delete_old_ads and policy.dry_run
    assert group.settings.cleaner_enabled
    await click(session, bot, dp, "live", two, "cleaner", n=10)
    assert (await session.get(CleanerSetting, two)).dry_run
    await click(session, bot, dp, "live_confirm", two, "cleaner", n=11)
    assert not (await session.get(CleanerSetting, two)).dry_run
    await dp.feed_update(bot, callback_update(GroupCB(action="old_ads", group_id=two).pack(), update_id=12))
    session.expire_all()
    assert not (await session.get(CleanerSetting, two)).delete_old_ads


async def test_permission_fsm_expiry_revoke_and_global_visibility(session, tg) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    await click(session, bot, dp, "perm", gid, n=1)
    assert "Ruxsatlar" in fake.edited_texts()[-1]
    await click(session, bot, dp, "perm_add", gid, n=2)
    await type_text(session, bot, dp, str(USER_ID), n=3)
    await click(session, bot, dp, "perm_kind", gid, "link_allowed", n=4)
    await type_text(session, bot, dp, "7", n=5)
    await type_text(session, bot, dp, "<Tasdiqlangan>&", n=6)
    assert not (await session.execute(select(Permission))).scalars().all()
    await click(session, bot, dp, "perm_confirm", gid, n=7)
    entry = (await session.execute(select(Permission))).scalar_one()
    pid = entry.id
    assert entry.user_id == USER_ID and entry.group_id == gid and entry.expires_at
    assert "&lt;Tasdiqlangan&gt;&amp;" in fake.edited_texts()[-1]
    await click(session, bot, dp, "perm_revoke", gid, str(pid), n=8)
    assert (await session.get(Permission, pid)).is_active
    await click(session, bot, dp, "perm_revoke_confirm", gid, str(pid), n=9)
    assert not (await session.get(Permission, pid)).is_active

    await click(session, bot, dp, "perm_add", 0, n=10)
    await type_text(session, bot, dp, str(USER_ID), n=11)
    await click(session, bot, dp, "perm_kind", 0, "full_exempt", n=12)
    await type_text(session, bot, dp, "0", n=13)
    await type_text(session, bot, dp, "Doimiy ruxsat", n=14)
    await click(session, bot, dp, "perm_confirm", 0, n=15)
    global_id = (await session.execute(select(Permission).where(
        Permission.is_active.is_(True)))).scalar_one().id
    await click(session, bot, dp, "perm", gid, n=16)
    assert "global" in fake.edited_texts()[-1]
    # Guruh ro'yxatidagi global ruxsatga "qaytarib olish" tugmasi 0-scope yuboradi.
    markup = fake.called("EditMessageText")[-1]["reply_markup"]["inline_keyboard"]
    buttons = [b for row in markup for b in row if "#" + str(global_id) in b["text"]]
    assert any(b["callback_data"].startswith("pol:perm_revoke:0:") for b in buttons)


async def test_users_manual_ban_lift_and_warning_reset(session, tg) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    session.add(Warning(group_id=gid, user_id=USER_ID, count=4))
    await session.commit()
    await click(session, bot, dp, "user_find", gid, n=1)
    await type_text(session, bot, dp, str(USER_ID), n=2)
    assert "4 ta" in fake.sent_texts()[-1]
    await click(session, bot, dp, "warning_ask", gid, str(USER_ID), n=3)
    await click(session, bot, dp, "warning_confirm", gid, str(USER_ID), n=4)
    assert (await session.get(Warning, (gid, USER_ID))).count == 0
    assert (await session.execute(select(ActionLog).where(
        ActionLog.action == "warning_reset"))).scalars().first()

    await click(session, bot, dp, "manual_ask", gid, f"{USER_ID}.ban", n=5)
    await type_text(session, bot, dp, "Ruxsatsiz reklamalar", n=6)
    assert not fake.called("BanChatMember")
    await click(session, bot, dp, "manual_confirm", gid, f"{USER_ID}.ban", n=7)
    assert len(fake.called("BanChatMember")) == 1
    restrictions = (await session.execute(select(Restriction))).scalars().all()
    assert len(restrictions) == 1 and restrictions[0].is_active
    restriction_id = restrictions[0].id
    await click(session, bot, dp, "manual_confirm", gid, f"{USER_ID}.ban", n=8)  # eski tugma
    assert len(fake.called("BanChatMember")) == 1
    await click(session, bot, dp, "lift_ask", gid, str(restriction_id), n=9)
    await click(session, bot, dp, "lift_confirm", gid, str(restriction_id), n=10)
    assert len(fake.called("UnbanChatMember")) == 1
    assert not (await session.get(Restriction, restriction_id)).is_active
    assert (await session.execute(select(ActionLog).where(
        ActionLog.action == "restriction_lift"))).scalars().first()


async def test_global_switch_restore_needs_confirmation_and_audit(session, tg) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    await click(session, bot, dp, "gt", gid, "enabled", n=1)
    row = await session.get(GuardSetting, gid)
    assert row.enabled and row.dry_run
    await dp.feed_update(bot, callback_update(
        AdminCB(action="toggle", value="guard_enabled_global").pack(), update_id=2,
    ))
    assert not await settings_service.is_feature_enabled("guard")
    await dp.feed_update(bot, callback_update(
        AdminCB(action="toggle", value="guard_enabled_global").pack(), update_id=3,
    ))
    assert "QAYTA YOQISH" in fake.edited_texts()[-1]
    assert not await settings_service.is_feature_enabled("guard")  # tasdiq kerak
    await dp.feed_update(bot, callback_update(
        AdminCB(action="resume_policy", value="guard_enabled_global").pack(), update_id=4,
    ))
    assert await settings_service.is_feature_enabled("guard")
    session.expire_all()
    assert (await session.get(GuardSetting, gid)).dry_run  # global switch guruhni o'zgartirmaydi
    logs = (await session.execute(select(ActionLog).where(
        ActionLog.action == "global_policy_switch"
    ))).scalars().all()
    assert len(logs) == 2


async def test_admin_cancels_scheduled_delete_without_retries(session, tg) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable_cleaner(session, gid, dry_run=False, delay=120)
    await dp.feed_update(bot, update(901))
    action = (await session.execute(select(GroupMessageAction))).scalar_one()
    aid = action.id
    assert action.status == "pending"
    await click(session, bot, dp, "pending", gid, n=2)
    assert "kutilayotgan" in fake.edited_texts()[-1]
    await click(session, bot, dp, "action_cancel_ask", gid, str(aid), n=3)
    await click(session, bot, dp, "action_cancel_confirm", gid, str(aid), n=4)
    assert (await session.get(GroupMessageAction, aid)).status == "skipped"
    # Eski callback ham zarar qilmaydi, scheduler bu xabarga qaytmaydi.
    await click(session, bot, dp, "action_cancel_confirm", gid, str(aid), n=5)
    assert not (await session.get(GroupMessageAction, aid)).status == "running"
    assert await process_due_cleanup(bot) == 0
    assert not fake.called("DeleteMessage")
    log = (await session.execute(select(ActionLog).where(
        ActionLog.action == "policy_action_cancel"
    ))).scalars().all()
    assert len(log) == 1


async def test_manual_ban_respects_global_emergency_stop(session, tg) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    await click(session, bot, dp, "manual_ask", gid, f"{USER_ID}.ban", n=1)
    await type_text(session, bot, dp, "Firibgarlik", n=2)
    await settings_service.set(session, "kill_switch", True, updated_by=ADMIN_ID)
    await session.commit()
    await click(session, bot, dp, "manual_confirm", gid, f"{USER_ID}.ban", n=3)
    assert not fake.called("BanChatMember")
    assert not (await session.execute(select(Restriction))).scalars().all()


async def test_invalid_fsm_value_and_cancel_leaves_group_unchanged(session, tg) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    await click(session, bot, dp, "ge", gid, "warn_limit", n=1)
    await type_text(session, bot, dp, "0", n=2)
    assert any("⚠️" in text for text in fake.sent_texts())
    await type_text(session, bot, dp, "/cancel", n=3)
    assert (await session.get(GuardSetting, gid)).warn_limit == 3
    # FSM tozalangan: keyingi xabar tasodifan sozlamaga aylanmaydi.
    await type_text(session, bot, dp, "7", n=4)
    assert (await session.get(GuardSetting, gid)).warn_limit == 3
