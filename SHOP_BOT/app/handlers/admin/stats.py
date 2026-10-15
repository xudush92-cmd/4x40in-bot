"""Kunlik/haftalik/oylik statistika, guruh kesimi va CSV eksporti."""

from __future__ import annotations

from math import ceil

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole
from app.db.models import Group
from app.filters import IsAdmin
from app.keyboards.callbacks import AdminCB, StatsCB
from app.services import report_service
from app.services.stats_service import format_overview, get_overview
from app.utils.text import escape_html, truncate
from app.utils.tg import alert, render

router = Router(name="admin:stats")
router.callback_query.filter(IsAdmin())


def _btn(label: str, action: str, group_id: int = 0,
         days: int = 7, page: int = 0) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=label, callback_data=StatsCB(
        action=action, group_id=group_id, days=days, page=page,
    ).pack())


def _periods(group_id: int = 0) -> list[list[InlineKeyboardButton]]:
    return [[_btn("📅 Kunlik (kecha)", "trend", group_id, 1),
             _btn("📊 Haftalik (7 kun)", "trend", group_id, 7)],
            [_btn("📈 Oylik (30 kun)", "trend", group_id, 30)]]


async def render_home(callback: CallbackQuery, session: AsyncSession,
                      role: str | None) -> None:
    overview = await get_overview(session)
    text = format_overview(overview)
    text += ("\n\n<i>Grafiklar: yakunlangan lokal kunlar; kechagi kun "
             "soat 00:10 dan keyin jamlanadi. Guruh daromadi hisoblanmaydi: "
             "to'lov chekida guruh tanlanmaydi.</i>")
    rows = _periods()
    rows += [[_btn("👥 Guruhlar kesimi", "groups")]]
    if role in (AdminRole.ADMIN, AdminRole.SUPER):
        rows += [[_btn("📥 7 kunlik CSV (barchasi)", "csv", days=7),
                  _btn("📥 30 kunlik CSV", "csv", days=30)]]
    rows.append([InlineKeyboardButton(text="◀️ Panel", callback_data=AdminCB(action="menu").pack())])
    await render(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(StatsCB.filter(F.action == "home"))
async def home(callback: CallbackQuery, session: AsyncSession, role: str | None) -> None:
    await render_home(callback, session, role)
    await alert(callback, "")


@router.callback_query(StatsCB.filter(F.action == "groups"))
async def groups(callback: CallbackQuery, callback_data: StatsCB,
                 session: AsyncSession) -> None:
    total = int((await session.execute(select(func.count(Group.id)))).scalar_one())
    pages = max(1, ceil(total / 8))
    page = min(max(0, callback_data.page), pages - 1)
    listing = (await session.execute(select(Group).order_by(Group.id)
                                     .offset(page * 8).limit(8))).scalars().all()
    rows = [[_btn(f"👥 {truncate(group.display, 38)} (#{group.id})", "trend", group.id, 7)]
            for group in listing]
    nav = []
    if page:
        nav.append(_btn("◀️", "groups", page=page - 1))
    if page + 1 < pages:
        nav.append(_btn("▶️", "groups", page=page + 1))
    if nav:
        rows.append(nav)
    rows.append([_btn("◀️ Umumiy statistika", "home")])
    await render(callback, f"👥 <b>Guruhlar kesimi</b> · {total} guruh · {page + 1}/{pages}\n"
                 "Har guruhning xabar/taklif/qoidabuzarlik grafigi mustaqil.",
                 InlineKeyboardMarkup(inline_keyboard=rows))
    await alert(callback, "")


@router.callback_query(StatsCB.filter(F.action == "trend"))
async def trend(callback: CallbackQuery, callback_data: StatsCB,
                session: AsyncSession, role: str | None) -> None:
    group_id, days = callback_data.group_id, callback_data.days
    try:
        series = await report_service.day_series(session, days, group_id)
    except ValueError as exc:
        await alert(callback, str(exc), show=True)
        return
    group = await session.get(Group, group_id) if group_id else None
    title = escape_html(group.display) if group else "Barcha guruhlar"
    label = {1: "Kunlik", 7: "Haftalik", 30: "Oylik"}[days]
    completed = sum(row is not None for row in series)
    sums = {key: sum(getattr(row, key) for row in series if row is not None)
            for key in ("posts", "joins", "leaves", "violations", "deleted_msgs")}
    amounts = sum((row.payments_amount for row in series if row is not None), start=0)
    active = next((row.active_ads for row in reversed(series) if row is not None), 0)
    text = (f"📊 <b>{title} · {label} ({days} kun)</b>\n"
            f"To'liq qayd etilgan: {completed}/{days} kun\n"
            f"📢 Post: <b>{sums['posts']}</b> · faol e'lon (oxirgi snapshot): <b>{active}</b>\n"
            f"👥 Hisoblangan kirish: {sums['joins']} · erta chiqish: {sums['leaves']}\n"
            f"🛡 Qoidabuzarlik: {sums['violations']} · logdagi o'chirish: {sums['deleted_msgs']}\n")
    if group_id == 0:
        text += f"💰 Tasdiqlangan bank to'lovi: <b>{amounts:,.0f} UZS</b>\n".replace(",", " ")
    text += ("\n<b>Kunlik grafik (chapdan o'ngga):</b>\n"
             f"📢 {report_service.sparkline([row.posts if row else 0 for row in series])}\n"
             f"👥 {report_service.sparkline([row.joins if row else 0 for row in series])}\n"
             f"🛡 {report_service.sparkline([row.violations if row else 0 for row in series])}\n"
             "<i>· = 0 yoki jamlanmagan kun; oxirgi kunlar chapdan o'ngga ketadi.</i>")
    if days <= 7:
        text += "\n\n" + "\n".join(
            f"{row.day:%d.%m}: {row.posts} post / {row.violations} buzilish"
            for row in series if row is not None
        )
    rows = _periods(group_id)
    if role in (AdminRole.ADMIN, AdminRole.SUPER):
        rows.append([_btn(f"📥 {days} kun CSV", "csv", group_id, days)])
    rows.append([_btn("◀️ Guruhlar" if group_id else "◀️ Umumiy", "groups" if group_id else "home")])
    await render(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))
    await alert(callback, "")


@router.callback_query(StatsCB.filter(F.action == "csv"))
async def export_csv(callback: CallbackQuery, callback_data: StatsCB,
                     session: AsyncSession, role: str | None) -> None:
    if role not in (AdminRole.ADMIN, AdminRole.SUPER):
        await alert(callback, "⛔️ Moliyaviy eksport faqat admin uchun.", show=True)
        return
    try:
        data = await report_service.csv_export(
            session, callback_data.days,
            group_id=callback_data.group_id if callback_data.group_id else None,
        )
    except ValueError as exc:
        await alert(callback, str(exc), show=True)
        return
    filename = f"hisobot_{callback_data.days}kun_{callback_data.group_id or 'barchasi'}.csv"
    await callback.message.answer_document(
        BufferedInputFile(data, filename=filename),
        caption="📥 Yakunlangan kunlar (CSV, UTF-8). Tasdiqlangan bank to'lovi faqat umumiy satrda.",
    )
    await alert(callback, "Hisobot yuborildi.")
