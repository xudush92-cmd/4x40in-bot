"""Guruh ichidagi router'lar: hayot sikli, posbon, tozalovchi, sanoqchi."""

from aiogram import Router

from app.handlers.group import lifecycle

group_router = Router(name="group")
group_router.include_router(lifecycle.router)

__all__ = ["group_router"]
