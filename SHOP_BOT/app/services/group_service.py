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
)
from app.db.models import ActionLog, Ad, Category, Group, GroupRotation, GroupSettings, PostLog
from app.utils.time import utcnow

# Bot uchun majburiy admin huquqlari (REJA.md 1 — Guruhlar)
REQUIRED_RIGHTS: dict[str, str] = {
    "can_delete_messages": "Xabarlarni o'chirish",
    "can_restrict_members": "A'zolarni cheklash (mute/ban)",
}

OPTIONAL_RIGHTS: dict[str, str] = {
    # Guruhdagi «A'zo qo'shish» botning taklif havolasi yaratish huquqiga
    # bog'liq emas. Eski link manbasi endi N kreditiga kirmaydi.
    "can_invite_users": "Taklif havolalari yaratish",
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
        # Oddiy huquq yangilanishi adminning qo'lda bergan favqulodda
        # pauzasini o'z-o'zidan bekor qilmasin.
        if group.paused_reason != "manual":
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
async def recompute_next_post(session: AsyncSession, group: Group) -> None:
    """Faqat diagnostika va texnik lease: shaxsiy due'ni bloklamaydi."""
    rotation = await session.get(GroupRotation, group.id)
    settings = await session.get(GroupSettings, group.id)
    if rotation is None:
        return
    sending = (await session.execute(select(PostLog.id).where(
        PostLog.group_id == group.id, PostLog.status == "sending",
    ).limit(1))).scalar_one_or_none()
    if sending is not None:
        return  # in-flight claim lease'ini o'zgartirmaymiz
    if settings is None or not settings.posting_enabled or not group.is_active:
        rotation.next_post_at = None
        return
    await session.flush()  # autoflush=False: shu tranzaksiyadagi due ko‘rinsin
    rotation.next_post_at = (await session.execute(select(func.min(Ad.next_eligible_at))
        .join(Category, Category.id == Ad.category_id)
        .where(Category.group_id == group.id, Category.is_active.is_(True),
               Ad.status == "active", Ad.admin_paused.is_(False),
               Ad.next_eligible_at.is_not(None)))).scalar_one()


async def set_feature(
    session: AsyncSession, group: Group, feature: str, enabled: bool, *, actor_id: int | None = None
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
        if enabled:
            categories = (await session.execute(
                select(Category).where(Category.group_id == group.id)
            )).scalars().all()
            for category in categories:
                if category.rotation and not category.rotation.is_paused:
                    category.rotation.next_post_at = None
        await recompute_next_post(session, group)
        if enabled and group.settings.free_ads_enabled:
            from app.services.free_ad_service import rebase_group_due

            await rebase_group_due(session, group)
    elif str(feature) == GroupFeature.COUNTER:
        # Phase 7: matritsa tugmasi sanoqchini faqat sinov rejimida yoqadi.
        from app.services.counter_service import ensure_counter

        row = await ensure_counter(session, group.id)
        row.enabled = enabled
        if enabled:
            row.dry_run = True
        if actor_id is not None:
            session.add(ActionLog(
                actor_id=actor_id, action="counter_switch", entity="group_settings",
                entity_id=group.id, group_id=group.id,
                before={column: current}, after={column: enabled, "dry_run": row.dry_run},
            ))
    elif str(feature) in (GroupFeature.GUARD, GroupFeature.CLEANER):
        # Matritsa orqali bir bosishda yoqish ham xavfsiz dry-run'dan boshlanadi.
        from app.services import group_policy_service as policy

        row = await (policy.ensure_guard(session, group.id) if feature == GroupFeature.GUARD
                     else policy.ensure_cleaner(session, group.id))
        row.enabled = enabled
        if enabled:
            row.dry_run = True
        if actor_id is not None:
            session.add(ActionLog(
                actor_id=actor_id, action="group_policy_switch", entity="group_settings",
                entity_id=group.id, group_id=group.id,
                before={column: current}, after={column: enabled, "dry_run": row.dry_run},
            ))

    await session.flush()
    return True


async def set_setting(
    session: AsyncSession,
    group: Group,
    field_name: str,
    value: Any,
) -> None:
    """Faqat guruhning tijoriy bo'lmagan sozlamalari."""
    if group.settings is None or field_name not in {"protect_content", "timezone"}:
        raise ValueError("Bu sozlama guruhda emas, tarif yoki bepul rejada boshqariladi.")
    setattr(group.settings, field_name, value)
    await session.flush()


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
        categories = (await session.execute(
            select(Category).where(Category.group_id == group.id)
        )).scalars().all()
        for category in categories:
            if category.rotation and not category.rotation.is_paused:
                category.rotation.next_post_at = None
    await recompute_next_post(session, group)
    if group.settings and group.settings.free_ads_enabled:
        from app.services.free_ad_service import rebase_group_due

        await rebase_group_due(session, group)
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
]
