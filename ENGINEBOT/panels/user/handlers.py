"""
panels/user/handlers.py — oddiy foydalanuvchi (taksist/sotuvchi) paneli.

ASOSIY FUNKSIYALAR:
───────────────────
- Tenant tanlash (qaysi guruhda ishlash)
- Profil koʻrish va tahrir
- Mening eʼlonlarim
- Eʼlon yozish (plugin orqali)
- Logout

Eslatma: eʼlon yaratish konkret biznes mantiq plugin/taxi/handlers.py
ichida (chunki har soha boshqacha maydonlarga ega). Bu yerda — umumiy
panel funksiyalari.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from config import Role, UserStatus
from core import audit_log, database as db, notifier
from core.permissions import RoleContext, resolve_role
from keyboards import user_kb
from keyboards.common_kb import Btn, request_contact
from utils import formatters as fmt
from utils import logger as log_mod
from utils.confirmation import confirm_logout, parse_confirmation
from utils.session_state import session
from utils.validators import validate_name, validate_phone

logger = log_mod.get_logger("panels.user")
router = Router(name="user")


# ─────────────────────────────────────────────────────────────────────
# 📝 "Men eʼlon beraman" — tenant tanlash
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.I_AM_USER)
async def i_am_user(message: Message) -> None:
    """
    Foydalanuvchi qaysi tenantga (kanalga) ulanishni xohlashini tanlash.

    MVP: barcha aktiv tenantlar roʻyxati. Real ishlatishda — tenant
    o'z deep-link'ini foydalanuvchilarga beradi (masalan
    https://t.me/enginebot?start=tenant_123456).
    """
    if message.from_user is None:
        return

    from config import TenantStatus
    tenants = await db.list_tenants(status=TenantStatus.ACTIVE, limit=20)
    if not tenants:
        await message.answer(
            "📭 Hozircha aktiv guruhlar yoʻq.\n\n"
            "Iltimos, kanal egasi botni sozlasin va kanalingizga "
            "o'zining deep-link'ini bersin."
        )
        return

    from keyboards.common_kb import inline_grid

    items = [
        (
            f"🏢 {(t.get('name') or '?')[:30]}",
            f"user:select_tenant:{t['tenant_id']}",
        )
        for t in tenants
    ]
    kb = inline_grid(items, columns=1)

    await message.answer(
        "🏢 <b>Qaysi guruhda ishlamoqchisiz?</b>\n\n"
        "Quyidagi roʻyxatdan kanalingizni tanlang:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("user:select_tenant:"))
async def select_tenant(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    tenant_id = int(query.data.rsplit(":", 1)[1])

    tenant = await db.get_tenant(tenant_id)
    if not tenant:
        await query.answer("Topilmadi.", show_alert=True)
        return

    # Userni tenantga ulash (yoki mavjudligini tekshirish)
    existing = await db.get_user(tenant_id, query.from_user.id)
    if existing and existing.get("status") == UserStatus.ACTIVE:
        await query.answer("Siz allaqachon shu guruhdasiz.", show_alert=True)
        if query.message:
            await query.message.answer(
                f"✅ Siz <b>{fmt.esc(tenant.get('name', ''))}</b> guruhidasiz.",
                reply_markup=user_kb.user_main_menu(),
            )
        await session.update(query.from_user.id, tenant_id=tenant_id)
        return

    # Yangi — ro'yxatdan o'tishni boshlaymiz
    await session.update(
        query.from_user.id,
        step="user:awaiting_name",
        tenant_id=tenant_id,
    )
    if query.message:
        await query.message.answer(
            f"✅ Tanlandi: <b>{fmt.esc(tenant.get('name', ''))}</b>\n\n"
            "📝 Roʻyxatdan oʻtish uchun maʼlumotlaringizni soʻrayman.\n\n"
            "1️⃣ <b>Toʻliq ismingizni</b> yuboring (masalan: Akmal Karimov):"
        )
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# 👤 Profil
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.MY_PROFILE)
async def show_profile(message: Message) -> None:
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)
    tenant_id = state.tenant_id

    if not tenant_id:
        await message.answer("Avval guruh tanlang. /start")
        return

    user = await db.get_user(tenant_id, message.from_user.id)
    if not user:
        await message.answer("Profilingiz hali yaratilmagan. /start")
        return

    text = fmt.format_user_card(user)
    await message.answer(text)


# ─────────────────────────────────────────────────────────────────────
# 📋 Mening eʼlonlarim
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.MY_POSTS)
async def show_my_posts(message: Message) -> None:
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        await message.answer("Avval guruh tanlang. /start")
        return

    posts = await db.list_user_announcements(tenant_id, message.from_user.id)
    if not posts:
        await message.answer(
            "📭 Hali eʼloningiz yoʻq.\n\n"
            "📝 Yangi eʼlon qoʻshish uchun menyudan tanlang."
        )
        return

    lines = [f"📋 <b>Mening eʼlonlarim ({len(posts)} ta)</b>", ""]
    for i, p in enumerate(posts[:15], 1):
        emoji = {
            "active": "🟢",
            "draft": "📝",
            "paused": "⏸",
            "expired": "⚪",
            "deleted": "🗑",
        }.get(p.get("status", ""), "❓")
        lines.append(
            f"{i}. {emoji} <code>#{p['id']}</code> | "
            f"{p.get('plugin', '?')} | "
            f"{fmt.format_relative(p.get('created_at'))}"
        )

    await message.answer("\n".join(lines))


# ─────────────────────────────────────────────────────────────────────
# 🚪 Logout
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.LOGOUT)
async def cmd_logout(message: Message) -> None:
    if message.from_user is None:
        return
    text, kb = confirm_logout(message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("confirm:yes:logout:"))
async def confirm_logout_yes(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return

    uid = query.from_user.id
    state = await session.get(uid)
    tenant_id = state.tenant_id
    ctx = await resolve_role(uid, tenant_id=tenant_id)

    # Aktiv eʼlonlarni oʻchirish
    if tenant_id:
        from config import PostStatus
        posts = await db.list_user_announcements(
            tenant_id, uid, status=PostStatus.ACTIVE
        )
        for p in posts:
            await db.update_announcement(
                p["id"], tenant_id, status=PostStatus.DELETED
            )

    await session.remove(uid)
    await audit_log.log_action(actor=ctx, action="user_logged_out")

    if query.message:
        await query.message.answer(
            "🚪 Tizimdan chiqdingiz. Qaytadan kirish: /start",
            reply_markup=user_kb.role_selection_menu(),
        )
    await query.answer("Chiqdingiz.", show_alert=True)


@router.callback_query(F.data.startswith("confirm:no:logout:"))
async def confirm_logout_no(query: CallbackQuery) -> None:
    if query.message:
        await query.message.answer("✅ Bekor qilindi.", reply_markup=user_kb.user_main_menu())
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# Ro'yxatdan o'tish flow (matn handlerlari)
# ─────────────────────────────────────────────────────────────────────
@router.message(F.contact)
async def receive_contact(message: Message) -> None:
    """Telegram contact button orqali yuborilgan telefon."""
    if message.from_user is None or message.contact is None:
        return
    state = await session.get(message.from_user.id)
    if state.step != "user:awaiting_phone":
        return

    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone

    await _save_phone_and_continue(message, phone)


@router.message(F.text)
async def user_text_router(message: Message) -> None:
    """Ro'yxatdan o'tish flow va boshqa matn inputlari."""
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)
    text = (message.text or "").strip()

    if state.step == "user:awaiting_name":
        ok, name, err = validate_name(text)
        if not ok:
            await message.answer(err)
            return
        state.data["full_name"] = name
        state.step = "user:awaiting_phone"
        await session.set(message.from_user.id, state)
        await message.answer(
            f"✅ Ism: {fmt.esc(name)}\n\n"
            "2️⃣ <b>Telefon raqamingizni yuboring:</b>\n"
            "(Pastdagi tugma orqali yoki +998XXXXXXXXX formatida yozing)",
            reply_markup=request_contact(),
        )
        return

    if state.step == "user:awaiting_phone":
        await _save_phone_and_continue(message, text)
        return


async def _save_phone_and_continue(message: Message, phone_raw: str) -> None:
    if message.from_user is None:
        return
    ok, phone, err = validate_phone(phone_raw)
    if not ok:
        await message.answer(err)
        return

    state = await session.get(message.from_user.id)
    tenant_id = state.tenant_id or 0
    full_name = state.data.get("full_name", "")

    if not tenant_id:
        await message.answer("Guruh aniqlanmadi. /start")
        return

    # Foydalanuvchini DB'ga yozish — settings'ga qarab require_approval
    settings = await db.get_settings(tenant_id)
    require_approval = bool(settings.get("require_approval", True))

    user = await db.upsert_user(
        tenant_id=tenant_id,
        user_id=message.from_user.id,
        full_name=full_name,
        username=message.from_user.username or "",
        phone=phone,
    )

    if not require_approval:
        # Avtomatik tasdiqlash
        await db.set_user_status(
            tenant_id, message.from_user.id, UserStatus.ACTIVE,
            approved_by=tenant_id,  # tizim tasdiqladi deb belgilaymiz
        )
        await session.reset(message.from_user.id)
        await session.update(message.from_user.id, tenant_id=tenant_id)
        await message.answer(
            "✅ Roʻyxatdan oʻtdingiz va tasdiqlandingiz!\n\n"
            "Endi eʼlon yozishingiz mumkin.",
            reply_markup=user_kb.user_main_menu(),
        )
    else:
        # Tenantga xabar — tasdiqlash kerak
        from keyboards.tenant_kb import approve_user_inline
        try:
            from main import bot
            await bot.send_message(
                tenant_id,
                text=(
                    f"🔔 <b>Yangi ariza</b>\n\n"
                    f"👤 <b>{fmt.esc(full_name)}</b>\n"
                    f"🆔 <code>#{message.from_user.id}</code>\n"
                    f"📱 {fmt.esc(phone)}"
                    + (f"\n📎 @{fmt.esc(message.from_user.username)}" if message.from_user.username else "")
                ),
                reply_markup=approve_user_inline(message.from_user.id),
            )
        except Exception as e:
            logger.warning(f"tenant {tenant_id}'ga ariza yuborilmadi: {e}")

        await session.reset(message.from_user.id)
        await session.update(message.from_user.id, tenant_id=tenant_id)
        await message.answer(
            "✅ Maʼlumotlaringiz qabul qilindi.\n\n"
            "⏳ Guruh egasi tasdiqlashini kuting. "
            "Tasdiqlanganidan soʻng menyu ochiladi.",
            reply_markup=user_kb.user_unregistered_menu(),
        )
