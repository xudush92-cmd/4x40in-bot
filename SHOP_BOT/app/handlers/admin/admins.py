"""Faqat super admin: foydalanuvchi ID orqali admin qo'shish, rol, audit."""

from __future__ import annotations

from math import ceil

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.constants import AdminRole
from app.db.models import ActionLog, Admin
from app.filters import IsSuperAdmin
from app.keyboards.callbacks import AdminCB, AdminOpsCB
from app.services import admin_service
from app.states import AdminOpsStates
from app.utils.text import escape_html, truncate
from app.utils.tg import alert, render
from app.utils.time import fmt_dt

router = Router(name="admin:admins")
router.message.filter(IsSuperAdmin())
router.callback_query.filter(IsSuperAdmin())

_ROLES = {AdminRole.SUPER: "👑 Super", AdminRole.ADMIN: "🛠 Admin",
          AdminRole.MODERATOR: "✅ Moderator"}


def _btn(label: str, action: str, admin_id: int = 0, value: str = "-",
         page: int = 0) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=label, callback_data=AdminOpsCB(
        action=action, admin_id=admin_id, value=value, page=page,
    ).pack())


async def render_home(target: CallbackQuery | Message, session: AsyncSession,
                      page: int = 0) -> None:
    count = int((await session.execute(select(func.count(Admin.id)))).scalar_one())
    pages = max(1, ceil(count / 10))
    page = min(max(0, page), pages - 1)
    listing = (await session.execute(select(Admin).order_by(Admin.is_active.desc(), Admin.id)
                                     .offset(page * 10).limit(10))).scalars().all()
    rows = [[_btn(f"{'🟢' if a.is_active else '⏸'} {_ROLES.get(a.role, a.role)} "
                  f"· {a.user_id} {truncate(a.title or '', 16)}", "card", a.user_id, page=page)]
            for a in listing]
    rows += [[_btn("➕ Admin qo'shish", "add"), _btn("📋 Amallar tarixi", "logs")]]
    nav = []
    if page:
        nav.append(_btn("◀️", "home", page=page - 1))
    if page + 1 < pages:
        nav.append(_btn("▶️", "home", page=page + 1))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="◀️ Panel", callback_data=AdminCB(action="menu").pack())])
    await render(target, f"👑 <b>Adminlarni boshqarish</b> · {count} ta · {page + 1}/{pages}\n"
                 "Rollar: super (hammasi), admin (kontent/moliyaviy panel), "
                 "moderator (moderatsiya; ayrim bo'limlar faqat ko'rish). O'zini va .env superini "
                 "o'chirib bo'lmaydi; barcha o'zgarishlar auditda.",
                 InlineKeyboardMarkup(inline_keyboard=rows))


async def render_card(target: CallbackQuery, session: AsyncSession, admin_id: int,
                      page: int = 0) -> None:
    row = (await session.execute(select(Admin).where(Admin.user_id == admin_id))).scalar_one_or_none()
    if row is None:
        await alert(target, "Admin topilmadi.", show=True)
        return
    text = (f"👑 <b>Admin {row.user_id}</b> · {_ROLES.get(row.role, row.role)}\n"
            f"Holat: {'🟢 faol' if row.is_active else '⏸ nofaol'}\n"
            f"Nomi: {escape_html(row.title or '—')} · qo'shgan: {row.added_by or '—'}\n"
            f"Qo'shilgan: {fmt_dt(row.created_at)}\n"
            f"Oxirgi kirish: {fmt_dt(row.last_seen_at)}\n"
            f".env boshqaruvida: {'ha — himoyalangan' if row.user_id in get_settings().admin_ids else 'yo‘q'}")
    rows = []
    if row.is_active and row.user_id not in get_settings().admin_ids:
        rows += [[_btn(f"{_ROLES[role]} rolini berish", "role_ask", row.user_id, role, page)]
                 for role in (AdminRole.SUPER, AdminRole.ADMIN, AdminRole.MODERATOR)
                 if role != row.role]
        rows.append([_btn("🚫 Adminlikdan chiqarish", "stop_ask", row.user_id, page=page)])
    elif not row.is_active:
        rows.append([_btn("▶️ Qayta qo'shish", "add_existing", row.user_id, page=page)])
    rows.append([_btn("◀️ Adminlar", "home", page=page)])
    await render(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(AdminOpsCB.filter(F.action == "home"))
async def home(callback: CallbackQuery, callback_data: AdminOpsCB, session: AsyncSession) -> None:
    await render_home(callback, session, callback_data.page)
    await alert(callback, "")


@router.callback_query(AdminOpsCB.filter(F.action == "card"))
async def card(callback: CallbackQuery, callback_data: AdminOpsCB, session: AsyncSession) -> None:
    await render_card(callback, session, callback_data.admin_id, callback_data.page)
    await alert(callback, "")


@router.callback_query(AdminOpsCB.filter(F.action == "add"))
async def start_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminOpsStates.waiting_user_id)
    await render(callback, "➕ Yangi adminning <b>Telegram raqamli ID</b>sini yuboring.\n"
                 "Bu odam botga /start bosgan bo'lishi kerak; "
                 "tegishli rol keyingi qadamda tanlanadi.\n/cancel — bekor qilish.")
    await alert(callback, "")


@router.message(StateFilter(AdminOpsStates), Command("cancel"))
async def cancel(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await render_home(message, session)


@router.message(StateFilter(AdminOpsStates.waiting_user_id))
async def read_user_id(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or not 0 < int(raw) < 2**63:
        await message.answer("⚠️ Faqat musbat Telegram ID yuboring. /cancel — bekor qilish.")
        return
    await state.update_data(admin_id=int(raw))
    await state.set_state(AdminOpsStates.waiting_role)
    await message.answer(f"👑 <code>{raw}</code> uchun rolni tanlang:",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                             [_btn(label, "add_role", value=role)] for role, label in _ROLES.items()
                         ]))


@router.callback_query(AdminOpsCB.filter(F.action.in_({"add_role", "add_existing"})))
async def choose_role(callback: CallbackQuery, callback_data: AdminOpsCB,
                      state: FSMContext, session: AsyncSession) -> None:
    if callback_data.action == "add_role":
        if await state.get_state() != AdminOpsStates.waiting_role.state:
            await alert(callback, "Avval foydalanuvchi ID sini yuboring.", show=True)
            return
        admin_id = int((await state.get_data()).get("admin_id") or 0)
        role = callback_data.value
    else:
        row = (await session.execute(select(Admin).where(Admin.user_id == callback_data.admin_id)))\
            .scalar_one_or_none()
        if row is None or row.is_active:
            await alert(callback, "Bu admin allaqachon faol yoki topilmadi.", show=True)
            return
        admin_id, role = row.user_id, row.role
        await state.set_state(AdminOpsStates.waiting_role)
        await state.update_data(admin_id=admin_id)
    if role not in _ROLES:
        await alert(callback, "Rol noto'g'ri.", show=True)
        return
    await render(callback, f"⚠️ <b>Admin qo'shishni tasdiqlang</b>\n"
                 f"ID: <code>{admin_id}</code> · rol: {_ROLES[role]}\n"
                 "Yangi admin avval botga shaxsiy /start bosishi kerak.",
                 InlineKeyboardMarkup(inline_keyboard=[
                     [_btn("✅ Ha, qo'shish", "add_confirm", admin_id, role)],
                     [_btn("❌ Yo'q", "home")],
                 ]))
    await alert(callback, "")


@router.callback_query(AdminOpsCB.filter(F.action == "add_confirm"))
async def confirm_add(callback: CallbackQuery, callback_data: AdminOpsCB,
                      state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    if await state.get_state() != AdminOpsStates.waiting_role.state or \
            data.get("admin_id") != callback_data.admin_id:
        await alert(callback, "Qo'shish jarayoni eskirgan.", show=True)
        return
    try:
        await admin_service.add(session, callback_data.admin_id, callback_data.value,
                                callback.from_user.id)
    except admin_service.AdminError as exc:
        await alert(callback, str(exc), show=True)
        return
    await state.clear()
    await render_card(callback, session, callback_data.admin_id)
    await alert(callback, "Admin qo'shildi.")


@router.callback_query(AdminOpsCB.filter(F.action.in_({"role_ask", "stop_ask"})))
async def ask_change(callback: CallbackQuery, callback_data: AdminOpsCB) -> None:
    action = "role_apply" if callback_data.action == "role_ask" else "stop_apply"
    await render(callback, f"⚠️ <b>Admin {callback_data.admin_id} o'zgartirilsinmi?</b>\n"
                 f"Amal: {escape_html(callback_data.value)}. Bu rol darhol kuchga kiradi.",
                 InlineKeyboardMarkup(inline_keyboard=[
                     [_btn("✅ Tasdiqlash", action, callback_data.admin_id, callback_data.value,
                           callback_data.page)],
                     [_btn("❌ Bekor", "card", callback_data.admin_id, page=callback_data.page)],
                 ]))
    await alert(callback, "")


@router.callback_query(AdminOpsCB.filter(F.action.in_({"role_apply", "stop_apply"})))
async def apply_change(callback: CallbackQuery, callback_data: AdminOpsCB,
                       session: AsyncSession) -> None:
    try:
        await admin_service.modify(session, callback_data.admin_id, callback.from_user.id,
                                   role=callback_data.value if callback_data.action == "role_apply" else None,
                                   deactivate=callback_data.action == "stop_apply")
    except admin_service.AdminError as exc:
        await alert(callback, str(exc), show=True)
        return
    await render_card(callback, session, callback_data.admin_id, callback_data.page)
    await alert(callback, "Admin huquqlari saqlandi.")


@router.callback_query(AdminOpsCB.filter(F.action == "logs"))
async def logs(callback: CallbackQuery, session: AsyncSession) -> None:
    rows = (await session.execute(select(ActionLog).where(
        ActionLog.action.in_(("admin_add", "admin_role", "admin_deactivate")),
    ).order_by(ActionLog.id.desc()).limit(15))).scalars().all()
    text = "📋 <b>Adminlar amallari tarixi</b> (oxirgi 15 ta)"
    text += "".join(f"\n{fmt_dt(row.created_at)} · {row.actor_id} → {row.entity_id}: "
                    f"{escape_html(row.action)}" for row in rows)
    if not rows:
        text += "\nHali o'zgarish yo'q."
    await render(callback, text, InlineKeyboardMarkup(inline_keyboard=[[_btn("◀️ Adminlar", "home")]]))
    await alert(callback, "")
