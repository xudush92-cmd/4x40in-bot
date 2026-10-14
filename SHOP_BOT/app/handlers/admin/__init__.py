"""Boshqaruv paneli router'lari (faqat adminlar uchun).

Tartib muhim: state bilan ishlaydigan router'lar (settings, groups,
categories) oldin turadi, umumiy menyu (panel) oxirida.
"""

from aiogram import Router

from app.filters import PrivateChat
from app.handlers.admin import categories, groups, panel, settings

# Faqat shaxsiy chatdagi admin amallari (guruh ichida panel ishlamaydi)
admin_router = Router(name="admin")
admin_router.message.filter(PrivateChat())
admin_router.callback_query.filter(PrivateChat())

admin_router.include_router(settings.router)     # ⚙️ global sozlamalar (FSM)
admin_router.include_router(groups.router)       # 👥 guruhlar (FSM)
admin_router.include_router(categories.router)   # 🗂 toifalar (FSM)
admin_router.include_router(panel.router)        # 🛠 asosiy menyu va bo'limlar

__all__ = ["admin_router"]
