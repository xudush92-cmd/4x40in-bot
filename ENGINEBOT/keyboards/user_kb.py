"""
keyboards/user_kb.py — foydalanuvchi (user) menyulari.

V1: USER ichida POSTER va CUSTOMER ikkala sub-rol uchun alohida menyular.

QATLAMLAR:
──────────
1. Rol tanlash — /start ostida (Tenant/Poster/Customer/Help)
2. POSTER asosiy menyu — eʼlon yozish, START/STOP, profil
3. CUSTOMER asosiy menyu — qidiruv, lenta, profil
4. BOTH (poster + customer) — birlashgan menyu
5. Kategoriya tanlash (inline)
6. Interval tanlash (inline)
"""

from __future__ import annotations

from config import Rotation, UserRole
from core.categories import all_categories
from keyboards.common_kb import Btn, inline_grid, make_reply


# ─────────────────────────────────────────────────────────────────────
# 1. ROL TANLASH — /start ostida
# ─────────────────────────────────────────────────────────────────────
def role_selection_menu():
    """
    /start: 4 xil rol/yo'nalishni ko'rsatadi.

    🏢 Men guruh adminiman
    📝 Men eʼlon beraman   |  🔍 Men mijozman
    ℹ️ Yordam
    """
    return make_reply([
        [Btn.I_AM_TENANT],
        [Btn.I_AM_POSTER, Btn.I_AM_CUSTOMER],
        [Btn.HELP],
    ])


# ─────────────────────────────────────────────────────────────────────
# 2. POSTER asosiy menyu
# ─────────────────────────────────────────────────────────────────────
def poster_main_menu(*, rotation_active: bool = False):
    """
    POSTER bosh menyusi.

    ➕ Yangi eʼlon         📋 Mening eʼlonlarim
    ▶️/⛔ START/STOP       ⏱ Interval
    📊 Statistika          👤 Profilim
    🔄 Soha oʻzgartirish    🚪 Chiqish
    """
    start_stop = Btn.POSTER_STOP if rotation_active else Btn.POSTER_START
    return make_reply([
        [Btn.NEW_POST, Btn.MY_POSTS],
        [start_stop, Btn.POSTER_INTERVAL],
        [Btn.POSTER_STATS, Btn.MY_PROFILE],
        [Btn.CHANGE_CATEGORY, Btn.HELP],
        [Btn.LOGOUT],
    ])


# ─────────────────────────────────────────────────────────────────────
# 3. CUSTOMER asosiy menyu
# ─────────────────────────────────────────────────────────────────────
def customer_main_menu():
    """
    CUSTOMER bosh menyusi.

    🔍 Qidirish            📰 Yangi eʼlonlar
    ⭐ Saqlanganlar         📋 Qidiruv tarixi
    👤 Profilim            ℹ️ Yordam
    🚪 Chiqish
    """
    return make_reply([
        [Btn.SEARCH, Btn.BROWSE_FEED],
        [Btn.MY_BOOKMARKS, Btn.SEARCH_HISTORY],
        [Btn.MY_PROFILE, Btn.HELP],
        [Btn.LOGOUT],
    ])


# ─────────────────────────────────────────────────────────────────────
# 4. BOTH menyu (poster + customer)
# ─────────────────────────────────────────────────────────────────────
def both_main_menu(*, rotation_active: bool = False):
    """
    Ikki rolli foydalanuvchi (taksist mijoz ham) uchun birlashgan menyu.
    """
    start_stop = Btn.POSTER_STOP if rotation_active else Btn.POSTER_START
    return make_reply([
        [Btn.NEW_POST, Btn.SEARCH],
        [Btn.MY_POSTS, Btn.BROWSE_FEED],
        [start_stop, Btn.POSTER_INTERVAL],
        [Btn.MY_PROFILE, Btn.POSTER_STATS],
        [Btn.HELP, Btn.LOGOUT],
    ])


# ─────────────────────────────────────────────────────────────────────
# 5. Roʻyxatdan oʻtmagan / pending menyu
# ─────────────────────────────────────────────────────────────────────
def pending_menu():
    """Tasdiq kutmoqda."""
    return make_reply([
        ["⏳ Tasdiq kutilmoqda"],
        [Btn.HELP],
    ])


# ─────────────────────────────────────────────────────────────────────
# 6. KATEGORIYA tanlash (inline)
# ─────────────────────────────────────────────────────────────────────
def category_picker(callback_prefix: str = "user:category"):
    """
    13 ta kategoriya tugmasi (12 standart + Boshqa).

    callback_prefix : "user:category" → "user:category:taxi"
    """
    items = [(c.label, f"{callback_prefix}:{c.code}") for c in all_categories()]
    return inline_grid(
        items,
        columns=2,
        extra_rows=[[(Btn.BACK, f"{callback_prefix}:back")]],
    )


# ─────────────────────────────────────────────────────────────────────
# 7. INTERVAL tanlash (inline)
# ─────────────────────────────────────────────────────────────────────
def interval_picker(callback_prefix: str = "poster:interval"):
    """
    Poster aylanish intervali tanlash.

    Min: 10 daqiqa (qatʼiy qoida)
    """
    items: list[tuple[str, str]] = []
    for m in Rotation.QUICK_INTERVALS:
        if m < 60:
            label = f"⏱ {m} daq"
        elif m < 1440:
            hours = m // 60
            label = f"⏱ {hours} soat"
        else:
            label = f"⏱ {m // 1440} kun"
        items.append((label, f"{callback_prefix}:set:{m}"))
    items.append(("✏️ Qoʻlda kiritish", f"{callback_prefix}:custom"))
    return inline_grid(
        items,
        columns=3,
        extra_rows=[[(Btn.BACK, f"{callback_prefix}:back")]],
    )


# ─────────────────────────────────────────────────────────────────────
# 8. Mening eʼlonlarim — har eʼlon uchun amallar
# ─────────────────────────────────────────────────────────────────────
def post_actions(post_id: int):
    """Bitta eʼlon ustida poster amallari."""
    return inline_grid(
        [
            ("👁 Koʻrish", f"poster:post:view:{post_id}"),
            ("✏️ Tahrirlash", f"poster:post:edit:{post_id}"),
            ("🗑 Oʻchirish", f"poster:post:delete:{post_id}"),
        ],
        columns=1,
        extra_rows=[[(Btn.BACK, "poster:posts:back")]],
    )


# ─────────────────────────────────────────────────────────────────────
# 9. Eʼlon publish — tasdiqlash uchun
# ─────────────────────────────────────────────────────────────────────
def confirm_post_create():
    """Eʼlon yaratishda 'Joylashtirish/Bekor' tugmalari."""
    return inline_grid(
        [
            ("✅ Joylashtirish", "poster:post:confirm"),
            ("✏️ Tahrirlash", "poster:post:edit_text"),
            ("❌ Bekor qilish", "poster:post:cancel"),
        ],
        columns=1,
    )


# ─────────────────────────────────────────────────────────────────────
# 10. Customer search — kategoriya tanlash
# ─────────────────────────────────────────────────────────────────────
def customer_search_categories():
    """Mijoz qidiruvi: kategoriya tanlash."""
    items = [(c.label, f"customer:search:category:{c.code}") for c in all_categories()]
    items.append(("🔍 Hammasidan qidirish", "customer:search:category:all"))
    return inline_grid(
        items,
        columns=2,
        extra_rows=[[(Btn.BACK, "customer:menu")]],
    )


# ─────────────────────────────────────────────────────────────────────
# 11. Eʼlon ostidagi tugmalar (mijoz uchun)
# ─────────────────────────────────────────────────────────────────────
def post_view_actions(post_id: int, phone: str = ""):
    """Mijoz eʼlonni koʻrganda — bog'lanish va saqlash tugmalari."""
    items: list[tuple[str, str]] = []
    if phone:
        items.append((f"📞 {phone}", f"customer:contact:{post_id}"))
    items.append(("⭐ Saqlash", f"customer:bookmark:{post_id}"))
    items.append(("📋 Yana qidirish", "customer:search"))
    return inline_grid(items, columns=1)
