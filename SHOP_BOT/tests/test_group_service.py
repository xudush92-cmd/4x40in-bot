"""Guruh servisi testlari: yaratish, huquqlar, pauza."""

from __future__ import annotations

from aiogram.types import Chat, ChatMemberAdministrator
from aiogram.types import User as TgUser

from app.db.models import GroupSettings
from app.services.group_service import (
    REQUIRED_RIGHTS,
    extract_rights,
    get_group_by_chat_id,
    get_or_create_group,
    missing_rights,
    pause_group,
    resume_group,
)
from app.utils.time import utcnow

TENANT = -1001234567890


def _chat(**kwargs) -> Chat:
    base = {"id": TENANT, "type": "supergroup", "title": "Telefonlar bozori"}
    base.update(kwargs)
    return Chat(**base)


def _admin_member(can_delete: bool = True, can_restrict: bool = True, can_invite: bool = True):
    return ChatMemberAdministrator(
        status="administrator",
        user=TgUser(id=42, is_bot=True, first_name="Bot"),
        can_be_edited=False,
        is_anonymous=False,
        can_manage_chat=True,
        can_delete_messages=can_delete,
        can_manage_video_chats=True,
        can_restrict_members=can_restrict,
        can_promote_members=False,
        can_change_info=True,
        can_invite_users=can_invite,
        can_post_messages=None,
        can_edit_messages=None,
        can_pin_messages=True,
        can_post_stories=False,
        can_edit_stories=False,
        can_delete_stories=False,
        can_send_welcome_messages=False,
    )


def test_extract_rights_from_administrator() -> None:
    rights = extract_rights(_admin_member())
    assert rights["can_delete_messages"] is True
    assert rights["can_restrict_members"] is True
    assert set(REQUIRED_RIGHTS).issubset(rights)


def test_direct_add_does_not_need_bot_invite_link_permission() -> None:
    rights = extract_rights(_admin_member(can_invite=False))
    assert rights["can_invite_users"] is False
    assert missing_rights(rights) == []


def test_extract_rights_from_non_admin() -> None:
    class FakeMember:
        status = "member"

    rights = extract_rights(FakeMember())
    assert all(value is False for value in rights.values())
    assert len(missing_rights(rights)) == len(REQUIRED_RIGHTS)


async def test_get_or_create_group_creates_settings_and_rotation(session) -> None:
    group = await get_or_create_group(session, _chat(), added_by=111)
    await session.flush()

    assert group.id is not None
    assert group.tg_chat_id == TENANT
    assert group.is_supergroup is True
    assert group.settings is not None
    assert group.rotation is not None

    # Ikkinchi marta chaqirilsa — yangi yozuv yaratilmaydi
    again = await get_or_create_group(session, _chat(), added_by=111)
    assert again.id == group.id


async def test_get_or_create_group_updates_title(session) -> None:
    await get_or_create_group(session, _chat())
    await session.flush()
    await get_or_create_group(session, _chat(title="Yangi nom"), added_by=None)
    await session.flush()

    refreshed = await get_group_by_chat_id(session, TENANT)
    assert refreshed is not None
    assert refreshed.title == "Yangi nom"


async def test_pause_and_resume(session) -> None:
    group = await get_or_create_group(session, _chat())
    await session.flush()
    group.settings.posting_enabled = True
    group.rotation.next_post_at = utcnow()
    await session.flush()

    await pause_group(session, group, reason="no_rights")
    assert group.is_active is False
    assert group.paused_reason == "no_rights"
    assert group.settings.posting_enabled is False

    await resume_group(session, group)
    assert group.is_active is True
    assert group.paused_reason is None
    assert group.settings.posting_enabled is True
    assert group.rotation.error_streak == 0


async def test_settings_defaults_for_new_group(session) -> None:
    group = await get_or_create_group(session, _chat())
    await session.flush()

    settings = await session.get(GroupSettings, group.id)
    assert settings is not None
    assert settings.posting_enabled is False       # admin yoqmaguncha o'chiq
    assert settings.guard_enabled is False
    assert settings.counter_enabled is False
    assert settings.cleaner_enabled is False
    assert settings.interval_sec == 1800
    assert settings.daily_post_limit == 50
