"""Boshqaruv paneli router'lari (faqat adminlar uchun).

Tartib muhim: state bilan ishlaydigan router'lar (settings, groups,
categories, sellers, tariffs, moderation) oldin turadi, umumiy menyu
(panel) oxirida.
"""

from aiogram import Router

from app.filters import PrivateChat
from app.handlers.admin import (
    admins,
    broadcast,
    categories,
    counter,
    errors,
    groups,
    mods,
    panel,
    payments,
    permissions,
    policy,
    posting,
    referral,
    sellers,
    settings,
    stats,
    tariffs,
    texts,
)
from app.handlers.applications import admin_router as applications_router

# Faqat shaxsiy chatdagi admin amallari (guruh ichida panel ishlamaydi)
admin_router = Router(name="admin")
admin_router.message.filter(PrivateChat())
admin_router.callback_query.filter(PrivateChat())

admin_router.include_router(settings.router)     # ⚙️ global sozlamalar (FSM)
admin_router.include_router(texts.router)        # ✍️ bot matnlari (FSM)
admin_router.include_router(errors.router)       # ⚠️ xatolar jurnali
admin_router.include_router(referral.router)     # 🤝 referal (FSM)
admin_router.include_router(broadcast.router)    # 📣 broadcast (FSM)
admin_router.include_router(stats.router)        # 📊 kunlik/guruh hisobotlari
admin_router.include_router(admins.router)       # 👑 super admin rollari
admin_router.include_router(groups.router)       # 👥 guruhlar (FSM)
admin_router.include_router(counter.router)      # 🧮 har guruh sanoqchisi (FSM)
admin_router.include_router(policy.router)       # 🛡 guruh siyosati (FSM)
admin_router.include_router(permissions.router)  # 🔑 istisnolar va foydalanuvchi
admin_router.include_router(categories.router)   # 🗂 toifalar (FSM)
admin_router.include_router(sellers.router)      # 🛒 sotuvchilar (FSM)
admin_router.include_router(applications_router)  # 📥 sotuvchilik arizalari (FSM)
admin_router.include_router(tariffs.router)      # 💳 tariflar (FSM)
admin_router.include_router(mods.router)         # ✅ moderatsiya + 📢 e'lonlar
admin_router.include_router(posting.router)      # 📋 navbat / 🚀 qo'lda joylash (Phase 4)
admin_router.include_router(payments.router)     # 💰 cheklar va rekvizitlar (Phase 5)
admin_router.include_router(panel.router)        # 🛠 asosiy menyu va bo'limlar

__all__ = ["admin_router"]
