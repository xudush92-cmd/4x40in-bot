"""Guruh bilan ishlash servisi.

Phase 0: guruh yozuvini yaratish/yangilash, huquqlar, pauza.
Phase 1: ro'yxat, sozlamalar, funksiya tumbleri, huquqni tekshirish, o'chirish.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aiogram import Bot
from aiogram.types import Chat, ChatMemberAdministrator, ChatMemberUpdated
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    FEATURE_LABELS,
    GroupFeature,
    MAX_DAILY_POST_LIMIT,
    MAX_INTERVAL_SEC,
    MAX_JITTER_PERCENT,
    MIN_INTERVAL_SEC,
    MIN_JITTER_PERCENT,
)
from app.db.models import Ad, Category, Group, GroupRotation, GroupSettings
from app.utils.text import clamp
from app.utils.time import next_run_time, utcnow

# Bot uchun majburiy admin huquqlari (REJA.md 1 — Guruhlar)
REQUIRED_RIGHTS: dict[str, str] = {
    "can_delete_messages": "Xabarlarni o'chirish",
    "can_restrict_members": "A'zolarni cheklash (mute/ban)",
    "can_invite_users": "Taklif havolalari yaratish",
}

OPTIONAL_RIGHTS: dict[str, str] = {
    "can_pin_messages": "Xabarlarni qadash",
    "can_change_info": "Guruh ma'lumotlarini o'zgartirish",
}

# Funksiya → GroupSettings ustuni
FEATURE_COLUMN: dict[str, str] = {
    GroupFeature.POSTING: "posting_enabled",
    GroupFeature.COUNTER: "counter_enabled",
    GroupFeature.GUARD: "guard_enabled",
    GroupFeature.CLEANER: "cleaner_enabled",
    GroupFeature.WELCOME: "welcome_enabled",
}


# ─────────────────────────── Huquqlar ──────────────────────────────
def extract_rights(member: Any) -> dict[str, bool]:
    """ChatMemberAdministrator obyektidan huquqlar lug'atini olish."""
    if isinstance(member, ChatMemberAdministrator):
        return {key: bool(getattr(member, key, False)) for key in (*REQUIRED_RIGHTS, *OPTIONAL_RIGHTS)}
    return {key: False for key in (*REQUIRED_RIGHTS, *OPTIONAL_RIGHTS)}


def missing_rights(rights: dict[str, bool]) -> list[str]:
    """Yetishmayotgan majburiy huquqlar (o'qishga qulay nomlar bilan)."""
    return [REQUIRED_RIGHTS[key] for key in REQUIRED_RIGHTS if not rights.get(key)]


@dataclass
class RightsCheck:
    """Guruh huquqlarini tekshirish natijasi."""

    ok: bool = False                     # bot admin va huquqlar yetarli
    is_admin: bool = False
    status: str | None = None
    missing: list[str] = field(default_factory=list)
    member_count: int | None = None
    rights: dict[str, bool] = field(default_factory=dict)
    error: str | None = None             # Telegram xatosi (guruh o'chirilgan va h.k.)

    @property
    def summary(self) -> str:
        if self.error:
            return f"❌ Xato: {self.error[:120]}"
        if not self.is_admin:
            return "❌ Bot bu guruhda admin emas"
        if self.missing:
            return "⚠️ Yetishmayotgan huquqlar: " + ", ".join(self.missing)
        return "✅ Barcha huquqlar joyida"


async def check_group_rights(bot: Bot, group: Group) -> RightsCheck:
    """Telegram'dan guruh va bot huquqlarini tekshirish (DB'ga yozmaydi)."""
    result = RightsCheck()
    try:
        member = await bot.get_chat_member(group.tg_chat_id, bot.id)
    except Exception as exc:  # guruh o'chirilgan / bot chiqarilgan
        result.error = str(exc)
        return result

    result.status = getattr(member, "status", None)
    result.is_admin = result.status in ("administrator", "creator")
    result.rights = extract_rights(member)
    result.missing = missing_rights(result.rights) if result.is_admin else []
    result.ok = result.is_admin and not result.missing

    try:
        result.member_count = await bot.get_chat_member_count(group.tg_chat_id)
    except Exception:  # pragma: no cover
        result.member_count = None

    return result


async def apply_rights_check(
    session: AsyncSession,
    bot: Bot,
    group: Group,
    result: RightsCheck,
    *,
    notify: bool = True,
) -> bool:
    """Tekshiruv natijasini bazaga yozish; muammo bo'lsa guruhni pauza qilish.

    Qaytaradi: guruh holati yaxshimi (ok).
    """
    group.bot_is_admin = result.is_admin
    group.bot_rights = result.rights or None
    group.last_checked_at = utcnow()
    if result.member_count is not None:
        group.member_count = result.member_count

    if result.ok:
        group.last_error = None
        return True

    # Muammo: xato yoki admin emas
    reason = "chat_not_found" if result.error else "no_rights"
    group.last_error = (result.error or result.summary)[:500]

    if group.is_active:
        await pause_group(session, group, reason=reason)
        if notify:
            await _notify_group_problem(bot, group, result, session)

    return False


async def _notify_group_problem(
    bot: Bot, group: Group, result: RightsCheck, session: AsyncSession
) -> None:
    from app.services.notify import notify_admins

    if result.error:
        text = (
            f"⚠️ <b>{group.display}</b> guruhi tekshirilmadi.\n"
            f"Sabab: <code>{result.error[:200]}</code>\n"
            "Guruh o'chirilgan yoki bot chiqarilgan bo'lishi mumkin. Joylash to'xtatildi."
        )
    elif not result.is_admin:
        text = (
            f"⚠️ <b>{group.display}</b> guruhida bot endi admin emas.\n"
            "E'lon joylash to'xtatildi. Iltimos, admin huquqini qayta bering."
        )
    else:
        text = (
            f"⚠️ <b>{group.display}</b> guruhida huquqlar yetishmayapti:\n"
            f"{', '.join(result.missing)}\n\n"
            "Iltimos, guruh sozlamalarida botga shu huquqlarni bering."
        )

    await notify_admins(bot, text, session=session)


# ─────────────────────── Guruhni olish / yaratish ──────────────────
async def get_group(session: AsyncSession, group_id: int) -> Group | None:
    return (await session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()


async def get_group_by_chat_id(session: AsyncSession, tg_chat_id: int) -> Group | None:
    return (
        await session.execute(select(Group).where(Group.tg_chat_id == tg_chat_id))
    ).scalar_one_or_none()


async def get_or_create_group(
    session: AsyncSession,
    chat: Chat,
    *,
    added_by: int | None = None,
) -> Group:
    """Guruh yozuvini topish yoki yaratish (+ settings/rotation qatorlari)."""
    group = await get_group_by_chat_id(session, chat.id)

    if group is None:
        group = Group(
            tg_chat_id=chat.id,
            title=chat.title,
            username=chat.username,
            chat_type=chat.type,
            is_supergroup=chat.type == "supergroup",
            added_by=added_by,
            is_active=True,
        )
        # Bog'liq yozuvlarni obyekt sifatida biriktiramiz: shunda async
        # kontekstda lazy-load (MissingGreenlet xatosi) bo'lmaydi.
        group.settings = GroupSettings()
        group.rotation = GroupRotation()
        session.add(group)
        await session.flush()
        logger.info("Yangi guruh qo'shildi: {} ({})", chat.title, chat.id)
    else:
        group.title = chat.title
        group.username = chat.username
        group.chat_type = chat.type
        group.is_supergroup = chat.type == "supergroup"

    return group


async def sync_bot_status(
    session: AsyncSession,
    event: ChatMemberUpdated,
) -> tuple[Group, list[str]]:
    """`my_chat_member` update'i bo'yicha guruh holatini yangilash.

    Qaytaradi: (guruh, yetishmayotgan huquqlar ro'yxati)
    """
    chat = event.chat
    group = await get_or_create_group(session, chat, added_by=event.from_user.id)

    status = event.new_chat_member.status
    is_admin = status == "administrator"

    group.bot_is_admin = is_admin
    group.bot_rights = extract_rights(event.new_chat_member)
    group.last_checked_at = utcnow()

    missing: list[str] = []
    if is_admin:
        missing = missing_rights(group.bot_rights or {})
        group.is_active = True
        group.paused_reason = None
        group.last_error = "Yetishmayotgan huquqlar: " + ", ".join(missing) if missing else None
    else:
        group.last_error = "Bot guruhda admin emas"

    return group, missing


# ─────────────────────── Ro'yxat va statistika ─────────────────────
async def count_groups(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(Group))).scalar_one())


async def list_groups(session: AsyncSession, *, offset: int = 0, limit: int = 6) -> list[Group]:
    """Guruhlar ro'yxati (yangi qo'shilganlar yuqorida)."""
    return list(
        (
            await session.execute(
                select(Group).order_by(Group.is_active.desc(), Group.id.desc()).offset(offset).limit(limit)
            )
        ).scalars().all()
    )


async def get_group_stats(session: AsyncSession, group: Group) -> dict[str, int]:
    """Guruh bo'yicha jamlanma: toifalar va e'lonlar soni."""
    categories = int(
        (
            await session.execute(
                select(func.count()).select_from(Category).where(Category.group_id == group.id)
            )
        ).scalar_one()
    )
    ads = int(
        (
            await session.execute(
                select(func.count()).select_from(Ad).where(Ad.group_id == group.id)
            )
        ).scalar_one()
    )
    return {"categories": categories, "ads": ads}


async def count_groups_by_status(session: AsyncSession) -> tuple[int, int]:
    """(faol, pauzada) guruhlar soni."""
    active = int(
        (
            await session.execute(
                select(func.count()).select_from(Group).where(Group.is_active.is_(True))
            )
        ).scalar_one()
    )
    total = await count_groups(session)
    return active, total - active


# ─────────────────────────── Sozlamalar ────────────────────────────
async def recompute_next_post(session: AsyncSession, group: Group, *, delay_min_sec: int | None = None) -> None:
    """Keyingi joylash vaqtini guruh sozlamalari asosida hisoblash."""
    rotation = group.rotation
    if rotation is None:
        return

    settings = group.settings
    if settings is None or not settings.posting_enabled or not group.is_active:
        rotation.next_post_at = None
        return

    minimum = delay_min_sec if delay_min_sec is not None else MIN_INTERVAL_SEC
    rotation.next_post_at = next_run_time(
        settings.interval_sec,
        jitter_ratio=clamp(settings.jitter_percent, MIN_JITTER_PERCENT, MAX_JITTER_PERCENT) / 100,
        minimum_sec=max(MIN_INTERVAL_SEC, minimum),
    )


async def set_feature(
    session: AsyncSession, group: Group, feature: str, enabled: bool
) -> bool:
    """Funksiyani yoqish/o'chirish. Qaytaradi: qiymat o'zgardimi."""
    column = FEATURE_COLUMN.get(str(feature))
    if column is None or group.settings is None:
        return False

    current = bool(getattr(group.settings, column))
    if current == enabled:
        return False

    setattr(group.settings, column, enabled)
    logger.info(
        "Guruh {} — {} funksiyasi {}",
        group.display,
        FEATURE_LABELS.get(feature, feature),
        "yoqildi" if enabled else "o'chirildi",
    )

    if str(feature) == GroupFeature.POSTING:
        await recompute_next_post(session, group, delay_min_sec=5 if enabled else None)

    await session.flush()
    return True


async def set_setting(
    session: AsyncSession,
    group: Group,
    field_name: str,
    value: Any,
) -> None:
    """Guruh sozlamasini yangilash (+ joylash vaqtini qayta hisoblash)."""
    if group.settings is None:
        return
    setattr(group.settings, field_name, value)
    if field_name in ("interval_sec", "jitter_percent"):
        await recompute_next_post(session, group)
    await session.flush()


def validate_interval_minutes(minutes: int) -> int:
    """Daqiqani sekundga aylantirish va chegaralarni tekshirish."""
    seconds = minutes * 60
    return clamp(seconds, MIN_INTERVAL_SEC, MAX_INTERVAL_SEC)


def validate_jitter(percent: int) -> int:
    return clamp(percent, MIN_JITTER_PERCENT, MAX_JITTER_PERCENT)


def validate_daily_limit(limit: int) -> int:
    return clamp(limit, 1, MAX_DAILY_POST_LIMIT)


# ─────────────────────── Pauza / o'chirish ─────────────────────────
async def pause_group(session: AsyncSession, group: Group, reason: str) -> None:
    """Guruhni to'xtatish (REJA.md 8.7): joylash o'chadi, sabab yoziladi."""
    group.is_active = False
    group.paused_reason = reason[:32]
    if group.settings is not None:
        group.settings.posting_enabled = False
    if group.rotation is not None:
        group.rotation.next_post_at = None
    logger.warning("Guruh to'xtatildi: {} — sabab: {}", group.display, reason)


async def resume_group(session: AsyncSession, group: Group, *, enable_posting: bool = True) -> None:
    group.is_active = True
    group.paused_reason = None
    group.last_error = None
    if enable_posting and group.settings is not None:
        group.settings.posting_enabled = True
        if group.rotation is not None:
            group.rotation.error_streak = 0
    await recompute_next_post(session, group, delay_min_sec=5)
    logger.info("Guruh qayta yoqildi: {}", group.display)


async def set_active(session: AsyncSession, group: Group, active: bool) -> None:
    """Guruhni pauza qilish yoki yoqish (admin tugmasi)."""
    if active:
        await resume_group(session, group)
    else:
        await pause_group(session, group, reason="manual")
    await session.flush()


async def delete_group(session: AsyncSession, group: Group) -> None:
    """Guruhni bazadan o'chirish (toifalar biriktirilishi bo'shatiladi)."""
    logger.warning("Guruh bazadan o'chirildi: {} ({})", group.display, group.tg_chat_id)
    await session.delete(group)
    await session.flush()


__all__ = [
    "FEATURE_COLUMN",
    "OPTIONAL_RIGHTS",
    "REQUIRED_RIGHTS",
    "RightsCheck",
    "apply_rights_check",
    "check_group_rights",
    "count_groups",
    "count_groups_by_status",
    "delete_group",
    "extract_rights",
    "get_group",
    "get_group_by_chat_id",
    "get_group_stats",
    "get_or_create_group",
    "list_groups",
    "missing_rights",
    "pause_group",
    "recompute_next_post",
    "resume_group",
    "set_active",
    "set_feature",
    "set_setting",
    "sync_bot_status",
    "validate_daily_limit",
    "validate_interval_minutes",
    "validate_jitter",
]
