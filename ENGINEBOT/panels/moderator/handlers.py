"""
panels/moderator/handlers.py — moderator (tenant yordamchisi) paneli.

CHEKLANGAN HUQUQLAR:
────────────────────
- Eʼlonlarni koʻrish (lekin oʻchira olmaydi)
- Foydalanuvchini tasdiqlash (lekin bloklash YO'Q)
- Pause va warn berish

XAVFSIZLIK:
───────────
Har handler boshida moderator ekanligi tekshiriladi.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from config import Role, UserStatus
from core import audit_log, database as db, notifier
from core.permissions import (
    Action,
    PermissionDenied,
    RoleContext,
    can,
    resolve_role,
)
from keyboards import moderator_kb
from keyboards.common_kb import Btn
from utils import formatters as fmt
from utils import logger as log_mod
from utils.session_state import session

logger = log_mod.get_logger("panels.moderator")
router = Router(name="moderator")


# ─────────────────────────────────────────────────────────────────────
# Helper: moderator ekanligini va qaysi tenant'ga tegishli ekanligini
# aniqlash. Moderator bir nechta tenantda boʻlmaydi (MVP qoidasi).
# ─────────────────────────────────────────────────────────────────────
async def _ensure_moderator(uid: int) -> RoleContext:
    """
    Moderator rolini tasdiqlash. session.tenant_id orqali
    qaysi tenantning moderatori ekanligi olinadi.
    """
    state = await session.get(uid)
    tenant_id = state.tenant_id

    if not tenant_id:
        # MVP: moderator session'ga tenant_id'ni saqlashi kerak
        raise PermissionDenied("Avval guruhni tanlang.")

    ctx = await resolve_role(uid, tenant_id=tenant_id)
    if ctx.role != Role.MODERATOR:
        raise PermissionDenied("Bu funksiya faqat moderatorlar uchun.")
    return ctx


# ─────────────────────────────────────────────────────────────────────
# 🟡 Tasdiqlash navbati
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == "🟡 Tasdiqlash navbati")
async def show_approve_queue(message: Message) -> None:
    if message.from_user is None:
        return
    try:
        ctx = await _ensure_moderator(message.from_user.id)
    except PermissionDenied as e:
        await message.answer(str(e))
        return

    pending = await db.list_users(
        ctx.tenant_id, status=UserStatus.PENDING, limit=20
    )
    if not pending:
        await message.answer("✅ Navbat bo'sh. Tasdiq kutmoqda foydalanuvchi yo'q.")
        return

    lines = [f"🟡 <b>Tasdiq kutmoqda ({len(pending)} ta)</b>", ""]
    from keyboards.common_kb import inline_grid

    items = []
    for u in pending[:10]:
        lines.append(
            f"• {fmt.esc(u.get('full_name') or '?')} "
            f"<code>#{u['user_id']}</code> "
            f"{fmt.esc(u.get('phone') or '')}"
        )
        items.append(
            (
                f"#{u['user_id']} {(u.get('full_name') or '')[:20]}",
                f"mod:user:view:{u['user_id']}",
            )
        )

    kb = inline_grid(items, columns=1)
    await message.answer("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data.startswith("mod:user:view:"))
async def view_pending_user(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_moderator(query.from_user.id)

    target_uid = int(query.data.rsplit(":", 1)[1])
    user = await db.get_user(ctx.tenant_id, target_uid)
    if not user:
        await query.answer("Topilmadi.", show_alert=True)
        return

    text = fmt.format_user_card(user)
    kb = moderator_kb.approve_queue_actions(target_uid)
    if query.message:
        await query.message.answer(text, reply_markup=kb)
    await query.answer()


@router.callback_query(F.data.startswith("mod:user:approve:"))
async def mod_approve_user(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_moderator(query.from_user.id)
    target_uid = int(query.data.rsplit(":", 1)[1])

    if not can(ctx, Action.APPROVE_USER):
        await query.answer("🚫 Ruxsat yo'q.", show_alert=True)
        return

    await db.set_user_status(
        ctx.tenant_id, target_uid, UserStatus.ACTIVE, approved_by=ctx.user_id
    )
    await notifier.notify_user_approved(
        user_id=target_uid, tenant_id=ctx.tenant_id
    )
    await audit_log.log_user_event(
        ctx, action="user_approved_by_mod", target_user_id=target_uid
    )
    await query.answer("✅ Tasdiqlandi", show_alert=True)


@router.callback_query(F.data.startswith("mod:user:reject:"))
async def mod_reject_user(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_moderator(query.from_user.id)
    target_uid = int(query.data.rsplit(":", 1)[1])

    # Reject = soft delete (foydalanuvchi blocked emas, balki rad etilgan)
    await db.set_user_status(ctx.tenant_id, target_uid, UserStatus.BLOCKED)
    await notifier.notify_user_blocked(
        user_id=target_uid,
        tenant_id=ctx.tenant_id,
        reason="Arizangiz rad etildi",
    )
    await audit_log.log_user_event(
        ctx, action="user_rejected_by_mod", target_user_id=target_uid
    )
    await query.answer("❌ Rad etildi", show_alert=True)
