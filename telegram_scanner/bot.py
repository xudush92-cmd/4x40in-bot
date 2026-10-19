import asyncio
import html
import logging

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
    delete_phrase,
    get_all_phrases_with_id,
    get_groups,
    get_keywords,
    get_match_count,
    get_setting,
    init_db,
    set_setting,
    toggle_group,
)
from matcher import parse_key_words

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BTN_ADD = "➕ Kalit so'z qo'shish"
BTN_PHRASES = "📋 Kalitlar ro'yxati"
BTN_GROUPS = "📋 Guruhlar ro'yxati"
BTN_COUNT = "🔔 Xabar sharti"
BTN_TOGGLE = "⏸ To'xtatish / ▶️ Davom ettirish"
MENU_BUTTONS = {BTN_ADD, BTN_PHRASES, BTN_GROUPS, BTN_COUNT, BTN_TOGGLE}
# Eski menyu tugmalari (yangilangach ham adashmaslik uchun)
_LEGACY_BUTTONS = {"➕ Yangi ibora qo'shish", "📋 Iboralar ro'yxati"}


class AdminFilter(BaseFilter):
    """Faqat ADMIN_ID egasiga ruxsat beradi (barcha handlerlarda)."""

    async def __call__(self, event: types.TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        return bool(ADMIN_ID) and user is not None and user.id == ADMIN_ID


class AddPhrase(StatesGroup):
    waiting_phrase = State()  # kalit so'z(lar) kutilmoqda


class SetCount(StatesGroup):
    waiting_count = State()  # nechta so'z topilsa xabar berish soni kutilmoqda


def main_menu() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text=BTN_ADD)],
        [KeyboardButton(text=BTN_PHRASES), KeyboardButton(text=BTN_GROUPS)],
        [KeyboardButton(text=BTN_COUNT), KeyboardButton(text=BTN_TOGGLE)],
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


@dp.message(F.text == BTN_GROUPS)
async def list_groups(message: types.Message, state: FSMContext):
    await state.clear()
    groups = get_groups()
    if not groups:
        await message.answer("Guruhlar topilmadi. Userbotni bir marta ishga tushiring.")
        return

    await message.answer("Guruhlarni kuzatishni yoqish/o'chirish uchun bosing:")
    for chat_id, title, is_active in groups:
        status = "✅ Kuzatilmoqda" if is_active else "❌ O'chirilgan"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=status,
                        # ":" ajratgichi salbiy chat_id (-100...) bilan ham ishlaydi
                        callback_data=f"tgl:{chat_id}:{is_active}",
                    )
                ]
            ]
        )
        await message.answer(f"👥 {html.escape(title or '')}", parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("tgl:"))
async def toggle_group_callback(callback: types.CallbackQuery):
    try:
        _, chat_id_str, current_status = callback.data.split(":")
        chat_id, current = int(chat_id_str), int(current_status)
    except ValueError:
        await callback.answer("Xato ma'lumot.", show_alert=True)
        return

    new_status = 0 if current == 1 else 1
    toggle_group(chat_id, new_status)

    status_text = "✅ Kuzatilmoqda" if new_status == 1 else "❌ O'chirilgan"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=status_text,
                    callback_data=f"tgl:{chat_id}:{new_status}",
                )
            ]
        ]
    )
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer("O'zgartirildi!")


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
