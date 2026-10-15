"""Boshqaruv paneli: bo'limlar daraxti va navigatsiya (REJA.md 6-bo'lim)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole
from app.filters import IsAdmin
from app.keyboards import SECTION_PHASES, SECTION_TITLES, admin_main_kb
from app.keyboards.callbacks import AdminCB
from app.services.stats_service import get_menu_counts
from app.utils.tg import alert, render

router = Router(name="admin:panel")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

MENU_TEXT = (
    "🛠 <b>Boshqaruv paneli</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "Kerakli bo'limni tanlang.\n\n"
    "<i>Tugmalardagi raqamlar — joriy holat (masalan guruhlar soni). "
    "Hali tayyor bo'lmagan bo'limlar qaysi bosqichda qo'shilishini aytadi.</i>"
)


@router.callback_query(AdminCB.filter(F.action == "menu"))
async def show_menu(callback: CallbackQuery, role: str | None, session: AsyncSession) -> None:
    """Asosiy panel ekranini ko'rsatish/yangilash."""
    counts = await get_menu_counts(session)
    await render(callback, MENU_TEXT, admin_main_kb(role, counts))
    await alert(callback, "")


@router.callback_query(AdminCB.filter(F.action == "section"))
async def open_section(
    callback: CallbackQuery,
    callback_data: AdminCB,
    session: AsyncSession,
    role: str | None,
) -> None:
    """Bo'limni ochish: tayyor bo'lsa ko'rsatiladi, aks holda "Phase N" xabari."""
    key = callback_data.value

    if key == "stats":
        from app.handlers.admin.stats import render_home

        await render_home(callback, session, role)
        await alert(callback, "Statistika yangilandi")
        return

    if key == "admins":
        if role != AdminRole.SUPER:
            await alert(callback, "⛔️ Adminlarni faqat super admin boshqaradi.", show=True)
            return
        from app.handlers.admin.admins import render_home

        await render_home(callback, session)
        await alert(callback, "")
        return

    if key == "broadcast":
        if role not in (AdminRole.ADMIN, AdminRole.SUPER):
            await alert(callback, "⛔️ Tarqatishni faqat admin boshqaradi.", show=True)
            return
        from app.handlers.admin.broadcast import render_home

        await render_home(callback, session)
        await alert(callback, "")
        return

    if key == "referral":
        from app.handlers.admin.referral import render_home

        await render_home(callback, session, role)
        await alert(callback, "")
        return

    if key == "texts":
        from app.handlers.admin.texts import render_list

        await render_list(callback, session)
        await alert(callback, "")
        return

    if key == "errors":
        if role not in (AdminRole.ADMIN, AdminRole.SUPER):
            await alert(callback, "⛔️ Xatolarni faqat admin ko'radi.", show=True)
            return
        from app.handlers.admin.errors import render_list

        await render_list(callback, session)
        await alert(callback, "")
        return

    if key == "settings":
        from app.handlers.admin.settings import render_settings_screen

        await render_settings_screen(callback, session, role)
        return

    if key == "groups":
        from app.handlers.admin.groups import render_list as render_groups

        await render_groups(callback, session, 0)
        await alert(callback, "")
        return

    if key == "categories":
        from app.handlers.admin.categories import render_list as render_categories

        await render_categories(callback, session, 0)
        await alert(callback, "")
        return

    if key == "sellers":
        from app.handlers.admin.sellers import render_list as render_sellers

        await render_sellers(callback, session, 0)
        await alert(callback, "")
        return

    if key == "tariffs":
        from app.handlers.admin.tariffs import render_list as render_tariffs

        await render_tariffs(callback, session, 0)
        await alert(callback, "")
        return

    if key == "ads":
        from app.handlers.admin.mods import render_ads

        await render_ads(callback, session, 0, "all")
        await alert(callback, "")
        return

    if key == "moderation":
        from app.handlers.admin.mods import render_pending

        await render_pending(callback, session, 0)
        await alert(callback, "")
        return

    if key == "payments":
        if role not in (AdminRole.ADMIN, AdminRole.SUPER):
            await alert(callback, "⛔️ To'lovlarni faqat admin boshqaradi.", show=True)
            return
        from app.handlers.admin.payments import render_home

        await render_home(callback, session)
        await alert(callback, "")
        return

    if key == "counter":
        from app.handlers.admin.counter import render_choose

        await render_choose(callback, session)
        await alert(callback, "")
        return

    if key in {"guard", "cleaner", "permissions"}:
        from app.handlers.admin.policy import render_choose

        await render_choose(callback, session, key)
        await alert(callback, "")
        return

    if key == "users":
        from app.handlers.admin.permissions import render_users_home

        await render_users_home(callback, session)
        await alert(callback, "")
        return

    phase = SECTION_PHASES.get(key, 9)
    title = SECTION_TITLES.get(key, key)
    logger.debug("Tayyor bo'lmagan bo'lim: {} (Phase {})", key, phase)
    await alert(
        callback,
        f"{title} bo'limi Phase {phase} da qo'shiladi (REJA.md 14-bo'lim).",
        show=True,
    )


@router.callback_query(AdminCB.filter(F.action == "noop"))
async def noop(callback: CallbackQuery) -> None:
    await alert(callback, "")


def menu_markup(role: str | None) -> InlineKeyboardMarkup:
    return admin_main_kb(role)


__all__ = ["menu_markup", "router"]
