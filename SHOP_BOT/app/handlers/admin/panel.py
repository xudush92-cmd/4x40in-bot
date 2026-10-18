"""Boshqaruv paneli: bo'limlar daraxti va navigatsiya (REJA.md 6-bo'lim)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole
from app.db.models import ActionLog
from app.filters import IsAdmin
from app.keyboards import SECTION_PHASES, SECTION_TITLES, admin_main_kb
from app.keyboards.admin import HUB_SECTIONS, admin_all_sections_kb, admin_hub_kb
from app.keyboards.callbacks import AdminCB
from app.services.stats_service import get_menu_counts
from app.utils.text import escape_html
from app.utils.tg import alert, render
from app.utils.time import fmt_dt

router = Router(name="admin:panel")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

def menu_text(counts: dict[str, int], role: str | None) -> str:
    """Navbatda faqat qaror kutayotgan ariza/e'lon/chek; xatolar emas."""
    lines = ["🛠 <b>Boshqaruv paneli</b>", "━━━━━━━━━━━━━━━━━━━━", "📥 <b>Qaror kutayotganlar</b>"]
    if role in {AdminRole.ADMIN, AdminRole.SUPER}:
        lines.append(f"🛒 Arizalar: <b>{counts.get('applications', 0)}</b>")
    lines.append(f"📢 Moderatsiya: <b>{counts.get('moderation', 0)}</b>")
    if role in {AdminRole.ADMIN, AdminRole.SUPER}:
        lines.append(f"🧾 Cheklar: <b>{counts.get('payments', 0)}</b>")
    lines.append("\n👥 Guruhlar → har bir guruhning joylash/N/tozalash/xavfsizlik qoidalari alohida.")
    lines.append("🛒 Savdo · 📢 Kontent · 📊 Nazorat · ⚙️ Tizim")
    lines.append("<i>Global o'chirgich guruh qoidasini o'zgartirmaydi.</i>")
    return "\n".join(lines)


MENU_TEXT = menu_text({}, AdminRole.SUPER)  # eski importlar uchun


@router.callback_query(AdminCB.filter(F.action == "menu"))
async def show_menu(callback: CallbackQuery, role: str | None, session: AsyncSession) -> None:
    """Asosiy panel ekranini ko'rsatish/yangilash."""
    counts = await get_menu_counts(session)
    await render(callback, menu_text(counts, role), admin_main_kb(role, counts))
    await alert(callback, "")


@router.callback_query(AdminCB.filter(F.action == "hub"))
async def open_hub(callback: CallbackQuery, callback_data: AdminCB,
                   role: str | None, session: AsyncSession) -> None:
    key = callback_data.value
    if key not in HUB_SECTIONS or (key == "sales" and role == AdminRole.MODERATOR):
        await alert(callback, "⛔️ Bo'lim mavjud emas yoki ruxsat yo'q.", show=True)
        return
    counts = await get_menu_counts(session)
    title, _ = HUB_SECTIONS[key]
    text = f"{title} — <b>bo'limlar</b>\n\n"
    if key == "system":
        text += ("Global pauza (⚙️ Sozlamalar) <b>guruh qoidalarini o'zgartirmaydi</b>. "
                 "Pullik interval tarifda, bepul interval alohida bepul rejada sozlanadi.")
    else:
        text += "Kerakli tugmani tanlang; eski bo'limlar va huquq tekshiruvlari saqlangan."
    await render(callback, text, admin_hub_kb(key, role, counts))
    await alert(callback, "")


@router.callback_query(AdminCB.filter(F.action == "all"))
async def open_all(callback: CallbackQuery, role: str | None) -> None:
    await render(callback, "📚 <b>Barcha tayyor bo'limlar</b>\nEski tugmalar ham ishlaydi.",
                 admin_all_sections_kb(role))
    await alert(callback, "")


@router.callback_query(AdminCB.filter(F.action == "audit"))
async def open_audit(callback: CallbackQuery, role: str | None, session: AsyncSession) -> None:
    if role not in {AdminRole.ADMIN, AdminRole.SUPER}:
        await alert(callback, "⛔️ Harakatlar tarixini faqat admin ko'radi.", show=True)
        return
    history = (await session.execute(select(ActionLog).order_by(ActionLog.id.desc()).limit(15))).scalars().all()
    lines = ["📋 <b>Harakatlar tarixi</b> (oxirgi 15 amal)"]
    lines += [f"{fmt_dt(row.created_at)} · {row.actor_id or 'tizim'} · "
              f"{escape_html(row.action)} · {escape_html(row.entity or '—')} #{row.entity_id or '—'}"
              for row in history]
    if not history:
        lines.append("Hali harakat yo'q.")
    await render(callback, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Nazorat", callback_data=AdminCB(action="hub", value="control").pack())
    ]]))
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
    # Eski `adm:section` callback ham UI'ni chetlab o'tmasin: ro'yxatni
    # to'g'ridan-to'g'ri render qilish ichki router filtrini ishlatmaydi.
    if (
        key in {"applications", "sellers", "tariffs", "payments", "referral", "broadcast", "errors"}
        and role not in {AdminRole.ADMIN, AdminRole.SUPER}
    ):
        await alert(callback, "⛔️ Bu bo'lim faqat admin uchun.", show=True)
        return

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

    if key == "applications":
        if role not in {AdminRole.ADMIN, AdminRole.SUPER}:
            await alert(callback, "⛔️ Arizalarni faqat admin ko'radi.", show=True)
            return
        from app.handlers.applications import render_admin_list

        await render_admin_list(callback, session)
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

    if key == "free_moderation":
        from app.handlers.admin.free_ads import render_pending

        await render_pending(callback, session)
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
