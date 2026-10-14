"""⚙️ Global sozlamalar: kill switch, texnik rejim, interval, yordam kontakti.

Bu bo'lim Phase 0 da to'liq ishlaydi — chunki u butun tizimning
"boshqaruv markazi" (REJA.md "asosiy qoida": kodga tegmasdan boshqarish).
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters import IsAdmin
from app.keyboards import settings_kb
from app.keyboards.callbacks import AdminCB
from app.services.settings_service import DEFAULTS, settings_service
from app.states import AdminSettingsStates

router = Router(name="admin:settings")

# Tumbler (on/off) ko'rinishidagi sozlamalar
TOGGLE_KEYS = {"kill_switch", "maintenance_mode", "referral_enabled", "receipt_required"}

LABELS = {
    "kill_switch": "🛑 Hammani to'xtatish",
    "maintenance_mode": "🔧 Texnik rejim",
    "referral_enabled": "🤝 Referal",
    "receipt_required": "🧾 Chek majburiy",
    "support_contact": "☎️ Yordam kontakti",
    "default_interval_sec": "⏱ Joylash intervali",
}


def _format_settings(values: dict[str, object]) -> str:
    interval = int(values.get("default_interval_sec", DEFAULTS["default_interval_sec"]) or 1800) // 60
    return (
        "⚙️ <b>Global sozlamalar</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🛑 Hammani to'xtatish: <b>{'YOQILGAN' if values.get('kill_switch') else 'o‘chirilgan'}</b>\n"
        f"🔧 Texnik rejim: <b>{'YOQILGAN' if values.get('maintenance_mode') else 'o‘chirilgan'}</b>\n"
        f"🤝 Referal tizimi: <b>{'YOQILGAN' if values.get('referral_enabled') else 'o‘chirilgan'}</b>\n"
        f"🧾 Chek majburiy: <b>{'ha' if values.get('receipt_required') else 'yo‘q'}</b>\n"
        f"⏱ Default joylash intervali: <b>{interval} daqiqa</b>\n"
        f"☎️ Yordam kontakti: <b>{values.get('support_contact') or '—'}</b>\n"
        f"🗄 Loglarni saqlash: <b>{values.get('log_retention_days')} kun</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>O'zgarishlar botni qayta yoqmasdan darhol kuchga kiradi.</i>"
    )


async def render_settings_screen(
    callback: CallbackQuery, session: AsyncSession, role: str | None = None
) -> None:
    """Sozlamalar ekranini chizish (yangi xabar yoki mavjudni tahrirlash)."""
    values = await settings_service.get_all(session)
    text = _format_settings(values)
    markup = settings_kb(values)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback.message.answer(text, reply_markup=markup)
    _ = role


@router.callback_query(IsAdmin(), AdminCB.filter(F.action == "toggle"))
async def toggle_setting(
    callback: CallbackQuery,
    callback_data: AdminCB,
    session: AsyncSession,
    role: str | None,
) -> None:
    key = callback_data.value
    if key not in TOGGLE_KEYS:
        await callback.answer("⚠️ Bu sozlamani o'zgartirib bo'lmaydi.", show_alert=True)
        return

    current = bool(await settings_service.get(key, DEFAULTS.get(key, False), session))
    new_value = not current
    await settings_service.set(session, key, new_value, updated_by=callback.from_user.id)

    label = LABELS.get(key, key)
    logger.info("Admin {} '{}' sozlamasini {} qildi", callback.from_user.id, key, new_value)

    await render_settings_screen(callback, session, role)
    await callback.answer(
        f"{label}: {'YOQILGAN ✅' if new_value else 'o‘chirilgan ❌'}",
        show_alert=new_value,  # yoqilganda ogohlantirish sifatida ko'rsatiladi
    )


@router.callback_query(IsAdmin(), AdminCB.filter(F.action == "edit"))
async def start_edit(
    callback: CallbackQuery,
    callback_data: AdminCB,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    key = callback_data.value

    if key == "support_contact":
        current = await settings_service.get("support_contact", "—", session)
        await state.set_state(AdminSettingsStates.waiting_support_contact)
        await callback.message.answer(
            "☎️ <b>Yangi yordam kontakti</b>\n"
            f"Hozirgi qiymat: <b>{current}</b>\n\n"
            "@username yoki telefon raqam yuboring.\n"
            "Bekor qilish uchun /cancel"
        )
    elif key == "default_interval_sec":
        current = int(await settings_service.get("default_interval_sec", 1800, session) or 1800) // 60
        await state.set_state(AdminSettingsStates.waiting_interval)
        await callback.message.answer(
            "⏱ <b>Yangi interval</b>\n"
            f"Hozirgi qiymat: <b>{current} daqiqa</b>\n\n"
            "1 dan 1440 gacha daqiqa yuboring (raqam bilan).\n"
            "Bekor qilish uchun /cancel"
        )
    else:
        await callback.answer("⚠️ Noma'lum sozlama.", show_alert=True)
        return

    await callback.answer()


@router.message(IsAdmin(), Command("cancel"), StateFilter(AdminSettingsStates))
async def cancel_edit(message: Message, state: FSMContext, session: AsyncSession, role: str | None) -> None:
    await state.clear()
    values = await settings_service.get_all(session)
    await message.answer(_format_settings(values), reply_markup=settings_kb(values))
    _ = role


@router.message(IsAdmin(), StateFilter(AdminSettingsStates.waiting_support_contact), F.text)
async def apply_support_contact(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = (message.text or "").strip()
    if not value or len(value) > 64:
        await message.answer("⚠️ Noto'g'ri qiymat. @username yoki telefon raqam yuboring.")
        return

    await settings_service.set(session, "support_contact", value, updated_by=message.from_user.id)
    await state.clear()
    values = await settings_service.get_all(session)
    await message.answer(
        f"✅ Yordam kontakti yangilandi: <b>{value}</b>\n\n" + _format_settings(values),
        reply_markup=settings_kb(values),
    )


@router.message(IsAdmin(), StateFilter(AdminSettingsStates.waiting_interval), F.text)
async def apply_interval(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("⚠️ Faqat raqam yuboring (daqiqada).")
        return

    minutes = int(raw)
    if not 1 <= minutes <= 1440:
        await message.answer("⚠️ Qiymat 1 dan 1440 daqiqagacha bo'lishi kerak.")
        return

    await settings_service.set(
        session, "default_interval_sec", minutes * 60, updated_by=message.from_user.id
    )
    await state.clear()
    values = await settings_service.get_all(session)
    await message.answer(
        f"✅ Interval yangilandi: <b>{minutes} daqiqa</b>\n\n" + _format_settings(values),
        reply_markup=settings_kb(values),
    )


__all__ = ["router", "render_settings_screen"]
