"""Guruh ichidagi router'lar: hayot sikli, posbon, tozalovchi, sanoqchi."""

from aiogram import Router

from app.handlers.group import counter, lifecycle, policy

group_router = Router(name="group")
group_router.include_router(lifecycle.router)
group_router.include_router(counter.router)  # buyruq/chat_member; oddiy xabarlar siyosat orqali o'tadi
group_router.include_router(policy.router)

__all__ = ["group_router"]
