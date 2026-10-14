"""Global sozlamalar servisi testlari (kesh + darhol kuchga kirish)."""

from __future__ import annotations

from app.constants import GroupFeature
from app.db.models import Setting
from app.services.settings_service import DEFAULTS, settings_service


async def test_defaults_available(session) -> None:
    values = await settings_service.get_all(session)
    assert values["default_interval_sec"] == DEFAULTS["default_interval_sec"]
    assert values["kill_switch"] is False


async def test_db_value_overrides_default(session) -> None:
    session.add(Setting(key="support_contact", value="@mening_admin"))
    await session.flush()

    settings_service.invalidate()
    assert await settings_service.get("support_contact", None, session) == "@mening_admin"


async def test_set_updates_cache_immediately(session) -> None:
    await settings_service.get_all(session)

    await settings_service.set(session, "support_contact", "@yangi", updated_by=111)
    # Kesh yangilangan — DB'ga qayta murojaat qilmasdan ham yangi qiymat
    assert await settings_service.get("support_contact") == "@yangi"

    row = await session.get(Setting, "support_contact")
    assert row is not None
    assert row.value == "@yangi"
    assert row.updated_by == 111


async def test_kill_switch_disables_features(session) -> None:
    await settings_service.get_all(session)
    assert await settings_service.is_feature_enabled(GroupFeature.POSTING) is True

    await settings_service.set(session, "kill_switch", True, updated_by=111)
    assert await settings_service.is_feature_enabled(GroupFeature.POSTING) is False
    assert await settings_service.is_kill_switch_on() is True


async def test_feature_flags_are_global(session) -> None:
    await settings_service.get_all(session)
    await settings_service.set(session, "guard_enabled_global", False, updated_by=111)
    assert await settings_service.is_feature_enabled(GroupFeature.GUARD) is False
    assert await settings_service.is_feature_enabled(GroupFeature.POSTING) is True


async def test_get_many(session) -> None:
    await settings_service.get_all(session)
    result = await settings_service.get_many(["support_contact", "kill_switch", "yoq_key"])
    assert set(result) == {"support_contact", "kill_switch", "yoq_key"}
    assert result["yoq_key"] is None
