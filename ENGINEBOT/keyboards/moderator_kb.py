"""
keyboards/moderator_kb.py — moderator (tenant yordamchisi) menyusi.

Cheklangan huquqlar: e'lonlarni ko'rish, foydalanuvchi tasdiqlash,
ogohlantirish berish. Bloklash va sozlash YO'Q.
"""

from __future__ import annotations

from keyboards.common_kb import Btn, inline_grid, make_reply


def moderator_main_menu():
    """
    Moderator asosiy menyusi.

    🟡 Tasdiqlash navbati    📋 E'lonlar
    👥 Foydalanuvchilar      📊 Statistika
    📝 Mening e'lonlarim     ℹ️ Yordam
    🚪 Chiqish
    """
    return make_reply([
        ["🟡 Tasdiqlash navbati", Btn.MANAGE_POSTS],
        [Btn.MANAGE_USERS, Btn.STATS],
        [Btn.MY_POSTS, Btn.HELP],
        [Btn.LOGOUT],
    ])


# ─────────────────────────────────────────────────────────────────────
# E'lon ustida moderator amallari
# ─────────────────────────────────────────────────────────────────────
def post_actions(post_id: int):
    """Moderator faqat pause va warn qila oladi."""
    items = [
        ("👁 Toʻliq koʻrish", f"mod:post:view:{post_id}"),
        ("⏸ Pause", f"mod:post:pause:{post_id}"),
        ("⚠️ Egaga ogohlantirish", f"mod:post:warn:{post_id}"),
    ]
    return inline_grid(
        items,
        columns=1,
        extra_rows=[[(Btn.BACK, "mod:posts:back")]],
    )


# ─────────────────────────────────────────────────────────────────────
# Foydalanuvchini tasdiqlash navbati
# ─────────────────────────────────────────────────────────────────────
def approve_queue_actions(target_user_id: int):
    """Pending foydalanuvchi uchun moderator amallari."""
    items = [
        ("✅ Tasdiqlash", f"mod:user:approve:{target_user_id}"),
        ("❌ Rad etish", f"mod:user:reject:{target_user_id}"),
        ("👁 Profilni koʻrish", f"mod:user:view:{target_user_id}"),
    ]
    return inline_grid(
        items,
        columns=1,
        extra_rows=[[(Btn.BACK, "mod:queue:back")]],
    )
