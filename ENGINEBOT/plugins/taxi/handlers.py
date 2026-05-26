"""
plugins/taxi/handlers.py — taxi plugin'ning bot handlerlari.

ASOSIY OQIM (e'lon yaratish):
─────────────────────────────
1. 📝 "Yangi e'lon" tugmasi → mashina ma'lumotlari (agar yo'q bo'lsa)
2. Qayerdan? → 14 ta viloyat
3. Qayerga? → 13 ta viloyat (qayerdan tashqari)
4. Qachon? → vaqt presetlari
5. Bo'sh joy soni? → 1-7
6. Narx? → kelishuv yoki belgilangan
7. Tasdiqlash → kanalga yuborish
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from config import (
    DEFAULT_TZ_OFFSET,
    PostStatus,
    Role,
    Rotation,
    UserStatus,
)
from core import audit_log, database as db, notifier
from core.event_bus import Events, bus
from core.permissions import resolve_role
from keyboards import routes
from keyboards.common_kb import Btn, inline_grid
from keyboards.routes import (
    car_color_keyboard,
    get_region_clean_name,
    price_type_keyboard,
    regions_keyboard,
    seats_keyboard,
    time_keyboard,
)
from utils import formatters as fmt
from utils import logger as log_mod
from utils.confirmation import build_confirmation
from utils.session_state import session
from utils.validators import (
    validate_amount_uzs,
    validate_car_plate,
    validate_post_text,
)

logger = log_mod.get_logger("plugins.taxi")
router = Router(name="plugin.taxi")

PLUGIN_CODE = "taxi"


# ─────────────────────────────────────────────────────────────────────
# 📝 "Yangi e'lon" tugmasi — flow boshlanishi
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.NEW_POST)
async def start_new_post(message: Message) -> None:
    if message.from_user is None:
        return

    state = await session.get(message.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        await message.answer("Avval guruh tanlang. /start")
        return

    # User aktiv ekanligini tekshirish
    user = await db.get_user(tenant_id, message.from_user.id)
    if not user or user.get("status") != UserStatus.ACTIVE:
        await message.answer(
            "⏳ Profilingiz hali tasdiqlanmagan.\n\n"
            "Iltimos, kanal egasi tasdiqlashini kuting."
        )
        return

    # Tenant qabul qilayaptimi?
    from core.tenant_manager import can_accept_new_post
    can, reason = await can_accept_new_post(tenant_id)
    if not can:
        msg = {
            "tenant_status:paused": "⏸ Bot toʻlov muddati tufayli pause holatida.",
            "tenant_status:blocked": "🚫 Bot bloklangan.",
            "bot_off": "⛔ Bot guruh egasi tomonidan toʻxtatilgan.",
            "post_intake_off": "⛔ Yangi eʼlon qabuli vaqtincha toʻxtatilgan.",
        }.get(reason, "❌ Eʼlon qabul qilinmaydi.")
        await message.answer(msg)
        return

    # Profilda mashina ma'lumotlari bormi?
    profile = user.get("profile_data") or {}
    if isinstance(profile, str):
        import json
        try:
            profile = json.loads(profile)
        except Exception:
            profile = {}

    if not all(k in profile and profile[k] for k in ("car_model", "car_color", "car_plate")):
        # Avval mashina ma'lumotlarini so'raymiz
        await session.update(
            message.from_user.id,
            step="taxi:awaiting_car_model",
        )
        await message.answer(
            "🚗 <b>Avval mashina ma'lumotlarini kiritamiz</b>\n\n"
            "1️⃣ <b>Mashina markasi va modeli:</b>\n"
            "(Misol: Chevrolet Cobalt, Lacetti, Cobalt 2020)"
        )
        return

    # Mashina bor — to'g'ridan-to'g'ri yo'nalish
    await _ask_from_region(message)


# ─────────────────────────────────────────────────────────────────────
# Mashina ma'lumotlarini olish
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text)
async def taxi_text_router(message: Message) -> None:
    """Taxi flow ichida matn kiritilgan bo'lsa."""
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)
    text = (message.text or "").strip()

    # 1) Mashina markasi
    if state.step == "taxi:awaiting_car_model":
        if len(text) < 2 or len(text) > 100:
            await message.answer("🚗 Mashina markasi 2-100 belgi bo'lishi kerak.")
            return
        state.data["car_model"] = text
        state.step = "taxi:awaiting_car_color"
        await session.set(message.from_user.id, state)
        await message.answer(
            f"✅ Marka: {fmt.esc(text)}\n\n"
            "2️⃣ <b>Mashina rangini tanlang:</b>",
            reply_markup=car_color_keyboard("taxi:car_color"),
        )
        return

    # 2) Davlat raqami
    if state.step == "taxi:awaiting_car_plate":
        ok, plate, err = validate_car_plate(text)
        if not ok:
            await message.answer(err)
            return
        state.data["car_plate"] = plate
        await _save_profile_and_continue(message)
        return

    # 3) Custom narx (fixed)
    if state.step == "taxi:awaiting_price":
        ok, normalized, err = validate_amount_uzs(text)
        if not ok:
            await message.answer(err)
            return
        state.data["content"]["price_amount"] = int(normalized)
        await session.set(message.from_user.id, state)
        await _show_post_preview(message)
        return


# Mashina rangi
@router.callback_query(F.data.startswith("taxi:car_color:"))
async def select_car_color(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    color_code = query.data.rsplit(":", 1)[1]
    if color_code == "back":
        return  # MVP: orqaga qaytarish keyinroq

    state = await session.get(query.from_user.id)
    if state.step != "taxi:awaiting_car_color":
        return await query.answer()

    state.data["car_color"] = color_code
    state.step = "taxi:awaiting_car_plate"
    await session.set(query.from_user.id, state)

    if query.message:
        await query.message.answer(
            f"✅ Rang: {fmt.esc(routes.get_car_color_name(color_code))}\n\n"
            "3️⃣ <b>Davlat raqami:</b>\n"
            "(Misol: 01A123BC)"
        )
    await query.answer()


async def _save_profile_and_continue(message: Message) -> None:
    """Mashina ma'lumotlari to'liq — profile'ga saqlab, e'lon flow'ga o'tish."""
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        return

    profile = {
        "car_model": state.data.get("car_model"),
        "car_color": state.data.get("car_color"),
        "car_plate": state.data.get("car_plate"),
    }

    user = await db.get_user(tenant_id, message.from_user.id)
    existing_profile = (user or {}).get("profile_data") or {}
    if isinstance(existing_profile, str):
        import json
        try:
            existing_profile = json.loads(existing_profile)
        except Exception:
            existing_profile = {}
    existing_profile.update(profile)

    await db.update_user(
        tenant_id, message.from_user.id, profile_data=existing_profile
    )

    await message.answer(
        f"✅ Mashina ma'lumotlari saqlandi.\n\n"
        f"🚗 {fmt.esc(profile['car_model'])} | "
        f"{fmt.esc(routes.get_car_color_name(profile['car_color'] or ''))} | "
        f"{fmt.esc(profile['car_plate'])}\n\n"
        "Endi e'lon yarataylik..."
    )

    # Yo'nalish bo'limiga o'tish
    await _ask_from_region(message)


# ─────────────────────────────────────────────────────────────────────
# Yo'nalish: qaerdan
# ─────────────────────────────────────────────────────────────────────
async def _ask_from_region(message: Message) -> None:
    if message.from_user is None:
        return
    await session.update(
        message.from_user.id,
        step="taxi:choosing_from",
        data={"content": {}},
    )
    await message.answer(
        "📍 <b>QAYERDAN ketmoqchisiz?</b>",
        reply_markup=regions_keyboard("taxi:from"),
    )


@router.callback_query(F.data.startswith("taxi:from:"))
async def select_from_region(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    code = query.data.rsplit(":", 1)[1]
    if code == "back":
        return await query.answer()

    state = await session.get(query.from_user.id)
    if "content" not in state.data:
        state.data["content"] = {}
    state.data["content"]["from_region"] = code
    state.step = "taxi:choosing_to"
    await session.set(query.from_user.id, state)

    name = routes.get_region_name(code)
    if query.message:
        await query.message.answer(
            f"✅ Qayerdan: <b>{fmt.esc(name)}</b>\n\n"
            "📍 <b>QAYERGA bormoqchisiz?</b>",
            reply_markup=regions_keyboard("taxi:to", exclude=code),
        )
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# Yo'nalish: qaerga
# ─────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("taxi:to:"))
async def select_to_region(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    code = query.data.rsplit(":", 1)[1]
    if code == "back":
        return await query.answer()

    state = await session.get(query.from_user.id)
    state.data["content"]["to_region"] = code
    state.step = "taxi:choosing_time"
    await session.set(query.from_user.id, state)

    name = routes.get_region_name(code)
    if query.message:
        await query.message.answer(
            f"✅ Qayerga: <b>{fmt.esc(name)}</b>\n\n"
            "⏰ <b>QACHON ketasiz?</b>",
            reply_markup=time_keyboard("taxi:time"),
        )
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# Vaqt
# ─────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("taxi:time:"))
async def select_time(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    code = query.data.rsplit(":", 1)[1]
    if code == "back":
        return await query.answer()
    if code == "custom":
        # MVP: custom vaqt keyingi versiyada
        await query.answer("Hozircha presetlardan tanlang.", show_alert=True)
        return

    label_map = {
        "now": "🚀 Hozir",
        "in_1h": "⏰ 1 soatdan keyin",
        "in_2h": "⏰ 2 soatdan keyin",
        "today_evening": "📅 Bugun kechqurun",
        "tomorrow": "📅 Ertaga",
        "day_after": "📅 Indinga",
    }
    label = label_map.get(code, code)

    state = await session.get(query.from_user.id)
    state.data["content"]["departure_time"] = label
    state.data["content"]["departure_code"] = code
    state.step = "taxi:choosing_seats"
    await session.set(query.from_user.id, state)

    if query.message:
        await query.message.answer(
            f"✅ Vaqt: <b>{label}</b>\n\n"
            "💺 <b>NECHTA bo'sh joy bor?</b>",
            reply_markup=seats_keyboard("taxi:seats"),
        )
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# Joy soni
# ─────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("taxi:seats:"))
async def select_seats(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    code = query.data.rsplit(":", 1)[1]
    if code == "back":
        return await query.answer()
    try:
        seats = int(code)
    except ValueError:
        return

    state = await session.get(query.from_user.id)
    state.data["content"]["seats"] = seats
    state.step = "taxi:choosing_price"
    await session.set(query.from_user.id, state)

    if query.message:
        await query.message.answer(
            f"✅ Joylar: <b>{seats} ta</b>\n\n"
            "💰 <b>NARX qanday?</b>",
            reply_markup=price_type_keyboard("taxi:price_type"),
        )
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# Narx turi
# ─────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("taxi:price_type:"))
async def select_price_type(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    ptype = query.data.rsplit(":", 1)[1]
    if ptype == "back":
        return await query.answer()

    state = await session.get(query.from_user.id)
    state.data["content"]["price_type"] = ptype

    if ptype == "fixed":
        state.step = "taxi:awaiting_price"
        await session.set(query.from_user.id, state)
        if query.message:
            await query.message.answer(
                "💰 Narxni so'mda kiriting:\n(Misol: <code>200000</code>)"
            )
        await query.answer()
        return

    # negotiable — preview
    state.data["content"]["price_amount"] = None
    await session.set(query.from_user.id, state)
    if query.message:
        await _show_post_preview(query.message)
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# Preview va tasdiqlash
# ─────────────────────────────────────────────────────────────────────
async def _show_post_preview(message: Message) -> None:
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        return

    user = await db.get_user(tenant_id, message.from_user.id)
    if not user:
        return

    from plugins.taxi.templates import render_taxi_post

    body = render_taxi_post(state.data["content"], user)
    preview = (
        "<b>📋 E'LONNI TEKSHIRING:</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"{body}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Bu e'lon kanalga chiqadi va boshqalar ko'radi."
    )

    text, kb = build_confirmation(
        action_id="taxi:publish",
        title="E'lonni joylashtirish",
        question="Yuqoridagi e'lon to'g'rimi?",
        details=["📌 Eʼlon darhol kanalga chiqadi"],
        warning="✅ Tasdiqlasangiz e'lon avtomatik joylashadi.",
    )
    await message.answer(preview)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "confirm:yes:taxi:publish")
async def confirm_publish(query: CallbackQuery) -> None:
    if query.from_user is None:
        return

    state = await session.get(query.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        await query.answer("Sessiya muddati o'tib ketdi.", show_alert=True)
        return

    content = state.data.get("content", {})
    user = await db.get_user(tenant_id, query.from_user.id)
    if not user:
        return

    # Birinchi aktiv kanalni topamiz (MVP — keyinchalik tanlash)
    channels = await db.list_channels(tenant_id, only_active=True)
    if not channels:
        await query.answer("Hech qanday kanal ulanmagan.", show_alert=True)
        return
    channel_id = channels[0]["channel_id"]

    # Tarif limitini olish
    from core.tenant_manager import get_tariff_info
    tenant = await db.get_tenant(tenant_id)
    limits = await get_tariff_info(tenant or {})
    max_active = int(limits.get("max_active_posts_per_user", 3))

    # Lifetime
    settings = await db.get_settings(tenant_id)
    lifetime = int(settings.get("post_lifetime_hours", Rotation.DEFAULT_LIFETIME_HOURS))

    # Render qilish
    from plugins.taxi.templates import render_taxi_post
    rendered = render_taxi_post(content, user)

    ok, status, post_id = await db.create_announcement(
        tenant_id=tenant_id,
        user_id=query.from_user.id,
        channel_id=channel_id,
        plugin=PLUGIN_CODE,
        content_data=content,
        rendered_text=rendered,
        lifetime_hours=lifetime,
        max_active_per_user=max_active,
    )
    if not ok:
        if status == "limit":
            await query.answer(
                f"⛔ Sizda allaqachon {max_active} ta aktiv e'lon bor.",
                show_alert=True,
            )
        else:
            await query.answer(f"❌ Xato: {status}", show_alert=True)
        return

    # Statusni 'active' qilamiz va publisher tomonidan kanalga yuboriladi
    await db.update_announcement(post_id, tenant_id, status=PostStatus.ACTIVE)

    await audit_log.log_post_event(
        actor=await resolve_role(query.from_user.id, tenant_id=tenant_id),
        action="post_created",
        post_id=post_id,
        plugin=PLUGIN_CODE,
        channel_id=channel_id,
    )

    await bus.emit(
        Events.POST_CREATED,
        {
            "post_id": post_id,
            "tenant_id": tenant_id,
            "user_id": query.from_user.id,
            "channel_id": channel_id,
            "plugin": PLUGIN_CODE,
        },
    )

    await session.reset(query.from_user.id)
    await session.update(query.from_user.id, tenant_id=tenant_id)

    if query.message:
        await query.message.answer(
            f"✅ E'lon muvaffaqiyatli yaratildi!\n\n"
            f"📋 Post ID: <code>#{post_id}</code>\n"
            f"📺 Kanalga publisher tomonidan yuboriladi (bir necha soniya ichida).\n\n"
            f"📊 Eʼlon yashash muddati: {lifetime} soat"
        )
    await query.answer("✅ Yaratildi", show_alert=True)


@router.callback_query(F.data == "confirm:no:taxi:publish")
async def cancel_publish(query: CallbackQuery) -> None:
    if query.from_user is None:
        return
    await session.reset(query.from_user.id)
    if query.message:
        await query.message.answer("❌ E'lon bekor qilindi.")
    await query.answer()
