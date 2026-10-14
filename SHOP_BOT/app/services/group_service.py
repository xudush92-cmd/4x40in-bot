"""Guruh bilan ishlash servisi: yozuvni yaratish/yangilash, huquqlar, pauza."""

from __future__ import annotations

from typing import Any

from aiogram.types import Chat, ChatMemberAdministrator, ChatMemberUpdated
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group, GroupRotation, GroupSettings

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


def extract_rights(member: Any) -> dict[str, bool]:
    """ChatMemberAdministrator obyektidan huquqlar lug'atini olish."""
    if isinstance(member, ChatMemberAdministrator):
        return {key: bool(getattr(member, key, False)) for key in (*REQUIRED_RIGHTS, *OPTIONAL_RIGHTS)}
    return {key: False for key in (*REQUIRED_RIGHTS, *OPTIONAL_RIGHTS)}


def missing_rights(rights: dict[str, bool]) -> list[str]:
    """Yetishmayotgan majburiy huquqlar (o'qishga qulay nomlar bilan)."""
    return [REQUIRED_RIGHTS[key] for key in REQUIRED_RIGHTS if not rights.get(key)]


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
    group.last_checked_at = None  # keyingi tekshiruvda yangilanadi

    missing: list[str] = []
    if is_admin:
        missing = missing_rights(group.bot_rights or {})
        group.is_active = True
        group.paused_reason = None
        if missing:
            group.last_error = "Yetishmayotgan huquqlar: " + ", ".join(missing)
    else:
        group.last_error = "Bot guruhda admin emas"

    if hasattr(event.new_chat_member, "user") and event.new_chat_member.user is not None:
        pass  # kerak bo'lsa kelajakda foydalaniladi

    return group, missing


async def pause_group(session: AsyncSession, group: Group, reason: str) -> None:
    """Guruhni to'xtatish (REJA.md 8.7): joylash o'chadi, sabab yoziladi."""
    group.is_active = False
    group.paused_reason = reason[:32]
    if group.settings is not None:
        group.settings.posting_enabled = False
    logger.warning("Guruh to'xtatildi: {} — sabab: {}", group.display, reason)


async def resume_group(session: AsyncSession, group: Group, *, enable_posting: bool = True) -> None:
    group.is_active = True
    group.paused_reason = None
    group.last_error = None
    if enable_posting and group.settings is not None:
        group.settings.posting_enabled = True
        if group.rotation is not None:
            group.rotation.error_streak = 0
    logger.info("Guruh qayta yoqildi: {}", group.display)
