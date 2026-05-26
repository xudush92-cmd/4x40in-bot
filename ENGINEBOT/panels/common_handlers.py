"""
panels/common_handlers.py — barcha rollar uchun umumiy handlerlar.

MAQSAD:
───────
"👤 Profilim" va "🚪 Chiqish" tugmalari poster, customer va boshqa
foydalanuvchilarda bir xil. Avval ular har router'da duplicate
qilingandi — endi shu yerda yagona joyda.

ROUTER PRIORITY:
────────────────
main.py'da bu router super_admin/tenant'dan KEYIN, lekin
poster/customer'dan OLDIN ulanadi — shunda super admin va tenant
o'z profile'larini ko'radi (tenant_kb.profile_edit_panel bilan),
oddiy USER'lar (poster/customer) — bu yerdagi umumiy handler.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from config import Role
from core import audit_log, database as db
from core.categories import get_category_label
from core.permissions import resolve_role
from keyboards import user_kb
from keyboards.common_kb import Btn
from utils import formatters as fmt
from utils import logger as log_mod
from utils.confirmation import confirm_logout
from utils.session_state import session

logger = log_mod.get_logger("panels.common")
router = Router(name="common")


# ─────────────────────────────────────────────────────────────────────
# 👤 PROFIL — faqat USER (poster/customer) uchun
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.MY_PROFILE)
async def show_profile(message: Message) -> None:
    """USER profilini ko'rsatish (poster/customer/both).

    Tenant va super admin o'z profilini boshqa joyda boshqaradi
    (tenant_kb.profile_edit_panel) — shuning uchun bu yerda ulardan
    chiqamiz.
    """
    if message.from_user is None:
        return

    state = await session.get(message.from_user.id)
    tenant_id = state.tenant_id

    # Rol tekshiruvi: faqat USER uchun ishlaydi
    ctx = await resolve_role(message.from_user.id, tenant_id=tenant_id)
    if ctx.role in (Role.SUPER_ADMIN, Role.TENANT, Role.MODERATOR):
        # Boshqa router'lar bu rol uchun ishlatadi
        return

    if not tenant_id:
        await message.answer("Avval guruh tanlang. /start")
        return

    user = await db.get_user(tenant_id, message.from_user.id)
    if not user:
        await message.answer("Profilingiz hali yaratilmagan. /start")
        return

    text = fmt.format_user_card(user)
    if user.get("region"):
        text += f"\n🌍 Viloyat: {fmt.esc(user['region'])}"
    if user.get("category_code"):
        text += f"\n🎯 Soha: {get_category_label(user['category_code'])}"
    if ctx.is_poster:
        interval = user.get("rotation_interval_min", 10)
        rotation = "🟢 ON" if user.get("rotation_active") else "🔴 OFF"
        text += f"\n⏱ Interval: {interval} daq | Auto-post: {rotation}"
    await message.answer(text)


# ─────────────────────────────────────────────────────────────────────
# 🚪 LOGOUT — barcha rollar uchun (faqat tasdiqlash)
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.LOGOUT)
async def cmd_logout(message: Message) -> None:
    """Tasdiqlash so'rash (har rolga yagona)."""
    if message.from_user is None:
        return
    text, kb = confirm_logout(message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("confirm:yes:logout:"))
async def confirm_logout_yes(query: CallbackQuery) -> None:
    """Logout tasdiqlandi — session tozalash."""
    if query.from_user is None:
        return
    await session.remove(query.from_user.id)
    await audit_log.log_action(
        actor_role="user",
        actor_id=query.from_user.id,
        action="user_logged_out",
    )
    if query.message:
        await query.message.answer(
            "🚪 Tizimdan chiqdingiz. Qaytadan kirish: /start",
            reply_markup=user_kb.role_selection_menu(),
        )
    await query.answer("Chiqdingiz.", show_alert=True)


@router.callback_query(F.data.startswith("confirm:no:logout:"))
async def confirm_logout_no(query: CallbackQuery) -> None:
    """Logout bekor qilindi."""
    if query.message:
        await query.message.answer("✅ Bekor qilindi.")
    await query.answer()
