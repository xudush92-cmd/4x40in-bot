"""Phase 6: real Dispatcher + SQLite + soxta Telegram bilan xabar siyosati."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, MessageEntity, Update, VideoChatStarted
from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.constants import AdminRole, Penalty, PermissionKind
from app.db.base import session_scope
from app.db.models import (
    ActionLog,
    Admin,
    CleanerSetting,
    CleanupLog,
    Group,
    GroupAdmin,
    GroupMessageAction,
    GuardSetting,
    Permission,
    Restriction,
    Setting,
    Violation,
    Warning,
)
from app.handlers.group import policy as handler_policy
from app.handlers.group.policy import claim_due_actions, process_due_cleanup
from app.scheduler.runner import build_scheduler
from app.services import group_policy_service as policy
from app.services import group_service
from app.services.settings_service import settings_service
from app.utils.time import utcnow
from tests.fake_telegram import (
    ADMIN_ID,
    GROUP_CHAT_ID,
    FakeSession,
    bot_member,
    group_chat,
    make_bot,
    make_dispatcher,
    reset_dispatcher_state,
)

USER_ID = 456789
OTHER_CHAT_ID = -1009876543210


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


async def setup_group(session, *, chat_id: int = GROUP_CHAT_ID) -> int:
    group = await group_service.get_or_create_group(
        session, group_chat() if chat_id == GROUP_CHAT_ID else Chat(
            id=chat_id, type="supergroup", title="Ikkinchi bozor",
        ),
    )
    group.bot_is_admin = True
    group.bot_rights = {"can_delete_messages": True, "can_restrict_members": True}
    await session.commit()
    return group.id


def update(mid: int, text: str | None = "https://spam.uz/reklama", *, chat_id: int = GROUP_CHAT_ID,
           user_id: int = USER_ID, uid: int | None = None, **kwargs) -> Update:
    return Update(
        update_id=uid if uid is not None else mid,
        message=Message(
            message_id=mid, date=datetime.now(UTC),
            chat=group_chat() if chat_id == GROUP_CHAT_ID else Chat(
                id=chat_id, type="supergroup", title="Ikkinchi bozor",
            ),
            from_user=TgUser(id=user_id, is_bot=False, first_name="Xaridor"),
            text=text, **kwargs,
        ),
    )


async def enable_guard(session, gid: int, *, dry_run: bool = True,
                       penalty: str = Penalty.WARN, warn_limit: int = 3) -> None:
    group = await group_service.get_group(session, gid)
    group.settings.guard_enabled = True
    guard = await policy.ensure_guard(session, gid)
    guard.enabled, guard.dry_run = True, dry_run
    guard.penalty, guard.warn_limit = penalty, warn_limit
    await session.commit()


async def enable_cleaner(session, gid: int, *, dry_run: bool = True,
                         delete_links: bool = True, delay: int = 0) -> None:
    group = await group_service.get_group(session, gid)
    group.settings.cleaner_enabled = True
    cleaner = await policy.ensure_cleaner(session, gid)
    cleaner.enabled, cleaner.dry_run = True, dry_run
    cleaner.delete_links, cleaner.delete_after_seconds = delete_links, delay
    await session.commit()


async def send(session, dp, bot, message: Update) -> None:
    await dp.feed_update(bot, message)
    session.expire_all()


# ── Qoidalarni boshqarish ────────────────────────────────────────
async def test_safe_defaults_validation_audit_and_group_isolation(session) -> None:
    one, two = await setup_group(session), await setup_group(session, chat_id=OTHER_CHAT_ID)
    guard, cleaner = await policy.ensure_guard(session, one), await policy.ensure_cleaner(session, one)
    assert not guard.enabled and guard.dry_run and guard.penalty == "warn"
    assert not cleaner.enabled and cleaner.dry_run and not cleaner.delete_old_ads
    assert not cleaner.delete_links and not cleaner.delete_join_leave
    g1 = await group_service.get_group(session, one)
    g2 = await group_service.get_group(session, two)
    await policy.edit_guard(session, g1, "allowed_domains", "olx.uz, t.me", ADMIN_ID)
    await policy.edit_guard(session, g1, "banned_words", "firib, Fake aksiyA", ADMIN_ID)
    await policy.edit_guard(session, g1, "warn_window_hours", "48", ADMIN_ID)
    await policy.edit_guard(session, g1, "enabled", True, ADMIN_ID)
    assert g1.settings.guard_enabled and guard.dry_run
    assert not g2.settings.guard_enabled
    g2_guard = await policy.ensure_guard(session, two)
    assert not g2_guard.enabled and not g2_guard.allowed_domains
    for field, value in [("require_subscription", True), ("require_counter", True),
                         ("warn_limit", 0), ("allowed_domains", "https://olx.uz/path"),
                         ("banned_words", "x" * 51)]:
        with pytest.raises(ValueError):
            await policy.edit_guard(session, g1, field, value, ADMIN_ID)
    for field, value in [("keep_last_ads", 0), ("delete_after_seconds", 36001)]:
        with pytest.raises(ValueError):
            await policy.edit_cleaner(session, g1, field, value, ADMIN_ID)
    assert (await session.execute(select(ActionLog).where(ActionLog.group_id == one))).scalars().all()


def test_classifier_whitelist_entities_and_overlap() -> None:
    guard = policy.safe_guard(1)
    guard.enabled, guard.allowed_domains = True, ["example.uz", "xn--d1acpjx3f.xn--p1ai"]
    cleaner = policy.safe_cleaner(1)
    cleaner.enabled, cleaner.delete_links = True, True

    def msg(text: str, entities=None) -> Message:
        return update(1, text, entities=entities).message

    assert policy.classify(msg("😀 https://m.example.uz/help"), guard, cleaner) is None
    assert policy.classify(msg("😀 https://example.uz.evil.net"), guard, cleaner).source == "guard"
    assert policy.classify(msg("t.me/x"), guard, cleaner).kind == "link"
    assert policy.classify(msg("😀 o‘tish", [MessageEntity(type="text_link", offset=3,
                                                          length=6, url="https://evil.uz")]),
                           guard, cleaner).kind == "link"
    # Guard dry-run; cleaner jonli bo'lsa ham o'sha xabarga cleaner sifatida qaramaydi.
    cleaner.dry_run = False
    assert policy.classify(msg("https://evil.uz"), guard, cleaner).source == "guard"
    assert policy.classify(msg("https://evil.uz"), guard, cleaner,
                           frozenset({PermissionKind.LINK_ALLOWED})) is None
    guard.banned_words = ["firib"]
    assert policy.classify(msg("X firib!"), guard, cleaner).kind == "banned_word"
    assert policy.classify(msg("firibchi"), guard, None) is None
    guard.forward_filter = True
    forwarded = update(2, "ok", forward_origin={"type": "hidden_user", "date": int(utcnow().timestamp()),
                                                  "sender_user_name": "abc"}).message
    assert policy.classify(forwarded, guard, None).kind == "forward"
    cleaner.delete_service = True
    service = update(3, None, video_chat_started=VideoChatStarted()).message
    assert policy.classify(service, guard, cleaner).kind == "service"


# ── Jonli xabarlar ──────────────────────────────────────────────
async def test_cleaner_uses_group_filters_without_enabling_guard(session, tg) -> None:
    fake, bot, dp = tg
    g1, g2 = await setup_group(session), await setup_group(session, chat_id=OTHER_CHAT_ID)
    await enable_cleaner(session, g1, dry_run=False, delete_links=False)
    await enable_cleaner(session, g2, dry_run=False, delete_links=False)
    first = await policy.ensure_cleaner(session, g1)
    second = await policy.ensure_cleaner(session, g2)
    first.delete_violations = second.delete_violations = True
    rules = await policy.ensure_guard(session, g1)
    rules.banned_words = ["aldov"]
    rules.allowed_domains = ["example.uz"]
    rules.link_filter = True
    await session.commit()
    # Global posbon o'chirilgan va ikkala guruhda ham posbon yoqilmagan.
    async with session.begin():
        await settings_service.set(session, "guard_enabled_global", False, updated_by=ADMIN_ID)
    await send(session, dp, bot, update(5, "aldov elon"))
    await send(session, dp, bot, update(5, "aldov elon", chat_id=OTHER_CHAT_ID, uid=6))
    await send(session, dp, bot, update(7, "https://example.uz/elon"))
    await send(session, dp, bot, update(8, "https://evil.uz/elon"))
    actions = (await session.execute(select(GroupMessageAction).order_by(GroupMessageAction.message_id))).scalars().all()
    assert [(a.message_id, a.group_id, a.source) for a in actions] == [
        (5, g1, "cleaner"), (8, g1, "cleaner"),
    ]
    assert len(fake.called("DeleteMessage")) == 2
    assert not fake.called("BanChatMember") and not fake.called("RestrictChatMember")


async def test_dry_run_dedup_and_per_group_message_key(session, tg) -> None:
    fake, bot, dp = tg
    g1, g2 = await setup_group(session), await setup_group(session, chat_id=OTHER_CHAT_ID)
    await enable_guard(session, g1)
    await enable_guard(session, g2)
    await send(session, dp, bot, update(9))
    await send(session, dp, bot, update(9, uid=10))  # Telegram qayta yetkazdi
    await send(session, dp, bot, update(9, chat_id=OTHER_CHAT_ID, uid=11))
    actions = (await session.execute(select(GroupMessageAction).order_by(GroupMessageAction.id))).scalars().all()
    violations = (await session.execute(select(Violation))).scalars().all()
    assert len(actions) == len(violations) == 2
    assert {a.group_id for a in actions} == {g1, g2}
    assert all(a.is_dry_run and a.status == "done" for a in actions)
    assert all(v.action == "logged" for v in violations)
    assert not fake.called("DeleteMessage")
    assert not (await session.execute(select(Warning))).scalars().all()


async def test_live_warn_mute_ban_are_group_scoped(session, tg) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable_guard(session, gid, dry_run=False, penalty=Penalty.BAN, warn_limit=2)
    for mid in range(101, 105):
        await send(session, dp, bot, update(mid))
    assert len(fake.called("DeleteMessage")) == 4
    assert len(fake.called("RestrictChatMember")) == 2
    assert len(fake.called("BanChatMember")) == 1
    assert (await session.get(Warning, (gid, USER_ID))).count == 4
    actions = (await session.execute(select(GroupMessageAction).order_by(GroupMessageAction.id))).scalars().all()
    assert [a.planned_action for a in actions] == ["warn", "mute", "mute", "ban"]
    assert all(a.status == "done" for a in actions)
    restrictions = (await session.execute(select(Restriction))).scalars().all()
    assert len(restrictions) == 3 and {r.kind for r in restrictions} == {"mute", "ban"}
    assert (await session.execute(select(CleanupLog))).scalars().all()


async def test_warn_default_never_bans_and_failure_does_not_count(session, tg) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable_guard(session, gid, dry_run=False, warn_limit=1)
    fake.errors["DeleteMessage"] = TelegramBadRequest(
        SendMessage(chat_id=GROUP_CHAT_ID, text="x"), "message can't be deleted",
    )
    await send(session, dp, bot, update(210))
    action = (await session.execute(select(GroupMessageAction))).scalar_one()
    assert action.status == "failed"
    assert not (await session.execute(select(Warning))).scalars().all()
    fake.errors.clear()
    await send(session, dp, bot, update(211))
    await send(session, dp, bot, update(212))
    assert (await session.get(Warning, (gid, USER_ID))).count == 2
    assert not fake.called("BanChatMember") and not fake.called("RestrictChatMember")


async def test_rights_lost_pauses_group_and_notifies_without_retries(session, tg) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable_guard(session, gid, dry_run=False)
    group = await group_service.get_group(session, gid)
    group.bot_rights = {"can_delete_messages": False, "can_restrict_members": True}
    await session.commit()
    await send(session, dp, bot, update(310))
    session.expire_all()
    group = await group_service.get_group(session, gid)
    assert not group.is_active and group.paused_reason == "no_rights"
    assert (await session.execute(select(GroupMessageAction))).scalar_one().status == "failed"
    assert not fake.called("DeleteMessage")
    assert any("huquqi" in t for t in fake.sent_texts())
    fake.reset()
    await send(session, dp, bot, update(311))
    assert not fake.called("DeleteMessage")


async def test_permission_ttl_group_and_admin_exemptions(session, tg) -> None:
    fake, bot, dp = tg
    g1, g2 = await setup_group(session), await setup_group(session, chat_id=OTHER_CHAT_ID)
    await enable_guard(session, g1, dry_run=False)
    await enable_guard(session, g2, dry_run=False)
    await policy.grant_permission(session, group_id=g1, user_id=USER_ID,
                                  kind=PermissionKind.LINK_ALLOWED, days=3,
                                  reason="Rasmiy do'kon", actor_id=ADMIN_ID)
    await session.commit()
    await send(session, dp, bot, update(402))
    assert not fake.called("DeleteMessage")
    await send(session, dp, bot, update(402, chat_id=OTHER_CHAT_ID, uid=403))
    assert len(fake.called("DeleteMessage")) == 1
    entry = (await session.execute(select(Permission))).scalar_one()
    entry.expires_at = utcnow() - timedelta(days=1)
    await session.commit()
    await send(session, dp, bot, update(404))
    assert len(fake.called("DeleteMessage")) == 2

    # Telegram adminiga dry-run ham, jonli jazo ham berilmaydi.
    fake.overrides["GetChatMember"] = bot_member(is_admin=True)
    await send(session, dp, bot, update(405))
    assert len(fake.called("DeleteMessage")) == 2
    assert (await session.execute(select(GroupMessageAction).where(
        GroupMessageAction.message_id == 405))).scalar_one().status == "skipped"


async def test_permission_unique_scope_revoke_and_expired_history(session) -> None:
    g1, g2 = await setup_group(session), await setup_group(session, chat_id=OTHER_CHAT_ID)
    args = dict(user_id=USER_ID, kind=PermissionKind.LINK_ALLOWED, days=3, actor_id=ADMIN_ID)
    first = await policy.grant_permission(session, group_id=g1, reason="Birinchi sabab", **args)
    original_id = first.id
    updated = await policy.grant_permission(session, group_id=g1, reason="Yangi sabab", **args)
    assert updated.id == original_id and updated.reason == "Yangi sabab"
    second = await policy.grant_permission(session, group_id=g2, reason="Ikkinchi guruh", **args)
    global_permission = await policy.grant_permission(
        session, group_id=None, reason="Global istisno", **args,
    )
    assert len({first.id, second.id, global_permission.id}) == 3
    # Bir xil aktiv ruxsatni boshqa worker bevosita kiritishga urinsa ham DB rad etadi.
    for scope in (g1, None):
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(Permission(
                    group_id=scope, user_id=USER_ID, kind=PermissionKind.LINK_ALLOWED,
                    reason="Dublikat", granted_by=ADMIN_ID, is_active=True,
                ))
                await session.flush()
    assert await policy.revoke_permission(session, first, ADMIN_ID)
    assert not await policy.revoke_permission(session, first, ADMIN_ID)
    renewed = await policy.grant_permission(session, group_id=g1, reason="Qayta ruxsat", **args)
    assert renewed.id != original_id
    renewed.expires_at = utcnow() - timedelta(days=1)
    await session.flush()
    fresh = await policy.grant_permission(session, group_id=g1, reason="Muddat o'tdi", **args)
    assert fresh.id not in {original_id, renewed.id}
    assert not first.is_active and not renewed.is_active and fresh.is_active
    assert second.is_active and global_permission.is_active
    assert len((await session.execute(select(Permission).where(
        Permission.group_id == g1,
    ))).scalars().all()) == 3


async def test_cleaner_delayed_claim_pinned_and_global_stop(session, tg) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable_cleaner(session, gid, dry_run=False, delay=30)
    await send(session, dp, bot, update(501))
    action = (await session.execute(select(GroupMessageAction))).scalar_one()
    action_id = action.id
    assert action.status == "pending" and action.source == "cleaner"
    assert not fake.called("DeleteMessage") and await claim_due_actions() == []
    action.due_at = utcnow() - timedelta(seconds=1)
    await session.commit()
    # Mahkamlangan xabarni birorta worker o'chirmaydi.
    fake.overrides["GetChat"] = SimpleNamespace(pinned_message=SimpleNamespace(message_id=501))
    assert await process_due_cleanup(bot) == 1
    session.expire_all()
    assert (await session.get(GroupMessageAction, action_id)).status == "skipped"
    assert not fake.called("DeleteMessage")
    assert await process_due_cleanup(bot) == 0

    fake.overrides.pop("GetChat")
    await send(session, dp, bot, update(502))
    pending = (await session.execute(select(GroupMessageAction).where(
        GroupMessageAction.message_id == 502))).scalar_one()
    pending_id = pending.id
    pending.due_at = utcnow() - timedelta(seconds=1)
    await session.commit()
    async with session.begin():
        await settings_service.set(session, "cleaner_enabled_global", False, updated_by=ADMIN_ID)
    assert await process_due_cleanup(bot) == 1
    session.expire_all()
    assert (await session.get(GroupMessageAction, pending_id)).status == "skipped"
    assert not fake.called("DeleteMessage")


async def test_cleaner_dry_run_and_guard_overlap(session, tg) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable_guard(session, gid)  # dry-run
    await enable_cleaner(session, gid, dry_run=False)
    await send(session, dp, bot, update(601))
    assert not fake.called("DeleteMessage")
    act = (await session.execute(select(GroupMessageAction))).scalar_one()
    assert act.source == "guard" and act.is_dry_run
    # Guard o'chsa, o'sha turdagi xabarni cleaner mustaqil o'chiradi.
    g = await session.get(GuardSetting, gid)
    g.enabled = False
    await session.commit()
    await send(session, dp, bot, update(602))
    assert len(fake.called("DeleteMessage")) == 1
    actions = (await session.execute(select(GroupMessageAction).order_by(GroupMessageAction.id))).scalars().all()
    assert actions[-1].source == "cleaner"


async def test_group_emergency_stop_during_api_check_skips_delete(session, tg, monkeypatch) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable_guard(session, gid, dry_run=False)

    async def switched_off(bot, chat_id, user_id):
        async with session_scope() as other:
            group = await other.get(Group, gid)
            group.is_active = False
            group.paused_reason = "manual"
        return False

    monkeypatch.setattr(handler_policy, "_is_group_admin", switched_off)
    await send(session, dp, bot, update(800))
    assert not fake.called("DeleteMessage")
    assert (await session.execute(select(GroupMessageAction))).scalar_one().status == "skipped"


async def test_uncached_global_kill_stops_deletion_before_api(session, tg, monkeypatch) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable_guard(session, gid, dry_run=False)
    assert await settings_service.is_feature_enabled("guard")  # keshni ataylab isitish

    async def switched_off(bot, chat_id, user_id):
        async with session_scope() as other:
            other.add(Setting(key="kill_switch", value=True, updated_by=ADMIN_ID))
        return False

    monkeypatch.setattr(handler_policy, "_is_group_admin", switched_off)
    await send(session, dp, bot, update(810))
    assert not fake.called("DeleteMessage")
    assert (await session.execute(select(GroupMessageAction))).scalar_one().status == "skipped"


async def test_expired_warning_window_restarts_and_local_admin_is_exempt(session, tg) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable_guard(session, gid, dry_run=False, penalty=Penalty.MUTE, warn_limit=2)
    session.add(Warning(group_id=gid, user_id=USER_ID, count=10,
                        last_at=utcnow() - timedelta(days=3)))
    await session.commit()
    await send(session, dp, bot, update(830))
    assert (await session.get(Warning, (gid, USER_ID))).count == 1
    assert not fake.called("RestrictChatMember")
    session.add(GroupAdmin(group_id=gid, user_id=USER_ID))
    await session.commit()
    await send(session, dp, bot, update(831))
    assert len(fake.called("DeleteMessage")) == 1
    assert not (await session.execute(select(GroupMessageAction).where(
        GroupMessageAction.message_id == 831))).scalars().all()


async def test_penalty_lowered_during_admin_check_skips_mute(session, tg, monkeypatch) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable_guard(session, gid, dry_run=False, penalty=Penalty.MUTE, warn_limit=1)
    checks = 0

    async def lower_penalty(bot, chat_id, user_id):
        nonlocal checks
        checks += 1
        if checks == 2:  # Delete'dan so'ng, sanctiondan oldin
            async with session_scope() as other:
                guard = await other.get(GuardSetting, gid)
                guard.penalty = Penalty.WARN
        return False

    monkeypatch.setattr(handler_policy, "_is_group_admin", lower_penalty)
    await send(session, dp, bot, update(840))
    assert checks == 2
    assert len(fake.called("DeleteMessage")) == 1
    assert not fake.called("RestrictChatMember")
    assert (await session.execute(select(GroupMessageAction))).scalar_one().status == "done"


async def test_cleaner_join_leave_is_separate_from_guard(session, tg) -> None:
    fake, bot, dp = tg
    gid = await setup_group(session)
    await enable_cleaner(session, gid, dry_run=False, delete_links=False)
    cleaner = await session.get(CleanerSetting, gid)
    cleaner.delete_join_leave = True
    await session.commit()
    await send(session, dp, bot, update(850, text=None,
                                       new_chat_members=[TgUser(id=989898, is_bot=False, first_name="New")]))
    assert len(fake.called("DeleteMessage")) == 1
    log = (await session.execute(select(CleanupLog))).scalar_one()
    assert log.kind == "join_leave" and log.deleted_count == 1
    assert not (await session.execute(select(Warning))).scalars().all()


async def test_scheduler_job_registered(session, tg) -> None:
    _, bot, _ = tg
    from app.config import get_settings

    scheduler = build_scheduler(get_settings(), bot)
    job = scheduler.get_job("group_cleanup")
    assert job is not None and job.func is not None
    scheduler.remove_all_jobs()
