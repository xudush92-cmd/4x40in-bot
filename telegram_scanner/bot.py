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
    get_all_phrases_with_id,
    get_keywords,
    get_managed_groups,
    get_match_count,
    get_setting,
    init_db,
    requeue_managed_group,
    set_setting,
    toggle_managed_group,
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
MENU_BUTTONS = {
    BTN_ADD, BTN_PHRASES, BTN_GROUP_ADD, BTN_GROUPS,
    BTN_COUNT, BTN_TOGGLE, BTN_TEST,
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


def main_menu() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_GROUP_ADD)],
        [KeyboardButton(text=BTN_PHRASES), KeyboardButton(text=BTN_GROUPS)],
        [KeyboardButton(text=BTN_COUNT), KeyboardButton(text=BTN_TOGGLE)],
        [KeyboardButton(text=BTN_TEST)],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def current_status_text() -> str:
    return (
        f"🔑 Kalitlar soni: <b>{len(get_keywords())}</b> ta\n"
        f"🔔 Xabar sharti: kamida <b>{get_match_count()}</b> ta kalit so'z "
        "topilsa xabar beriladi"
    )


bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()
# Admin tekshiruvi HAR BIR handlerga global qo'llanadi
dp.message.filter(AdminFilter())
dp.callback_query.filter(AdminFilter())


# --- Handlers ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Assalomu alaykum! Skaner boshqaruv botiga xush kelibsiz.\n\n"
        + current_status_text(),
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi.", reply_markup=main_menu())


@dp.message(F.text == BTN_ADD)
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


@dp.message(StateFilter(AddPhrase.waiting_phrase), F.text)
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


@dp.message(F.text == BTN_COUNT)
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


@dp.callback_query(StateFilter(SetCount.waiting_count), F.data.startswith("setcnt:"))
async def set_count_callback(callback: types.CallbackQuery, state: FSMContext):
    try:
        value = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato ma'lumot.", show_alert=True)
        return
    await _apply_match_count(callback.message, state, value)
    await callback.answer("Saqlandi!")


@dp.message(StateFilter(SetCount.waiting_count), F.text)
async def set_count_message(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text in MENU_BUTTONS | _LEGACY_BUTTONS:
        await state.clear()
        return
    if not text.isdigit():
        await message.answer("⚠️ Faqat raqam yuboring, masalan: 3")
        return
    await _apply_match_count(message, state, int(text))


@dp.message(F.text == BTN_PHRASES)
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


@dp.callback_query(F.data.startswith("del:"))
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


@dp.message(F.text == BTN_GROUP_ADD)
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


@dp.message(StateFilter(AddGroup.waiting_group), F.text)
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


@dp.message(F.text.in_({BTN_GROUPS, "📋 Guruhlar ro'yxati"}))
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


@dp.callback_query(F.data.startswith("gact:"))
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


@dp.callback_query(F.data.startswith("grecheck:"))
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


@dp.callback_query(F.data.startswith("gdel:"))
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


@dp.message(F.text == BTN_TEST)
async def scan_test_start(message: types.Message, state: FSMContext):
    await state.set_state(ScanTest.waiting_text)
    await message.answer(
        scanner_status_text()
        + "\n\n🧪 <b>Test:</b> endi namuna xabar yozib yuboring — "
        "kalitlarga tekshirib, skaner xabar berardimi yoki yo'qmi, "
        "sababi bilan aytaman.\n\nBekor qilish: /cancel",
        parse_mode="HTML",
    )


@dp.message(StateFilter(ScanTest.waiting_text), F.text)
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


@dp.message(F.text == BTN_TOGGLE)
async def toggle_system(message: types.Message, state: FSMContext):
    await state.clear()
    current = get_setting("is_active")
    new_status = "0" if current == "1" else "1"
    set_setting("is_active", new_status)

    status_text = "⏸ To'xtatildi" if new_status == "0" else "▶️ Davom ettirildi"
    await message.answer(
        f"Tizim holati: <b>{status_text}</b>", parse_mode="HTML"
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
