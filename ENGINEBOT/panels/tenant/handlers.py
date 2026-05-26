"""
panels/tenant/handlers.py — guruh egasi (tenant) paneli.

ASOSIY FUNKSIYALAR:
───────────────────
- Kanal ulash va boshqaruv
- Foydalanuvchilarni tasdiqlash/bloklash
- E'lonlarni nazorat qilish
- Aylanish (rotation) sozlamalari (ON/OFF, interval, schedule)
- Bot/E'lon qabuli ON/OFF
- Statistika
- Audit log (o'z guruhi)

XAVFSIZLIK:
───────────
Har handler boshida tenant ekanligi tekshiriladi.
Cross-tenant amallar PermissionDenied bilan bloklanadi
(assert_same_tenant orqali).
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from config import Role, Rotation, UserStatus
from core import audit_log, database as db, notifier
from core.permissions import (
    Action,
    PermissionDenied,
    RoleContext,
    assert_can,
    assert_same_tenant,
    can,
    resolve_role,
)
from keyboards import tenant_kb
from keyboards.common_kb import Btn, inline_grid
from utils import formatters as fmt
from utils import logger as log_mod
from utils.confirmation import (
    build_confirmation,
    confirm_block_user,
    confirm_rotation_toggle,
)
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

    # Mavjud tenant?
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
    from keyboards.super_admin_kb import approve_tenant_inline
    from config import SUPER_ADMIN_ID

    try:
        from main import bot  # global bot instance
        await bot.send_message(
            SUPER_ADMIN_ID,
            text=(
                f"🔔 <b>Yangi tenant arizasi</b>\n\n"
                f"👤 <b>{fmt.esc(name)}</b>\n"
                f"🆔 <code>#{uid}</code>\n"
                f"📎 {('@' + fmt.esc(username)) if username else 'username yoʻq'}\n\n"
                f"📦 Auto-trial bilan aktivlashtirildi: {tenant.get('paid_until', '')[:10]}"
            ),
            reply_markup=approve_tenant_inline(uid),
        )
    except Exception as e:
        logger.warning(f"super adminga xabar yuborib boʻlmadi: {e}")

    await message.answer(
        f"✅ <b>Tabriklayman, {fmt.esc(name)}!</b>\n\n"
        f"📦 Sizga {tenant.get('tariff', 'trial').upper()} tarif berildi.\n"
        f"📅 Sinov muddati: {tenant.get('paid_until', '')[:10]}\n\n"
        "Endi /start bosing va kanalingizni ulang.",
    )


# ─────────────────────────────────────────────────────────────────────
# 🔄 Aylanish sozlamalari
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.ROTATION_SETTINGS)
async def show_rotation(message: Message) -> None:
    if message.from_user is None:
        return
    ctx = await _ensure_tenant(message.from_user.id)

    settings = await db.get_settings(ctx.user_id)

    text = (
        f"🔄 <b>Aylanish va boshqaruv</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🤖 Bot: <b>{'🟢 ON' if settings['bot_active'] else '🔴 OFF'}</b>\n"
        f"📥 E'lon qabuli: <b>{'🟢 ON' if settings['post_intake_active'] else '🔴 OFF'}</b>\n"
        f"🔄 Aylanish: <b>{'🟢 ON' if settings['rotation_active'] else '🔴 OFF'}</b>\n\n"
        f"⏱ Interval: <b>{settings['rotation_interval_min']} daq</b>\n"
        f"⏰ Vaqt: {settings['active_from']} — {settings['active_to']}\n"
        f"⏳ Eʼlon yashash: {settings['post_lifetime_hours']} soat\n\n"
        f"<i>Eslatma:</i> Aylanish min {Rotation.MIN_INTERVAL_MIN} daqiqa "
        f"boʻlishi shart."
    )

    kb = tenant_kb.rotation_panel(
        rotation_active=bool(settings["rotation_active"]),
        interval_min=int(settings["rotation_interval_min"]),
        bot_active=bool(settings["bot_active"]),
        post_intake_active=bool(settings["post_intake_active"]),
    )
    await message.answer(text, reply_markup=kb)


# Toggle ON/OFF
@router.callback_query(F.data.startswith("tenant:toggle:"))
async def toggle_setting(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)

    field = query.data.rsplit(":", 1)[1]  # bot / post_intake / rotation
    db_field = {
        "bot": "bot_active",
        "post_intake": "post_intake_active",
        "rotation": "rotation_active",
    }.get(field)
    if not db_field:
        await query.answer("Noma'lum amal.", show_alert=True)
        return

    settings = await db.get_settings(ctx.user_id)
    current = bool(settings[db_field])
    new_value = not current

    # Aylanishni yoqishda — interval tekshirish
    if field == "rotation" and new_value:
        if int(settings["rotation_interval_min"]) < Rotation.MIN_INTERVAL_MIN:
            await query.answer(
                f"⛔ Avval intervalni min {Rotation.MIN_INTERVAL_MIN} daqiqaga sozlang.",
                show_alert=True,
            )
            return

    # Tasdiqlash so'raymiz (oddiy toggle uchun ham)
    if field == "rotation":
        text, kb = confirm_rotation_toggle(
            new_value, int(settings["rotation_interval_min"])
        )
    else:
        labels = {"bot": "Botni", "post_intake": "E'lon qabulini"}
        action_word = "yoqish" if new_value else "to'xtatish"
        text, kb = build_confirmation(
            action_id=f"tenant:apply_toggle:{field}:{1 if new_value else 0}",
            title=f"{labels[field]} {action_word}",
            question=f"Rostan ham {labels[field].lower()} {action_word}ni xohlaysizmi?",
            details=(
                ["📌 Yangi e'lonlar qabul qilinadi", "📌 Aylanish davom etadi"]
                if new_value
                else ["📌 Mavjud e'lonlar saqlanadi", f"📌 Faqat {labels[field].lower()} to'xtaydi"]
            ),
        )
        if query.message:
            await query.message.answer(text, reply_markup=kb)
        await query.answer()
        return

    if query.message:
        await query.message.answer(text, reply_markup=kb)
    # Action_id'ni callback'da qoldiramiz
    await query.answer()


@router.callback_query(F.data.regexp(r"^confirm:yes:tenant:apply_toggle:"))
async def apply_toggle_yes(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    # confirm:yes:tenant:apply_toggle:bot:1
    parts = query.data.split(":")
    field = parts[4]
    new_val = bool(int(parts[5]))

    db_field = {
        "bot": "bot_active",
        "post_intake": "post_intake_active",
        "rotation": "rotation_active",
    }.get(field)
    if not db_field:
        return

    await db.update_settings(ctx.user_id, **{db_field: new_val})
    await audit_log.log_tenant_event(
        ctx,
        action=f"{db_field}_toggled",
        tenant_id=ctx.user_id,
        new_value=new_val,
    )

    if query.message:
        emoji = "🟢" if new_val else "🔴"
        await query.message.answer(
            f"✅ {emoji} {field} → {'ON' if new_val else 'OFF'}"
        )
    await query.answer()


# Rotation ON/OFF tasdiqlash
@router.callback_query(F.data.startswith("confirm:yes:rotation_toggle:"))
async def apply_rotation_toggle(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    new_val = bool(int(query.data.rsplit(":", 1)[1]))

    await db.update_settings(ctx.user_id, rotation_active=new_val)
    await audit_log.log_tenant_event(
        ctx, action="rotation_toggled", tenant_id=ctx.user_id, new_value=new_val
    )
    if query.message:
        await query.message.answer(
            f"✅ Aylanish: {'🟢 ON' if new_val else '🔴 OFF'}"
        )
    await query.answer()


# Interval o'zgartirish
@router.callback_query(F.data == "tenant:rotation:set_interval")
async def show_interval_picker(query: CallbackQuery) -> None:
    if query.from_user is None:
        return
    if query.message:
        await query.message.answer(
            f"⏱ <b>Aylanish intervali</b>\n\n"
            f"Min: {Rotation.MIN_INTERVAL_MIN} daq | Max: {Rotation.MAX_INTERVAL_MIN // 60} soat\n\n"
            "Quyidagidan tanlang yoki o'zingiz kiriting:",
            reply_markup=tenant_kb.interval_quick_picker(),
        )
    await query.answer()


@router.callback_query(F.data.startswith("tenant:interval:set:"))
async def set_interval(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    try:
        n = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        return
    if n < Rotation.MIN_INTERVAL_MIN:
        await query.answer(f"Min {Rotation.MIN_INTERVAL_MIN} daqiqa.", show_alert=True)
        return

    await db.update_settings(ctx.user_id, rotation_interval_min=n)
    await audit_log.log_tenant_event(
        ctx, action="interval_changed", tenant_id=ctx.user_id, interval_min=n
    )
    await query.answer(f"✅ Interval: {n} daqiqa", show_alert=True)


@router.callback_query(F.data == "tenant:interval:custom")
async def ask_custom_interval(query: CallbackQuery) -> None:
    if query.from_user is None:
        return
    await session.update(query.from_user.id, step="tenant:awaiting_interval")
    if query.message:
        await query.message.answer(
            f"⏱ <b>Maxsus interval</b>\n\n"
            f"Daqiqalarda kiriting (min {Rotation.MIN_INTERVAL_MIN}):"
        )
    await query.answer()


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
            "Yangi kanal qo'shish uchun /start menyusidan '➕ Kanal ulash' bosing."
        )
        return

    lines = [f"📺 <b>Kanallaringiz ({len(channels)} ta)</b>", ""]
    for i, ch in enumerate(channels, 1):
        emoji = "🟢" if ch["is_active"] else "🔴"
        lines.append(
            f"{i}. {emoji} <b>{fmt.esc(ch.get('title') or ch.get('channel_username') or '')}</b>\n"
            f"   <code>{ch['channel_id']}</code> | {ch.get('category', 'general')}"
        )
    await message.answer("\n".join(lines))


@router.message(F.text == Btn.ADD_CHANNEL)
async def start_add_channel(message: Message) -> None:
    if message.from_user is None:
        return
    ctx = await _ensure_tenant(message.from_user.id)

    await session.update(message.from_user.id, step="tenant:awaiting_channel")
    await message.answer(
        "➕ <b>Kanal ulash</b>\n\n"
        "1️⃣ Avval botni o'z kanalingizga <b>admin</b> qilib qo'shing\n"
        "2️⃣ Keyin kanal ID yoki @username ni shu yerga yuboring\n\n"
        "Misol:\n"
        "<code>@toshkent_taxi</code>\n"
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

    lines = [
        f"👥 <b>Foydalanuvchilar ({len(users)} ta)</b>",
        f"🟡 Tasdiq kutmoqda: {pending_count}",
        "",
    ]
    for i, u in enumerate(users[:15], 1):
        emoji = {"active": "🟢", "pending": "🟡", "blocked": "🔴"}.get(
            u.get("status", ""), "❓"
        )
        lines.append(
            f"{i}. {emoji} {fmt.esc(u.get('full_name') or '?')} "
            f"<code>#{u.get('user_id')}</code>"
        )

    await message.answer(
        "\n".join(lines),
        reply_markup=tenant_kb.users_filter(),
    )


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


@router.callback_query(F.data.startswith("tenant:user:block:"))
async def start_block_user_cb(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    ctx = await _ensure_tenant(query.from_user.id)
    target_uid = int(query.data.rsplit(":", 1)[1])

    user = await db.get_user(ctx.user_id, target_uid)
    if not user:
        await query.answer("Topilmadi.", show_alert=True)
        return

    await session.update(
        query.from_user.id,
        step="tenant:awaiting_block_reason",
        data={"target_user_id": target_uid},
    )
    if query.message:
        await query.message.answer(
            f"⛔ <b>{fmt.esc(user.get('full_name', ''))} ni bloklash</b>\n\n"
            "Iltimos, sababni yozing (min 3 belgi):"
        )
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
        await query.message.answer(
            "⚠️ Ogohlantirish sababini yozing (min 3 belgi):"
        )
    await query.answer()


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

    lines = ["📜 <b>Mening guruhim — Tarix (oxirgi 15 ta)</b>", ""]
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

    # Faqat tenant'lar uchun
    ctx = await resolve_role(message.from_user.id)
    if ctx.role != Role.TENANT:
        return

    # 1) Kanal ulash
    if state.step == "tenant:awaiting_channel":
        ok, normalized, err = validate_channel(text)
        if not ok:
            await message.answer(err)
            return
        # MVP: -100... formatida bo'lsa int qilamiz, @username bo'lsa
        # Telegram orqali aniqlash kerak (services'da bo'ladi).
        # Hozircha sodda yozib qo'yamiz:
        try:
            channel_id = int(normalized) if normalized.lstrip("-").isdigit() else 0
        except ValueError:
            channel_id = 0

        if not channel_id:
            await message.answer(
                f"⚠️ Hozircha faqat numeric Channel ID qabul qilinadi (-1001234567890).\n"
                f"Telethon integratsiyasi tayyor bo'lganda @username ham ishlaydi."
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
                f"📺 <code>{channel_id}</code>\n"
                f"📎 {fmt.esc(normalized)}"
            )
        await session.reset(message.from_user.id)
        return

    # 2) Custom interval
    if state.step == "tenant:awaiting_interval":
        ok, normalized, err = validate_interval(
            text, min_min=Rotation.MIN_INTERVAL_MIN, max_min=Rotation.MAX_INTERVAL_MIN
        )
        if not ok:
            await message.answer(err)
            return
        n = int(normalized)
        await db.update_settings(ctx.user_id, rotation_interval_min=n)
        await audit_log.log_tenant_event(
            ctx, action="interval_changed", tenant_id=ctx.user_id, interval_min=n
        )
        await session.reset(message.from_user.id)
        await message.answer(f"✅ Interval: {n} daqiqaga o'rnatildi.")
        return

    # 3) Block sababi
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

    # 4) Warn sababi
    if state.step == "tenant:awaiting_warn_reason":
        ok, reason, err = validate_reason(text)
        if not ok:
            await message.answer(err)
            return
        target_uid = int(state.data.get("target_user_id", 0))
        if not target_uid:
            return

        wid = await db.add_warning(
            tenant_id=ctx.user_id,
            user_id=target_uid,
            issued_by=ctx.user_id,
            reason=reason,
        )
        # Ogohlantirishlar sonini olish
        user = await db.get_user(ctx.user_id, target_uid)
        warns = (user or {}).get("warnings_count", 1)
        from config import Limits
        await notifier.notify_user_warned(
            user_id=target_uid,
            tenant_id=ctx.user_id,
            reason=reason,
            warnings_count=warns,
            max_warnings=Limits.MAX_WARNINGS_BEFORE_BLOCK,
        )
        await audit_log.log_user_event(
            ctx,
            action="user_warned",
            target_user_id=target_uid,
            reason=reason,
            warning_id=wid,
        )

        # Limit yaqinlashganmi?
        if warns >= Limits.MAX_WARNINGS_BEFORE_BLOCK:
            # Avtomatik bloklash
            await db.set_user_status(ctx.user_id, target_uid, UserStatus.BLOCKED)
            await notifier.notify_user_blocked(
                user_id=target_uid,
                tenant_id=ctx.user_id,
                reason=f"{warns} ogohlantirish — avtomatik blok",
            )
            await audit_log.log_user_event(
                ctx, action="user_auto_blocked", target_user_id=target_uid, warnings=warns
            )

        await session.reset(message.from_user.id)
        await message.answer(
            f"⚠️ Ogohlantirish berildi.\nUser #{target_uid} | {warns}/{Limits.MAX_WARNINGS_BEFORE_BLOCK}"
        )
        return
