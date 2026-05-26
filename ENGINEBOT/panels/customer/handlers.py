"""
panels/customer/handlers.py — mijoz (customer) paneli.

ASOSIY OQIM:
────────────
1. "Men mijozman" tugmasi → tenant tanlash (yoki avto)
2. Yengil ro'yxat (ism, telefon, viloyat)
3. Tenant tasdiqlaydi (yoki avto-tasdiq) → menyu ochiladi
4. Mijoz qila olishi:
   - 🔍 Qidirish (kategoriya bo'yicha)
   - 📰 Yangi e'lonlar lentasi
   - 👤 Profil
   - 🚪 Chiqish
"""

from __future__ import annotations

import contextlib

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from config import Role, UserRole, UserStatus
from core import audit_log, database as db, notifier
from core.categories import all_categories, get_category_label, is_valid_category
from core.event_bus import Events, bus
from core.permissions import RoleContext, resolve_role
from keyboards import user_kb
from keyboards.common_kb import Btn, inline_grid, request_contact
from utils import formatters as fmt
from utils import logger as log_mod
from utils.confirmation import confirm_logout
from utils.session_state import session
from utils.validators import validate_name, validate_phone

logger = log_mod.get_logger("panels.customer")
router = Router(name="customer")


# ─────────────────────────────────────────────────────────────────────
# 1. "Men mijozman" tugmasi — boshlanish
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.I_AM_CUSTOMER)
async def i_am_customer(message: Message) -> None:
    if message.from_user is None:
        return

    uid = message.from_user.id
    state = await session.get(uid)
    tenant_id = state.tenant_id

    # Agar session'da tenant bor — bevosita ro'yxatga o'tamiz
    if tenant_id:
        await _start_registration(message, tenant_id, role_target=UserRole.CUSTOMER)
        return

    # Aks holda, mavjud aktiv tenantlar ro'yxatini ko'rsatamiz
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
            f"customer:select_tenant:{t['tenant_id']}",
        )
        for t in tenants
    ]
    kb = inline_grid(items, columns=1)
    await message.answer(
        "🏢 <b>Qaysi guruh xizmatlaridan foydalanmoqchisiz?</b>\n\n"
        "Quyidagi roʻyxatdan tanlang:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("customer:select_tenant:"))
async def select_tenant(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return
    tenant_id = int(query.data.rsplit(":", 1)[1])

    tenant = await db.get_tenant(tenant_id)
    if not tenant:
        await query.answer("Topilmadi.", show_alert=True)
        return

    await session.update(query.from_user.id, tenant_id=tenant_id)

    # Foydalanuvchi shu tenantda allaqachon mijoz bo'lganmi?
    existing = await db.get_user(tenant_id, query.from_user.id)
    if existing and existing.get("status") == UserStatus.ACTIVE:
        # Sub-rolni yangilash: agar poster edi → both, agar yo'q edi → customer
        current_role = existing.get("user_role", UserRole.CUSTOMER)
        new_role = (
            UserRole.BOTH
            if current_role in (UserRole.POSTER, UserRole.BOTH)
            else UserRole.CUSTOMER
        )
        if new_role != current_role:
            await db.update_user(tenant_id, query.from_user.id, user_role=new_role)
        if query.message:
            await query.message.answer(
                f"✅ <b>{fmt.esc(tenant.get('name', ''))}</b> guruhiga ulandingiz!\n\n"
                "Endi qidirishingiz mumkin:",
                reply_markup=user_kb.customer_main_menu()
                if new_role == UserRole.CUSTOMER
                else user_kb.both_main_menu(),
            )
        await query.answer()
        return

    if query.message:
        await _start_registration(
            query.message,
            tenant_id,
            role_target=UserRole.CUSTOMER,
            from_user_id=query.from_user.id,
        )
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# 2. Yengil ro'yxat — name → phone → region
# ─────────────────────────────────────────────────────────────────────
async def _start_registration(
    message: Message,
    tenant_id: int,
    role_target: str,
    from_user_id: int | None = None,
) -> None:
    uid = from_user_id if from_user_id is not None else (
        message.from_user.id if message.from_user else 0
    )
    if not uid:
        return
    await session.update(
        uid,
        step="customer:awaiting_name",
        tenant_id=tenant_id,
        data={"role_target": role_target},
    )
    await message.answer(
        "📝 <b>Yengil ro'yxat</b>\n\n"
        "Mijoz sifatida qidirish uchun bir necha ma'lumot kerak.\n\n"
        "1️⃣ <b>Ismingizni</b> yozing (masalan: Akmal Karimov):"
    )


# Matn handlerlari (state'ga qarab)
async def _in_customer_flow(message: Message) -> bool:
    """Filter: faqat customer flow state'ida ishlaydi."""
    if message.from_user is None:
        return False
    state = await session.get(message.from_user.id)
    return state.step.startswith("customer:")


@router.message(F.text, _in_customer_flow)
async def customer_text_router(message: Message) -> None:
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)
    text = (message.text or "").strip()

    # Agar customer flow'da emas — boshqa handlerga o'tkazamiz (return)
    if not state.step.startswith("customer:"):
        return

    if state.step == "customer:awaiting_name":
        ok, name, err = validate_name(text)
        if not ok:
            await message.answer(err)
            return
        state.data["full_name"] = name
        state.step = "customer:awaiting_phone"
        await session.set(message.from_user.id, state)
        await message.answer(
            f"✅ Ism: {fmt.esc(name)}\n\n"
            "2️⃣ <b>Telefon raqamingiz:</b>\n"
            "(Tugma orqali yoki +998XXXXXXXXX formatida)",
            reply_markup=request_contact(),
        )
        return

    if state.step == "customer:awaiting_phone":
        ok, phone, err = validate_phone(text)
        if not ok:
            await message.answer(err)
            return
        state.data["phone"] = phone
        state.step = "customer:awaiting_region"
        await session.set(message.from_user.id, state)
        await _ask_region(message)
        return


# Telefon contact button orqali kelishi
@router.message(F.contact)
async def receive_contact(message: Message) -> None:
    if message.from_user is None or message.contact is None:
        return
    state = await session.get(message.from_user.id)
    if state.step != "customer:awaiting_phone":
        return

    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone

    state.data["phone"] = phone
    state.step = "customer:awaiting_region"
    await session.set(message.from_user.id, state)
    await _ask_region(message)


async def _ask_region(message: Message) -> None:
    """Viloyat tanlash."""
    from keyboards.routes import REGIONS

    items = [(name, f"customer:region:{code}") for name, code in REGIONS]
    kb = inline_grid(
        items,
        columns=2,
        extra_rows=[[(Btn.CANCEL, "customer:cancel")]],
    )
    await message.answer(
        "3️⃣ <b>Qaysi viloyatdasiz?</b>\n\n"
        "Bu — sizga yaqin xizmatlarni topish uchun kerak.",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("customer:region:"))
async def select_region(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return

    region_code = query.data.rsplit(":", 1)[1]
    state = await session.get(query.from_user.id)
    if state.step != "customer:awaiting_region":
        await query.answer("Sessiya muddati tugadi. /start", show_alert=True)
        return

    state.data["region"] = region_code
    await session.set(query.from_user.id, state)

    if query.message:
        await _finalize_registration(query.message, query.from_user.id)
    await query.answer()


@router.callback_query(F.data == "customer:cancel")
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
    """Registration yakunlash — DB ga yozish, sub-rolni belgilash."""
    state = await session.get(user_id)
    tenant_id = state.tenant_id or 0
    if not tenant_id:
        await message.answer("Tenant aniqlanmadi. /start")
        return

    full_name = state.data.get("full_name", "")
    phone = state.data.get("phone", "")
    region = state.data.get("region", "")
    role_target = state.data.get("role_target", UserRole.CUSTOMER)

    # Mavjud user'ni tekshiramiz (ehtimol poster edi)
    existing = await db.get_user(tenant_id, user_id)
    if existing:
        # Mavjud — sub-rolni o'zgartirish
        existing_role = existing.get("user_role", UserRole.CUSTOMER)
        if existing_role == UserRole.POSTER and role_target == UserRole.CUSTOMER:
            new_role = UserRole.BOTH
        else:
            new_role = role_target
        await db.update_user(
            tenant_id, user_id,
            full_name=full_name or existing.get("full_name", ""),
            phone=phone or existing.get("phone", ""),
            region=region or existing.get("region", ""),
            user_role=new_role,
        )
        user = await db.get_user(tenant_id, user_id)
    else:
        # Yangi user
        user = await db.upsert_user(
            tenant_id=tenant_id,
            user_id=user_id,
            full_name=full_name,
            username="",
            phone=phone,
        )
        await db.update_user(
            tenant_id, user_id,
            user_role=role_target,
            region=region,
        )

    # Tenant settings: auto-tasdiq?
    settings = await db.get_settings(tenant_id)
    require_approval = bool(settings.get("require_approval", True))

    if not require_approval:
        # Avtomatik aktivlashtirish
        await db.set_user_status(
            tenant_id, user_id, UserStatus.ACTIVE, approved_by=tenant_id
        )
        await session.reset(user_id)
        await session.update(user_id, tenant_id=tenant_id)
        await audit_log.log_action(
            actor_role="system", actor_id=0,
            tenant_id=tenant_id,
            action="customer_auto_approved",
            target_type="user", target_id=user_id,
        )
        await message.answer(
            f"✅ <b>Tabriklayman!</b>\n\n"
            f"📌 Roli: 🔍 Mijoz\n"
            f"🌍 Viloyat: {fmt.esc(region)}\n\n"
            "Endi qidirishni boshlang!",
            reply_markup=user_kb.customer_main_menu(),
        )
        return

    # Manual approval — tenantga xabar
    from keyboards.tenant_kb import approve_user_inline
    from aiogram.exceptions import TelegramAPIError
    with contextlib.suppress(TelegramAPIError):
        from main import bot
        await bot.send_message(
            tenant_id,
            text=(
                f"🔔 <b>Yangi mijoz arizasi</b>\n\n"
                f"👤 <b>{fmt.esc(full_name)}</b>\n"
                f"🆔 <code>#{user_id}</code>\n"
                f"📱 {fmt.esc(phone)}\n"
                f"🌍 {fmt.esc(region)}\n"
                f"📌 Rol: 🔍 Mijoz"
            ),
            reply_markup=approve_user_inline(user_id),
        )

    await session.reset(user_id)
    await session.update(user_id, tenant_id=tenant_id)
    await message.answer(
        "✅ Maʼlumotlaringiz qabul qilindi.\n\n"
        "⏳ Guruh egasi tasdiqlashini kuting. "
        "Tasdiqlanganidan soʻng menyu ochiladi.",
        reply_markup=user_kb.pending_menu(),
    )


# ─────────────────────────────────────────────────────────────────────
# 3. SEARCH — kategoriya tanlash
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.SEARCH)
async def show_search_menu(message: Message) -> None:
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        await message.answer("Avval guruh tanlang. /start")
        return
    ctx = await resolve_role(message.from_user.id, tenant_id=tenant_id)
    if not ctx.is_customer and not ctx.is_super_admin:
        await message.answer("🚫 Bu funksiya faqat mijozlar uchun.")
        return

    # Tenant kategoriya cheklovi
    allowed = await db.get_allowed_categories(tenant_id)
    await message.answer(
        "🔍 <b>Qidirish</b>\n\n"
        "Qaysi kategoriyada qidirayapsiz?",
        reply_markup=user_kb.customer_search_categories(allowed_codes=allowed or None),
    )


@router.callback_query(F.data.startswith("customer:search:category:"))
async def search_by_category(query: CallbackQuery) -> None:
    if query.from_user is None or not query.data:
        return

    # Rate limiter — qidiruv abuse'ga qarshi
    from core.rate_limiter import limiter, get_block_message
    if not limiter.is_allowed(query.from_user.id, "command"):
        msg = get_block_message(query.from_user.id, "command")
        return await query.answer(msg or "⏳ Juda koʻp soʻrov.", show_alert=True)
    state = await session.get(query.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        return await query.answer("Tenant tanlanmagan.", show_alert=True)

    code = query.data.rsplit(":", 1)[1]
    cat_filter = None if code == "all" else code

    posts = await db.search_announcements(
        tenant_id=tenant_id, category_code=cat_filter, limit=15
    )

    if not posts:
        text = (
            f"📭 <b>{get_category_label(cat_filter) if cat_filter else 'Hammasi'}</b> — "
            "hozircha eʼlonlar yo'q."
        )
        if query.message:
            await query.message.answer(text)
        await query.answer()
        return

    if query.message:
        cat_label = get_category_label(cat_filter) if cat_filter else "🔍 Hammasidan"
        await query.message.answer(
            f"🔍 <b>{cat_label}</b> — {len(posts)} ta natija topildi:\n"
        )
        for post in posts:
            await _send_post_card(query.message, post)
    await query.answer()


# ─────────────────────────────────────────────────────────────────────
# 4. BROWSE FEED — yangi e'lonlar lentasi
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.BROWSE_FEED)
async def show_feed(message: Message) -> None:
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        await message.answer("Avval guruh tanlang. /start")
        return

    posts = await db.get_recent_announcements(tenant_id, limit=10)
    if not posts:
        await message.answer(
            "📭 Hozircha yangi eʼlonlar yo'q.\n\nKeyinroq qaytib keling."
        )
        return

    await message.answer(
        f"📰 <b>Eng so'nggi e'lonlar ({len(posts)} ta)</b>"
    )
    for post in posts:
        await _send_post_card(message, post)


async def _send_post_card(message: Message, post: dict) -> None:
    """Bitta e'lon kartochkasini chiqarish (mijoz uchun)."""
    cat_label = get_category_label(post.get("category_code", ""))
    raw_text = post.get("raw_text") or post.get("rendered_text") or ""
    user_id = post.get("user_id")
    tenant_id = post.get("tenant_id")
    poster = await db.get_user(tenant_id, user_id) if (user_id and tenant_id) else None

    poster_name = (poster or {}).get("full_name", "Nomaʼlum")
    poster_phone = (poster or {}).get("phone", "")

    lines = [
        f"{cat_label}",
        "━━━━━━━━━━━━━━━━━━",
        fmt.esc(raw_text),
        "━━━━━━━━━━━━━━━━━━",
        f"👤 {fmt.esc(poster_name)}",
    ]
    if poster_phone:
        lines.append(f"📞 <code>{fmt.esc(poster_phone)}</code>")

    text = "\n".join(lines)
    kb = user_kb.post_view_actions(post["id"], poster_phone)

    # Rasmlar bormi?
    photos = post.get("photos") or []
    if isinstance(photos, str):
        import json
        with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
            photos = json.loads(photos)

    if photos and isinstance(photos, list) and photos:
        from aiogram.exceptions import TelegramAPIError
        with contextlib.suppress(TelegramAPIError):
            await message.answer_photo(
                photo=photos[0], caption=text, reply_markup=kb
            )
            return
    await message.answer(text, reply_markup=kb)


# ─────────────────────────────────────────────────────────────────────
# 5. Profil
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
    if user.get("region"):
        text += f"\n🌍 Viloyat: {fmt.esc(user['region'])}"
    await message.answer(text)


# ─────────────────────────────────────────────────────────────────────
# 6. Logout
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text == Btn.LOGOUT)
async def cmd_logout(message: Message) -> None:
    if message.from_user is None:
        return
    text, kb = confirm_logout(message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("confirm:yes:logout:"))
async def confirm_logout_yes(query: CallbackQuery) -> None:
    if query.from_user is None:
        return
    await session.remove(query.from_user.id)
    await audit_log.log_action(
        actor_role="user", actor_id=query.from_user.id,
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
    if query.message:
        await query.message.answer("✅ Bekor qilindi.")
    await query.answer()



# ═════════════════════════════════════════════════════════════════════
# 7. BOOKMARK (saqlash/olib tashlash) — toggle
# ═════════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("customer:bookmark:"))
async def toggle_bookmark(query: CallbackQuery) -> None:
    """E'lonni saqlash yoki saqlangandan olib tashlash (toggle)."""
    if query.from_user is None or not query.data:
        return

    state = await session.get(query.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        return await query.answer("Tenant tanlanmagan.", show_alert=True)

    try:
        post_id = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        return await query.answer("Notoʻgʻri ID.", show_alert=True)

    # E'lon mavjudligini tekshirish (tenant izolyatsiyasi bilan)
    post = await db.get_announcement(post_id, tenant_id=tenant_id)
    if not post:
        return await query.answer("E'lon topilmadi.", show_alert=True)

    # Toggle
    is_saved = await db.is_bookmarked(tenant_id, query.from_user.id, post_id)
    if is_saved:
        await db.remove_bookmark(tenant_id, query.from_user.id, post_id)
        msg = "🗑 Saqlanganlardan olib tashlandi"
    else:
        ok = await db.add_bookmark(tenant_id, query.from_user.id, post_id)
        msg = "⭐ Saqlandi!" if ok else "Allaqachon saqlangan"

    await query.answer(msg, show_alert=True)


# ═════════════════════════════════════════════════════════════════════
# 8. CONTACT (telefon orqali bog'lanish — counter)
# ═════════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("customer:contact:"))
async def contact_poster(query: CallbackQuery) -> None:
    """
    Mijoz poster bilan bog'lanish — telefon raqamini ko'rsatadi va
    contacts_count ni +1 qiladi.
    """
    if query.from_user is None or not query.data:
        return

    state = await session.get(query.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        return await query.answer("Tenant tanlanmagan.", show_alert=True)

    try:
        post_id = int(query.data.rsplit(":", 1)[1])
    except ValueError:
        return await query.answer("Notoʻgʻri ID.", show_alert=True)

    post = await db.get_announcement(post_id, tenant_id=tenant_id)
    if not post:
        return await query.answer("E'lon topilmadi.", show_alert=True)

    poster = await db.get_user(tenant_id, int(post.get("user_id", 0)))
    if not poster:
        return await query.answer("Poster topilmadi.", show_alert=True)

    phone = poster.get("phone", "")
    name = poster.get("full_name", "")

    # Counter +1
    import aiosqlite
    with contextlib.suppress(aiosqlite.Error, ValueError):
        await db.increment_announcement_counter(post_id, tenant_id, "contacts_count")

    # Audit
    await audit_log.log_action(
        actor_role="user",
        actor_id=query.from_user.id,
        tenant_id=tenant_id,
        action="contact_poster",
        target_type="announcement",
        target_id=post_id,
        details={"poster_id": poster.get("user_id")},
    )

    if phone:
        text = (
            f"📞 <b>Bog'lanish</b>\n\n"
            f"👤 {fmt.esc(name)}\n"
            f"📱 <code>{fmt.esc(phone)}</code>\n\n"
            f"<i>Telefon raqamni nusxalash uchun bosib ushlab turing.</i>"
        )
    else:
        text = (
            f"⚠️ Telefon raqam ko'rsatilmagan.\n\n"
            f"👤 {fmt.esc(name)}"
        )
    await query.answer()
    if query.message:
        await query.message.answer(text)


# ═════════════════════════════════════════════════════════════════════
# 9. MY BOOKMARKS — saqlangan e'lonlar ro'yxati
# ═════════════════════════════════════════════════════════════════════
@router.message(F.text == Btn.MY_BOOKMARKS)
async def show_my_bookmarks(message: Message) -> None:
    """Mijozning saqlangan e'lonlari."""
    if message.from_user is None:
        return
    state = await session.get(message.from_user.id)
    tenant_id = state.tenant_id
    if not tenant_id:
        await message.answer("Avval guruh tanlang. /start")
        return

    posts = await db.list_bookmarks(tenant_id, message.from_user.id, limit=20)
    if not posts:
        await message.answer(
            "📭 Saqlangan e'lonlar yo'q.\n\n"
            "Qidiruvda yoqgan e'lonni ⭐ tugmasi bilan saqlashingiz mumkin."
        )
        return

    await message.answer(
        f"⭐ <b>Saqlangan e'lonlar ({len(posts)} ta)</b>"
    )
    for post in posts:
        await _send_post_card(message, post)


# ═════════════════════════════════════════════════════════════════════
# 10. SEARCH HISTORY — placeholder (v1.5'da to'liq qo'shamiz)
# ═════════════════════════════════════════════════════════════════════
@router.message(F.text == Btn.SEARCH_HISTORY)
async def show_search_history(message: Message) -> None:
    """Qidiruv tarixi (hozir oddiy info, v1.5'da DB bilan)."""
    await message.answer(
        "📋 <b>Qidiruv tarixi</b>\n\n"
        "Bu funksiya keyingi versiyada qo'shiladi.\n"
        "Hozircha 🔍 Qidirish va 📰 Yangi eʼlonlardan foydalaning."
    )
