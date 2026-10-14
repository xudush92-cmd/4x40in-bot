"""Handler router'larini yig'ish.

Tartib muhim: aniqroq router'lar oldin, "yutib yuboruvchi" (fallback)
handler'lar oxirida turadi.
"""

from __future__ import annotations

from aiogram import Router

from app.handlers import common
from app.handlers.admin import admin_router
from app.handlers.group import group_router
from app.handlers.seller import seller_router


def build_root_router() -> Router:
    root = Router(name="root")
    root.include_router(admin_router)      # 1) admin amallari (private)
    root.include_router(seller_router)     # 2) sotuvchi paneli
    root.include_router(group_router)      # 3) guruh hodisalari
    root.include_router(common.router)     # 4) umumiy buyruqlar va fallback
    return root


__all__ = ["build_root_router"]
