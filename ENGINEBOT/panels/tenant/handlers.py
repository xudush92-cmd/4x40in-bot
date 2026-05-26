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
from utils.validators import validate_channel, validate_interval, validate_reason

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
    with contextlib.suppress(Exception):
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
    await query.answer(f"✅ {'🟢 ON' if new_val else '🔴 OFF'}", show_alert=True)


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
        "2️⃣ Keyin kanal ID yoki @username ni shu yerga yuboring\n\n"
        "Misol:\n"
        "<code>@toshkent_xizmatlar</code>\n"
        "yoki\n"
        "<code>-1001234567890</code>"
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
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    target_uid = int(query.data.rsplit(":", 1)[1])

    await db.set_user_status(ctx.user_id, target_uid, UserStatus.ACTIVE)
    await audit_log.log_user_event(
        ctx, action="user_unblocked", target_user_id=target_uid
    )
    await query.answer("✅ Tiklandi", show_alert=True)


# ─────────────────────────────────────────────────────────────────────
# 📊 Statistika
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.STATS)
async def show_stats(message: Message) -> None:
    if message.from_user is None:
        return
    ctx = await _ensure_tenant(message.from_user.id)

    stats = await db.tenant_stats(ctx.user_id)
    text = fmt.format_stats_card(
        "Mening guruhim — Statistika",
        {
            "Foydalanuvchilar (jami)": stats["users_total"],
            "Aktiv foydalanuvchilar": stats["users_active"],
            "Aktiv eʼlonlar": stats["posts_active"],
            "Kanallar": stats["channels_active"],
        },
    )
    await message.answer(text)


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
@router.message(F.text)
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
        try:
            channel_id = int(normalized) if normalized.lstrip("-").isdigit() else 0
        except ValueError:
            channel_id = 0

        if not channel_id:
            await message.answer(
                "⚠️ Hozircha faqat numeric Channel ID qabul qilinadi (-1001234567890).\n"
                "@username uchun kelajakda qoʻshamiz."
            )
            return

        ok, status = await db.add_channel(
            tenant_id=ctx.user_id,
            channel_id=channel_id,
            channel_username=normalized if normalized.startswith("@") else "",
        )
        if not ok and status == "duplicate":
            await message.answer("ℹ️ Bu kanal allaqachon ulangan.")
        else:
            await audit_log.log_action(
                actor=ctx,
                action="channel_added",
                target_type="channel",
                target_id=channel_id,
            )
            await message.answer(
                f"✅ Kanal ulandi!\n\n"
                f"📺 <code>{channel_id}</code>"
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
