"""Klaviaturalar."""

from app.keyboards.admin import (
    ADMIN_SECTIONS,
    READY_SECTIONS,
    SECTION_PHASES,
    SECTION_TITLES,
    admin_main_kb,
    back_kb,
    settings_kb,
)
from app.keyboards.callbacks import AdminCB, FeatureCB, GroupCB, NavCB

__all__ = [
    "ADMIN_SECTIONS",
    "READY_SECTIONS",
    "SECTION_PHASES",
    "SECTION_TITLES",
    "AdminCB",
    "FeatureCB",
    "GroupCB",
    "NavCB",
    "admin_main_kb",
    "back_kb",
    "settings_kb",
]
