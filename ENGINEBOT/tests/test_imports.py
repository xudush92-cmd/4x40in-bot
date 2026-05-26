"""
tests/test_imports.py — barcha modullarni import qilib ko'rish.

Smoke test: importable bo'lsa, sintaksis va asosiy bog'lanishlar OK.
Aslida pip kerak (aiogram, aiosqlite, dotenv) — sandbox'da skip bo'lishi mumkin.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Modullar — config'dan boshqa hammasi (config.py BOT_TOKEN talab qiladi)
EXPECTED_MODULES = [
    "config",
    "core.database",
    "core.permissions",
    "core.categories",
    "core.tenant_manager",
    "core.event_bus",
    "core.audit_log",
    "core.rate_limiter",
    "core.notifier",
    "core.error_handler",
    "utils.session_state",
    "utils.confirmation",
    "utils.validators",
    "utils.formatters",
    "utils.logger",
    "keyboards.common_kb",
    "keyboards.routes",
    "keyboards.user_kb",
    "keyboards.tenant_kb",
    "keyboards.super_admin_kb",
    "keyboards.moderator_kb",
]


def test_modules_can_be_loaded() -> None:
    """Har bir modul spec_from_file_location bilan yuklanishi mumkin."""
    failed = []
    for mod_name in EXPECTED_MODULES:
        parts = mod_name.split(".")
        path = ROOT.joinpath(*parts).with_suffix(".py")
        if not path.exists():
            failed.append(f"{mod_name} ({path}) topilmadi")
            continue

        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            failed.append(f"{mod_name} spec yaratilmadi")

    assert not failed, f"Modullar yuklanmadi: {failed}"


def test_categories_count() -> None:
    """13 ta kategoriya (12 standart + Boshqa)."""
    from core.categories import all_categories, all_codes

    cats = all_categories()
    assert len(cats) == 13, f"13 ta kutilgan, {len(cats)} ta topildi"

    codes = all_codes()
    assert "taxi" in codes
    assert "other" in codes
    assert "plumber" in codes


def test_btn_class_has_required_buttons() -> None:
    """Btn class — barcha kerakli tugmalar bor."""
    from keyboards.common_kb import Btn

    required = [
        "I_AM_TENANT", "I_AM_POSTER", "I_AM_CUSTOMER",
        "NEW_POST", "MY_POSTS", "POSTER_START", "POSTER_STOP",
        "SEARCH", "BROWSE_FEED", "MY_BOOKMARKS",
        "MY_PROFILE", "LOGOUT", "HELP", "CANCEL", "BACK",
        "MY_CHANNELS", "ADD_CHANNEL", "MANAGE_USERS", "MANAGE_POSTS",
        "BOT_SETTINGS", "STATS", "AUDIT_LOG",
        "DEEP_LINK", "CATEGORY_RESTRICTION",
    ]
    for name in required:
        assert hasattr(Btn, name), f"Btn.{name} topilmadi"


def test_user_role_values() -> None:
    """UserRole — POSTER, CUSTOMER, BOTH."""
    from config import UserRole

    assert UserRole.POSTER == "poster"
    assert UserRole.CUSTOMER == "customer"
    assert UserRole.BOTH == "both"


def test_rotation_min_interval_is_10() -> None:
    """Rotation min interval — qat'iy 10 daqiqa qoidasi."""
    from config import Rotation

    assert Rotation.MIN_INTERVAL_MIN == 10
