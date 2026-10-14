"""Telegram bilan ishlashning kichik yordamchilari (ekranlarni chizish)."""

from __future__ import annotations

from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from loguru import logger

Target = "CallbackQuery | Message"


async def render(
    target: CallbackQuery | Message | None,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    *,
    disable_preview: bool = True,
) -> Message | None:
    """Xabarni tahrirlash (callback) yoki yangi xabar yuborish (message).

    Callback'da xabar o'zgarmagan bo'lsa Telegram xato qaytaradi — bu holda
    jim o'tiladi (foydalanuvchi uchun muammo emas).
    """
    if target is None:
        return None

    if isinstance(target, CallbackQuery):
        message = target.message
        if message is None:
            return None
        try:
            return await message.edit_text(
                text, reply_markup=markup, disable_web_page_preview=disable_preview
            )
        except Exception as exc:
            if "message is not modified" in str(exc):
                return message
            try:
                return await message.answer(
                    text, reply_markup=markup, disable_web_page_preview=disable_preview
                )
            except Exception as inner:  # pragma: no cover
                logger.warning("Xabarni yuborib bo'lmadi: {}", inner)
                return None

    try:
        return await target.answer(
            text, reply_markup=markup, disable_web_page_preview=disable_preview
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("Xabarni yuborib bo'lmadi: {}", exc)
        return None


async def alert(callback: CallbackQuery, text: str, *, show: bool = False) -> None:
    """Callback'ga qisqa javob (show=True bo'lsa oyna ko'rinishida)."""
    try:
        await callback.answer(text, show_alert=show)
    except Exception:  # pragma: no cover — eskirgan callback
        pass


def keyboard_rows(markup: InlineKeyboardMarkup | None) -> list[list]:
    return list(markup.inline_keyboard) if markup else []
