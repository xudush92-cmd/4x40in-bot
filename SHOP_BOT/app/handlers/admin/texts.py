"""Phase 8: bot matnlarini tekshirish, tahrirlash va zavodga qaytarish.

Noma'lum kalit yoki HTML/placeholder kiritishdan avval rad qilinadi. Admin
kiritgan qiymatlar boshqa worker'larga faqat DB commitidan so'ng tarqatiladi.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole
from app.db.models import BotText
from app.filters import IsAdmin
from app.keyboards.callbacks import AdminCB, TextCB
from app.services.text_service import DEFAULT_TEXTS, safe_format, text_service, update_template
from app.states import AdminTextStates
from app.utils.text import escape_html, truncate
from app.utils.tg import alert, render

router = Router(name="admin:texts")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


def _can_edit(role: str | None) -> bool:
    return role in (AdminRole.ADMIN, AdminRole.SUPER)


def _btn(label: str, action: str, key: str = "-", page: int = 0) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=label, callback_data=TextCB(
        action=action, key=key, page=page,
    ).pack())


async def render_list(target: Message | CallbackQuery, session: AsyncSession, page: int = 0) -> None:
    keys = sorted(DEFAULT_TEXTS)
    pages = max(1, (len(keys) + 5) // 6)
    page = max(0, min(page, pages - 1))
    custom = set((await session.execute(select(BotText.key).where(
        BotText.lang == "uz", BotText.is_custom.is_(True),
    ))).scalars())
    rows = [[_btn(f"{'✍️' if key in custom else '📝'} {key}", "card", key, page)]
            for key in keys[page * 6:(page + 1) * 6]]
    nav = []
    if page:
        nav.append(_btn("◀️", "list", page=page - 1))
    nav.append(_btn(f"{page + 1}/{pages} 🔄", "list", page=page))
    if page + 1 < pages:
        nav.append(_btn("▶️", "list", page=page + 1))
    rows += [nav, [InlineKeyboardButton(text="◀️ Panel", callback_data=AdminCB(
        action="menu",
    ).pack())]]
    await render(target, "✍️ <b>Bot matnlari</b>\n📝 Standart · ✍️ Tahrirlangan. "
                 "O'zgarishlar boshqa worker'larga 15 soniya ichida yetadi.",
                 InlineKeyboardMarkup(inline_keyboard=rows))


async def render_card(target: Message | CallbackQuery, session: AsyncSession,
                      key: str, page: int, role: str | None) -> None:
    if key not in DEFAULT_TEXTS:
        await render(target, "⚠️ Matn kaliti topilmadi.")
        return
    row = (await session.execute(select(BotText).where(BotText.key == key, BotText.lang == "uz"))).scalar_one_or_none()
    current = row.text if row else DEFAULT_TEXTS[key]
    text = (f"✍️ <b>{escape_html(key)}</b> · {'tahrirlangan' if row and row.is_custom else 'standart'}\n"
            f"<b>Saqlangan matn:</b>\n<pre>{escape_html(truncate(current, 850))}</pre>\n"
            "<i>Ko'rish tugmasi namunaviy qiymatlar bilan haqiqiy HTML ko'rinishini beradi.</i>")
    buttons = [[_btn("👀 Ko'rish (preview)", "preview", key, page)]]
    if _can_edit(role):
        buttons.append([_btn("✏️ Tahrirlash", "edit", key, page)])
        if row and row.is_custom:
            buttons.append([_btn("♻️ Zavodga qaytarish", "reset_ask", key, page)])
    buttons.append([_btn("◀️ Matnlar", "list", page=page)])
    await render(target, text, InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(TextCB.filter(F.action == "list"))
async def list_texts(callback: CallbackQuery, callback_data: TextCB, session: AsyncSession) -> None:
    await render_list(callback, session, callback_data.page)
    await alert(callback, "")


@router.callback_query(TextCB.filter(F.action == "card"))
async def card(callback: CallbackQuery, callback_data: TextCB, session: AsyncSession,
               role: str | None) -> None:
    await render_card(callback, session, callback_data.key, callback_data.page, role)
    await alert(callback, "")


@router.callback_query(TextCB.filter(F.action == "preview"))
async def preview(callback: CallbackQuery, callback_data: TextCB, session: AsyncSession) -> None:
    key = callback_data.key
    if key not in DEFAULT_TEXTS:
        await alert(callback, "Matn topilmadi", show=True)
        return
    row = (await session.execute(select(BotText).where(BotText.key == key, BotText.lang == "uz"))).scalar_one_or_none()
    samples = {"ism": "Namuna", "guruh": "Sinov guruhi", "huquqlar": "Xabar o'chirish",
               "sabab": "Misol sabab", "tarif": "Biznes", "kun": "7", "elon": "3", "rasm": "5",
               "sana": "30.10.2026", "yordam": "@admin", "tarif_holati": "Faol",
               "qoldi": "3", "toifa": "Telefonlar", "sotuvchi": "Ali", "summa": "150 000",
               "manba": "Bot", "xato": "Misol xato"}
    rendered = safe_format(row.text if row else DEFAULT_TEXTS[key], **samples)
    await render(callback, f"👀 <b>Ko'rinish: {escape_html(key)}</b>\n\n{rendered}",
                 InlineKeyboardMarkup(inline_keyboard=[[_btn("◀️ Matn", "card", key, callback_data.page)]]))
    await alert(callback, "")


@router.callback_query(TextCB.filter(F.action == "edit"))
async def start_edit(callback: CallbackQuery, callback_data: TextCB, state: FSMContext,
                     role: str | None) -> None:
    if not _can_edit(role) or callback_data.key not in DEFAULT_TEXTS:
        await alert(callback, "⛔️ Bu matnni tahrirlashga ruxsat yo'q.", show=True)
        return
    await state.set_state(AdminTextStates.waiting_text)
    await state.update_data(text_key=callback_data.key, text_page=callback_data.page)
    await render(callback, f"✏️ <b>{escape_html(callback_data.key)}</b> uchun yangi matn yuboring.\n"
                 "1–2800 belgi, faqat shu shablondagi {placeholder} va oddiy "
                 "&lt;b&gt;/&lt;i&gt;/&lt;u&gt;/&lt;s&gt;/&lt;code&gt;/&lt;pre&gt; teglari.\n"
                 "&lt; va &amp; belgilarini mos ravishda &amp;lt; va &amp;amp; yozing.\n"
                 "Bekor qilish: /cancel")
    await alert(callback, "")


@router.message(Command("cancel"), StateFilter(AdminTextStates.waiting_text))
async def cancel_edit(message: Message, state: FSMContext, session: AsyncSession,
                      role: str | None) -> None:
    data = await state.get_data()
    await state.clear()
    await render_card(message, session, data.get("text_key", "-"), int(data.get("text_page", 0)), role)


@router.message(StateFilter(AdminTextStates.waiting_text), F.text)
async def save_text(message: Message, state: FSMContext, session: AsyncSession,
                    role: str | None) -> None:
    if not _can_edit(role):
        await state.clear()
        return
    data = await state.get_data()
    key = data.get("text_key", "-")
    try:
        await update_template(session, key, message.text, message.from_user.id)
    except ValueError as exc:
        await message.answer(f"⚠️ {escape_html(str(exc))}\n/cancel — bekor qilish.")
        return
    await session.commit()
    await text_service.publish()
    await state.clear()
    await render_card(message, session, key, int(data.get("text_page", 0)), role)


@router.callback_query(TextCB.filter(F.action == "reset_ask"))
async def reset_ask(callback: CallbackQuery, callback_data: TextCB, role: str | None) -> None:
    if not _can_edit(role) or callback_data.key not in DEFAULT_TEXTS:
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    await render(callback, f"♻️ <b>{escape_html(callback_data.key)}</b> matnini "
                 "standart holatga qaytarishni tasdiqlaysizmi?",
                 InlineKeyboardMarkup(inline_keyboard=[
                     [_btn("✅ Qaytarish", "reset", callback_data.key, callback_data.page)],
                     [_btn("◀️ Bekor", "card", callback_data.key, callback_data.page)],
                 ]))
    await alert(callback, "")


@router.callback_query(TextCB.filter(F.action == "reset"))
async def reset(callback: CallbackQuery, callback_data: TextCB, session: AsyncSession,
                role: str | None) -> None:
    if not _can_edit(role) or callback_data.key not in DEFAULT_TEXTS:
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    await update_template(session, callback_data.key, None, callback.from_user.id)
    await session.commit()
    await text_service.publish()
    await render_card(callback, session, callback_data.key, callback_data.page, role)
    await alert(callback, "✅ Zavodga qaytarildi")
