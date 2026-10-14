"""Phase 1: guruh sozlamalari, tumbler va matn yordamchilari testlari."""

from __future__ import annotations

from aiogram.types import Chat

from app.constants import GroupFeature, MAX_DAILY_POST_LIMIT, MAX_JITTER_PERCENT, MAX_INTERVAL_SEC
from app.keyboards import admin_main_kb, settings_kb
from app.keyboards.callbacks import FeatureCB
from app.keyboards.groups import MATRIX_FEATURES, matrix_kb
from app.services import group_service
from app.utils.text import (
    escape_html,
    fmt_interval,
    fmt_quiet_hours,
    human_int,
    parse_quiet_hours,
    split_name_emoji,
    truncate,
)

TENANT = -1009999888777


async def _group(session, *, posting: bool = False):
    group = await group_service.get_or_create_group(
        session, Chat(id=TENANT, type="supergroup", title="Test bozor")
    )
    await session.flush()
    group.settings.posting_enabled = posting
    await session.flush()
    return group


# ── Tumblerlar ────────────────────────────────────────────────────
async def test_set_feature_toggles_and_reports_change(session) -> None:
    group = await _group(session)

    assert await group_service.set_feature(session, group, GroupFeature.GUARD, True) is True
    assert group.settings.guard_enabled is True

    # Takroriy chaqiruv — o'zgarish yo'q
    assert await group_service.set_feature(session, group, GroupFeature.GUARD, True) is False

    assert await group_service.set_feature(session, group, GroupFeature.GUARD, False) is True
    assert group.settings.guard_enabled is False


async def test_set_feature_unknown_returns_false(session) -> None:
    group = await _group(session)
    assert await group_service.set_feature(session, group, "yoq_funksiya", True) is False


async def test_posting_enable_schedules_next_post(session) -> None:
    group = await _group(session)
    assert group.rotation.next_post_at is None

    await group_service.set_feature(session, group, GroupFeature.POSTING, True)
    assert group.rotation.next_post_at is not None

    await group_service.set_feature(session, group, GroupFeature.POSTING, False)
    assert group.rotation.next_post_at is None


async def test_changing_interval_reschedules(session) -> None:
    group = await _group(session, posting=True)
    await group_service.recompute_next_post(session, group)
    first = group.rotation.next_post_at
    assert first is not None

    await group_service.set_setting(session, group, "interval_sec", 60)
    second = group.rotation.next_post_at
    assert second is not None
    # Yangi interval qisqaroq — keyingi joylash vaqti oldinga suriladi
    assert second <= first


async def test_pause_clears_next_post(session) -> None:
    group = await _group(session, posting=True)
    await group_service.recompute_next_post(session, group)

    await group_service.set_active(session, group, False)
    assert group.is_active is False
    assert group.paused_reason == "manual"
    assert group.rotation.next_post_at is None

    await group_service.set_active(session, group, True)
    assert group.is_active is True
    assert group.paused_reason is None
    assert group.settings.posting_enabled is True


# ── Validatsiya ───────────────────────────────────────────────────
def test_validators_clamp_values() -> None:
    assert group_service.validate_interval_minutes(5) == 300
    assert group_service.validate_interval_minutes(0) == 60          # minimal
    assert group_service.validate_interval_minutes(100000) == MAX_INTERVAL_SEC

    assert group_service.validate_jitter(-5) == 0
    assert group_service.validate_jitter(100) == MAX_JITTER_PERCENT

    assert group_service.validate_daily_limit(0) == 1
    assert group_service.validate_daily_limit(10**6) == MAX_DAILY_POST_LIMIT


# ── Matn yordamchilari ────────────────────────────────────────────
def test_fmt_interval() -> None:
    assert fmt_interval(60) == "1 daqiqa"
    assert fmt_interval(1800) == "30 daqiqa"
    assert fmt_interval(3600) == "1 soat"
    assert fmt_interval(7200) == "2 soat"
    assert fmt_interval(5400) == "1 soat 30 daqiqa"
    assert fmt_interval(86400) == "1 kun"
    assert fmt_interval(None) == "—"


def test_parse_quiet_hours() -> None:
    assert parse_quiet_hours("23:00-08:00") == ("23:00", "08:00")
    assert parse_quiet_hours("9:05-18:30") == ("09:05", "18:30")
    assert parse_quiet_hours("off") is None
    assert parse_quiet_hours("O'CHIR") is None

    for bad in ("23:00", "25:00-08:00", "abc", "23:00 08:00"):
        try:
            parse_quiet_hours(bad)
        except ValueError:
            continue
        raise AssertionError(f"'{bad}' uchun ValueError kutilgan edi")


def test_fmt_quiet_hours() -> None:
    assert fmt_quiet_hours("23:00", "08:00") == "23:00 – 08:00"
    assert fmt_quiet_hours(None, None) == "o'chirilgan"


def test_human_int_and_truncate() -> None:
    assert human_int(1234567) == "1 234 567"
    assert human_int(None) == "0"
    assert truncate("a" * 50, 10).endswith("…")
    assert truncate("qisqa", 10) == "qisqa"
    assert truncate(None) == "—"


def test_split_name_emoji() -> None:
    assert split_name_emoji("📱 Telefonlar") == ("📱", "Telefonlar")
    assert split_name_emoji("Telefonlar") == (None, "Telefonlar")
    assert split_name_emoji("  🚗 Avto  ") == ("🚗", "Avto")
    assert split_name_emoji("") == (None, "")


def test_escape_html() -> None:
    assert escape_html("<b>Salom</b> & salom") == "&lt;b&gt;Salom&lt;/b&gt; &amp; salom"
    assert escape_html(None) == ""


# ── Klaviaturalar ─────────────────────────────────────────────────
def test_feature_callback_roundtrip() -> None:
    packed = FeatureCB(group_id=7, feature="guard", enabled=True, origin="matrix", page=2).pack()
    parsed = FeatureCB.unpack(packed)
    assert (parsed.group_id, parsed.feature, parsed.enabled, parsed.origin, parsed.page) == (
        7,
        "guard",
        True,
        "matrix",
        2,
    )
    assert len(packed.encode()) <= 64  # Telegram cheklovi


def test_matrix_keyboard_has_feature_buttons(session=None) -> None:
    from app.db.models import Group, GroupSettings

    group = Group(id=1, tg_chat_id=TENANT, title="Test", is_active=True, is_supergroup=True)
    group.settings = GroupSettings(group_id=1)

    kb = matrix_kb([group], page=0, total_pages=1)
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]

    for feature in MATRIX_FEATURES:
        expected = FeatureCB(group_id=1, feature=feature, enabled=True, origin="matrix", page=0).pack()
        assert expected in callbacks, f"{feature} tugmasi matritsada yo'q"


def test_admin_menu_shows_counts() -> None:
    kb = admin_main_kb(role="super", counts={"groups": 3, "moderation": 2})
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any(text.startswith("👥 Guruhlar · 3") for text in texts)
    assert any(text.startswith("✅ Moderatsiya · 2") for text in texts)
    # Hisoblagich bo'lmasa oddiy ko'rinishda qoladi
    kb_plain = admin_main_kb(role="super")
    texts_plain = [btn.text for row in kb_plain.inline_keyboard for btn in row]
    assert any(text == "👥 Guruhlar" for text in texts_plain)


def test_settings_keyboard_has_kill_switch() -> None:
    kb = settings_kb({"kill_switch": False})
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert any("kill_switch" in (cb or "") for cb in callbacks)
