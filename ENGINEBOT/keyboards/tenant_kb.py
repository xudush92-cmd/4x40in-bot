"""
keyboards/tenant_kb.py — guruh egasi (tenant) menyusi.
"""

from __future__ import annotations

from keyboards.common_kb import Btn, inline_grid, make_reply, toggle_label
from config import Rotation


def tenant_main_menu():
    """
    Guruh egasi asosiy menyusi.

    📺 Kanallarim         👥 Foydalanuvchilar
    📋 E'lonlar           🔄 Aylanish
    📊 Statistika         👮 Moderatorlar
    💰 To'lov             ⚙️ Sozlamalar
    📜 Tarix              🚪 Chiqish
    """
    return make_reply([
        [Btn.MY_CHANNELS, Btn.MANAGE_USERS],
        [Btn.MANAGE_POSTS, Btn.ROTATION_SETTINGS],
        [Btn.STATS, Btn.MODERATORS],
        [Btn.BILLING, Btn.BOT_SETTINGS],
        [Btn.AUDIT_LOG, Btn.HELP],
        [Btn.LOGOUT],
    ])


# ─────────────────────────────────────────────────────────────────────
# Aylanish (rotation) sozlamalari
# ─────────────────────────────────────────────────────────────────────
def rotation_panel(
    *,
    rotation_active: bool,
    interval_min: int,
    bot_active: bool,
    post_intake_active: bool,
):
    """
    Aylanish boshqaruv paneli (inline).

    🟢/🔴 Bot: ON/OFF
    🟢/🔴 E'lon qabuli: ON/OFF
    🟢/🔴 Aylanish: ON/OFF
    ⏱ Interval: 30 daq
    📅 Vaqt jadvali
    """
    items = [
        (toggle_label(bot_active, "Bot"), "tenant:toggle:bot"),
        (toggle_label(post_intake_active, "Eʼlon qabuli"), "tenant:toggle:post_intake"),
        (toggle_label(rotation_active, "Aylanish"), "tenant:toggle:rotation"),
        (f"⏱ Interval: {interval_min} daq", "tenant:rotation:set_interval"),
        ("📅 Vaqt jadvali", "tenant:rotation:set_schedule"),
        ("⏳ Eʼlon yashash muddati", "tenant:rotation:set_lifetime"),
    ]
    return inline_grid(
        items,
        columns=1,
        extra_rows=[[(Btn.BACK, "tenant:rotation:back")]],
    )


def interval_quick_picker():
    """Tezkor interval tanlash (Rotation.QUICK_INTERVALS asosida)."""
    items: list[tuple[str, str]] = []
    for m in Rotation.QUICK_INTERVALS:
        if m < 60:
            label = f"{m} daq"
        elif m < 1440:
            label = f"{m // 60} soat"
        else:
            label = f"{m // 1440} kun"
        items.append((label, f"tenant:interval:set:{m}"))
    items.append(("✏️ Boshqa qiymat", "tenant:interval:custom"))
    return inline_grid(
        items,
        columns=3,
        extra_rows=[[(Btn.BACK, "tenant:rotation:back")]],
    )


# ─────────────────────────────────────────────────────────────────────
# Foydalanuvchi boshqaruvi
# ─────────────────────────────────────────────────────────────────────
def users_filter():
    """Foydalanuvchilar filtri."""
    items = [
        ("👥 Hammasi", "tenant:users:filter:all"),
        ("🟢 Aktiv", "tenant:users:filter:active"),
        ("🟡 Kutilayotgan", "tenant:users:filter:pending"),
        ("🔴 Bloklangan", "tenant:users:filter:blocked"),
    ]
    return inline_grid(
        items,
        columns=2,
        extra_rows=[[(Btn.BACK, "tenant:users:back")]],
    )


def user_actions(target_user_id: int, status: str = "active"):
    """Bitta foydalanuvchi ustida amallar."""
    items: list[tuple[str, str]] = [
        ("📋 Eʼlonlari", f"tenant:user:posts:{target_user_id}"),
        ("📜 Tarix (log)", f"tenant:user:audit:{target_user_id}"),
    ]
    if status == "pending":
        items.insert(0, ("✅ Tasdiqlash", f"tenant:user:approve:{target_user_id}"))
        items.insert(1, ("❌ Rad etish", f"tenant:user:reject:{target_user_id}"))
    if status == "active":
        items.append(("⚠️ Ogohlantirish", f"tenant:user:warn:{target_user_id}"))
        items.append(("⛔ Bloklash", f"tenant:user:block:{target_user_id}"))
    if status == "blocked":
        items.append(("✅ Tiklash", f"tenant:user:unblock:{target_user_id}"))

    return inline_grid(
        items,
        columns=1,
        extra_rows=[[(Btn.BACK, "tenant:users:back")]],
    )


# ─────────────────────────────────────────────────────────────────────
# Kanal boshqaruvi
# ─────────────────────────────────────────────────────────────────────
def channel_actions(channel_id: int, is_active: bool):
    """Bitta kanal ustida amallar."""
    items = [
        (
            "🔴 Vaqtincha oʻchirish" if is_active else "🟢 Yoqish",
            f"tenant:channel:toggle:{channel_id}",
        ),
        ("✏️ Sozlamalar", f"tenant:channel:settings:{channel_id}"),
        ("🗑 Olib tashlash", f"tenant:channel:remove:{channel_id}"),
    ]
    return inline_grid(
        items,
        columns=1,
        extra_rows=[[(Btn.BACK, "tenant:channels:back")]],
    )


# ─────────────────────────────────────────────────────────────────────
# Pending foydalanuvchini tasdiqlash (notification ostida)
# ─────────────────────────────────────────────────────────────────────
def approve_user_inline(target_user_id: int):
    """Notify ichida 'Tasdiqlash / Rad etish' tugmalari."""
    return inline_grid(
        [
            ("✅ Tasdiqlash", f"tenant:user:approve:{target_user_id}"),
            ("❌ Rad etish", f"tenant:user:reject:{target_user_id}"),
        ],
        columns=2,
    )
