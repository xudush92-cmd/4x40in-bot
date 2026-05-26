"""
panels/start.py — /start komandasi va rolga qarab marshrutlash.

Har foydalanuvchi /start bossa shu yerga keladi:
  1. Rolini aniqlaymiz (resolve_role)
  2. Rolga qarab tegishli panelga yo'naltiramiz

YANGI FOYDALANUVCHI uchun:
  - Rol tanlash menyusi: 🏢 Guruh admini / 📝 E'lon beruvchi / 🔍 Izlovchi
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from config import BRAND_NAME, BRAND_TAGLINE, Role
from core import audit_log, tenant_manager
from core.permissions import RoleContext, resolve_role
from keyboards import (
    common_kb,
    moderator_kb,
    super_admin_kb,
    tenant_kb,
    user_kb,
)
from utils import logger as log_mod

logger = log_mod.get_logger("panels.start")
router = Router(name="start")


# ─────────────────────────────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if message.from_user is None:
        return

    uid = message.from_user.id
    name = message.from_user.full_name or "do'st"

    ctx = await resolve_role(uid)

    await audit_log.log_action(
        actor=ctx,
        action="start_command",
        details={"name": name, "username": message.from_user.username or ""},
    )

    if ctx.role == Role.SUPER_ADMIN:
        await _greet_super_admin(message, name)
    elif ctx.role == Role.TENANT:
        await _greet_tenant(message, name)
    else:
        await _greet_new_user(message, name)


# ─────────────────────────────────────────────────────────────────────
# Salomlashish — har rol uchun alohida
# ─────────────────────────────────────────────────────────────────────
async def _greet_super_admin(message: Message, name: str) -> None:
    text = (
        f"👑 <b>Salom, {name}!</b>\n\n"
        f"⚙️ <b>{BRAND_NAME}</b> — {BRAND_TAGLINE}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Siz <b>Super Admin</b> sifatida tizimga kirdingiz.\n\n"
        "Quyidagi menyu orqali tenantlarni boshqaring:"
    )
    await message.answer(text, reply_markup=super_admin_kb.super_admin_main_menu())


async def _greet_tenant(message: Message, name: str) -> None:
    tenant = await tenant_manager.get_tenant_with_settings(message.from_user.id)
    if not tenant:
        # Bu holat normal emas, lekin defensive
        await _greet_new_user(message, name)
        return

    status = tenant.get("status", "?")
    paid_until = (tenant.get("paid_until") or "")[:10]

    text = (
        f"🏢 <b>Xush kelibsiz, {name}!</b>\n\n"
        f"⚙️ <b>{BRAND_NAME}</b> — guruh admin paneli\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Tarif: <b>{tenant.get('tariff', '?').upper()}</b>\n"
        f"📅 Muddat: {paid_until or '—'}\n"
        f"🟢 Holat: {status}\n\n"
        "Quyidagi menyu orqali guruhingizni boshqaring:"
    )
    await message.answer(text, reply_markup=tenant_kb.tenant_main_menu())


async def _greet_new_user(message: Message, name: str) -> None:
    """
    Yangi foydalanuvchi (yoki rol aniq emas).

    Rol tanlash menyusini koʻrsatamiz.
    """
    text = (
        f"👋 <b>Salom, {name}!</b>\n\n"
        f"⚙️ <b>{BRAND_NAME}</b> — {BRAND_TAGLINE}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Bu — kanal va guruhlar uchun aqlli e'lon boshqaruv tizimi.\n\n"
        "<b>Siz kimsiz?</b>\n\n"
        "🏢 <b>Guruh admini</b> — o'z kanalimni bot bilan boshqaraman\n"
        "📝 <b>E'lon beraman</b> — kanalga o'z e'lonimni qo'yaman\n"
        "🔍 <b>E'lon izlayman</b> — kerakli e'lonni topaman"
    )
    await message.answer(text, reply_markup=user_kb.role_selection_menu())


# ─────────────────────────────────────────────────────────────────────
# Universal Yordam
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == common_kb.Btn.HELP)
async def cmd_help(message: Message) -> None:
    text = (
        f"⚙️ <b>{BRAND_NAME}</b> — Yordam\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📖 <b>Asosiy buyruqlar:</b>\n"
        "• /start — bosh menyu\n"
        "• /cancel — joriy amalni bekor qilish\n"
        "• /help — bu xabar\n\n"
        "📞 <b>Yordam:</b>\n"
        "Savollaringiz bo'lsa kanal egasiga murojaat qiling.\n\n"
        "🤖 Bot: ENGINEBOT v1.0\n"
        "📚 Hujjat: README.md"
    )
    await message.answer(text)


# ─────────────────────────────────────────────────────────────────────
# /cancel — har qanday joriy amalni bekor qilish
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text.in_({"/cancel", common_kb.Btn.CANCEL}))
async def cmd_cancel(message: Message) -> None:
    if message.from_user is None:
        return
    from utils.session_state import session
    await session.reset(message.from_user.id)

    ctx = await resolve_role(message.from_user.id)
    if ctx.role == Role.SUPER_ADMIN:
        kb = super_admin_kb.super_admin_main_menu()
    elif ctx.role == Role.TENANT:
        kb = tenant_kb.tenant_main_menu()
    elif ctx.role == Role.USER:
        kb = user_kb.user_main_menu()
    else:
        kb = user_kb.role_selection_menu()

    await message.answer("✅ Bekor qilindi. Bosh menyuga qaytdik.", reply_markup=kb)
