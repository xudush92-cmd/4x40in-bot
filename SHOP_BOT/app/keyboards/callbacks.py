"""Inline tugmalar uchun callback_data fabrikalari (aiogram CallbackData)."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class AdminCB(CallbackData, prefix="adm"):
    """Boshqaruv paneli navigatsiyasi: `adm:<action>:<value>`."""

    action: str
    value: str = "-"


class NavCB(CallbackData, prefix="nav"):
    """Umumiy navigatsiya (orqaga, bekor qilish)."""

    to: str = "menu"


class GroupCB(CallbackData, prefix="grp"):
    """Guruh sozlamalari (Phase 1)."""

    action: str
    group_id: int = 0
    value: str = "-"


class FeatureCB(CallbackData, prefix="feat"):
    """Funksiya tumblerlari: `feat:<group_id>:<feature>:<on/off>`."""

    group_id: int
    feature: str
    enabled: bool = True
