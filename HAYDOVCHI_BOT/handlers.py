"""
handlers.py — bot buyruqlari, tugmalar, ro'yxatdan o'tish, boshqaruv paneli, guruh xabarlari.

Rollar:
- Super admin (ADMIN_ID) va guruhlardagi adminlar (Telegram admin huquqi) — boshqaruv paneli.
- Haydovchi — ro'yxatdan o'tadi, admin tasdiqlaydi, obuna muddatini admin belgilaydi,
  so'ng start/stop va bo'sh joy tugmalarini ishlatadi.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

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

from config import ADMIN_ID, GROUP_CHAT_IDS
from db import end_of_day_ts, ts_to_date_str
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
SUB_CHOICES = [30, 90]                  # kun (tugmalar)


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


def _hub(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["hub"]


async def is_manager(bot, uid: int) -> bool:
    """Super admin, yoki boshqaruvchi guruhlardan birida admin/creator."""
    if uid == ADMIN_ID:
        return True
    for chat_id in GROUP_CHAT_IDS:
        try:
            member = await bot.get_chat_member(chat_id, uid)
            if member.status in ("creator", "administrator"):
                return True
        except TelegramError:
            continue
    return False


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
        return "❌ obuna yo'q (admin belgilaydi)"
    if paid_until < int(time.time()):
        return f"⛔ obuna tugagan ({ts_to_date_str(paid_until)})"
    return f"✅ obuna: {ts_to_date_str(paid_until)} gacha"


def _subscribed(user) -> bool:
    return user.paid_until > int(time.time())


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

    if await is_manager(context.bot, uid):
        await _manager_text(update, context, text)
        return

    db = _db(context)
    await db.ensure_user(uid)
    user = await db.get_user(uid)

    if user.status == "approved":
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
                f"⛔ Obuna muddati tugagan yoki belgilanmagan.\n{_sub_status(user.paid_until)}\n"
                "Obunani admin belgilaydi. Admin bilan bog'laning."
            )
            return
        routes = [r for r in await db.list_routes() if r["is_open"]]
        if not routes:
            await msg.reply_text("Hozircha ochiq yo'nalish yo'q. Admin yo'nalish ochishini kuting.")
            return
        rows = [
            [InlineKeyboardButton(f"📍 {r['from_place']} → {r['to_place']}",
                                  callback_data=f"rt:{r['id']}")]
            for r in routes
        ]
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
        rows = [
            [InlineKeyboardButton(f"🔴 {e['from_place']} → {e['to_place']}",
                                  callback_data=f"st:{e['id']}")]
            for e in entries
        ]
        await msg.reply_text("To'xtatmoqchi bo'lgan yo'nalishingizni tanlang:",
                             reply_markup=InlineKeyboardMarkup(rows))
        return

    if text == BTN_MY:
        body, markup = await _my_entries_view(db, uid)
        await msg.reply_text(body, reply_markup=markup)
        return

    if text == BTN_PROFILE:
        entries = await db.driver_entries(uid)
        await msg.reply_text(
            f"👤 {user.first_name} {user.last_name}\n📞 {user.phone}\n"
            f"📅 {_sub_status(user.paid_until)}\n"
            f"🟢 Faol e'lon: {len(entries)} ta"
        )
        return

    await msg.reply_text("🚗 Haydovchi paneli", reply_markup=driver_menu_kb())


async def _my_entries_view(db, uid: int) -> tuple[str, InlineKeyboardMarkup]:
    entries = await db.driver_entries(uid)
    if not entries:
        return ("Sizda faol e'lon yo'q. 🟢 Ishni boshlash tugmasini bosing.",
                InlineKeyboardMarkup([]))
    rows = []
    lines = ["📋 Faol e'loningiz:"]
    for e in entries:
        lines.append(f"📍 {e['from_place']} → {e['to_place']}: {seats_label(e['seats'])}")
        rows.append([
            InlineKeyboardButton("➖", callback_data=f"ea:{e['id']}:-1"),
            InlineKeyboardButton("➕", callback_data=f"ea:{e['id']}:1"),
            InlineKeyboardButton("🔢", callback_data=f"ee:{e['id']}"),
            InlineKeyboardButton("🔴", callback_data=f"st:{e['id']}"),
        ])
    lines.append("\n➖ odam oldi · ➕ joy bo'shadi · 🔢 aniq son · 🔴 to'xtatish")
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ══════════════════════════════════════════════════════════════════════════
# Boshqaruv paneli (super admin + guruh adminlari)
# ══════════════════════════════════════════════════════════════════════════
async def _manager_text(update, context, text: str) -> None:
    db = _db(context)
    msg = update.effective_message
    pending = context.user_data.get("await")

    if pending and pending[0] == "route":
        context.user_data.pop("await", None)
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
        if bad:
            out.append("⚠️ Tushunilmadi (format: Toshkent - Qibray):\n" + "\n".join(bad))
        await msg.reply_text("\n\n".join(out) or "Hech narsa qo'shilmadi.")
        if added:
            _hub(context).request_update_all()
        body, markup = await _routes_view(db)
        await msg.reply_text(body, reply_markup=markup)
        return

    if pending and pending[0] == "sub":
        context.user_data.pop("await", None)
        uid = pending[1]
        try:
            d = datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            await msg.reply_text("Sana formati noto'g'ri. Masalan: 2026-11-30")
            context.user_data["await"] = ("sub", uid)
            return
        await db.set_subscription_end(uid, end_of_day_ts(d))
        user = await db.get_user(uid)
        await msg.reply_text(f"✅ {user.full_name} obunasi {d.isoformat()} gacha belgilandi.")
        _hub(context).request_update_all()
        return

    if text == A_ROUTES:
        body, markup = await _routes_view(db)
        await msg.reply_text(body, reply_markup=markup)
    elif text == A_DRIVERS:
        body, markup = await _drivers_view(db)
        await msg.reply_text(body, reply_markup=markup)
    elif text == A_REFRESH:
        await _hub(context).force_all()
        await msg.reply_text("✅ Guruh oynalari pastga qayta yuborildi.")
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
            InlineKeyboardButton("⛔ Yopish" if r["is_open"] else "🟢 Ochish",
                                 callback_data=f"rtg:{r['id']}"),
            InlineKeyboardButton("🗑 O'chirish", callback_data=f"rdl:{r['id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ Yangi yo'nalish", callback_data="ra")])
    lines.append("\nYangi yo'nalish: bir qatorga bitta, masalan \"Toshkent - Qibray\".")
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
        lines.append(f"🚗 {u.full_name} — {u.phone}\n    {_sub_status(u.paid_until)}")
        rows.append([
            InlineKeyboardButton(f"📅 +{SUB_CHOICES[0]} kun", callback_data=f"sub:{u.tg_id}:{SUB_CHOICES[0]}"),
            InlineKeyboardButton(f"📅 +{SUB_CHOICES[1]} kun", callback_data=f"sub:{u.tg_id}:{SUB_CHOICES[1]}"),
            InlineKeyboardButton("📅 Sana", callback_data=f"sd:{u.tg_id}"),
        ])
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
        f"🪑 Jami bo'sh joy (oynadagi): {free_seats}\n"
        f"🏘 Boshqariladigan guruhlar: {len(GROUP_CHAT_IDS)}"
    )


# ══════════════════════════════════════════════════════════════════════════
# Inline tugmalar (callback)
# ══════════════════════════════════════════════════════════════════════════
MANAGER_ACTIONS = {"ra", "rtg", "rdl", "dok", "dno", "dblk", "dunb", "sub", "sd", "sauto", "sper"}


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    parts = query.data.split(":")
    action = parts[0]
    db = _db(context)

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
    hub = _hub(context)

    if action == "ra":
        context.user_data["await"] = ("route",)
        await query.message.reply_text(
            "Yangi yo'nalishni yozing. Bir nechta bo'lsa, har birini yangi qatordan yozing.\n"
            "Masalan:\nToshkent - Qibray\nQibray - Toshkent"
        )
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
        hub.request_update_all()
        body, markup = await _routes_view(db)
        await _safe_edit(query, body, markup)
        return

    if action == "rdl":
        await db.delete_route(int(parts[1]))
        hub.request_update_all()
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
                      "✅ Arizangiz tasdiqlandi! Obuna muddatini admin belgilagach ishlashingiz mumkin.",
                      driver_menu_kb())
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"📅 +{SUB_CHOICES[0]} kun", callback_data=f"sub:{target}:{SUB_CHOICES[0]}"),
            InlineKeyboardButton(f"📅 +{SUB_CHOICES[1]} kun", callback_data=f"sub:{target}:{SUB_CHOICES[1]}"),
            InlineKeyboardButton("📅 Sana", callback_data=f"sd:{target}"),
        ]])
        await _safe_edit(query,
                         f"✅ Tasdiqlandi: {user.full_name} — {user.phone}\n"
                         "Obuna muddatini belgilang:", markup)
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
        await db.block_driver(target)
        hub.request_update_all()
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

    if action == "sub":
        target, days = int(parts[1]), int(parts[2])
        await db.extend_subscription(target, days)
        user = await db.get_user(target)
        await _notify(context, target,
                      f"📅 Obuna yangilandi: {_sub_status(user.paid_until)}")
        hub.request_update_all()
        body, markup = await _drivers_view(db)
        await _safe_edit(query, body, markup)
        return

    if action == "sd":
        target = int(parts[1])
        context.user_data["await"] = ("sub", target)
        await query.message.reply_text(
            "Obuna tugash sanasini yozing (YYYY-MM-DD), masalan: 2026-11-30"
        )
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
    hub = _hub(context)
    user = await db.get_user(uid)

    if action in ("rt", "ns") and not _subscribed(user):
        await _safe_edit(query, f"⛔ Obuna tugagan yoki belgilanmagan.\n{_sub_status(user.paid_until)}")
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
        hub.request_update_all()
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
        hub.request_update_all()
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
        hub.request_update_all()
        body, markup = await _my_entries_view(db, uid)
        await _safe_edit(query, body, markup)
        return

    if action == "st":
        entry = await db.get_entry_by_id(int(parts[1]))
        if not entry or entry["driver_id"] != uid:
            await _safe_edit(query, "Bu e'lon topilmadi.")
            return
        await db.stop_entry(entry["id"])
        hub.request_update_all()
        await _safe_edit(query, "🔴 E'lon to'xtatildi va guruh oynasidan olib tashlandi.")
        return

    if action == "sa":
        count = await db.stop_all_for_driver(uid)
        if count:
            hub.request_update_all()
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
    if not await is_manager(context.bot, update.effective_user.id):
        return
    board = _hub(context).get(update.effective_chat.id)
    if board:
        await board.force_repost()
    try:
        await update.effective_message.delete()
    except TelegramError:
        pass
