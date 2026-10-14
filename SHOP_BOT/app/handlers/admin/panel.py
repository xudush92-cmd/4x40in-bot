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
from app.services.stats_service import format_overview, get_overview

router = Router(name="admin:panel")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.callback_query(AdminCB.filter(F.action == "menu"))
async def show_menu(callback: CallbackQuery, role: str | None) -> None:
    """Asosiy panel ekranini ko'rsatish/yangilash."""
    text = (
        "🛠 <b>Boshqaruv paneli</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Kerakli bo'limni tanlang.\n\n"
        "<i>Eslatma: hozircha tayyor bo'lmagan bo'limlar bosilganda "
        "qaysi bosqichda qo'shilishi ko'rsatiladi.</i>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=admin_main_kb(role))
    except Exception:  # xabar o'zgarmagan bo'lsa Telegram xato beradi
        await callback.message.answer(text, reply_markup=admin_main_kb(role))
    await callback.answer()


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
        data = await get_overview(session)
        text = format_overview(data)
        await callback.message.edit_text(text, reply_markup=admin_main_kb(role))
        await callback.answer("Statistika yangilandi")
        return

    if key == "settings":
        from app.handlers.admin.settings import render_settings_screen

        await render_settings_screen(callback, session, role)
        return

    phase = SECTION_PHASES.get(key, 9)
    title = SECTION_TITLES.get(key, key)
    logger.debug("Tayyor bo'lmagan bo'lim: {} (Phase {})", key, phase)
    await callback.answer(
        f"{title} bo'limi Phase {phase} da qo'shiladi (REJA.md 14-bo'lim).",
        show_alert=True,
    )


@router.callback_query(AdminCB.filter(F.action == "noop"))
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


def menu_markup(role: str | None) -> InlineKeyboardMarkup:
    return admin_main_kb(role)


__all__ = ["router", "menu_markup"]
_ = AdminRole
