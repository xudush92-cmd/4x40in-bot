"""
panels/tenant/handlers.py — guruh egasi (tenant) paneli (V1).

V1 yangiliklar:
- Tenant rotation_active toggle YO'Q (rotation per-poster bo'ldi)
- Tenant faqat MIN INTERVAL cheklovini belgilaydi (default 10 daq)
- Auto-approval toggle qo'shildi
- Bot ON/OFF, Post intake ON/OFF saqlangan
- Foydalanuvchilar tasdiqlash/bloklash/ogohlantirish
- Kanal ulash, statistika, audit log
"""

from __future__ import annotations

import contextlib

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from config import Limits, Role, Rotation, UserStatus, get_tariff_limit
from core import audit_log, database as db, notifier
from core.permissions import (
    PermissionDenied,
    RoleContext,
    resolve_role,
)
from keyboards import tenant_kb
from keyboards.common_kb import Btn, inline_grid
from utils import formatters as fmt
from utils import logger as log_mod
from utils.confirmation import build_confirmation
from utils.session_state import session
from utils.validators import validate_channel, validate_interval, validate_phone, validate_reason

logger = log_mod.get_logger("panels.tenant")
router = Router(name="tenant")


# ─────────────────────────────────────────────────────────────────────
# Helper: tenant ekanligini tekshirish
# ─────────────────────────────────────────────────────────────────────
async def _ensure_tenant(uid: int) -> RoleContext:
    """tenant_id == uid bo'lgan kanal egasi ekanligini tasdiqlash."""
    ctx = await resolve_role(uid)
    if ctx.role != Role.TENANT:
        raise PermissionDenied("Bu funksiya faqat guruh egasi uchun.")
    return ctx


# ─────────────────────────────────────────────────────────────────────
# 🏢 "Men guruh adminiman" — yangi tenant ariza
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.I_AM_TENANT)
async def i_am_tenant(message: Message) -> None:
    if message.from_user is None:
        return

    uid = message.from_user.id
    name = message.from_user.full_name or ""
    username = message.from_user.username or ""

    existing = await db.get_tenant(uid)
    if existing:
        ctx = await resolve_role(uid)
        if ctx.role == Role.TENANT:
            await message.answer(
                "✅ Siz allaqachon ro'yxatdan o'tgansiz.\n\n/start — bosh menyu"
            )
            return

    # Yangi tenant — auto trial bilan
    from core.tenant_manager import register_tenant
    tenant = await register_tenant(uid, name=name, username=username, auto_trial=True)

    # Super adminga xabar
    from config import SUPER_ADMIN_ID
    from keyboards.super_admin_kb import approve_tenant_inline
    from aiogram.exceptions import TelegramAPIError
    with contextlib.suppress(TelegramAPIError):
        from main import bot
        username_str = ('@' + fmt.esc(username)) if username else 'username yoʻq'
        await bot.send_message(
            SUPER_ADMIN_ID,
            text=(
                f"🔔 <b>Yangi tenant arizasi</b>\n\n"
                f"👤 <b>{fmt.esc(name)}</b>\n"
                f"🆔 <code>#{uid}</code>\n"
                f"📎 {username_str}\n\n"
                f"📦 Auto-trial bilan aktivlashtirildi: {tenant.get('paid_until', '')[:10]}"
            ),
            reply_markup=approve_tenant_inline(uid),
        )

    await message.answer(
        f"✅ <b>Tabriklayman, {fmt.esc(name)}!</b>\n\n"
        f"📦 Sizga {tenant.get('tariff', 'trial').upper()} tarif berildi.\n"
        f"📅 Sinov muddati: {tenant.get('paid_until', '')[:10]}\n\n"
        "Endi /start bosing va kanalingizni ulang.",
    )


# ─────────────────────────────────────────────────────────────────────
# ⚙️ Sozlamalar paneli
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.BOT_SETTINGS)
async def show_settings(message: Message) -> None:
    if message.from_user is None:
        return
    ctx = await _ensure_tenant(message.from_user.id)

    settings = await db.get_settings(ctx.user_id)
    text = (
        f"⚙️ <b>Sozlamalar</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🤖 Bot: <b>{'🟢 ON' if settings['bot_active'] else '🔴 OFF'}</b>\n"
        f"📥 Eʼlon qabuli: <b>{'🟢 ON' if settings['post_intake_active'] else '🔴 OFF'}</b>\n"
        f"✅ Avto-tasdiq: <b>"
        f"{'🟢 ON' if not settings.get('require_approval', True) else '🔴 OFF'}</b>\n"
        f"⏱ Min interval: <b>{settings['rotation_interval_min']} daq</b>\n\n"
        f"<i>Eslatma:</i> Min interval — har poster uchun rotation min cheklovi.\n"
        f"Posterlar oʻz intervalini shu qiymatdan past qila olmaydi.\n"
        f"Tizim qoidasi: hech qachon {Rotation.MIN_INTERVAL_MIN} daqdan kam emas."
    )
    kb = tenant_kb.settings_panel(
        bot_active=bool(settings["bot_active"]),
        post_intake_active=bool(settings["post_intake_active"]),
        require_approval=bool(settings.get("require_approval", True)),
        min_interval_min=int(settings["rotation_interval_min"]),
    )
    await message.answer(text, reply_markup=kb)


# Toggle ON/OFF
@router.callback_query(F.data.startswith("tenant:toggle:"))
async def toggle_setting(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)

    field = query.data.rsplit(":", 1)[1]  # bot / post_intake / auto_approve
    settings = await db.get_settings(ctx.user_id)

    if field == "bot":
        new_val = not bool(settings["bot_active"])
        await db.update_settings(ctx.user_id, bot_active=new_val)
        action_log = "bot_toggled"
    elif field == "post_intake":
        new_val = not bool(settings["post_intake_active"])
        await db.update_settings(ctx.user_id, post_intake_active=new_val)
        action_log = "post_intake_toggled"
    elif field == "auto_approve":
        # auto_approve YOQ holati = require_approval=False
        new_require = not bool(settings.get("require_approval", True))
        await db.update_settings(ctx.user_id, require_approval=new_require)
        new_val = not new_require  # auto_approve = NOT require
        action_log = "auto_approve_toggled"
    else:
        return await query.answer("Nomaʼlum amal.", show_alert=True)

    await audit_log.log_tenant_event(
        ctx, action=action_log, tenant_id=ctx.user_id, new_value=new_val
    )

    # Panel'ni yangilash — yangi holat bilan KB qayta chizish
    new_settings = await db.get_settings(ctx.user_id)
    new_kb = tenant_kb.settings_panel(
        bot_active=bool(new_settings["bot_active"]),
        post_intake_active=bool(new_settings["post_intake_active"]),
        require_approval=bool(new_settings.get("require_approval", True)),
        min_interval_min=int(new_settings["rotation_interval_min"]),
    )
    if query.message:
        with contextlib.suppress(Exception):
            await query.message.edit_reply_markup(reply_markup=new_kb)

    await query.answer(f"✅ {'🟢 ON' if new_val else '🔴 OFF'}", show_alert=False)


@router.callback_query(F.data == "tenant:set_min_interval")
async def show_min_interval_picker(query: CallbackQuery) -> None:
    if query.from_user is None:
        return
    if query.message:
        await query.message.answer(
            f"⏱ <b>Min interval (posterlar uchun cheklov)</b>\n\n"
            f"Min: {Rotation.MIN_INTERVAL_MIN} daq (qoida)\n\n"
            f"Tanlang:",
            reply_markup=tenant_kb.min_interval_picker(),
        )
    await query.answer()


@router.callback_query(F.data.startswith("tenant:min_interval:set:"))
async def set_min_interval(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)

    try:
        n = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        return
    if n < Rotation.MIN_INTERVAL_MIN:
        return await query.answer(
            f"⛔ Min {Rotation.MIN_INTERVAL_MIN} daq.", show_alert=True
        )

    await db.update_settings(ctx.user_id, rotation_interval_min=n)
    await audit_log.log_tenant_event(
        ctx, action="min_interval_changed", tenant_id=ctx.user_id, min_interval_min=n
    )
    await query.answer(f"✅ Min interval: {n} daq", show_alert=True)


# ─────────────────────────────────────────────────────────────────────
# 📺 Kanallarim
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.MY_CHANNELS)
async def show_channels(message: Message) -> None:
    if message.from_user is None:
        return
    ctx = await _ensure_tenant(message.from_user.id)

    channels = await db.list_channels(ctx.user_id, only_active=False)
    if not channels:
        await message.answer(
            "📭 Hali kanal ulanmagan.\n\n"
            "Yangi kanal qo'shish uchun '➕ Kanal ulash' bosing."
        )
        return

    lines = [f"📺 <b>Kanallaringiz ({len(channels)} ta)</b>", ""]
    for i, ch in enumerate(channels, 1):
        emoji = "🟢" if ch["is_active"] else "🔴"
        title = ch.get('title') or ch.get('channel_username') or '?'
        lines.append(
            f"{i}. {emoji} <b>{fmt.esc(title)}</b>\n"
            f"   <code>{ch['channel_id']}</code>"
        )
    await message.answer("\n".join(lines))


@router.message(F.text == Btn.ADD_CHANNEL)
async def start_add_channel(message: Message) -> None:
    if message.from_user is None:
        return

    # Rate limiter — kanal qo'shish (modify action)
    from core.rate_limiter import limiter, get_block_message
    if not limiter.is_allowed(message.from_user.id, "modify"):
        msg = get_block_message(message.from_user.id, "modify")
        if msg:
            await message.answer(msg)
        return
    ctx = await _ensure_tenant(message.from_user.id)

    # Tarif limit tekshirish
    tenant = await db.get_tenant(ctx.user_id)
    tariff = (tenant or {}).get("tariff", "trial")
    max_channels = int(get_tariff_limit(tariff, "max_channels", 1) or 1)
    current = len(await db.list_channels(ctx.user_id, only_active=False))
    if current >= max_channels:
        await message.answer(
            f"⛔ Tarifingiz ({tariff.upper()}) max {max_channels} kanal ruxsat beradi.\n"
            f"Tarif yangilash uchun bot egasi bilan bogʻlaning."
        )
        return

    await session.update(message.from_user.id, step="tenant:awaiting_channel")
    await message.answer(
        "➕ <b>Kanal ulash</b>\n\n"
        "1️⃣ Avval botni o'z kanalingizga <b>admin</b> qilib qo'shing\n"
        "2️⃣ Keyin kanal @username yoki ID ni shu yerga yuboring\n\n"
        "Misol:\n"
        "<code>@toshkent_xizmatlar</code>\n"
        "yoki\n"
        "<code>-1001234567890</code>\n\n"
        "<i>Bot get_chat() orqali kanalni avtomatik aniqlaydi.</i>"
    )


# ─────────────────────────────────────────────────────────────────────
# 👥 Foydalanuvchilar
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.MANAGE_USERS)
async def show_users(message: Message) -> None:
    if message.from_user is None:
        return
    ctx = await _ensure_tenant(message.from_user.id)

    users = await db.list_users(ctx.user_id, limit=20)
    pending_count = await db.count_users(ctx.user_id, status=UserStatus.PENDING)

    if not users:
        await message.answer("📭 Hali foydalanuvchilar yo'q.")
        return

    from core.categories import get_category_label
    lines = [
        f"👥 <b>Foydalanuvchilar ({len(users)} ta)</b>",
        f"🟡 Tasdiq kutmoqda: {pending_count}",
        "",
    ]
    for i, u in enumerate(users[:15], 1):
        emoji = {"active": "🟢", "pending": "🟡", "blocked": "🔴"}.get(
            u.get("status", ""), "❓"
        )
        role = u.get("user_role", "")
        role_emoji = {"poster": "📝", "customer": "🔍", "both": "🔄"}.get(role, "")
        cat = u.get("category_code", "")
        cat_str = get_category_label(cat) if cat else ""
        lines.append(
            f"{i}. {emoji}{role_emoji} {fmt.esc(u.get('full_name') or '?')} "
            f"<code>#{u.get('user_id')}</code> {cat_str}"
        )

    items = [
        (
            f"#{u['user_id']} {(u.get('full_name') or '?')[:20]}",
            f"tenant:user:show:{u['user_id']}",
        )
        for u in users[:10]
    ]
    kb = inline_grid(
        items, columns=1,
        extra_rows=[[(Btn.BACK, "tenant:users:back")]],
    )
    await message.answer("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data.startswith("tenant:user:show:"))
async def show_user_detail(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    target_uid = int(query.data.rsplit(":", 1)[1])

    user = await db.get_user(ctx.user_id, target_uid)
    if not user:
        return await query.answer("Topilmadi.", show_alert=True)

    text = fmt.format_user_card(user)
    if user.get("category_code"):
        from core.categories import get_category_label
        text += f"\n🎯 Soha: {get_category_label(user['category_code'])}"
    if user.get("region"):
        text += f"\n🌍 Viloyat: {fmt.esc(user['region'])}"

    kb = tenant_kb.user_actions(target_uid, status=user.get("status", "active"))
    if query.message:
        await query.message.answer(text, reply_markup=kb)
    await query.answer()


@router.callback_query(F.data.startswith("tenant:user:approve:"))
async def approve_user_cb(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    target_uid = int(query.data.rsplit(":", 1)[1])

    await db.set_user_status(
        ctx.user_id, target_uid, UserStatus.ACTIVE, approved_by=ctx.user_id
    )
    await notifier.notify_user_approved(
        user_id=target_uid, tenant_id=ctx.user_id
    )
    await audit_log.log_user_event(
        ctx, action="user_approved", target_user_id=target_uid
    )
    await query.answer("✅ Tasdiqlandi", show_alert=True)


@router.callback_query(F.data.startswith("tenant:user:reject:"))
async def reject_user_cb(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    target_uid = int(query.data.rsplit(":", 1)[1])

    await db.set_user_status(ctx.user_id, target_uid, UserStatus.BLOCKED)
    await notifier.notify_user_blocked(
        user_id=target_uid, tenant_id=ctx.user_id, reason="Arizangiz rad etildi"
    )
    await audit_log.log_user_event(
        ctx, action="user_rejected", target_user_id=target_uid
    )
    await query.answer("❌ Rad etildi", show_alert=True)


@router.callback_query(F.data.startswith("tenant:user:block:"))
async def start_block_user_cb(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    target_uid = int(query.data.rsplit(":", 1)[1])
    await session.update(
        query.from_user.id,
        step="tenant:awaiting_block_reason",
        data={"target_user_id": target_uid},
    )
    if query.message:
        await query.message.answer("⛔ Bloklash sababini yozing (min 3 belgi):")
    await query.answer()


@router.callback_query(F.data.startswith("tenant:user:warn:"))
async def start_warn_user_cb(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    target_uid = int(query.data.rsplit(":", 1)[1])
    await session.update(
        query.from_user.id,
        step="tenant:awaiting_warn_reason",
        data={"target_user_id": target_uid},
    )
    if query.message:
        await query.message.answer("⚠️ Ogohlantirish sababini yozing (min 3 belgi):")
    await query.answer()


@router.callback_query(F.data.startswith("tenant:user:unblock:"))
async def unblock_user_cb(query: CallbackQuery) -> None:
    """User'ni tiklash — confirmation so'raymiz."""
    if query.from_user is None or not query.data:
        return
    await _ensure_tenant(query.from_user.id)
    target_uid = int(query.data.rsplit(":", 1)[1])

    text, kb = build_confirmation(
        action_id=f"tenant:user_unblock:{target_uid}",
        title="Foydalanuvchini tiklash",
        question=f"User <code>#{target_uid}</code> ni qayta aktivlashtiramizmi?",
    )
    if query.message:
        await query.message.answer(text, reply_markup=kb)
    await query.answer()


@router.callback_query(F.data.startswith("confirm:yes:tenant:user_unblock:"))
async def unblock_user_yes(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    target_uid = int(query.data.rsplit(":", 1)[1])

    await db.set_user_status(ctx.user_id, target_uid, UserStatus.ACTIVE)
    await audit_log.log_user_event(
        ctx, action="user_unblocked", target_user_id=target_uid
    )
    await query.answer("✅ Tiklandi", show_alert=True)


@router.callback_query(F.data.startswith("confirm:no:tenant:user_unblock:"))
async def unblock_user_no(query: CallbackQuery) -> None:
    if query.message:
        await query.message.answer("✅ Bekor qilindi.")
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# 📊 Statistika (eski — kengaytirilgan versiya pastda)
# ─────────────────────────────────────────────────────────────────────
# Eski show_stats olib tashlandi — pastdagi show_detailed_stats ishlatiladi.


# ─────────────────────────────────────────────────────────────────────
# 📜 Audit log (oʻz guruhi)
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.AUDIT_LOG)
async def show_audit(message: Message) -> None:
    if message.from_user is None:
        return
    ctx = await _ensure_tenant(message.from_user.id)

    logs = await audit_log.get_tenant_audit(ctx.user_id, limit=15)
    if not logs:
        await message.answer("📭 Audit log boʻsh.")
        return

    lines = ["📜 <b>Tarix (oxirgi 15 ta)</b>", ""]
    for entry in logs:
        ts = (entry.get("ts") or "")[:19]
        lines.append(
            f"<code>{ts}</code> {fmt.esc(entry.get('actor_role', '?'))}"
            f"#{entry.get('actor_id')} → {fmt.esc(entry.get('action', '?'))}"
        )
    await message.answer("\n".join(lines))


# ─────────────────────────────────────────────────────────────────────
# Matn handlerlari (state'ga qarab)
# ─────────────────────────────────────────────────────────────────────
async def _in_tenant_flow(message: Message) -> bool:
    """Filter: faqat tenant flow state'ida ishlaydi."""
    if message.from_user is None:
        return False
    state = await session.get(message.from_user.id)
    return state.step.startswith("tenant:")


@router.message(F.text, _in_tenant_flow)
async def tenant_text_router(message: Message) -> None:
    if message.from_user is None:
        return

    state = await session.get(message.from_user.id)
    text = (message.text or "").strip()

    ctx = await resolve_role(message.from_user.id)
    if ctx.role != Role.TENANT:
        return

    # 1) Kanal ulash
    if state.step == "tenant:awaiting_channel":
        ok, normalized, err = validate_channel(text)
        if not ok:
            await message.answer(err)
            return

        # Channel ID aniqlash: numeric yoki @username
        channel_id = 0
        channel_username = ""
        channel_title = ""

        if normalized.lstrip("-").isdigit():
            # Numeric ID
            try:
                channel_id = int(normalized)
            except ValueError:
                channel_id = 0
        elif normalized.startswith("@"):
            # @username — bot.get_chat() orqali aniqlash
            try:
                from main import bot
                from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
                try:
                    chat = await bot.get_chat(normalized)
                    channel_id = int(chat.id)
                    channel_username = normalized
                    channel_title = chat.title or ""
                except TelegramForbiddenError:
                    await message.answer(
                        "🚫 <b>Bot kanal admini emas.</b>\n\n"
                        "Iltimos:\n"
                        "1️⃣ Botni kanalingizga admin qilib qoʻshing\n"
                        "2️⃣ Keyin qaytadan urinib koʻring"
                    )
                    return
                except TelegramBadRequest as e:
                    await message.answer(
                        f"❌ Kanal topilmadi yoki ID notoʻgʻri.\n\n"
                        f"Sababi: {fmt.esc(str(e))}\n\n"
                        f"Tekshiring: <code>{fmt.esc(normalized)}</code>"
                    )
                    return
            except Exception as e:
                logger.error(f"@username channel resolve xato: {type(e).__name__}: {e}")
                await message.answer(
                    "⚠️ Kanal ma'lumotini olib bo'lmadi. Numeric ID bilan urinib ko'ring."
                )
                return

        if not channel_id:
            await message.answer(
                "❌ Channel ID aniqlanmadi.\n"
                "Numeric ID (-1001234567890) yoki @username kiriting."
            )
            return

        ok, status = await db.add_channel(
            tenant_id=ctx.user_id,
            channel_id=channel_id,
            channel_username=channel_username,
            title=channel_title,
        )
        if not ok and status == "duplicate":
            await message.answer("ℹ️ Bu kanal allaqachon ulangan.")
        else:
            await audit_log.log_action(
                actor=ctx,
                action="channel_added",
                target_type="channel",
                target_id=channel_id,
                details={"username": channel_username, "title": channel_title},
            )
            label = channel_username or f"#{channel_id}"
            title_str = f"\n📌 Nomi: <b>{fmt.esc(channel_title)}</b>" if channel_title else ""
            await message.answer(
                f"✅ Kanal ulandi!\n\n"
                f"📺 {label}\n"
                f"🆔 <code>{channel_id}</code>"
                f"{title_str}"
            )
        await session.reset(message.from_user.id)
        return

    # 2) Block sababi
    if state.step == "tenant:awaiting_block_reason":
        ok, reason, err = validate_reason(text)
        if not ok:
            await message.answer(err)
            return
        target_uid = int(state.data.get("target_user_id", 0))
        if not target_uid:
            return

        await db.set_user_status(ctx.user_id, target_uid, UserStatus.BLOCKED)
        await notifier.notify_user_blocked(
            user_id=target_uid, tenant_id=ctx.user_id, reason=reason
        )
        await audit_log.log_user_event(
            ctx, action="user_blocked", target_user_id=target_uid, reason=reason
        )
        await session.reset(message.from_user.id)
        await message.answer(f"⛔ Foydalanuvchi #{target_uid} bloklandi.")
        return

    # 3) Warn sababi
    if state.step == "tenant:awaiting_warn_reason":
        ok, reason, err = validate_reason(text)
        if not ok:
            await message.answer(err)
            return
        target_uid = int(state.data.get("target_user_id", 0))
        if not target_uid:
            return

        wid = await db.add_warning(
            tenant_id=ctx.user_id, user_id=target_uid,
            issued_by=ctx.user_id, reason=reason,
        )
        user = await db.get_user(ctx.user_id, target_uid)
        warns = (user or {}).get("warnings_count", 1)
        await notifier.notify_user_warned(
            user_id=target_uid, tenant_id=ctx.user_id,
            reason=reason, warnings_count=warns,
            max_warnings=Limits.MAX_WARNINGS_BEFORE_BLOCK,
        )
        await audit_log.log_user_event(
            ctx, action="user_warned", target_user_id=target_uid,
            reason=reason, warning_id=wid,
        )

        # Limitga yetdi → avtomatik bloklash
        if warns >= Limits.MAX_WARNINGS_BEFORE_BLOCK:
            await db.set_user_status(ctx.user_id, target_uid, UserStatus.BLOCKED)
            await notifier.notify_user_blocked(
                user_id=target_uid, tenant_id=ctx.user_id,
                reason=f"{warns} ogohlantirish — avtomatik blok",
            )
            await audit_log.log_user_event(
                ctx, action="user_auto_blocked",
                target_user_id=target_uid, warnings=warns,
            )

        await session.reset(message.from_user.id)
        await message.answer(
            f"⚠️ Ogohlantirish berildi.\n"
            f"User #{target_uid} | {warns}/{Limits.MAX_WARNINGS_BEFORE_BLOCK}"
        )
        return

    # 4) Profile edit (name / phone / description)
    if state.step.startswith("tenant:edit_profile:"):
        field = state.step.rsplit(":", 1)[1]
        if not text:
            await message.answer("❌ Bo'sh kiritish ruxsat etilmaydi.")
            return

        if field == "name":
            if len(text) > 100:
                await message.answer("❌ Ism juda uzun (max 100 belgi).")
                return
            await db.update_tenant(ctx.user_id, name=text)
            msg = f"✅ Ism yangilandi: <b>{fmt.esc(text)}</b>"

        elif field == "phone":
            ok, phone, err = validate_phone(text)
            if not ok:
                await message.answer(err)
                return
            await db.update_tenant(ctx.user_id, phone=phone)
            msg = f"✅ Telefon yangilandi: <code>{fmt.esc(phone)}</code>"

        elif field == "description":
            if len(text) > 500:
                await message.answer("❌ Tavsif juda uzun (max 500 belgi).")
                return
            await db.update_tenant(ctx.user_id, description=text)
            msg = "✅ Tavsif yangilandi."

        else:
            await message.answer("❌ Nomaʼlum maydon.")
            return

        await audit_log.log_action(
            actor=ctx,
            action="tenant_profile_updated",
            details={"field": field},
        )
        await session.reset(message.from_user.id, keep_tenant=True)
        await message.answer(msg, reply_markup=tenant_kb.tenant_main_menu())
        return



# ═════════════════════════════════════════════════════════════════════
# 📋 E'LONLAR NAZORATI (manage_posts)
# ═════════════════════════════════════════════════════════════════════
@router.message(F.text == Btn.MANAGE_POSTS)
async def show_posts_panel(message: Message) -> None:
    """Tenant — e'lonlar nazorat paneli."""
    if message.from_user is None:
        return
    ctx = await _ensure_tenant(message.from_user.id)

    from config import PostStatus
    active = await db.count_tenant_announcements(ctx.user_id, PostStatus.ACTIVE)
    paused = await db.count_tenant_announcements(ctx.user_id, PostStatus.PAUSED)
    queued = await db.count_tenant_announcements(ctx.user_id, PostStatus.QUEUED)
    total = active + paused + queued

    text = (
        f"📋 <b>Eʼlonlar nazorati</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Jami aktiv/pauza/navbat: <b>{total}</b>\n"
        f"   🟢 Aktiv: {active}\n"
        f"   ⏸ Pause: {paused}\n"
        f"   🟡 Navbat: {queued}\n\n"
        f"Filtrni tanlang:"
    )
    await message.answer(text, reply_markup=tenant_kb.posts_filter())


@router.callback_query(F.data.startswith("tenant:posts:filter:"))
async def posts_filter_cb(query: CallbackQuery) -> None:
    """E'lonlarni status bo'yicha filtrlash."""
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)

    from config import PostStatus
    filter_val = query.data.rsplit(":", 1)[1]

    status_map = {
        "all": None,
        "active": PostStatus.ACTIVE,
        "paused": PostStatus.PAUSED,
        "queued": PostStatus.QUEUED,
    }
    status = status_map.get(filter_val)

    posts = await db.list_tenant_announcements(ctx.user_id, status=status, limit=15)
    if not posts:
        await query.answer("📭 Eʼlon topilmadi.", show_alert=True)
        return

    from core.categories import get_category_label
    lines = [f"📋 <b>Eʼlonlar ({len(posts)} ta)</b>", ""]
    for i, p in enumerate(posts[:10], 1):
        st_emoji = {
            "active": "🟢", "paused": "⏸", "queued": "🟡",
            "draft": "📝", "expired": "⏰", "deleted": "🗑"
        }.get(p.get("status", ""), "❓")
        cat = get_category_label(p.get("category_code", ""))
        text_preview = (p.get("raw_text") or "")[:40]
        if len(p.get("raw_text") or "") > 40:
            text_preview += "..."
        lines.append(
            f"{i}. {st_emoji} {cat}\n"
            f"   #{p['id']} | {fmt.esc(text_preview)}\n"
            f"   👤 User #{p.get('user_id', '?')}"
        )

    items = [
        (f"#{p['id']} {(p.get('raw_text') or '?')[:15]}", f"tenant:post:show:{p['id']}")
        for p in posts[:10]
    ]
    kb = inline_grid(
        items, columns=1,
        extra_rows=[[(Btn.BACK, "tenant:posts:back")]],
    )
    if query.message:
        await query.message.answer("\n".join(lines), reply_markup=kb)
    await query.answer()


@router.callback_query(F.data.startswith("tenant:post:show:"))
async def show_post_detail(query: CallbackQuery) -> None:
    """Bitta e'lonni batafsil ko'rish."""
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    post_id = int(query.data.rsplit(":", 1)[1])

    post = await db.get_announcement(post_id, tenant_id=ctx.user_id)
    if not post:
        return await query.answer("Topilmadi.", show_alert=True)

    from core.categories import get_category_label
    cat = get_category_label(post.get("category_code", ""))
    raw = (post.get("raw_text") or "—")[:500]
    photos = post.get("photos") or []
    if isinstance(photos, str):
        import json as _json
        try:
            photos = _json.loads(photos)
        except Exception:
            photos = []

    text = (
        f"📋 <b>Eʼlon #{post['id']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Kategoriya: {cat}\n"
        f"👤 Poster: <code>#{post.get('user_id')}</code>\n"
        f"📊 Holat: {post.get('status', '?')}\n"
        f"🔄 Rotation: {post.get('rotation_count', 0)} marta\n"
        f"📷 Rasm: {len(photos)} ta\n"
        f"📅 Yaratildi: {(post.get('created_at') or '')[:16]}\n"
        f"⏰ Tugaydi: {(post.get('expires_at') or '—')[:16]}\n\n"
        f"📝 <b>Matn:</b>\n{fmt.esc(raw)}"
    )
    kb = tenant_kb.post_actions(post_id, status=post.get("status", "active"))
    if query.message:
        await query.message.answer(text, reply_markup=kb)
    await query.answer()


@router.callback_query(F.data.startswith("tenant:post:pause:"))
async def pause_post_cb(query: CallbackQuery) -> None:
    """E'lonni pause qilish."""
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    post_id = int(query.data.rsplit(":", 1)[1])

    from config import PostStatus
    await db.update_announcement(post_id, ctx.user_id, status=PostStatus.PAUSED)
    await audit_log.log_action(
        actor=ctx, action="post_paused",
        target_type="announcement", target_id=post_id,
    )
    await query.answer("⏸ E'lon pauzaga olinidi.", show_alert=True)


@router.callback_query(F.data.startswith("tenant:post:resume:"))
async def resume_post_cb(query: CallbackQuery) -> None:
    """E'lonni davom ettirish (resume)."""
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    post_id = int(query.data.rsplit(":", 1)[1])

    from config import PostStatus
    await db.update_announcement(post_id, ctx.user_id, status=PostStatus.ACTIVE)
    await audit_log.log_action(
        actor=ctx, action="post_resumed",
        target_type="announcement", target_id=post_id,
    )
    await query.answer("▶️ E'lon davom ettirildi.", show_alert=True)


@router.callback_query(F.data.startswith("tenant:post:delete:"))
async def delete_post_cb(query: CallbackQuery) -> None:
    """E'lonni o'chirish — TASDIQLASH so'raymiz."""
    if query.from_user is None or not query.data:
        return
    await _ensure_tenant(query.from_user.id)
    post_id = int(query.data.rsplit(":", 1)[1])

    text, kb = build_confirmation(
        action_id=f"tenant:post_delete:{post_id}",
        title="E'lonni o'chirish",
        question=f"E'lon <code>#{post_id}</code> ni o'chirishni tasdiqlaysizmi?",
        warning="⚠️ Bu amalni ortga qaytarib bo'lmaydi.\nE'lon kanaldan ham o'chiriladi.",
    )
    if query.message:
        await query.message.answer(text, reply_markup=kb)
    await query.answer()


@router.callback_query(F.data.startswith("confirm:yes:tenant:post_delete:"))
async def delete_post_confirm(query: CallbackQuery) -> None:
    """E'lonni o'chirish — TASDIQLANGAN."""
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    post_id = int(query.data.rsplit(":", 1)[1])

    from config import PostStatus
    await db.update_announcement(post_id, ctx.user_id, status=PostStatus.DELETED)
    await audit_log.log_action(
        actor=ctx, action="post_deleted",
        target_type="announcement", target_id=post_id,
    )
    # Kanaldan ham o'chirish
    with contextlib.suppress(Exception):
        from services.publisher import remove_post_from_channel
        await remove_post_from_channel(post_id, ctx.user_id)
    # Poster'ga xabar
    post = await db.get_announcement(post_id)
    if post:
        await notifier.notify_post_action(
            user_id=post["user_id"],
            tenant_id=ctx.user_id,
            post_id=post_id,
            action="deleted",
            reason="Guruh admini tomonidan o'chirildi",
        )
    await query.answer("🗑 E'lon o'chirildi.", show_alert=True)
    if query.message:
        from aiogram.exceptions import TelegramAPIError
        with contextlib.suppress(TelegramAPIError):
            await query.message.delete()


@router.callback_query(F.data.startswith("confirm:no:tenant:post_delete:"))
async def delete_post_cancel(query: CallbackQuery) -> None:
    if query.message:
        await query.message.answer("✅ Bekor qilindi.")
    await query.answer()


@router.callback_query(F.data.startswith("tenant:post:warn_owner:"))
async def warn_post_owner_cb(query: CallbackQuery) -> None:
    """E'lon egasiga ogohlantirish berish (post ustidan)."""
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    post_id = int(query.data.rsplit(":", 1)[1])

    post = await db.get_announcement(post_id, tenant_id=ctx.user_id)
    if not post:
        return await query.answer("Topilmadi.", show_alert=True)

    target_uid = post["user_id"]
    await session.update(
        query.from_user.id,
        step="tenant:awaiting_warn_reason",
        data={"target_user_id": target_uid},
    )
    if query.message:
        await query.message.answer(
            f"⚠️ E'lon #{post_id} egasiga ogohlantirish.\n"
            f"Sababini yozing (min 3 belgi):"
        )
    await query.answer()


@router.callback_query(F.data == "tenant:posts:back")
async def posts_back_cb(query: CallbackQuery) -> None:
    await query.answer()
    if query.message:
        await query.message.delete()


# ═════════════════════════════════════════════════════════════════════
# 🚫 KATEGORIYA CHEKLOVI
# ═════════════════════════════════════════════════════════════════════
@router.message(F.text == Btn.CATEGORY_RESTRICTION)
async def show_category_restriction(message: Message) -> None:
    """Tenant — ruxsat etilgan kategoriyalar sozlamasi."""
    if message.from_user is None:
        return
    ctx = await _ensure_tenant(message.from_user.id)

    allowed = await db.get_allowed_categories(ctx.user_id)
    if not allowed:
        note = "ℹ️ Hozir <b>barcha kategoriyalar</b> ruxsat etilgan (cheklov yo'q)."
    else:
        from core.categories import get_category_label
        cats_str = ", ".join(get_category_label(c) for c in allowed)
        note = f"✅ Ruxsat etilgan: {cats_str}"

    text = (
        f"🚫 <b>Kategoriya cheklovi</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"{note}\n\n"
        f"Posterlar faqat siz ruxsat bergan kategoriyalarda e'lon bera oladi.\n"
        f"Tanlash uchun tugmalarni bosing:"
    )
    await message.answer(
        text,
        reply_markup=tenant_kb.category_restriction_picker(allowed),
    )


@router.callback_query(F.data.startswith("tenant:cat_toggle:"))
async def toggle_category_cb(query: CallbackQuery) -> None:
    """Kategoriya yoqish/o'chirish (toggle)."""
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)

    code = query.data.rsplit(":", 1)[1]
    from core.categories import is_valid_category
    if not is_valid_category(code):
        return await query.answer("Nomaʼlum kategoriya.", show_alert=True)

    allowed = await db.get_allowed_categories(ctx.user_id)
    if code in allowed:
        allowed.remove(code)
    else:
        allowed.append(code)

    # Session'da saqlaymiz (save tugmasi bosilganida DB'ga yoziladi)
    await session.update(
        query.from_user.id,
        step="tenant:category_edit",
        data={"allowed_categories": allowed},
    )

    # KB yangilash
    if query.message:
        try:
            await query.message.edit_reply_markup(
                reply_markup=tenant_kb.category_restriction_picker(allowed),
            )
        except Exception:
            pass
    await query.answer()


@router.callback_query(F.data == "tenant:cat_save")
async def save_category_restriction(query: CallbackQuery) -> None:
    """Kategoriya cheklovni saqlash."""
    if query.from_user is None:
        return
    ctx = await _ensure_tenant(query.from_user.id)

    state = await session.get(query.from_user.id)
    allowed = state.data.get("allowed_categories", [])

    await db.set_allowed_categories(ctx.user_id, allowed)
    await audit_log.log_tenant_event(
        ctx, action="category_restriction_updated",
        tenant_id=ctx.user_id, allowed_categories=allowed,
    )
    await session.reset(query.from_user.id)

    if not allowed:
        msg = "✅ Kategoriya cheklovi olib tashlandi (barchasi ruxsat)."
    else:
        from core.categories import get_category_label
        cats_str = ", ".join(get_category_label(c) for c in allowed)
        msg = f"✅ Saqlandi!\n\nRuxsat etilgan: {cats_str}"

    await query.answer(msg, show_alert=True)
    if query.message:
        try:
            await query.message.delete()
        except Exception:
            pass


@router.callback_query(F.data == "tenant:cat:back")
async def cat_back_cb(query: CallbackQuery) -> None:
    await session.reset(query.from_user.id)
    await query.answer()
    if query.message:
        await query.message.delete()


# ═════════════════════════════════════════════════════════════════════
# 🔗 DEEP-LINK
# ═════════════════════════════════════════════════════════════════════
@router.message(F.text == Btn.DEEP_LINK)
async def show_deep_link(message: Message) -> None:
    """Tenant uchun maxsus deep-link ko'rsatish."""
    if message.from_user is None:
        return
    ctx = await _ensure_tenant(message.from_user.id)

    # Bot username olish
    try:
        from main import bot
        me = await bot.get_me()
        bot_username = me.username
    except Exception:
        bot_username = "enginebot"

    link = f"https://t.me/{bot_username}?start=join_{ctx.user_id}"

    text = (
        f"🔗 <b>Sizning maxsus havolangiz</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📎 <code>{link}</code>\n\n"
        f"Bu linkni kanalingizga pin qilib qo'ying.\n"
        f"Foydalanuvchilar bossa — to'g'ri sizning guruhga keladi.\n\n"
        f"💡 <b>Maslahat:</b>\n"
        f"Kanalingizning pinned xabariga shu matnni qo'ying:\n\n"
        f"<i>\"📢 E'lon berish yoki xizmat izlash uchun:\n"
        f"{link}\"</i>"
    )
    await message.answer(text, reply_markup=tenant_kb.deep_link_card())


@router.callback_query(F.data == "tenant:deeplink:copy")
async def deeplink_copy_cb(query: CallbackQuery) -> None:
    await query.answer(
        "📋 Havolani nusxalang: yuqoridagi kodni bosib ushlab turing",
        show_alert=True,
    )


@router.callback_query(F.data == "tenant:deeplink:back")
async def deeplink_back_cb(query: CallbackQuery) -> None:
    await query.answer()
    if query.message:
        await query.message.delete()


# ═════════════════════════════════════════════════════════════════════
# 📊 KENGAYTIRILGAN STATISTIKA (v1.1)
# ═════════════════════════════════════════════════════════════════════
@router.message(F.text == Btn.STATS)
async def show_detailed_stats(message: Message) -> None:
    """Tenant — kengaytirilgan statistika."""
    if message.from_user is None:
        return
    ctx = await _ensure_tenant(message.from_user.id)

    stats = await db.tenant_detailed_stats(ctx.user_id)
    from core.categories import get_category_label

    # Top kategoriyalar formatlash
    top_cats_lines = []
    for cat_row in stats.get("top_categories", []):
        code = cat_row.get("category_code", "")
        cnt = cat_row.get("cnt", 0)
        top_cats_lines.append(f"   {get_category_label(code)}: {cnt}")
    top_cats_str = "\n".join(top_cats_lines) if top_cats_lines else "   — hali yo'q"

    text = (
        f"📊 <b>Statistika — batafsil</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 <b>Foydalanuvchilar</b>\n"
        f"   Jami: {stats['users_total']}\n"
        f"   Aktiv: {stats['users_active']}\n"
        f"   📝 Posterlar: {stats['posters_count']}\n"
        f"   🔍 Mijozlar: {stats['customers_count']}\n\n"
        f"📋 <b>E'lonlar</b>\n"
        f"   Aktiv: {stats['posts_active']}\n"
        f"   🔄 Rotation ON: {stats['rotation_active_posters']} poster\n\n"
        f"📅 <b>Bugun</b>\n"
        f"   Yangi foydalanuvchilar: {stats['today_new_users']}\n"
        f"   Yangi e'lonlar: {stats['today_new_posts']}\n\n"
        f"📅 <b>Bu hafta</b>\n"
        f"   Yangi e'lonlar: {stats['week_new_posts']}\n\n"
        f"📺 Kanallar: {stats['channels_active']}\n\n"
        f"🏆 <b>Top kategoriyalar</b>\n{top_cats_str}"
    )
    await message.answer(text)



# ═════════════════════════════════════════════════════════════════════
# 📺 KANAL TOGGLE/REMOVE
# ═════════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("tenant:channel:toggle:"))
async def channel_toggle_cb(query: CallbackQuery) -> None:
    """Kanalni vaqtincha o'chirish/yoqish."""
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    try:
        channel_id = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        return await query.answer("Notoʻgʻri ID.", show_alert=True)

    channel = await db.get_channel(ctx.user_id, channel_id)
    if not channel:
        return await query.answer("Kanal topilmadi.", show_alert=True)

    new_state = not bool(channel.get("is_active"))
    await db.update_channel_active(ctx.user_id, channel_id, is_active=new_state)

    await audit_log.log_action(
        actor=ctx,
        action="channel_toggled",
        target_type="channel",
        target_id=channel_id,
        details={"is_active": new_state},
    )
    msg = "🟢 yoqildi" if new_state else "🔴 toʻxtatildi"
    await query.answer(
        f"✅ Kanal {msg}",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("tenant:channel:remove:"))
async def channel_remove_cb(query: CallbackQuery) -> None:
    """Kanalni butunlay olib tashlash (tasdiqlash bilan)."""
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    try:
        channel_id = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        return await query.answer("Notoʻgʻri ID.", show_alert=True)

    # Tasdiqlash so'raymiz
    confirm_text, kb = build_confirmation(
        action_id=f"tenant:channel_remove:{channel_id}",
        title="Kanalni olib tashlash",
        question=f"Kanal #{channel_id} ni butunlay olib tashlaymizmi?",
        details=[
            "📌 Bu kanaldagi e'lonlar to'xtaydi",
            "📌 Kanalni qaytadan ulash mumkin",
        ],
    )
    if query.message:
        await query.message.answer(confirm_text, reply_markup=kb)
    await query.answer()


@router.callback_query(F.data.startswith("confirm:yes:tenant:channel_remove:"))
async def channel_remove_confirm(query: CallbackQuery) -> None:
    """Kanalni o'chirish — tasdiqlangandan so'ng."""
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    try:
        channel_id = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        return await query.answer("Notoʻgʻri ID.", show_alert=True)

    ok = await db.remove_channel(ctx.user_id, channel_id)
    if not ok:
        return await query.answer("Kanal topilmadi.", show_alert=True)

    await audit_log.log_action(
        actor=ctx,
        action="channel_removed",
        target_type="channel",
        target_id=channel_id,
    )
    await query.answer("🗑 Kanal olib tashlandi.", show_alert=True)
    if query.message:
        from aiogram.exceptions import TelegramAPIError
        with contextlib.suppress(TelegramAPIError):
            await query.message.delete()


@router.callback_query(F.data.startswith("confirm:no:tenant:channel_remove:"))
async def channel_remove_cancel(query: CallbackQuery) -> None:
    if query.message:
        await query.message.answer("✅ Bekor qilindi.")
    await query.answer()


# ═════════════════════════════════════════════════════════════════════
# 👥 FOYDALANUVCHILAR FILTRI
# ═════════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("tenant:users:filter:"))
async def users_filter_cb(query: CallbackQuery) -> None:
    """Foydalanuvchilarni status bo'yicha filtrlash."""
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)

    filter_val = query.data.rsplit(":", 1)[1]
    status_map = {
        "all": None,
        "active": UserStatus.ACTIVE,
        "pending": UserStatus.PENDING,
        "blocked": UserStatus.BLOCKED,
    }
    status = status_map.get(filter_val)

    users = await db.list_users(ctx.user_id, status=status, limit=15)
    if not users:
        await query.answer(f"📭 {filter_val.upper()} foydalanuvchi yo'q.", show_alert=True)
        return

    from core.categories import get_category_label
    label = {
        "all": "👥 Hammasi",
        "active": "🟢 Aktiv",
        "pending": "🟡 Kutilayotgan",
        "blocked": "🔴 Bloklangan",
    }.get(filter_val, "👥")

    lines = [f"{label} <b>({len(users)} ta)</b>", ""]
    for i, u in enumerate(users[:10], 1):
        emoji = {"active": "🟢", "pending": "🟡", "blocked": "🔴"}.get(
            u.get("status", ""), "❓"
        )
        role = u.get("user_role", "")
        role_emoji = {"poster": "📝", "customer": "🔍", "both": "🔄"}.get(role, "")
        cat = u.get("category_code", "")
        cat_str = get_category_label(cat) if cat else ""
        lines.append(
            f"{i}. {emoji}{role_emoji} {fmt.esc(u.get('full_name') or '?')} "
            f"<code>#{u.get('user_id')}</code> {cat_str}"
        )

    items = [
        (
            f"#{u['user_id']} {(u.get('full_name') or '?')[:20]}",
            f"tenant:user:show:{u['user_id']}",
        )
        for u in users[:10]
    ]
    kb = inline_grid(
        items, columns=1,
        extra_rows=[[(Btn.BACK, "tenant:users:back")]],
    )
    if query.message:
        await query.message.answer("\n".join(lines), reply_markup=kb)
    await query.answer()


@router.callback_query(F.data == "tenant:users:back")
async def users_back_cb(query: CallbackQuery) -> None:
    await query.answer()
    if query.message:
        from aiogram.exceptions import TelegramAPIError
        with contextlib.suppress(TelegramAPIError):
            await query.message.delete()


# ═════════════════════════════════════════════════════════════════════
# 👤 FOYDALANUVCHI E'LONLARI VA AUDIT
# ═════════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("tenant:user:posts:"))
async def user_posts_cb(query: CallbackQuery) -> None:
    """Foydalanuvchining e'lonlari (tenant ko'rib chiqishi)."""
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    try:
        target_uid = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        return await query.answer("Notoʻgʻri ID.", show_alert=True)

    posts = await db.list_user_announcements(ctx.user_id, target_uid)
    if not posts:
        return await query.answer("📭 Bu foydalanuvchining e'loni yo'q.", show_alert=True)

    from core.categories import get_category_label
    lines = [f"📋 <b>User #{target_uid} eʼlonlari ({len(posts)} ta)</b>", ""]
    for p in posts[:10]:
        emoji = {
            "active": "🟢", "draft": "📝", "queued": "🟡",
            "paused": "⏸", "expired": "⏰", "deleted": "🗑",
        }.get(p.get("status", ""), "❓")
        cat = get_category_label(p.get("category_code", ""))
        text_preview = (p.get("raw_text") or "")[:50]
        lines.append(
            f"{emoji} #{p['id']} {cat} — {fmt.esc(text_preview)}"
        )

    items = [
        (f"#{p['id']} {(p.get('raw_text') or '?')[:20]}", f"tenant:post:show:{p['id']}")
        for p in posts[:8]
    ]
    kb = inline_grid(
        items, columns=1,
        extra_rows=[[(Btn.BACK, "tenant:users:back")]],
    )
    if query.message:
        await query.message.answer("\n".join(lines), reply_markup=kb)
    await query.answer()


@router.callback_query(F.data.startswith("tenant:user:audit:"))
async def user_audit_cb(query: CallbackQuery) -> None:
    """Foydalanuvchining audit tarixi."""
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    try:
        target_uid = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        return await query.answer("Notoʻgʻri ID.", show_alert=True)

    logs = await db.list_audit(actor_id=target_uid, limit=15)
    # Faqat shu tenant kontekstidagi
    logs = [e for e in logs if e.get("tenant_id") == ctx.user_id]

    if not logs:
        return await query.answer("📭 Tarix bo'sh.", show_alert=True)

    lines = [f"📜 <b>User #{target_uid} tarix (oxirgi {len(logs)} ta)</b>", ""]
    for entry in logs[:15]:
        ts = (entry.get("ts") or "")[:19]
        action = entry.get("action", "?")
        lines.append(f"<code>{ts}</code> → {fmt.esc(action)}")

    if query.message:
        await query.message.answer("\n".join(lines))
    await query.answer()



# ═════════════════════════════════════════════════════════════════════
# 👤 TENANT PROFILE (ko'rish va tahrirlash)
# ═════════════════════════════════════════════════════════════════════
@router.message(F.text == Btn.MY_PROFILE)
async def show_tenant_profile(message: Message) -> None:
    """Tenant — o'z profilini ko'rish va tahrirlash."""
    if message.from_user is None:
        return
    ctx = await _ensure_tenant(message.from_user.id)

    tenant = await db.get_tenant(ctx.user_id)
    if not tenant:
        await message.answer("❌ Profil topilmadi.")
        return

    name = tenant.get("name") or "—"
    username = tenant.get("username") or "—"
    phone = tenant.get("phone") or "—"
    description = tenant.get("description") or "—"
    paid_until = (tenant.get("paid_until") or "")[:10] or "—"
    tariff = tenant.get("tariff", "?").upper()

    text = (
        f"👤 <b>Sizning profilingiz</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Ism: <b>{fmt.esc(name)}</b>\n"
        f"📎 Username: @{fmt.esc(username) if username != '—' else '—'}\n"
        f"📱 Telefon: <code>{fmt.esc(phone)}</code>\n"
        f"📝 Tavsif: {fmt.esc(description)}\n\n"
        f"📦 Tarif: <b>{tariff}</b>\n"
        f"📅 Muddat: {paid_until}\n\n"
        f"<i>Quyida ma'lumotlarni tahrirlashingiz mumkin:</i>"
    )
    await message.answer(text, reply_markup=tenant_kb.profile_edit_panel())


@router.callback_query(F.data.startswith("tenant:profile:edit:"))
async def start_profile_edit(query: CallbackQuery) -> None:
    """Tenant profilini tahrirlash boshlash."""
    if query.from_user is None or not query.data:
        return
    field = query.data.rsplit(":", 1)[1]
    if field not in {"name", "phone", "description"}:
        return await query.answer("Nomaʼlum maydon.", show_alert=True)

    await session.update(
        query.from_user.id,
        step=f"tenant:edit_profile:{field}",
    )

    prompts = {
        "name": "✏️ Yangi ismingizni yozing (max 100 belgi):",
        "phone": (
            "📱 Yangi telefon raqamni yozing.\n"
            "Format: +998 90 123 45 67"
        ),
        "description": (
            "📝 Tavsifni yozing (max 500 belgi).\n"
            "Bu — siz bilan bog'lanish uchun foydali ma'lumot:\n"
            "• Faoliyat soha\n"
            "• Ish vaqti\n"
            "• Murojaat shartlari va h.k."
        ),
    }
    if query.message:
        await query.message.answer(prompts[field])
    await query.answer()


@router.callback_query(F.data == "tenant:profile:back")
async def profile_back_cb(query: CallbackQuery) -> None:
    if query.from_user:
        await session.reset(query.from_user.id)
    await query.answer()
    if query.message:
        from aiogram.exceptions import TelegramAPIError
        with contextlib.suppress(TelegramAPIError):
            await query.message.delete()


# tenant_text_router edit_profile step'ini ham qayta ishlaydi (yuqorida).
# Alohida F.text handler — bu router'da KO'P EMAS — duplicate handler
# muammosini oldini olamiz.


# ═════════════════════════════════════════════════════════════════════
# ⬅️ Universal "Orqaga" handlerlar (settings/channels/posts back)
# ═════════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "tenant:settings:back")
async def settings_back_cb(query: CallbackQuery) -> None:
    """Sozlamalar panelidan orqaga."""
    await query.answer()
    if query.message:
        from aiogram.exceptions import TelegramAPIError
        with contextlib.suppress(TelegramAPIError):
            await query.message.delete()


@router.callback_query(F.data == "tenant:channels:back")
async def channels_back_cb(query: CallbackQuery) -> None:
    """Kanal panelidan orqaga."""
    await query.answer()
    if query.message:
        from aiogram.exceptions import TelegramAPIError
        with contextlib.suppress(TelegramAPIError):
            await query.message.delete()


# ═════════════════════════════════════════════════════════════════════
# 👁 POST VIEW (alias to show)
# ═════════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("tenant:post:view:"))
async def post_view_alias(query: CallbackQuery) -> None:
    """tenant:post:view — show bilan bir xil (alias)."""
    await show_post_detail(query)


# ═════════════════════════════════════════════════════════════════════
# ❌ User REJECT (approve_user_inline'da ishlatiladi)
# ═════════════════════════════════════════════════════════════════════
# `reject_user_cb` allaqachon yuqorida bor — bu blok placeholder izoh.
