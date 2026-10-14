"""💳 Tariflar bo'limi (Phase 2).

Imkoniyatlar:
  * ro'yxat va kartochka (narx, muddat, limitlar, statistika)
  * yaratish (FSM: nom → narx → muddat → e'lon → rasm)
  * har bir maydonni alohida tahrirlash (nom, tavsif, narx, muddat, limitlar)
  * faol/pauza, sinov tarifi belgisi, tartib (⬆️/⬇️)
  * o'chirish — bog'langan obuna/to'lov bo'lsa faqat to'xtatiladi (tarix saqlanadi)

Diqqat: bir xil FSM holati ikki vazifani (yaratish va tahrirlash) bajaradi.
Shuning uchun holat `data["flow"]` va `data["field"]` orqali ajratiladi —
aiogram bir holat uchun faqat **birinchi** mos handler'ni ishlatadi.
"""

from __future__ import annotations

from math import ceil
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole
from app.db.models import Tariff
from app.filters import IsAdmin
from app.keyboards.callbacks import TariffCB
from app.keyboards.common import PER_PAGE_TARIFFS
from app.keyboards.tariffs import cancel_kb, delete_confirm_kb, tariff_card_kb, tariffs_list_kb
from app.services import tariff_service
from app.states import AdminTariffStates
from app.utils.text import escape_html, truncate
from app.utils.tg import alert, render

router = Router(name="admin:tariffs")
# Tariflar bo'limi — admin va super admin uchun
router.message.filter(IsAdmin(AdminRole.ADMIN))
router.callback_query.filter(IsAdmin(AdminRole.ADMIN))

FIELD_TITLES = {
    "name": "✏️ Nom",
    "description": "📝 Tavsif",
    "price": "💰 Narx",
    "duration_days": "📅 Muddat",
    "max_ads": "📢 E'lon limiti",
    "max_photos": "🖼 Rasm limiti",
}

# callback action → (so'raladigan matn, FSM holati, yangilanadigan maydon)
FIELD_PROMPTS: dict[str, tuple[str, Any, str]] = {
    "rename": (
        "✏️ <b>Yangi nom</b>\nMasalan: <code>🟢 Boshlang'ich</code>",
        AdminTariffStates.waiting_name,
        "name",
    ),
    "desc": (
        "📝 <b>Tavsif</b>\nSotuvchi tarifni tanlaganda ko'radi.\nTozalash uchun <code>-</code> yuboring.",
        AdminTariffStates.waiting_description,
        "description",
    ),
    "price": (
        "💰 <b>Narx</b> (so'm)\nMasalan: <code>150000</code>",
        AdminTariffStates.waiting_price,
        "price",
    ),
    "days": (
        "📅 <b>Muddat</b> — necha kun?\n1–3650 (masalan <code>30</code>)",
        AdminTariffStates.waiting_days,
        "duration_days",
    ),
    "ads": (
        "📢 <b>E'lon limiti</b> — sotuvchi nechta e'lon joylay oladi?\n1–1000",
        AdminTariffStates.waiting_ads,
        "max_ads",
    ),
    "photos": (
        "🖼 <b>Rasm limiti</b> — har e'londa nechta rasm?\n1–10 (Telegram albom chegarasi)",
        AdminTariffStates.waiting_photos,
        "max_photos",
    ),
}

ALLOWED_GROUP_TEXT = (
    "🎯 Cheklov: <b>hammasi</b>\n"
    "<i>Aniq guruh/toifani tanlash e'lon joylash (Phase 3) bilan birga qo'shiladi.</i>"
)

RANGES = {
    "duration_days": (1, 3650, "1–3650"),
    "max_ads": (1, 1000, "1–1000"),
    "max_photos": (1, 10, "1–10"),
}


# ═══════════════════════════ Matnlar ═══════════════════════════════
def _list_text(tariffs: list[Tariff], total: int, active: int) -> str:
    lines = [
        "💳 <b>Tariflar</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Jami: <b>{total}</b>  ·  🟢 Faol: <b>{active}</b>",
        "",
    ]
    if not tariffs:
        lines.append("📭 Tarif yo'q. «➕ Yangi tarif» tugmasini bosing.")
    else:
        for tariff in tariffs:
            mark = "🟢" if tariff.is_active else "⏸"
            trial = " 🎁" if tariff.is_trial else ""
            lines.append(
                f"{mark} <b>{escape_html(tariff.name)}</b>{trial}\n"
                f"   └ 💰 {tariff_service.format_price(tariff)} · 📅 {tariff.duration_days} kun · "
                f"📢 {tariff.max_ads} · 🖼 {tariff.max_photos}"
            )
        lines.append("\n<i>Sotuvchiga tarif berish: 🛒 Sotuvchilar → kartochka → «💳 Tarif berish».</i>")
    return "\n".join(lines)


def _card_text(tariff: Tariff, stats: dict[str, int]) -> str:
    lines = [
        f"💳 <b>{escape_html(tariff.name)}</b>" + (" 🎁 sinov" if tariff.is_trial else ""),
        "━━━━━━━━━━━━━━━━━━━━",
        f"📌 Holat: {'🟢 Faol' if tariff.is_active else '⏸ To‘xtatilgan'}",
        f"💰 Narx: <b>{tariff_service.format_price(tariff)}</b>",
        f"📅 Muddat: <b>{tariff.duration_days} kun</b>",
        f"📢 E'lon limiti: <b>{tariff.max_ads}</b> ta",
        f"🖼 Rasm limiti: <b>{tariff.max_photos}</b> ta",
        f"🔢 Tartib: <b>#{tariff.position}</b>",
        ALLOWED_GROUP_TEXT,
    ]
    if tariff.description:
        lines.append(f"\n📝 {escape_html(truncate(tariff.description, 300))}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        f"🕘 Obunalar: <b>{stats['subscriptions']}</b> (faol {stats['active']})  ·  "
        f"💰 To'lovlar: <b>{stats['payments']}</b>"
    )
    return "\n".join(lines)


def _parse_page(value: str) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


# ══════════════════════════ Renderlar ══════════════════════════════
async def render_list(target, session: AsyncSession, page: int = 0) -> None:
    total = await tariff_service.count_tariffs(session)
    active = await tariff_service.count_tariffs(session, active_only=True)
    pages = max(1, ceil(total / PER_PAGE_TARIFFS))
    page = max(0, min(page, pages - 1))

    tariffs = await tariff_service.list_tariffs(
        session, offset=page * PER_PAGE_TARIFFS, limit=PER_PAGE_TARIFFS
    )
    await render(
        target, _list_text(tariffs, total, active), tariffs_list_kb(tariffs, page, pages)
    )


async def render_card(target, session: AsyncSession, tariff_id: int) -> bool:
    tariff = await tariff_service.get_tariff(session, tariff_id)
    if tariff is None:
        await render(target, "⚠️ Tarif topilmadi (o'chirilgan bo'lishi mumkin).")
        return False

    stats = await tariff_service.get_stats(session, tariff)
    await render(
        target, _card_text(tariff, stats), tariff_card_kb(tariff, subs=stats["subscriptions"])
    )
    return True


# ══════════════════════ Ko'rish (navigatsiya) ══════════════════════
@router.callback_query(TariffCB.filter(F.action == "list"))
async def on_list(callback: CallbackQuery, callback_data: TariffCB, session: AsyncSession) -> None:
    await render_list(callback, session, _parse_page(callback_data.value))
    await alert(callback, "")


@router.callback_query(TariffCB.filter(F.action == "card"))
async def on_card(callback: CallbackQuery, callback_data: TariffCB, session: AsyncSession) -> None:
    ok = await render_card(callback, session, callback_data.tariff_id)
    await alert(callback, "" if ok else "Tarif topilmadi")


# ══════════════ FSM: yaratish va tahrirlash (birlashtirilgan) ══════
@router.callback_query(TariffCB.filter(F.action == "create"))
async def start_create(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(flow="create")
    await state.set_state(AdminTariffStates.waiting_name)
    await render(
        callback,
        "➕ <b>Yangi tarif</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ Tarif nomini yuboring.\nMasalan: <code>🟢 Boshlang'ich</code>\n\n"
        "Bekor qilish uchun /cancel",
        cancel_kb(),
    )
    await alert(callback, "")


@router.callback_query(TariffCB.filter(F.action.in_(set(FIELD_PROMPTS))))
async def start_field_edit(
    callback: CallbackQuery, callback_data: TariffCB, state: FSMContext, session: AsyncSession
) -> None:
    tariff = await tariff_service.get_tariff(session, callback_data.tariff_id)
    if tariff is None:
        await alert(callback, "⚠️ Tarif topilmadi", show=True)
        return

    prompt, next_state, field = FIELD_PROMPTS[callback_data.action]
    await state.clear()
    await state.update_data(flow="edit", tariff_id=tariff.id, field=field)
    await state.set_state(next_state)
    await render(callback, f"{prompt}\n\nBekor qilish uchun /cancel", cancel_kb(tariff.id))
    await alert(callback, "")


async def _finish_edit(message: Message, session: AsyncSession, tariff: Tariff, field: str, value: Any) -> None:
    """Maydonni saqlash va kartochkani qayta chizish."""
    changed = await tariff_service.update_tariff(session, tariff, **{field: value})
    await message.answer("✅ Saqlandi." if changed else "ℹ️ Qiymat o'zgarmadi.")
    await render_card(message, session, tariff.id)


@router.message(StateFilter(AdminTariffStates.waiting_name), F.text)
async def step_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    name = (message.text or "").strip()

    if data.get("flow") == "edit":
        tariff = await tariff_service.get_tariff(session, int(data.get("tariff_id") or 0))
        await state.clear()
        if tariff is None:
            await message.answer("⚠️ Tarif topilmadi.")
            return
        if len(name) < 2:
            await message.answer("⚠️ Nom juda qisqa (kamida 2 belgi).")
            await render_card(message, session, tariff.id)
            return
        await _finish_edit(message, session, tariff, "name", name)
        return

    # Yaratish oqimi
    if len(name) < 2:
        await message.answer("⚠️ Nom juda qisqa. Qaytadan yuboring. Bekor qilish: /cancel")
        return
    await state.update_data(name=name)
    await state.set_state(AdminTariffStates.waiting_price)
    await message.answer(
        "2️⃣ Narxni yuboring (so'm).\nMasalan: <code>150000</code> — bepul bo'lsa <code>0</code>\n"
        "Bekor qilish uchun /cancel"
    )


@router.message(StateFilter(AdminTariffStates.waiting_price), F.text)
async def step_price(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    price = tariff_service.parse_price(message.text)

    if data.get("flow") == "edit":
        tariff = await tariff_service.get_tariff(session, int(data.get("tariff_id") or 0))
        if price is None:
            await message.answer("⚠️ Narxni raqamda yuboring (masalan 150000). Bekor qilish: /cancel")
            return
        await state.clear()
        if tariff is None:
            await message.answer("⚠️ Tarif topilmadi.")
            return
        await _finish_edit(message, session, tariff, "price", price)
        return

    if price is None:
        await message.answer("⚠️ Narxni raqamda yuboring (masalan 150000). Bekor qilish: /cancel")
        return
    await state.update_data(price=str(price))
    await state.set_state(AdminTariffStates.waiting_days)
    await message.answer("3️⃣ Muddat — necha kun? (masalan <code>30</code>)\nBekor qilish uchun /cancel")


async def _numeric_step(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    *,
    field: str,
    next_state: Any,
    next_prompt: str,
) -> bool:
    """Raqamli qadam: tahrirda saqlaydi, yaratishda keyingi holatga o'tadi.

    Qaytaradi: True — tahrir yakunlandi (yaratish oqimi emas).
    """
    data = await state.get_data()
    raw = (message.text or "").strip().lstrip("+")
    low, high, hint = RANGES[field]

    if not raw.isdigit() or not (low <= int(raw) <= high):
        await message.answer(f"⚠️ {hint} orasida son yuboring. Bekor qilish: /cancel")
        return True

    if data.get("flow") == "edit":
        tariff = await tariff_service.get_tariff(session, int(data.get("tariff_id") or 0))
        await state.clear()
        if tariff is None:
            await message.answer("⚠️ Tarif topilmadi.")
            return True
        await _finish_edit(message, session, tariff, field, int(raw))
        return True

    await state.update_data(**{field: int(raw)})
    await state.set_state(next_state)
    await message.answer(next_prompt)
    return False


@router.message(StateFilter(AdminTariffStates.waiting_days), F.text)
async def step_days(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _numeric_step(
        message,
        state,
        session,
        field="duration_days",
        next_state=AdminTariffStates.waiting_ads,
        next_prompt="4️⃣ Nechta e'lon joylashi mumkin? (masalan <code>10</code>)\nBekor qilish uchun /cancel",
    )


@router.message(StateFilter(AdminTariffStates.waiting_ads), F.text)
async def step_ads(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _numeric_step(
        message,
        state,
        session,
        field="max_ads",
        next_state=AdminTariffStates.waiting_photos,
        next_prompt=(
            "5️⃣ Har bir e'londa nechta rasm? (1–10)\n"
            "Telegram albom chegarasi — 10 ta.\nBekor qilish uchun /cancel"
        ),
    )


@router.message(StateFilter(AdminTariffStates.waiting_photos), F.text)
async def step_photos(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    raw = (message.text or "").strip()

    if data.get("flow") == "edit":
        await _numeric_step(
            message, state, session, field="max_photos", next_state=None, next_prompt=""
        )
        return

    if not raw.isdigit() or not (1 <= int(raw) <= 10):
        await message.answer("⚠️ 1–10 orasida son yuboring. Bekor qilish: /cancel")
        return

    await state.clear()
    tariff = await tariff_service.create_tariff(
        session,
        name=str(data.get("name") or ""),
        price=str(data.get("price") or "0"),
        duration_days=int(data.get("duration_days") or 30),
        max_ads=int(data.get("max_ads") or 5),
        max_photos=int(raw),
        created_by=message.from_user.id,
    )
    if tariff is None:
        await message.answer("⚠️ Tarifni yaratib bo'lmadi. Qaytadan urinib ko'ring.")
        await render_list(message, session, 0)
        return

    await message.answer(f"✅ Tarif yaratildi: <b>{escape_html(tariff.name)}</b>")
    await render_card(message, session, tariff.id)


@router.message(StateFilter(AdminTariffStates.waiting_description), F.text)
async def step_description(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    tariff = await tariff_service.get_tariff(session, int(data.get("tariff_id") or 0))
    await state.clear()
    if tariff is None:
        await message.answer("⚠️ Tarif topilmadi.")
        return

    raw = (message.text or "").strip()
    value = None if raw in ("-", "tozalash") else raw
    await _finish_edit(message, session, tariff, "description", value)


# ══════════════════════ Tumbler va tartib ══════════════════════════
@router.callback_query(TariffCB.filter(F.action == "active"))
async def on_toggle_active(callback: CallbackQuery, callback_data: TariffCB, session: AsyncSession) -> None:
    tariff = await tariff_service.get_tariff(session, callback_data.tariff_id)
    if tariff is None:
        await alert(callback, "⚠️ Tarif topilmadi", show=True)
        return

    active = not tariff.is_active
    await tariff_service.set_active(session, tariff, active)
    await render_card(callback, session, tariff.id)
    await alert(callback, "🟢 Yoqildi" if active else "⏸ To'xtatildi")


@router.callback_query(TariffCB.filter(F.action == "trial"))
async def on_toggle_trial(callback: CallbackQuery, callback_data: TariffCB, session: AsyncSession) -> None:
    tariff = await tariff_service.get_tariff(session, callback_data.tariff_id)
    if tariff is None:
        await alert(callback, "⚠️ Tarif topilmadi", show=True)
        return

    await tariff_service.update_tariff(session, tariff, is_trial=not tariff.is_trial)
    await render_card(callback, session, tariff.id)
    await alert(callback, "🎁 Sinov tarifi: ✅" if tariff.is_trial else "🎁 Sinov belgisi olindi")


@router.callback_query(TariffCB.filter(F.action.in_({"up", "down"})))
async def on_move(callback: CallbackQuery, callback_data: TariffCB, session: AsyncSession) -> None:
    tariff = await tariff_service.get_tariff(session, callback_data.tariff_id)
    if tariff is None:
        await alert(callback, "⚠️ Tarif topilmadi", show=True)
        return

    moved = await tariff_service.move(session, tariff, callback_data.action)
    await render_card(callback, session, tariff.id)
    await alert(callback, "✅ Tartib o'zgardi" if moved else "Chegaraga yetdi")


# ═══════════════════════════ O'chirish ═════════════════════════════
@router.callback_query(TariffCB.filter(F.action == "delete"))
async def on_delete(callback: CallbackQuery, callback_data: TariffCB, session: AsyncSession) -> None:
    tariff = await tariff_service.get_tariff(session, callback_data.tariff_id)
    if tariff is None:
        await alert(callback, "⚠️ Tarif topilmadi", show=True)
        return

    stats = await tariff_service.get_stats(session, tariff)
    text = (
        f"🗑 <b>{escape_html(tariff.name)}</b> — o'chirish\n\n"
        f"🕘 Bog'langan obunalar: <b>{stats['subscriptions']}</b>\n"
        f"💰 To'lovlar: <b>{stats['payments']}</b>\n\n"
    )
    text += (
        "⚠️ Bog'langan yozuvlar bor — tarif butunlay o'chirilmaydi, faqat to'xtatiladi "
        "(sotuvchilar tarixi saqlanadi)."
        if (stats["subscriptions"] or stats["payments"])
        else "⚠️ Bu amalni ortga qaytarib bo'lmaydi."
    )
    await render(
        callback,
        text,
        delete_confirm_kb(tariff, subs=stats["subscriptions"], payments=stats["payments"]),
    )
    await alert(callback, "")


@router.callback_query(TariffCB.filter(F.action == "delete_confirm"))
async def on_delete_confirm(callback: CallbackQuery, callback_data: TariffCB, session: AsyncSession) -> None:
    tariff = await tariff_service.get_tariff(session, callback_data.tariff_id)
    if tariff is None:
        await alert(callback, "⚠️ Tarif topilmadi", show=True)
        return

    tariff_id = tariff.id
    deleted, message = await tariff_service.delete_tariff(session, tariff)
    if deleted:
        await render_list(callback, session, 0)
    else:
        await render_card(callback, session, tariff_id)
    await alert(callback, message, show=True)


# ═══════════════════════════ Bekor qilish ══════════════════════════
@router.message(StateFilter(AdminTariffStates), Command("cancel"))
async def cancel_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    await state.clear()
    tariff_id = int(data.get("tariff_id") or 0)
    if tariff_id:
        await render_card(message, session, tariff_id)
    else:
        await render_list(message, session, 0)


__all__ = ["FIELD_TITLES", "render_card", "render_list", "router"]
