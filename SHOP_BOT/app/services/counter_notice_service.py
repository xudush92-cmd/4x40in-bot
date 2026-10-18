"""Sanoqchi cheklovining guruhdagi qisqa izohi va uni DB navbati orqali o'chirish.

Telegram sendMessage idempotent emas: jo'natish paytida process to'xtasa xabar ID'si
bazaga yozilmay qolishi mumkin. Oddiy restartda saqlangan navbat qayta ishlaydi.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from loguru import logger
from sqlalchemy import and_, or_, select, update

from app.config import get_settings
from app.constants import PermissionKind
from app.db.base import session_scope
from app.db.models import Admin, CounterSetting, Group, GroupAdmin, GroupMessageAction
from app.services import counter_service as counters
from app.services import group_policy_service as policy
from app.services.settings_service import settings_service
from app.utils.time import ensure_aware, utcnow

NOTICE_SOURCE = "counter_notice"
NOTICE_SECONDS = 15
COOLDOWN_SECONDS = 60
_RETRY_SECONDS = 30
_STALE_SECONDS = 45


async def _reserve(group_id: int, user_id: int, issue: str) -> tuple[int, int] | None:
    """Guruh qatori qulfida har a'zoga 60 sekundda ko'pi bilan bir ogohlantirish."""
    if (user_id <= 0 or issue != "counter_not_done"
            or not await settings_service.is_feature_enabled_fresh("counter")):
        return None
    async with session_scope() as session:
        group = (await session.execute(select(Group).where(Group.id == group_id)
                                       .with_for_update())).scalar_one_or_none()
        setting = await session.get(CounterSetting, group_id)
        if not (group and group.is_supergroup and group.is_active and group.bot_is_admin
                and group.settings and group.settings.counter_enabled
                and (group.bot_rights or {}).get("can_delete_messages")
                and setting and setting.enabled and not setting.dry_run):
            return None
        if issue == "counter_not_done" and (setting.required_n <= 0 or
                                            await counters.total_for(session, group_id, user_id)
                                            >= setting.required_n):
            return None  # xabar o'chgach orada hisob bajarilgan bo'lishi mumkin
        if user_id in get_settings().admin_ids:
            return None
        kinds = await policy.permission_kinds(session, user_id, group_id)
        if (PermissionKind.FULL_EXEMPT in kinds or
                (issue == "counter_not_done" and PermissionKind.COUNTER_EXEMPT in kinds)):
            return None
        admin = (await session.execute(select(Admin.id).where(
            Admin.user_id == user_id, Admin.is_active.is_(True),
        ))).scalar_one_or_none()
        local = (await session.execute(select(GroupAdmin.id).where(
            GroupAdmin.group_id == group_id, GroupAdmin.user_id == user_id,
        ))).scalar_one_or_none()
        if admin or local or await counters.paid_for_group(session, group_id, user_id):
            return None
        recent = (await session.execute(select(GroupMessageAction.id).where(
            GroupMessageAction.group_id == group_id,
            GroupMessageAction.user_id == user_id,
            GroupMessageAction.source == NOTICE_SOURCE,
            or_(GroupMessageAction.created_at >= utcnow() - timedelta(seconds=COOLDOWN_SECONDS),
                GroupMessageAction.status.in_({"pending", "running"}),
                and_(GroupMessageAction.status == "sending",
                     GroupMessageAction.updated_at >= utcnow() - timedelta(minutes=5))),
        ).limit(1))).first()
        if recent:
            return None
        # Telegram ID'lari musbat; jo'natishdan oldin noma'lum ID'ni manfiy
        # rezervatsiya bilan band qilamiz. Qulf parallel worker'larni ajratadi.
        row = GroupMessageAction(
            group_id=group_id, user_id=user_id, message_id=-secrets.randbits(62) - 1,
            source=NOTICE_SOURCE, kind=issue, planned_action="delete", status="sending",
        )
        session.add(row)
        await session.flush()
        return row.id, group.tg_chat_id


def _text(issue: str) -> str:
    # Guruh a'zosi bot menyusidan foydalanishi shart emas. Raqam, havola,
    # shaxsiy hisob va ortiqcha tugmalarni ommaviy xabarda ko'rsatmaymiz.
    if issue == "counter_not_done":
        return "Guruhga yozish uchun odam qo‘shing."
    raise ValueError("Faqat shu guruhga odam qo'shish ogohlantirishi mavjud.")


async def send_notice(bot: Bot, *, group_id: int, user_id: int, issue: str) -> None:
    """Faqat muvaffaqiyatli delete/mute'dan keyin chaqiriladi; xato jazoni buzmaydi."""
    sent_id: int | None = None
    chat_id: int | None = None
    action_id: int | None = None
    try:
        reserved = await _reserve(group_id, user_id, issue)
        if reserved is None:
            return
        action_id, chat_id = reserved
        # DB rezervatsiyasidan so'ng ham global favqulodda switchni tekshir.
        if not await settings_service.is_feature_enabled_fresh("counter"):
            async with session_scope() as session:
                row = await session.get(GroupMessageAction, action_id)
                if row is not None and row.status == "sending":
                    row.status, row.error = "skipped", "Global sanoqchi pauzaga olingan."
            return
        try:
            sent = await bot.send_message(
                chat_id, _text(issue), parse_mode=None, disable_notification=True,
            )
        except TelegramAPIError as exc:
            async with session_scope() as session:
                row = await session.get(GroupMessageAction, action_id)
                if row is not None and row.status == "sending":
                    row.status, row.error = "failed", str(exc)[:500]
            logger.warning("Sanoqchi guruh izohi yuborilmadi #{}:{}: {}", group_id, user_id, exc)
            return
        sent_id = sent.message_id
        async with session_scope() as session:
            row = await session.get(GroupMessageAction, action_id)
            if row is None or row.status != "sending":
                raise RuntimeError("Sanoqchi izohi navbatga qo'yilmadi")
            row.message_id = sent_id
            row.due_at = utcnow() + timedelta(seconds=NOTICE_SECONDS)
            row.status = "pending"
    except Exception as exc:
        logger.exception("Sanoqchi guruh izohi #{}:{}: {}", group_id, user_id, exc)
        if sent_id is not None and chat_id is not None:
            # DB saqlay olmasa, muddatsiz qolishidan ko'ra hoziroq o'chiramiz.
            try:
                await bot.delete_message(chat_id, sent_id)
            except TelegramAPIError as delete_exc:
                logger.warning("Saqlanmagan sanoqchi izohini o'chirib bo'lmadi: {}", delete_exc)
        if action_id is not None:
            try:
                async with session_scope() as session:
                    row = await session.get(GroupMessageAction, action_id)
                    if row is not None and row.status == "sending":
                        row.status, row.error = "failed", str(exc)[:500]
            except Exception:
                logger.exception("Sanoqchi izohi rezervatsiyasini yopib bo'lmadi")


async def claim_due_notices(*, limit: int = 100) -> list[int]:
    """CAS: parallel posterlar va restartdan qolgan running delete'larni ajratadi."""
    now = utcnow()
    stale = now - timedelta(seconds=_STALE_SECONDS)
    eligible = or_(
        GroupMessageAction.status == "pending",
        and_(GroupMessageAction.status == "running", GroupMessageAction.updated_at < stale),
    )
    async with session_scope() as session:
        ids = (await session.execute(select(GroupMessageAction.id).where(
            GroupMessageAction.source == NOTICE_SOURCE,
            GroupMessageAction.due_at <= now, eligible,
        ).order_by(GroupMessageAction.due_at, GroupMessageAction.id).limit(limit))).scalars().all()
        claimed: list[int] = []
        for action_id in ids:
            result = await session.execute(update(GroupMessageAction).where(
                GroupMessageAction.id == action_id, GroupMessageAction.source == NOTICE_SOURCE,
                GroupMessageAction.due_at <= now, eligible,
            ).values(status="running", updated_at=now).returning(GroupMessageAction.id))
            if result.scalar_one_or_none() is not None:
                claimed.append(action_id)
        return claimed


async def process_due_notices(bot: Bot) -> int:
    """Botning o'z izohini qoidadan mustaqil o'chir: switch o'chsa ham xabar qolmasin."""
    ids = await claim_due_notices()
    for action_id in ids:
        try:
            async with session_scope() as session:
                row = await session.get(GroupMessageAction, action_id)
                if row is None or row.source != NOTICE_SOURCE or row.status != "running":
                    continue
                group = await session.get(Group, row.group_id)
                if group is None:
                    row.status, row.error = "failed", "Guruh topilmadi."
                    continue
                chat_id, message_id = group.tg_chat_id, row.message_id
            status, error, retry_at = "done", None, None
            try:
                await bot.delete_message(chat_id, message_id)
            except TelegramBadRequest as exc:
                # Delete amalga oshib, worker javobni yozmasdan yiqilgan bo'lishi mumkin.
                if "message to delete not found" not in str(exc).lower():
                    status, error = "failed", str(exc)[:500]
            except (TelegramNetworkError, TelegramRetryAfter) as exc:
                async with session_scope() as session:
                    row = await session.get(GroupMessageAction, action_id)
                    old = row is not None and ensure_aware(row.created_at) < utcnow() - timedelta(days=1)
                status = "failed" if old else "pending"
                error = str(exc)[:500]
                retry_at = utcnow() + timedelta(seconds=max(
                    _RETRY_SECONDS, getattr(exc, "retry_after", 0) + 1,
                ))
            except TelegramAPIError as exc:
                status, error = "failed", str(exc)[:500]
            async with session_scope() as session:
                row = await session.get(GroupMessageAction, action_id)
                if row is not None and row.status == "running" and row.source == NOTICE_SOURCE:
                    row.status, row.error = status, error
                    if status == "pending":
                        row.due_at = retry_at
            if status == "failed":
                logger.warning("Sanoqchi izohi 15s da o'chirilmadi #{}: {}", action_id, error)
        except Exception as exc:
            # running 45s dan keyin yana olinadi; bir xato qolganlarini to'xtatmaydi.
            logger.exception("Sanoqchi izohi delete #{}: {}", action_id, exc)
    return len(ids)
