"""
panels/super_admin/handlers.py — bot egasi (siz) uchun panel.

ASOSIY FUNKSIYALAR:
───────────────────
- Tenantlar ro'yxati va boshqaruvi
- To'lov qabul qilish va tarif belgilash
- Pending tenantlarni tasdiqlash (notification ostida)
- Global statistika
- Audit log (global)
- Broadcast xabar
- Tizim holati

XAVFSIZLIK:
───────────
Har bir handler boshida is_super_admin tekshiruvi. Aks holda
PermissionDenied xato — boshqa rol bu funksiyalarni hech qachon
ishlatmasligi kerak.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import (
    BRAND_NAME,
    Role,
    SUPER_ADMIN_ID,
    Tariff,
    TARIFF_LIMITS,
    TenantStatus,
)
from core import audit_log, database as db, notifier, tenant_manager
from core.permissions import (
    Action,
    PermissionDenied,
    RoleContext,
    assert_can,
    can,
    resolve_role,
)
from keyboards import super_admin_kb
from keyboards.common_kb import Btn, inline_grid
from utils import formatters as fmt
from utils import logger as log_mod
from utils.confirmation import (
    build_confirmation,
    parse_confirmation,
)
from utils.session_state import session
from utils.validators import validate_reason

logger = log_mod.get_logger("panels.super_admin")
router = Router(name="super_admin")


# ─────────────────────────────────────────────────────────────────────
# Filter: faqat super admin uchun
# ─────────────────────────────────────────────────────────────────────
async def _ensure_super(uid: int) -> RoleContext:
    """
    Foydalanuvchi super admin ekanligini tasdiqlash.
    Aks holda PermissionDenied raise qilinadi.
    """
    ctx = await resolve_role(uid)
    if ctx.role != Role.SUPER_ADMIN:
        raise PermissionDenied("Bu funksiya faqat Super Admin uchun.")
    return ctx


# ─────────────────────────────────────────────────────────────────────
# 📊 Global statistika
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.GLOBAL_STATS)
async def show_global_stats(message: Message) -> None:
    if message.from_user is None or message.from_user.id != SUPER_ADMIN_ID:
        return
    ctx = await _ensure_super(message.from_user.id)

    stats = await db.global_stats()

    text = fmt.format_stats_card(
        f"{BRAND_NAME} — Global statistika",
        {
            "Tenantlar (jami)": f"{stats['tenants_total']} ta",
            "Aktiv tenantlar": f"🟢 {stats['tenants_active']} ta",
            "Foydalanuvchilar": f"{stats['users_total']} ta",
            "Aktiv e'lonlar": f"📝 {stats['posts_active']} ta",
        },
    )
    await message.answer(text)
    await audit_log.log_action(actor=ctx, action="view_global_stats")


# ─────────────────────────────────────────────────────────────────────
# 👥 Tenantlar ro'yxati
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.ALL_TENANTS)
async def show_tenants(message: Message) -> None:
    if message.from_user is None or message.from_user.id != SUPER_ADMIN_ID:
        return
    ctx = await _ensure_super(message.from_user.id)

    tenants = await db.list_tenants(limit=20)
    if not tenants:
        await message.answer(
            "📭 Hozircha tenant yo'q.\n\nYangi tenantlar /start orqali ro'yxatdan o'tadi.",
            reply_markup=super_admin_kb.tenants_filter(),
        )
        return

    lines = [f"👥 <b>Tenantlar (oxirgi {len(tenants)} ta)</b>", ""]
    for i, t in enumerate(tenants, 1):
        emoji = {
            "active": "🟢",
            "pending": "🟡",
            "paused": "⏸",
            "blocked": "🔴",
        }.get(t.get("status", ""), "❓")
        lines.append(
            f"{i}. {emoji} <b>{fmt.esc(t.get('name') or 'Nomaʼlum')}</b> "
            f"<code>#{t['tenant_id']}</code> — {t.get('tariff', '?')}"
        )
    lines.append("")
    lines.append("Tenant ID ni yuboring batafsil ko'rish uchun:")
    lines.append("Misol: <code>123456789</code>")

    items = [
        (
            f"#{t['tenant_id']} {fmt.esc((t.get('name') or '?')[:20])}",
            f"super:tenant:show:{t['tenant_id']}",
        )
        for t in tenants[:10]
    ]
    kb = inline_grid(
        items,
        columns=1,
        extra_rows=[[("🔍 Filtr", "super:tenants:filter_menu")]],
    )

    await session.update(
        message.from_user.id, step="super:awaiting_tenant_id"
    )
    await message.answer("\n".join(lines), reply_markup=kb)
    await audit_log.log_action(actor=ctx, action="view_all_tenants")


# Tenant batafsil ko'rinish (callback orqali)
@router.callback_query(F.data.startswith("super:tenant:show:"))
async def show_tenant_detail(query: CallbackQuery) -> None:
    if query.from_user.id != SUPER_ADMIN_ID:
        await query.answer("🚫 Ruxsat yo'q.", show_alert=True)
        return
    if not query.data:
        return

    tenant_id = int(query.data.rsplit(":", 1)[1])
    tenant = await db.get_tenant(tenant_id)
    if not tenant:
        await query.answer("Tenant topilmadi.", show_alert=True)
        return

    stats = await db.tenant_stats(tenant_id)
    text = fmt.format_tenant_card(tenant, stats=stats)

    kb = super_admin_kb.tenant_actions(tenant_id, status=tenant.get("status", ""))
    if query.message:
        await query.message.answer(text, reply_markup=kb)
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# Tenant ID matn orqali kiritildi
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text.regexp(r"^\d{6,15}$"))
async def maybe_tenant_lookup(message: Message) -> None:
    if message.from_user is None or message.from_user.id != SUPER_ADMIN_ID:
        return

    state = await session.get(message.from_user.id)
    if state.step != "super:awaiting_tenant_id":
        return  # boshqa kontekstdan kelmagan, tegma

    tenant_id = int((message.text or "").strip())
    tenant = await db.get_tenant(tenant_id)
    if not tenant:
        await message.answer(f"❌ Tenant <code>#{tenant_id}</code> topilmadi.")
        return

    stats = await db.tenant_stats(tenant_id)
    text = fmt.format_tenant_card(tenant, stats=stats)
    kb = super_admin_kb.tenant_actions(tenant_id, status=tenant.get("status", ""))
    await message.answer(text, reply_markup=kb)


# ─────────────────────────────────────────────────────────────────────
# ✅ Pending tenant'ni Trial bilan aktivlashtirish
# ─────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("super:tenant:approve_trial:"))
async def approve_tenant_trial(query: CallbackQuery) -> None:
    if query.from_user.id != SUPER_ADMIN_ID or not query.data:
        return await query.answer("🚫 Ruxsat yo'q.", show_alert=True)

    ctx = await _ensure_super(query.from_user.id)
    tenant_id = int(query.data.rsplit(":", 1)[1])

    await tenant_manager.activate_trial(tenant_id)
    await audit_log.log_tenant_event(
        ctx, "tenant_approved", tenant_id, mode="trial"
    )
    await query.answer("✅ Trial bilan aktivlashtirildi", show_alert=True)
    if query.message:
        tenant = await db.get_tenant(tenant_id)
        if tenant:
            await query.message.answer(fmt.format_tenant_card(tenant))


# ─────────────────────────────────────────────────────────────────────
# 💰 Yangi to'lov qabul qilish
# ─────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("super:tenant:add_payment:"))
async def start_add_payment(query: CallbackQuery) -> None:
    """Yangi tenant tasdiqlash yoki muddat uzaytirish — tarif tanlash."""
    if query.from_user.id != SUPER_ADMIN_ID or not query.data:
        return await query.answer("🚫 Ruxsat yo'q.", show_alert=True)

    tenant_id = int(query.data.rsplit(":", 1)[1])
    if query.message:
        await query.message.answer(
            f"📅 <b>Tarif va muddat belgilash</b>\n\n"
            f"Tenant: <code>#{tenant_id}</code>\n\n"
            "Tarifni tanlang:",
            reply_markup=super_admin_kb.tariff_picker(tenant_id),
        )
    await query.answer()


@router.callback_query(F.data.startswith("super:tenant:extend:"))
async def start_extend_subscription(query: CallbackQuery) -> None:
    """'Muddat uzaytirish' tugmasi — add_payment bilan bir xil flow."""
    await start_add_payment(query)


@router.callback_query(F.data.startswith("super:payment:tariff:"))
async def select_tariff(query: CallbackQuery) -> None:
    """Tarif tanlandi — endi muddat (kun) so'raymiz.

    PULSIZ MODEL: og'zaki kelishuv asosida super admin tarif va
    muddatni o'zi belgilaydi. Pul kiritish flow'i olib tashlandi.
    """
    if query.from_user.id != SUPER_ADMIN_ID or not query.data:
        return await query.answer("🚫 Ruxsat yo'q.", show_alert=True)

    parts = query.data.split(":")
    if len(parts) < 5:
        return
    tenant_id = int(parts[3])
    tariff = parts[4]

    if tariff not in Tariff.ALL:
        await query.answer("Noto'g'ri tarif.", show_alert=True)
        return

    limits = TARIFF_LIMITS[tariff]
    default_days = limits["duration_days"]
    description = limits.get("description", tariff.upper())

    # Session'ga saqlaymiz — keyin kun kiritsin yoki default'ni tanlasin
    await session.update(
        query.from_user.id,
        step="super:awaiting_period_days",
        data={
            "tenant_id": tenant_id,
            "tariff": tariff,
            "default_days": default_days,
        },
    )

    text = (
        f"📅 <b>Muddat belgilash</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🏢 Tenant: <code>#{tenant_id}</code>\n"
        f"📦 Tarif: {description}\n"
        f"📅 Default muddat: {default_days} kun\n\n"
        f"Necha kunga aktivlashtirish kerak?\n"
        f"Raqamni kiriting (masalan: <code>{default_days}</code>)\n\n"
        f"<i>ENGINEBOT'da pul tizimi yo'q — bu og'zaki kelishuv asosidagi muddat.</i>"
    )
    if query.message:
        await query.message.answer(text)
    await query.answer()


@router.message(F.text.regexp(r"^\d+$"))
async def receive_period_days(message: Message) -> None:
    """Super admin muddat (kun) kiritdi — tasdiqlash so'raymiz."""
    if message.from_user is None or message.from_user.id != SUPER_ADMIN_ID:
        return

    state = await session.get(message.from_user.id)
    if state.step != "super:awaiting_period_days":
        return  # boshqa flow

    try:
        days = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Raqam kiriting (masalan: 30)")
        return

    if days < 1 or days > 3650:
        await message.answer("❌ 1 dan 3650 kun oralig'ida bo'lsin.")
        return

    data = state.data
    tenant_id = int(data["tenant_id"])
    tariff = str(data["tariff"])
    description = TARIFF_LIMITS.get(tariff, {}).get("description", tariff.upper())

    text, kb = build_confirmation(
        action_id=f"super:confirm_extend:{tenant_id}",
        title="Muddat uzaytirish",
        question=f"Tenant <code>#{tenant_id}</code> uchun:",
        details=[
            f"📦 Tarif: {description}",
            f"📅 Muddat: <b>{days} kun</b>",
        ],
        warning="✅ Tasdiqlasangiz tenant darhol aktivlashadi.",
    )
    state.data["period_days"] = days
    state.step = "super:confirm_extend_pending"
    await session.set(message.from_user.id, state)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("confirm:yes:super:confirm_extend:"))
async def confirm_extend_yes(query: CallbackQuery) -> None:
    """Muddat uzaytirish tasdiqlandi — extend_subscription chaqirish."""
    if query.from_user.id != SUPER_ADMIN_ID or not query.data:
        return await query.answer("🚫", show_alert=True)

    state = await session.get(query.from_user.id)
    if state.step != "super:confirm_extend_pending":
        await query.answer("Sessiya muddati o'tib ketdi.", show_alert=True)
        return

    data = state.data
    tenant_id = int(data["tenant_id"])
    tariff = str(data["tariff"])
    period_days = int(data["period_days"])

    payment_id = await tenant_manager.extend_subscription(
        tenant_id=tenant_id,
        tariff=tariff,
        period_days=period_days,
        approved_by=query.from_user.id,
        note="Og'zaki kelishuv asosida — super admin tomonidan",
    )

    await session.reset(query.from_user.id)

    if query.message:
        await query.message.answer(
            f"✅ Muddat uzaytirildi!\n\n"
            f"📋 Yozuv ID: #{payment_id}\n"
            f"🏢 Tenant: #{tenant_id}\n"
            f"📦 {tariff.upper()}\n"
            f"📅 {period_days} kun"
        )
    await query.answer("✅ Tasdiqlandi", show_alert=True)


@router.callback_query(F.data.startswith("confirm:no:super:confirm_extend:"))
async def confirm_extend_no(query: CallbackQuery) -> None:
    """Muddat uzaytirish bekor qilindi."""
    if query.from_user.id != SUPER_ADMIN_ID:
        return
    await session.reset(query.from_user.id)
    if query.message:
        await query.message.answer("❌ Bekor qilindi.")
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# Eski to'lov tasdiqlash callback'lari (backward compat)
# ─────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("confirm:yes:super:confirm_payment:"))
async def confirm_payment_yes(query: CallbackQuery) -> None:
    """Eski to'lov tasdiqlash — endi extend bilan bir xil."""
    await confirm_extend_yes(query)


@router.callback_query(F.data.startswith("confirm:no:super:confirm_payment:"))
async def confirm_payment_no(query: CallbackQuery) -> None:
    """Eski bekor qilish — endi extend no bilan bir xil."""
    await confirm_extend_no(query)


# ─────────────────────────────────────────────────────────────────────
# ⛔ Tenant'ni bloklash (tasdiqlash bilan)
# ─────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("super:tenant:block:"))
async def start_block_tenant(query: CallbackQuery) -> None:
    if query.from_user.id != SUPER_ADMIN_ID or not query.data:
        return await query.answer("🚫", show_alert=True)

    tenant_id = int(query.data.rsplit(":", 1)[1])
    await session.update(
        query.from_user.id,
        step="super:awaiting_block_reason",
        data={"target_tenant_id": tenant_id},
    )
    if query.message:
        await query.message.answer(
            f"⛔ <b>Tenant'ni bloklash</b>\n\n"
            f"Tenant: <code>#{tenant_id}</code>\n\n"
            "Iltimos, bloklash sababini yozing (min 3 belgi):"
        )
    await query.answer()


@router.callback_query(F.data.startswith("super:tenant:unblock:"))
async def unblock_tenant_cb(query: CallbackQuery) -> None:
    if query.from_user.id != SUPER_ADMIN_ID or not query.data:
        return await query.answer("🚫", show_alert=True)
    ctx = await _ensure_super(query.from_user.id)
    tenant_id = int(query.data.rsplit(":", 1)[1])
    await tenant_manager.unblock_tenant(tenant_id, unblocked_by=ctx.user_id)
    await query.answer("✅ Tiklandi", show_alert=True)
    if query.message:
        tenant = await db.get_tenant(tenant_id)
        if tenant:
            await query.message.answer(fmt.format_tenant_card(tenant))


@router.callback_query(F.data.startswith("super:tenant:pause:"))
async def pause_tenant_cb(query: CallbackQuery) -> None:
    if query.from_user.id != SUPER_ADMIN_ID or not query.data:
        return await query.answer("🚫", show_alert=True)
    tenant_id = int(query.data.rsplit(":", 1)[1])
    await tenant_manager.pause_tenant(tenant_id, reason="Super admin tomonidan pause")
    await query.answer("⏸ Pause qilindi", show_alert=True)


# ─────────────────────────────────────────────────────────────────────
# 📜 Global audit log
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.GLOBAL_AUDIT)
async def show_global_audit(message: Message) -> None:
    if message.from_user is None or message.from_user.id != SUPER_ADMIN_ID:
        return
    ctx = await _ensure_super(message.from_user.id)

    logs = await audit_log.get_global_audit(limit=20)
    if not logs:
        await message.answer("📭 Audit log bo'sh.")
        return

    lines = ["📜 <b>Global audit log (oxirgi 20 ta)</b>", ""]
    for entry in logs:
        ts = (entry.get("ts") or "")[:19]
        level_emoji = {
            "info": "ℹ️",
            "warn": "⚠️",
            "error": "❌",
            "critical": "🚨",
        }.get(entry.get("level", "info"), "•")
        lines.append(
            f"{level_emoji} <code>{ts}</code> "
            f"<b>{fmt.esc(entry.get('actor_role', '?'))}</b>"
            f"#{entry.get('actor_id')} → {fmt.esc(entry.get('action', '?'))}"
        )

    await message.answer("\n".join(lines))
    await audit_log.log_action(actor=ctx, action="view_global_audit")


# ─────────────────────────────────────────────────────────────────────
# 🛠 Tizim
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.SYSTEM)
async def show_system(message: Message) -> None:
    if message.from_user is None or message.from_user.id != SUPER_ADMIN_ID:
        return
    await message.answer(
        f"🛠 <b>Tizim paneli</b>\n\nQuyidagi amallarni bajarishingiz mumkin:",
        reply_markup=super_admin_kb.system_menu(),
    )


@router.callback_query(F.data == "super:system:status")
async def system_status(query: CallbackQuery) -> None:
    if query.from_user.id != SUPER_ADMIN_ID:
        return
    stats = await db.global_stats()
    text = fmt.format_stats_card(
        "Tizim holati",
        {
            "Tenantlar": stats["tenants_total"],
            "Aktiv": stats["tenants_active"],
            "Userlar": stats["users_total"],
            "Aktiv eʼlonlar": stats["posts_active"],
        },
    )
    if query.message:
        await query.message.answer(text)
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# 📨 Broadcast (sodda variant)
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.BROADCAST)
async def start_broadcast(message: Message) -> None:
    if message.from_user is None or message.from_user.id != SUPER_ADMIN_ID:
        return
    await session.update(
        message.from_user.id, step="super:awaiting_broadcast_text"
    )
    await message.answer(
        "📨 <b>Broadcast</b>\n\n"
        "Yuboriladigan matnni kiriting (HTML qoʻllab-quvvatlanadi).\n\n"
        "/cancel — bekor qilish"
    )


# ─────────────────────────────────────────────────────────────────────
# Block sababini matn orqali olish
# ─────────────────────────────────────────────────────────────────────
async def _in_super_flow(message: Message) -> bool:
    """Filter: faqat super_admin flow state'ida ishlaydi."""
    if message.from_user is None or message.from_user.id != SUPER_ADMIN_ID:
        return False
    state = await session.get(message.from_user.id)
    return state.step.startswith("super:")


@router.message(F.text, _in_super_flow)
async def handle_super_admin_text(message: Message) -> None:
    """
    Boshqa filterlardan oʻtmagan matnlar shu yerga keladi.

    Block sababi, broadcast matni va h.k. - state'ga qarab yo'naltiradi.
    """
    if message.from_user is None or message.from_user.id != SUPER_ADMIN_ID:
        return

    state = await session.get(message.from_user.id)

    if state.step == "super:awaiting_block_reason":
        ok, reason, err = validate_reason(message.text or "")
        if not ok:
            await message.answer(err)
            return
        tenant_id = int(state.data.get("target_tenant_id", 0))
        if not tenant_id:
            return
        await tenant_manager.block_tenant(
            tenant_id, reason=reason, blocked_by=message.from_user.id
        )
        await session.reset(message.from_user.id)
        await message.answer(
            f"⛔ Tenant <code>#{tenant_id}</code> bloklandi.\nSabab: {fmt.esc(reason)}"
        )
        return

    if state.step == "super:awaiting_broadcast_text":
        text = (message.text or "").strip()
        if not text:
            await message.answer("Matn boʻsh.")
            return
        # Hamma aktiv tenantga yuboramiz (notification orqali)
        tenants = await db.list_tenants(status=TenantStatus.ACTIVE, limit=10000)
        sent = 0
        for t in tenants:
            try:
                await notifier.notify_info(
                    user_id=t["tenant_id"],
                    tenant_id=t["tenant_id"],
                    title="📨 Bot egasidan xabar",
                    message=text,
                )
                sent += 1
            except Exception as e:
                logger.error(f"broadcast send fail {t['tenant_id']}: {e}")
        await session.reset(message.from_user.id)
        await message.answer(f"✅ Broadcast: {sent}/{len(tenants)} tenant ga yuborildi.")
        return
