"""
keyboards/user_kb.py — oddiy foydalanuvchi (taksist/sotuvchi) menyusi.
"""

from __future__ import annotations

from keyboards.common_kb import Btn, make_reply


def user_main_menu():
    """
    Asosiy foydalanuvchi menyusi (ro'yxatdan o'tgan).

    📝 Yangi e'lon       📋 Mening e'lonlarim
    🔍 Qidirish          👤 Profilim
    ℹ️ Yordam            🚪 Chiqish
    """
    return make_reply([
        [Btn.NEW_POST, Btn.MY_POSTS],
        ["🔍 Qidirish", Btn.MY_PROFILE],
        [Btn.HELP, Btn.LOGOUT],
    ])


def user_unregistered_menu():
    """Hali ro'yxatdan o'tmagan foydalanuvchi uchun menyu."""
    return make_reply([
        ["📝 Roʻyxatdan oʻtish"],
        [Btn.HELP],
    ])


def role_selection_menu():
    """
    Birinchi /start: kim ekanligini tanlash.

    🏢 Men guruh adminiman
    📝 Men e'lon beraman
    🔍 Men e'lon izlayman
    ℹ️ Yordam
    """
    return make_reply([
        [Btn.I_AM_TENANT],
        [Btn.I_AM_USER, Btn.I_AM_SEARCHER],
        [Btn.HELP],
    ])
