"""
handlers.py — bot buyruqlari, tugmalar, ro'yxatdan o'tish, boshqaruv paneli, guruh xabarlari.

Rollar:
- Super admin (ADMIN_ID) — boshqaruv paneli (guruh adminlari boshqaruvga kirmaydi).
  Admin haydovchi ism/telefonini o'zgartira olmaydi.
- Haydovchi — ro'yxatdan o'tadi, admin tasdiqlaydi, muddatni admin belgilaydi, so'ng e'lon beradi.
  Ism va telefonini faqat o'zi tahrirlaydi.
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
from utils import SEAT_OPTIONS, normalize_phone, parse_route, seats_label

log = logging.getLogger("haydovchi.handlers")

# ── tugma matnlari ───────────────────────────────────────────────────────
BTN_START = "🟢 Ishni boshlash"
BTN_STOP = "🔴 To'xtatish"
BTN_MY = "📋 Mening holatim"
BTN_PROFILE = "✏️ Ma'lumotlarim"
BTN_CONTACT = "📱 Raqamni yuborish"
BTN_CANCEL = "❌ Bekor qilish"

A_ROUTES = "🛣 Yo'nalishlar"
A_DRIVERS = "👥 Haydovchilar"
A_GROUPS = "🏘 Guruhlar"
A_REFRESH = "📢 Oynani yangilash"
A_SETTINGS = "⚙️ Sozlamalar"
A_STATS = "📊 Statistika"

MENU_BUTTONS = {BTN_START, BTN_STOP, BTN_MY, BTN_PROFILE,
                A_ROUTES, A_DRIVERS, A_GROUPS, A_REFRESH, A_SETTINGS, A_STATS}

AUTO_STOP_CHOICES = [1, 2, 3, 4]     # soat
REPOST_CHOICES = [3, 5, 10]          # yangi xabar soni
MAX_SUB_DAYS = 365


def driver_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[BTN_START, BTN_STOP], [BTN_MY, BTN_PROFILE]], resize_keyboard=True)


def admin_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[A_ROUTES, A_DRIVERS], [A_GROUPS, A_REFRESH], [A_SETTINGS, A_STATS]], resize_keyboard=True
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[BTN_CANCEL]], resize_keyboard=True)


def contact_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(BTN_CONTACT, request_contact=True)], [BTN_CANCEL]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


STATUS_LABEL = {
    "pending": "⏳ kutilmoqda",
    "approved": "🟢 faol",
    "paused": "⏸ to'xtatilgan",
    "blocked": "⛔ bloklangan",
}


# ── yordamchilar ─────────────────────────────────────────────────────────
def _db(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["db"]


def _hub(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["hub"]


def _bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.application.bot_data.get("bot_username", "")


async def is_manager(context, uid: int) -> bool:
    """Boshqaruv faqat super admin (ADMIN_ID) uchun. Guruh adminlari boshqaruvga kirmaydi."""
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
# Shaxsiy chatdagi matn, kontakt va bekor qilish
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
        routes = [r for r in await db.list_routes() if r["is_open"]]
        if not routes:
            await msg.reply_text("Hozircha ochiq yo'nalish yo'q. Admin yo'nalish ochishini kuting.")
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
    if not entries:
        return ("Sizda faol e'lon yo'q. 🟢 Ishni boshlash tugmasini bosing.",
                InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="back")]]))
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
    rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="back")])
    lines.append("\n➖ odam oldi · ➕ joy bo'shadi · 🔢 aniq son · 🔴 to'xtatish")
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _profile_view(db, uid: int) -> tuple[str, InlineKeyboardMarkup]:
    user = await db.get_user(uid)
    entries = await db.driver_entries(uid)
    text = (
        "✏️ Ma'lumotlaringiz\n\n"
        f"👤 Ism: {user.first_name}\n"
        f"👤 Familiya: {user.last_name}\n"
        f"📞 Telefon: {user.phone}\n"
        f"📅 Muddat: {_sub_status(user.paid_until)}\n"
        f"🟢 Faol e'lon: {len(entries)} ta\n\n"
        "O'zgartirish uchun tugmani bosing:"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Ismni o'zgartirish", callback_data="pe:first")],
        [InlineKeyboardButton("✏️ Familiyani o'zgartirish", callback_data="pe:last")],
        [InlineKeyboardButton("📱 Telefonni o'zgartirish", callback_data="pe:phone")],
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
        added, bad = [], []
        for line in text.splitlines():
            if not line.strip():
                continue
            parsed = parse_route(line)
            if parsed:
                await db.add_route(parsed[0], parsed[1])
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
        body, markup = await _routes_view(db)
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

    if text == A_ROUTES:
        body, markup = await _routes_view(db)
        await msg.reply_text(body, reply_markup=markup)
    elif text == A_DRIVERS:
        body, markup = await _drivers_view(db)
        await msg.reply_text(body, reply_markup=markup)
    elif text == A_GROUPS:
        body, markup = await _groups_view(db)
        await msg.reply_text(body, reply_markup=markup)
    elif text == A_REFRESH:
        await _hub(context).force_all()
        await msg.reply_text("✅ Barcha guruh oynalari pastga qayta yuborildi.")
    elif text == A_SETTINGS:
        body, markup = await _settings_view(db)
        await msg.reply_text(body, reply_markup=markup)
    elif text == A_STATS:
        await msg.reply_text(await _stats_text(db, _hub(context)))
    else:
        await msg.reply_text("🛠 Boshqaruv paneli", reply_markup=admin_menu_kb())


# ── Yo'nalishlar ───────────────────────────────────────────────────────
async def _routes_view(db) -> tuple[str, InlineKeyboardMarkup]:
    routes = await db.list_routes()
    rows = []
    lines = ["🛣 Yo'nalishlar:"]
    if not routes:
        lines.append("Hozircha yo'nalish yo'q.")
    for r in routes:
        state = "🟢 ochiq" if r["is_open"] else "⛔ yopiq"
        lines.append(f"• {r['from_place']} → {r['to_place']} ({state})")
        rows.append([
            InlineKeyboardButton("⛔ Yopish" if r["is_open"] else "🟢 Ochish",
                                 callback_data=f"rtg:{r['id']}"),
            InlineKeyboardButton("🗑 O'chirish", callback_data=f"rdl:{r['id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ Yangi yo'nalish", callback_data="ra")])
    rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="back")])
    lines.append("\nYangi yo'nalish: har qatorga bitta, masalan \"Toshkent - Qibray\".")
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ── Guruhlar ───────────────────────────────────────────────────────────
async def _groups_view(db) -> tuple[str, InlineKeyboardMarkup]:
    groups = await db.list_groups()
    rows = []
    lines = ["🏘 Guruhlar:"]
    if not groups:
        lines.append("Hozircha guruh yo'q.")
    for i, g in enumerate(groups, start=1):
        title = (g["title"] or str(g["chat_id"]))[:28]
        state = "⏸" if g["paused"] else "🟢"
        rows.append([InlineKeyboardButton(f"{state} {i}. {title}", callback_data=f"gv:{g['chat_id']}")])
    rows.append([InlineKeyboardButton("➕ Yangi guruh qo'shish", callback_data="gadd")])
    rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="back")])
    lines.append(
        "\nTelegram botlar guruh yarata olmaydi. Avval Telegram'da guruh oching, botni admin qiling "
        "(xabarlarni o'chirish huquqi bilan), so'ng bu yerda ➕ tugmasini bosing."
    )
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _group_detail(db, hub, chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    groups = {g["chat_id"]: g for g in await db.list_groups()}
    g = groups.get(chat_id)
    board: BoardManager | None = hub.get(chat_id)
    title = (g["title"] if g else "") or str(chat_id)
    paused = bool(g["paused"]) if g else False
    last_ts, pending_msgs = await board.last_update_info() if board else (0, 0)
    last_txt = (time.strftime("%d.%m %H:%M", time.localtime(last_ts)) if last_ts else "hali yo'q")
    state = "⏸ to'xtatilgan (avtomatik yangilanmaydi)" if paused else "🟢 faol"
    text = (
        f"🏘 {title}\n"
        f"🆔 {chat_id}\n"
        f"Holat: {state}\n"
        f"Oxirgi yangilanish: {last_txt}\n"
        f"Shundan beri yangi xabarlar: {pending_msgs} ta"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Hozir yangilash", callback_data=f"gref:{chat_id}")],
        [InlineKeyboardButton("▶️ Davom ettirish" if paused else "⏸ Avtomatikni to'xtatish",
                              callback_data=f"gpz:{chat_id}")],
        [InlineKeyboardButton("🗑 Guruhni olib tashlash", callback_data=f"grm:{chat_id}")],
        [InlineKeyboardButton("⬅️ Guruhlar", callback_data="gl")],
    ])
    return text, markup


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
    body, markup = await _groups_view(db)
    await msg.reply_text(body, reply_markup=markup)


def _forwarded_chat_id(msg) -> int | None:
    origin = getattr(msg, "forward_origin", None)
    chat = getattr(origin, "chat", None)
    if chat is not None:
        return chat.id
    fwd = getattr(msg, "forward_from_chat", None)  # eski PTB ko'rinishi
    return fwd.id if fwd else None


# ── Haydovchilar ───────────────────────────────────────────────────────
async def _drivers_view(db) -> tuple[str, InlineKeyboardMarkup]:
    pending = await db.users_by_status("pending")
    others = []
    for st in ("approved", "paused", "blocked"):
        others += await db.users_by_status(st)
    rows = []
    lines = [f"⏳ Kutilayotgan arizalar: {len(pending)} ta"]
    for u in pending[:15]:
        lines.append(f"• {u.full_name} — {u.phone}")
        rows.append([
            InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"dok:{u.tg_id}"),
            InlineKeyboardButton("❌ Rad etish", callback_data=f"dno:{u.tg_id}"),
        ])
    lines.append(f"\n👥 Haydovchilar: {len(others)} ta (tanlab boshqaring)")
    for u in others[:25]:
        label = (u.full_name or str(u.tg_id))[:24]
        rows.append([InlineKeyboardButton(f"{label} · {STATUS_LABEL.get(u.status, u.status)}",
                                          callback_data=f"dv:{u.tg_id}")])
    rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="back")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _driver_detail(db, uid: int) -> tuple[str, InlineKeyboardMarkup]:
    user = await db.get_user(uid)
    entries = await db.driver_entries(uid)
    route_txt = (f"{entries[0]['from_place']} → {entries[0]['to_place']}"
                 if entries else "yo'q")
    text = (
        f"👤 {user.full_name}\n"
        f"📞 {user.phone}\n"
        f"Holat: {STATUS_LABEL.get(user.status, user.status)}\n"
        f"📅 Muddat: {_sub_status(user.paid_until)}\n"
        f"📍 Faol e'lon: {route_txt}"
    )
    rows = [[InlineKeyboardButton("📅 Muddat berish (kun)", callback_data=f"dsub:{uid}")]]
    if user.status in ("approved", "paused"):
        if user.status == "approved":
            rows.append([InlineKeyboardButton("⏸ Vaqtincha to'xtatib qo'yish",
                                              callback_data=f"dpz:{uid}")])
        else:
            rows.append([InlineKeyboardButton("▶️ Ishga tushirish", callback_data=f"dpz:{uid}")])
    if user.status == "blocked":
        rows.append([InlineKeyboardButton("🔓 Qayta tiklash", callback_data=f"dunb:{uid}")])
    else:
        rows.append([InlineKeyboardButton("🚫 Bloklash", callback_data=f"dblk:{uid}")])
    rows.append([InlineKeyboardButton("⬅️ Haydovchilar", callback_data="dl")])
    return text, InlineKeyboardMarkup(rows)


# ── Sozlamalar ─────────────────────────────────────────────────────────
async def _settings_view(db) -> tuple[str, InlineKeyboardMarkup]:
    hours = await db.auto_stop_hours()
    repost = await db.repost_after_msgs()
    text = (
        "⚙️ Sozlamalar\n\n"
        f"⏰ Avtomatik to'xtash: {hours} soat (yangilanmagan e'lon)\n"
        f"📌 Oyna pastga tushishi: {repost} ta yangi xabardan keyin\n"
        "\nOyna har 30 soniyada tekshiriladi. Haydovchi o'zgarishi bo'lsa darhol yangilanadi."
    )
    rows = [
        [InlineKeyboardButton(("✔ " if h == hours else "") + f"{h} soat",
                              callback_data=f"sauto:{h}") for h in AUTO_STOP_CHOICES],
        [InlineKeyboardButton(("✔ " if n == repost else "") + f"{n} xabar",
                              callback_data=f"sbt:{n}") for n in REPOST_CHOICES],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="back")],
    ]
    return text, InlineKeyboardMarkup(rows)


async def _stats_text(db, hub) -> str:
    counts = await db.count_users_by_status()
    routes = await db.list_routes()
    open_routes = sum(1 for r in routes if r["is_open"])
    board = await db.board_routes()
    free_seats = sum(e["seats"] for r in board for e in r["entries"])
    active = await db.active_entry_count()
    groups = await db.list_groups()
    paused_groups = sum(1 for g in groups if g["paused"])
    return (
        "📊 Statistika\n\n"
        f"✅ Faol haydovchilar: {counts.get('approved', 0)}\n"
        f"⏸ To'xtatilgan: {counts.get('paused', 0)}\n"
        f"⏳ Kutilayotgan arizalar: {counts.get('pending', 0)}\n"
        f"⛔ Bloklangan: {counts.get('blocked', 0)}\n\n"
        f"🛣 Ochiq yo'nalishlar: {open_routes} / {len(routes)}\n"
        f"🟢 Faol e'lonlar: {active}\n"
        f"🪑 Jami bo'sh joy (oynadagi): {free_seats}\n"
        f"🏘 Guruhlar: {len(groups)} ta (to'xtatilgan: {paused_groups})"
    )


# ══════════════════════════════════════════════════════════════════════════
# Inline tugmalar (callback)
# ══════════════════════════════════════════════════════════════════════════
MANAGER_ACTIONS = {
    "ra", "rtg", "rdl", "rdy", "ro",
    "gadd", "gl", "gv", "gref", "gpz", "grm", "grmy",
    "dok", "dno", "dl", "dv", "dsub", "dpz", "dblk", "dblky", "dunb",
    "sauto", "sbt",
}


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    parts = query.data.split(":")
    action = parts[0]
    db = _db(context)

    if action == "back":
        await query.answer()
        await _safe_edit(query, "⬅️ Asosiy menyu. Kerakli bo'limni tanlang.", None)
        return

    if action in MANAGER_ACTIONS:
        if not await is_manager(context, uid):
            await query.answer("Bu amal faqat adminlar uchun.", show_alert=True)
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

    # ── yo'nalishlar ──
    if action == "ra":
        context.user_data["await"] = ("route",)
        await msg.reply_text(
            "Yangi yo'nalishni yozing. Bir nechta bo'lsa, har birini yangi qatordan yozing.\n"
            "Masalan:\nToshkent - Qibray\nQibray - Toshkent",
            reply_markup=cancel_kb(),
        )
        return
    if action == "ro":
        body, markup = await _routes_view(db)
        await _safe_edit(query, body, markup)
        return
    if action == "rtg":
        route_id = int(parts[1])
        route = await db.get_route(route_id)
        if route:
            now_open = not route["is_open"]
            await db.set_route_open(route_id, now_open)
            if not now_open:
                await db.stop_route_entries(route_id)
            hub.mark_all_dirty()
        body, markup = await _routes_view(db)
        await _safe_edit(query, body, markup)
        return
    if action == "rdl":
        route = await db.get_route(int(parts[1]))
        if not route:
            return
        await _safe_edit(
            query,
            f"🗑 Yo'nalish o'chirilsinmi?\n📍 {route['from_place']} → {route['to_place']}\n"
            "Bu yo'nalishdagi e'lonlar ham to'xtatiladi.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"rdy:{route['id']}"),
                InlineKeyboardButton("❌ Yo'q", callback_data="ro"),
            ]]),
        )
        return
    if action == "rdy":
        await db.delete_route(int(parts[1]))
        hub.mark_all_dirty()
        body, markup = await _routes_view(db)
        await _safe_edit(query, body, markup)
        return

    # ── guruhlar ──
    if action == "gadd":
        context.user_data["await"] = ("group",)
        await msg.reply_text(
            "Guruhdan bitta xabarni shu botga forward qiling, yoki guruh ID sini yozing (-100...).",
            reply_markup=cancel_kb(),
        )
        return
    if action == "gl":
        body, markup = await _groups_view(db)
        await _safe_edit(query, body, markup)
        return
    if action == "gv":
        body, markup = await _group_detail(db, hub, int(parts[1]))
        await _safe_edit(query, body, markup)
        return
    if action == "gref":
        chat_id = int(parts[1])
        board = hub.get(chat_id)
        if board:
            await board.force_repost()
        body, markup = await _group_detail(db, hub, chat_id)
        await _safe_edit(query, body, markup)
        return
    if action == "gpz":
        chat_id = int(parts[1])
        groups = {g["chat_id"]: g for g in await db.list_groups()}
        if chat_id in groups:
            now_paused = not bool(groups[chat_id]["paused"])
            await db.set_group_paused(chat_id, now_paused)
            board = hub.get(chat_id)
            if board:
                board.paused = now_paused
                if not now_paused:
                    board.mark_dirty()
        body, markup = await _group_detail(db, hub, chat_id)
        await _safe_edit(query, body, markup)
        return
    if action == "grm":
        chat_id = int(parts[1])
        await _safe_edit(
            query,
            "🗑 Guruh ro'yxatdan olib tashlansinmi?\nBu guruhdagi ma'lumot oynasi ham o'chadi.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Ha, olib tashlash", callback_data=f"grmy:{chat_id}"),
                InlineKeyboardButton("❌ Yo'q", callback_data=f"gv:{chat_id}"),
            ]]),
        )
        return
    if action == "grmy":
        chat_id = int(parts[1])
        board = hub.remove(chat_id)
        if board:
            await board.delete_all()
        await db.remove_group(chat_id)
        body, markup = await _groups_view(db)
        await _safe_edit(query, body, markup)
        return

    # ── haydovchilar ──
    if action == "dl":
        body, markup = await _drivers_view(db)
        await _safe_edit(query, body, markup)
        return
    if action == "dv":
        body, markup = await _driver_detail(db, int(parts[1]))
        await _safe_edit(query, body, markup)
        return
    if action == "dok":
        target = int(parts[1])
        user = await db.get_user(target)
        if not user:
            return
        await db.update_user_fields(target, status="approved")
        await _notify(context, target,
                      "✅ Arizangiz tasdiqlandi! Muddatni admin belgilagach ishlashingiz mumkin.",
                      driver_menu_kb())
        body, markup = await _driver_detail(db, target)
        await _safe_edit(query, f"✅ Tasdiqlandi.\n\n{body}", markup)
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

    # ── sozlamalar: tanlangach menyu yopiladi ──
    if action == "sauto":
        hours = int(parts[1])
        if hours in AUTO_STOP_CHOICES:
            await db.set_setting("auto_stop_hours", str(hours))
        await _safe_edit(query, f"✅ Saqlandi: avtomatik to'xtash {hours} soat.")
        return
    if action == "sbt":
        n = int(parts[1])
        if n in REPOST_CHOICES:
            await db.set_setting("repost_after_msgs", str(n))
        await _safe_edit(query, f"✅ Saqlandi: oyna har {n} ta yangi xabardan keyin pastga tushadi.")
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

    if action == "rt":
        route_id = int(parts[1])
        route = await db.get_route(route_id)
        if not route or not route["is_open"]:
            await _safe_edit(query, "Bu yo'nalish hozir yopiq.")
            return
        await _safe_edit(
            query,
            f"📍 {route['from_place']} → {route['to_place']}\n\nNechta bo'sh joy bor?",
            InlineKeyboardMarkup(_seat_rows(f"ns:{route_id}")),
        )
        return

    if action == "ns":
        route_id, seats = int(parts[1]), int(parts[2])
        route = await db.get_route(route_id)
        if not route or not route["is_open"]:
            await _safe_edit(query, "Bu yo'nalish hozir yopiq.")
            return
        _, replaced = await db.start_entry(uid, route_id, seats)
        hub.mark_all_dirty()
        text = (f"🟢 E'lon guruhga joylandi:\n📍 {route['from_place']} → {route['to_place']}\n"
                f"{seats_label(seats)}")
        if replaced:
            text += "\n\nℹ️ Oldingi e'loningiz to'xtatildi: " + ", ".join(replaced)
        await _safe_edit(query, text)
        return

    if action == "ea":
        entry = await db.get_entry_by_id(int(parts[1]))
        if not entry or entry["driver_id"] != uid or not entry["active"]:
            await _safe_edit(query, "Bu e'lon topilmadi yoki to'xtatilgan.")
            return
        new_seats = min(max(entry["seats"] + int(parts[2]), 0), max(SEAT_OPTIONS))
        await db.set_entry_seats(entry["id"], new_seats)
        hub.mark_all_dirty()
        body, markup = await _my_entries_view(db, uid)
        await _safe_edit(query, body, markup)
        return

    if action == "ee":
        entry = await db.get_entry_by_id(int(parts[1]))
        if not entry or entry["driver_id"] != uid or not entry["active"]:
            await _safe_edit(query, "Bu e'lon topilmadi yoki to'xtatilgan.")
            return
        await _safe_edit(query, "Nechta bo'sh joy bor?",
                         InlineKeyboardMarkup(_seat_rows(f"es:{entry['id']}")))
        return

    if action == "es":
        entry = await db.get_entry_by_id(int(parts[1]))
        if not entry or entry["driver_id"] != uid or not entry["active"]:
            await _safe_edit(query, "Bu e'lon topilmadi yoki to'xtatilgan.")
            return
        await db.set_entry_seats(entry["id"], int(parts[2]))
        hub.mark_all_dirty()
        body, markup = await _my_entries_view(db, uid)
        await _safe_edit(query, body, markup)
        return

    if action == "st":
        entry = await db.get_entry_by_id(int(parts[1]))
        if not entry or entry["driver_id"] != uid:
            await _safe_edit(query, "Bu e'lon topilmadi.")
            return
        await db.stop_entry(entry["id"])
        hub.mark_all_dirty()
        await _safe_edit(query, "🔴 E'lon to'xtatildi va guruh oynasidan olib tashlandi.")
        return

    if action == "sa":
        count = await db.stop_all_for_driver(uid)
        if count:
            hub.mark_all_dirty()
        await _safe_edit(query, f"🔴 {count} ta e'lon to'xtatildi.")
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
    """Guruhda /yangila — admin shu guruh oynasini darhol pastga qayta yuboradi."""
    if not await is_manager(context, update.effective_user.id):
        return
    board = _hub(context).get(update.effective_chat.id)
    if board:
        await board.force_repost()
    try:
        await update.effective_message.delete()
    except TelegramError:
        pass
