"""
panels/poster/handlers.py — poster (e'lon beruvchi) paneli.

ASOSIY OQIM:
────────────
1. "Men eʼlon beraman" tugmasi → tenant tanlash
2. Kategoriya tanlash (taxi, usta, ...)
3. Yengil ro'yxat (ism, telefon, viloyat)
4. Tenant tasdiqlaydi (yoki avto-tasdiq)
5. Poster bosh menyuga kiradi:
   - ➕ Yangi e'lon (erkin matn + ixtiyoriy rasm)
   - 📋 Mening e'lonlarim (gala — queue_order bo'yicha)
   - ▶️/⛔ START/STOP — auto-rotation yoqish/o'chirish
   - ⏱ Interval — 10 daqdan kam emas
   - 🔄 Soha o'zgartirish

PER-POSTER ROTATION:
────────────────────
Posterning eʼlonlari ketma-ket galadan chiqadi (services/scheduler.py).
Bu yerda — faqat boshqaruv (START/STOP, interval, e'lon CRUD).
"""

from __future__ import annotations

import contextlib

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from config import (
    Limits,
    PostStatus,
    Role,
    Rotation,
    UserRole,
    UserStatus,
    get_tariff_limit,
)
from core import audit_log, database as db, notifier
from core.categories import all_categories, get_category_label, is_valid_category
from core.event_bus import Events, bus
from core.permissions import RoleContext, resolve_role
from keyboards import user_kb
from keyboards.common_kb import Btn, inline_grid, request_contact
from utils import formatters as fmt
from utils import logger as log_mod
from utils.confirmation import build_confirmation
from utils.session_state import session
from utils.validators import validate_interval, validate_name, validate_phone

logger = log_mod.get_logger("panels.poster")
router = Router(name="poster")


# ─────────────────────────────────────────────────────────────────────
# 1. "Men eʼlon beraman" tugmasi
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.I_AM_POSTER)
async def i_am_poster(message: Message) -> None:
    if message.from_user is None:
        return

    uid = message.from_user.id
    state = await session.get(uid)
    tenant_id = state.tenant_id

    if tenant_id:
        await _start_registration(message, tenant_id, role_target=UserRole.POSTER)
        return

    from config import TenantStatus
    tenants = await db.list_tenants(status=TenantStatus.ACTIVE, limit=20)
    if not tenants:
        await message.answer(
            "📭 Hozircha aktiv guruhlar yoʻq.\n\n"
            "Iltimos, kanal egasi botni sozlasin va sizga deep-link bersin."
        )
        return

    items = [
        (
            f"🏢 {(t.get('name') or '?')[:30]}",
            f"poster:select_tenant:{t['tenant_id']}",
        )
        for t in tenants
    ]
    kb = inline_grid(items, columns=1)
    await message.answer(
        "🏢 <b>Qaysi guruhda eʼlon berasiz?</b>\n\n"
        "Quyidagi roʻyxatdan tanlang:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("poster:select_tenant:"))
async def select_tenant(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    tenant_id = int(query.data.rsplit(":", 1)[1])
    tenant = await db.get_tenant(tenant_id)
    if not tenant:
        return await query.answer("Topilmadi.", show_alert=True)

    await session.update(query.from_user.id, tenant_id=tenant_id)

    # Mavjud user?
    existing = await db.get_user(tenant_id, query.from_user.id)
    if existing and existing.get("status") == UserStatus.ACTIVE:
        # Customer edi → poster ham bo'ladi (BOTH)
        current_role = existing.get("user_role", UserRole.CUSTOMER)
        if current_role == UserRole.CUSTOMER:
            await db.update_user(tenant_id, query.from_user.id, user_role=UserRole.BOTH)
            new_role = UserRole.BOTH
        else:
            new_role = current_role
        if not existing.get("category_code"):
            # Kategoriya tanlash kerak
            await session.update(
                query.from_user.id,
                step="poster:awaiting_category",
                tenant_id=tenant_id,
                data={"role_target": new_role},
            )
            if query.message:
                await query.message.answer(
                    "🎯 <b>Qaysi sohada ishlaysiz?</b>\n\n"
                    "Sohani tanlang:",
                    reply_markup=user_kb.category_picker("poster:setup:category"),
                )
        else:
            if query.message:
                await query.message.answer(
                    f"✅ Siz allaqachon shu guruhda poster sifatida ro'yxatdansiz.\n\n"
                    "Bosh menyuga oʻtdik:",
                    reply_markup=user_kb.poster_main_menu(
                        rotation_active=bool(existing.get("rotation_active", 0))
                    ),
                )
        await query.answer()
        return

    # Yangi — kategoriya tanlash bilan boshlaymiz
    await session.update(
        query.from_user.id,
        step="poster:awaiting_category",
        tenant_id=tenant_id,
        data={"role_target": UserRole.POSTER},
    )
    if query.message:
        await query.message.answer(
            "🎯 <b>Qaysi sohada ishlaysiz?</b>\n\n"
            "Sohani tanlang:",
            reply_markup=user_kb.category_picker("poster:setup:category"),
        )
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# 2. Kategoriya tanlash
# ─────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("poster:setup:category:"))
async def select_category_setup(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    code = query.data.rsplit(":", 1)[1]
    if code == "back":
        return await query.answer()

    if not is_valid_category(code):
        return await query.answer("Notoʻgʻri kategoriya.", show_alert=True)

    # ── Tenant kategoriya cheklovi tekshiruvi ────────────────────────
    state = await session.get(query.from_user.id)
    tenant_id = state.tenant_id
    if tenant_id:
        allowed = await db.get_allowed_categories(tenant_id)
        if allowed and code not in allowed:
            return await query.answer(
                "🚫 Bu kategoriya guruh tomonidan ruxsat etilmagan.",
                show_alert=True,
            )

    state.data["category_code"] = code
    await session.set(query.from_user.id, state)

    if query.message:
        cat_label = get_category_label(code)
        await query.message.answer(
            f"✅ Soha: <b>{cat_label}</b>\n\n"
            "📝 Endi yengil ro'yxat:\n\n"
            "1️⃣ <b>To'liq ismingiz</b>:"
        )
    state.step = "poster:awaiting_name"
    await session.set(query.from_user.id, state)
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# 3. Ism + telefon + region
# ─────────────────────────────────────────────────────────────────────
async def _start_registration(
    message: Message, tenant_id: int, role_target: str
) -> None:
    if message.from_user is None:
        return
    await session.update(
        message.from_user.id,
        step="poster:awaiting_category",
        tenant_id=tenant_id,
        data={"role_target": role_target},
    )
    # Tenant kategoriya cheklovi
    allowed = await db.get_allowed_categories(tenant_id)
    await message.answer(
        "🎯 <b>Qaysi sohada ishlaysiz?</b>\n\n"
        "Sohani tanlang:",
        reply_markup=user_kb.category_picker(
            "poster:setup:category",
            allowed_codes=allowed or None,
        ),
    )


async def _in_poster_flow(message: Message) -> bool:
    """Filter: faqat poster flow state'ida ishlaydi."""
    if message.from_user is None:
        return False
    state = await session.get(message.from_user.id)
    return state.step.startswith("poster:")


@router.message(F.text, _in_poster_flow)
async def poster_text_router(message: Message) -> None:
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)
    text = (message.text or "").strip()

    # Faqat poster flow'da
    if not state.step.startswith("poster:"):
        return

    # 1) Ism
    if state.step == "poster:awaiting_name":
        ok, name, err = validate_name(text)
        if not ok:
            await message.answer(err)
            return
        state.data["full_name"] = name
        state.step = "poster:awaiting_phone"
        await session.set(message.from_user.id, state)
        await message.answer(
            f"✅ Ism: {fmt.esc(name)}\n\n"
            "2️⃣ <b>Telefon raqamingiz:</b>",
            reply_markup=request_contact(),
        )
        return

    # 2) Telefon
    if state.step == "poster:awaiting_phone":
        ok, phone, err = validate_phone(text)
        if not ok:
            await message.answer(err)
            return
        state.data["phone"] = phone
        state.step = "poster:awaiting_region"
        await session.set(message.from_user.id, state)
        await _ask_region(message)
        return

    # 3) Yangi e'lon matni
    if state.step == "poster:writing_post":
        await _handle_new_post_text(message, text)
        return

    # 4) Custom interval
    if state.step == "poster:awaiting_interval":
        ok, normalized, err = validate_interval(
            text, min_min=Rotation.MIN_INTERVAL_MIN, max_min=Rotation.MAX_INTERVAL_MIN
        )
        if not ok:
            await message.answer(err)
            return
        n = int(normalized)
        ctx = await resolve_role(message.from_user.id, tenant_id=state.tenant_id)
        await db.set_poster_rotation(state.tenant_id, message.from_user.id, active=True, interval_min=n)
        await audit_log.log_action(
            actor=ctx, action="set_own_interval", details={"interval_min": n}
        )
        await session.reset(message.from_user.id)
        await session.update(message.from_user.id, tenant_id=state.tenant_id)
        await message.answer(
            f"✅ Interval {n} daqiqaga oʻrnatildi va auto-post YOQILDI.",
            reply_markup=user_kb.poster_main_menu(rotation_active=True),
        )
        return

    # 5) E'lon matnini tahrirlash
    if state.step == "poster:editing_post":
        await _handle_edit_post_text(message, text)
        return


@router.message(F.contact)
async def receive_contact(message: Message) -> None:
    if message.from_user is None or message.contact is None:
        return
    state = await session.get(message.from_user.id)
    if state.step != "poster:awaiting_phone":
        return

    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone

    state.data["phone"] = phone
    state.step = "poster:awaiting_region"
    await session.set(message.from_user.id, state)
    await _ask_region(message)


async def _ask_region(message: Message) -> None:
    from keyboards.routes import REGIONS
    items = [(name, f"poster:region:{code}") for name, code in REGIONS]
    kb = inline_grid(
        items,
        columns=2,
        extra_rows=[[(Btn.CANCEL, "poster:cancel")]],
    )
    await message.answer(
        "3️⃣ <b>Qaysi viloyatda ishlaysiz?</b>\n\n"
        "Bu — mijozlar sizga yaqin xizmatlarni topish uchun:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("poster:region:"))
async def select_region(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return

    region_code = query.data.rsplit(":", 1)[1]
    state = await session.get(query.from_user.id)
    if state.step != "poster:awaiting_region":
        return await query.answer()

    state.data["region"] = region_code
    await session.set(query.from_user.id, state)

    if query.message:
        await _finalize_registration(query.message, query.from_user.id)
    await query.answer()


@router.callback_query(F.data == "poster:cancel")
async def cancel_registration(query: CallbackQuery) -> None:
    if query.from_user is None:
        return
    await session.reset(query.from_user.id)
    if query.message:
        await query.message.answer(
            "❌ Bekor qilindi.", reply_markup=user_kb.role_selection_menu()
        )
    await query.answer()


async def _finalize_registration(message: Message, user_id: int) -> None:
    """Registration yakunlash."""
    state = await session.get(user_id)
    tenant_id = state.tenant_id or 0
    if not tenant_id:
        await message.answer("Tenant aniqlanmadi. /start")
        return

    full_name = state.data.get("full_name", "")
    phone = state.data.get("phone", "")
    region = state.data.get("region", "")
    cat_code = state.data.get("category_code", "")
    role_target = state.data.get("role_target", UserRole.POSTER)

    existing = await db.get_user(tenant_id, user_id)
    if existing:
        existing_role = existing.get("user_role", UserRole.CUSTOMER)
        if existing_role == UserRole.CUSTOMER:
            new_role = UserRole.BOTH
        else:
            new_role = role_target
        await db.update_user(
            tenant_id, user_id,
            full_name=full_name or existing.get("full_name", ""),
            phone=phone or existing.get("phone", ""),
            region=region or existing.get("region", ""),
            category_code=cat_code,
            user_role=new_role,
        )
    else:
        await db.upsert_user(
            tenant_id=tenant_id,
            user_id=user_id,
            full_name=full_name,
            username="",
            phone=phone,
        )
        await db.update_user(
            tenant_id, user_id,
            user_role=role_target,
            category_code=cat_code,
            region=region,
        )

    settings = await db.get_settings(tenant_id)
    require_approval = bool(settings.get("require_approval", True))

    if not require_approval:
        await db.set_user_status(
            tenant_id, user_id, UserStatus.ACTIVE, approved_by=tenant_id
        )
        await session.reset(user_id)
        await session.update(user_id, tenant_id=tenant_id)
        await audit_log.log_action(
            actor_role="system", actor_id=0,
            tenant_id=tenant_id,
            action="poster_auto_approved",
            target_type="user", target_id=user_id,
        )
        await message.answer(
            f"✅ <b>Tabriklayman!</b>\n\n"
            f"📌 Soha: {get_category_label(cat_code)}\n"
            f"🌍 Viloyat: {fmt.esc(region)}\n\n"
            "Endi e'lon yozishingiz mumkin!",
            reply_markup=user_kb.poster_main_menu(rotation_active=False),
        )
        return

    # Manual approval
    from keyboards.tenant_kb import approve_user_inline
    from aiogram.exceptions import TelegramAPIError
    with contextlib.suppress(TelegramAPIError):
        from main import bot
        await bot.send_message(
            tenant_id,
            text=(
                f"🔔 <b>Yangi poster arizasi</b>\n\n"
                f"👤 <b>{fmt.esc(full_name)}</b>\n"
                f"🆔 <code>#{user_id}</code>\n"
                f"📱 {fmt.esc(phone)}\n"
                f"🌍 {fmt.esc(region)}\n"
                f"🎯 {get_category_label(cat_code)}"
            ),
            reply_markup=approve_user_inline(user_id),
        )

    await session.reset(user_id)
    await session.update(user_id, tenant_id=tenant_id)
    await message.answer(
        "✅ Maʼlumotlaringiz qabul qilindi.\n\n"
        "⏳ Guruh egasi tasdiqlashini kuting.",
        reply_markup=user_kb.pending_menu(),
    )


# ─────────────────────────────────────────────────────────────────────
# 4. NEW POST — erkin matn
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.NEW_POST)
async def start_new_post(message: Message) -> None:
    if message.from_user is None:
        return

    # Rate limiter — anti-spam (max 10 post/daqiqa per user)
    from core.rate_limiter import limiter, get_block_message
    if not limiter.is_allowed(message.from_user.id, "post"):
        msg = get_block_message(message.from_user.id, "post")
        if msg:
            await message.answer(msg)
        return
    state = await session.get(message.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        await message.answer("Avval guruh tanlang. /start")
        return

    ctx = await resolve_role(message.from_user.id, tenant_id=tenant_id)
    if not ctx.is_poster and not ctx.is_super_admin:
        await message.answer("🚫 Bu funksiya posterlarga moʻljallangan.")
        return

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
            "tenant_status:paused": "⏸ Bot muddati tufayli pause holatida.",
            "tenant_status:blocked": "🚫 Bot bloklangan.",
            "bot_off": "⛔ Bot guruh egasi tomonidan toʻxtatilgan.",
            "post_intake_off": "⛔ Yangi eʼlon qabuli vaqtincha toʻxtatilgan.",
        }.get(reason, "❌ Eʼlon qabul qilinmaydi.")
        await message.answer(msg)
        return

    state.step = "poster:writing_post"
    state.data["new_post"] = {"raw_text": "", "photos": []}
    await session.set(message.from_user.id, state)

    await message.answer(
        "📝 <b>Yangi e'lon</b>\n\n"
        "E'lon matnini yozib yuboring (ixtiyoriy ravishda rasm ham qoʻshib).\n\n"
        f"⚙️ Cheklov: max {Limits.MAX_POST_TEXT_LEN} belgi, "
        f"{Limits.MAX_PHOTOS_PER_POST} ta rasm.\n\n"
        "/cancel — bekor qilish"
    )


async def _handle_new_post_text(message: Message, text: str) -> None:
    """Yangi eʼlon matnini qabul qilish va tasdiqlash so'rash."""
    if message.from_user is None:
        return
    if len(text) > Limits.MAX_POST_TEXT_LEN:
        await message.answer(
            f"❌ Matn juda uzun (max {Limits.MAX_POST_TEXT_LEN} belgi)."
        )
        return

    state = await session.get(message.from_user.id)
    state.data["new_post"]["raw_text"] = text
    await session.set(message.from_user.id, state)

    user = await db.get_user(state.tenant_id, message.from_user.id)
    cat_code = (user or {}).get("category_code", "")
    cat_label = get_category_label(cat_code)

    preview = (
        f"📋 <b>EʼLON OLDIN KOʻRISH:</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{cat_label}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{fmt.esc(text)}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    await message.answer(preview)

    confirm_text, kb = build_confirmation(
        action_id="poster:publish",
        title="E'lonni joylashtirish",
        question="Yuqoridagi matn to'g'rimi?",
        details=[
            "📌 Eʼlon galaning oxiriga qo'shiladi",
            "📌 Auto-post yoqilgan bo'lsa — navbati kelganda chiqadi",
            f"📌 24 soatdan keyin avtomatik o'chadi",
        ],
    )
    await message.answer(confirm_text, reply_markup=kb)


@router.message(F.photo)
async def receive_photo(message: Message) -> None:
    """Yangi e'lon yozayotganda rasm qo'shish."""
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)
    if state.step != "poster:writing_post":
        return

    # Eng yaxshi sifatli rasmni olamiz (eng oxirgisi)
    if not message.photo:
        return
    photo_id = message.photo[-1].file_id

    photos = state.data.get("new_post", {}).get("photos", [])
    if len(photos) >= Limits.MAX_PHOTOS_PER_POST:
        await message.answer(f"❌ Max {Limits.MAX_PHOTOS_PER_POST} ta rasm.")
        return

    photos.append(photo_id)
    state.data["new_post"]["photos"] = photos
    await session.set(message.from_user.id, state)

    await message.answer(
        f"📷 Rasm qabul qilindi ({len(photos)}/{Limits.MAX_PHOTOS_PER_POST}). "
        "Yana yozing yoki rasm qo'shing."
    )


@router.callback_query(F.data == "confirm:yes:poster:publish")
async def confirm_publish(query: CallbackQuery) -> None:
    if query.from_user is None:
        return
    state = await session.get(query.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        return await query.answer("Sessiya tugadi.", show_alert=True)

    new_post = state.data.get("new_post", {})
    raw_text = new_post.get("raw_text", "")
    photos = new_post.get("photos", [])

    if not raw_text:
        return await query.answer("Matn boʻsh.", show_alert=True)

    user = await db.get_user(tenant_id, query.from_user.id)
    if not user:
        return

    # Birinchi aktiv kanal (MVP — keyin tanlash mumkin)
    channels = await db.list_channels(tenant_id, only_active=True)
    if not channels:
        return await query.answer(
            "❌ Tenant kanal ulamagan.", show_alert=True
        )
    channel_id = channels[0]["channel_id"]

    # Tarif limit
    tenant = await db.get_tenant(tenant_id)
    tariff = (tenant or {}).get("tariff", "trial")
    max_active = int(get_tariff_limit(tariff, "max_active_posts_per_user", 5) or 5)

    settings = await db.get_settings(tenant_id)
    lifetime = int(settings.get("post_lifetime_hours", Rotation.DEFAULT_LIFETIME_HOURS))
    cat_code = user.get("category_code", "")

    # Rendered text — qisqa karkas (publisher to'liqini qiladi)
    rendered = f"{get_category_label(cat_code)}\n\n{raw_text}"

    ok, status, post_id = await db.create_announcement(
        tenant_id=tenant_id,
        user_id=query.from_user.id,
        channel_id=channel_id,
        raw_text=raw_text,
        rendered_text=rendered,
        category_code=cat_code,
        photos=photos,
        lifetime_hours=lifetime,
        max_active_per_user=max_active,
    )
    if not ok:
        if status == "limit":
            return await query.answer(
                f"⛔ Sizda allaqachon {max_active} ta aktiv eʼlon bor.",
                show_alert=True,
            )
        return await query.answer(f"❌ Xato: {status}", show_alert=True)

    # Status: agar rotation ON va birinchi e'lon — DARHOL ACTIVE,
    # boshqa holatlarda QUEUED (scheduler chiqaradi).
    rotation_active = bool(user.get("rotation_active", 0))
    if rotation_active or Rotation.FIRST_POST_IMMEDIATE:
        await db.update_announcement(post_id, tenant_id, status=PostStatus.ACTIVE)

    await audit_log.log_action(
        actor=await resolve_role(query.from_user.id, tenant_id=tenant_id),
        action="post_created",
        target_type="announcement",
        target_id=post_id,
        details={"category": cat_code, "channel_id": channel_id, "photos": len(photos)},
    )

    await bus.emit(
        Events.POST_CREATED,
        {
            "post_id": post_id,
            "tenant_id": tenant_id,
            "user_id": query.from_user.id,
            "channel_id": channel_id,
            "category": cat_code,
        },
    )

    await session.reset(query.from_user.id)
    await session.update(query.from_user.id, tenant_id=tenant_id)

    if query.message:
        await query.message.answer(
            f"✅ E'lon yaratildi!\n\n"
            f"📋 Post ID: <code>#{post_id}</code>\n"
            f"📺 Publisher tomonidan kanalga yuboriladi.\n\n"
            f"💡 Auto-post yoqilgan bo'lsa, e'loningiz galaga qo'shildi.",
            reply_markup=user_kb.poster_main_menu(rotation_active=rotation_active),
        )
    await query.answer("✅ Yaratildi", show_alert=True)


@router.callback_query(F.data == "confirm:no:poster:publish")
async def cancel_publish(query: CallbackQuery) -> None:
    if query.from_user is None:
        return
    await session.reset(query.from_user.id)
    if query.message:
        await query.message.answer("❌ Eʼlon bekor qilindi.")
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# 5. MY POSTS
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

    posts = await db.get_user_post_queue(tenant_id, message.from_user.id)
    if not posts:
        await message.answer(
            "📭 Hali eʼloningiz yo'q.\n\nYangi e'lon: ➕ Yangi eʼlon"
        )
        return

    user = await db.get_user(tenant_id, message.from_user.id)
    rotation_active = bool((user or {}).get("rotation_active", 0))
    interval_min = int((user or {}).get("rotation_interval_min", 10))

    lines = [
        f"📋 <b>Mening eʼlonlarim ({len(posts)} ta)</b>",
        f"🔄 Auto-post: {'🟢 ON' if rotation_active else '🔴 OFF'} | ⏱ {interval_min} daq",
        "",
    ]
    for p in posts[:15]:
        emoji = {
            "active": "🟢",
            "draft": "📝",
            "queued": "⏳",
            "paused": "⏸",
        }.get(p.get("status", ""), "❓")
        text_preview = (p.get("raw_text") or "")[:60].replace("\n", " ")
        lines.append(
            f"{p.get('queue_order', 0)}. {emoji} <code>#{p['id']}</code>: {fmt.esc(text_preview)}..."
        )

    items = [
        (
            f"#{p['id']}: {(p.get('raw_text') or '')[:25]}...",
            f"poster:post:show:{p['id']}",
        )
        for p in posts[:10]
    ]
    kb = inline_grid(items, columns=1)
    await message.answer("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data.startswith("poster:post:show:"))
async def show_post_detail(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    post_id = int(query.data.rsplit(":", 1)[1])
    state = await session.get(query.from_user.id)
    post = await db.get_announcement(post_id, tenant_id=state.tenant_id)
    if not post:
        return await query.answer("Topilmadi.", show_alert=True)
    if post.get("user_id") != query.from_user.id:
        return await query.answer("Bu sizning eʼloningiz emas.", show_alert=True)

    text = (
        f"<b>Eʼlon #{post['id']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{get_category_label(post.get('category_code', ''))}\n\n"
        f"{fmt.esc(post.get('raw_text') or '')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 Holat: {post.get('status', '?')}\n"
        f"📋 Gala: #{post.get('queue_order', '?')}\n"
        f"👁 Ko'rishlar: {post.get('views_count', 0)}\n"
        f"🔄 Aylanishlar: {post.get('rotation_count', 0)}\n"
        f"📅 Yaratilgan: {fmt.format_relative(post.get('created_at'))}"
    )
    if query.message:
        await query.message.answer(text, reply_markup=user_kb.post_actions(post_id))
    await query.answer()


@router.callback_query(F.data.startswith("poster:post:delete:"))
async def delete_post(query: CallbackQuery) -> None:
    """E'lonni o'chirish — TASDIQLASH so'raymiz."""
    if query.from_user is None or not query.data:
        return
    post_id = int(query.data.rsplit(":", 1)[1])
    state = await session.get(query.from_user.id)
    tenant_id = state.tenant_id

    post = await db.get_announcement(post_id, tenant_id=tenant_id)
    if not post or post.get("user_id") != query.from_user.id:
        return await query.answer("Topilmadi.", show_alert=True)

    text, kb = build_confirmation(
        action_id=f"poster:post_delete:{post_id}",
        title="Eʼlonni o'chirish",
        question=f"E'lon <code>#{post_id}</code> ni o'chirishni tasdiqlaysizmi?",
        warning="⚠️ Bu amalni ortga qaytarib bo'lmaydi.\nE'lon kanaldan ham o'chiriladi.",
    )
    if query.message:
        await query.message.answer(text, reply_markup=kb)
    await query.answer()


@router.callback_query(F.data.startswith("confirm:yes:poster:post_delete:"))
async def delete_post_confirm(query: CallbackQuery) -> None:
    """E'lonni o'chirish — TASDIQLANGAN."""
    if query.from_user is None or not query.data:
        return
    post_id = int(query.data.rsplit(":", 1)[1])
    state = await session.get(query.from_user.id)
    tenant_id = state.tenant_id

    post = await db.get_announcement(post_id, tenant_id=tenant_id)
    if not post or post.get("user_id") != query.from_user.id:
        return await query.answer("Topilmadi.", show_alert=True)

    # Kanaldan o'chirish (publisher orqali)
    with contextlib.suppress(ImportError, AttributeError):
        from services.publisher import remove_post_from_channel
        await remove_post_from_channel(post_id, tenant_id)

    # DB: status=deleted
    await db.update_announcement(post_id, tenant_id, status=PostStatus.DELETED)
    await db.reorder_user_queue(tenant_id, query.from_user.id)

    await audit_log.log_action(
        actor=await resolve_role(query.from_user.id, tenant_id=tenant_id),
        action="post_deleted",
        target_type="announcement",
        target_id=post_id,
    )
    await query.answer("🗑 O'chirildi", show_alert=True)
    if query.message:
        from aiogram.exceptions import TelegramAPIError
        with contextlib.suppress(TelegramAPIError):
            await query.message.delete()


@router.callback_query(F.data.startswith("confirm:no:poster:post_delete:"))
async def delete_post_cancel(query: CallbackQuery) -> None:
    if query.message:
        await query.message.answer("✅ Bekor qilindi.")
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# 6. START / STOP — auto-post boshqaruv
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.POSTER_START)
async def start_rotation(message: Message) -> None:
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        await message.answer("Avval guruh tanlang. /start")
        return

    user = await db.get_user(tenant_id, message.from_user.id)
    if not user:
        return

    posts = await db.get_user_post_queue(tenant_id, message.from_user.id)
    if not posts:
        await message.answer(
            "❌ Galangizda eʼlon yo'q. Avval e'lon yarating: ➕ Yangi eʼlon"
        )
        return

    interval = int(user.get("rotation_interval_min", 10))
    await db.set_poster_rotation(tenant_id, message.from_user.id, active=True)

    await audit_log.log_action(
        actor=await resolve_role(message.from_user.id, tenant_id=tenant_id),
        action="rotation_started",
        details={"interval_min": interval, "posts": len(posts)},
    )

    await message.answer(
        f"✅ <b>Auto-post YOQILDI!</b>\n\n"
        f"⏱ Interval: {interval} daqiqa\n"
        f"📋 Galada: {len(posts)} ta eʼlon\n\n"
        f"🚀 Eʼlonlaringiz kanalga ketma-ket chiqadi.",
        reply_markup=user_kb.poster_main_menu(rotation_active=True),
    )


@router.message(F.text == Btn.POSTER_STOP)
async def stop_rotation(message: Message) -> None:
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        return

    await db.set_poster_rotation(tenant_id, message.from_user.id, active=False)

    await audit_log.log_action(
        actor=await resolve_role(message.from_user.id, tenant_id=tenant_id),
        action="rotation_stopped",
    )
    await message.answer(
        "⛔ <b>Auto-post TOʻXTATILDI.</b>\n\n"
        "📌 Mavjud eʼlonlar kanalda qoladi (24 soatgacha)\n"
        "📌 Lekin yangilanish toʻxtaydi\n\n"
        "Yana yoqish uchun: ▶️ Auto-post YOQISH",
        reply_markup=user_kb.poster_main_menu(rotation_active=False),
    )


# ─────────────────────────────────────────────────────────────────────
# 7. INTERVAL
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.POSTER_INTERVAL)
async def show_interval(message: Message) -> None:
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        return

    user = await db.get_user(tenant_id, message.from_user.id)
    interval = int((user or {}).get("rotation_interval_min", 10))

    await message.answer(
        f"⏱ <b>Aylanish intervali</b>\n\n"
        f"Hozir: <b>{interval} daqiqa</b>\n\n"
        f"⚠️ Min: {Rotation.MIN_INTERVAL_MIN} daqiqa (qoida)\n\n"
        "Yangi qiymatni tanlang:",
        reply_markup=user_kb.interval_picker("poster:interval"),
    )


@router.callback_query(F.data.startswith("poster:interval:set:"))
async def set_interval(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    state = await session.get(query.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        return

    try:
        n = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        return
    if n < Rotation.MIN_INTERVAL_MIN:
        return await query.answer(
            f"⛔ Min {Rotation.MIN_INTERVAL_MIN} daqiqa.", show_alert=True
        )

    await db.set_poster_rotation(tenant_id, query.from_user.id, active=True, interval_min=n)
    await audit_log.log_action(
        actor=await resolve_role(query.from_user.id, tenant_id=tenant_id),
        action="set_own_interval",
        details={"interval_min": n},
    )
    await query.answer(f"✅ {n} daqiqa o'rnatildi (auto-post YOQILDI)", show_alert=True)


@router.callback_query(F.data == "poster:interval:custom")
async def ask_custom_interval(query: CallbackQuery) -> None:
    if query.from_user is None:
        return
    await session.update(query.from_user.id, step="poster:awaiting_interval")
    if query.message:
        await query.message.answer(
            f"⏱ Daqiqalarda kiriting (min {Rotation.MIN_INTERVAL_MIN}, max {Rotation.MAX_INTERVAL_MIN}):"
        )
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# 8. CHANGE CATEGORY
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.CHANGE_CATEGORY)
async def show_change_category(message: Message) -> None:
    if message.from_user is None:
        return
    await message.answer(
        "🔄 <b>Soha o'zgartirish</b>\n\n"
        "Yangi sohani tanlang:",
        reply_markup=user_kb.category_picker("poster:change_category"),
    )


@router.callback_query(F.data.startswith("poster:change_category:"))
async def change_category(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    code = query.data.rsplit(":", 1)[1]
    if code == "back":
        return await query.answer()
    if not is_valid_category(code):
        return await query.answer("Notoʻgʻri kategoriya.", show_alert=True)

    state = await session.get(query.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        return

    await db.update_user(tenant_id, query.from_user.id, category_code=code)
    await audit_log.log_action(
        actor=await resolve_role(query.from_user.id, tenant_id=tenant_id),
        action="set_own_category",
        details={"category_code": code},
    )
    await query.answer(f"✅ Soha: {get_category_label(code)}", show_alert=True)


# ─────────────────────────────────────────────────────────────────────
# 9. STATISTIKA
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.POSTER_STATS)
async def show_stats(message: Message) -> None:
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        return

    user = await db.get_user(tenant_id, message.from_user.id)
    posts = await db.list_user_announcements(tenant_id, message.from_user.id)
    total_views = sum(int(p.get("views_count", 0)) for p in posts)
    total_rotations = sum(int(p.get("rotation_count", 0)) for p in posts)

    text = fmt.format_stats_card(
        "Mening statistikam",
        {
            "Jami eʼlonlar": len(posts),
            "Aktiv": sum(1 for p in posts if p.get("status") == "active"),
            "Ko'rishlar": total_views,
            "Aylanishlar": total_rotations,
            "Reyting": f"{(user or {}).get('rating', 5.0):.1f} ⭐",
            "Ogohlantirishlar": (user or {}).get("warnings_count", 0),
        },
    )
    await message.answer(text)


# ─────────────────────────────────────────────────────────────────────
# 10. PROFIL & LOGOUT — UMUMIY HANDLER'GA KO'CHIRILGAN
# ─────────────────────────────────────────────────────────────────────
# `Btn.MY_PROFILE` va `Btn.LOGOUT` tugmalari uchun handler'lar endi
# `panels/common_handlers.py` faylida (har router'da duplicate
# qilmaslik uchun). Bu yerda olib tashlandi.



# ─────────────────────────────────────────────────────────────────────
# 11. POST:VIEW va POST:EDIT (KB tugmalari uchun)
# ─────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("poster:post:view:"))
async def view_post_alias(query: CallbackQuery) -> None:
    """post:view callback — show_post_detail bilan bir xil."""
    await show_post_detail(query)


@router.callback_query(F.data.startswith("poster:post:edit:"))
async def start_edit_post(query: CallbackQuery) -> None:
    """E'lon matnini tahrirlashni boshlash."""
    if query.from_user is None or not query.data:
        return
    try:
        post_id = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        return await query.answer("Notoʻgʻri ID.", show_alert=True)

    state = await session.get(query.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        return await query.answer("Sessiya tugadi.", show_alert=True)

    post = await db.get_announcement(post_id, tenant_id=tenant_id)
    if not post or post.get("user_id") != query.from_user.id:
        return await query.answer("Bu sizning eʼloningiz emas.", show_alert=True)

    if post.get("status") in (PostStatus.EXPIRED, PostStatus.DELETED):
        return await query.answer(
            "Bu eʼlon o'chirilgan yoki muddati tugagan.", show_alert=True
        )

    state.step = "poster:editing_post"
    state.data["edit_post_id"] = post_id
    await session.set(query.from_user.id, state)

    current_text = post.get("raw_text") or ""
    if query.message:
        await query.message.answer(
            f"✏️ <b>E'lon #{post_id} tahrirlash</b>\n\n"
            f"<b>Hozirgi matn:</b>\n"
            f"<code>{fmt.esc(current_text)}</code>\n\n"
            f"Yangi matnni yozing yoki /cancel bilan bekor qiling:"
        )
    await query.answer()


async def _handle_edit_post_text(message: Message, text: str) -> None:
    """E'lon matnini tahrirlash kiritildi (state=poster:editing_post)."""
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)

    if text in ("/cancel", "❌ Bekor qilish"):
        await session.reset(message.from_user.id)
        await session.update(message.from_user.id, tenant_id=state.tenant_id)
        await message.answer(
            "❌ Bekor qilindi.",
            reply_markup=user_kb.poster_main_menu(rotation_active=False),
        )
        return

    if len(text) > Limits.MAX_POST_TEXT_LEN:
        await message.answer(
            f"❌ Matn juda uzun (max {Limits.MAX_POST_TEXT_LEN} belgi)."
        )
        return
    if len(text) < 5:
        await message.answer("❌ Matn juda qisqa (min 5 belgi).")
        return

    post_id = int(state.data.get("edit_post_id", 0))
    tenant_id = state.tenant_id
    if not post_id or not tenant_id:
        await session.reset(message.from_user.id)
        return

    post = await db.get_announcement(post_id, tenant_id=tenant_id)
    if not post or post.get("user_id") != message.from_user.id:
        await session.reset(message.from_user.id)
        await message.answer("❌ E'lon topilmadi yoki sizniki emas.")
        return

    cat_code = post.get("category_code", "")
    rendered = f"{get_category_label(cat_code)}\n\n{text}"

    await db.update_announcement(
        post_id, tenant_id,
        raw_text=text,
        rendered_text=rendered,
    )

    # Kanaldagi xabarni ham yangilash (publisher.refresh_post_in_channel)
    with contextlib.suppress(Exception):
        from services.publisher import refresh_post_in_channel
        await refresh_post_in_channel(post_id, tenant_id)

    await audit_log.log_action(
        actor=await resolve_role(message.from_user.id, tenant_id=tenant_id),
        action="post_edited",
        target_type="announcement",
        target_id=post_id,
    )

    await session.reset(message.from_user.id)
    await session.update(message.from_user.id, tenant_id=tenant_id)

    user = await db.get_user(tenant_id, message.from_user.id)
    rotation_active = bool((user or {}).get("rotation_active", 0))

    await message.answer(
        f"✅ E'lon #{post_id} yangilandi!\n\n"
        f"📌 Yangi matn saqlandi.",
        reply_markup=user_kb.poster_main_menu(rotation_active=rotation_active),
    )



# ─────────────────────────────────────────────────────────────────────
# 12. LOGOUT — UMUMIY HANDLER'GA KO'CHIRILGAN
# ─────────────────────────────────────────────────────────────────────
# `Btn.LOGOUT` tugmasi uchun handler endi `panels/common_handlers.py`
# faylida — barcha rollar uchun yagona joyda.
