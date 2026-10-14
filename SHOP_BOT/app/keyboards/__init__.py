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
from app.keyboards.callbacks import (
    AdminCB,
    CategoryCB,
    FeatureCB,
    GroupCB,
    NavCB,
    SellerCB,
    SellerPanelCB,
    TariffCB,
)

__all__ = [
    "ADMIN_SECTIONS",
    "READY_SECTIONS",
    "SECTION_PHASES",
    "SECTION_TITLES",
    "AdminCB",
    "CategoryCB",
    "FeatureCB",
    "GroupCB",
    "NavCB",
    "SellerCB",
    "SellerPanelCB",
    "TariffCB",
    "admin_main_kb",
    "back_kb",
    "settings_kb",
]
