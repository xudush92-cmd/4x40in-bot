"""Phase 8: faqat admin ko'radigan xato jurnali va hal qilish."""

from __future__ import annotations

from math import ceil

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole
from app.filters import IsAdmin
from app.keyboards.callbacks import AdminCB, ErrorCB
from app.services import error_service
from app.utils.text import escape_html, truncate
from app.utils.tg import alert, render
from app.utils.time import fmt_dt

router = Router(name="admin:errors")
router.callback_query.filter(IsAdmin())


def _allowed(role: str | None) -> bool:
    return role in (AdminRole.ADMIN, AdminRole.SUPER)


def _btn(label: str, action: str, error_id: int = 0, value: str = "open",
         page: int = 0) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=label, callback_data=ErrorCB(
        action=action, error_id=error_id, value=value, page=page,
    ).pack())


async def render_list(target: CallbackQuery | Message, session: AsyncSession,
                      *, status: str = "open", page: int = 0) -> None:
    if status not in error_service.FILTERS:
        status = "open"
    rows, total = await error_service.list_errors(session, status=status, page=0)
    pages = max(1, ceil(total / 8))
    page = max(0, min(page, pages - 1))
    if page:
        rows, _ = await error_service.list_errors(session, status=status, page=page)
    text = f"⚠️ <b>Xatolar jurnali</b> · {status} · {total} yozuv · {page + 1}/{pages}\n"
    text += "Har xato alohida ko'riladi; loglar avtomatik takrorlanmaydi."
    buttons = [[_btn(f"{'🔴' if item.is_critical else '🐛'} #{item.id} {truncate(item.source, 18)} "
                     f"· {truncate(item.message, 27)}", "card", item.id, status, page)]
               for item in rows]
    for filter_name, label in (("open", "⏳ Ochiq"), ("critical", "🔴 Kritik"),
                               ("resolved", "✅ Hal qilingan"), ("all", "📚 Hammasi")):
        if filter_name != status:
            buttons.append([_btn(label, "list", value=filter_name)])
    nav = []
    if page:
        nav.append(_btn("◀️", "list", value=status, page=page - 1))
    if page + 1 < pages:
        nav.append(_btn("▶️", "list", value=status, page=page + 1))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="◀️ Panel", callback_data=AdminCB(action="menu").pack())])
    await render(target, text, InlineKeyboardMarkup(inline_keyboard=buttons))


async def render_card(callback: CallbackQuery, session: AsyncSession, error_id: int,
                      status: str, page: int) -> None:
    from app.db.models import ErrorLog

    item = await session.get(ErrorLog, error_id)
    if item is None:
        await alert(callback, "Xato topilmadi.", show=True)
        return
    text = (f"⚠️ <b>Xato #{item.id}</b> · {'hal qilingan' if item.resolved_at else 'ochiq'}\n"
            f"📅 {fmt_dt(item.created_at)} · {escape_html(item.level)}\n"
            f"Manba: <code>{escape_html(item.source)}</code>\n"
            f"Guruh: {item.group_id or '—'} · user: {item.user_id or '—'}\n"
            f"Kritik: {'ha' if item.is_critical else 'yo‘q'}\n"
            f"<b>Izoh:</b> <pre>{escape_html(truncate(item.message, 250))}</pre>")
    if item.traceback:
        text += f"\n<b>Traceback:</b> <pre>{escape_html(truncate(item.traceback, 330))}</pre>"
    if item.context:
        text += f"\n<b>Kontekst:</b> <pre>{escape_html(truncate(str(item.context), 100))}</pre>"
    if item.resolved_at:
        text += f"\n✅ {fmt_dt(item.resolved_at)}, admin {item.resolved_by or '—'}"
    buttons = []
    if item.resolved_at is None:
        buttons.append([_btn("✅ Hal qilindi", "resolve_ask", error_id, status, page)])
    buttons.append([_btn("◀️ Ro'yxat", "list", value=status, page=page)])
    await render(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(ErrorCB.filter(F.action == "list"))
async def list_logs(callback: CallbackQuery, callback_data: ErrorCB,
                    session: AsyncSession, role: str | None) -> None:
    if not _allowed(role):
        await alert(callback, "⛔️ Xatolarni faqat admin ko'radi.", show=True)
        return
    await render_list(callback, session, status=callback_data.value, page=callback_data.page)
    await alert(callback, "")


@router.callback_query(ErrorCB.filter(F.action == "card"))
async def card(callback: CallbackQuery, callback_data: ErrorCB, session: AsyncSession,
               role: str | None) -> None:
    if not _allowed(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    await render_card(callback, session, callback_data.error_id, callback_data.value, callback_data.page)
    await alert(callback, "")


@router.callback_query(ErrorCB.filter(F.action == "resolve_ask"))
async def ask_resolve(callback: CallbackQuery, callback_data: ErrorCB, role: str | None) -> None:
    if not _allowed(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    await render(callback, f"⚠️ Xato #{callback_data.error_id} hal qilindi deb belgilansinmi? "
                 "Bu xatoning asl sababini tuzatmaydi.", InlineKeyboardMarkup(inline_keyboard=[
                     [_btn("✅ Tasdiqlayman", "resolve", callback_data.error_id,
                           callback_data.value, callback_data.page)],
                     [_btn("◀️ Bekor", "card", callback_data.error_id,
                           callback_data.value, callback_data.page)],
                 ]))
    await alert(callback, "")


@router.callback_query(ErrorCB.filter(F.action == "resolve"))
async def resolve(callback: CallbackQuery, callback_data: ErrorCB, session: AsyncSession,
                  role: str | None) -> None:
    if not _allowed(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    ok = await error_service.resolve(session, callback_data.error_id, callback.from_user.id)
    await render_card(callback, session, callback_data.error_id, callback_data.value, callback_data.page)
    await alert(callback, "✅ Hal qilindi" if ok else "Allaqachon hal qilingan", show=True)
