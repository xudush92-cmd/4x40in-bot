import asyncio
import html
import logging
import re
import time

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from config import ADMIN_ID, BOT_TOKEN, missing_settings
from database import (
    MAX_USER_GROUPS,
    add_filter_word_checked,
    add_keyword_checked,
    delete_filter_word,
    get_client_words,
    get_filter_words_with_id,
    get_stop_words,
    add_user_group,
    approve_pending_session,
    clear_pending_session,
    clear_session,
    count_user_groups,
    delete_phrase,
    delete_user_completely,
    delete_user_group,
    get_all_phrases_with_id,
    get_all_user_groups,
    get_all_users,
    get_all_users_full,
    get_counter,
    get_keywords,
    get_match_count,
    get_setting,
    get_user,
    get_user_by_phone,
    get_user_counter,
    get_user_full,
    get_user_group,
    get_user_groups,
    get_user_match_count,
    get_user_scanner_enabled,
    init_db,
    is_subscription_active,
    requeue_user_group,
    set_new_term,
    set_pending_session,
    set_registration_info,
    set_user_match_count,
    set_user_scanner_enabled,
    set_setting,
    set_user_blocked,
    toggle_user_group,
    upsert_user,
)
from login_manager import (
    LoginError,
    check_session,
    cleanup as login_cleanup,
    request_code,
    revoke_session,
    sign_in_code,
    sign_in_password,
    take_signed_client,
    validate_account,
    validate_full_name,
    validate_phone,
)
from session_crypto import decrypt_session, encrypt_session
from matcher import (
    _MAX_PHRASE_WORDS,
    parse_key_words,
    split_entries,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BTN_ADD = "➕ Kalit so'z qo'shish"
BTN_PHRASES = "📋 Kalitlar ro'yxati"
BTN_GROUP_ADD = "➕ Guruh qo'shish"
BTN_GROUPS = "📋 Guruhlarim"
BTN_COUNT = "🔔 Xabar sharti"
BTN_TOGGLE = "⏸ To'xtatish / ▶️ Davom ettirish"
BTN_TEST = "🧪 Skaner testi"
BTN_USERS = "👥 Foydalanuvchilar"
BTN_STATS = "📊 Statistika"
BTN_BROADCAST = "📣 Xabar yuborish"
BTN_STOPWORDS = "🚫 Stop-so'zlar"
BTN_APPLICATIONS = "📝 Arizalar"
# Foydalanuvchi tugmalari (boshqaruv tugmalari ularda BO'LMAYDI)
BTN_LOGIN = "🔑 Login"
BTN_ACCOUNT = "📱 Akkaunt holati"
BTN_HELP = "ℹ️ Yordam"
# Foydalanuvchining UMUMIY skaner boshqaruvi (bitta tugma, menyuda)
BTN_SCAN_PAUSE = "🔴 ⏸ Stop"
BTN_SCAN_RESUME = "🟢 ▶️ Start"
MENU_BUTTONS = {
    BTN_ADD, BTN_PHRASES, BTN_GROUP_ADD, BTN_GROUPS,
    BTN_COUNT, BTN_TOGGLE, BTN_TEST, BTN_USERS, BTN_STATS,
    BTN_BROADCAST, BTN_APPLICATIONS, BTN_STOPWORDS,
    BTN_LOGIN, BTN_ACCOUNT, BTN_HELP, BTN_SCAN_PAUSE, BTN_SCAN_RESUME,
}
# Eski menyu tugmalari (yangilangach ham adashmaslik uchun)
_LEGACY_BUTTONS = {
    "➕ Yangi ibora qo'shish", "📋 Iboralar ro'yxati", "📋 Guruhlar ro'yxati",
}


class AdminFilter(BaseFilter):
    """Faqat ADMIN_ID egasiga ruxsat beradi (barcha handlerlarda)."""

    async def __call__(self, event: types.TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        return bool(ADMIN_ID) and user is not None and user.id == ADMIN_ID


class NotAdminFilter(BaseFilter):
    async def __call__(self, event: types.TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and not (
            bool(ADMIN_ID) and user.id == ADMIN_ID
        )


class AddPhrase(StatesGroup):
    waiting_phrase = State()  # kalit so'z(lar) kutilmoqda


class SetCount(StatesGroup):
    waiting_count = State()  # nechta so'z topilsa xabar berish soni kutilmoqda


class FilterWords(StatesGroup):
    waiting_word = State()  # stop-so'z yoki mijoz so'zi kutilmoqda (data: kind)


class AddGroup(StatesGroup):
    waiting_group = State()  # guruh manzili yoki ID kutilmoqda


class ScanTest(StatesGroup):
    waiting_text = State()  # tekshirish uchun namuna xabar kutilmoqda


class Registration(StatesGroup):
    full_name = State()
    phone = State()
    code = State()       # kod raqamli tugmalarda teriladi
    password = State()   # 2FA parol


class AdminTerm(StatesGroup):
    waiting_days = State()  # admin muddatni raqam bilan yozadi


class Broadcast(StatesGroup):
    choosing_audience = State()
    waiting_message = State()
    confirming = State()


def is_admin(user_id: int | None) -> bool:
    return bool(ADMIN_ID) and user_id is not None and user_id == ADMIN_ID


def main_menu(admin: bool = True) -> ReplyKeyboardMarkup:
    if admin:
        kb = [
            [KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_PHRASES)],
            [KeyboardButton(text=BTN_STOPWORDS), KeyboardButton(text=BTN_COUNT)],
            [KeyboardButton(text=BTN_USERS), KeyboardButton(text=BTN_APPLICATIONS)],
            [KeyboardButton(text=BTN_BROADCAST), KeyboardButton(text=BTN_STATS)],
            [KeyboardButton(text=BTN_TEST), KeyboardButton(text=BTN_TOGGLE)],
        ]
    else:
        kb = user_menu_keyboard()
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def user_menu_keyboard(connected: bool = True, scanner_enabled: bool = True):
    """Foydalanuvchi menyusi: bitta UMUMIY Stop/Start + skaner testi bor."""
    if not connected:
        return [
            [KeyboardButton(text=BTN_LOGIN)],
            [KeyboardButton(text=BTN_HELP)],
        ]
    toggle = BTN_SCAN_PAUSE if scanner_enabled else BTN_SCAN_RESUME
    return [
        # Umumiy Stop/Start — menyuning ENG TEPASIDA, alohida qatorda
        [KeyboardButton(text=toggle)],
        [KeyboardButton(text=BTN_GROUP_ADD), KeyboardButton(text=BTN_GROUPS)],
        [KeyboardButton(text=BTN_STATS), KeyboardButton(text=BTN_ACCOUNT)],
        [KeyboardButton(text=BTN_TEST), KeyboardButton(text=BTN_COUNT)],
        [KeyboardButton(text=BTN_HELP)],
    ]


def format_date(ts) -> str:
    if not ts:
        return "—"
    return time.strftime("%d.%m.%Y", time.localtime(int(ts)))


def subscription_text(user_row) -> str:
    """Foydalanuvchi tarif holati matni."""
    now = int(time.time())
    if not user_row:
        return "💳 Tarif: faol emas"
    _uid, _name, _uname, blocked, expires, _created = user_row
    if blocked:
        return "⛔ Hisobingiz bloklangan. Admin bilan bog'laning."
    if expires and expires > now:
        days = (expires - now + 86399) // 86400
        return (
            f"💳 Tarif: ✅ faol\n"
            f"📅 Tugash sanasi: <b>{format_date(expires)}</b> "
            f"({days} kun qoldi)"
        )
    return "💳 Tarif: ❌ faol emas (muddati tugagan yoki yoqilmagan)"


def user_connected(user_id: int) -> bool:
    row = get_user_full(user_id)
    return bool(row and row[8] and not row[10])


def user_menu_for(user_id: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=user_menu_keyboard(
            connected=user_connected(user_id),
            scanner_enabled=get_user_scanner_enabled(user_id),
        ),
        resize_keyboard=True,
    )


def account_status_text(user_id: int) -> str:
    row = get_user_full(user_id)
    if not row:
        return "📱 Akkaunt ulanmagan."
    (_uid, _name, _uname, blocked, expires, _created, full_name,
     phone, session_enc, pending_enc, awaiting, status, _warn, last_found,
     _scanner_on) = row
    if awaiting:
        conn = "⏳ Login qilingan — admin tasdig'i kutilmoqda"
    elif session_enc:
        conn = "✅ Telegram akkaunt ulangan"
    else:
        conn = "❌ Telegram akkaunt ulanmagan"
    phone_text = phone or "—"
    if phone and len(phone) > 6:
        phone_text = phone[:4] + " *** " + phone[-2:]
    last = (
        time.strftime("%d.%m.%Y %H:%M", time.localtime(last_found))
        if last_found else "hali yo'q"
    )
    return (
        "📱 <b>Akkaunt holati</b>\n\n"
        f"👤 Ism: <b>{html.escape(full_name or _name or '—')}</b>\n"
        f"📞 Telefon: <b>{html.escape(phone_text)}</b>\n"
        f"🔐 Sessiya: {conn} ({html.escape(status or 'none')})\n"
        f"📡 Skaner: {'▶️ yoniq' if _scanner_on else '⏸ oʻchirilgan'}\n"
        f"🔔 Xabar sharti: kamida <b>{get_user_match_count(_uid)}</b> ta kalit\n\n"
        + subscription_text(get_user(user_id))
        + f"\n🕐 Oxirgi topilgan xabar: {last}\n\n"
        "Tarif masalasi admin bilan og'zaki hal qilinadi."
    )


def current_status_text() -> str:
    return (
        f"🔑 Kalitlar soni: <b>{len(get_keywords())}</b> ta\n"
        f"🔔 Xabar sharti: kamida <b>{get_match_count()}</b> ta kalit so'z "
        "topilsa xabar beriladi"
    )


bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()
# DIQQAT: global admin filtri YO'Q — oddiy foydalanuvchilar ham botni
# ishlatadi. Har bir admin handlerida alohida AdminFilter() turadi.


# --- Handlers ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    # Har bir foydalanuvchi bazaga yoziladi (admin ro'yxatda ko'radi)
    is_new = get_user(user.id) is None
    upsert_user(user.id, user.first_name or "", user.username or "")

    if is_admin(user.id):
        await message.answer(
            "Assalomu alaykum, Admin! 👑 Boshqaruv paneli.\n\n"
            + current_status_text(),
            parse_mode="HTML",
            reply_markup=main_menu(admin=True),
        )
        return

    if is_new and ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                "🆕 <b>Yangi foydalanuvchi!</b>\n\n"
                f"👤 {html.escape(user.first_name or '')} "
                f"(@{html.escape(user.username or 'yoʻq')})\n"
                f"🆔 <code>{user.id}</code>\n\n"
                "Tarif yoqish: 👥 Foydalanuvchilar bo'limidan.",
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Yangi foydalanuvchi haqida adminga yuborilmadi")

    row = get_user(user.id)
    await message.answer(
        "Assalomu alaykum! 👋 Mijozlar xabarlarini qabul qilish "
        "botiga xush kelibsiz.\n\n"
        + subscription_text(row)
        + "\n\nTarif faol bo'lsa, topilgan xabarlar shu chatga keladi.",
        parse_mode="HTML",
        reply_markup=user_menu_for(user.id),
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await login_cleanup(message.from_user.id)
    await message.answer(
        "Bekor qilindi.",
        reply_markup=(
            main_menu(admin=True)
            if is_admin(message.from_user.id)
            else user_menu_for(message.from_user.id)
        ),
    )


# --- Oddiy foydalanuvchi: registratsiya (QR siz), akkaunt, guruhlar, statistika ---

def _numpad_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for chunk in (("1", "2", "3"), ("4", "5", "6"), ("7", "8", "9")):
        rows.append([
            InlineKeyboardButton(text=d, callback_data=f"code:{d}") for d in chunk
        ])
    rows.append([
        InlineKeyboardButton(text="⌫", callback_data="code:back"),
        InlineKeyboardButton(text="0", callback_data="code:0"),
        InlineKeyboardButton(text="✅", callback_data="code:ok"),
    ])
    rows.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="code:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _numpad_text(buffer: str, length: int = 5) -> str:
    dots = "●" * len(buffer) + "○" * max(0, length - len(buffer))
    return (
        "🔐 <b>Telegram tasdiq kodini kiriting</b>\n\n"
        f"<code>{dots}</code>\n\n"
        "Kod faqat quyidagi raqamli tugmalar bilan teriladi. "
        "Kodni oddiy xabar qilib yubormang."
    )


@dp.message(F.text == BTN_LOGIN)
async def begin_login(message: types.Message, state: FSMContext, user_id: int | None = None):
    uid = user_id or message.from_user.id
    if is_admin(uid):
        return
    row = get_user_full(uid)
    if row and row[3]:
        await message.answer("⛔ Hisobingiz bloklangan. Admin bilan bog'laning.")
        return
    if row and row[10]:
        await message.answer(
            "⏳ Arizangiz admin tasdig'ini kutmoqda.",
            reply_markup=user_menu_for(uid),
        )
        return
    if row and row[8]:
        await message.answer(
            "✅ Akkauntingiz allaqachon ulangan.",
            reply_markup=user_menu_for(uid),
        )
        return
    await login_cleanup(uid)
    if row and row[6] and row[7]:
        # Ism/telefon bor — darhol kod so'raymiz
        try:
            length = await request_code(uid, row[7])
        except LoginError as e:
            await message.answer(str(e), reply_markup=user_menu_for(uid))
            return
        if length == 0:
            await _complete_signed_in(message, state, uid)
            return
        await state.set_state(Registration.code)
        await state.update_data(code_buffer="", code_length=length, phone=row[7])
        await message.answer(_numpad_text("", length), parse_mode="HTML",
                             reply_markup=_numpad_keyboard())
        return
    await state.set_state(Registration.full_name)
    await message.answer(
        "👤 Ism va familiyangizni <b>bitta xabarda</b> yozing.\n"
        "Masalan: <i>Ali Valiyev</i>\n\nBekor qilish: /cancel",
        parse_mode="HTML",
    )


@dp.message(StateFilter(Registration.full_name), F.text)
async def reg_full_name(message: types.Message, state: FSMContext):
    if (message.text or "").strip() in MENU_BUTTONS | _LEGACY_BUTTONS:
        await state.clear()
        return
    name = " ".join((message.text or "").split())
    if not validate_full_name(name):
        await message.answer("⚠️ Ism va familiyani to'liq yozing. Masalan: <i>Ali Valiyev</i>", parse_mode="HTML")
        return
    set_registration_info(message.from_user.id, name)
    await state.set_state(Registration.phone)
    await message.answer(
        f"✅ {html.escape(name)}\n\n📱 Telefon raqamingizni yuboring:\n"
        "Format: <code>+998XXXXXXXXX</code>",
        parse_mode="HTML",
    )


@dp.message(StateFilter(Registration.phone), F.text)
async def reg_phone(message: types.Message, state: FSMContext):
    if (message.text or "").strip() in MENU_BUTTONS | _LEGACY_BUTTONS:
        await state.clear()
        return
    uid = message.from_user.id
    phone = validate_phone(message.text or "")
    if not phone:
        await message.answer("⚠️ Format noto'g'ri. Masalan: <code>+998901234567</code>", parse_mode="HTML")
        return
    owner = get_user_by_phone(phone)
    if owner and owner[0] != uid:
        await message.answer("⚠️ Bu telefon boshqa foydalanuvchiga tegishli.")
        return
    row = get_user_full(uid)
    set_registration_info(uid, (row[6] if row else "") or message.from_user.first_name or "", phone)
    try:
        length = await request_code(uid, phone)
    except LoginError as e:
        await state.clear()
        await message.answer(str(e), reply_markup=user_menu_for(uid))
        return
    if length == 0:
        await _complete_signed_in(message, state, uid)
        return
    await state.set_state(Registration.code)
    await state.update_data(code_buffer="", code_length=length, phone=phone)
    await message.answer(_numpad_text("", length), parse_mode="HTML",
                         reply_markup=_numpad_keyboard())


@dp.callback_query(StateFilter(Registration.code), F.data.startswith("code:"))
async def code_numpad(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    buffer = data.get("code_buffer", "")
    length = int(data.get("code_length") or 5)

    if action == "cancel":
        await login_cleanup(uid)
        await state.clear()
        await callback.message.edit_text("❌ Login bekor qilindi.")
        await callback.answer()
        return
    if action == "back":
        buffer = buffer[:-1]
    elif action == "ok":
        if len(buffer) < 4:
            await callback.answer("Kodni to'liq kiriting.", show_alert=True)
            return
        await callback.answer("Tekshirilmoqda...")
        await _try_code(callback.message, state, uid, buffer)
        return
    elif action.isdigit() and len(buffer) < 8:
        buffer += action

    await state.update_data(code_buffer=buffer)
    try:
        await callback.message.edit_text(
            _numpad_text(buffer, length), parse_mode="HTML",
            reply_markup=_numpad_keyboard(),
        )
    except Exception:
        pass
    await callback.answer()


async def _try_code(message: types.Message, state: FSMContext, uid: int, code: str):
    status, _client, me = await sign_in_code(uid, code)
    if status == "ok":
        error = validate_account(uid, me, (await state.get_data()).get("phone", ""))
        if error:
            await login_cleanup(uid)
            await state.clear()
            await message.answer(error, reply_markup=user_menu_for(uid))
            return
        await _complete_signed_in(message, state, uid)
        return
    if status == "password":
        await state.set_state(Registration.password)
        await message.answer(
            "🔐 Ikki bosqichli parolingizni (2FA) yuboring.\n"
            "Xabaringiz darhol o'chiriladi. Bekor qilish: /cancel"
        )
        return
    if status == "wrong":
        data = await state.get_data()
        length = int(data.get("code_length") or 5)
        await state.update_data(code_buffer="")
        await message.answer(
            "❌ Kod noto'g'ri. Qayta kiriting:",
            parse_mode="HTML",
        )
        await message.answer(_numpad_text("", length), parse_mode="HTML",
                             reply_markup=_numpad_keyboard())
        return
    await login_cleanup(uid)
    await state.clear()
    await message.answer(
        "❌ Kod muddati o'tgan yoki urinishlar tugadi. 🔑 Login dan qayta boshlang.",
        reply_markup=user_menu_for(uid),
    )


@dp.message(StateFilter(Registration.code), F.text)
async def code_as_text(message: types.Message, state: FSMContext):
    """Kodni matn qilib yuborsa — o'chiramiz va ogohlantiramiz (xavfsizlik)."""
    try:
        await message.delete()
    except Exception:
        pass
    data = await state.get_data()
    length = int(data.get("code_length") or 5)
    await message.answer(
        "⚠️ Kodni oddiy xabar qilib yubormang! Raqamli tugmalar bilan tering:",
        parse_mode="HTML",
    )
    await message.answer(_numpad_text(data.get("code_buffer", ""), length),
                         parse_mode="HTML", reply_markup=_numpad_keyboard())


@dp.message(StateFilter(Registration.password), F.text)
async def reg_password(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    password = message.text or ""
    try:
        await message.delete()
    except Exception:
        pass
    status, _client, me = await sign_in_password(uid, password)
    if status == "ok":
        error = validate_account(uid, me, (await state.get_data()).get("phone", ""))
        if error:
            await login_cleanup(uid)
            await state.clear()
            await message.answer(error, reply_markup=user_menu_for(uid))
            return
        await _complete_signed_in(message, state, uid)
        return
    await login_cleanup(uid)
    await state.clear()
    await message.answer(
        "❌ Parol noto'g'ri yoki login buzildi. 🔑 Login dan qayta boshlang.",
        reply_markup=user_menu_for(uid),
    )


async def _complete_signed_in(message: types.Message, state: FSMContext, uid: int):
    """Login tugadi: sessiya pending (shifrlangan) -> admin tasdig'i."""
    client = take_signed_client(uid)
    if client is None:
        await state.clear()
        await message.answer("❌ Login jarayoni buzildi. Qayta urining.",
                             reply_markup=user_menu_for(uid))
        return
    try:
        session_str = client.session.save()
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    set_pending_session(uid, encrypt_session(session_str))
    await state.clear()
    await message.answer(
        "✅ <b>Login muvaffaqiyatli!</b>\n\n"
        "⏳ Endi admin tasdiqlashini kuting — tasdiqlangach, akkauntingiz "
        "ishlaydi va xabar keladi.",
        parse_mode="HTML",
        reply_markup=user_menu_for(uid),
    )
    if ADMIN_ID:
        row = get_user_full(uid)
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"regok:{uid}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"regno:{uid}"),
        ]])
        try:
            await bot.send_message(
                ADMIN_ID,
                "🆕 <b>Ro'yxatdan o'tish arizasi!</b>\n\n"
                f"👤 {html.escape((row[6] or '') if row else '')} "
                f"(@{html.escape((row[2] or 'yoʻq') if row else '')})\n"
                f"📱 {html.escape((row[7] or '') if row else '')}\n"
                f"🆔 <code>{uid}</code>\n\n"
                "Tasdiqlasangiz, sessiya aktiv bo'ladi. Tarif muddatini "
                "keyin foydalanuvchi kartasidan ⏰ orqali berasiz.",
                parse_mode="HTML",
                reply_markup=kb,
            )
        except Exception:
            logger.exception("Adminga ariza xabari yuborilmadi")


@dp.callback_query(AdminFilter(), F.data.startswith("regok:"))
async def registration_approve(callback: types.CallbackQuery):
    try:
        uid = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato.", show_alert=True)
        return
    row = get_user_full(uid)
    if not row or not row[9]:
        await callback.answer("Pending sessiya topilmadi.", show_alert=True)
        return
    status, me = await check_session(decrypt_session(row[9]))
    if status == "temporary":
        await callback.answer(
            "⏳ Vaqtinchalik xato (Telegram/tarmoq). Sessiya saqlandi — keyinroq qayta bosing.",
            show_alert=True,
        )
        return
    if status != "ok" or not me or me.id != uid:
        # Yaroqsiz yoki boshqa akkaunt: pending tozalanadi, qayta login qiladi
        if status == "ok" and me:
            await revoke_session(decrypt_session(row[9]))
        clear_pending_session(uid)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.answer("❌ Sessiya yaroqsiz/mos emas — tozalandi", show_alert=True)
        try:
            await bot.send_message(uid, "❌ Sessiyangiz tasdiqlanmadi. 🔑 Login dan qayta kiring.")
        except Exception:
            pass
        return
    if not approve_pending_session(uid):
        await callback.answer("Holat o'zgargan.", show_alert=True)
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer("✅ Tasdiqlandi")
    try:
        import scanner_manager
        await scanner_manager.start_user_client(uid)
    except Exception:
        logger.exception("Client start (approve)")
    try:
        await bot.send_message(
            uid,
            "🎉 <b>Hisobingiz tasdiqlandi!</b>\n\n"
            "Endi guruhlaringizni qo'shishingiz mumkin. Topilgan xabarlar "
            "tarif faol bo'lganda keladi.\n\n" + account_status_text(uid),
            parse_mode="HTML",
            reply_markup=user_menu_for(uid),
        )
    except Exception:
        pass


@dp.callback_query(AdminFilter(), F.data.startswith("regno:"))
async def registration_reject(callback: types.CallbackQuery):
    try:
        uid = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato.", show_alert=True)
        return
    row = get_user_full(uid)
    if row and row[9]:
        await revoke_session(decrypt_session(row[9]))
    delete_user_completely(uid)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer("❌ Rad etildi, foydalanuvchi o'chirildi")
    try:
        await bot.send_message(uid, "❌ Ro'yxatdan o'tish arizangiz rad etildi.")
    except Exception:
        pass


# --- Foydalanuvchi: akkaunt holati ---
@dp.message(F.text == BTN_ACCOUNT)
async def account_status(message: types.Message, state: FSMContext):
    if is_admin(message.from_user.id):
        return
    await state.clear()
    uid = message.from_user.id
    # Bu bo'limda tugmalar yo'q — faqat holat ko'rsatiladi
    # (sessiyani uzish tugmasi olib tashlangan).
    await message.answer(account_status_text(uid), parse_mode="HTML")


@dp.callback_query(F.data == "sess_in")
async def sess_in_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await begin_login(callback.message, state, user_id=callback.from_user.id)


# --- Foydalanuvchi: o'z guruhlari ---
@dp.message(NotAdminFilter(), F.text == BTN_GROUP_ADD)
async def user_ask_group(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if not user_connected(uid):
        await message.answer(
            "Avval Telegram akkauntingizni ulang: 🔑 Login",
            reply_markup=user_menu_for(uid),
        )
        return
    if count_user_groups(uid) >= MAX_USER_GROUPS:
        await message.answer(f"⚠️ Limit: ko'pi bilan {MAX_USER_GROUPS} ta guruh qo'sha olasiz.")
        return
    await state.set_state(AddGroup.waiting_group)
    await message.answer(
        "Guruh <b>manzili yoki ID</b> sidan birini yuboring:\n\n"
        "• <code>@guruh_nomi</code> yoki <code>https://t.me/guruh_nomi</code>\n"
        "• <code>-1001234567890</code> (raqamli ID)\n\n"
        "⚠️ Ulangan Telegram akkauntingiz shu guruhda a'zo bo'lishi shart.\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML",
    )


@dp.message(NotAdminFilter(), StateFilter(AddGroup.waiting_group), F.text)
async def user_save_group(message: types.Message, state: FSMContext):
    if (message.text or "").strip() in MENU_BUTTONS | _LEGACY_BUTTONS:
        await state.clear()
        return
    uid = message.from_user.id
    value = normalize_group_input(message.text or "")
    if value is None:
        await message.answer("⚠️ Manzil (@username / t.me havola) yoki ID (-100...) yuboring.")
        return
    await state.clear()
    ok, err = add_user_group(uid, value)
    if not ok:
        await message.answer(f"⚠️ {html.escape(err)}", reply_markup=user_menu_for(uid))
        return
    await message.answer(
        f"✅ Guruh qabul qilindi: <b>{html.escape(value)}</b>\n"
        "⏳ Akkauntingiz orqali tekshirilmoqda (odatda 1 daqiqagacha). "
        "Holat: 📋 Guruhlarim",
        parse_mode="HTML",
        reply_markup=user_menu_for(uid),
    )


def _user_group_text(row) -> str:
    gid, owner, input_value, chat_id, title, is_active, status, last_error = row
    name = title or input_value
    if status == "ok":
        line = "✅ Kuzatuvda (umumiy Stop menyuda)"
    elif status == "pending":
        line = "⏳ Tekshirilmoqda..."
    else:
        line = f"⚠️ Xato: {last_error or 'nomaʼlum'}"
    return f"👥 <b>{html.escape(name or '')}</b>\n{line}"


def _user_group_keyboard(row) -> InlineKeyboardMarkup:
    # Stop/Start guruhga EMAS — bitta UMUMIY tugma menyuda. Bu yerda
    # faqat o'chirish (va xato bo'lsa qayta tekshirish) qoladi.
    gid, owner, input_value, chat_id, title, is_active, status, last_error = row
    rows = []
    if status == "ok":
        rows.append([
            InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"ugdel:{gid}"),
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="🔄 Qayta tekshirish", callback_data=f"ugrecheck:{gid}"),
            InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"ugdel:{gid}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(NotAdminFilter(), F.text.in_({BTN_GROUPS, "📋 Guruhlar ro'yxati"}))
async def user_list_groups(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    groups = get_user_groups(uid)
    if not groups:
        await message.answer(
            "Sizda hali guruhlar yo'q. ➕ Guruh qo'shish orqali qo'shing.",
            reply_markup=user_menu_for(uid),
        )
        return
    await message.answer(f"📋 Sizning guruhlaringiz — {len(groups)} ta:")
    for row in groups:
        await message.answer(_user_group_text(row), parse_mode="HTML",
                             reply_markup=_user_group_keyboard(row))


def _find_user_group(uid: int, gid: int):
    row = get_user_group(gid)
    return row if row and row[1] == uid else None


@dp.callback_query(F.data.startswith("ugact:"))
async def user_group_toggle(callback: types.CallbackQuery):
    uid = callback.from_user.id
    try:
        _, gid_s, cur_s = callback.data.split(":")
        gid, cur = int(gid_s), int(cur_s)
    except ValueError:
        await callback.answer("Xato.", show_alert=True)
        return
    if not _find_user_group(uid, gid):
        await callback.answer("Bu guruh sizniki emas.", show_alert=True)
        return
    new = 0 if cur == 1 else 1
    toggle_user_group(gid, uid, new)
    row = get_user_group(gid)
    if row:
        await callback.message.edit_text(
            _user_group_text(row), parse_mode="HTML",
            reply_markup=_user_group_keyboard(row))
    await callback.answer("⏸ Stop" if new == 0 else "▶️ Start")


@dp.callback_query(F.data.startswith("ugdel:"))
async def user_group_delete(callback: types.CallbackQuery):
    uid = callback.from_user.id
    try:
        gid = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato.", show_alert=True)
        return
    row = _find_user_group(uid, gid)
    if not row:
        await callback.answer("Bu guruh sizniki emas.", show_alert=True)
        return
    name = row[4] or row[2]
    delete_user_group(gid, uid)
    await callback.message.edit_text(
        f"🗑 Guruh o'chirildi: <b>{html.escape(str(name))}</b>\n"
        "Endi bu guruhdan sizga xabar kelmaydi.",
        parse_mode="HTML",
    )
    await callback.answer("O'chirildi")


@dp.callback_query(F.data.startswith("ugrecheck:"))
async def user_group_recheck(callback: types.CallbackQuery):
    uid = callback.from_user.id
    try:
        gid = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato.", show_alert=True)
        return
    if not _find_user_group(uid, gid):
        await callback.answer("Bu guruh sizniki emas.", show_alert=True)
        return
    requeue_user_group(gid)
    row = get_user_group(gid)
    if row:
        await callback.message.edit_text(
            _user_group_text(row), parse_mode="HTML",
            reply_markup=_user_group_keyboard(row))
    await callback.answer("🔄 Tekshiruvga qo'yildi")


# --- Foydalanuvchi: statistika (faqat o'ziniki) + yordam ---
@dp.message(NotAdminFilter(), F.text == BTN_STATS)
async def user_stats(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    groups = get_user_groups(uid)
    active_groups = sum(1 for g in groups if g[6] == "ok" and g[5] == 1)
    row = get_user_full(uid)
    last_found = (
        time.strftime("%d.%m.%Y %H:%M", time.localtime(row[13]))
        if row and row[13] else "hali yo'q"
    )
    await message.answer(
        "📊 <b>Sizning statistikangiz</b>\n\n"
        f"👥 Guruhlaringiz: <b>{len(groups)}</b> ta (faol: {active_groups} ta)\n"
        f"🚖 Topilgan xabarlar (jami): <b>{get_user_counter(uid, 'leads_found')}</b> ta\n"
        f"🕐 Oxirgi topilgan: {last_found}\n\n"
        + subscription_text(get_user(uid)),
        parse_mode="HTML",
        reply_markup=user_menu_for(uid),
    )


# --- Foydalanuvchi: UMUMIY Stop/Start (bitta tugma, menyuda) ---
@dp.message(NotAdminFilter(), F.text.in_({BTN_SCAN_PAUSE, BTN_SCAN_RESUME}))
async def user_scanner_toggle(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    enable = (message.text or "").strip() == BTN_SCAN_RESUME
    set_user_scanner_enabled(uid, enable)
    if enable:
        text = "🟢 <b>Skaner yoqildi.</b>\nGuruhlaringiz yana kuzatiladi."
    else:
        text = ("🔴 <b>Skaner to'xtatildi.</b>\nBarcha guruhlaringizdan "
                "xabar kelishi to'xtaydi (guruhlar o'chmaydi).")
    await message.answer(text, parse_mode="HTML", reply_markup=user_menu_for(uid))


# --- Skaner testi: to'liq zanjir hisoboti (test == real skaner) ---
_STATUS_ICON = {"ok": "✅", "fail": "❌", "skip": "⏭", "info": "ℹ️"}
_ORDINAL = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]


def scan_test_report(uid: int, text: str) -> str:
    """Namuna xabarni HAQIQIY skaner zanjiridan o'tkazib, hisobot beradi.

    filters.evaluate() — real skaner ishlatadigan aynan o'sha funksiya,
    shuning uchun bu yerda "o'tdi" degan xabar haqiqatda ham o'tadi.
    """
    from filters import evaluate

    verdict = evaluate(uid, text, check_group=False)
    lines = ["🧪 <b>Skaner testi</b>", ""]
    if verdict.ok:
        lines.append("🎯 <b>NATIJA: xabar KELADI</b>")
    else:
        lines.append(f"❌ <b>NATIJA: xabar KELMAYDI</b>")
        lines.append(f"Sabab: <b>{html.escape(verdict.detail, quote=False)}</b>")
    lines.append("")

    for index, stage in enumerate(verdict.stages):
        if index >= len(_ORDINAL):
            break
        icon = _STATUS_ICON.get(stage.status, "•")
        lines.append(
            f"{_ORDINAL[index]} {icon} <b>{html.escape(stage.title, quote=False)}</b>: "
            f"{html.escape(stage.text, quote=False)}"
        )

    warn = count_warning(verdict.required)
    if warn:
        lines += ["", warn]

    lines.append("")
    if verdict.ok:
        lines.append(
            "Shu xabar guruhga kelsa, bildirishnoma aynan sizga keladi."
        )
    else:
        lines.append(
            "Bu xabar guruhga kelsa ham bildirishnoma kelmaydi — "
            "sabab yuqorida ko'rsatilgan."
        )
    return "\n".join(lines)


def _user_scan_status_text(uid: int) -> str:
    groups = get_user_groups(uid)
    ok = sum(1 for g in groups if g[6] == "ok")
    pending = sum(1 for g in groups if g[6] == "pending")
    errored = sum(1 for g in groups if g[6] == "error")
    try:
        import scanner_manager

        online = scanner_manager.is_client_online(uid)
    except Exception:
        online = False
    lines = [
        "🧪 <b>Skaner testi — sizning holatingiz</b>",
        "",
        f"📱 Akkaunt: {'✅ ulangan' if user_connected(uid) else '❌ ulanmagan'}",
        f"🔐 Sessiya: {'✅ onlayn' if online else '❌ onlayn emas (server ishga tushganini tekshiring)'}",
        f"📡 Umumiy skaner: {'🟢 yoniq' if get_user_scanner_enabled(uid) else '🔴 oʻchirilgan — menyu tepasidagi 🟢 ▶️ Start ni bosing'}",
        f"👥 Guruhlaringiz: <b>{len(groups)}</b> ta (ulangan: {ok}, tekshiruvda: {pending}, xato: {errored})",
    ]
    if get_setting("is_active") != "1":
        lines.append("⚠️ Tizim admin tomonidan to'xtatilgan.")
    lines += ["", subscription_text(get_user(uid))]
    return "\n".join(lines)


# --- Foydalanuvchi: skaner testi (menyuda, bitta umumiy) ---
@dp.message(NotAdminFilter(), F.text == BTN_TEST)
async def user_scan_test_start(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if not user_connected(uid):
        await state.clear()
        await message.answer(
            "Avval Telegram akkauntingizni ulang: 🔑 Login",
            reply_markup=user_menu_for(uid),
        )
        return
    await state.set_state(ScanTest.waiting_text)
    await message.answer(
        _user_scan_status_text(uid)
        + "\n\n🧪 Endi <b>namuna xabar</b> yozib yuboring — shart "
        "bajarilishini tekshirib beraman. Bekor qilish: /cancel",
        parse_mode="HTML",
    )


@dp.message(NotAdminFilter(), StateFilter(ScanTest.waiting_text), F.text)
async def user_scan_test_check(message: types.Message, state: FSMContext):
    if (message.text or "").strip() in MENU_BUTTONS | _LEGACY_BUTTONS:
        await state.clear()
        return
    await state.clear()
    uid = message.from_user.id
    await message.answer(
        scan_test_report(uid, message.text or ""),
        parse_mode="HTML",
        reply_markup=user_menu_for(uid),
    )


# --- Foydalanuvchi: O'Z xabar sharti (har kimniki alohida) ---
def _user_count_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=str(n) + (" ⚠️" if n >= TOO_HIGH_COUNT else ""),
            callback_data=f"usetcnt:{n}",
        )
        for n in (1, 2, 3, 4, 5)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


@dp.message(NotAdminFilter(), F.text == BTN_COUNT)
async def user_ask_match_count(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    await state.set_state(SetCount.waiting_count)
    await message.answer(
        f"🔔 <b>Sizning xabar shartingiz:</b> xabarda kamida "
        f"<b>{get_user_match_count(uid)}</b> ta kalit so'z topilsa "
        "sizga xabar keladi.\n\n"
        "Yangi sonni tugmadan tanlang yoki raqam yozib yuboring "
        "(masalan: 2). Bu faqat <b>sizga</b> ta'sir qiladi.\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML",
        reply_markup=_user_count_keyboard(),
    )


async def _apply_user_match_count(message: types.Message, state: FSMContext,
                                  uid: int, value: int):
    total = len(get_keywords())
    await state.clear()
    if value < 1:
        await message.answer("⚠️ Son kamida 1 bo'lishi kerak.",
                             reply_markup=user_menu_for(uid))
        return
    set_user_match_count(uid, value)
    notes = []
    if total and value > total:
        notes.append(
            f"⚠️ Hozir kalitlar {total} ta, shartingiz {value} ta — "
            "bunday holda xabar kelmasligi mumkin."
        )
    warn = count_warning(value)
    if warn:
        notes.append(warn)
    note = ("\n\n" + "\n\n".join(notes)) if notes else ""
    await message.answer(
        f"✅ Sizning shartingiz o'rnatildi: kamida <b>{value}</b> ta "
        f"kalit so'z topilsa xabar keladi.{note}",
        parse_mode="HTML",
        reply_markup=user_menu_for(uid),
    )


@dp.callback_query(NotAdminFilter(), StateFilter(SetCount.waiting_count),
                   F.data.startswith("usetcnt:"))
async def user_set_count_callback(callback: types.CallbackQuery, state: FSMContext):
    try:
        value = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato ma'lumot.", show_alert=True)
        return
    await _apply_user_match_count(
        callback.message, state, callback.from_user.id, value)
    await callback.answer("Saqlandi!")


@dp.message(NotAdminFilter(), StateFilter(SetCount.waiting_count), F.text)
async def user_set_count_message(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text in MENU_BUTTONS | _LEGACY_BUTTONS:
        await state.clear()
        return
    if not text.isdigit():
        await message.answer("⚠️ Faqat raqam yuboring, masalan: 2")
        return
    await _apply_user_match_count(message, state, message.from_user.id, int(text))


@dp.message(F.text == BTN_HELP)
async def help_user(message: types.Message, state: FSMContext):
    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer("Siz adminsiz — menyudan foydalaning.",
                             reply_markup=main_menu(admin=True))
        return
    await message.answer(
        "ℹ️ <b>Yordam</b>\n\n"
        "• 🔑 Login — Telegram akkauntingizni ulaysiz (kod raqamli tugmalarda teriladi).\n"
        "• ➕ Guruh qo'shish — o'z guruhlaringizni kuzatuvga qo'shasiz, xabarlar faqat sizga keladi.\n"
        "• 🔔 Xabar sharti — xabarda nechta kalit topilsa sizga xabar kelishini o'zingiz belgilaysiz (faqat sizga ta'sir qiladi).\n"
        "• Tarif admin bilan og'zaki kelishiladi — botda to'lov yo'q.\n"
        "• Savollar bo'lsa adminga yozing.",
        parse_mode="HTML",
        reply_markup=user_menu_for(message.from_user.id),
    )



@dp.message(AdminFilter(), F.text == BTN_ADD)
async def ask_phrase(message: types.Message, state: FSMContext):
    await state.set_state(AddPhrase.waiting_phrase)
    await message.answer(
        "Kalit so'z yuboring. Har bir so'z — alohida kalit, "
        "so'zlar soni <b>cheklanmagan</b>.\n\n"
        "Bitta xabarda bir nechta so'z yuborsangiz, har biri alohida "
        "kalit bo'lib saqlanadi.\n"
        "Masalan: <i>toshkent samarqand odam mashina kerak yuk</i>\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML",
    )


@dp.message(AdminFilter(), StateFilter(AddPhrase.waiting_phrase), F.text)
async def save_new_phrase(message: types.Message, state: FSMContext):
    if (message.text or "").strip() in MENU_BUTTONS | _LEGACY_BUTTONS:
        await state.clear()
        return

    words = parse_key_words(message.text or "")
    if not words:
        await message.answer("⚠️ Kamida bitta so'z yozing.")
        return  # holatda qolamiz — qayta yozishi mumkin

    await state.clear()
    added, conflicts = [], []
    for word in words:
        is_added, where = add_keyword_checked(word)
        if is_added:
            added.append(word)
        else:
            conflicts.append((word, where))

    parts = []
    if added:
        parts.append(
            f"✅ Qo'shildi ({len(added)} ta): <b>{html.escape(', '.join(added))}</b>"
        )
    for word, where in conflicts:
        where_text = ", ".join(where) if where else "bazada"
        parts.append(
            f"⚠️ <b>{html.escape(word)}</b> — {html.escape(where_text)} "
            "ro'yxatida bor, qo'shilmadi."
        )
    parts.append("")
    parts.append(current_status_text())
    await message.answer(
        "\n".join(parts), parse_mode="HTML", reply_markup=main_menu()
    )


# --- Xabar berish sharti (admin belgilaydi / o'zgartiradi) ---
def _count_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=str(n) + (" ⚠️" if n >= TOO_HIGH_COUNT else ""),
            callback_data=f"setcnt:{n}",
        )
        for n in (1, 2, 3, 4, 5)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


@dp.message(AdminFilter(), F.text == BTN_COUNT)
async def ask_match_count(message: types.Message, state: FSMContext):
    await state.set_state(SetCount.waiting_count)
    await message.answer(
        f"Hozirgi UMUMIY (standart) shart: xabarda kamida <b>{get_match_count()}</b> ta "
        "kalit so'z topilsa xabar beriladi. Bu — o'z shartini "
        "belgilamagan foydalanuvchilar uchun standart qiymat.\n\n"
        "Yangi sonni tugmadan tanlang yoki o'zingiz raqam yozib yuboring "
        "(masalan: 6). Kalitlar nechta bo'lishidan qat'iy nazar, shu son ishlatiladi.\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML",
        reply_markup=_count_keyboard(),
    )


async def _apply_match_count(message: types.Message, state: FSMContext, value: int):
    total = len(get_keywords())
    await state.clear()
    if value < 1:
        await message.answer(
            "⚠️ Son kamida 1 bo'lishi kerak.", reply_markup=main_menu()
        )
        return
    set_setting("match_count", value)
    notes = []
    if total and value > total:
        notes.append(
            f"⚠️ Hozir kalitlar {total} ta, shart {value} ta — "
            "kalit qo'shmasangiz hech qachon xabar kelmaydi."
        )
    warn = count_warning(value)
    if warn:
        notes.append(warn)
    note = ("\n\n" + "\n\n".join(notes)) if notes else ""
    await message.answer(
        f"✅ Xabar sharti o'rnatildi: kamida <b>{value}</b> ta kalit so'z "
        f"topilsa xabar beriladi.{note}",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


@dp.callback_query(AdminFilter(), StateFilter(SetCount.waiting_count), F.data.startswith("setcnt:"))
async def set_count_callback(callback: types.CallbackQuery, state: FSMContext):
    try:
        value = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato ma'lumot.", show_alert=True)
        return
    await _apply_match_count(callback.message, state, value)
    await callback.answer("Saqlandi!")


@dp.message(AdminFilter(), StateFilter(SetCount.waiting_count), F.text)
async def set_count_message(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text in MENU_BUTTONS | _LEGACY_BUTTONS:
        await state.clear()
        return
    if not text.isdigit():
        await message.answer("⚠️ Faqat raqam yuboring, masalan: 3")
        return
    await _apply_match_count(message, state, int(text))


@dp.message(AdminFilter(), F.text == BTN_PHRASES)
async def list_phrases(message: types.Message, state: FSMContext):
    await state.clear()
    phrases = get_all_phrases_with_id()
    if not phrases:
        await message.answer("Ro'yxat bo'sh.")
        return

    await message.answer(
        f"Sizning kalit so'zlaringiz — jami {len(phrases)} ta "
        f"(o'chirish uchun tugmani bosing):"
    )
    for p_id, p_text in phrases:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"del:{p_id}")]
            ]
        )
        await message.answer(
            f"🔑 {html.escape(p_text)}", parse_mode="HTML", reply_markup=kb
        )


# --- Admin: stop-so'zlar (haydovchi filtri) va mijoz so'zlari ---
_FILTER_KIND = {
    "stop": ("stop_words", "🚫 Stop-so'zlar"),
    "client": ("client_words", "👤 Mijoz so'zlari"),
}


async def _send_filter_list(message: types.Message, kind: str):
    table, title = _FILTER_KIND[kind]
    entries = get_filter_words_with_id(table)
    add_cb = f"fadd:{kind}"
    await message.answer(
        f"{title} — jami {len(entries)} ta.\n"
        "O'chirish uchun yozuvning tugmasini bosing, qo'shish uchun "
        "pastdagi ➕ tugmani bosing.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="➕ Qo'shish", callback_data=add_cb)
        ]]),
    )
    for w_id, w_text in entries:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🗑 O'chirish", callback_data=f"fdel:{kind}:{w_id}")
        ]])
        await message.answer(
            f"{'🚫' if kind == 'stop' else '👤'} {html.escape(w_text)}",
            parse_mode="HTML", reply_markup=kb,
        )


@dp.message(AdminFilter(), F.text == BTN_STOPWORDS)
async def stopwords_menu(message: types.Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Stop-so'zlar", callback_data="flist:stop")],
        [InlineKeyboardButton(text="👤 Mijoz so'zlari", callback_data="flist:client")],
    ])
    await message.answer(
        "🚫 <b>Haydovchi filtri</b>\n\n"
        "0. <b>Emoji/stiker</b>: xabarda emoji bo'lsa yoki stiker bo'lsa — "
        "avtomatik bloklanadi.\n"
        "1. <b>Stop-so'zlar</b>: xabarda shulardan <b>bittasi</b> bo'lsa ham — "
        "xabar haydovchiniki, bloklanadi.\n"
        "2. <b>Mijoz so'zlari</b>: xabar o'tishi uchun mijozga xos so'zdan "
        "kamida bittasi bo'lishi kerak (asosiy kalitlardan tashqari).\n\n"
        "Barcha so'zlarni faqat admin kiritadi; takroriy so'z bazaga "
        "ikkinchi marta qo'shilmaydi.\n\n"
        "Qaysi ro'yxatni ochamiz?",
        parse_mode="HTML",
        reply_markup=kb,
    )


@dp.callback_query(AdminFilter(), F.data.startswith("flist:"))
async def filter_list_callback(callback: types.CallbackQuery):
    kind = callback.data.split(":", 1)[1]
    if kind not in _FILTER_KIND:
        await callback.answer("Xato.", show_alert=True)
        return
    await _send_filter_list(callback.message, kind)
    await callback.answer()


@dp.callback_query(AdminFilter(), F.data.startswith("fadd:"))
async def filter_add_start(callback: types.CallbackQuery, state: FSMContext):
    kind = callback.data.split(":", 1)[1]
    if kind not in _FILTER_KIND:
        await callback.answer("Xato.", show_alert=True)
        return
    await state.set_state(FilterWords.waiting_word)
    await state.update_data(filter_kind=kind)
    await callback.message.answer(
        "Yangi yozuvni yuboring — bitta so'z yoki ibora bo'lishi mumkin.\n"
        "Masalan: <i>odam olamiz</i>\n\n"
        "Bir nechta so'zni bir martada ham yuborishingiz mumkin — "
        "har biri alohida yozuv bo'ladi (qator, vergul yoki probil bilan):\n"
        "<i>olamiz, olaman, chiqamiz</i>\n\nBekor qilish: /cancel",
        parse_mode="HTML",
    )
    await callback.answer()


@dp.message(AdminFilter(), StateFilter(FilterWords.waiting_word), F.text)
async def filter_add_save(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text in MENU_BUTTONS | _LEGACY_BUTTONS:
        await state.clear()
        return
    data = await state.get_data()
    kind = data.get("filter_kind", "stop")
    table, title = _FILTER_KIND[kind]
    entries = split_entries(text)
    if not entries:
        await message.answer(
            "⚠️ Bo'sh yozuv qo'shib bo'lmaydi.",
            reply_markup=main_menu(admin=True),
        )
        return
    await state.clear()

    added: list[str] = []
    conflicts: list[tuple[str, list[str]]] = []
    for entry in entries:
        is_added, where = add_filter_word_checked(table, entry)
        if is_added:
            added.append(entry)
        else:
            conflicts.append((entry, where))

    parts: list[str] = []
    if added:
        shown = ", ".join(added[:20])
        if len(added) > 20:
            shown += f" ... (+{len(added) - 20} ta)"
        parts.append(
            f"✅ <b>{title}</b>ga qo'shildi ({len(added)} ta):\n"
            f"{html.escape(shown)}"
        )
    for entry, where in conflicts[:10]:
        where_text = ", ".join(where) if where else "bazada"
        parts.append(
            f"⚠️ <b>{html.escape(entry.lower())}</b> — "
            f"{html.escape(where_text)} ro'yxatida bor, qo'shilmadi."
        )
    if len(conflicts) > 10:
        parts.append(f"⚠️ yana {len(conflicts) - 10} ta yozuv qo'shilmadi.")
    if not parts:
        parts.append("⚠️ Hech narsa qo'shilmadi.")
    # Uzun qator probil bilan yuborilgan bo'lsa, iboralar so'zlarga
    # bo'linib ketadi: "joy bor" -> "joy" + "bor". Bu xavfli, ogohlantiramiz.
    if any(
        len(line.split()) > _MAX_PHRASE_WORDS for line in text.splitlines()
    ):
        parts.append(
            "ℹ️ Probel bilan ajratilgan ro'yxat so'zlarga bo'lindi. "
            "Iboralar (<i>joy bor</i>, <i>kim olib ketadi</i>) buzilmasligi "
            "uchun ularni har birini alohida qatorda yuboring."
        )
    parts.append("")
    parts.append(f"Jami yuborildi: {len(entries)} ta.")
    await message.answer(
        "\n".join(parts), parse_mode="HTML", reply_markup=main_menu(admin=True)
    )


@dp.callback_query(AdminFilter(), F.data.startswith("fdel:"))
async def filter_delete_callback(callback: types.CallbackQuery):
    try:
        _f, kind, w_id = callback.data.split(":")
        w_id = int(w_id)
    except (ValueError, IndexError):
        await callback.answer("Xato ma'lumot.", show_alert=True)
        return
    if kind not in _FILTER_KIND:
        await callback.answer("Xato.", show_alert=True)
        return
    delete_filter_word(_FILTER_KIND[kind][0], w_id)
    await callback.message.edit_text("🗑 O'chirildi!")
    await callback.answer()


@dp.callback_query(AdminFilter(), F.data.startswith("del:"))
async def delete_phrase_callback(callback: types.CallbackQuery):
    try:
        p_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Xato ma'lumot.", show_alert=True)
        return
    delete_phrase(p_id)
    await callback.message.edit_text("🗑 O'chirildi!")
    await callback.answer()


def normalize_group_input(text: str) -> str | None:
    """Guruh manzili yoki ID ni yagona ko'rinishga keltiradi.

    Qabul qilinadi: @username, t.me/username havolasi, t.me/+... taklif
    havolasi, raqamli ID (-100...). Aniqlanmasa None.
    """
    t = (text or "").strip()
    if re.fullmatch(r"-?\d{5,}", t):
        return t
    if "t.me/+" in t or "t.me/joinchat/" in t:
        return t
    m = re.search(r"(?:t\.me/|@)([A-Za-z0-9_]{5,})", t)
    if m:
        return "@" + m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_]{5,}", t):
        return "@" + t
    return None


# --- Admin: foydalanuvchilar boshqaruvi (bitta to'liq kartochka) ---
def _short_text(value, limit: int = 38) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _admin_user_card_text(row) -> str:
    """Bitta foydalanuvchi haqida barcha ma'lumot bitta kartochkada.

    Alohida "guruhlar" bo'limi yo'q: guruhlar, shart, skaner holati,
    tarif, sessiya va statistika shu kartochkaning o'zida ko'rsatiladi.
    """
    (uid, first_name, uname, blocked, expires, created, full_name, phone,
     session_enc, pending_enc, awaiting, session_status, _warn,
     last_found, scanner_enabled) = row
    now = int(time.time())
    groups = get_user_groups(uid)
    ok_groups = [g for g in groups if g[6] == "ok"]
    pending_groups = [g for g in groups if g[6] == "pending"]
    error_groups = [g for g in groups if g[6] == "error"]

    try:
        import scanner_manager

        client_online = scanner_manager.is_client_online(uid)
    except Exception:
        client_online = False

    if blocked:
        tariff_line = "⛔ Bloklangan"
    elif expires and expires > now:
        days = (expires - now + 86399) // 86400
        tariff_line = (
            f"✅ Faol — {format_date(expires)} gacha ({days} kun qoldi)"
        )
    else:
        tariff_line = "❌ Faol emas / muddati tugagan"

    if awaiting:
        session_line = "⏳ Login qilingan, admin tasdig'i kutilmoqda"
    elif session_enc:
        session_line = (
            f"{'✅ Ulangan, client onlayn' if client_online else '⚠️ Sessiya bor, client offline'}"
            f" ({html.escape(session_status or 'unknown')})"
        )
    else:
        session_line = "❌ Telegram akkaunt ulanmagan"

    keywords = get_keywords()
    required = get_user_match_count(uid)
    if not keywords:
        condition_line = "❌ Kalit so'zlar kiritilmagan"
        condition_ok = False
    elif required > len(keywords):
        condition_line = (
            f"⚠️ Kamida {required} ta kalit kerak, lekin kalitlar "
            f"{len(keywords)} ta — shart bajarilmaydi"
        )
        condition_ok = False
    else:
        condition_line = (
            f"✅ Kamida {required} ta kalit topilsa xabar boradi "
            f"(kalitlar: {len(keywords)} ta)"
        )
        condition_ok = True

    system_on = get_setting("is_active") == "1"
    if blocked:
        working_line = "❌ Ishlamaydi — foydalanuvchi bloklangan"
    elif awaiting or not session_enc:
        working_line = "❌ Ishlamaydi — akkaunt tasdiqlanmagan/ulanmagan"
    elif not system_on:
        working_line = "❌ Ishlamaydi — admin tizimni umumiy to'xtatgan"
    elif not (expires and expires > now):
        working_line = "❌ Ishlamaydi — tarif faol emas"
    elif not scanner_enabled:
        working_line = "❌ Ishlamaydi — foydalanuvchi umumiy Stop bosgan"
    elif not client_online:
        working_line = "⚠️ Ishlamayapti — sessiya clienti hozir offline"
    elif not ok_groups:
        working_line = "❌ Ishlamaydi — tayyor ulangan guruh yo'q"
    elif not condition_ok:
        working_line = "❌ Ishlamaydi — xabar sharti bajarilmaydigan holatda"
    else:
        working_line = "✅ Ishlayapti — guruhlar kuzatilmoqda"

    if groups:
        group_lines = []
        for index, g in enumerate(groups, 1):
            name = _short_text(g[4] or g[2] or "Nomsiz guruh")
            if g[6] == "ok":
                state = "✅ ulangan"
            elif g[6] == "pending":
                state = "⏳ tekshiruvda"
            else:
                state = f"⚠️ xato: {_short_text(g[7] or 'nomaʼlum', 55)}"
            group_lines.append(
                f"{index}. {html.escape(name)} — {state}"
            )
        groups_text = "\n".join(group_lines)
    else:
        groups_text = "Guruh qo'shilmagan"

    last_found_text = (
        time.strftime("%d.%m.%Y %H:%M", time.localtime(last_found))
        if last_found else "hali yo'q"
    )
    created_text = format_date(created) if created else "—"
    display_name = full_name or first_name or "—"
    username_text = f"@{html.escape(uname)}" if uname else "username yo'q"

    return (
        "👤 <b>Foydalanuvchi kartochkasi</b>\n\n"
        f"👤 Ism: <b>{html.escape(display_name)}</b> ({username_text})\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"📱 Telefon: <b>{html.escape(phone or '—')}</b>\n"
        f"🗓 Ro'yxatdan o'tgan: {created_text}\n\n"
        f"💳 Tarif: {tariff_line}\n"
        f"🔐 Sessiya: {session_line}\n"
        f"📡 Foydalanuvchi skaneri: {'🟢 Start holatida' if scanner_enabled else '🔴 Stop holatida'}\n"
        f"⚙️ Umumiy tizim: {'✅ yoniq' if system_on else '⏸ admin toʻxtatgan'}\n"
        f"🧪 Skaner holati: <b>{working_line}</b>\n\n"
        f"🔔 Xabar sharti: {condition_line}\n"
        f"🚫 Haydovchi filtri: faol (emoji/stiker blok, "
        f"{len(get_stop_words())} stop-so'z, "
        f"{len(get_client_words())} mijoz so'zi)\n\n"
        f"👥 <b>Guruhlari: {len(groups)} ta</b> "
        f"(ulangan: {len(ok_groups)}, tekshiruvda: {len(pending_groups)}, "
        f"xato: {len(error_groups)})\n"
        f"{groups_text}\n\n"
        "📊 <b>Statistikasi</b>\n"
        f"🚖 Topilgan xabarlar: <b>{get_user_counter(uid, 'leads_found')}</b> ta\n"
        f"🕐 Oxirgi topilgan xabar: {last_found_text}"
    )


def _user_keyboard(uid: int, blocked: int, with_back: bool = True) -> InlineKeyboardMarkup:
    block_btn = (
        InlineKeyboardButton(
            text="✅ Blokdan chiqarish", callback_data=f"ublock:{uid}"
        )
        if blocked
        else InlineKeyboardButton(
            text="⛔ Bloklash", callback_data=f"ublock:{uid}"
        )
    )
    rows = [
        [
            InlineKeyboardButton(
                text="⏰ Muddat berish", callback_data=f"uterm:{uid}"
            ),
            block_btn,
        ],
        [
            InlineKeyboardButton(
                text="🔄 Kartochkani yangilash",
                callback_data=f"urefresh:{uid}",
            ),
            InlineKeyboardButton(
                text="🔌 Sessiyani uzish", callback_data=f"ukick:{uid}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="🗑 Foydalanuvchini o'chirish",
                callback_data=f"udel:{uid}",
            )
        ],
    ]
    if with_back:
        rows.append([
            InlineKeyboardButton(text="⬅️ Orqaga", callback_data="uback")
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _users_list_keyboard(users) -> InlineKeyboardMarkup:
    """Ro'yxat: har bir foydalanuvchi — ism-familiya yozilgan tugma."""
    rows = []
    now = int(time.time())
    for row in users:
        uid, blocked, expires, awaiting = row[0], row[3], row[4], row[10]
        if blocked:
            icon = "⛔"
        elif awaiting:
            icon = "⏳"
        elif expires and expires > now:
            icon = "✅"
        else:
            icon = "❌"
        name = _short_text(row[6] or row[1] or "Nomsiz", 30)
        rows.append([InlineKeyboardButton(
            text=f"{icon} {name}", callback_data=f"ucard:{uid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _users_list_text(users) -> str:
    active_n = sum(
        1 for u in users if is_subscription_active(u[0]) and not u[3]
    )
    return (
        f"👥 <b>Foydalanuvchilar: {len(users)} ta</b> "
        f"(faol tarif: {active_n} ta)\n\n"
        "Kartochkasini ochish uchun ismni bosing 👇"
    )


@dp.message(AdminFilter(), F.text == BTN_USERS)
async def list_users(message: types.Message, state: FSMContext):
    await state.clear()
    users = [u for u in get_all_users_full() if u[0] != ADMIN_ID]
    if not users:
        await message.answer(
            "👥 Hozircha foydalanuvchilar yo'q.\n"
            "Bot havolasini ulashing — /start bosganlar shu yerda chiqadi."
        )
        return
    await message.answer(
        _users_list_text(users),
        parse_mode="HTML",
        reply_markup=_users_list_keyboard(users),
    )


@dp.callback_query(AdminFilter(), F.data.startswith("ucard:"))
async def open_user_card(callback: types.CallbackQuery):
    try:
        user_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato.", show_alert=True)
        return
    row = get_user_full(user_id)
    if not row:
        await callback.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return
    await callback.message.edit_text(
        _admin_user_card_text(row),
        parse_mode="HTML",
        reply_markup=_user_keyboard(row[0], row[3], with_back=True),
    )
    await callback.answer()


@dp.callback_query(AdminFilter(), F.data == "uback")
async def back_to_users(callback: types.CallbackQuery):
    users = [u for u in get_all_users_full() if u[0] != ADMIN_ID]
    if not users:
        await callback.message.edit_text("👥 Foydalanuvchilar yo'q.")
        await callback.answer()
        return
    await callback.message.edit_text(
        _users_list_text(users),
        parse_mode="HTML",
        reply_markup=_users_list_keyboard(users),
    )
    await callback.answer()


async def _refresh_user_card(callback: types.CallbackQuery, user_id: int):
    row = get_user_full(user_id)
    if row:
        await callback.message.edit_text(
            _admin_user_card_text(row),
            parse_mode="HTML",
            reply_markup=_user_keyboard(row[0], row[3]),
        )


@dp.callback_query(AdminFilter(), F.data.startswith("urefresh:"))
async def refresh_user_card_callback(callback: types.CallbackQuery):
    try:
        user_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato.", show_alert=True)
        return
    await _refresh_user_card(callback, user_id)
    await callback.answer("🔄 Yangilandi")



async def _apply_new_term(admin_message: types.Message, target_id: int, days: int):
    """Yangi muddat eskisini BEKOR qiladi (ustiga qo'shilmaydi)."""
    old = get_user(target_id)
    old_text = format_date(old[4]) if old and old[4] else "yo'q edi"
    expiry = set_new_term(target_id, days)
    await admin_message.answer(
        f"✅ Yangi muddat berildi: <b>{format_date(expiry)}</b> gacha "
        f"({days} kun, hozirdan).\nBekor qilingan eski muddat: {old_text}",
        parse_mode="HTML",
    )
    try:
        await bot.send_message(
            target_id,
            "⏰ <b>Tarifingiz yangilandi!</b>\n\n"
            f"📅 Amal qilish muddati: <b>{format_date(expiry)}</b> gacha.",
            parse_mode="HTML",
        )
    except Exception:
        pass


@dp.callback_query(AdminFilter(), F.data.startswith("uterm:"))
async def user_term_start(callback: types.CallbackQuery, state: FSMContext):
    try:
        user_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{d} kun", callback_data=f"utermset:{user_id}:{d}")
         for d in (1, 7, 30)],
        [InlineKeyboardButton(text="90 kun", callback_data=f"utermset:{user_id}:90"),
         InlineKeyboardButton(text="✏️ Qo'lda yozish", callback_data=f"utermwrite:{user_id}")],
    ])
    await callback.message.answer(
        "⏰ Yangi muddat tanlang yoki qo'lda yozing.\n"
        "⚠️ Yangi muddat <b>eskisini bekor qiladi</b> — ustiga qo'shilmaydi.",
        parse_mode="HTML", reply_markup=kb,
    )
    await callback.answer()


@dp.callback_query(AdminFilter(), F.data.startswith("utermset:"))
async def user_term_set(callback: types.CallbackQuery, state: FSMContext):
    try:
        _p, uid_s, days_s = callback.data.split(":")
        user_id, days = int(uid_s), int(days_s)
    except ValueError:
        await callback.answer("Xato.", show_alert=True)
        return
    await _apply_new_term(callback.message, user_id, days)
    await callback.answer("✅ Muddat berildi")


@dp.callback_query(AdminFilter(), F.data.startswith("utermwrite:"))
async def user_term_write(callback: types.CallbackQuery, state: FSMContext):
    try:
        user_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato.", show_alert=True)
        return
    await state.set_state(AdminTerm.waiting_days)
    await state.update_data(term_target=user_id)
    await callback.message.answer(
        "✏️ Muddatni kun hisobida yozing (masalan: 45).\n"
        "⚠️ Yangi muddat eskisini bekor qiladi. Bekor qilish: /cancel"
    )
    await callback.answer()


@dp.message(AdminFilter(), StateFilter(AdminTerm.waiting_days), F.text)
async def user_term_days_input(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit() or not (1 <= int(text) <= 3650):
        await message.answer("⚠️ 1 dan 3650 gacha butun son yozing.")
        return
    data = await state.get_data()
    target = data.get("term_target")
    await state.clear()
    if target:
        await _apply_new_term(message, int(target), int(text))


@dp.callback_query(AdminFilter(), F.data.startswith("ukick:"))
async def admin_user_kick_session(callback: types.CallbackQuery):
    try:
        user_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato.", show_alert=True)
        return
    try:
        import scanner_manager
        await scanner_manager.stop_user_client(user_id, revoke=True)
    except Exception:
        logger.exception("Admin sessiya uzish")
    clear_session(user_id)
    await callback.answer("🔌 Sessiya uzildi", show_alert=True)


@dp.callback_query(AdminFilter(), F.data.startswith("udel:"))
async def admin_user_delete(callback: types.CallbackQuery):
    try:
        user_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato.", show_alert=True)
        return
    try:
        import scanner_manager
        await scanner_manager.stop_user_client(user_id, revoke=True)
    except Exception:
        pass
    row = get_user_full(user_id)
    if row and row[8]:
        await revoke_session(decrypt_session(row[8]))
    delete_user_completely(user_id)
    await callback.message.edit_text("🗑 Foydalanuvchi butunlay o'chirildi.")
    await callback.answer("O'chirildi")


@dp.callback_query(AdminFilter(), F.data.startswith("ublock:"))
async def user_block_callback(callback: types.CallbackQuery):
    try:
        user_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato.", show_alert=True)
        return
    row = get_user(user_id)
    if not row:
        await callback.answer("Topilmadi.", show_alert=True)
        return
    set_user_blocked(user_id, not bool(row[3]))
    await _refresh_user_card(callback, user_id)
    await callback.answer("⛔ Bloklandi" if not row[3] else "✅ Blokdan chiqarildi")


# --- Admin: ro'yxatdan o'tish arizalari ---
@dp.message(AdminFilter(), F.text == BTN_APPLICATIONS)
async def list_applications(message: types.Message, state: FSMContext):
    await state.clear()
    pending = [u for u in get_all_users_full() if u[10] and u[0] != ADMIN_ID]
    if not pending:
        await message.answer("📝 Tasdiq kutayotgan arizalar yo'q.")
        return
    await message.answer(f"📝 Arizalar: {len(pending)} ta")
    for row in pending:
        uid = row[0]
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"regok:{uid}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"regno:{uid}"),
        ]])
        await message.answer(
            f"👤 {html.escape(row[6] or row[1] or '—')} "
            f"(@{html.escape(row[2] or 'yoʻq')})\n"
            f"📱 {html.escape(row[7] or '')}\n🆔 <code>{uid}</code>",
            parse_mode="HTML",
            reply_markup=kb,
        )


# --- Admin: foydalanuvchilarga xabar yuborish (broadcast) ---
_BROADCAST_AUDIENCES = {
    "all": "👥 Hammaga",
    "active": "✅ Tarifi faol",
    "expiring": "⏰ Tugayotganlar (3 kun)",
    "expired": "❌ Tarifi tugaganlar",
}


def _broadcast_recipients(kind: str) -> list[int]:
    import time as _t

    now = int(_t.time())
    users = [u for u in get_all_users_full() if u[0] != ADMIN_ID and not u[3]]
    if kind == "active":
        return [u[0] for u in users if (u[4] or 0) > now]
    if kind == "expiring":
        return [u[0] for u in users if now < (u[4] or 0) <= now + 3 * 86400]
    if kind == "expired":
        return [u[0] for u in users if (u[4] or 0) <= now]
    return [u[0] for u in users]


@dp.message(AdminFilter(), F.text == BTN_BROADCAST)
async def broadcast_start(message: types.Message, state: FSMContext):
    await state.set_state(Broadcast.choosing_audience)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"bcast:{key}")]
        for key, label in _BROADCAST_AUDIENCES.items()
    ])
    await message.answer("📣 Kimlarga yuboramiz?", reply_markup=kb)


@dp.callback_query(AdminFilter(), StateFilter(Broadcast.choosing_audience),
                   F.data.startswith("bcast:"))
async def broadcast_audience(callback: types.CallbackQuery, state: FSMContext):
    kind = callback.data.split(":", 1)[1]
    recipients = _broadcast_recipients(kind)
    await state.update_data(bcast_kind=kind, bcast_recipients=recipients)
    await state.set_state(Broadcast.waiting_message)
    await callback.message.answer(
        f"{_BROADCAST_AUDIENCES.get(kind, kind)} — {len(recipients)} kishi.\n"
        "Endi xabarni yuboring (matn yoki rasm+hujjat, izohi bilan)."
    )
    await callback.answer()


@dp.message(AdminFilter(), StateFilter(Broadcast.waiting_message),
            F.text | F.photo | F.document | F.video)
async def broadcast_collect(message: types.Message, state: FSMContext):
    data = await state.get_data()
    recipients = data.get("bcast_recipients") or []
    await state.update_data(
        bcast_from_chat=message.chat.id, bcast_from_msg=message.message_id
    )
    await state.set_state(Broadcast.confirming)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Yuborish", callback_data="bcastgo"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="bcastcancel"),
    ]])
    await message.answer(
        f"📣 Xabar <b>{len(recipients)}</b> kishiga yuboriladi. Tasdiqlaysizmi?",
        parse_mode="HTML",
        reply_markup=kb,
    )


@dp.callback_query(AdminFilter(), StateFilter(Broadcast.confirming),
                   F.data == "bcastcancel")
async def broadcast_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Xabar yuborish bekor qilindi.")
    await callback.answer()


@dp.callback_query(AdminFilter(), StateFilter(Broadcast.confirming),
                   F.data == "bcastgo")
async def broadcast_go(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    recipients = data.get("bcast_recipients") or []
    from_chat, from_msg = data.get("bcast_from_chat"), data.get("bcast_from_msg")
    await state.clear()
    await callback.answer("Yuborilmoqda...")
    sent = failed = 0
    for uid in recipients:
        try:
            await bot.copy_message(
                chat_id=uid, from_chat_id=from_chat, message_id=from_msg
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # Telegram limiti uchun pauza
    await callback.message.answer(
        "📣 <b>Xabar yuborildi!</b>\n\n"
        f"✅ Yetkazildi: {sent} ta\n❌ Yetkazilmadi: {failed} ta",
        parse_mode="HTML",
    )


# --- Admin: statistika ---
@dp.message(AdminFilter(), F.text == BTN_STATS)
async def show_stats(message: types.Message, state: FSMContext):
    await state.clear()
    users = [u for u in get_all_users() if u[0] != ADMIN_ID]
    active_users = sum(1 for u in users if is_subscription_active(u[0]) and not u[3])
    blocked_users = sum(1 for u in users if u[3])
    groups = get_all_user_groups()
    active_groups = sum(1 for g in groups if g[6] == "ok" and g[5] == 1)
    now = int(time.time())
    expiring = sum(
        1
        for u in users
        if u[4] and now < u[4] <= now + 3 * 86400 and not u[3]
    )
    await message.answer(
        "📊 <b>Statistika</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{len(users)}</b> ta\n"
        f"✅ Faol tarif: <b>{active_users}</b> ta\n"
        f"⏰ 3 kun ichida tugaydi: <b>{expiring}</b> ta\n"
        f"⛔ Bloklangan: <b>{blocked_users}</b> ta\n\n"
        f"🚖 Topilgan mijozlar (jami): <b>{get_counter('leads_found')}</b> ta\n"
        f"📨 Yuborilgan bildirishnomalar: <b>{get_counter('notifications_sent')}</b> ta\n\n"
        f"🔑 Kalitlar: <b>{len(get_keywords())}</b> ta\n"
        f"👥 Faol guruhlar: <b>{active_groups}</b> / {len(groups)} ta\n"
        f"⚙️ Tizim: {'▶️ ishlayapti' if get_setting('is_active') == '1' else '⏸ toʻxtatilgan'}",
        parse_mode="HTML",
    )


# Xabar sharti juda yuqori bo'lsa, mijoz xabarlari deyarli o'tmaydi.
# Amaliy o'lchov: shart 2 da 12/12, 3 da 10/12, 4 da 1/12 o'tadi.
TOO_HIGH_COUNT = 4


def count_warning(required: int) -> str:
    """Shart yuqori bo'lsa tushunarli ogohlantirish (aks holda '')."""
    if required < TOO_HIGH_COUNT:
        return ""
    return (
        f"⚠️ <b>Shart juda yuqori: {required} ta.</b>\n"
        "Qisqa mijoz xabarlarida odatda 2-3 ta kalit bo'ladi — "
        f"{required} ta talab qilinsa, ularning deyarli barchasi kelmaydi.\n"
        "👉 <b>2</b> ni tanlash tavsiya etiladi."
    )


def scanner_status_text() -> str:
    """Diagnostika: nega xabar kelmayotganini bir qarashda ko'rsatadi."""
    groups = get_all_user_groups()
    active = [g for g in groups if g[6] == "ok" and g[5] == 1]
    pending = [g for g in groups if g[6] == "pending"]
    errored = [g for g in groups if g[6] == "error"]
    paused = [g for g in groups if g[6] == "ok" and g[5] != 1]

    # Markaziy userbot yo'q: har bir foydalanuvchi o'z sessiyasi bilan
    # ishlaydi. Shuning uchun "userbot javob bermayapti" o'rniga
    # haqiqiy sessiyalar holati ko'rsatiladi.
    try:
        import scanner_manager

        online_ids = scanner_manager.online_user_ids()
    except Exception:
        online_ids = []

    if online_ids:
        session_line = (
            f"📡 Faol sessiyalar: <b>{len(online_ids)}</b> ta "
            "(skaner ishlayapti)"
        )
    else:
        session_line = (
            "📡 Faol sessiyalar: <b>0</b> ta — hech kim onlayn emas. "
            "🔑 Login qiling (yoki server ishga tushganini tekshiring)"
        )

    lines = [
        "📊 <b>Skaner holati</b>",
        "",
        f"⚙️ Tizim: {'▶️ ishlayapti' if get_setting('is_active') == '1' else '⏸ TOʻXTATILGAN — ▶️ yoqish kerak'}",
        session_line,
        f"🔑 Kalitlar: <b>{len(get_keywords())}</b> ta",
        f"🔔 Shart: kamida <b>{get_match_count()}</b> ta kalit topilsa"
        + ("  ⚠️ juda yuqori" if get_match_count() >= TOO_HIGH_COUNT else ""),
        f"👥 Faol guruhlar: <b>{len(active)}</b> ta",
    ]
    if pending:
        lines.append(f"⏳ Tekshiruvdagi guruhlar: {len(pending)} ta")
    if paused:
        lines.append(f"⏸ To'xtatilgan guruhlar: {len(paused)} ta (▶️ yoqing)")
    if errored:
        lines.append(f"⚠️ Xatoli guruhlar: {len(errored)} ta (📋 Guruhlarim da sababi bor)")
    if not groups:
        lines.append("📭 Guruh umuman qo'shilmagan — ➕ Guruh qo'shish dan qo'shing")
    elif not active:
        lines.append("📭 Faol guruh yo'q — guruh ulanganini tekshiring")
    lines += [
        "",
        "📬 <b>Bildirishnomalar aynan shu chatga keladi</b> (Secrets dagi "
        "ADMIN_ID — boshqa joyga yuborilmaydi).",
    ]
    return "\n".join(lines)


@dp.message(AdminFilter(), F.text == BTN_TEST)
async def scan_test_start(message: types.Message, state: FSMContext):
    await state.set_state(ScanTest.waiting_text)
    await message.answer(
        scanner_status_text()
        + "\n\n🧪 <b>Test:</b> endi namuna xabar yozib yuboring — "
        "kalitlarga tekshirib, skaner xabar berardimi yoki yo'qmi, "
        "sababi bilan aytaman.\n\nBekor qilish: /cancel",
        parse_mode="HTML",
    )


@dp.message(AdminFilter(), StateFilter(ScanTest.waiting_text), F.text)
async def scan_test_check(message: types.Message, state: FSMContext):
    if (message.text or "").strip() in MENU_BUTTONS | _LEGACY_BUTTONS:
        await state.clear()
        return
    await state.clear()
    # Admin ham xuddi foydalanuvchi kabi HAQIQIY zanjirdan o'tkazadi:
    # shu bilan "nega xabar kelmadi" ni o'z ko'zi bilan ko'radi.
    await message.answer(
        scan_test_report(message.from_user.id, message.text or ""),
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


@dp.message(AdminFilter(), F.text == BTN_TOGGLE)
async def toggle_system(message: types.Message, state: FSMContext):
    await state.clear()
    current = get_setting("is_active")
    new_status = "0" if current == "1" else "1"
    set_setting("is_active", new_status)

    status_text = "⏸ To'xtatildi" if new_status == "0" else "▶️ Davom ettirildi"
    await message.answer(
        f"Tizim holati: <b>{status_text}</b>", parse_mode="HTML"
    )


class NotAdminFilter(BaseFilter):
    async def __call__(self, event: types.TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and not is_admin(user.id)


@dp.message(NotAdminFilter(), F.text)
async def user_fallback(message: types.Message, state: FSMContext):
    """Oddiy foydalanuvchiga admin tugmalari ishlamaydi - o'z menyusi chiqadi."""
    await state.clear()
    upsert_user(
        message.from_user.id,
        message.from_user.first_name or "",
        message.from_user.username or "",
    )
    await message.answer(
        "Quyidagi menyudan foydalaning 👇\n\n"
        + subscription_text(get_user(message.from_user.id)),
        parse_mode="HTML",
        reply_markup=user_menu_for(message.from_user.id),
    )


async def main():
    missing = [m for m in missing_settings() if m in ("BOT_TOKEN", "ADMIN_ID")]
    if missing:
        raise SystemExit(
            "❌ Sozlamalar yetishmaydi: "
            + ", ".join(missing)
            + ". telegram_scanner/.env faylini .env.example asosida to'ldiring."
        )
    init_db()
    logger.info("Boshqaruv boti ishga tushdi...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
