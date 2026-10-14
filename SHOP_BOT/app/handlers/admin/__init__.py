"""Boshqaruv paneli router'lari (faqat adminlar uchun)."""

from aiogram import F, Router

from app.handlers.admin import panel, settings

# Faqat private chatdagi admin amallari
admin_router = Router(name="admin")
admin_router.message.filter(F.chat.type == "private")
admin_router.callback_query.filter(F.chat.type == "private")

admin_router.include_router(settings.router)
admin_router.include_router(panel.router)

__all__ = ["admin_router"]
