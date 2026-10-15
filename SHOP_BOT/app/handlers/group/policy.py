"""Phase 6: posbon va tozalovchining bitta xabarga yagona qarori.

Telegram API'da idempotency key yo'q. DB rezervatsiya oldin commit qilinadi;
`running` holati noma'lum qolsa, avtomatik qayta bajarilmaydi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import ChatPermissions, Message
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import session_scope
from app.db.models import (
    Admin,
    CleanerSetting,
    CleanupLog,
    Group,
    GroupAdmin,
    GroupMessageAction,
    GuardSetting,
    Restriction,
    Violation,
    Warning,
)
from app.filters import GroupChat
from app.services import group_policy_service as policy
from app.services.group_service import get_group_by_chat_id, pause_group
from app.services.notify import notify_admins
from app.services.settings_service import settings_service
from app.utils.text import escape_html
from app.utils.time import utcnow

router = Router(name="group:policy")


@dataclass(frozen=True)
class _Ready:
    group_id: int
    chat_id: int
    message_id: int
    user_id: int | None
    source: str
    kind: str
    keep_pinned: bool
    exempt_admins: bool
    warn_window: int
    mute_minutes: int
    penalty: str
    warn_limit: int


async def _global_enabled(feature: str, *, fresh: bool = False) -> bool:
    if fresh:
        return await settings_service.is_feature_enabled_fresh(feature)
    return bool(await settings_service.is_feature_enabled(feature)) and not bool(
        await settings_service.get("maintenance_mode", False)
    )


async def _notify_failure(bot: Bot, group_id: int, message_id: int, reason: str) -> None:
    logger.warning("Xabar siyosati: guruh={} xabar={} {}", group_id, message_id, reason)
    try:
        await notify_admins(
            bot,
            f"⚠️ Guruh #{group_id}, xabar #{message_id}: posbon/tozalovchi amali "
            f"bajarilmadi. Sabab: {escape_html(reason[:160])}. Jurnalni tekshiring.",
        )
    except Exception as exc:  # xabar xatosi siyosat holatini yo'qotmasin
        logger.warning("Adminlarga siyosat xatosi yuborilmadi: {}", exc)


async def _finish(action_id: int, status: str, reason: str = "") -> None:
    async with session_scope() as session:
        row = await session.get(GroupMessageAction, action_id)
        if row is not None and row.status == "running":
            row.status = status
            row.error = reason[:500] or None


async def _failure(bot: Bot, action_id: int, reason: str, *, rights_lost: bool = False) -> None:
    async with session_scope() as session:
        row = await session.get(GroupMessageAction, action_id)
        if row is None:
            return
        row.status = "failed"
        row.error = reason[:500]
        if rights_lost:
            group = await session.get(Group, row.group_id)
            if group is not None and group.is_active:
                await pause_group(session, group, reason="no_rights")
        group_id, message_id = row.group_id, row.message_id
    await _notify_failure(bot, group_id, message_id, reason)


async def claim_due_actions(*, limit: int = 100) -> list[int]:
    """Atomar CAS: bir nechta poster worker kechiktirilgan delete'ni bo'lishmaydi."""
    async with session_scope() as session:
        due = (await session.execute(select(GroupMessageAction.id).where(
            GroupMessageAction.status == "pending", GroupMessageAction.due_at <= utcnow(),
        ).order_by(GroupMessageAction.due_at, GroupMessageAction.id).limit(limit))).scalars().all()
        claimed: list[int] = []
        for action_id in due:
            result = await session.execute(update(GroupMessageAction).where(
                GroupMessageAction.id == action_id, GroupMessageAction.status == "pending"
            ).values(status="running").returning(GroupMessageAction.id))
            if result.scalar_one_or_none() is not None:
                claimed.append(action_id)
    return claimed


async def process_due_cleanup(bot: Bot) -> int:
    ids = await claim_due_actions()
    for action_id in ids:
        try:
            await perform_action(bot, action_id)
        except Exception as exc:
            logger.exception("Kechiktirilgan tozalash #{} xatosi: {}", action_id, exc)
            await _failure(bot, action_id, f"{type(exc).__name__}: {exc}")
    return len(ids)


async def _prepare(bot: Bot, action_id: int) -> _Ready | None:
    """Har bir amal oldidan joriy guruh/policy/ruxsatni qayta tekshir."""
    notification: tuple[int, int, str] | None = None
    ready: _Ready | None = None
    async with session_scope() as session:
        row = await session.get(GroupMessageAction, action_id)
        if row is None or row.status != "running":
            return None
        group = await session.get(Group, row.group_id)
        guard = await session.get(GuardSetting, row.group_id) if row.source == "guard" else None
        cleaner = await session.get(CleanerSetting, row.group_id) if row.source == "cleaner" else None
        settings = group.settings if group else None
        active = bool(
            (guard and guard.enabled and settings and settings.guard_enabled) if guard else
            (cleaner and cleaner.enabled and settings and settings.cleaner_enabled)
        )
        if (not group or not settings or not group.is_active or not group.is_supergroup
                or not group.bot_is_admin or not active):
            row.status, row.error = "skipped", "Guruh yoki ushbu funksiya faol emas."
        elif (guard and guard.dry_run) or (cleaner and cleaner.dry_run):
            row.status, row.error = "skipped", "Siyosat dry-run rejimiga qaytarilgan."
        elif not (group.bot_rights or {}).get("can_delete_messages"):
            reason = "Botda xabarni o'chirish huquqi yo'q; guruh pauzaga olindi."
            row.status, row.error = "failed", reason
            await pause_group(session, group, reason="no_rights")
            notification = (group.id, row.message_id, reason)
        else:
            kinds = await policy.permission_kinds(session, row.user_id or 0, group.id)
            exempt = "full_exempt" in kinds or (
                "guard_exempt" in kinds if guard else "cleaner_exempt" in kinds
            ) or (row.kind == "link" and "link_allowed" in kinds)
            if exempt or row.user_id in get_settings().admin_ids:
                row.status, row.error = "skipped", "Foydalanuvchiga ruxsat/admin istisnosi."
            else:
                admin_id = (await session.execute(select(Admin.id).where(
                    Admin.user_id == row.user_id, Admin.is_active.is_(True)
                ))).scalar_one_or_none()
                local_admin = (await session.execute(select(GroupAdmin.id).where(
                    GroupAdmin.user_id == row.user_id, GroupAdmin.group_id == group.id
                ))).scalar_one_or_none()
                if admin_id or local_admin:
                    row.status, row.error = "skipped", "Bot/guruh admini istisno."
                else:
                    pinned_policy = cleaner or await session.get(CleanerSetting, group.id)
                    ready = _Ready(
                        group_id=group.id, chat_id=group.tg_chat_id,
                        message_id=row.message_id, user_id=row.user_id,
                        source=row.source, kind=row.kind,
                        keep_pinned=pinned_policy.keep_pinned if pinned_policy else True,
                        exempt_admins=guard.exemption_for_admins if guard else True,
                        warn_window=int((guard.escalate or {}).get("warn_window_hours", 24)) if guard else 24,
                        mute_minutes=int(guard.mute_minutes or 10) if guard else 10,
                        penalty=guard.penalty if guard else "warn",
                        warn_limit=int(guard.warn_limit or 3) if guard else 3,
                    )
    if notification:
        await _notify_failure(bot, *notification)
    return ready


async def _is_group_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    # Telegram'ning joriy roli; xatoda fail-open (amal qilinmaydi).
    member = await bot.get_chat_member(chat_id, user_id)
    return str(member.status) in {"creator", "administrator"}


async def _warning_and_log(action_id: int, ready: _Ready, group_admin: bool) -> tuple[int, str]:
    """Faqat muvaffaqiyatli delete'dan keyin ogohlantirish hisobini oshir."""
    async with session_scope() as session:
        row = await session.get(GroupMessageAction, action_id)
        if row is None:
            return 0, "cancelled"
        session.add(CleanupLog(
            group_id=ready.group_id,
            kind="violation" if ready.source == "guard" else (
                ready.kind if ready.kind in {"join_leave", "service", "link"} else "violation"
            ),
            deleted_count=1, details={"message_id": ready.message_id},
        ))
        if row.status != "running":  # admin API paytida bekor qilgan bo'lishi mumkin
            return 0, "cancelled"
        if ready.source == "cleaner":
            row.status = "done"
            return 0, "warn"
        violation = (await session.execute(select(Violation).where(
            Violation.group_id == ready.group_id, Violation.message_id == ready.message_id
        ))).scalars().first()
        if violation:
            violation.action = "delete"
        count = await policy.increment_warning(
            session, group_id=ready.group_id, user_id=ready.user_id,
            window_hours=ready.warn_window,
        ) if ready.user_id else 0
        guard = await session.get(GuardSetting, ready.group_id)
        current = policy.consequence(guard, count) if guard and count else "warn"
        original = policy.consequence_values(ready.penalty, ready.warn_limit, count)
        # Delete paytida qoidalar almashsa, eski xabarni kuchliroq jazolamaymiz.
        outcome = min((current, original), key={"warn": 0, "mute": 1, "ban": 2}.get)
        if group_admin:  # admin istisnosi o'chirilganda ham mute/ban QILMAYMIZ
            outcome = "warn"
        row.planned_action = outcome
        if outcome == "warn":
            row.status = "done"
            if violation:
                violation.action = "warn"
        return count, outcome


async def _sanction_still_allowed(ready: _Ready, action_id: int) -> int | None:
    """Pauza/yangi ruxsat/jazo darajasi o'zgarsa ban/mute'ni bekor qil."""
    async with session_scope() as session:
        row = await session.get(GroupMessageAction, action_id)
        group = await session.get(Group, ready.group_id)
        guard = await session.get(GuardSetting, ready.group_id)
        kinds = await policy.permission_kinds(session, ready.user_id or 0, ready.group_id)
        admin_id = (await session.execute(select(Admin.id).where(
            Admin.user_id == ready.user_id, Admin.is_active.is_(True)
        ))).scalar_one_or_none()
        local_admin = (await session.execute(select(GroupAdmin.id).where(
            GroupAdmin.user_id == ready.user_id, GroupAdmin.group_id == ready.group_id
        ))).scalar_one_or_none()
        warning = await session.get(Warning, (ready.group_id, ready.user_id))
        fresh_outcome = policy.consequence(guard, warning.count) if guard and warning else "warn"
        severity = {"warn": 0, "mute": 1, "ban": 2}
        allowed = bool(
            row and row.status == "running" and group and group.is_active and group.bot_is_admin
            and group.settings and group.settings.guard_enabled and guard and guard.enabled
            and not guard.dry_run and "full_exempt" not in kinds and "guard_exempt" not in kinds
            and not (ready.kind == "link" and "link_allowed" in kinds)
            and not admin_id and not local_admin and ready.user_id not in get_settings().admin_ids
            and (group.bot_rights or {}).get("can_restrict_members")
            and severity[fresh_outcome] >= severity.get(row.planned_action, 99)
        )
        if not allowed and row and row.status == "running":
            row.status, row.error = "done", "Jazo oldidan pauza/ruxsat/huquq o'zgardi; faqat delete."
        return min(ready.mute_minutes, int(guard.mute_minutes or 10)) if allowed else None


async def perform_action(bot: Bot, action_id: int) -> None:
    """DB rezervatsiyasidan so'ng API; shubhali/ikkilangan holatda hech narsa qilma."""
    ready = await _prepare(bot, action_id)
    if ready is None:
        return
    if not await _global_enabled(ready.source):
        await _finish(action_id, "skipped", "Global switch yoki texnik rejim o'chirilgan.")
        return
    group_admin = False
    if ready.user_id:
        try:
            group_admin = await _is_group_admin(bot, ready.chat_id, ready.user_id)
        except TelegramAPIError as exc:
            await _failure(bot, action_id, f"Guruh adminini tekshirib bo'lmadi: {exc}")
            return
        if group_admin and ready.exempt_admins:
            await _finish(action_id, "skipped", "Guruh admini istisno.")
            return
    if ready.keep_pinned:
        try:
            pinned = getattr(await bot.get_chat(ready.chat_id), "pinned_message", None)
        except TelegramAPIError as exc:
            await _failure(bot, action_id, f"Mahkamlangan xabarni tekshirib bo'lmadi: {exc}")
            return
        if pinned is not None and pinned.message_id == ready.message_id:
            await _finish(action_id, "skipped", "Mahkamlangan xabar saqlanadi.")
            return
    # GetChat/GetChatMember tarmoq kutishida admin guruh pauzasini, ruxsatni
    # yoki dry-run'ni o'zgartirgan bo'lishi mumkin. API oldidan yana tekshir.
    fresh = await _prepare(bot, action_id)
    if fresh is None:
        return
    if group_admin and fresh.exempt_admins:
        await _finish(action_id, "skipped", "Admin istisnosi yoqildi.")
        return
    if fresh.keep_pinned and not ready.keep_pinned:
        try:
            pinned = getattr(await bot.get_chat(fresh.chat_id), "pinned_message", None)
        except TelegramAPIError as exc:
            await _failure(bot, action_id, f"Mahkamlangan xabarni tekshirib bo'lmadi: {exc}")
            return
        if pinned is not None and pinned.message_id == fresh.message_id:
            await _finish(action_id, "skipped", "Mahkamlangan xabar saqlanadi.")
            return
    ready = fresh
    if not await _global_enabled(ready.source, fresh=True):
        await _finish(action_id, "skipped", "Global pauza yoqildi.")
        return
    try:
        await bot.delete_message(ready.chat_id, ready.message_id)
    except TelegramAPIError as exc:
        await _failure(
            bot, action_id, f"Xabarni o'chirib bo'lmadi: {exc}",
            rights_lost=isinstance(exc, TelegramForbiddenError),
        )
        return

    count, outcome = await _warning_and_log(action_id, ready, group_admin)
    if ready.source == "cleaner" or outcome == "cancelled":
        return
    if outcome == "warn":
        if ready.user_id:
            try:
                await bot.send_message(
                    ready.user_id,
                    f"⚠️ Guruhdagi xabaringiz qoida ({escape_html(ready.kind)}) sababli o'chirildi. "
                    f"Ogohlantirish: {count}. Guruh adminiga murojaat qilishingiz mumkin.",
                )
            except TelegramAPIError:
                pass  # /start bosmagan a'zoga DM imkonsiz bo'lishi mumkin
        return

    mute_minutes = await _sanction_still_allowed(ready, action_id)
    if mute_minutes is None or not await _global_enabled("guard", fresh=True):
        await _finish(action_id, "done", "Jazo oldidan global/guruh pauzasi yoqildi.")
        return
    # Admin roli delete vaqtida o'zgargan bo'lsa ham unga jazo bermaymiz.
    try:
        if ready.user_id and await _is_group_admin(bot, ready.chat_id, ready.user_id):
            await _finish(action_id, "done", "Foydalanuvchi admin bo'ldi; jazo bekor.")
            return
    except TelegramAPIError as exc:
        await _failure(bot, action_id, f"Jazodan oldin adminni tekshirib bo'lmadi: {exc}")
        return
    mute_minutes = await _sanction_still_allowed(ready, action_id)
    if mute_minutes is None or not await _global_enabled("guard", fresh=True):
        await _finish(action_id, "done", "Jazodan oldin pauza/ruxsat o'zgardi.")
        return

    until = utcnow() + timedelta(minutes=mute_minutes) if outcome == "mute" else None
    try:
        if outcome == "mute":
            await bot.restrict_chat_member(
                ready.chat_id, ready.user_id,
                permissions=ChatPermissions(can_send_messages=False), until_date=until,
            )
        else:
            await bot.ban_chat_member(ready.chat_id, ready.user_id)
    except TelegramAPIError as exc:
        await _failure(
            bot, action_id, f"Xabar o'chdi, {outcome} berilmadi: {exc}",
            rights_lost=isinstance(exc, TelegramForbiddenError),
        )
        return
    async with session_scope() as session:
        row = await session.get(GroupMessageAction, action_id)
        if row is None:
            return
        row.status = "done"
        violation = (await session.execute(select(Violation).where(
            Violation.group_id == ready.group_id, Violation.message_id == ready.message_id
        ))).scalars().first()
        if violation:
            violation.action, violation.penalty_until = outcome, until
        session.add(Restriction(
            group_id=ready.group_id, user_id=ready.user_id, kind=outcome,
            until_at=until, reason=f"{ready.kind} (xabar #{ready.message_id})", is_active=True,
        ))


@router.message(GroupChat())
async def on_group_message(
    message: Message, session: AsyncSession, bot: Bot, is_admin: bool | None = None,
) -> None:
    # Anonymous admin/sender_chat va botlar: yozuvchining shaxsi aniq emas.
    if (message.sender_chat is not None or message.from_user is None or message.from_user.is_bot
            or is_admin or message.from_user.id in get_settings().admin_ids):
        return
    guard_global = await _global_enabled("guard")
    cleaner_global = await _global_enabled("cleaner")
    if not guard_global and not cleaner_global:
        return
    group = await get_group_by_chat_id(session, message.chat.id)
    if group is None or not group.is_supergroup or not group.bot_is_admin or not group.is_active or group.settings is None:
        return
    guard = await session.get(GuardSetting, group.id) if guard_global and group.settings.guard_enabled else None
    cleaner = await session.get(CleanerSetting, group.id) if cleaner_global and group.settings.cleaner_enabled else None
    if guard is None and cleaner is None:
        return
    # Cleanerning «qoidabuzar xabar» filtri posbonni jonli yoqishni talab qilmaydi;
    # guard siyosatidan faqat namunaviy filtr/whitelist ma'lumotini oladi.
    reference = (await session.get(GuardSetting, group.id)
                 if cleaner and (cleaner.delete_violations or cleaner.delete_links) and guard is None else guard)
    kinds = await policy.permission_kinds(session, message.from_user.id, group.id)
    match = policy.classify(message, guard, cleaner, kinds, violation_guard=reference)
    if match is None:
        return
    # Guruh moderatorlari Telegram admin maqomisiz ham bazada tayinlanishi mumkin.
    local_admin = (await session.execute(select(GroupAdmin.id).where(
        GroupAdmin.group_id == group.id, GroupAdmin.user_id == message.from_user.id
    ))).scalar_one_or_none()
    if local_admin:
        return
    selected = guard if match.source == "guard" else cleaner
    dry_run = bool(selected.dry_run)
    # Dry-run ham guruh adminlarini qoidabuzar deb qayd etmasin.
    if dry_run and (match.source == "cleaner" or guard.exemption_for_admins):
        try:
            if await _is_group_admin(bot, group.tg_chat_id, message.from_user.id):
                return
        except TelegramAPIError:
            return
    delay = int(cleaner.delete_after_seconds or 0) if match.source == "cleaner" and cleaner else 0
    due_at = utcnow() + timedelta(seconds=delay) if delay and not dry_run else None
    action = await policy.reserve_action(
        session, group_id=group.id, message_id=message.message_id, user_id=message.from_user.id,
        match=match, dry_run=dry_run, due_at=due_at,
        text_excerpt=message.text or message.caption,
    )
    if action is None:
        return
    action_id = action.id
    if dry_run and match.source == "cleaner":
        session.add(CleanupLog(
            group_id=group.id,
            kind=match.kind if match.kind in {"join_leave", "service", "link"} else "violation",
            deleted_count=0, details={"dry_run": True, "message_id": message.message_id},
        ))
    await session.commit()  # API'dan oldin yagona DB rezervatsiya
    if dry_run or due_at is not None:
        return
    try:
        await perform_action(bot, action_id)
    except Exception as exc:  # API/DB xatosi hech qachon jazo sifatida qaytarilmasin
        logger.exception("Xabar siyosati #{} xatosi: {}", action_id, exc)
        await _failure(bot, action_id, f"{type(exc).__name__}: {exc}")


__all__ = ["router", "claim_due_actions", "process_due_cleanup", "perform_action"]
