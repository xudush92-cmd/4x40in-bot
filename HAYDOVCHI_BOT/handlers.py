"""
handlers.py — bot buyruqlari, tugmalar, ro'yxatdan o'tish, boshqaruv paneli, guruh xabarlari.

Rollar:
- Super admin (ADMIN_ID) — yagona boshqaruvchi. Guruhlarni, yo'nalishlarni, haydovchilarni,
  e'lonlarni va sozlamalarni har guruh uchun alohida boshqaradi.
  Admin haydovchi ism/telefonini o'zgartira olmaydi.
- Haydovchi — ro'yxatdan o'tadi, admin tasdiqlab guruhga biriktiradi, muddatni admin belgilaydi.
  Ism va telefonini faqat o'zi tahrirlaydi. O'z guruhining yo'nalishlarida e'lon beradi.
- Yo'lovchi — botdan foydalanmaydi; faqat guruh oynasidagi "🚕 Taksi chaqirish" tugmasini bosadi.
"""

from __future__ import annotations

import logging
import time

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ChatType
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from board import BoardManager
from config import ADMIN_ID
from db import ts_to_date_str
from taxi import MUTE_CALLBACK, mute_driver, passenger_request
from utils import SEAT_OPTIONS, normalize_phone, parse_route, seats_label

log = logging.getLogger("haydovchi.handlers")

# ── tugma matnlari ───────────────────────────────────────────────────────
BTN_START = "🟢 Ishni boshlash"
BTN_STOP = "🔴 To'xtatish"
BTN_MY = "📋 Mening holatim"
BTN_PROFILE = "✏️ Ma'lumotlarim"
BTN_CONTACT = "📱 Raqamni yuborish"
BTN_CANCEL = "❌ Bekor qilish"

A_GROUPS = "🏘 Guruhlar"
A_DRIVERS = "👥 Haydovchilar"
A_ROUTES = "🛣 Yo'nalishlar"
A_SETTINGS = "⚙️ Sozlamalar"
A_REFRESH = "📢 Oynani yangilash"
A_STATS = "📊 Statistika"

MENU_BUTTONS = {BTN_START, BTN_STOP, BTN_MY, BTN_PROFILE,
                A_GROUPS, A_DRIVERS, A_ROUTES, A_SETTINGS, A_REFRESH, A_STATS}

AUTO_STOP_CHOICES = [1, 2, 3, 4]     # soat
REPOST_CHOICES = [3, 5, 10]          # yangi xabar soni
MAX_SUB_DAYS = 365

STATUS_LABEL = {
    "pending": "⏳ kutilmoqda",
    "approved": "🟢 faol",
    "paused": "⏸ to'xtatilgan",
    "blocked": "⛔ bloklangan",
}


def driver_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[BTN_START, BTN_STOP], [BTN_MY, BTN_PROFILE]], resize_keyboard=True)


def admin_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[A_GROUPS, A_DRIVERS], [A_ROUTES, A_SETTINGS], [A_REFRESH, A_STATS]],
        resize_keyboard=True,
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[BTN_CANCEL]], resize_keyboard=True)


def contact_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(BTN_CONTACT, request_contact=True)], [BTN_CANCEL]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# ── yordamchilar ─────────────────────────────────────────────────────────
def _db(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["db"]


def _hub(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["hub"]


async def is_manager(context, uid: int) -> bool:
    """Boshqaruv faqat super admin (ADMIN_ID) uchun."""
    return uid == ADMIN_ID


async def _safe_edit(query, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await query.edit_message_text(text, reply_markup=markup)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            log.warning("Xabarni tahrirlab bo'lmadi: %s", e)


async def _notify(context, uid: int, text: str, markup=None) -> None:
    try:
        await context.bot.send_message(chat_id=uid, text=text, reply_markup=markup)
    except TelegramError as e:
        log.info("Xabar yuborib bo'lmadi (%s): %s", uid, e)


def _sub_status(paid_until: int) -> str:
    if not paid_until:
        return "❌ muddat belgilanmagan"
    if paid_until < int(time.time()):
        return f"⛔ muddat tugagan ({ts_to_date_str(paid_until)})"
    return f"✅ {ts_to_date_str(paid_until)} gacha"


def _subscribed(user) -> bool:
    return user.paid_until > int(time.time())


def _clear_await(context) -> None:
    context.user_data.pop("await", None)


async def _group_title(db, group_id: int | None) -> str:
    if not group_id:
        return "biriktirilmagan"
    g = await db.get_group(group_id)
    return (g["title"] or str(group_id)) if g else "o'chirilgan guruh"


# ══════════════════════════════════════════════════════════════════════════
# /start va ro'yxatdan o'tish
# ══════════════════════════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    _clear_await(context)
    uid = update.effective_user.id
    if await is_manager(context, uid):
        await update.effective_message.reply_text(
            "🛠 Boshqaruv paneli. Kerakli bo'limni tanlang.", reply_markup=admin_menu_kb()
        )
        return
    await _db(context).ensure_user(uid)
    await _advance(update, context, uid)


async def _advance(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int) -> None:
    db = _db(context)
    msg = update.effective_message
    user = await db.get_user(uid)
    if user is None:
        await db.ensure_user(uid)
        user = await db.get_user(uid)

    if user.status == "blocked":
        await msg.reply_text("⛔ Sizning huquqingiz cheklangan. Admin bilan bog'laning.",
                             reply_markup=ReplyKeyboardRemove())
        return
    if user.status == "paused":
        await msg.reply_text("⏸ Admin sizni vaqtincha to'xtatib qo'ygan. Admin bilan bog'laning.",
                             reply_markup=ReplyKeyboardRemove())
        return
    if user.status == "pending":
        await msg.reply_text("⏳ Arizangiz ko'rib chiqilmoqda. Tasdiqlangach xabar beramiz.",
                             reply_markup=ReplyKeyboardRemove())
        return
    if user.status == "approved":
        await msg.reply_text("🚗 Haydovchi paneli", reply_markup=driver_menu_kb())
        return

    if not user.first_name:
        await msg.reply_text("👋 Xush kelibsiz! Avval ismingizni yozing:",
                             reply_markup=ReplyKeyboardRemove())
    elif not user.last_name:
        await msg.reply_text("Familiyangizni yozing:", reply_markup=ReplyKeyboardRemove())
    elif not user.phone:
        await msg.reply_text(
            "📱 Telefon raqamingizni yuboring (pastdagi tugma yoki raqamni yozish orqali).",
            reply_markup=contact_kb(),
        )
    else:
        await _submit_application(update, context, user)


async def _submit_application(update: Update, context, user) -> None:
    db = _db(context)
    await db.update_user_fields(user.tg_id, status="pending")
    await update.effective_message.reply_text(
        "✅ Arizangiz yuborildi. Admin tasdiqlagach xabar beramiz.",
        reply_markup=ReplyKeyboardRemove(),
    )
    text = (
        "🆕 Yangi haydovchi arizasi\n\n"
        f"👤 {user.first_name} {user.last_name}\n"
        f"📞 {user.phone}\n"
        f"🆔 {user.tg_id}"
    )
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"dok:{user.tg_id}"),
        InlineKeyboardButton("❌ Rad etish", callback_data=f"dno:{user.tg_id}"),
    ]])
    await _notify(context, ADMIN_ID, text, markup)


# ══════════════════════════════════════════════════════════════════════════
# Shaxsiy chatdagi kontakt, matn va bekor qilish
# ══════════════════════════════════════════════════════════════════════════
async def on_private_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    contact = update.effective_message.contact
    uid = update.effective_user.id
    if contact.user_id != uid:
        await update.effective_message.reply_text("Iltimos, o'zingizning raqamingizni yuboring.")
        return
    phone = normalize_phone(contact.phone_number)
    if not phone:
        await update.effective_message.reply_text("Raqam noto'g'ri. Qaytadan urinib ko'ring.")
        return
    db = _db(context)
    await db.ensure_user(uid)
    user = await db.get_user(uid)

    pending = context.user_data.get("await")
    if pending and pending[0] == "edit_phone" and user.status == "approved":
        _clear_await(context)
        await db.update_user_fields(uid, phone=phone)
        _hub(context).mark_all_dirty()
        await update.effective_message.reply_text(
            f"✅ Telefon saqlandi: {phone}", reply_markup=driver_menu_kb())
        return

    await db.update_user_fields(uid, phone=phone)
    await _advance(update, context, uid)


async def _cancel(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int) -> None:
    _clear_await(context)
    msg = update.effective_message
    if await is_manager(context, uid):
        await msg.reply_text("❌ Bekor qilindi.", reply_markup=admin_menu_kb())
        return
    user = await _db(context).get_user(uid)
    if user and user.status == "approved":
        await msg.reply_text("❌ Bekor qilindi.", reply_markup=driver_menu_kb())
        return
    await _advance(update, context, uid)


async def on_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    text = (update.effective_message.text or "").strip()

    if text == BTN_CANCEL:
        await _cancel(update, context, uid)
        return
    if text in MENU_BUTTONS:
        _clear_await(context)  # kutilayotgan kiritish bekor qilinadi, menyu ishlaydi

    if await is_manager(context, uid):
        await _manager_text(update, context, text)
        return

    db = _db(context)
    await db.ensure_user(uid)
    user = await db.get_user(uid)

    if user.status == "approved":
        pending = context.user_data.get("await")
        if pending and pending[0] in ("edit_first", "edit_last"):
            await _save_name(update, context, uid, pending[0], text)
            return
        await _driver_text(update, context, uid, text)
        return

    if user.status in ("new", ""):
        if not user.first_name:
            if len(text) < 2:
                await update.effective_message.reply_text("Ismingizni to'liqroq yozing:")
                return
            await db.update_user_fields(uid, first_name=text)
        elif not user.last_name:
            if len(text) < 2:
                await update.effective_message.reply_text("Familiyangizni to'liqroq yozing:")
                return
            await db.update_user_fields(uid, last_name=text)
        elif not user.phone:
            phone = normalize_phone(text)
            if not phone:
                await update.effective_message.reply_text(
                    "Raqam noto'g'ri. Masalan: +998901234567 yoki 901234567"
                )
                return
            await db.update_user_fields(uid, phone=phone)
        await _advance(update, context, uid)
        return

    await _advance(update, context, uid)


async def _save_name(update, context, uid: int, which: str, text: str) -> None:
    if len(text) < 2:
        await update.effective_message.reply_text("Juda qisqa. Qaytadan yozing yoki ❌ Bekor qilish.")
        return
    _clear_await(context)
    field = "first_name" if which == "edit_first" else "last_name"
    await _db(context).update_user_fields(uid, **{field: text})
    _hub(context).mark_all_dirty()
    await update.effective_message.reply_text("✅ Saqlandi.", reply_markup=driver_menu_kb())


# ══════════════════════════════════════════════════════════════════════════
# Haydovchi paneli
# ══════════════════════════════════════════════════════════════════════════
async def _driver_text(update, context, uid: int, text: str) -> None:
    db = _db(context)
    msg = update.effective_message
    user = await db.get_user(uid)

    if text == BTN_START:
        if not _subscribed(user):
            await msg.reply_text(
                f"⛔ Muddat tugagan yoki belgilanmagan.\n📅 {_sub_status(user.paid_until)}\n"
                "Muddatni admin belgilaydi. Admin bilan bog'laning."
            )
            return
        if not user.group_id:
            await msg.reply_text("Sizga guruh biriktirilmagan. Admin bilan bog'laning.")
            return
        routes = [r for r in await db.list_routes(user.group_id) if r["is_open"]]
        if not routes:
            await msg.reply_text("Bu guruhda hozircha ochiq yo'nalish yo'q. Admin yo'nalish ochishini kuting.")
            return
        rows = [[InlineKeyboardButton(f"📍 {r['from_place']} → {r['to_place']}",
                                      callback_data=f"rt:{r['id']}")] for r in routes]
        await msg.reply_text(
            "Yo'nalishni tanlang. Bir vaqtda faqat bitta yo'nalishda e'lon bo'ladi:",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if text == BTN_STOP:
        entries = await db.driver_entries(uid)
        if not entries:
            await msg.reply_text("Sizda faol e'lon yo'q.")
            return
        rows = [[InlineKeyboardButton(f"🔴 {e['from_place']} → {e['to_place']}",
                                      callback_data=f"st:{e['id']}")] for e in entries]
        await msg.reply_text("To'xtatmoqchi bo'lgan yo'nalishingizni tanlang:",
                             reply_markup=InlineKeyboardMarkup(rows))
        return

    if text == BTN_MY:
        body, markup = await _my_entries_view(db, uid)
        await msg.reply_text(body, reply_markup=markup)
        return

    if text == BTN_PROFILE:
        body, markup = await _profile_view(db, uid)
        await msg.reply_text(body, reply_markup=markup)
        return

    await msg.reply_text("🚗 Haydovchi paneli", reply_markup=driver_menu_kb())


async def _my_entries_view(db, uid: int) -> tuple[str, InlineKeyboardMarkup]:
    entries = await db.driver_entries(uid)
    back = [InlineKeyboardButton("⬅️ Orqaga", callback_data="back")]
    if not entries:
        return ("Sizda faol e'lon yo'q. 🟢 Ishni boshlash tugmasini bosing.",
                InlineKeyboardMarkup([back]))
    rows = []
    lines = ["📋 Hozirgi holatingiz:"]
    for e in entries:
        lines.append(f"📍 {e['from_place']} → {e['to_place']}: {seats_label(e['seats'])}")
        rows.append([
            InlineKeyboardButton("➖", callback_data=f"ea:{e['id']}:-1"),
            InlineKeyboardButton("➕", callback_data=f"ea:{e['id']}:1"),
            InlineKeyboardButton("🔢", callback_data=f"ee:{e['id']}"),
            InlineKeyboardButton("🔴", callback_data=f"st:{e['id']}"),
        ])
    rows.append(back)
    lines.append("\n➖ odam oldi · ➕ joy bo'shadi · 🔢 aniq son · 🔴 to'xtatish")
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _profile_view(db, uid: int) -> tuple[str, InlineKeyboardMarkup]:
    user = await db.get_user(uid)
    entries = await db.driver_entries(uid)
    taxi = "🟢 olinadi" if user.taxi_on else "🔕 o'chirilgan"
    text = (
        "✏️ Ma'lumotlaringiz\n\n"
        f"👤 Ism: {user.first_name}\n"
        f"👤 Familiya: {user.last_name}\n"
        f"📞 Telefon: {user.phone}\n"
        f"🏘 Guruh: {await _group_title(db, user.group_id)}\n"
        f"📅 Muddat: {_sub_status(user.paid_until)}\n"
        f"🚕 Taksi so'rovlari: {taxi}\n"
        f"🟢 Faol e'lon: {len(entries)} ta\n\n"
        "O'zgartirish uchun tugmani bosing:"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Ismni o'zgartirish", callback_data="pe:first")],
        [InlineKeyboardButton("✏️ Familiyani o'zgartirish", callback_data="pe:last")],
        [InlineKeyboardButton("📱 Telefonni o'zgartirish", callback_data="pe:phone")],
        [InlineKeyboardButton(
            "🔕 Taksi so'rovlarini o'chirish" if user.taxi_on else "🟢 Taksi so'rovlarini yoqish",
            callback_data="tq")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="back")],
    ])
    return text, markup


# ══════════════════════════════════════════════════════════════════════════
# Boshqaruv paneli (faqat super admin)
# ══════════════════════════════════════════════════════════════════════════
async def _manager_text(update, context, text: str) -> None:
    db = _db(context)
    msg = update.effective_message
    pending = context.user_data.get("await")

    if pending and pending[0] == "route":
        _clear_await(context)
        group_id = pending[1]
        added, bad = [], []
        for line in text.splitlines():
            if not line.strip():
                continue
            parsed = parse_route(line)
            if parsed:
                await db.add_route(group_id, parsed[0], parsed[1])
                added.append(f"{parsed[0]} → {parsed[1]}")
            else:
                bad.append(line.strip())
        out = []
        if added:
            out.append("✅ Qo'shildi:\n" + "\n".join(f"• {a}" for a in added))
            _hub(context).mark_all_dirty()
        if bad:
            out.append("⚠️ Tushunilmadi (format: Toshkent - Qibray):\n" + "\n".join(bad))
        await msg.reply_text("\n\n".join(out) or "Hech narsa qo'shilmadi.")
        body, markup = await _routes_view(db, group_id)
        await msg.reply_text(body, reply_markup=markup)
        return

    if pending and pending[0] == "group":
        _clear_await(context)
        await _add_group_from_message(update, context)
        return

    if pending and pending[0] == "sub":
        uid = pending[1]
        if not text.isdigit() or not (1 <= int(text) <= MAX_SUB_DAYS):
            await msg.reply_text(f"Faqat raqam kiriting, 1 dan {MAX_SUB_DAYS} gacha. Masalan: 30",
                                 reply_markup=cancel_kb())
            return
        _clear_await(context)
        days = int(text)
        until = await db.set_subscription_days(uid, days)
        user = await db.get_user(uid)
        await _notify(context, uid,
                      f"📅 Muddat belgilandi: {ts_to_date_str(until)} gacha ({days} kun). "
                      "Eski muddat bekor qilindi.")
        _hub(context).mark_all_dirty()
        await msg.reply_text(f"✅ {user.full_name}: {days} kun, {ts_to_date_str(until)} gacha.",
                             reply_markup=admin_menu_kb())
        body, markup = await _driver_detail(db, uid)
        await msg.reply_text(body, reply_markup=markup)
        return

    if text == A_GROUPS:
        body, markup = await _groups_list_view(db)
        await msg.reply_text(body, reply_markup=markup)
    elif text == A_ROUTES:
        body, markup = await _group_picker(db, "gr", "🛣 Qaysi guruh yo'nalishlari?")
        await msg.reply_text(body, reply_markup=markup)
    elif text == A_SETTINGS:
        body, markup = await _group_picker(db, "gs", "⚙️ Qaysi guruh sozlamalari?")
        await msg.reply_text(body, reply_markup=markup)
    elif text == A_REFRESH:
        await _hub(context).force_all()
        await msg.reply_text("✅ Barcha guruh oynalari pastga qayta yuborildi.")
    elif text == A_DRIVERS:
        body, markup = await _drivers_overview(db)
        await msg.reply_text(body, reply_markup=markup)
    elif text == A_STATS:
        await msg.reply_text(await _stats_text(db))
    else:
        await msg.reply_text("🛠 Boshqaruv paneli", reply_markup=admin_menu_kb())


# ── Guruh tanlash (yo'nalish / sozlama bo'limlari uchun) ──────────────
async def _group_picker(db, prefix: str, title: str) -> tuple[str, InlineKeyboardMarkup]:
    groups = await db.list_groups()
    if not groups:
        return ("Avval guruh qo'shing (🏘 Guruhlar).",
                InlineKeyboardMarkup([[InlineKeyboardButton("🏘 Guruhlar", callback_data="gl")]]))
    rows = []
    for i, g in enumerate(groups, start=1):
        label = f"{i}. {(g['title'] or str(g['chat_id']))[:28]}"
        rows.append([InlineKeyboardButton(label, callback_data=f"{prefix}:{g['chat_id']}")])
    return title, InlineKeyboardMarkup(rows)


# ── Guruhlar ro'yxati va guruh menyusi ─────────────────────────────────
async def _groups_list_view(db) -> tuple[str, InlineKeyboardMarkup]:
    groups = await db.list_groups()
    rows = []
    lines = ["🏘 Guruhlar:"]
    if not groups:
        lines.append("Hozircha guruh yo'q.")
    for i, g in enumerate(groups, start=1):
        title = (g["title"] or str(g["chat_id"]))[:28]
        state = "⏸" if g["paused"] else "🟢"
        rows.append([InlineKeyboardButton(f"{state} {i}. {title}", callback_data=f"g:{g['chat_id']}")])
    rows.append([InlineKeyboardButton("➕ Yangi guruh", callback_data="gadd")])
    rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="back")])
    lines.append(
        "\nHar guruhning yo'nalishlari, haydovchilari, e'lonlari va sozlamalari alohida.\n"
        "Yangi guruh: Telegram botlar guruh yarata olmaydi. Avval Telegram'da guruh oching, "
        "botni admin qiling (xabarlarni o'chirish huquqi bilan), so'ng ➕ tugmasini bosing."
    )
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _group_menu_view(db, hub, chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    g = await db.get_group(chat_id)
    if g is None:
        return "Bu guruh topilmadi.", InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Guruhlar", callback_data="gl")]])
    routes = await db.list_routes(chat_id)
    drivers = await db.group_drivers(chat_id)
    approved = sum(1 for d in drivers if d.status == "approved")
    active = await db.active_entry_count(chat_id)
    board: BoardManager | None = hub.get(chat_id)
    last_ts = (await board.last_update_info())[0] if board else 0
    last_txt = time.strftime("%d.%m %H:%M", time.localtime(last_ts)) if last_ts else "hali yo'q"
    state_txt = "⏸ to'xtatilgan" if g["paused"] else "🟢 faol"
    taxi_txt = "yoqilgan" if g["taxi_enabled"] else "o'chirilgan"
    text = (
        f"🏘 {g['title'] or chat_id}\n"
        f"Holat: {state_txt}\n"
        f"🛣 Yo'nalishlar: {len(routes)} ta\n"
        f"👥 Haydovchilar: {approved} ta faol\n"
        f"📢 Faol e'lonlar: {active} ta\n"
        f"🚕 Taksi tugmasi: {taxi_txt}\n"
        f"⏰ Avto-to'xtash: {g['auto_stop_hours']} soat · 📌 pastga tushish: {g['repost_after_msgs']} xabar\n"
        f"🕐 Oxirgi yangilanish: {last_txt}"
    )
    rows = [
        [InlineKeyboardButton("🛣 Yo'nalishlar", callback_data=f"gr:{chat_id}"),
         InlineKeyboardButton("👥 Haydovchilar", callback_data=f"gd:{chat_id}")],
        [InlineKeyboardButton("📢 E'lonlar", callback_data=f"ge:{chat_id}"),
         InlineKeyboardButton("⚙️ Sozlamalar", callback_data=f"gs:{chat_id}")],
        [InlineKeyboardButton("🚕 Taksi: " + ("o'chirish" if g["taxi_enabled"] else "yoqish"),
                              callback_data=f"gtx:{chat_id}"),
         InlineKeyboardButton("🔄 Oynani yangilash", callback_data=f"gref:{chat_id}")],
        [InlineKeyboardButton("▶️ Davom ettirish" if g["paused"] else "⏸ Avtomatikni to'xtatish",
                              callback_data=f"gpz:{chat_id}")],
        [InlineKeyboardButton("🗑 Guruhni olib tashlash", callback_data=f"grm:{chat_id}")],
        [InlineKeyboardButton("⬅️ Guruhlar", callback_data="gl")],
    ]
    return text, InlineKeyboardMarkup(rows)


async def _routes_view(db, chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    routes = await db.list_routes(chat_id)
    rows = []
    lines = ["🛣 Yo'nalishlar:"]
    if not routes:
        lines.append("Hozircha yo'nalish yo'q.")
    for r in routes:
        state = "🟢 ochiq" if r["is_open"] else "⛔ yopiq"
        lines.append(f"• {r['from_place']} → {r['to_place']} ({state})")
        rows.append([
            InlineKeyboardButton("⛔ Yopish" if r["is_open"] else "🟢 Ochish",
                                 callback_data=f"grt:{r['id']}"),
            InlineKeyboardButton("🗑 O'chirish", callback_data=f"grd:{r['id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ Yangi yo'nalish", callback_data=f"gra:{chat_id}")])
    rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data=f"g:{chat_id}")])
    lines.append("\nYangi yo'nalish: har qatorga bitta, masalan \"Toshkent - Qibray\".")
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _group_drivers_view(db, chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    drivers = await db.group_drivers(chat_id)
    title = await _group_title(db, chat_id)
    rows = []
    lines = [f"👥 {title} haydovchilari: {len(drivers)} ta"]
    if not drivers:
        lines.append("Hozircha haydovchi yo'q. Yangi arizalar 👥 Haydovchilar bo'limida.")
    for u in drivers[:30]:
        label = (u.full_name or str(u.tg_id))[:24]
        rows.append([InlineKeyboardButton(f"{label} · {STATUS_LABEL.get(u.status, u.status)}",
                                          callback_data=f"dv:{u.tg_id}")])
    rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data=f"g:{chat_id}")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _group_entries_view(db, chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    entries = await db.group_active_entries(chat_id)
    title = await _group_title(db, chat_id)
    lines = [f"📢 {title} — faol e'lonlar: {len(entries)} ta"]
    for e in entries:
        lines.append(f"• {e['first_name']} {e['last_name']} · {e['from_place']} → {e['to_place']} · "
                     f"{seats_label(e['seats'])}")
    if not entries:
        lines.append("Hozir faol e'lon yo'q.")
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data=f"g:{chat_id}")]])
    return "\n".join(lines), markup


async def _group_settings_view(db, chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    g = await db.get_group(chat_id)
    text = (
        f"⚙️ {g['title'] or chat_id} sozlamalari\n\n"
        f"⏰ Avtomatik to'xtash: {g['auto_stop_hours']} soat (yangilanmagan e'lon)\n"
        f"📌 Oyna pastga tushishi: {g['repost_after_msgs']} ta yangi xabardan keyin\n"
        "\nTanlang:"
    )
    rows = [
        [InlineKeyboardButton(("✔ " if h == g["auto_stop_hours"] else "") + f"{h} soat",
                              callback_data=f"gsa:{chat_id}:{h}") for h in AUTO_STOP_CHOICES],
        [InlineKeyboardButton(("✔ " if n == g["repost_after_msgs"] else "") + f"{n} xabar",
                              callback_data=f"gsb:{chat_id}:{n}") for n in REPOST_CHOICES],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data=f"g:{chat_id}")],
    ]
    return text, InlineKeyboardMarkup(rows)


async def _add_group_from_message(update, context) -> None:
    db = _db(context)
    hub = _hub(context)
    msg = update.effective_message
    chat_id = _forwarded_chat_id(msg)
    if chat_id is None:
        try:
            chat_id = int((msg.text or "").strip())
        except ValueError:
            context.user_data["await"] = ("group",)
            await msg.reply_text("Guruh ID si noto'g'ri. Guruhdan xabar forward qiling yoki "
                                 "-100 bilan boshlanadigan raqamni yozing.",
                                 reply_markup=cancel_kb())
            return
    if chat_id >= 0:
        await msg.reply_text("Bu guruh emas. Guruh ID si manfiy raqam bo'ladi (-100...).")
        return
    if chat_id in hub.boards:
        await msg.reply_text("Bu guruh allaqachon qo'shilgan.")
        return

    bot_user = await context.bot.get_me()
    try:
        chat = await context.bot.get_chat(chat_id)
        me = await context.bot.get_chat_member(chat_id, bot_user.id)
    except TelegramError as e:
        await msg.reply_text(f"⚠️ Guruhga kirib bo'lmadi. Bot guruhda borligini tekshiring.\n({e})")
        return
    if me.status not in ("administrator", "creator"):
        await msg.reply_text("⚠️ Bot bu guruhda admin emas. Avval botni admin qiling "
                             "(xabarlarni o'chirish huquqi bilan), keyin qayta urinib ko'ring.")
        return

    await db.add_group(chat_id, chat.title or "")
    board = BoardManager(context.bot, db, chat_id, bot_user.username)
    hub.add(board)
    await board.sync()  # darhol chiqadi
    await msg.reply_text(f"✅ Guruh qo'shildi: {chat.title or chat_id}. Oyna shu yerda chiqdi.")
    body, markup = await _groups_list_view(db)
    await msg.reply_text(body, reply_markup=markup)


def _forwarded_chat_id(msg) -> int | None:
    origin = getattr(msg, "forward_origin", None)
    chat = getattr(origin, "chat", None)
    if chat is not None:
        return chat.id
    fwd = getattr(msg, "forward_from_chat", None)  # eski PTB ko'rinishi
    return fwd.id if fwd else None


# ── Haydovchilar (global ro'yxat) ──────────────────────────────────────
async def _drivers_overview(db) -> tuple[str, InlineKeyboardMarkup]:
    pending = await db.users_by_status("pending")
    others = []
    for st in ("approved", "paused", "blocked"):
        others += await db.users_by_status(st)
    rows = []
    lines = [f"⏳ Kutilayotgan arizalar: {len(pending)} ta"]
    for u in pending[:15]:
        rows.append([InlineKeyboardButton(f"⏳ {(u.full_name or str(u.tg_id))[:24]}",
                                          callback_data=f"dv:{u.tg_id}")])
    lines.append(f"\n👥 Barcha haydovchilar: {len(others)} ta")
    for u in others[:25]:
        label = (u.full_name or str(u.tg_id))[:20]
        g = await _group_title(db, u.group_id)
        rows.append([InlineKeyboardButton(f"{label} · {g[:12]} · {STATUS_LABEL.get(u.status, u.status)}",
                                          callback_data=f"dv:{u.tg_id}")])
    rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="back")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _driver_detail(db, uid: int) -> tuple[str, InlineKeyboardMarkup]:
    user = await db.get_user(uid)
    entries = await db.driver_entries(uid)
    route_txt = (f"{entries[0]['from_place']} → {entries[0]['to_place']}" if entries else "yo'q")
    group_title = await _group_title(db, user.group_id)
    taxi_txt = "yoqilgan" if user.taxi_on else "o'chirilgan"
    text = (
        f"👤 {user.full_name}\n"
        f"📞 {user.phone}\n"
        f"🏘 Guruh: {group_title}\n"
        f"Holat: {STATUS_LABEL.get(user.status, user.status)}\n"
        f"📅 Muddat: {_sub_status(user.paid_until)}\n"
        f"🚕 Taksi so'rovlari: {taxi_txt}\n"
        f"📍 Faol e'lon: {route_txt}"
    )
    back = f"gd:{user.group_id}" if user.group_id else "back"
    rows = []
    if user.status == "pending":
        rows.append([
            InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"dok:{uid}"),
            InlineKeyboardButton("❌ Rad etish", callback_data=f"dno:{uid}"),
        ])
    else:
        rows.append([InlineKeyboardButton("🔀 Guruhni o'zgartirish", callback_data=f"dgp:{uid}")])
        rows.append([InlineKeyboardButton("📅 Muddat berish (kun)", callback_data=f"dsub:{uid}")])
        if user.status == "approved":
            rows.append([InlineKeyboardButton("⏸ Vaqtincha to'xtatib qo'yish", callback_data=f"dpz:{uid}")])
        elif user.status == "paused":
            rows.append([InlineKeyboardButton("▶️ Ishga tushirish", callback_data=f"dpz:{uid}")])
        if user.status == "blocked":
            rows.append([InlineKeyboardButton("🔓 Qayta tiklash", callback_data=f"dunb:{uid}")])
        else:
            rows.append([InlineKeyboardButton("🚫 Bloklash", callback_data=f"dblk:{uid}")])
    rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data=back)])
    return text, InlineKeyboardMarkup(rows)


async def _group_picker_view(db, uid: int) -> tuple[str, InlineKeyboardMarkup]:
    groups = await db.list_groups()
    rows = []
    for i, g in enumerate(groups, start=1):
        rows.append([InlineKeyboardButton(f"{i}. {(g['title'] or str(g['chat_id']))[:28]}",
                                          callback_data=f"dgo:{uid}:{g['chat_id']}")])
    rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data=f"dv:{uid}")])
    if not groups:
        return "Avval guruh qo'shing (🏘 Guruhlar).", InlineKeyboardMarkup(rows)
    return "Haydovchi qaysi guruhga biriktirilsin?", InlineKeyboardMarkup(rows)


# ── Sozlamalar / statistika ────────────────────────────────────────────
async def _stats_text(db) -> str:
    counts = await db.count_users_by_status()
    groups = await db.list_groups()
    active = await db.active_entry_count()
    paused = sum(1 for g in groups if g["paused"])
    lines = [
        "📊 Statistika\n",
        f"✅ Faol haydovchilar: {counts.get('approved', 0)}",
        f"⏸ To'xtatilgan: {counts.get('paused', 0)}",
        f"⏳ Kutilayotgan arizalar: {counts.get('pending', 0)}",
        f"⛔ Bloklangan: {counts.get('blocked', 0)}",
        f"🟢 Jami faol e'lonlar: {active}",
        f"🚕 Taksi so'rovlari (jami): {await db.taxi_requests_count()}",
        f"🏘 Guruhlar: {len(groups)} ta (to'xtatilgan: {paused})",
        "",
    ]
    for i, g in enumerate(groups, start=1):
        routes = await db.list_routes(g["chat_id"])
        lines.append(f"{i}. {g['title'] or g['chat_id']}: {len(routes)} yo'nalish, "
                     f"{await db.active_entry_count(g['chat_id'])} faol e'lon, "
                     f"{await db.taxi_requests_count(g['chat_id'])} taksi so'rovi")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# Inline tugmalar (callback)
# ══════════════════════════════════════════════════════════════════════════
MANAGER_ACTIONS = {
    "gl", "g", "gadd", "gr", "gra", "grt", "grd", "grdy", "gd", "ge", "gtx", "gs", "gsa", "gsb",
    "gref", "gpz", "grm", "grmy",
    "dl", "dv", "dok", "dno", "dgp", "dgo", "dsub", "dpz", "dblk", "dblky", "dunb",
}


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    parts = (query.data or "").split(":")
    action = parts[0]
    db = _db(context)

    # Yo'lovchi: guruh oynasidagi "Taksi chaqirish" (auth shart emas)
    if action == "tx":
        try:
            text = await passenger_request(context.bot, db, query.message.chat_id, query.from_user)
        except Exception:
            log.exception("Taksi so'rovida xato")
            text = "Xatolik yuz berdi. Keyinroq urinib ko'ring."
        await query.answer(text, show_alert=True)
        return

    # Haydovchi: taksi so'rovini to'xtatish (xabar ostidagi tugma)
    if action == MUTE_CALLBACK:
        await mute_driver(db, uid)
        await query.answer("🔕 Taksi so'rovlari to'xtatildi")
        base = query.message.text or ""
        await _safe_edit(query, base + "\n\n🔕 Taksi so'rovlari to'xtatildi. "
                         "Qayta yoqish: ✏️ Ma'lumotlarim → 🚕 Taksi so'rovlari.", None)
        return

    if action == "back":
        await query.answer()
        await _safe_edit(query, "⬅️ Asosiy menyu. Kerakli bo'limni tanlang.", None)
        return

    if action in MANAGER_ACTIONS:
        if not await is_manager(context, uid):
            await query.answer("Bu amal faqat admin uchun.", show_alert=True)
            return
        await query.answer()
        await _manager_callback(query, context, action, parts)
        return

    user = await db.get_user(uid)
    if user and user.status == "paused":
        await query.answer("Sizning huquqingiz vaqtincha to'xtatilgan.", show_alert=True)
        return
    if not user or user.status != "approved":
        await query.answer("Sizda haydovchi huquqi yo'q.", show_alert=True)
        return
    await query.answer()
    await _driver_callback(query, context, uid, action, parts)


async def _manager_callback(query, context, action: str, parts: list[str]) -> None:
    db = _db(context)
    hub = _hub(context)
    msg = query.message

    # ── guruhlar ──
    if action == "gl":
        body, markup = await _groups_list_view(db)
        await _safe_edit(query, body, markup)
        return
    if action == "g":
        body, markup = await _group_menu_view(db, hub, int(parts[1]))
        await _safe_edit(query, body, markup)
        return
    if action == "gadd":
        context.user_data["await"] = ("group",)
        await msg.reply_text(
            "Guruhdan bitta xabarni shu botga forward qiling, yoki guruh ID sini yozing (-100...).",
            reply_markup=cancel_kb(),
        )
        return
    if action == "gtx":
        chat_id = int(parts[1])
        g = await db.get_group(chat_id)
        if g:
            await db.set_group_field(chat_id, "taxi_enabled", 0 if g["taxi_enabled"] else 1)
            board = hub.get(chat_id)
            if board:
                board.mark_dirty()
        body, markup = await _group_menu_view(db, hub, chat_id)
        await _safe_edit(query, body, markup)
        return
    if action == "gref":
        chat_id = int(parts[1])
        board = hub.get(chat_id)
        if board:
            await board.force_repost()
        body, markup = await _group_menu_view(db, hub, chat_id)
        await _safe_edit(query, body, markup)
        return
    if action == "gpz":
        chat_id = int(parts[1])
        g = await db.get_group(chat_id)
        if g:
            now_paused = not bool(g["paused"])
            await db.set_group_paused(chat_id, now_paused)
            board = hub.get(chat_id)
            if board and not now_paused:
                board.mark_dirty()
        body, markup = await _group_menu_view(db, hub, chat_id)
        await _safe_edit(query, body, markup)
        return
    if action == "grm":
        chat_id = int(parts[1])
        await _safe_edit(
            query,
            "🗑 Guruh ro'yxatdan olib tashlansinmi?\n"
            "Bu guruhning yo'nalishlari va e'lonlari o'chadi, oynasi ham o'chadi. "
            "Haydovchilar guruhsiz qoladi.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Ha, olib tashlash", callback_data=f"grmy:{chat_id}"),
                InlineKeyboardButton("❌ Yo'q", callback_data=f"g:{chat_id}"),
            ]]),
        )
        return
    if action == "grmy":
        chat_id = int(parts[1])
        board = hub.remove(chat_id)
        if board:
            await board.delete_all()
        await db.remove_group(chat_id)
        body, markup = await _groups_list_view(db)
        await _safe_edit(query, body, markup)
        return

    # ── guruh ichidagi yo'nalishlar ──
    if action == "gr":
        body, markup = await _routes_view(db, int(parts[1]))
        await _safe_edit(query, body, markup)
        return
    if action == "gra":
        chat_id = int(parts[1])
        context.user_data["await"] = ("route", chat_id)
        await msg.reply_text(
            "Yangi yo'nalishni yozing. Bir nechta bo'lsa, har birini yangi qatordan yozing.\n"
            "Masalan:\nToshkent - Qibray\nQibray - Toshkent",
            reply_markup=cancel_kb(),
        )
        return
    if action == "grt":
        route = await db.get_route(int(parts[1]))
        if route:
            now_open = not route["is_open"]
            await db.set_route_open(route["id"], now_open)
            if not now_open:
                await db.stop_route_entries(route["id"])
            hub.mark_all_dirty()
            body, markup = await _routes_view(db, route["group_id"])
            await _safe_edit(query, body, markup)
        return
    if action == "grd":
        route = await db.get_route(int(parts[1]))
        if route:
            await _safe_edit(
                query,
                f"🗑 Yo'nalish o'chirilsinmi?\n📍 {route['from_place']} → {route['to_place']}\n"
                "Bu yo'nalishdagi e'lonlar ham to'xtatiladi.",
                InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"grdy:{route['id']}"),
                    InlineKeyboardButton("❌ Yo'q", callback_data=f"gr:{route['group_id']}"),
                ]]),
            )
        return
    if action == "grdy":
        route = await db.get_route(int(parts[1]))
        if route:
            await db.delete_route(route["id"])
            hub.mark_all_dirty()
            body, markup = await _routes_view(db, route["group_id"])
            await _safe_edit(query, body, markup)
        return

    # ── guruh ichidagi haydovchilar, e'lonlar, sozlamalar ──
    if action == "gd":
        body, markup = await _group_drivers_view(db, int(parts[1]))
        await _safe_edit(query, body, markup)
        return
    if action == "ge":
        body, markup = await _group_entries_view(db, int(parts[1]))
        await _safe_edit(query, body, markup)
        return
    if action == "gs":
        body, markup = await _group_settings_view(db, int(parts[1]))
        await _safe_edit(query, body, markup)
        return
    if action == "gsa":
        chat_id, hours = int(parts[1]), int(parts[2])
        if hours in AUTO_STOP_CHOICES:
            await db.set_group_field(chat_id, "auto_stop_hours", hours)
        # tanlangach menyu yopiladi (natija qoladi)
        await _safe_edit(query, f"✅ Saqlandi: avtomatik to'xtash {hours} soat.")
        return
    if action == "gsb":
        chat_id, n = int(parts[1]), int(parts[2])
        if n in REPOST_CHOICES:
            await db.set_group_field(chat_id, "repost_after_msgs", n)
        await _safe_edit(query, f"✅ Saqlandi: oyna har {n} ta yangi xabardan keyin pastga tushadi.")
        return

    # ── haydovchilar (global) ──
    if action == "dl":
        body, markup = await _drivers_overview(db)
        await _safe_edit(query, body, markup)
        return
    if action == "dv":
        body, markup = await _driver_detail(db, int(parts[1]))
        await _safe_edit(query, body, markup)
        return
    if action == "dok":
        target = int(parts[1])
        body, markup = await _group_picker_view(db, target)
        await _safe_edit(query, f"✅ Arizani tasdiqlash.\n{body}", markup)
        return
    if action == "dgp":
        target = int(parts[1])
        body, markup = await _group_picker_view(db, target)
        await _safe_edit(query, body, markup)
        return
    if action == "dgo":
        target, chat_id = int(parts[1]), int(parts[2])
        user = await db.get_user(target)
        g = await db.get_group(chat_id)
        if user is None or g is None:
            return
        title = g["title"] or str(chat_id)
        if user.status == "pending":
            await db.update_user_fields(target, status="approved")
            await db.change_driver_group(target, chat_id)
            await _notify(context, target,
                          f"✅ Arizangiz tasdiqlandi! Guruh: {title}.\n"
                          "Muddatni admin belgilagach ishlashingiz mumkin.",
                          driver_menu_kb())
        elif user.group_id != chat_id:
            await db.change_driver_group(target, chat_id)
            await _notify(context, target,
                          f"🔀 Guruhingiz o'zgartirildi: {title}. Eski e'loningiz to'xtatildi.")
        hub.mark_all_dirty()
        body, markup = await _driver_detail(db, target)
        await _safe_edit(query, body, markup)
        return
    if action == "dno":
        target = int(parts[1])
        user = await db.get_user(target)
        await db.update_user_fields(target, status="blocked")
        await _notify(context, target, "❌ Afsuski, arizangiz rad etildi.")
        name = user.full_name if user else str(target)
        await _safe_edit(query, f"❌ Rad etildi: {name}")
        return
    if action == "dsub":
        target = int(parts[1])
        context.user_data["await"] = ("sub", target)
        await msg.reply_text(
            f"Necha kun muddat berasiz? Faqat raqam yozing (1–{MAX_SUB_DAYS}), masalan: 30\n"
            "Eski muddat bekor bo'ladi.",
            reply_markup=cancel_kb(),
        )
        return
    if action == "dpz":
        target = int(parts[1])
        user = await db.get_user(target)
        if user and user.status in ("approved", "paused"):
            if user.status == "approved":
                await db.update_user_fields(target, status="paused")
                await db.stop_all_for_driver(target)
                await _notify(context, target,
                              "⏸ Admin sizni vaqtincha to'xtatib qo'ydi. E'lonlaringiz oynadan olib tashlandi.")
            else:
                await db.update_user_fields(target, status="approved")
                await _notify(context, target, "▶️ Admin sizni qayta ishga tushirdi.")
            hub.mark_all_dirty()
        body, markup = await _driver_detail(db, target)
        await _safe_edit(query, body, markup)
        return
    if action == "dblk":
        target = int(parts[1])
        user = await db.get_user(target)
        name = user.full_name if user else str(target)
        await _safe_edit(
            query,
            f"🚫 {name} bloklansinmi?\nBloklangan haydovchi botdan foydalana olmaydi.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Ha, bloklash", callback_data=f"dblky:{target}"),
                InlineKeyboardButton("❌ Yo'q", callback_data=f"dv:{target}"),
            ]]),
        )
        return
    if action == "dblky":
        target = int(parts[1])
        await db.block_driver(target)
        hub.mark_all_dirty()
        await _notify(context, target, "⛔ Huquqingiz cheklandi. E'lonlaringiz oynadan olib tashlandi.")
        body, markup = await _driver_detail(db, target)
        await _safe_edit(query, body, markup)
        return
    if action == "dunb":
        target = int(parts[1])
        await db.update_user_fields(target, status="approved")
        await _notify(context, target, "✅ Huquqingiz qayta tiklandi. Muddatni admin belgilaydi.")
        body, markup = await _driver_detail(db, target)
        await _safe_edit(query, body, markup)
        return


async def _driver_callback(query, context, uid: int, action: str, parts: list[str]) -> None:
    db = _db(context)
    hub = _hub(context)
    user = await db.get_user(uid)

    if action in ("rt", "ns") and not _subscribed(user):
        await _safe_edit(query, f"⛔ Muddat tugagan yoki belgilanmagan.\n📅 {_sub_status(user.paid_until)}")
        return

    if action == "pe":
        field = parts[1]
        if field == "phone":
            context.user_data["await"] = ("edit_phone",)
            await query.message.reply_text(
                "Yangi telefon raqamingizni 📱 tugma orqali yuboring.", reply_markup=contact_kb())
        else:
            which = "edit_first" if field == "first" else "edit_last"
            context.user_data["await"] = (which,)
            label = "ismingizni" if field == "first" else "familiyangizni"
            await query.message.reply_text(f"Yangi {label} yozing:", reply_markup=cancel_kb())
        return

    if action == "tq":
        await db.update_user_fields(uid, taxi_on=0 if user.taxi_on else 1)
        body, markup = await _profile_view(db, uid)
        await _safe_edit(query, body, markup)
        return

    if action == "rt":
        route = await db.get_route(int(parts[1]))
        if not route or not route["is_open"] or route["group_id"] != user.group_id:
            await _safe_edit(query, "Bu yo'nalish hozir yopiq yoki sizning guruhingizga tegishli emas.")
            return
        await _safe_edit(
            query,
            f"📍 {route['from_place']} → {route['to_place']}\n\nNechta bo'sh joy bor?",
            InlineKeyboardMarkup(_seat_rows(f"ns:{route['id']}")),
        )
        return

    if action == "ns":
        route = await db.get_route(int(parts[1]))
        seats = int(parts[2])
        if not route or not route["is_open"] or route["group_id"] != user.group_id:
            await _safe_edit(query, "Bu yo'nalish hozir yopiq yoki sizning guruhingizga tegishli emas.")
            return
        _, replaced = await db.start_entry(uid, route["id"], seats)
        hub.mark_all_dirty()
        text = (f"🟢 E'lon guruhga joylandi:\n📍 {route['from_place']} → {route['to_place']}\n"
                f"{seats_label(seats)}")
        if replaced:
            text += "\n\nℹ️ Oldingi e'loningiz to'xtatildi: " + ", ".join(replaced)
        await _safe_edit(query, text)
        return

    if action in ("ea", "ee", "es", "st"):
        entry = await db.get_entry_by_id(int(parts[1]))
        if not entry or entry["driver_id"] != uid:
            await _safe_edit(query, "Bu e'lon topilmadi.")
            return
        if action != "st" and not entry["active"]:
            await _safe_edit(query, "Bu e'lon to'xtatilgan.")
            return
        if action == "ea":
            new_seats = min(max(entry["seats"] + int(parts[2]), 0), max(SEAT_OPTIONS))
            await db.set_entry_seats(entry["id"], new_seats)
            hub.mark_all_dirty()
            body, markup = await _my_entries_view(db, uid)
            await _safe_edit(query, body, markup)
        elif action == "ee":
            await _safe_edit(query, "Nechta bo'sh joy bor?",
                             InlineKeyboardMarkup(_seat_rows(f"es:{entry['id']}")))
        elif action == "es":
            await db.set_entry_seats(entry["id"], int(parts[2]))
            hub.mark_all_dirty()
            body, markup = await _my_entries_view(db, uid)
            await _safe_edit(query, body, markup)
        else:  # st
            await db.stop_entry(entry["id"])
            hub.mark_all_dirty()
            await _safe_edit(query, "🔴 E'lon to'xtatildi va guruh oynasidan olib tashlandi.")
        return


def _seat_rows(prefix: str) -> list[list[InlineKeyboardButton]]:
    """0..8 raqamli tugmalar, 3 tadan qator. prefix: 'ns:<rid>' yoki 'es:<eid>'."""
    buttons = [InlineKeyboardButton(str(n), callback_data=f"{prefix}:{n}") for n in SEAT_OPTIONS]
    return [buttons[i:i + 3] for i in range(0, len(buttons), 3)]


# ══════════════════════════════════════════════════════════════════════════
# Guruh xabarlari
# ══════════════════════════════════════════════════════════════════════════
async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or update.effective_user is None:
        return
    if update.effective_user.id == context.bot.id:
        return
    board = _hub(context).get(update.effective_chat.id)
    if board:
        await board.on_group_message(msg.message_id)


async def cmd_group_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Guruhda /yangila — faqat super admin: shu guruh oynasini darhol pastga qayta yuboradi."""
    if not await is_manager(context, update.effective_user.id):
        return
    board = _hub(context).get(update.effective_chat.id)
    if board:
        await board.force_repost()
    try:
        await update.effective_message.delete()
    except TelegramError:
        pass
