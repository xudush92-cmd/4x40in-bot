"""
POSTCHI_BOT — Viloyatlar bo'yicha e'lon tarqatuvchi Telegram bot.

Bot begona guruhlarga ADMIN qilinadi, guruhlar viloyatlarga ajratiladi.
Foydalanuvchi viloyat tanlaydi + e'lon beradi → bot o'sha viloyat
guruhlariga e'lonni interval bilan yuboradi.

MUHIM: bot e'lonni O'ZI yuboradi (Bot API). Telethon/login/2FA YO'Q.

Rollar:
- 👑 Super admin — hammasini boshqaradi
- 🏢 Guruh egasi — o'z guruhi statistikasi + vaqtincha to'xtatish
- 👤 Foydalanuvchi — e'lon beradi
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
from logging.handlers import RotatingFileHandler

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import database as db
from rate_limiter import RateLimiter
from group_tracker import on_my_chat_member
from sender import entities_to_json
from worker import Scheduler
import config
from config import (
    BOT_TOKEN, SUPER_ADMIN, BOT_USERNAME, ADMIN_CONTACT_PHONE,
    MEDIA_DIR, LOG_FILE, MAX_ADS_PER_USER,
    MIN_INTERVAL_MIN, MAX_INTERVAL_MIN, DEFAULT_INTERVAL_MIN,
    BTN_BACK, BTN_PHONE, BTN_ADS, BTN_REGION, BTN_START, BTN_STOP,
    BTN_STATUS, BTN_STATS, BTN_REFERRAL, BTN_LOGOUT,
    BTN_ADMIN_REGIONS, BTN_ADMIN_GROUPS, BTN_ADMIN_USERS,
    BTN_ADMIN_STATS, BTN_ADMIN_SETTINGS, BTN_OWNER_GROUPS,
)

os.makedirs(MEDIA_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────
logger = logging.getLogger("PostchiBot")
logger.setLevel(logging.INFO)
_fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_fh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
_sh = logging.StreamHandler()
_sh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%H:%M:%S"))
logger.addHandler(_fh)
logger.addHandler(_sh)

# ─────────────────────────────────────────────────────────────────────────
# GLOBAL
# ─────────────────────────────────────────────────────────────────────────
user_states: dict[int, dict] = {}
rate_limiter = RateLimiter()
scheduler: Scheduler | None = None
application: Application | None = None


def is_super(uid: int) -> bool:
    return uid == SUPER_ADMIN


def _user_media_dir(uid: int) -> str:
    p = os.path.join(MEDIA_DIR, str(uid))
    os.makedirs(p, exist_ok=True)
    return p


def _safe_unlink(path: str | None) -> None:
    if not path:
        return
    with contextlib.suppress(Exception):
        if os.path.exists(path):
            os.remove(path)


# ─────────────────────────────────────────────────────────────────────────
# MENYULAR
# ─────────────────────────────────────────────────────────────────────────
def kb_register() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🚀 Ro'yxatdan o'tish")]], resize_keyboard=True
    )


def kb_pending() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("⏳ Tasdiq kutilmoqda...")]], resize_keyboard=True
    )


def kb_phone() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(BTN_PHONE, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def kb_user(is_owner: bool = False, super_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(BTN_ADS), KeyboardButton(BTN_REGION)],
        [KeyboardButton(BTN_START), KeyboardButton(BTN_STOP)],
        [KeyboardButton(BTN_STATUS), KeyboardButton(BTN_STATS)],
        [KeyboardButton(BTN_REFERRAL), KeyboardButton(BTN_LOGOUT)],
    ]
    if is_owner:
        rows.insert(0, [KeyboardButton(BTN_OWNER_GROUPS)])
    if super_admin:
        rows.insert(0, [
            KeyboardButton(BTN_ADMIN_REGIONS), KeyboardButton(BTN_ADMIN_GROUPS),
        ])
        rows.insert(1, [
            KeyboardButton(BTN_ADMIN_USERS), KeyboardButton(BTN_ADMIN_STATS),
        ])
        rows.insert(2, [KeyboardButton(BTN_ADMIN_SETTINGS)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


async def menu_for(uid: int) -> ReplyKeyboardMarkup:
    """Foydalanuvchi roliga mos klaviatura."""
    if is_super(uid):
        # Super admin ham guruh egasi/foydalanuvchi bo'lishi mumkin
        owner_groups = await db.get_groups_by_owner(uid)
        return kb_user(is_owner=bool(owner_groups), super_admin=True)

    user = await db.get_user(uid)
    approved = bool(user and user.get("is_approved") and not user.get("is_blocked"))
    if not approved:
        if user and (user.get("awaiting_approval")):
            return kb_pending()
        return kb_register()

    owner_groups = await db.get_groups_by_owner(uid)
    return kb_user(is_owner=bool(owner_groups), super_admin=False)


# ─────────────────────────────────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id

    if not rate_limiter.is_allowed(uid, "command"):
        wait = rate_limiter.get_wait_time(uid, "command")
        await update.message.reply_text(f"⏳ Juda ko'p so'rov. {wait} soniya kuting.")
        return

    # Referal: /start ref_<uid>
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            ref_part = arg[4:]
            if ref_part.isdigit() and not await db.is_approved(uid):
                with contextlib.suppress(Exception):
                    await db.set_referrer(uid, int(ref_part))

    # Allaqachon tasdiqlangan
    if await db.is_approved(uid) or is_super(uid):
        await update.message.reply_text(
            "🏠 Bosh menyu", reply_markup=await menu_for(uid)
        )
        return

    # Tasdiq kutyapti
    user = await db.get_user(uid)
    if user and user.get("awaiting_approval"):
        await update.message.reply_text(
            "⏳ So'rovingiz ko'rib chiqilmoqda. Admin tasdiqlashini kuting.",
            reply_markup=kb_pending(),
        )
        return

    # Yangi foydalanuvchi
    await update.message.reply_text(
        "📮 POSTCHI BOT — viloyatlar bo'yicha e'lon tarqatuvchi bot\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 BOT NIMA QILADI?\n\n"
        "Siz viloyat tanlaysiz va e'lon yozasiz — bot o'sha viloyatdagi\n"
        "barcha guruhlarga e'loningizni avtomatik tarqatadi.\n\n"
        "✅ Login, kod, parol KERAK EMAS\n"
        "✅ Faqat ism + telefon + admin tasdig'i\n"
        "✅ E'lon ostida bog'lanish tugmasi bo'ladi\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "📋 BOSHLASH\n\n"
        "1️⃣ '🚀 Ro'yxatdan o'tish' tugmasini bosing\n"
        "2️⃣ Ismingizni kiriting\n"
        "3️⃣ Telefon raqamingizni yuboring\n"
        "4️⃣ Admin tasdiqlashini kuting\n\n"
        f"📞 Admin: {ADMIN_CONTACT_PHONE}",
        reply_markup=kb_register(),
    )


# ─────────────────────────────────────────────────────────────────────────
# RO'YXATDAN O'TISH
# ─────────────────────────────────────────────────────────────────────────
async def _begin_register(update: Update) -> None:
    uid = update.effective_user.id
    user_states[uid] = {"step": "reg_name"}
    await update.message.reply_text(
        "📋 RO'YXATDAN O'TISH (1/2)\n\n"
        "👤 To'liq ismingizni kiriting:\n\n"
        "Masalan: Akmal Karimov"
    )


async def _handle_reg_name(update: Update, text: str) -> None:
    uid = update.effective_user.id
    name = text.strip()
    if len(name) < 2:
        await update.message.reply_text("❌ Ism juda qisqa. Qaytadan kiriting:")
        return
    name = name[:64]
    username = update.effective_user.username or ""
    await db.set_user_info(uid, name, username)
    user_states[uid] = {"step": "reg_phone"}
    await update.message.reply_text(
        f"✅ Rahmat, {name}!\n\n"
        "📋 RO'YXATDAN O'TISH (2/2)\n\n"
        "📱 Telefon raqamingizni yuboring.\n"
        "Pastdagi tugmani bosing yoki +998... ko'rinishida yozing.",
        reply_markup=kb_phone(),
    )


async def _handle_reg_phone(update: Update, phone: str) -> None:
    uid = update.effective_user.id
    phone = phone.strip().replace(" ", "")
    if not phone.startswith("+") or not phone[1:].isdigit() or len(phone) < 7:
        await update.message.reply_text(
            "❌ Telefon + bilan boshlanishi kerak. Masalan: +998901234567"
        )
        return
    await db.set_phone(uid, phone)
    await db.set_awaiting_approval(uid, True)
    user_states.pop(uid, None)
    logger.info("Ro'yxat so'rovi: %s (%s)", uid, phone)
    await _notify_admin_approval(uid)
    await update.message.reply_text(
        "✅ So'rovingiz qabul qilindi!\n\n"
        "⏳ Admin tasdiqlashini kuting. Tasdiqlangach menyu ochiladi.\n\n"
        f"📞 Tezroq tasdiqlanish uchun: {ADMIN_CONTACT_PHONE}",
        reply_markup=kb_pending(),
    )


async def _notify_admin_approval(uid: int) -> None:
    user = await db.get_user(uid)
    name = (user or {}).get("name", "Noma'lum")
    username = (user or {}).get("username", "")
    phone = (user or {}).get("phone", "")
    uname = f"@{username}" if username else "username yo'q"
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"appr:ok:{uid}"),
            InlineKeyboardButton("⛔ Rad etish", callback_data=f"appr:no:{uid}"),
        ],
    ])
    text = (
        "🔔 Yangi foydalanuvchi tasdiq so'ramoqda\n\n"
        f"👤 Ism: {name}\n"
        f"📱 Telefon: {phone}\n"
        f"📎 {uname}\n"
        f"🆔 ID: {uid}"
    )
    with contextlib.suppress(Exception):
        await application.bot.send_message(SUPER_ADMIN, text, reply_markup=kb)


# ─────────────────────────────────────────────────────────────────────────
# ERROR HANDLER
# ─────────────────────────────────────────────────────────────────────────
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Handler xato: %s", context.error)



# ─────────────────────────────────────────────────────────────────────────
# MESSAGE HANDLER (asosiy router)
# ─────────────────────────────────────────────────────────────────────────
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    msg = update.message
    if not msg:
        return
    text = (msg.text or "").strip()
    state = user_states.get(uid, {})
    step = state.get("step")

    if not rate_limiter.is_allowed(uid, "message"):
        wait = rate_limiter.get_wait_time(uid, "message")
        await msg.reply_text(f"⏳ Juda ko'p xabar. {wait} soniya kuting.")
        return

    # ── Kontakt (telefon tugmasi) ────────────────────────────────────────
    if msg.contact and step == "reg_phone":
        phone = msg.contact.phone_number
        if not phone.startswith("+"):
            phone = "+" + phone
        await _handle_reg_phone(update, phone)
        return

    # ── RO'YXATDAN O'TISH BOSQICHLARI ────────────────────────────────────
    if step == "reg_name":
        await _handle_reg_name(update, text)
        return
    if step == "reg_phone":
        await _handle_reg_phone(update, text)
        return

    # ── FSM: menyu tugmasi bosilsa holatni bekor qilamiz ─────────────────
    if step in ("add_ad", "edit_ad", "ad_contact", "region_name",
                "region_rename", "set_interval"):
        if _is_menu_button(text):
            user_states.pop(uid, None)
            # pastga tushadi — menyu handleriga
        else:
            await _route_fsm(update, context, step, text)
            return

    # ── TASDIQLANMAGAN ───────────────────────────────────────────────────
    approved = is_super(uid) or await db.is_approved(uid)
    if not approved:
        user = await db.get_user(uid)
        if user and user.get("awaiting_approval"):
            await msg.reply_text(
                "⏳ So'rovingiz ko'rib chiqilmoqda. Admin tasdiqlashini kuting.",
                reply_markup=kb_pending(),
            )
            return
        if text == "🚀 Ro'yxatdan o'tish":
            await _begin_register(update)
            return
        await msg.reply_text(
            "⚠️ Avval 🚀 Ro'yxatdan o'ting.", reply_markup=kb_register()
        )
        return

    # ── SUPER ADMIN tugmalari ────────────────────────────────────────────
    if is_super(uid):
        if text == BTN_ADMIN_REGIONS:
            await _admin_regions(update)
            return
        if text == BTN_ADMIN_GROUPS:
            await _admin_groups(update)
            return
        if text == BTN_ADMIN_USERS:
            await _admin_users(update)
            return
        if text == BTN_ADMIN_STATS:
            await _admin_stats(update)
            return
        if text == BTN_ADMIN_SETTINGS:
            await _admin_settings(update)
            return

    # ── GURUH EGASI tugmasi ──────────────────────────────────────────────
    if text == BTN_OWNER_GROUPS:
        await _owner_groups(update)
        return

    # ── FOYDALANUVCHI tugmalari ──────────────────────────────────────────
    if text == BTN_ADS:
        await _show_ads(update)
        return
    if text == BTN_REGION:
        await _show_regions_for_user(update)
        return
    if text == BTN_START:
        await _user_start(update)
        return
    if text == BTN_STOP:
        await _user_stop(update)
        return
    if text == BTN_STATUS:
        await _user_status(update)
        return
    if text == BTN_STATS:
        await _user_stats(update)
        return
    if text == BTN_REFERRAL:
        await _user_referral(update)
        return
    if text == BTN_LOGOUT:
        await _user_logout(update)
        return

    await msg.reply_text(
        "⚠️ Iltimos, menyudagi tugmalardan foydalaning.",
        reply_markup=await menu_for(uid),
    )


_MENU_BUTTONS = {
    BTN_ADS, BTN_REGION, BTN_START, BTN_STOP, BTN_STATUS, BTN_STATS,
    BTN_REFERRAL, BTN_LOGOUT, BTN_OWNER_GROUPS,
    BTN_ADMIN_REGIONS, BTN_ADMIN_GROUPS, BTN_ADMIN_USERS,
    BTN_ADMIN_STATS, BTN_ADMIN_SETTINGS,
}


def _is_menu_button(text: str) -> bool:
    return text in _MENU_BUTTONS


async def _route_fsm(update, context, step: str, text: str) -> None:
    if step == "add_ad":
        await _handle_add_ad(update)
    elif step == "edit_ad":
        await _handle_edit_ad(update)
    elif step == "ad_contact":
        await _handle_ad_contact(update, text)
    elif step == "region_name":
        await _handle_region_name(update, text)
    elif step == "region_rename":
        await _handle_region_rename(update, text)
    elif step == "set_interval":
        await _handle_set_interval(update, text)



# ═════════════════════════════════════════════════════════════════════════
# FOYDALANUVCHI AMALLARI
# ═════════════════════════════════════════════════════════════════════════

# ── E'LONLAR ─────────────────────────────────────────────────────────────
async def _show_ads(update: Update) -> None:
    uid = update.effective_user.id
    ads = await db.get_ads(uid)
    user = await db.get_user(uid)
    active_id = (user or {}).get("active_ad_id")

    lines = [f"📢 E'LONLARINGIZ ({len(ads)}/{MAX_ADS_PER_USER})", ""]
    rows = []
    for i, a in enumerate(ads, 1):
        mark = "✅" if a["id"] == active_id else "▫️"
        icon = "🖼" if a.get("photo_path") else "📝"
        preview = (a.get("text_content") or "(faqat rasm)")[:30]
        lines.append(f"{mark} {i}. {icon} {preview}")
        rows.append([
            InlineKeyboardButton(f"✅ {i} faol", callback_data=f"adact:{a['id']}"),
            InlineKeyboardButton(f"✏️ {i}", callback_data=f"aded:{a['id']}"),
            InlineKeyboardButton(f"🗑 {i}", callback_data=f"addel:{a['id']}"),
        ])
    if len(ads) < MAX_ADS_PER_USER:
        rows.append([InlineKeyboardButton("➕ Yangi e'lon qo'shish", callback_data="adnew")])
    if not ads:
        lines.append("Hozircha e'lon yo'q. ➕ tugma orqali qo'shing.")

    await update.message.reply_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(rows) if rows else None
    )


async def _handle_add_ad(update: Update) -> None:
    """E'lon mazmunini qabul qiladi → kontakt so'raydi."""
    uid = update.effective_user.id
    msg = update.message
    text = msg.text or msg.caption or ""
    entities_src = list(msg.entities or []) + list(msg.caption_entities or [])

    photo_path = None
    if msg.photo:
        try:
            tg_file = await msg.photo[-1].get_file()
            photo_path = os.path.join(_user_media_dir(uid), f"{uuid.uuid4().hex}.jpg")
            await tg_file.download_to_drive(custom_path=photo_path)
        except Exception as e:
            logger.error("Rasm yuklash xatosi %s: %s", uid, e)
            await msg.reply_text("❌ Rasmni saqlab bo'lmadi. Qaytadan urinib ko'ring.",
                                 reply_markup=await menu_for(uid))
            return

    if not text.strip() and not photo_path:
        await msg.reply_text("❌ Bo'sh e'lon qabul qilinmaydi. Matn yoki rasm yuboring.",
                             reply_markup=await menu_for(uid))
        return

    # Mazmunni vaqtincha saqlaymiz, kontakt so'raymiz
    user_states[uid] = {
        "step": "ad_contact",
        "ad_text": text,
        "ad_entities": entities_to_json(entities_src),
        "ad_photo": photo_path,
    }
    await msg.reply_text(
        "📞 Bog'lanish uchun kontakt kiriting:\n\n"
        "@username yoki +998... ko'rinishida.\n"
        "(Bu e'lon ostidagi '📞 Bog'lanish' tugmasiga biriktiriladi.)\n\n"
        "Agar kerak bo'lmasa — 'yo'q' deb yozing."
    )


async def _handle_ad_contact(update: Update, text: str) -> None:
    """Kontakt qabul qilinadi → e'lon saqlanadi."""
    uid = update.effective_user.id
    state = user_states.get(uid, {})
    contact = text.strip()
    if contact.lower() in ("yo'q", "yoq", "yo`q", "-"):
        contact = ""

    ad_text = state.get("ad_text", "")
    ad_entities = state.get("ad_entities", "[]")
    ad_photo = state.get("ad_photo")
    edit_id = state.get("edit_ad_id")
    user_states.pop(uid, None)

    if edit_id:
        # Tahrirlash
        old = await db.get_ad(edit_id)
        await db.update_ad(edit_id, ad_text, ad_entities, ad_photo, contact)
        if old and old.get("photo_path") and old["photo_path"] != ad_photo:
            _safe_unlink(old["photo_path"])
        await update.message.reply_text("✅ E'lon yangilandi!", reply_markup=await menu_for(uid))
        return

    ok, reason, ad_id = await db.add_ad(
        uid, ad_text, ad_entities, ad_photo, contact, MAX_ADS_PER_USER
    )
    if not ok:
        _safe_unlink(ad_photo)
        if reason == "limit":
            await update.message.reply_text(
                f"❌ Maksimal {MAX_ADS_PER_USER} ta e'lon. Avval birini o'chiring.",
                reply_markup=await menu_for(uid),
            )
        else:
            await update.message.reply_text("❌ Saqlab bo'lmadi.", reply_markup=await menu_for(uid))
        return

    # Birinchi e'lon bo'lsa — avtomatik faol qilamiz
    user = await db.get_user(uid)
    if not (user or {}).get("active_ad_id"):
        await db.set_active_ad(uid, ad_id)

    await update.message.reply_text(
        "✅ E'lon saqlandi!\n\n"
        "Endi 🗺 Viloyat tanlang va ▶️ Boshlang.",
        reply_markup=await menu_for(uid),
    )


async def _handle_edit_ad(update: Update) -> None:
    """Tahrirlashda yangi mazmun qabul qilinadi → kontakt so'raladi."""
    uid = update.effective_user.id
    state = user_states.get(uid, {})
    edit_id = state.get("edit_ad_id")
    msg = update.message
    text = msg.text or msg.caption or ""
    entities_src = list(msg.entities or []) + list(msg.caption_entities or [])

    ad = await db.get_ad(edit_id) if edit_id else None
    if not ad:
        user_states.pop(uid, None)
        await msg.reply_text("❌ E'lon topilmadi.", reply_markup=await menu_for(uid))
        return

    photo_path = None
    if msg.photo:
        try:
            tg_file = await msg.photo[-1].get_file()
            photo_path = os.path.join(_user_media_dir(uid), f"{uuid.uuid4().hex}.jpg")
            await tg_file.download_to_drive(custom_path=photo_path)
        except Exception:
            await msg.reply_text("❌ Rasmni saqlab bo'lmadi.", reply_markup=await menu_for(uid))
            return

    if not text.strip() and not photo_path:
        await msg.reply_text("❌ Bo'sh e'lon qabul qilinmaydi.", reply_markup=await menu_for(uid))
        return

    user_states[uid] = {
        "step": "ad_contact",
        "ad_text": text,
        "ad_entities": entities_to_json(entities_src),
        "ad_photo": photo_path,
        "edit_ad_id": edit_id,
    }
    await msg.reply_text(
        "📞 Bog'lanish kontaktini kiriting (@username yoki +998...).\n"
        "Kerak bo'lmasa — 'yo'q' deb yozing."
    )


# ── VILOYAT ──────────────────────────────────────────────────────────────
async def _show_regions_for_user(update: Update) -> None:
    uid = update.effective_user.id
    regions = await db.get_regions()
    if not regions:
        await update.message.reply_text(
            "❌ Hozircha viloyatlar yo'q. Admin bilan bog'laning.",
            reply_markup=await menu_for(uid),
        )
        return
    rows = []
    row = []
    for r in regions:
        cnt = await db.count_groups_in_region(r["id"])
        row.append(InlineKeyboardButton(f"{r['name']} ({cnt})", callback_data=f"rsel:{r['id']}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    await update.message.reply_text(
        "🗺 Viloyatni tanlang (qavsda — guruhlar soni):",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _user_start(update: Update) -> None:
    uid = update.effective_user.id
    user = await db.get_user(uid)
    ad_id = (user or {}).get("active_ad_id")
    region_id = (user or {}).get("selected_region_id")

    if not ad_id:
        await update.message.reply_text("❌ Avval 📢 E'lon qo'shing va faol qiling.",
                                        reply_markup=await menu_for(uid))
        return
    if not region_id:
        await update.message.reply_text("❌ Avval 🗺 Viloyat tanlang.",
                                        reply_markup=await menu_for(uid))
        return
    groups = await db.get_active_groups_in_region(region_id)
    if not groups:
        await update.message.reply_text("❌ Tanlangan viloyatda faol guruh yo'q.",
                                        reply_markup=await menu_for(uid))
        return

    await db.set_running(uid, True)
    region = await db.get_region(region_id)
    rname = (region or {}).get("name", "?")
    logger.info("Start: %s (viloyat=%s, guruhlar=%s)", uid, rname, len(groups))
    await update.message.reply_text(
        f"✅ E'loningiz yuborila boshlandi!\n\n"
        f"🗺 Viloyat: {rname}\n"
        f"👥 Guruhlar: {len(groups)} ta\n"
        f"⏱ Har guruh o'z intervali bilan oladi.",
        reply_markup=await menu_for(uid),
    )


async def _user_stop(update: Update) -> None:
    uid = update.effective_user.id
    if not await db.get_running(uid):
        await update.message.reply_text("⚠️ Hozir ishlamayapti.", reply_markup=await menu_for(uid))
        return
    await db.set_running(uid, False)
    logger.info("Stop: %s", uid)
    await update.message.reply_text("⛔ E'lon yuborish to'xtatildi.", reply_markup=await menu_for(uid))


async def _user_status(update: Update) -> None:
    uid = update.effective_user.id
    user = await db.get_user(uid)
    ad_id = (user or {}).get("active_ad_id")
    region_id = (user or {}).get("selected_region_id")
    running = bool((user or {}).get("running"))

    region = await db.get_region(region_id) if region_id else None
    ad = await db.get_ad(ad_id) if ad_id else None
    ads_count = await db.count_ads(uid)

    status = "🟢 ISHLAYAPTI" if running else "🔴 TO'XTAGAN"
    rname = region["name"] if region else "tanlanmagan"
    ad_preview = (ad.get("text_content") or "(rasm)")[:40] if ad else "tanlanmagan"

    await update.message.reply_text(
        "📊 HOLAT\n\n"
        f"Holat: {status}\n"
        f"🗺 Viloyat: {rname}\n"
        f"📢 Faol e'lon: {ad_preview}\n"
        f"📦 Jami e'lonlar: {ads_count}/{MAX_ADS_PER_USER}",
        reply_markup=await menu_for(uid),
    )


async def _user_stats(update: Update) -> None:
    uid = update.effective_user.id
    user = await db.get_user(uid)
    ad_id = (user or {}).get("active_ad_id")
    if not ad_id:
        await update.message.reply_text("❌ Faol e'lon yo'q.", reply_markup=await menu_for(uid))
        return
    stats = await db.get_ad_send_stats(ad_id)
    today = await db.count_sends_today(uid=uid)
    await update.message.reply_text(
        "📈 STATISTIKA (faol e'lon)\n\n"
        f"✅ Muvaffaqiyatli: {stats['ok']} ta\n"
        f"❌ Xato: {stats['error']} ta\n"
        f"📅 Bugun yuborilgan: {today} ta",
        reply_markup=await menu_for(uid),
    )


async def _user_referral(update: Update) -> None:
    uid = update.effective_user.id
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
    total = await db.count_referrals(uid)
    await update.message.reply_text(
        "👥 REFERAL\n\n"
        "🔗 Sizning havolangiz:\n"
        f"{link}\n\n"
        f"✅ Faol referallar: {total} ta\n"
        "(ro'yxatdan o'tib, tasdiqlanganlar)",
        reply_markup=await menu_for(uid),
    )


async def _user_logout(update: Update) -> None:
    uid = update.effective_user.id
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ha", callback_data="lo:yes"),
        InlineKeyboardButton("❌ Yo'q", callback_data="lo:no"),
    ]])
    await update.message.reply_text(
        "🚪 Chiqasizmi? E'lon yuborish to'xtaydi.", reply_markup=kb
    )



# ═════════════════════════════════════════════════════════════════════════
# SUPER ADMIN AMALLARI
# ═════════════════════════════════════════════════════════════════════════
async def _admin_regions(update: Update) -> None:
    regions = await db.get_regions()
    lines = [f"🗺 VILOYATLAR ({len(regions)} ta)", ""]
    rows = []
    for r in regions:
        cnt = await db.count_groups_in_region(r["id"])
        lines.append(f"• {r['name']} — {cnt} guruh")
        rows.append([
            InlineKeyboardButton(f"✏️ {r['name']}", callback_data=f"rgren:{r['id']}"),
            InlineKeyboardButton(f"🗑 {r['name']}", callback_data=f"rgdel:{r['id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ Viloyat qo'shish", callback_data="rgnew")])
    await update.message.reply_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(rows)
    )


async def _admin_groups(update: Update) -> None:
    groups = await db.get_all_groups()
    unassigned = [g for g in groups if not g.get("region_id")]
    lines = [f"👥 GURUHLAR ({len(groups)} ta)", ""]
    if unassigned:
        lines.append(f"⚠️ Biriktirilmagan: {len(unassigned)} ta")
        lines.append("")
    rows = []
    for g in groups[:30]:
        region = await db.get_region(g["region_id"]) if g.get("region_id") else None
        rname = region["name"] if region else "❓ biriktirilmagan"
        status = "🟢" if g.get("is_active") else "🔴"
        pause = " ⏸" if g.get("is_paused") else ""
        title = (g.get("title") or str(g["chat_id"]))[:25]
        lines.append(f"{status}{pause} {title}\n   📍 {rname} | ⏱ {g.get('interval_min')} daq")
        rows.append([
            InlineKeyboardButton(f"🏷 {title[:15]}", callback_data=f"grbind:{g['id']}"),
            InlineKeyboardButton("⏱", callback_data=f"grint:{g['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"grdel:{g['id']}"),
        ])
    if not groups:
        lines.append("Hozircha guruh yo'q. Botni guruhga admin qiling.")
    await update.message.reply_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(rows) if rows else None
    )


async def _admin_users(update: Update) -> None:
    pending = await db.get_pending_users()
    approved = await db.get_approved_users()
    lines = [f"👤 FOYDALANUVCHILAR", "", f"⏳ Tasdiq kutayotgan: {len(pending)}",
             f"✅ Tasdiqlangan: {len(approved)}", ""]
    rows = []
    for u in pending[:15]:
        name = u.get("name", str(u["uid"]))
        lines.append(f"⏳ {name} ({u['uid']})")
        rows.append([
            InlineKeyboardButton(f"✅ {name[:12]}", callback_data=f"appr:ok:{u['uid']}"),
            InlineKeyboardButton("⛔", callback_data=f"appr:no:{u['uid']}"),
        ])
    for u in approved[:15]:
        if is_super(u["uid"]):
            continue
        name = u.get("name", str(u["uid"]))
        blocked = " 🚫" if u.get("is_blocked") else ""
        lines.append(f"✅ {name} ({u['uid']}){blocked}")
        rows.append([
            InlineKeyboardButton(f"🚫 {name[:10]}", callback_data=f"ublk:{u['uid']}"),
            InlineKeyboardButton("🗑", callback_data=f"udel:{u['uid']}"),
        ])
    await update.message.reply_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(rows) if rows else None
    )


async def _admin_stats(update: Update) -> None:
    regions = await db.get_regions()
    groups = await db.get_all_groups()
    approved = await db.get_approved_users()
    active_groups = [g for g in groups if g.get("is_active")]
    lines = [
        "📊 STATISTIKA", "",
        f"🗺 Viloyatlar: {len(regions)}",
        f"👥 Guruhlar: {len(groups)} (faol: {len(active_groups)})",
        f"👤 Tasdiqlangan userlar: {len(approved)}",
        "", "📍 Viloyatlar bo'yicha:",
    ]
    for r in regions:
        cnt = await db.count_groups_in_region(r["id"])
        lines.append(f"• {r['name']}: {cnt} guruh")
    await update.message.reply_text("\n".join(lines), reply_markup=await menu_for(update.effective_user.id))


async def _admin_settings(update: Update) -> None:
    await update.message.reply_text(
        "⚙️ SOZLAMALAR\n\n"
        f"⏱ Standart interval: {DEFAULT_INTERVAL_MIN} daqiqa\n"
        f"   (admin guruhga interval bermasa)\n"
        f"📦 Maksimal e'lon: {MAX_ADS_PER_USER} ta\n"
        f"⏳ Interval oralig'i: {MIN_INTERVAL_MIN}-{MAX_INTERVAL_MIN} daq\n\n"
        "Guruh intervalini 👥 Guruhlar bo'limidan o'zgartiring.",
        reply_markup=await menu_for(update.effective_user.id),
    )


# ═════════════════════════════════════════════════════════════════════════
# GURUH EGASI AMALLARI
# ═════════════════════════════════════════════════════════════════════════
async def _owner_groups(update: Update) -> None:
    uid = update.effective_user.id
    groups = await db.get_groups_by_owner(uid)
    if not groups:
        await update.message.reply_text("❌ Sizning guruhingiz yo'q.", reply_markup=await menu_for(uid))
        return
    lines = ["🏢 MENING GURUHLARIM", ""]
    rows = []
    for g in groups:
        region = await db.get_region(g["region_id"]) if g.get("region_id") else None
        rname = region["name"] if region else "biriktirilmagan"
        sent_today = await db.count_sends_today(group_id=g["id"])
        users_cnt = await db.count_active_users_in_group(g["id"])
        status = "⏸ PAUZA" if g.get("is_paused") else ("🟢 FAOL" if g.get("is_active") else "🔴 NOFAOL")
        title = g.get("title") or str(g["chat_id"])
        lines.append(
            f"📛 {title}\n"
            f"   📍 {rname} | ⏱ {g.get('interval_min')} daq | {status}\n"
            f"   📊 Bugun: {sent_today} e'lon | 👥 {users_cnt} foydalanuvchi"
        )
        if g.get("is_paused"):
            rows.append([InlineKeyboardButton(f"▶️ Yoqish: {title[:15]}", callback_data=f"opause:{g['id']}:0")])
        else:
            rows.append([InlineKeyboardButton(f"⏸ To'xtatish: {title[:15]}", callback_data=f"opause:{g['id']}:1")])
    await update.message.reply_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(rows) if rows else None
    )


# ═════════════════════════════════════════════════════════════════════════
# FSM HANDLERLAR (matn kutuvchi holatlar)
# ═════════════════════════════════════════════════════════════════════════
async def _handle_region_name(update: Update, text: str) -> None:
    uid = update.effective_user.id
    name = text.strip()[:64]
    user_states.pop(uid, None)
    if len(name) < 2:
        await update.message.reply_text("❌ Nom juda qisqa.", reply_markup=await menu_for(uid))
        return
    ok, reason = await db.add_region(name)
    if ok:
        await update.message.reply_text(f"✅ Viloyat qo'shildi: {name}", reply_markup=await menu_for(uid))
    elif reason == "duplicate":
        await update.message.reply_text("⚠️ Bunday viloyat allaqachon bor.", reply_markup=await menu_for(uid))
    else:
        await update.message.reply_text("❌ Qo'shib bo'lmadi.", reply_markup=await menu_for(uid))


async def _handle_region_rename(update: Update, text: str) -> None:
    uid = update.effective_user.id
    state = user_states.get(uid, {})
    region_id = state.get("region_id")
    user_states.pop(uid, None)
    new_name = text.strip()[:64]
    if region_id and len(new_name) >= 2:
        await db.rename_region(region_id, new_name)
        await update.message.reply_text(f"✅ Yangi nom: {new_name}", reply_markup=await menu_for(uid))
    else:
        await update.message.reply_text("❌ Bekor qilindi.", reply_markup=await menu_for(uid))


async def _handle_set_interval(update: Update, text: str) -> None:
    uid = update.effective_user.id
    state = user_states.get(uid, {})
    user_states.pop(uid, None)
    target = state.get("interval_target")  # ("group", group_id) yoki ("bind", group_id, region_id)
    try:
        m = int(text.strip())
    except Exception:
        await update.message.reply_text(
            f"❌ Faqat son ({MIN_INTERVAL_MIN}-{MAX_INTERVAL_MIN}).",
            reply_markup=await menu_for(uid))
        return
    if m < MIN_INTERVAL_MIN or m > MAX_INTERVAL_MIN:
        await update.message.reply_text(
            f"❌ {MIN_INTERVAL_MIN}-{MAX_INTERVAL_MIN} oralig'ida bo'lsin.",
            reply_markup=await menu_for(uid))
        return

    if not target:
        await update.message.reply_text("❌ Jarayon buzildi.", reply_markup=await menu_for(uid))
        return

    if target[0] == "group":
        await db.set_group_interval(target[1], m)
        await update.message.reply_text(f"✅ Interval o'rnatildi: {m} daqiqa", reply_markup=await menu_for(uid))
    elif target[0] == "bind":
        await db.assign_group_region(target[1], target[2], m)
        region = await db.get_region(target[2])
        await update.message.reply_text(
            f"✅ Guruh biriktirildi: {region['name'] if region else ''} / {m} daqiqa",
            reply_markup=await menu_for(uid),
        )



# ═════════════════════════════════════════════════════════════════════════
# CALLBACK HANDLER (barcha inline tugmalar)
# ═════════════════════════════════════════════════════════════════════════
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data or ""

    # ── Guruhni viloyatga biriktirish (group_tracker so'rovi) ────────────
    if data.startswith("setgr:"):
        if not is_super(uid):
            return
        _, chat_id_s, region_s = data.split(":")
        chat_id = int(chat_id_s)
        group = await db.get_group_by_chat(chat_id)
        if not group:
            await q.edit_message_text("⚠️ Guruh topilmadi.")
            return
        if region_s == "skip":
            await q.edit_message_text("⏭ Biriktirilmadi. Keyin 👥 Guruhlar dan biriktiring.")
            return
        region_id = int(region_s)
        # Interval so'raymiz
        user_states[uid] = {"step": "set_interval", "interval_target": ("bind", group["id"], region_id)}
        region = await db.get_region(region_id)
        await q.edit_message_text(
            f"✅ Viloyat: {region['name'] if region else ''}\n\n"
            f"⏱ Endi interval (daqiqa) kiriting ({MIN_INTERVAL_MIN}-{MAX_INTERVAL_MIN}).\n"
            f"Standart: {DEFAULT_INTERVAL_MIN}"
        )
        return

    # ── Foydalanuvchi tasdiqlash ─────────────────────────────────────────
    if data.startswith("appr:"):
        if not is_super(uid):
            return
        _, action, target_s = data.split(":")
        target = int(target_s)
        if action == "ok":
            await db.set_approved(target, True)
            logger.info("Tasdiqlandi: %s", target)
            await q.edit_message_text(f"✅ Tasdiqlandi: {target}")
            with contextlib.suppress(Exception):
                await context.bot.send_message(
                    target,
                    "✅ Hisobingiz tasdiqlandi!\n\n"
                    "Endi 📢 E'lon qo'shing, 🗺 Viloyat tanlang va ▶️ Boshlang.",
                    reply_markup=await menu_for(target),
                )
            # Referal hisoblash
            with contextlib.suppress(Exception):
                referrer = await db.try_count_referral(target)
                if referrer:
                    total = await db.count_referrals(referrer)
                    await context.bot.send_message(
                        referrer,
                        f"🎉 Referalingiz faollashdi!\n👥 Jami: {total} ta",
                    )
        else:
            await db.set_awaiting_approval(target, False)
            await q.edit_message_text(f"⛔ Rad etildi: {target}")
            with contextlib.suppress(Exception):
                await context.bot.send_message(
                    target,
                    f"❌ So'rovingiz rad etildi.\n📞 {ADMIN_CONTACT_PHONE}",
                )
        return

    # ── Foydalanuvchi bloklash / o'chirish ───────────────────────────────
    if data.startswith("ublk:"):
        if not is_super(uid):
            return
        target = int(data.split(":")[1])
        user = await db.get_user(target)
        new_val = not bool((user or {}).get("is_blocked"))
        await db.set_blocked(target, new_val)
        if new_val:
            await db.set_running(target, False)
        await q.edit_message_text(f"{'🚫 Bloklandi' if new_val else '✅ Blokdan chiqarildi'}: {target}")
        return

    if data.startswith("udel:"):
        if not is_super(uid):
            return
        target = int(data.split(":")[1])
        await db.set_running(target, False)
        await db.delete_user(target)
        await q.edit_message_text(f"🗑 O'chirildi: {target}")
        return

    # ── Viloyat boshqaruvi ───────────────────────────────────────────────
    if data == "rgnew":
        if not is_super(uid):
            return
        user_states[uid] = {"step": "region_name"}
        await q.edit_message_text("➕ Yangi viloyat nomini kiriting:")
        return

    if data.startswith("rgren:"):
        if not is_super(uid):
            return
        region_id = int(data.split(":")[1])
        user_states[uid] = {"step": "region_rename", "region_id": region_id}
        await q.edit_message_text("✏️ Yangi nomni kiriting:")
        return

    if data.startswith("rgdel:"):
        if not is_super(uid):
            return
        region_id = int(data.split(":")[1])
        await db.delete_region(region_id)
        await q.edit_message_text("🗑 Viloyat o'chirildi (guruhlar biriktirilmagan bo'ldi).")
        return

    # ── Guruh boshqaruvi (admin) ─────────────────────────────────────────
    if data.startswith("grbind:"):
        if not is_super(uid):
            return
        group_id = int(data.split(":")[1])
        regions = await db.get_regions()
        if not regions:
            await q.edit_message_text("❌ Avval viloyat qo'shing.")
            return
        rows = []
        row = []
        for r in regions:
            row.append(InlineKeyboardButton(r["name"], callback_data=f"grsetr:{group_id}:{r['id']}"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        await q.edit_message_text("🏷 Qaysi viloyatga?", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("grsetr:"):
        if not is_super(uid):
            return
        _, group_id_s, region_s = data.split(":")
        user_states[uid] = {
            "step": "set_interval",
            "interval_target": ("bind", int(group_id_s), int(region_s)),
        }
        region = await db.get_region(int(region_s))
        await q.edit_message_text(
            f"✅ Viloyat: {region['name'] if region else ''}\n"
            f"⏱ Interval (daqiqa) kiriting (standart {DEFAULT_INTERVAL_MIN}):"
        )
        return

    if data.startswith("grint:"):
        if not is_super(uid):
            return
        group_id = int(data.split(":")[1])
        user_states[uid] = {"step": "set_interval", "interval_target": ("group", group_id)}
        await q.edit_message_text(
            f"⏱ Yangi interval (daqiqa) kiriting ({MIN_INTERVAL_MIN}-{MAX_INTERVAL_MIN}):"
        )
        return

    if data.startswith("grdel:"):
        if not is_super(uid):
            return
        group_id = int(data.split(":")[1])
        await db.delete_group(group_id)
        await q.edit_message_text("🗑 Guruh ro'yxatdan o'chirildi.")
        return

    # ── Guruh egasi: pauza ───────────────────────────────────────────────
    if data.startswith("opause:"):
        _, group_id_s, val_s = data.split(":")
        group_id = int(group_id_s)
        group = await db.get_group(group_id)
        # Faqat o'z guruhi (yoki super admin)
        if not group or (group.get("owner_uid") != uid and not is_super(uid)):
            await q.edit_message_text("⚠️ Bu sizning guruhingiz emas.")
            return
        await db.set_group_paused(group_id, val_s == "1")
        await q.edit_message_text(
            "⏸ Guruh to'xtatildi." if val_s == "1" else "▶️ Guruh qayta yoqildi."
        )
        return

    # ── E'lon boshqaruvi (foydalanuvchi) ─────────────────────────────────
    if data == "adnew":
        ads_count = await db.count_ads(uid)
        if ads_count >= MAX_ADS_PER_USER:
            await q.edit_message_text(f"❌ Maksimal {MAX_ADS_PER_USER} ta e'lon.")
            return
        user_states[uid] = {"step": "add_ad"}
        await q.edit_message_text("✍️ E'lon yuboring (matn yoki rasm+matn):")
        return

    if data.startswith("adact:"):
        ad_id = int(data.split(":")[1])
        ad = await db.get_ad(ad_id)
        if ad and ad.get("uid") == uid:
            await db.set_active_ad(uid, ad_id)
            await q.edit_message_text("✅ Bu e'lon faol qilindi.")
        return

    if data.startswith("aded:"):
        ad_id = int(data.split(":")[1])
        ad = await db.get_ad(ad_id)
        if ad and ad.get("uid") == uid:
            user_states[uid] = {"step": "edit_ad", "edit_ad_id": ad_id}
            await q.edit_message_text("✏️ Yangi mazmunni yuboring (matn yoki rasm):")
        return

    if data.startswith("addel:"):
        ad_id = int(data.split(":")[1])
        ad = await db.get_ad(ad_id)
        if ad and ad.get("uid") == uid:
            _safe_unlink(ad.get("photo_path"))
            await db.delete_ad(ad_id)
            # Agar faol e'lon o'chirilsa — faolni tozalaymiz
            user = await db.get_user(uid)
            if (user or {}).get("active_ad_id") == ad_id:
                await db.set_active_ad(uid, None)
                await db.set_running(uid, False)
            await q.edit_message_text("🗑 E'lon o'chirildi.")
        return

    # ── Viloyat tanlash (foydalanuvchi) ──────────────────────────────────
    if data.startswith("rsel:"):
        region_id = int(data.split(":")[1])
        region = await db.get_region(region_id)
        if not region:
            await q.edit_message_text("⚠️ Viloyat topilmadi.")
            return
        await db.set_selected_region(uid, region_id)
        cnt = await db.count_groups_in_region(region_id)
        await q.edit_message_text(f"✅ Viloyat tanlandi: {region['name']} ({cnt} guruh)")
        return

    # ── Logout ───────────────────────────────────────────────────────────
    if data == "lo:yes":
        await db.set_running(uid, False)
        await q.edit_message_text("🚪 Chiqdingiz. E'lon yuborish to'xtatildi.")
        with contextlib.suppress(Exception):
            await context.bot.send_message(uid, "🏠 Bosh menyu", reply_markup=await menu_for(uid))
        return
    if data == "lo:no":
        await q.edit_message_text("✅ Bekor qilindi.")
        return


# ═════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════
async def _post_init(app: Application) -> None:
    """Bot ishga tushgach: baza, super admin, scheduler."""
    global scheduler
    await db.init_db()
    await db.upsert_user(SUPER_ADMIN, is_approved=1)
    scheduler = Scheduler(app.bot)
    scheduler.start()
    logger.info("POSTCHI_BOT tayyor")


async def _post_shutdown(app: Application) -> None:
    if scheduler:
        await scheduler.stop()
    await db.close_db()
    logger.info("POSTCHI_BOT to'xtadi")


def main() -> None:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    global application
    application = app

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.CONTACT) & ~filters.COMMAND,
            on_message,
        )
    )
    app.add_error_handler(on_error)

    logger.info("POSTCHI_BOT ishga tushmoqda...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
