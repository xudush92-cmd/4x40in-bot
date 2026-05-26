"""
panels/start.py — /start komandasi va rolga qarab marshrutlash.

V1 yangiliklar:
- 4 rol tanlash: Tenant / Poster / Customer / Help
- USER aktiv bo'lsa, sub-rolga qarab menyu (Poster/Customer/Both)
- Tenant'ning aktiv pending statelari hisobga olinadi
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from config import (
    BRAND_NAME,
    BRAND_TAGLINE,
    Role,
    UserRole,
    UserStatus,
)
from core import audit_log, database as db, tenant_manager
from core.permissions import RoleContext, full_role_label, resolve_role
from keyboards import (
    super_admin_kb,
    tenant_kb,
    user_kb,
)
from keyboards.common_kb import Btn
from utils import logger as log_mod
from utils.session_state import session

logger = log_mod.get_logger("panels.start")
router = Router(name="start")


# ─────────────────────────────────────────────────────────────────────
# /start (deep-link support: /start join_<tenant_id>)
# ─────────────────────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if message.from_user is None:
        return

    uid = message.from_user.id
    name = message.from_user.full_name or "doʻst"

    # ── Deep-link parametr parser ────────────────────────────────────
    # Format: /start join_<tenant_id>
    # Foydalanuvchi tenant'ning deep-link'ini bosgan bo'lsa,
    # avtomatik o'sha tenant'ga bog'lanadi.
    deep_link_param = ""
    if message.text and len(message.text.split()) > 1:
        deep_link_param = message.text.split(maxsplit=1)[1].strip()

    if deep_link_param.startswith("join_"):
        target_tenant_id = None
        try:
            target_tenant_id = int(deep_link_param[5:])
        except (ValueError, IndexError):
            pass

        if target_tenant_id:
            # Tenant mavjudligini tekshirish
            tenant = await db.get_tenant(target_tenant_id)
            if tenant and tenant.get("status") in ("active", "pending"):
                # Session'ga tenant_id ni saqlaymiz
                await session.update(uid, tenant_id=target_tenant_id)
                logger.info(
                    f"Deep-link: user #{uid} → tenant #{target_tenant_id}"
                )
            else:
                await message.answer(
                    "⚠️ Bu guruh hozirda aktiv emas yoki topilmadi.\n"
                    "Qaytadan urinib ko'ring yoki /start bosing."
                )
                return

    # Session'dan tenant_id (agar oldin tanlangan yoki deep-link bo'lsa)
    state = await session.get(uid)
    tenant_id = state.tenant_id

    ctx = await resolve_role(uid, tenant_id=tenant_id)

    await audit_log.log_action(
        actor=ctx,
        action="start_command",
        details={
            "name": name,
            "username": message.from_user.username or "",
            "deep_link": deep_link_param or None,
        },
    )

    # Marshrut
    if ctx.role == Role.SUPER_ADMIN:
        await _greet_super_admin(message, name)
    elif ctx.role == Role.TENANT:
        await _greet_tenant(message, name)
    elif ctx.role == Role.USER:
        await _greet_user(message, name, ctx)
    else:
        await _greet_guest(message, name)


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
    if message.from_user is None:
        return
    tenant = await tenant_manager.get_tenant_with_settings(message.from_user.id)
    if not tenant:
        await _greet_guest(message, name)
        return

    status = tenant.get("status", "?")
    paid_until = (tenant.get("paid_until") or "")[:10]
    settings = tenant.get("settings", {})

    text = (
        f"🏢 <b>Xush kelibsiz, {name}!</b>\n\n"
        f"⚙️ <b>{BRAND_NAME}</b> — guruh admin paneli\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Tarif: <b>{tenant.get('tariff', '?').upper()}</b>\n"
        f"📅 Muddat: {paid_until or '—'}\n"
        f"🟢 Holat: {status}\n"
        f"⏱ Min interval: {settings.get('rotation_interval_min', 10)} daq\n\n"
        "Quyidagi menyu orqali guruhingizni boshqaring:"
    )
    await message.answer(text, reply_markup=tenant_kb.tenant_main_menu())


async def _greet_user(message: Message, name: str, ctx: RoleContext) -> None:
    """USER sub-rolga qarab tegishli menyu ko'rsatadi."""
    if message.from_user is None:
        return

    tenant_id = ctx.tenant_id
    if tenant_id is None:
        # Session'da tenant yo'q, lekin DB'da bor — qayta resolve qilamiz
        await _greet_guest(message, name)
        return

    user = await db.get_user(tenant_id, message.from_user.id)
    if not user:
        await _greet_guest(message, name)
        return

    status = user.get("status", "")
    if status == UserStatus.PENDING:
        await message.answer(
            f"⏳ <b>{name}, sizning ariza ko'rib chiqilmoqda</b>\n\n"
            "Guruh egasi tasdiqlashini kuting. Tasdiqlanganida xabar beraman.",
            reply_markup=user_kb.pending_menu(),
        )
        return

    if status == UserStatus.BLOCKED:
        await message.answer(
            "🚫 <b>Sizning hisobingiz bloklangan.</b>\n\n"
            "Iltimos, kanal egasi bilan bogʻlaning."
        )
        return

    # Active user — sub-rolga qarab menyu
    sub_role = ctx.user_sub_role or UserRole.CUSTOMER
    rotation_active = bool(user.get("rotation_active", 0))

    role_text = full_role_label(ctx)
    text = (
        f"👋 <b>Salom, {name}!</b>\n\n"
        f"⚙️ <b>{BRAND_NAME}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 Roli: {role_text}"
    )

    if sub_role == UserRole.POSTER:
        cat_code = user.get("category_code") or ""
        if cat_code:
            from core.categories import get_category_label
            text += f"\n🎯 Soha: {get_category_label(cat_code)}"
        text += f"\n🔄 Auto-post: {'🟢 ON' if rotation_active else '🔴 OFF'}"
        await message.answer(
            text, reply_markup=user_kb.poster_main_menu(rotation_active=rotation_active)
        )
    elif sub_role == UserRole.CUSTOMER:
        await message.answer(text, reply_markup=user_kb.customer_main_menu())
    else:  # BOTH
        await message.answer(
            text, reply_markup=user_kb.both_main_menu(rotation_active=rotation_active)
        )


async def _greet_guest(message: Message, name: str) -> None:
    """
    Yangi foydalanuvchi yoki rol aniq emas.

    Rol tanlash menyusini koʻrsatamiz.
    """
    text = (
        f"👋 <b>Salom, {name}!</b>\n\n"
        f"⚙️ <b>{BRAND_NAME}</b> — {BRAND_TAGLINE}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Bu — kanal va guruhlar uchun aqlli e'lon boshqaruv tizimi.\n\n"
        "<b>Siz kimsiz?</b>\n\n"
        "🏢 <b>Guruh admini</b> — kanalimni bot bilan boshqaraman\n"
        "📝 <b>Eʼlon beruvchi</b> — taksist, usta, ishchi (xizmat ko'rsataman)\n"
        "🔍 <b>Mijoz</b> — xizmat yoki taxi izlayman"
    )
    await message.answer(text, reply_markup=user_kb.role_selection_menu())


# ─────────────────────────────────────────────────────────────────────
# Universal Yordam
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.HELP)
async def cmd_help(message: Message) -> None:
    text = (
        f"⚙️ <b>{BRAND_NAME}</b> — Yordam\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📖 <b>Asosiy buyruqlar:</b>\n"
        "• /start — bosh menyu\n"
        "• /cancel — joriy amalni bekor qilish\n"
        "• /help — bu xabar\n\n"
        "📱 <b>Rollar:</b>\n"
        "• 🏢 Guruh admini — o'z kanalingizni boshqarasiz\n"
        "• 📝 Eʼlon beruvchi — taksist, usta, ishchi\n"
        "• 🔍 Mijoz — xizmat izlaysiz\n\n"
        "📞 <b>Yordam:</b>\n"
        "Savollaringiz bo'lsa kanal egasiga murojaat qiling.\n\n"
        "🤖 Bot: ENGINEBOT v1.1\n"
    )
    await message.answer(text)


# ─────────────────────────────────────────────────────────────────────
# /cancel — har qanday joriy amalni bekor qilish
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text.in_({"/cancel", Btn.CANCEL}))
async def cmd_cancel(message: Message) -> None:
    if message.from_user is None:
        return

    # Session reset (lekin tenant_id'ni saqlaymiz — keep_tenant=True)
    state = await session.get(message.from_user.id)
    tenant_id = state.tenant_id
    await session.reset(message.from_user.id, keep_tenant=True)

    # Bosh menyuga qaytaramiz
    name = message.from_user.full_name or "doʻst"
    ctx = await resolve_role(message.from_user.id, tenant_id=tenant_id)

    await message.answer("✅ Bekor qilindi.")

    if ctx.role == Role.SUPER_ADMIN:
        await _greet_super_admin(message, name)
    elif ctx.role == Role.TENANT:
        await _greet_tenant(message, name)
    elif ctx.role == Role.USER:
        await _greet_user(message, name, ctx)
    else:
        await _greet_guest(message, name)
