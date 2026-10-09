"""
handlers.py — bot buyruqlari, tugmalar va guruh xabarlari.

Rollar:
- Super admin (ADMIN_ID) va guruh adminlari (Telegram'dagi admin huquqi) — boshqaruv paneli.
- Haydovchi — ro'yxatdan o'tadi, tasdiqlanadi, start/stop va bo'sh joy tugmalari.
"""

from __future__ import annotations

import logging

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

from config import ADMIN_ID, GROUP_CHAT_ID
from utils import SEAT_OPTIONS, normalize_phone, parse_route, seats_label

log = logging.getLogger("haydovchi.handlers")

# ── tugma matnlari ───────────────────────────────────────────────────────
BTN_START = "🟢 Ishni boshlash"
BTN_STOP = "🔴 To'xtatish"
BTN_MY = "📋 Mening e'lonlarim"
BTN_PROFILE = "👤 Mening ma'lumotim"
BTN_CONTACT = "📱 Raqamni yuborish"

A_ROUTES = "🛣 Yo'nalishlar"
A_DRIVERS = "👥 Haydovchilar"
A_REFRESH = "📢 Oynani yangilash"
A_SETTINGS = "⚙️ Sozlamalar"
A_STATS = "📊 Statistika"

AUTO_STOP_CHOICES = [1, 2, 3, 4]        # soat
PERIODIC_CHOICES = [10, 15, 20, 30]     # daqiqa


def driver_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[BTN_START, BTN_STOP], [BTN_MY, BTN_PROFILE]], resize_keyboard=True
    )


def admin_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[A_ROUTES, A_DRIVERS], [A_REFRESH, A_SETTINGS], [A_STATS]], resize_keyboard=True
    )


def contact_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(BTN_CONTACT, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# ── yordamchilar ─────────────────────────────────────────────────────────
def _db(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["db"]


def _board(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["board"]


async def is_manager(bot, uid: int) -> bool:
    """Super admin yoki guruhdagi admin/creator."""
    if uid == ADMIN_ID:
        return True
    try:
        member = await bot.get_chat_member(GROUP_CHAT_ID, uid)
        return member.status in ("creator", "administrator")
    except TelegramError:
        return False


async def _safe_edit(query, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await query.edit_message_text(text, reply_markup=markup)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            log.warning("Xabarni tahrirlab bo'lmadi: %s", e)


async def _notify(context, uid: int, text: str, markup=None) -> None:
    """Foydalanuvchiga shaxsiy xabar. U botni ishga tushirmagan bo'lsa — jim o'tadi."""
    try:
        await context.bot.send_message(chat_id=uid, text=text, reply_markup=markup)
    except TelegramError as e:
        log.info("Xabar yuborib bo'lmadi (%s): %s", uid, e)


# ══════════════════════════════════════════════════════════════════════════
# /start va ro'yxatdan o'tish
# ══════════════════════════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if await is_manager(context.bot, uid):
        await update.effective_message.reply_text(
            "🛠 Boshqaruv paneli. Kerakli bo'limni tanlang.", reply_markup=admin_menu_kb()
        )
        return
    await _db(context).ensure_user(uid)
    await _advance(update, context, uid)


async def _advance(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int) -> None:
    """Haydovchi holatiga qarab keyingi qadamni ko'rsatadi."""
    db = _db(context)
    user = await db.get_user(uid)
    msg = update.effective_message

    if user is None:
        await db.ensure_user(uid)
        user = await db.get_user(uid)

    if user.status == "blocked":
        await msg.reply_text("⛔ Sizning huquqingiz cheklangan. Admin bilan bog'laning.",
                             reply_markup=ReplyKeyboardRemove())
        return
    if user.status == "pending":
        await msg.reply_text("⏳ Arizangiz ko'rib chiqilmoqda. Tasdiqlangach xabar beramiz.",
                             reply_markup=ReplyKeyboardRemove())
        return
    if user.status == "approved":
        await msg.reply_text("🚗 Haydovchi paneli", reply_markup=driver_menu_kb())
        return

    # ro'yxatdan o'tish bosqichlari
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
    markup = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"dok:{user.tg_id}"),
            InlineKeyboardButton("❌ Rad etish", callback_data=f"dno:{user.tg_id}"),
        ]]
    )
    await _notify(context, ADMIN_ID, text, markup)


# ══════════════════════════════════════════════════════════════════════════
# Shaxsiy chatdagi matn va kontakt
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
    await db.update_user_fields(uid, phone=phone)
    await _advance(update, context, uid)


async def on_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    text = (update.effective_message.text or "").strip()

    # 1) Boshqaruvchi — admin paneli (yo'nalish qo'shish holati ham shu yerda)
    if await is_manager(context.bot, uid):
        await _manager_text(update, context, text)
        return

    db = _db(context)
    await db.ensure_user(uid)
    user = await db.get_user(uid)

    # 2) Tasdiqlangan haydovchi
    if user.status == "approved":
        await _driver_text(update, context, uid, text)
        return

    # 3) Ro'yxatdan o'tish bosqichlari
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

    # 4) pending / blocked
    await _advance(update, context, uid)


# ══════════════════════════════════════════════════════════════════════════
# Haydovchi paneli
# ══════════════════════════════════════════════════════════════════════════
async def _driver_text(update, context, uid: int, text: str) -> None:
    db = _db(context)
    msg = update.effective_message

    if text == BTN_START:
        routes = [r for r in await db.list_routes() if r["is_open"]]
        if not routes:
            await msg.reply_text("Hozircha ochiq yo'nalish yo'q. Admin yo'nalish ochishini kuting.")
            return
        rows = [
            [InlineKeyboardButton(f"📍 {r['from_place']} → {r['to_place']}", callback_data=f"rt:{r['id']}")]
            for r in routes
        ]
        await msg.reply_text("Yo'nalishni tanlang:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if text == BTN_STOP:
        entries = await db.driver_entries(uid)
        if not entries:
            await msg.reply_text("Sizda faol e'lon yo'q.")
            return
        rows = [
            [InlineKeyboardButton(
                f"🔴 {e['from_place']} → {e['to_place']}", callback_data=f"st:{e['id']}")]
            for e in entries
        ]
        rows.append([InlineKeyboardButton("⛔ Hammasini to'xtatish", callback_data="sa")])
        await msg.reply_text("To'xtatmoqchi bo'lgan yo'nalishingizni tanlang:",
                             reply_markup=InlineKeyboardMarkup(rows))
        return

    if text == BTN_MY:
        body, markup = await _my_entries_view(db, uid)
        await msg.reply_text(body, reply_markup=markup)
        return

    if text == BTN_PROFILE:
        user = await db.get_user(uid)
        await msg.reply_text(
            f"👤 {user.first_name} {user.last_name}\n📞 {user.phone}\n"
            f"🟢 Faol e'lonlar: {len(await db.driver_entries(uid))} ta"
        )
        return

    await msg.reply_text("🚗 Haydovchi paneli", reply_markup=driver_menu_kb())


async def _my_entries_view(db, uid: int) -> tuple[str, InlineKeyboardMarkup]:
    entries = await db.driver_entries(uid)
    if not entries:
        return "Sizda faol e'lon yo'q. 🟢 Ishni boshlash tugmasini bosing.", InlineKeyboardMarkup([])
    rows = []
    lines = ["📋 Faol e'lonlaringiz:"]
    for e in entries:
        title = f"{e['from_place']} → {e['to_place']}"
        lines.append(f"📍 {title}: {seats_label(e['seats'])}")
        rows.append([
            InlineKeyboardButton("➖", callback_data=f"ea:{e['id']}:-1"),
            InlineKeyboardButton("➕", callback_data=f"ea:{e['id']}:1"),
            InlineKeyboardButton("🔢", callback_data=f"ee:{e['id']}"),
            InlineKeyboardButton("🔴", callback_data=f"st:{e['id']}"),
        ])
    rows.append([InlineKeyboardButton("⛔ Hammasini to'xtatish", callback_data="sa")])
    lines.append("\n➖ odam oldi · ➕ joy bo'shadi · 🔢 aniq son · 🔴 to'xtatish")
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ══════════════════════════════════════════════════════════════════════════
# Boshqaruv paneli (super admin + guruh adminlari)
# ══════════════════════════════════════════════════════════════════════════
async def _manager_text(update, context, text: str) -> None:
    db = _db(context)
    msg = update.effective_message

    # yo'nalish nomini kutilayotgan holat
    if context.user_data.get("await") == "route":
        parsed = parse_route(text)
        if not parsed:
            await msg.reply_text("Format noto'g'ri. Masalan: Toshkent - Qibray")
            return
        context.user_data.pop("await", None)
        await db.add_route(parsed[0], parsed[1])
        await msg.reply_text(f"✅ Yo'nalish qo'shildi: {parsed[0]} → {parsed[1]}")
        body, markup = await _routes_view(db)
        await msg.reply_text(body, reply_markup=markup)
        return

    if text == A_ROUTES:
        body, markup = await _routes_view(db)
        await msg.reply_text(body, reply_markup=markup)
    elif text == A_DRIVERS:
        body, markup = await _drivers_view(db)
        await msg.reply_text(body, reply_markup=markup)
    elif text == A_REFRESH:
        await _board(context).force_repost()
        await msg.reply_text("✅ Guruh oynasi pastga qayta yuborildi.")
    elif text == A_SETTINGS:
        body, markup = await _settings_view(db)
        await msg.reply_text(body, reply_markup=markup)
    elif text == A_STATS:
        await msg.reply_text(await _stats_text(db))
    else:
        await msg.reply_text("🛠 Boshqaruv paneli", reply_markup=admin_menu_kb())


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
            InlineKeyboardButton(
                ("⛔ Yopish" if r["is_open"] else "🟢 Ochish"),
                callback_data=f"rtg:{r['id']}",
            ),
            InlineKeyboardButton("🗑 O'chirish", callback_data=f"rdl:{r['id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ Yangi yo'nalish", callback_data="ra")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _drivers_view(db) -> tuple[str, InlineKeyboardMarkup]:
    pending = await db.users_by_status("pending")
    approved = await db.users_by_status("approved")
    rows = []
    lines = [f"👥 Kutilayotgan arizalar: {len(pending)} ta"]
    for u in pending[:20]:
        lines.append(f"⏳ {u.full_name} — {u.phone}")
        rows.append([
            InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"dok:{u.tg_id}"),
            InlineKeyboardButton("❌ Rad etish", callback_data=f"dno:{u.tg_id}"),
        ])
    lines.append(f"\n✅ Tasdiqlangan haydovchilar: {len(approved)} ta")
    for u in approved[:20]:
        lines.append(f"🚗 {u.full_name} — {u.phone}")
        rows.append([InlineKeyboardButton(f"🚫 Bloklash: {u.first_name}",
                                          callback_data=f"dblk:{u.tg_id}")])
    if len(approved) > 20:
        lines.append(f"… yana {len(approved) - 20} ta (ro'yxat qisqartirilgan)")
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _settings_view(db) -> tuple[str, InlineKeyboardMarkup]:
    hours = await db.auto_stop_hours()
    minutes = await db.periodic_minutes()
    text = (
        "⚙️ Sozlamalar\n\n"
        f"⏰ Avtomatik to'xtash: {hours} soat (yangilanmagan e'lon)\n"
        f"🔁 Vaqt bo'yicha tekshiruv: har {minutes} daqiqada\n"
        "\nGuruh oynasi o'zgarganda 30 soniya kutiladi, ikki qayta yuborish orasi 2 daqiqa."
    )
    rows = [
        [InlineKeyboardButton(("✔ " if h == hours else "") + f"{h} soat",
                              callback_data=f"sauto:{h}") for h in AUTO_STOP_CHOICES],
        [InlineKeyboardButton(("✔ " if m == minutes else "") + f"{m} daq",
                              callback_data=f"sper:{m}") for m in PERIODIC_CHOICES],
    ]
    return text, InlineKeyboardMarkup(rows)


async def _stats_text(db) -> str:
    counts = await db.count_users_by_status()
    routes = await db.list_routes()
    open_routes = sum(1 for r in routes if r["is_open"])
    board = await db.board_routes()
    free_seats = sum(e["seats"] for r in board for e in r["entries"])
    active = await db.active_entry_count()
    return (
        "📊 Statistika\n\n"
        f"✅ Tasdiqlangan haydovchilar: {counts.get('approved', 0)}\n"
        f"⏳ Kutilayotgan arizalar: {counts.get('pending', 0)}\n"
        f"⛔ Bloklangan: {counts.get('blocked', 0)}\n\n"
        f"🛣 Ochiq yo'nalishlar: {open_routes} / {len(routes)}\n"
        f"🟢 Faol e'lonlar: {active}\n"
        f"🪑 Jami bo'sh joy (oynadagi): {free_seats}"
    )


# ══════════════════════════════════════════════════════════════════════════
# Inline tugmalar (callback)
# ══════════════════════════════════════════════════════════════════════════
MANAGER_ACTIONS = {"ra", "rtg", "rdl", "dok", "dno", "dblk", "dunb", "sauto", "sper"}


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    parts = query.data.split(":")
    action = parts[0]
    db = _db(context)

    # Ruxsatni tekshiramiz, keyin BIR MARTA answer() qilamiz
    if action in MANAGER_ACTIONS:
        if not await is_manager(context.bot, uid):
            await query.answer("Bu amal faqat adminlar uchun.", show_alert=True)
            return
        await query.answer()
        await _manager_callback(query, context, action, parts)
        return

    user = await db.get_user(uid)
    if not user or user.status != "approved":
        await query.answer("Sizda haydovchi huquqi yo'q.", show_alert=True)
        return
    await query.answer()
    await _driver_callback(query, context, uid, action, parts)


async def _manager_callback(query, context, action: str, parts: list[str]) -> None:
    db = _db(context)
    board = _board(context)

    if action == "ra":
        context.user_data["await"] = "route"
        await query.message.reply_text("Yangi yo'nalishni yozing (masalan: Toshkent - Qibray):")
        return

    if action == "rtg":
        route_id = int(parts[1])
        route = await db.get_route(route_id)
        if not route:
            return
        now_open = not route["is_open"]
        await db.set_route_open(route_id, now_open)
        if not now_open:
            await db.stop_route_entries(route_id)
        board.request_update()
        body, markup = await _routes_view(db)
        await _safe_edit(query, body, markup)
        return

    if action == "rdl":
        await db.delete_route(int(parts[1]))
        board.request_update()
        body, markup = await _routes_view(db)
        await _safe_edit(query, body, markup)
        return

    if action == "dok":
        target = int(parts[1])
        user = await db.get_user(target)
        if not user:
            return
        await db.update_user_fields(target, status="approved")
        await _notify(context, target,
                      "✅ Arizangiz tasdiqlandi! Endi 🚗 haydovchi panelidan foydalanishingiz mumkin.",
                      driver_menu_kb())
        await _safe_edit(query, f"✅ Tasdiqlandi: {user.full_name} — {user.phone}")
        return

    if action == "dno":
        target = int(parts[1])
        user = await db.get_user(target)
        await db.update_user_fields(target, status="blocked")
        await _notify(context, target, "❌ Afsuski, arizangiz rad etildi.")
        name = user.full_name if user else str(target)
        await _safe_edit(query, f"❌ Rad etildi: {name}")
        return

    if action == "dblk":
        target = int(parts[1])
        user = await db.get_user(target)
        await db.block_driver(target)
        board.request_update()
        await _notify(context, target, "⛔ Huquqingiz cheklandi. E'lonlaringiz oynadan olib tashlandi.")
        body, markup = await _drivers_view(db)
        await _safe_edit(query, body, markup)
        return

    if action == "dunb":
        target = int(parts[1])
        await db.update_user_fields(target, status="approved")
        await _notify(context, target, "✅ Huquqingiz qayta tiklandi.")
        body, markup = await _drivers_view(db)
        await _safe_edit(query, body, markup)
        return

    if action == "sauto":
        hours = int(parts[1])
        if hours in AUTO_STOP_CHOICES:
            await db.set_setting("auto_stop_hours", str(hours))
        body, markup = await _settings_view(db)
        await _safe_edit(query, body, markup)
        return

    if action == "sper":
        minutes = int(parts[1])
        if minutes in PERIODIC_CHOICES:
            await db.set_setting("periodic_minutes", str(minutes))
        body, markup = await _settings_view(db)
        await _safe_edit(query, body, markup)
        return


async def _driver_callback(query, context, uid: int, action: str, parts: list[str]) -> None:
    db = _db(context)
    board = _board(context)

    # Yo'nalish tanlandi -> bo'sh joy tanlash
    if action == "rt":
        route_id = int(parts[1])
        route = await db.get_route(route_id)
        if not route or not route["is_open"]:
            await _safe_edit(query, "Bu yo'nalish hozir yopiq.")
            return
        rows = _seat_rows(f"ns:{route_id}")
        await _safe_edit(
            query,
            f"📍 {route['from_place']} → {route['to_place']}\n\nNechta bo'sh joy bor?",
            InlineKeyboardMarkup(rows),
        )
        return

    # Yangi e'lon: yo'nalish + bo'sh joy
    if action == "ns":
        route_id, seats = int(parts[1]), int(parts[2])
        route = await db.get_route(route_id)
        if not route or not route["is_open"]:
            await _safe_edit(query, "Bu yo'nalish hozir yopiq.")
            return
        await db.start_entry(uid, route_id, seats)
        board.request_update()
        await _safe_edit(
            query,
            f"🟢 E'lon guruhga joylandi:\n📍 {route['from_place']} → {route['to_place']}\n"
            f"{seats_label(seats)}",
        )
        return

    # Bo'sh joy +1 / -1
    if action == "ea":
        entry = await db.get_entry_by_id(int(parts[1]))
        if not entry or entry["driver_id"] != uid or not entry["active"]:
            await _safe_edit(query, "Bu e'lon topilmadi yoki to'xtatilgan.")
            return
        delta = int(parts[2])
        new_seats = min(max(entry["seats"] + delta, 0), max(SEAT_OPTIONS))
        await db.set_entry_seats(entry["id"], new_seats)
        board.request_update()
        body, markup = await _my_entries_view(db, uid)
        await _safe_edit(query, body, markup)
        return

    # Aniq son tanlash menyusi
    if action == "ee":
        entry = await db.get_entry_by_id(int(parts[1]))
        if not entry or entry["driver_id"] != uid or not entry["active"]:
            await _safe_edit(query, "Bu e'lon topilmadi yoki to'xtatilgan.")
            return
        await _safe_edit(query, "Nechta bo'sh joy bor?",
                         InlineKeyboardMarkup(_seat_rows(f"es:{entry['id']}")))
        return

    # Aniq son saqlash
    if action == "es":
        entry = await db.get_entry_by_id(int(parts[1]))
        if not entry or entry["driver_id"] != uid or not entry["active"]:
            await _safe_edit(query, "Bu e'lon topilmadi yoki to'xtatilgan.")
            return
        await db.set_entry_seats(entry["id"], int(parts[2]))
        board.request_update()
        body, markup = await _my_entries_view(db, uid)
        await _safe_edit(query, body, markup)
        return

    # Bitta e'lonni to'xtatish
    if action == "st":
        entry = await db.get_entry_by_id(int(parts[1]))
        if not entry or entry["driver_id"] != uid:
            await _safe_edit(query, "Bu e'lon topilmadi.")
            return
        await db.stop_entry(entry["id"])
        board.request_update()
        await _safe_edit(query, "🔴 E'lon to'xtatildi va guruh oynasidan olib tashlandi.")
        return

    # Hammasini to'xtatish
    if action == "sa":
        count = await db.stop_all_for_driver(uid)
        if count:
            board.request_update()
        await _safe_edit(query, f"🔴 {count} ta e'lon to'xtatildi.")
        return


def _seat_rows(prefix: str) -> list[list[InlineKeyboardButton]]:
    """0..8 raqamli tugmalar, 3 tadan qator. prefix: 'ns:<rid>' yoki 'es:<eid>'."""
    buttons = [
        InlineKeyboardButton(str(n), callback_data=f"{prefix}:{n}") for n in SEAT_OPTIONS
    ]
    return [buttons[i:i + 3] for i in range(0, len(buttons), 3)]


# ══════════════════════════════════════════════════════════════════════════
# Guruh xabarlari
# ══════════════════════════════════════════════════════════════════════════
async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Guruhdagi har bir xabar — oxirgi xabar holatini kuzatish uchun."""
    msg = update.effective_message
    if msg is None:
        return
    if update.effective_user and update.effective_user.id == context.bot.id:
        return
    await _board(context).on_group_message(msg.message_id)


async def cmd_group_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Guruhda /yangila — admin oynani darhol pastga qayta yuboradi."""
    if not await is_manager(context.bot, update.effective_user.id):
        return
    await _board(context).force_repost()
    try:
        await update.effective_message.delete()
    except TelegramError:
        pass
