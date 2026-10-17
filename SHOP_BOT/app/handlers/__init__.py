"""Handler router'larini yig'ish.

Tartib muhim: aniqroq router'lar oldin, "yutib yuboruvchi" (fallback)
handler'lar oxirida turadi.
"""

from __future__ import annotations

from aiogram import Router

from app.handlers import common, free_ads
from app.handlers.admin import admin_router
from app.handlers.applications import user_router as application_user_router
from app.handlers.group import group_router
from app.handlers.seller import seller_router
from app.handlers.seller.ads import router as seller_ads_router
from app.handlers.seller.payments import router as seller_payments_router


def build_root_router() -> Router:
    root = Router(name="root")
    root.include_router(admin_router)           # 1) admin amallari (private)
    root.include_router(free_ads.router)        # 1a) barcha uchun guruh-bepul e'lon (private)
    root.include_router(seller_payments_router) # 2) sotuvchi to'lovi/chek FSM (Phase 5)
    root.include_router(seller_ads_router)      # 3) sotuvchi e'lonlari (Phase 3)
    root.include_router(seller_router)          # 4) sotuvchi paneli
    root.include_router(application_user_router) # 5) oddiy foydalanuvchi arizasi (private)
    root.include_router(group_router)           # 6) guruh hodisalari
    root.include_router(common.router)          # 7) umumiy buyruqlar va fallback
    return root


__all__ = ["build_root_router"]
