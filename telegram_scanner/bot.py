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
    add_keyword,
    add_managed_group,
    delete_managed_group,
    delete_phrase,
    extend_subscription,
    get_all_phrases_with_id,
    get_all_users,
    get_counter,
    get_keywords,
    get_managed_groups,
    get_match_count,
    get_setting,
    get_user,
    increment_counter,
    init_db,
    is_subscription_active,
    requeue_managed_group,
    set_setting,
    set_user_blocked,
    toggle_managed_group,
    upsert_user,
)
from matcher import find_match, match_keywords, parse_key_words

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
# Foydalanuvchi tugmalari (boshqaruv tugmalari ularda BO'LMAYDI)
BTN_MY_TARIFF = "💳 Tarifim"
BTN_RECEIPT = "🧾 Chek yuborish"
BTN_HELP = "ℹ️ Yordam"
MENU_BUTTONS = {
    BTN_ADD, BTN_PHRASES, BTN_GROUP_ADD, BTN_GROUPS,
    BTN_COUNT, BTN_TOGGLE, BTN_TEST, BTN_USERS, BTN_STATS,
    BTN_MY_TARIFF, BTN_RECEIPT, BTN_HELP,
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


class AddPhrase(StatesGroup):
    waiting_phrase = State()  # kalit so'z(lar) kutilmoqda


class SetCount(StatesGroup):
    waiting_count = State()  # nechta so'z topilsa xabar berish soni kutilmoqda


class AddGroup(StatesGroup):
    waiting_group = State()  # guruh manzili yoki ID kutilmoqda


class ScanTest(StatesGroup):
    waiting_text = State()  # tekshirish uchun namuna xabar kutilmoqda


class Payment(StatesGroup):
    waiting_receipt = State()  # foydalanuvchidan to'lov cheki kutilmoqda


def is_admin(user_id: int | None) -> bool:
    return bool(ADMIN_ID) and user_id is not None and user_id == ADMIN_ID


def main_menu(admin: bool = True) -> ReplyKeyboardMarkup:
    if admin:
        kb = [
            [KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_GROUP_ADD)],
            [KeyboardButton(text=BTN_PHRASES), KeyboardButton(text=BTN_GROUPS)],
            [KeyboardButton(text=BTN_COUNT), KeyboardButton(text=BTN_TOGGLE)],
            [KeyboardButton(text=BTN_TEST), KeyboardButton(text=BTN_STATS)],
            [KeyboardButton(text=BTN_USERS)],
        ]
    else:
        # Oddiy foydalanuvchi: FAQAT tarif/yordam. Stop-start, xabar
        # sharti, skaner test, guruh va kalit boshqaruvi BO'LMAYDI.
        kb = [
            [KeyboardButton(text=BTN_MY_TARIFF), KeyboardButton(text=BTN_RECEIPT)],
            [KeyboardButton(text=BTN_HELP)],
        ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


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
        reply_markup=main_menu(admin=False),
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Bekor qilindi.",
        reply_markup=main_menu(admin=is_admin(message.from_user.id)),
    )


# --- Oddiy foydalanuvchi bo'limi (boshqaruv tugmalari yo'q) ---
@dp.message(F.text == BTN_MY_TARIFF)
async def my_tariff(message: types.Message, state: FSMContext):
    await state.clear()
    upsert_user(
        message.from_user.id,
        message.from_user.first_name or "",
        message.from_user.username or "",
    )
    await message.answer(
        subscription_text(get_user(message.from_user.id))
        + "\n\nTarifni yangilash uchun to'lov qilib, "
        "🧾 Chek yuborish tugmasi orqali chekni yuboring.",
        parse_mode="HTML",
        reply_markup=main_menu(admin=False),
    )


@dp.message(F.text == BTN_HELP)
async def help_user(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "ℹ️ <b>Yordam</b>\n\n"
        "• Bu bot topilgan mijozlar xabarlarini sizga yuboradi.\n"
        "• Xizmatdan foydalanish uchun oylik tarif faol bo'lishi kerak.\n"
        "• Tarif olish: to'lov qiling va 🧾 Chek yuborish orqali "
        "chek rasmini yuboring — admin tekshirib, tarifingizni yoqadi.\n"
        "• Savollar bo'lsa adminga yozing.",
        parse_mode="HTML",
        reply_markup=main_menu(admin=False),
    )


@dp.message(F.text == BTN_RECEIPT)
async def ask_receipt(message: types.Message, state: FSMContext):
    row = get_user(message.from_user.id)
    if row and row[3]:
        await message.answer("⛔ Hisobingiz bloklangan. Admin bilan bog'laning.")
        return
    await state.set_state(Payment.waiting_receipt)
    await message.answer(
        "🧾 To'lov cheki rasmini (skrinshot) yuboring — admin tekshirib, "
        "tarifingizni yoqadi.\n\nBekor qilish: /cancel"
    )


@dp.message(StateFilter(Payment.waiting_receipt), F.photo | F.document)
async def receive_receipt(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    upsert_user(user.id, user.first_name or "", user.username or "")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ 30 kunga yoqish", callback_data=f"payok:{user.id}"
                ),
                InlineKeyboardButton(
                    text="❌ Rad etish", callback_data=f"payno:{user.id}"
                ),
            ]
        ]
    )
    try:
        await message.copy_to(ADMIN_ID, reply_markup=kb)
        await bot.send_message(
            ADMIN_ID,
            "🧾 <b>To'lov cheki keldi!</b>\n\n"
            f"👤 {html.escape(user.first_name or '')} "
            f"(@{html.escape(user.username or 'yoʻq')})\n"
            f"🆔 <code>{user.id}</code>\n\n"
            "Yuqoridagi chek xabaridagi tugmadan tarifni yoqing.",
            parse_mode="HTML",
        )
        await message.answer(
            "✅ Chekingiz adminga yuborildi. Tekshirilgach, "
            "tarifingiz yoqiladi va sizga xabar keladi.",
            reply_markup=main_menu(admin=False),
        )
    except Exception:
        logger.exception("Chekni adminga yuborishda xato")
        await message.answer(
            "⚠️ Chekni yuborishda xato bo'ldi. Keyinroq qayta urining.",
            reply_markup=main_menu(admin=False),
        )


@dp.callback_query(AdminFilter(), F.data.startswith("payok:"))
async def payment_approve(callback: types.CallbackQuery):
    try:
        user_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato ma'lumot.", show_alert=True)
        return
    row = get_user(user_id)
    if not row:
        await callback.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return
    expiry = extend_subscription(user_id, days=30)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer("✅ 30 kunga yoqildi")
    try:
        await bot.send_message(
            user_id,
            "🎉 <b>Tarifingiz yoqildi!</b>\n\n"
            f"📅 Amalda: <b>{format_date(expiry)}</b> gacha.\n"
            "Endi topilgan xabarlar sizga keladi.",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Foydalanuvchiga tarif xabari yuborilmadi")


@dp.callback_query(AdminFilter(), F.data.startswith("payno:"))
async def payment_reject(callback: types.CallbackQuery):
    try:
        user_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato ma'lumot.", show_alert=True)
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer("❌ Rad etildi")
    try:
        await bot.send_message(
            user_id,
            "❌ To'lov chekingiz tasdiqlanmadi. To'lovni tekshirib, "
            "chekning aniq rasmini qayta yuboring yoki admin bilan bog'laning.",
        )
    except Exception:
        logger.exception("Foydalanuvchiga rad xabari yuborilmadi")


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
    added, already = [], []
    for word in words:
        (added if add_keyword(word) else already).append(word)

    parts = []
    if added:
        parts.append(
            f"✅ Qo'shildi ({len(added)} ta): <b>{html.escape(', '.join(added))}</b>"
        )
    if already:
        parts.append(
            f"ℹ️ Allaqachon bor ({len(already)} ta): "
            f"{html.escape(', '.join(already))}"
        )
    parts.append("")
    parts.append(current_status_text())
    await message.answer(
        "\n".join(parts), parse_mode="HTML", reply_markup=main_menu()
    )


# --- Xabar berish sharti (admin belgilaydi / o'zgartiradi) ---
def _count_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=str(n), callback_data=f"setcnt:{n}")
        for n in (1, 2, 3, 4, 5)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


@dp.message(AdminFilter(), F.text == BTN_COUNT)
async def ask_match_count(message: types.Message, state: FSMContext):
    await state.set_state(SetCount.waiting_count)
    await message.answer(
        f"Hozirgi shart: xabarda kamida <b>{get_match_count()}</b> ta "
        "kalit so'z topilsa xabar beriladi.\n\n"
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
    note = ""
    if total and value > total:
        note = (
            f"\n⚠️ Diqqat: hozir kalitlar {total} ta, shart {value} ta — "
            "kalit qo'shmasangiz hech qachon xabar kelmaydi."
        )
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


@dp.message(AdminFilter(), F.text == BTN_GROUP_ADD)
async def ask_group(message: types.Message, state: FSMContext):
    await state.set_state(AddGroup.waiting_group)
    await message.answer(
        "Guruh <b>manzili yoki ID</b> sidan birini yuboring:\n\n"
        "• <code>@guruh_nomi</code>\n"
        "• <code>https://t.me/guruh_nomi</code>\n"
        "• <code>-1001234567890</code> (raqamli ID)\n\n"
        "⚠️ Skaner qiluvchi akkaunt (userbot) shu guruhda <b>a'zo bo'lishi "
        "shart</b> — bo'lmasa bot xato haqida xabar beradi.\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML",
    )


@dp.message(AdminFilter(), StateFilter(AddGroup.waiting_group), F.text)
async def save_group(message: types.Message, state: FSMContext):
    if (message.text or "").strip() in MENU_BUTTONS | _LEGACY_BUTTONS:
        await state.clear()
        return

    value = normalize_group_input(message.text or "")
    if value is None:
        await message.answer(
            "⚠️ Tushunmadim. Guruh manzilini (@username yoki t.me havola) "
            "yoki raqamli ID (-100...) yuboring."
        )
        return  # holatda qolamiz — qayta yozishi mumkin

    await state.clear()
    if not add_managed_group(value):
        await message.answer(
            "ℹ️ Bu guruh allaqachon ro'yxatda bor. 📋 Guruhlarim dan ko'ring.",
            reply_markup=main_menu(),
        )
        return
    await message.answer(
        f"✅ Guruh qabul qilindi: <b>{html.escape(value)}</b>\n\n"
        "⏳ Userbot tekshirmoqda (odatda 30 soniyagacha). "
        "Tekshiruv natijasi shu yerga xabar bo'lib keladi. "
        "Holatni 📋 Guruhlarim dan ham ko'rishingiz mumkin.",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


def _group_text(row) -> str:
    gid, input_value, chat_id, title, is_active, status, last_error = row
    name = title or input_value
    if status == "ok":
        state_line = (
            "✅ Skanerlanmoqda" if is_active else "⏸ To'xtatilgan (skanerlanmaydi)"
        )
    elif status == "pending":
        state_line = "⏳ Userbot tekshirmoqda..."
    else:
        state_line = f"⚠️ Tekshiruvda xato: {last_error or 'nomaʼlum'}"
    chat_line = f"\n🆔 <code>{chat_id}</code>" if chat_id else ""
    return f"👥 <b>{html.escape(name or '')}</b>\n{state_line}{chat_line}"


def _group_keyboard(row) -> InlineKeyboardMarkup:
    gid, input_value, chat_id, title, is_active, status, last_error = row
    rows = []
    if status == "ok":
        # O'rnini almashtiradigan tugma: holatga qarab matni o'zgaradi
        toggle_text = "⏸ To'xtatish" if is_active else "▶️ Yoqish"
        rows.append(
            [InlineKeyboardButton(text=toggle_text, callback_data=f"gact:{gid}:{is_active}")]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="🔄 Qayta tekshirish", callback_data=f"grecheck:{gid}")]
        )
    rows.append(
        [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"gdel:{gid}")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _find_group(group_id: int):
    for row in get_managed_groups():
        if row[0] == group_id:
            return row
    return None


@dp.message(AdminFilter(), F.text.in_({BTN_GROUPS, "📋 Guruhlar ro'yxati"}))
async def list_groups(message: types.Message, state: FSMContext):
    await state.clear()
    groups = get_managed_groups()
    if not groups:
        await message.answer(
            "Hozircha guruhlar yo'q.\n"
            "➕ Guruh qo'shish tugmasi orqali manzil yoki ID yuboring — "
            "skaner faqat shu yerda qo'shilgan guruhlarni tekshiradi."
        )
        return

    await message.answer(f"Sizning guruhlaringiz — {len(groups)} ta:")
    for row in groups:
        await message.answer(
            _group_text(row), parse_mode="HTML", reply_markup=_group_keyboard(row)
        )


@dp.callback_query(AdminFilter(), F.data.startswith("gact:"))
async def toggle_managed_callback(callback: types.CallbackQuery):
    """⏸/▶️ — tugma o'z o'rnida qarama-qarshi holatga almashadi."""
    try:
        _, gid_str, current_str = callback.data.split(":")
        gid, current = int(gid_str), int(current_str)
    except ValueError:
        await callback.answer("Xato ma'lumot.", show_alert=True)
        return
    new_status = 0 if current == 1 else 1
    toggle_managed_group(gid, new_status)
    row = _find_group(gid)
    if row:
        await callback.message.edit_text(
            _group_text(row), parse_mode="HTML", reply_markup=_group_keyboard(row)
        )
    await callback.answer("⏸ To'xtatildi" if new_status == 0 else "▶️ Yoqildi")


@dp.callback_query(AdminFilter(), F.data.startswith("grecheck:"))
async def recheck_group_callback(callback: types.CallbackQuery):
    try:
        gid = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Xato ma'lumot.", show_alert=True)
        return
    requeue_managed_group(gid)
    row = _find_group(gid)
    if row:
        await callback.message.edit_text(
            _group_text(row), parse_mode="HTML", reply_markup=_group_keyboard(row)
        )
    await callback.answer("🔄 Tekshiruv navbatga qo'yildi (30 soniyagacha)")


@dp.callback_query(AdminFilter(), F.data.startswith("gdel:"))
async def delete_group_callback(callback: types.CallbackQuery):
    try:
        gid = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Xato ma'lumot.", show_alert=True)
        return
    row = _find_group(gid)
    name = (row[3] or row[1]) if row else gid
    delete_managed_group(gid)
    await callback.message.edit_text(
        f"🗑 Guruh butunlay o'chirildi: <b>{html.escape(str(name))}</b>\n"
        "Endi bu guruh skanerlanmaydi.",
        parse_mode="HTML",
    )
    await callback.answer("O'chirildi")


# --- Admin: foydalanuvchilar boshqaruvi ---
def _user_status_line(row) -> str:
    _uid, name, uname, blocked, expires, _created = row
    now = int(time.time())
    if blocked:
        status = "⛔ Bloklangan"
    elif expires and expires > now:
        status = f"✅ Faol ({format_date(expires)} gacha)"
    else:
        status = "❌ Tarif yo'q/tugagan"
    uname_text = f"@{html.escape(uname)}" if uname else "username yo'q"
    return (
        f"👤 <b>{html.escape(name or '—')}</b> ({uname_text})\n"
        f"🆔 <code>{_uid}</code>\n{status}"
    )


def _user_keyboard(row) -> InlineKeyboardMarkup:
    uid, _name, _uname, blocked, _expires, _created = row
    block_btn = (
        InlineKeyboardButton(text="✅ Blokdan chiqarish", callback_data=f"ublock:{uid}")
        if blocked
        else InlineKeyboardButton(text="⛔ Bloklash", callback_data=f"ublock:{uid}")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ 30 kun", callback_data=f"uextend:{uid}"
                ),
                block_btn,
            ]
        ]
    )


@dp.message(AdminFilter(), F.text == BTN_USERS)
async def list_users(message: types.Message, state: FSMContext):
    await state.clear()
    users = [u for u in get_all_users() if u[0] != ADMIN_ID]
    if not users:
        await message.answer(
            "👥 Hozircha foydalanuvchilar yo'q.\n"
            "Bot havolasini ulashing — /start bosganlar shu yerda chiqadi."
        )
        return
    active_n = sum(1 for u in users if is_subscription_active(u[0]) and not u[3])
    await message.answer(
        f"👥 <b>Foydalanuvchilar: {len(users)} ta</b> "
        f"(faol tarif: {active_n} ta)\n"
        "Har birida: ➕ 30 kun (tarif uzaytirish) va bloklash tugmasi.",
        parse_mode="HTML",
    )
    for row in users:
        await message.answer(
            _user_status_line(row),
            parse_mode="HTML",
            reply_markup=_user_keyboard(row),
        )


async def _refresh_user_card(callback: types.CallbackQuery, user_id: int):
    row = get_user(user_id)
    if row:
        await callback.message.edit_text(
            _user_status_line(row),
            parse_mode="HTML",
            reply_markup=_user_keyboard(row),
        )


@dp.callback_query(AdminFilter(), F.data.startswith("uextend:"))
async def user_extend_callback(callback: types.CallbackQuery):
    try:
        user_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato.", show_alert=True)
        return
    expiry = extend_subscription(user_id, days=30)
    await _refresh_user_card(callback, user_id)
    await callback.answer(f"✅ {format_date(expiry)} gacha uzaytirildi")
    try:
        await bot.send_message(
            user_id,
            "🎉 Tarifingiz uzaytirildi!\n"
            f"📅 Amalda: <b>{format_date(expiry)}</b> gacha.",
            parse_mode="HTML",
        )
    except Exception:
        pass


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


# --- Admin: statistika ---
@dp.message(AdminFilter(), F.text == BTN_STATS)
async def show_stats(message: types.Message, state: FSMContext):
    await state.clear()
    users = [u for u in get_all_users() if u[0] != ADMIN_ID]
    active_users = sum(1 for u in users if is_subscription_active(u[0]) and not u[3])
    blocked_users = sum(1 for u in users if u[3])
    groups = get_managed_groups()
    active_groups = sum(1 for g in groups if g[5] == "ok" and g[4] == 1)
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


def scanner_status_text() -> str:
    """Diagnostika: nega xabar kelmayotganini bir qarashda ko'rsatadi."""
    groups = get_managed_groups()
    active = [g for g in groups if g[5] == "ok" and g[4] == 1]
    pending = [g for g in groups if g[5] == "pending"]
    errored = [g for g in groups if g[5] == "error"]
    paused = [g for g in groups if g[5] == "ok" and g[4] != 1]

    last_seen_raw = get_setting("userbot_last_seen")
    if last_seen_raw:
        try:
            ago = max(0, int(time.time()) - int(last_seen_raw))
            userbot_line = (
                f"🤖 Userbot: {'✅ ishlayapti' if ago <= 90 else '❌ javob bermayapti'} "
                f"({ago} soniya oldin signal)"
            )
        except ValueError:
            userbot_line = "🤖 Userbot: ❓ holati noma'lum"
    else:
        userbot_line = (
            "🤖 Userbot: ❌ hali signal yo'q — userbot ishga tushmagan "
            "yoki Replitda faqat bot.py ishlayapti (main.py kerak)"
        )

    lines = [
        "📊 <b>Skaner holati</b>",
        "",
        f"⚙️ Tizim: {'▶️ ishlayapti' if get_setting('is_active') == '1' else '⏸ TOʻXTATILGAN — ▶️ yoqish kerak'}",
        userbot_line,
        f"🔑 Kalitlar: <b>{len(get_keywords())}</b> ta",
        f"🔔 Shart: kamida <b>{get_match_count()}</b> ta kalit topilsa",
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
    keywords = get_keywords()
    required = get_match_count()
    result = match_keywords(message.text or "", keywords, required)
    found = find_match(message.text or "", keywords, required)

    lines = [
        f"🔍 Topilgan kalitlar: <b>{result.matched_count}</b> ta "
        f"(shart: {required} ta)",
    ]
    if result.matched_words:
        lines.append(f"✅ {html.escape(', '.join(result.matched_words))}")
    if found:
        lines.append(
            "\n🎯 <b>Natija: skaner bu xabarga XABAR BERARDI</b> — "
            "agar guruh faol bo'lsa, bildirishnoma aynan shu chatga keladi."
        )
    else:
        lines.append(
            "\n❌ <b>Natija: xabar BERILMASDI</b> — kalitlar soni shartga "
            "yetmadi. Kalit qo'shing yoki 🔔 shartni kamaytiring."
        )
    if get_setting("is_active") != "1":
        lines.append("⚠️ Bundan tashqari tizim ⏸ to'xtatilgan — avval ▶️ yoqing.")
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=main_menu())


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
        reply_markup=main_menu(admin=False),
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
