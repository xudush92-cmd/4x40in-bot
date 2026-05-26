"""
keyboards/tenant_kb.py — guruh egasi (tenant) menyusi.

V1 yangilanish:
- Rotation panel'da "tenant rotation_active" toggle YO'Q (hozir per-poster)
- Tenant faqat MIN INTERVAL cheklovini belgilaydi (default 10 daq)
- Bot ON/OFF, Post intake ON/OFF — tenant darajasida saqlanadi
- Auto-approval toggle — qo'shildi
"""

from __future__ import annotations

from config import Rotation
from keyboards.common_kb import Btn, inline_grid, make_reply, toggle_label


# ─────────────────────────────────────────────────────────────────────
# Tenant asosiy menyusi
# ─────────────────────────────────────────────────────────────────────
def tenant_main_menu():
    """
    Guruh egasi asosiy menyusi.

    📺 Kanallarim         👥 Foydalanuvchilar
    📋 Eʼlonlar           ⚙️ Sozlamalar
    📊 Statistika         📜 Tarix
    🔗 Havola             🚫 Kategoriyalar
    👤 Profilim           ℹ️ Yordam
    🚪 Chiqish
    """
    return make_reply([
        [Btn.MY_CHANNELS, Btn.MANAGE_USERS],
        [Btn.MANAGE_POSTS, Btn.BOT_SETTINGS],
        [Btn.STATS, Btn.AUDIT_LOG],
        [Btn.DEEP_LINK, Btn.CATEGORY_RESTRICTION],
        [Btn.MY_PROFILE, Btn.HELP],
        [Btn.LOGOUT],
    ])


# ─────────────────────────────────────────────────────────────────────
# Sozlamalar paneli (Bot ON/OFF, post intake, min interval, auto-approval)
# ─────────────────────────────────────────────────────────────────────
def settings_panel(
    *,
    bot_active: bool,
    post_intake_active: bool,
    require_approval: bool,
    min_interval_min: int,
):
    """
    Tenant sozlamalari paneli (inline).

    🟢/🔴 Bot: ON/OFF
    🟢/🔴 Eʼlon qabuli: ON/OFF
    🟢/🔴 Auto-tasdiqlash: ON/OFF (yoqilgan bo'lsa user'lar avtomatik tasdiq)
    ⏱ Min interval: 10 daq (posterlar uchun min cheklov)
    """
    items = [
        (toggle_label(bot_active, "Bot"), "tenant:toggle:bot"),
        (toggle_label(post_intake_active, "Eʼlon qabuli"), "tenant:toggle:post_intake"),
        (toggle_label(require_approval is False, "Auto-tasdiq"),
         "tenant:toggle:auto_approve"),
        (f"⏱ Min interval: {min_interval_min} daq", "tenant:set_min_interval"),
    ]
    return inline_grid(
        items,
        columns=1,
        extra_rows=[[(Btn.BACK, "tenant:settings:back")]],
    )


# ─────────────────────────────────────────────────────────────────────
# Min interval picker (10 daqdan kam emas)
# ─────────────────────────────────────────────────────────────────────
def min_interval_picker():
    """
    Tenant tomonidan belgilanadigan posterlar uchun MIN cheklov.

    Default 10 daq (foydalanuvchining qatʼiy qoidasi).
    Tenant kerak bo'lsa kattarog'ini qo'yishi mumkin (15, 30, 60).
    """
    options = [10, 15, 20, 30, 60]
    items = [(f"⏱ {m} daq", f"tenant:min_interval:set:{m}") for m in options]
    return inline_grid(
        items,
        columns=3,
        extra_rows=[[(Btn.BACK, "tenant:settings:back")]],
    )


# ─────────────────────────────────────────────────────────────────────
# Foydalanuvchilar filtri
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



# ─────────────────────────────────────────────────────────────────────
# 📋 Eʼlonlar nazorati
# ─────────────────────────────────────────────────────────────────────
def posts_filter():
    """Eʼlonlar filtri (kategoriya yoki status bo'yicha)."""
    items = [
        ("📋 Hammasi", "tenant:posts:filter:all"),
        ("🟢 Aktiv", "tenant:posts:filter:active"),
        ("⏸ Pause", "tenant:posts:filter:paused"),
        ("🟡 Navbatda", "tenant:posts:filter:queued"),
    ]
    return inline_grid(
        items,
        columns=2,
        extra_rows=[[(Btn.BACK, "tenant:posts:back")]],
    )


def post_actions(post_id: int, status: str = "active"):
    """Bitta e'lon ustida amallar (tenant uchun)."""
    items: list[tuple[str, str]] = [
        ("👁 Ko'rish", f"tenant:post:view:{post_id}"),
    ]
    if status == "active":
        items.append(("⏸ Pause", f"tenant:post:pause:{post_id}"))
    elif status == "paused":
        items.append(("▶️ Davom", f"tenant:post:resume:{post_id}"))
    items.append(("🗑 O'chirish", f"tenant:post:delete:{post_id}"))
    items.append(("⚠️ Egasiga ogohlantirish", f"tenant:post:warn_owner:{post_id}"))
    return inline_grid(
        items,
        columns=1,
        extra_rows=[[(Btn.BACK, "tenant:posts:back")]],
    )


# ─────────────────────────────────────────────────────────────────────
# 🚫 Kategoriya cheklovi (tenant ruxsat bergan kategoriyalar)
# ─────────────────────────────────────────────────────────────────────
def category_restriction_picker(allowed_codes: list[str]):
    """
    Kategoriya tanlash paneli.

    allowed_codes — hozirda ruxsat berilgan kategoriyalar.
    Tugma bosib qo'shish/olib tashlash.
    """
    from core.categories import CATEGORIES

    items: list[tuple[str, str]] = []
    for cat in CATEGORIES:
        is_on = cat.code in allowed_codes
        prefix = "✅" if is_on else "⬜"
        items.append(
            (f"{prefix} {cat.icon} {cat.name}", f"tenant:cat_toggle:{cat.code}")
        )
    return inline_grid(
        items,
        columns=2,
        extra_rows=[
            [("💾 Saqlash", "tenant:cat_save")],
            [(Btn.BACK, "tenant:cat:back")],
        ],
    )


# ─────────────────────────────────────────────────────────────────────
# 🔗 Deep-link karta
# ─────────────────────────────────────────────────────────────────────
def deep_link_card():
    """Deep link o'qish (Orqaga tugmasi bilan)."""
    return inline_grid(
        [("📋 Nusxa olish", "tenant:deeplink:copy")],
        columns=1,
        extra_rows=[[(Btn.BACK, "tenant:deeplink:back")]],
    )



# ─────────────────────────────────────────────────────────────────────
# 👤 PROFILE edit (tenant)
# ─────────────────────────────────────────────────────────────────────
def profile_edit_panel():
    """Tenant profilini tahrirlash menyusi."""
    items = [
        ("✏️ Ism", "tenant:profile:edit:name"),
        ("📱 Telefon", "tenant:profile:edit:phone"),
        ("📝 Tavsif", "tenant:profile:edit:description"),
    ]
    return inline_grid(
        items,
        columns=1,
        extra_rows=[[(Btn.BACK, "tenant:profile:back")]],
    )
