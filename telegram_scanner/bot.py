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
from matcher import parse_key_words, validate_key_words

from database import (
    delete_phrase,
    get_all_phrases_with_id,
    get_groups,
    get_setting,
    add_phrase,
    init_db,
    set_setting,
    toggle_group,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BTN_ADD = "➕ Yangi ibora qo'shish"
BTN_PHRASES = "📋 Iboralar ro'yxati"
BTN_GROUPS = "📋 Guruhlar ro'yxati"
BTN_TOGGLE = "⏸ To'xtatish / ▶️ Davom ettirish"
MENU_BUTTONS = {BTN_ADD, BTN_PHRASES, BTN_GROUPS, BTN_TOGGLE}


class AdminFilter(BaseFilter):
    """Faqat ADMIN_ID egasiga ruxsat beradi (barcha handlerlarda)."""

    async def __call__(self, event: types.TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        return bool(ADMIN_ID) and user is not None and user.id == ADMIN_ID


class AddPhrase(StatesGroup):
    waiting_phrase = State()   # kalit so'zlar (2–10 ta) kutilmoqda
    waiting_required = State()  # nechta so'z uchrasa xabar berish tanlanmoqda


def main_menu() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text=BTN_ADD)],
        [KeyboardButton(text=BTN_PHRASES), KeyboardButton(text=BTN_GROUPS)],
        [KeyboardButton(text=BTN_TOGGLE)],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


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
        "Assalomu alaykum! Skaner boshqaruv botiga xush kelibsiz.",
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
        "Kalit so'zlarni yuboring — har bir so'z alohida kalit. "
        "Bitta to'plamda <b>2 tadan 10 tagacha</b> so'z bo'ladi, "
        "so'zlarni bo'shliq bilan yozing.\n"
        "Masalan: <i>toshkent samarqand odam mashina kerak yuk bugun</i>\n\n"
        "Keyingi qadamda nechta so'z uchrasa xabar berishni tanlaysiz "
        "(2 ta yoki 3 ta). Foiz yo'q — aniq son.\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML",
    )


async def _save_key_set(message: types.Message, state: FSMContext,
                        words: list[str], required: int):
    text = " ".join(words)
    await state.clear()
    if add_phrase(text, required):
        await message.answer(
            f"✅ Kalitlar to'plami saqlandi ({len(words)} ta so'z):\n"
            f"<b>{html.escape(text)}</b>\n\n"
            f"🔔 Xabarda shu so'zlardan <b>{required} tasi</b> uchrasa, "
            "bot sizga xabar beradi.",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
    else:
        await message.answer(
            "⚠️ Bu to'plam allaqachon ro'yxatda bor.",
            reply_markup=main_menu(),
        )


@dp.message(StateFilter(AddPhrase.waiting_phrase), F.text)
async def save_new_phrase(message: types.Message, state: FSMContext):
    if (message.text or "").strip() in MENU_BUTTONS:
        await state.clear()
        return

    words = parse_key_words(message.text or "")
    error = validate_key_words(words)
    if error:
        await message.answer(error, parse_mode="HTML")
        return  # holatda qolamiz — foydalanuvchi qayta yozishi mumkin

    if len(words) == 2:
        # 2 so'zli to'plamda ikkalasi ham uchrashi kerak — tanlov shart emas
        await _save_key_set(message, state, words, required=2)
        return

    # 3+ so'z: nechta so'z uchrasa xabar berishni foydalanuvchi tanlaydi
    await state.update_data(words=words)
    await state.set_state(AddPhrase.waiting_required)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="2 ta so'z uchrasa", callback_data="reqcnt:2"
                ),
                InlineKeyboardButton(
                    text="3 ta so'z uchrasa", callback_data="reqcnt:3"
                ),
            ]
        ]
    )
    await message.answer(
        f"To'plam: <b>{html.escape(' '.join(words))}</b> "
        f"({len(words)} ta so'z)\n\n"
        "Xabarda nechta so'z uchrasa sizga xabar beray?",
        parse_mode="HTML",
        reply_markup=kb,
    )


@dp.callback_query(StateFilter(AddPhrase.waiting_required), F.data.startswith("reqcnt:"))
async def save_required_count(callback: types.CallbackQuery, state: FSMContext):
    try:
        required = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Xato ma'lumot.", show_alert=True)
        return
    data = await state.get_data()
    words = data.get("words") or []
    if not words:
        await state.clear()
        await callback.answer("So'zlar topilmadi, qaytadan qo'shing.", show_alert=True)
        return
    required = max(2, min(required, len(words)))
    await _save_key_set(callback.message, state, words, required)
    await callback.answer("Saqlandi!")


@dp.message(F.text == BTN_PHRASES)
async def list_phrases(message: types.Message, state: FSMContext):
    await state.clear()
    phrases = get_all_phrases_with_id()
    if not phrases:
        await message.answer("Ro'yxat bo'sh.")
        return

    await message.answer("Sizning kalit to'plamlaringiz (o'chirish uchun tugmani bosing):")
    for p_id, p_text, required in phrases:
        word_count = len(p_text.split())
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"del:{p_id}")]
            ]
        )
        await message.answer(
            f"🔹 {html.escape(p_text)}\n"
            f"📝 {word_count} ta so'z, 🔔 {required} tasi uchrasa — xabar beradi",
            parse_mode="HTML",
            reply_markup=kb,
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
