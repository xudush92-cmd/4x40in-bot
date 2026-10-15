"""Phase 6: guruh/global istisnolari va foydalanuvchining jazo tarixi."""

from __future__ import annotations

from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.constants import AdminRole
from app.db.models import (
    ActionLog,
    Admin,
    Group,
    GroupAdmin,
    Permission,
    Restriction,
    User,
    Violation,
    Warning,
)
from app.filters import IsAdmin
from app.keyboards.callbacks import AdminCB, PolicyCB
from app.keyboards.policy import (
    PERMISSION_LABELS,
    confirm_kb,
    permission_kb,
    permission_types_kb,
)
from app.services import group_policy_service as policy
from app.services import group_service
from app.services.settings_service import settings_service
from app.states import AdminPolicyStates
from app.utils.text import clean_text, escape_html, truncate
from app.utils.tg import alert, render
from app.utils.time import fmt_dt, utcnow

router = Router(name="admin:permissions")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


def _can_edit(role: str | None) -> bool:
    return role in (AdminRole.ADMIN, AdminRole.SUPER)


def _btn(text: str, action: str, gid: int = 0, value: str = "-") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=PolicyCB(
        action=action, group_id=gid, value=value,
    ).pack())


async def render_permissions(target: CallbackQuery | Message, session: AsyncSession,
                             group_id: int, role: str | None) -> None:
    group = await group_service.get_group(session, group_id) if group_id else None
    if group_id and group is None:
        await render(target, "⚠️ Guruh topilmadi.")
        return
    conditions = (or_(Permission.group_id == group_id, Permission.group_id.is_(None))
                  if group_id else Permission.group_id.is_(None))
    entries = list((await session.execute(select(Permission).where(
        Permission.is_active.is_(True),
        or_(Permission.expires_at.is_(None), Permission.expires_at > utcnow()),
        conditions,
    ).order_by(Permission.id.desc()).limit(12))).scalars().all())
    title = f"{escape_html(group.display)} (+ global)" if group else "🌐 barcha guruhlar"
    text = f"🔑 <b>Ruxsatlar: {title}</b>\n\n"
    if entries:
        for p in entries:
            expires = fmt_dt(p.expires_at) if p.expires_at else "doimiy"
            text += (f"• #{p.id} · <code>{p.user_id}</code> · "
                     f"{escape_html(PERMISSION_LABELS.get(p.kind, p.kind))} "
                     f"({'🌐 global' if p.group_id is None else 'faqat shu guruh'})\n"
                     f"  📅 {expires} · sabab: {escape_html(truncate(p.reason, 65))}\n")
    else:
        text += "Hozir faol ruxsat yo‘q."
    text += "\n<i>Muddati tugagan ruxsat avtomatik kuchini yo‘qotadi; qaytarib olish alohida qayd qilinadi.</i>"
    await render(target, text, permission_kb(group_id, entries, can_edit=_can_edit(role)))


@router.callback_query(PolicyCB.filter(F.action == "perm"))
async def list_permissions(callback: CallbackQuery, callback_data: PolicyCB,
                           session: AsyncSession, role: str | None) -> None:
    await render_permissions(callback, session, callback_data.group_id, role)
    await alert(callback, "")


@router.callback_query(PolicyCB.filter(F.action == "perm_add"))
async def start_grant(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
                      state: FSMContext, role: str | None) -> None:
    if not _can_edit(role):
        await alert(callback, "⛔️ Ruxsatni faqat admin beradi.", show=True)
        return
    gid = callback_data.group_id
    if gid and await group_service.get_group(session, gid) is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    await state.clear()
    await state.set_state(AdminPolicyStates.waiting_permission_user)
    await state.update_data(policy_group_id=gid)
    await render(callback, "🔑 <b>Ruxsat berish</b>\n\n"
                 f"Qamrov: {'🌐 barcha guruhlar' if gid == 0 else f'guruh #{gid}'}\n"
                 "Foydalanuvchining <b>raqamli Telegram ID</b>sini yuboring.\n"
                 "Bekor qilish: /cancel")
    await alert(callback, "")


@router.message(StateFilter(AdminPolicyStates.waiting_permission_user), F.text)
async def grant_user(message: Message, state: FSMContext, session: AsyncSession,
                     role: str | None) -> None:
    if message.text and message.text.startswith("/cancel"):
        await cancel_grant(message, state, session, role)
        return
    if not _can_edit(role):
        await state.clear()
        return
    raw = (message.text or "").strip()
    if not raw.isascii() or not raw.isdigit() or not 0 < int(raw) < 10**17:
        await message.answer("⚠️ To'g'ri musbat Telegram ID kiriting. /cancel")
        return
    data = await state.get_data()
    await state.update_data(policy_user_id=int(raw))
    await state.set_state(AdminPolicyStates.waiting_permission_kind)
    await message.answer(f"👤 <code>{raw}</code> uchun <b>ruxsat turini tanlang</b>:",
                         reply_markup=permission_types_kb(int(data.get("policy_group_id") or 0)))


@router.callback_query(PolicyCB.filter(F.action == "perm_kind"),
                       StateFilter(AdminPolicyStates.waiting_permission_kind))
async def grant_kind(callback: CallbackQuery, callback_data: PolicyCB, state: FSMContext,
                     role: str | None) -> None:
    if not _can_edit(role) or callback_data.value not in PERMISSION_LABELS or callback_data.value == "counter_exempt":
        await alert(callback, "⚠️ Ruxsat yo'q yoki Phase 7 talabidir.", show=True)
        return
    data = await state.get_data()
    if callback_data.group_id != int(data.get("policy_group_id") or 0) or not data.get("policy_user_id"):
        await alert(callback, "⚠️ Eskirgan tugma.", show=True)
        return
    await state.update_data(policy_kind=callback_data.value)
    await state.set_state(AdminPolicyStates.waiting_permission_days)
    await render(callback, "📅 <b>Ruxsat muddati</b>\n"
                 "1–365 kun yuboring. <code>0</code> = doimiy.\n"
                 "Masalan: <code>7</code>\nBekor qilish: /cancel")
    await alert(callback, "")


@router.message(StateFilter(AdminPolicyStates.waiting_permission_days), F.text)
async def grant_days(message: Message, state: FSMContext, session: AsyncSession,
                     role: str | None) -> None:
    if message.text and message.text.startswith("/cancel"):
        await cancel_grant(message, state, session, role)
        return
    if not _can_edit(role):
        await state.clear()
        return
    raw = (message.text or "").strip()
    if not raw.isascii() or not raw.isdigit() or not 0 <= int(raw) <= 365:
        await message.answer("⚠️ 0–365 kun raqam kiriting. /cancel")
        return
    await state.update_data(policy_days=int(raw))
    await state.set_state(AdminPolicyStates.waiting_permission_reason)
    await message.answer("✍️ <b>Sababni yuboring</b> (3–255 belgi). \nBekor qilish: /cancel")


@router.message(StateFilter(AdminPolicyStates.waiting_permission_reason), F.text)
async def grant_reason(message: Message, state: FSMContext, session: AsyncSession,
                       role: str | None) -> None:
    if message.text and message.text.startswith("/cancel"):
        await cancel_grant(message, state, session, role)
        return
    if not _can_edit(role):
        await state.clear()
        return
    reason = clean_text(message.text)
    if not reason or not 3 <= len(reason) <= 255:
        await message.answer("⚠️ Sabab 3–255 belgidan iborat bo'lishi kerak. /cancel")
        return
    data = await state.get_data()
    if "policy_user_id" not in data or "policy_kind" not in data:
        await state.clear()
        return
    await state.update_data(policy_reason=reason)
    await state.set_state(AdminPolicyStates.confirming_permission)
    gid = int(data.get("policy_group_id") or 0)
    await message.answer(
        "🔑 <b>RUXSATNI TASDIQLANG</b>\n\n"
        f"Foydalanuvchi: <code>{data['policy_user_id']}</code>\n"
        f"Guruh: <b>{gid if gid else '🌐 barcha guruhlar'}</b>\n"
        f"Turi: <b>{escape_html(PERMISSION_LABELS[data['policy_kind']])}</b>\n"
        f"Muddat: <b>{data.get('policy_days') or 'doimiy'}"
        f"{' kun' if data.get('policy_days') else ''}</b>\n"
        f"Sabab: {escape_html(reason)}",
        reply_markup=confirm_kb("perm_confirm", gid, "-", "-", cancel_action="perm_cancel"),
    )


@router.callback_query(PolicyCB.filter(F.action == "perm_confirm"),
                       StateFilter(AdminPolicyStates.confirming_permission))
async def confirm_grant(callback: CallbackQuery, callback_data: PolicyCB,
                        state: FSMContext, session: AsyncSession, role: str | None) -> None:
    if not _can_edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    data = await state.get_data()
    gid = int(data.get("policy_group_id") or 0)
    if callback_data.group_id != gid or not data.get("policy_user_id") or not data.get("policy_reason"):
        await alert(callback, "⚠️ Eskirgan tugma.", show=True)
        return
    try:
        entry = await policy.grant_permission(
            session, group_id=gid or None, user_id=int(data["policy_user_id"]),
            kind=str(data["policy_kind"]), days=int(data.get("policy_days") or 0) or None,
            reason=str(data["policy_reason"]), actor_id=callback.from_user.id,
        )
    except ValueError as exc:
        await alert(callback, str(exc), show=True)
        return
    await state.clear()
    await render_permissions(callback, session, gid, role)
    await alert(callback, f"✅ Ruxsat #{entry.id} saqlandi.", show=True)


@router.callback_query(PolicyCB.filter(F.action == "perm_revoke"))
async def ask_revoke(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
                     role: str | None) -> None:
    if not _can_edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    if not callback_data.value.isdigit():
        return
    entry = await session.get(Permission, int(callback_data.value))
    if entry is None or not entry.is_active or entry.group_id != (callback_data.group_id or None):
        await alert(callback, "⚠️ Ruxsat topilmadi yoki boshqa guruhga tegishli.", show=True)
        return
    await render(callback, f"❌ <b>Ruxsatni qaytarib olishni tasdiqlang</b>\n\n"
                 f"#{entry.id} · foydalanuvchi <code>{entry.user_id}</code>\n"
                 f"{escape_html(PERMISSION_LABELS.get(entry.kind, entry.kind))} · "
                 f"{'🌐 global' if entry.group_id is None else f'guruh #{entry.group_id}'}\n"
                 f"Sabab: {escape_html(entry.reason)}",
                 confirm_kb("perm_revoke_confirm", callback_data.group_id,
                            str(entry.id), "-", cancel_action="perm"))
    await alert(callback, "")


@router.callback_query(PolicyCB.filter(F.action == "perm_revoke_confirm"))
async def confirm_revoke(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
                         role: str | None) -> None:
    if not _can_edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    if not callback_data.value.isdigit():
        return
    entry = await session.get(Permission, int(callback_data.value))
    if entry is None or entry.group_id != (callback_data.group_id or None):
        await alert(callback, "⚠️ Ruxsat topilmadi.", show=True)
        return
    await policy.revoke_permission(session, entry, callback.from_user.id)
    await render_permissions(callback, session, callback_data.group_id, role)
    await alert(callback, "✅ Ruxsat qaytarib olindi.", show=True)


@router.callback_query(PolicyCB.filter(F.action == "perm_cancel"))
async def cancel_permission_callback(callback: CallbackQuery, callback_data: PolicyCB,
                                     state: FSMContext, session: AsyncSession,
                                     role: str | None) -> None:
    await state.clear()
    await render_permissions(callback, session, callback_data.group_id, role)
    await alert(callback, "")


@router.message(StateFilter(
    AdminPolicyStates.waiting_permission_user,
    AdminPolicyStates.waiting_permission_kind,
    AdminPolicyStates.waiting_permission_days,
    AdminPolicyStates.waiting_permission_reason,
    AdminPolicyStates.confirming_permission,
), Command("cancel"))
async def cancel_grant(message: Message, state: FSMContext, session: AsyncSession,
                       role: str | None) -> None:
    data = await state.get_data()
    await state.clear()
    await render_permissions(message, session, int(data.get("policy_group_id") or 0), role)


# ─────────────────────── Foydalanuvchi ko'rinishi ───────────────────
async def render_user(target: CallbackQuery | Message, session: AsyncSession,
                      user_id: int, group_id: int, role: str | None) -> None:
    user = await session.get(User, user_id)
    group = await group_service.get_group(session, group_id) if group_id else None
    if group_id and group is None:
        await render(target, "⚠️ Guruh topilmadi.")
        return
    filter_group = (Warning.group_id == group_id,) if group_id else ()
    warnings = (await session.execute(select(Warning).where(
        Warning.user_id == user_id, *filter_group,
    ).order_by(Warning.group_id).limit(10))).scalars().all()
    restrictions = (await session.execute(select(Restriction).where(
        Restriction.user_id == user_id, Restriction.is_active.is_(True),
        or_(Restriction.until_at.is_(None), Restriction.until_at > utcnow()),
        *((Restriction.group_id == group_id,) if group_id else ()),
    ).order_by(Restriction.id.desc()).limit(10))).scalars().all()
    violations = (await session.execute(select(Violation).where(
        Violation.user_id == user_id,
        *((Violation.group_id == group_id,) if group_id else ()),
    ).order_by(Violation.id.desc()).limit(8))).scalars().all()
    label = f"{escape_html(group.display)}" if group else "🌐 barcha guruhlar"
    text = (f"👤 <b>Foydalanuvchi: {user_id}</b> · {label}\n"
            f"Profil: {escape_html(user.first_name) if user else 'botga kirmagan'}\n\n"
            "<b>Ogohlantirishlar (guruh bo‘yicha):</b>\n")
    text += "\n".join(f"• #{w.group_id}: {w.count} ta ({fmt_dt(w.last_at)})" for w in warnings) or "—"
    text += "\n\n<b>Faol cheklovlar:</b>\n"
    text += "\n".join(f"• #{r.id} · guruh #{r.group_id} · {r.kind} · "
                      f"{fmt_dt(r.until_at) if r.until_at else 'doimiy'} · "
                      f"{escape_html(truncate(r.reason, 70))}"
                      for r in restrictions) or "—"
    text += "\n\n<b>Qoidabuzarliklar:</b>\n"
    text += "\n".join(f"• {fmt_dt(v.created_at)} · guruh #{v.group_id} · {v.kind} "
                      f"· {v.action or '—'}{' 🧪' if v.is_dry_run else ''}"
                      for v in violations) or "—"
    rows: list[list[InlineKeyboardButton]] = []
    if _can_edit(role):
        rows.extend([[_btn(f"✅ #{r.id} {r.kind}ni bekor qilish", "lift_ask", r.group_id, str(r.id))]
                     for r in restrictions])
        if group:
            rows.append([_btn("⏱ Qo'lda mute (10 min)", "manual_ask", group.id, f"{user_id}.mute"),
                         _btn("🚫 Qo'lda ban", "manual_ask", group.id, f"{user_id}.ban")])
            if any(w.count for w in warnings):
                rows.append([_btn("♻️ Ogohlantirishni nollash", "warning_ask", group.id, str(user_id))])
    if group:
        rows.append([_btn("🛡 Guruh siyosati", "home", group.id, "guard")])
    else:
        # Guruh kontekstiga kirish uchun aynan qoidabuzarlik bo'lgan guruhlar.
        for gid in dict.fromkeys([*(w.group_id for w in warnings), *(v.group_id for v in violations)]):
            rows.append([_btn(f"👥 Guruh #{gid}da ko'rish", "user_profile", gid, str(user_id))])
    rows.extend([[_btn("🔄 Yangilash", "user_profile", group_id, str(user_id))],
                 [InlineKeyboardButton(text="◀️ Boshqaruv paneli", callback_data=AdminCB(action="menu").pack())]])
    await render(target, text[:3900], InlineKeyboardMarkup(inline_keyboard=rows))


async def render_users_home(target: CallbackQuery | Message, session: AsyncSession) -> None:
    restrictions = (await session.execute(select(Restriction).where(
        Restriction.is_active.is_(True),
        or_(Restriction.until_at.is_(None), Restriction.until_at > utcnow()),
    ).order_by(Restriction.id.desc()).limit(10))).scalars().all()
    text = ("👤 <b>Foydalanuvchilar / jazo tarixi</b>\n\n"
            "Telegram raqamli ID bo‘yicha qidiring yoki faol mute/ban ro'yxatidan tanlang. "
            "Qo'lda jazo faqat guruh tanlanib, alohida tasdiqlangandan keyin beriladi.\n\n"
            "<b>Faol cheklovlar:</b>\n")
    text += "\n".join(
        f"• <code>{r.user_id}</code> · guruh #{r.group_id} · {r.kind} "
        f"· {escape_html(truncate(r.reason, 55))}" for r in restrictions
    ) or "—"
    rows = [[_btn(f"👤 {r.user_id} · #{r.group_id} · {r.kind}",
                  "user_profile", r.group_id, str(r.user_id))] for r in restrictions]
    rows += [[_btn("🔍 Telegram ID bo'yicha qidirish", "user_find")],
             [_btn("🔑 Ruxsatlar", "perm")],
             [InlineKeyboardButton(text="◀️ Boshqaruv paneli", callback_data=AdminCB(action="menu").pack())]]
    await render(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(PolicyCB.filter(F.action == "users"))
async def users_home(callback: CallbackQuery, session: AsyncSession) -> None:
    await render_users_home(callback, session)
    await alert(callback, "")


@router.callback_query(PolicyCB.filter(F.action == "user_find"))
async def find_user(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
                    state: FSMContext) -> None:
    if callback_data.group_id and await group_service.get_group(session, callback_data.group_id) is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    await state.clear()
    await state.set_state(AdminPolicyStates.waiting_user_search)
    await state.update_data(policy_group_id=callback_data.group_id)
    await render(callback, "🔍 Foydalanuvchining raqamli Telegram ID sini yuboring.\n"
                 f"Qamrov: {'guruh #' + str(callback_data.group_id) if callback_data.group_id else 'barcha guruhlar'}\n"
                 "Bekor qilish: /cancel")
    await alert(callback, "")


@router.message(StateFilter(AdminPolicyStates.waiting_user_search), F.text)
async def search_user(message: Message, state: FSMContext, session: AsyncSession,
                      role: str | None) -> None:
    if message.text and message.text.startswith("/cancel"):
        await state.clear()
        await render_users_home(message, session)
        return
    raw = (message.text or "").strip()
    if not raw.isascii() or not raw.isdigit() or not 0 < int(raw) < 10**17:
        await message.answer("⚠️ Musbat Telegram ID yuboring. /cancel")
        return
    data = await state.get_data()
    await state.clear()
    await render_user(message, session, int(raw), int(data.get("policy_group_id") or 0), role)


@router.callback_query(PolicyCB.filter(F.action == "user_profile"))
async def user_profile(callback: CallbackQuery, callback_data: PolicyCB,
                       session: AsyncSession, role: str | None) -> None:
    if not callback_data.value.isascii() or not callback_data.value.isdigit():
        return
    await render_user(callback, session, int(callback_data.value), callback_data.group_id, role)
    await alert(callback, "")


# ─────────────────────── Qo'lda jazo va uni bekor qilish ────────────
async def _manual_context(session: AsyncSession, group_id: int, user_id: int) -> Group | None:
    group = await group_service.get_group(session, group_id)
    if group is None or not group.is_supergroup or not group.bot_is_admin or not group.is_active:
        return None
    if user_id <= 0 or user_id == group.tg_chat_id or user_id in get_settings().admin_ids:
        return None
    bot_admin = (await session.execute(select(Admin.id).where(
        Admin.user_id == user_id, Admin.is_active.is_(True)
    ))).scalar_one_or_none()
    local_admin = (await session.execute(select(GroupAdmin.id).where(
        GroupAdmin.group_id == group_id, GroupAdmin.user_id == user_id
    ))).scalar_one_or_none()
    return None if bot_admin or local_admin else group


@router.callback_query(PolicyCB.filter(F.action == "manual_ask"))
async def manual_ask(callback: CallbackQuery, callback_data: PolicyCB, state: FSMContext,
                     session: AsyncSession, role: str | None) -> None:
    if not _can_edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    try:
        uid, kind = callback_data.value.split(".", 1)
        user_id = int(uid)
    except ValueError:
        return
    if kind not in {"mute", "ban"} or await _manual_context(session, callback_data.group_id, user_id) is None:
        await alert(callback, "⚠️ Guruh faol emas yoki foydalanuvchi noto'g'ri.", show=True)
        return
    await state.clear()
    await state.update_data(policy_user_id=user_id, policy_group_id=callback_data.group_id,
                            policy_manual_kind=kind)
    await state.set_state(AdminPolicyStates.waiting_manual_reason)
    await render(callback, f"{kind.upper()} · foydalanuvchi <code>{user_id}</code> · "
                 f"guruh #{callback_data.group_id}\n\n"
                 "Sababni yuboring (3–255 belgi). Mute muddati 10 daqiqa; "
                 "ban doimiy. /cancel")
    await alert(callback, "")


@router.message(StateFilter(AdminPolicyStates.waiting_manual_reason), F.text)
async def manual_reason(message: Message, state: FSMContext, session: AsyncSession,
                        role: str | None) -> None:
    if message.text and message.text.startswith("/cancel"):
        await state.clear()
        await render_users_home(message, session)
        return
    if not _can_edit(role):
        await state.clear()
        return
    value = clean_text(message.text)
    if not value or not 3 <= len(value) <= 255:
        await message.answer("⚠️ 3–255 belgili sabab kerak. /cancel")
        return
    data = await state.get_data()
    if not data.get("policy_user_id") or not data.get("policy_manual_kind"):
        await state.clear()
        return
    await state.update_data(policy_manual_reason=value)
    await state.set_state(AdminPolicyStates.confirming_manual_action)
    gid, uid, kind = int(data["policy_group_id"]), int(data["policy_user_id"]), data["policy_manual_kind"]
    await message.answer(
        f"⚠️ <b>{kind.upper()} BERISHNI TASDIQLANG</b>\n"
        f"Guruh #{gid} · foydalanuvchi <code>{uid}</code>\n"
        f"Sabab: {escape_html(value)}\n"
        "Bu jonli Telegram amali. Natija noaniq bo'lsa avtomatik takrorlanmaydi.",
        reply_markup=confirm_kb("manual_confirm", gid, f"{uid}.{kind}", str(uid),
                                cancel_action="manual_cancel"),
    )


@router.callback_query(PolicyCB.filter(F.action == "manual_confirm"),
                       StateFilter(AdminPolicyStates.confirming_manual_action))
async def manual_confirm(callback: CallbackQuery, callback_data: PolicyCB, bot: Bot,
                         state: FSMContext, session: AsyncSession, role: str | None) -> None:
    if not _can_edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    data = await state.get_data()
    value = f"{data.get('policy_user_id')}.{data.get('policy_manual_kind')}"
    gid = int(data.get("policy_group_id") or 0)
    if callback_data.group_id != gid or callback_data.value != value or not data.get("policy_manual_reason"):
        await alert(callback, "⚠️ Eskirgan tugma.", show=True)
        return
    group = await _manual_context(session, gid, int(data["policy_user_id"]))
    if group is None or not (group.bot_rights or {}).get("can_restrict_members"):
        await alert(callback, "⚠️ Guruh faol emas yoki bot cheklash huquqiga ega emas.", show=True)
        return
    if not await settings_service.is_feature_enabled_fresh("guard"):
        await alert(callback, "🛑 Global switch/texnik rejimda yangi jazo taqiqlangan.", show=True)
        return
    user_id, kind, reason = int(data["policy_user_id"]), str(data["policy_manual_kind"]), str(data["policy_manual_reason"])
    await state.clear()  # takroriy tugma bosish qo'shimcha jazo bermaydi
    until = utcnow() + timedelta(minutes=10) if kind == "mute" else None
    entry = Restriction(group_id=gid, user_id=user_id, kind=kind,
                        until_at=until, reason=reason, is_active=False)
    session.add(entry)
    await session.flush()
    entry_id = entry.id
    await session.commit()  # API oldidan audit rezervatsiyasi
    try:
        member = await bot.get_chat_member(group.tg_chat_id, user_id)
        if str(member.status) in {"creator", "administrator"}:
            await alert(callback, "⚠️ Guruh adminini mute/ban qilib bo'lmaydi.", show=True)
            return
        await session.refresh(group, attribute_names=["is_active", "bot_is_admin", "bot_rights"])
        if not group.is_active or not group.bot_is_admin or not (group.bot_rights or {}).get("can_restrict_members"):
            entry.reason = f"{reason} (guruh pauza/huquq sabab bajarilmadi)"
            await alert(callback, "🛑 Guruh pauza yoki bot huquqi yo'q; jazo berilmadi.", show=True)
            return
        if not await settings_service.is_feature_enabled_fresh("guard"):
            entry.reason = f"{reason} (global pauza sabab bajarilmadi)"
            await alert(callback, "🛑 Global pauza yoqildi; jazo berilmadi.", show=True)
            return
        if kind == "ban":
            await bot.ban_chat_member(group.tg_chat_id, user_id)
        else:
            await bot.restrict_chat_member(
                group.tg_chat_id, user_id, permissions=ChatPermissions(can_send_messages=False), until_date=until,
            )
    except TelegramAPIError as exc:
        entry.reason = f"{reason} (TELEGRAM XATOSI: {str(exc)[:110]})"[:500]
        await alert(callback, "⚠️ Telegram javob bermadi; jazo qo'llanmadi/noaniq. Jurnalni tekshiring.", show=True)
        return
    entry.is_active = True
    await session.flush()
    session.add(ActionLog(actor_id=callback.from_user.id, action="manual_restrict",
                          entity="restriction", entity_id=entry_id, group_id=gid,
                          after={"user_id": user_id, "kind": kind, "reason": reason, "until": until.isoformat() if until else None}))
    await render_user(callback, session, user_id, gid, role)
    await alert(callback, f"✅ {kind.upper()} berildi.", show=True)


@router.callback_query(PolicyCB.filter(F.action == "manual_cancel"))
async def cancel_manual_callback(callback: CallbackQuery, callback_data: PolicyCB,
                                 state: FSMContext, session: AsyncSession,
                                 role: str | None) -> None:
    await state.clear()
    if callback_data.value.isdigit():
        await render_user(callback, session, int(callback_data.value), callback_data.group_id, role)
    else:
        await render_users_home(callback, session)
    await alert(callback, "")


@router.callback_query(PolicyCB.filter(F.action == "warning_ask"))
async def warning_ask(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
                      role: str | None) -> None:
    if not _can_edit(role) or not callback_data.value.isdigit():
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    count = await session.get(Warning, (callback_data.group_id, int(callback_data.value)))
    if count is None or count.count == 0:
        await alert(callback, "⚠️ Ogohlantirish topilmadi.", show=True)
        return
    await render(callback, f"♻️ <b>Ogohlantirishni 0 qilish</b>\n\n"
                 f"Guruh #{callback_data.group_id} · foydalanuvchi <code>{callback_data.value}</code> "
                 f"· avvalgi son <b>{count.count}</b>. Bu faqat shu guruh hisobini o'zgartiradi.",
                 confirm_kb("warning_confirm", callback_data.group_id, callback_data.value,
                            callback_data.value, cancel_action="user_profile"))
    await alert(callback, "")


@router.callback_query(PolicyCB.filter(F.action == "warning_confirm"))
async def warning_confirm(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
                          role: str | None) -> None:
    if not _can_edit(role) or not callback_data.value.isdigit():
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    user_id = int(callback_data.value)
    count = await session.get(Warning, (callback_data.group_id, user_id))
    if count is None or count.count == 0:
        await alert(callback, "⚠️ Ogohlantirish topilmadi.", show=True)
        return
    before = count.count
    count.count, count.last_at = 0, None
    session.add(ActionLog(actor_id=callback.from_user.id, action="warning_reset",
                          entity="warning", entity_id=user_id, group_id=callback_data.group_id,
                          before={"count": before}, after={"count": 0}))
    await session.flush()
    await render_user(callback, session, user_id, callback_data.group_id, role)
    await alert(callback, "✅ Faqat shu guruhda warning nollandi.", show=True)


@router.callback_query(PolicyCB.filter(F.action == "lift_ask"))
async def lift_ask(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
                   role: str | None) -> None:
    if not _can_edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    if not callback_data.value.isdigit():
        return
    entry = await session.get(Restriction, int(callback_data.value))
    if entry is None or not entry.is_active or entry.group_id != callback_data.group_id:
        await alert(callback, "⚠️ Cheklov topilmadi.", show=True)
        return
    await render(callback, f"✅ <b>{entry.kind}ni bekor qilish</b>\n\n"
                 f"Guruh #{entry.group_id} · foydalanuvchi <code>{entry.user_id}</code>\n"
                 "Telegram amalidan keyingina DB'da bekor qilingan deb belgilanadi.",
                 confirm_kb("lift_confirm", entry.group_id, str(entry.id), str(entry.user_id),
                            cancel_action="user_profile"))
    await alert(callback, "")


@router.callback_query(PolicyCB.filter(F.action == "lift_confirm"))
async def lift_confirm(callback: CallbackQuery, callback_data: PolicyCB, bot: Bot,
                       session: AsyncSession, role: str | None) -> None:
    if not _can_edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    if not callback_data.value.isdigit():
        return
    entry = await session.get(Restriction, int(callback_data.value))
    if entry is None or not entry.is_active or entry.group_id != callback_data.group_id:
        await alert(callback, "⚠️ Cheklov eskirgan yoki qaytarib olingan.", show=True)
        return
    group = await group_service.get_group(session, entry.group_id)
    if group is None or not group.bot_is_admin:
        await alert(callback, "⚠️ Bot admin emas.", show=True)
        return
    try:
        if entry.kind == "ban":
            await bot.unban_chat_member(group.tg_chat_id, entry.user_id, only_if_banned=True)
        elif entry.kind == "mute":
            chat = await bot.get_chat(group.tg_chat_id)
            permissions = getattr(chat, "permissions", None) or ChatPermissions(
                can_send_messages=True, can_send_audios=True, can_send_documents=True,
                can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
                can_add_web_page_previews=True,
            )
            await bot.restrict_chat_member(group.tg_chat_id, entry.user_id, permissions=permissions)
        else:
            await alert(callback, "⚠️ Bu cheklov turini hozir bekor qilib bo'lmaydi.", show=True)
            return
    except TelegramAPIError as exc:
        await alert(callback, f"⚠️ Telegram xatosi: {truncate(str(exc), 90)}", show=True)
        return
    entry.is_active = False
    entry.lifted_at, entry.lifted_by = utcnow(), callback.from_user.id
    await session.flush()
    session.add(ActionLog(actor_id=callback.from_user.id, action="restriction_lift",
                          entity="restriction", entity_id=entry.id, group_id=entry.group_id,
                          before={"kind": entry.kind, "user_id": entry.user_id, "active": True},
                          after={"active": False}))
    await render_user(callback, session, entry.user_id, entry.group_id, role)
    await alert(callback, "✅ Cheklov bekor qilindi.", show=True)


__all__ = ["router", "render_permissions", "render_user", "render_users_home"]
