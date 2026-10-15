"""Phase 5: rekvizitlar paneli, chek navbati, faqat adminning qarori."""

from __future__ import annotations

from math import ceil

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole, PaymentStatus
from app.db.models import ActionLog, Payment, PaymentMethod
from app.filters import IsAdmin
from app.keyboards.callbacks import PaymentCB
from app.keyboards.payments import (
    REASONS,
    method_cancel_kb,
    method_card_kb,
    method_delete_kb,
    methods_list_kb,
    payment_card_kb,
    payment_home_kb,
    payment_list_kb,
    reject_reasons_kb,
)
from app.services import payment_service
from app.states import AdminPaymentStates
from app.utils.text import clean_text, escape_html, fmt_amount, truncate
from app.utils.tg import alert, render
from app.utils.time import fmt_date, fmt_dt

router = Router(name="admin:payments")
router.message.filter(StateFilter(AdminPaymentStates), IsAdmin(AdminRole.ADMIN))
router.callback_query.filter(PaymentCB.filter(), IsAdmin())

_STATUSES = {"all", "pending", "approved", "rejected", "cancelled"}


def _parse_page(value: str, *, filter_status: bool = False) -> tuple[int, str]:
    try:
        page_text, status = value.split("|", 1) if filter_status else (value, "pending")
        page = max(0, int(page_text))
    except ValueError:
        return 0, "pending" if filter_status else "all"
    return page, status if status in _STATUSES else "pending"


async def render_home(target: CallbackQuery | Message, session: AsyncSession) -> None:
    pending = await payment_service.count_payments(session, status="pending")
    total = await payment_service.count_payments(session)
    methods = await payment_service.list_methods(session, active_only=True, limit=10_000)
    text = (
        "💰 <b>To'lovlar</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 Chek navbati: <b>{pending}</b>\n"
        f"🕘 To'lovlar tarixi: <b>{total}</b>\n"
        f"💳 Faol kartalar: <b>{len(methods)}</b>\n\n"
        "<i>Pul faqat bank kartasiga o'tkaziladi; obuna admin qarorisiz berilmaydi.</i>"
    )
    await render(target, text, payment_home_kb())


async def render_list(
    target: CallbackQuery | Message, session: AsyncSession, page: int = 0, status: str = "pending",
) -> None:
    if status not in _STATUSES:
        status = "pending"
    total = await payment_service.count_payments(session, status=status)
    pages = max(1, ceil(total / payment_service.PAYMENT_PAGE))
    page = min(max(0, page), pages - 1)
    payments = await payment_service.list_payments(
        session, status=status, offset=page * payment_service.PAYMENT_PAGE,
    )
    label = "Kelgan cheklar" if status == "pending" else "To'lovlar tarixi"
    text = f"📥 <b>{label}</b>\nJami: {total} · sahifa {page + 1}/{pages}\n"
    if not payments:
        text += "\nChek topilmadi."
    elif status == "pending":
        text += "\n🔴 belgi — ilgari ishlatilgan chek; tasdiqlab bo'lmaydi."
    await render(target, text, payment_list_kb(payments, page=page, pages=pages, status=status))


def payment_detail(payment: Payment, method: PaymentMethod | None) -> str:
    label = {
        PaymentStatus.PENDING: "🕓 Tekshiruvda", PaymentStatus.APPROVED: "✅ Tasdiqlangan",
        PaymentStatus.REJECTED: "❌ Rad etilgan", PaymentStatus.CANCELLED: "⏸ Bekor qilingan",
    }.get(payment.status, payment.status)
    seller_name = payment.seller.display_name if payment.seller else str(payment.seller_id)
    tariff_name = payment.tariff.name if payment.tariff else str(payment.tariff_id)
    text = (
        f"🧾 <b>Chek #{payment.id}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🛒 Sotuvchi: <b>{escape_html(seller_name)}</b> (ID {payment.seller.user_id if payment.seller else payment.seller_id})\n"
        f"💳 Tarif: <b>{escape_html(tariff_name)}</b>\n"
        f"💰 Bankka: <b>{fmt_amount(payment.amount, payment.currency)}</b>\n"
        + (f"💸 Narx: {fmt_amount(payment.base_amount, payment.currency)} · "
           f"🎟 Chegirma: {fmt_amount(payment.discount_amount, payment.currency)} · "
           f"🎁 Balans: {fmt_amount(payment.balance_used, payment.currency)}\n"
           if payment.discount_amount or payment.balance_used else "")
        + f"🏦 Rekvizit: {escape_html(method.name) if method else '—'}"
        f" · {payment_service.mask_card(method.card_number) if method else '—'}\n"
        f"📅 Kelgan: {fmt_dt(payment.created_at)}\n"
        f"📌 Holat: <b>{label}</b>"
    )
    if payment.is_duplicate_receipt:
        text += "\n🔴 <b>Takroriy chek! Avtomatik tasdiqlash bloklangan.</b>"
    if payment.receipt_file_id is None:
        text += ("\n🎁 Bonus bilan 0 UZS: bankka to'lov yo'q; "
                 "bonus haqiqiyligini va sotuvchini tekshiring." if payment.amount == 0
                 else "\n⚠️ Rasm yuborilmagan; bank o'tkazmasini qo'lda tekshiring.")
    if payment.reason:
        text += f"\n❌ Sabab: {escape_html(truncate(payment.reason, 300))}"
    if payment.subscription_id:
        text += f"\n🎫 Obuna #{payment.subscription_id}"
    return text


async def render_card(
    target: CallbackQuery | Message, session: AsyncSession, payment_id: int,
    *, page: int = 0, status: str = "pending",
) -> Payment | None:
    payment = await payment_service.get_payment(session, payment_id)
    if payment is None:
        await render(target, "⚠️ Chek topilmadi.")
        return None
    method = await payment_service.get_method(session, payment.method_id) if payment.method_id else None
    await render(target, payment_detail(payment, method), payment_card_kb(payment, page=page, status=status))
    return payment


async def render_methods(target: CallbackQuery | Message, session: AsyncSession, page: int = 0) -> None:
    count = await payment_service.count_methods(session)
    pages = max(1, ceil(count / payment_service.METHOD_PAGE))
    page = min(max(0, page), pages - 1)
    methods = await payment_service.list_methods(
        session, offset=page * payment_service.METHOD_PAGE,
    )
    text = (
        f"💳 <b>To'lov rekvizitlari</b>\nJami {count} · sahifa {page + 1}/{pages}\n\n"
        "Kartalar faqat shu panelda saqlanadi. Bir nechta faol karta cheklar ketma-ketligida aylanadi.\n"
        "⏸ To'xtatilgan karta tarixni saqlash uchun bazadan o'chirilmaydi."
    )
    await render(target, text, methods_list_kb(methods, page=page, pages=pages))


async def render_method_card(
    target: CallbackQuery | Message, session: AsyncSession, method_id: int, page: int = 0,
) -> PaymentMethod | None:
    method = await payment_service.get_method(session, method_id)
    if method is None:
        await render(target, "⚠️ Karta topilmadi.")
        return None
    text = (
        f"💳 <b>{escape_html(method.name)}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 {'🟢 Faol' if method.is_active else '⏸ To‘xtatilgan'}\n"
        f"🔢 Karta: <code>{method.card_number}</code>\n"
        f"👤 Egasi: {escape_html(method.holder) or '—'}\n"
        f"🏦 Bank: {escape_html(method.bank) or '—'}\n"
        f"💱 Valyuta: {escape_html(method.currency)}\n"
        f"📝 Izoh: {escape_html(truncate(method.note, 250)) if method.note else '—'}\n"
        f"🔀 Tartib: #{method.position}"
    )
    await render(target, text, method_card_kb(method, page=page))
    return method


async def _inform_seller(bot: Bot, payment: Payment, subscription=None) -> None:
    if payment.seller is None:
        return
    if subscription is not None:
        text = (
            "🎉 <b>To'lovingiz tasdiqlandi!</b>\n"
            f"🧾 Chek: #{payment.id}\n"
            f"💳 Tarif: {escape_html(payment.tariff.name if payment.tariff else '—')}\n"
            f"📅 Muddat: {fmt_date(subscription.expires_at)} gacha\n"
            f"📢 E'lon limiti: {subscription.ads_limit}\n"
            "Endi sotuvchi panelidan e'lon qo'shishingiz mumkin."
        )
    else:
        text = (
            f"❌ <b>Chek #{payment.id} rad etildi.</b>\n"
            f"Sabab: {escape_html(payment.reason)}\n"
            "Tarif katalogidan yangi to'lovni boshlashingiz yoki admin bilan bog'lanishingiz mumkin."
        )
    try:
        await bot.send_message(payment.seller.user_id, text)
    except TelegramAPIError as exc:
        logger.warning("Chek #{} qarori sotuvchiga yuborilmadi: {}", payment.id, exc)


@router.callback_query(PaymentCB.filter(F.action == "home"), IsAdmin(AdminRole.ADMIN))
async def on_home(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await render_home(callback, session)
    await alert(callback, "")


@router.callback_query(PaymentCB.filter(F.action == "list"), IsAdmin(AdminRole.ADMIN))
async def on_list(callback: CallbackQuery, callback_data: PaymentCB, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    page, status = _parse_page(callback_data.value, filter_status=True)
    await render_list(callback, session, page, status)
    await alert(callback, "")


@router.callback_query(PaymentCB.filter(F.action == "card"), IsAdmin(AdminRole.ADMIN))
async def on_card(
    callback: CallbackQuery, callback_data: PaymentCB, session: AsyncSession,
    state: FSMContext, bot: Bot,
) -> None:
    await state.clear()
    page, status = _parse_page(callback_data.value, filter_status=True)
    payment = await render_card(callback, session, callback_data.target_id, page=page, status=status)
    if payment and payment.receipt_file_id and not (callback.message and callback.message.photo):
        try:
            await bot.send_photo(
                callback.from_user.id, payment.receipt_file_id,
                caption=f"📷 Chek #{payment.id} · {fmt_amount(payment.amount, payment.currency)}",
                reply_markup=payment_card_kb(payment, page=page, status=status),
            )
        except TelegramAPIError as exc:
            logger.warning("Chek #{} rasmini ko'rsatib bo'lmadi: {}", payment.id, exc)
    await alert(callback, "")


@router.callback_query(PaymentCB.filter(F.action == "approve"), IsAdmin(AdminRole.ADMIN))
async def on_approve(callback: CallbackQuery, callback_data: PaymentCB, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    payment = await payment_service.get_payment(session, callback_data.target_id)
    if payment is None or payment.status != PaymentStatus.PENDING or payment.is_duplicate_receipt:
        await alert(callback, "⚠️ Bu chekni tasdiqlab bo'lmaydi. Holatni yangilang.", show=True)
        return
    text = (
        f"⚠️ <b>Chek #{payment.id} tasdiqlansinmi?</b>\n"
        f"💰 Summa: <b>{fmt_amount(payment.amount, payment.currency)}</b>\n"
        f"💳 Tarif: {escape_html(payment.tariff.name if payment.tariff else '—')}\n\n"
        "Bankingizdagi haqiqiy o'tkazmani tekshirdingizmi? Chekni o'zi to'lov isboti emas."
    )
    page, status = _parse_page(callback_data.value, filter_status=True)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Ha, bankda tekshirdim", callback_data=PaymentCB(
                action="approve_confirm", target_id=payment.id, value=callback_data.value,
            ).pack(),
        )],
        [InlineKeyboardButton(
            text="❌ Bekor", callback_data=PaymentCB(
                action="card", target_id=payment.id, value=f"{page}|{status}",
            ).pack(),
        )],
    ])
    await render(callback, text, markup)
    await alert(callback, "")


@router.callback_query(PaymentCB.filter(F.action == "approve_confirm"), IsAdmin(AdminRole.ADMIN))
async def on_approve_confirm(
    callback: CallbackQuery, callback_data: PaymentCB, session: AsyncSession, bot: Bot,
) -> None:
    result = await payment_service.decide(
        session, callback_data.target_id, admin_id=callback.from_user.id, approve=True,
    )
    if result.status != "approved":
        await alert(callback, {
            "already": "⚠️ Bu chekka avval qaror berilgan.",
            "duplicate": "🔴 Takroriy chek tasdiqlanmaydi. Rad eting.",
            "blocked": "🚫 Sotuvchi bloklangan. Avval hisobini tekshiring.",
        }.get(result.status, "⚠️ Chek topilmadi."), show=True)
        return
    await session.commit()  # sotuvchiga xabardan oldin qaror va obuna birga saqlanadi
    await _inform_seller(bot, result.payment, result.subscription)
    page, status = _parse_page(callback_data.value, filter_status=True)
    await render_card(callback, session, result.payment.id, page=page, status=status)
    await alert(callback, "✅ To'lov tasdiqlandi, obuna faollashdi.", show=True)


@router.callback_query(PaymentCB.filter(F.action == "reject"), IsAdmin(AdminRole.ADMIN))
async def on_reject(callback: CallbackQuery, callback_data: PaymentCB, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    payment = await payment_service.get_payment(session, callback_data.target_id)
    if payment is None or payment.status != PaymentStatus.PENDING:
        await alert(callback, "⚠️ Bu chekka allaqachon qaror berilgan.", show=True)
        return
    page, status = _parse_page(callback_data.value, filter_status=True)
    await render(
        callback, f"❌ <b>Chek #{payment.id}</b> — rad etish sababini tanlang:",
        reject_reasons_kb(payment.id, page=page, status=status),
    )
    await alert(callback, "")


async def _reject(
    target: CallbackQuery | Message, session: AsyncSession, bot: Bot,
    payment_id: int, admin_id: int, reason: str,
) -> None:
    result = await payment_service.decide(
        session, payment_id, admin_id=admin_id, approve=False, reason=reason,
    )
    if result.status != "rejected":
        if isinstance(target, CallbackQuery):
            await alert(target, "⚠️ Chek allaqachon ko'rilgan yoki sabab yaroqsiz.", show=True)
        else:
            await target.answer("⚠️ Chek allaqachon ko'rilgan yoki sabab yaroqsiz.")
        return
    await session.commit()
    await _inform_seller(bot, result.payment)
    await render_card(target, session, payment_id)
    if isinstance(target, CallbackQuery):
        await alert(target, "❌ Chek rad etildi.", show=True)


@router.callback_query(PaymentCB.filter(F.action == "reason"), IsAdmin(AdminRole.ADMIN))
async def on_reason(
    callback: CallbackQuery, callback_data: PaymentCB, session: AsyncSession,
    state: FSMContext, bot: Bot,
) -> None:
    if callback_data.value == "custom":
        await state.set_state(AdminPaymentStates.waiting_reject_reason)
        await state.update_data(payment_id=callback_data.target_id)
        await render(callback, "✏️ Rad etish sababini yuboring (3–300 belgi). Bekor: /cancel")
        await alert(callback, "")
        return
    reason = next((label for key, label in REASONS if key == callback_data.value), None)
    if reason is None:
        await alert(callback, "⚠️ Sabab topilmadi.", show=True)
        return
    await _reject(callback, session, bot, callback_data.target_id, callback.from_user.id, reason)


@router.message(StateFilter(AdminPaymentStates), F.text == "/cancel")
async def cancel_fsm(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Jarayon bekor qilindi.")


@router.message(StateFilter(AdminPaymentStates.waiting_reject_reason), F.text)
async def reject_custom(
    message: Message, session: AsyncSession, state: FSMContext, bot: Bot,
) -> None:
    if (message.text or "").strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Rad etish bekor qilindi.")
        return
    reason = clean_text(message.text, limit=300)
    if not reason or len(reason) < 3:
        await message.answer("⚠️ Sabab 3–300 belgidan iborat bo'lsin.")
        return
    payment_id = int((await state.get_data()).get("payment_id") or 0)
    await state.clear()
    await _reject(message, session, bot, payment_id, message.from_user.id, reason)


@router.callback_query(PaymentCB.filter(F.action == "methods"), IsAdmin(AdminRole.ADMIN))
async def on_methods(callback: CallbackQuery, callback_data: PaymentCB, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    page, _ = _parse_page(callback_data.value)
    await render_methods(callback, session, page)
    await alert(callback, "")


@router.callback_query(PaymentCB.filter(F.action == "method_card"), IsAdmin(AdminRole.ADMIN))
async def on_method_card(
    callback: CallbackQuery, callback_data: PaymentCB, session: AsyncSession, state: FSMContext,
) -> None:
    await state.clear()
    page, _ = _parse_page(callback_data.value)
    await render_method_card(callback, session, callback_data.target_id, page)
    await alert(callback, "")


@router.callback_query(PaymentCB.filter(F.action == "method_new"), IsAdmin(AdminRole.ADMIN))
async def on_method_new(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminPaymentStates.waiting_method_name)
    await state.update_data(flow="create")
    await render(callback, "💳 <b>Yangi karta</b>\n1️⃣ Nomi (masalan Uzcard). Bekor: /cancel", method_cancel_kb())
    await alert(callback, "")


@router.message(StateFilter(AdminPaymentStates.waiting_method_name), F.text)
async def method_name(message: Message, state: FSMContext) -> None:
    name = clean_text(message.text, limit=64)
    if not name or len(name) < 2:
        await message.answer("⚠️ Nomi kamida 2 belgi bo'lsin.")
        return
    await state.update_data(name=name)
    await state.set_state(AdminPaymentStates.waiting_card)
    await message.answer("2️⃣ Karta raqamini yuboring (16–19 raqam; bo'shliq bo'lishi mumkin). Bekor: /cancel")


@router.message(StateFilter(AdminPaymentStates.waiting_card), F.text)
async def method_card_number(message: Message, state: FSMContext) -> None:
    card = payment_service.normalize_card(message.text or "")
    if card is None:
        await message.answer("⚠️ Karta raqami 16–19 ta raqamdan iborat bo'lsin.")
        return
    await state.update_data(card_number=card)
    await state.set_state(AdminPaymentStates.waiting_holder)
    await message.answer("3️⃣ Karta egasining ismi (yo'q bo'lsa «-»). Bekor: /cancel")


@router.message(StateFilter(AdminPaymentStates.waiting_holder), F.text)
async def method_holder(message: Message, state: FSMContext) -> None:
    await state.update_data(holder=None if message.text.strip() == "-" else message.text)
    await state.set_state(AdminPaymentStates.waiting_bank)
    await message.answer("4️⃣ Bank nomi (yo'q bo'lsa «-»). Bekor: /cancel")


@router.message(StateFilter(AdminPaymentStates.waiting_bank), F.text)
async def method_bank(message: Message, state: FSMContext) -> None:
    await state.update_data(bank=None if message.text.strip() == "-" else message.text)
    await state.set_state(AdminPaymentStates.waiting_note)
    await message.answer("5️⃣ Sotuvchiga ko'rinadigan izoh (yo'q bo'lsa «-»). Bekor: /cancel")


@router.message(StateFilter(AdminPaymentStates.waiting_note), F.text)
async def method_note(message: Message, state: FSMContext) -> None:
    await state.update_data(note=None if message.text.strip() == "-" else message.text)
    await state.set_state(AdminPaymentStates.waiting_currency)
    await message.answer("6️⃣ Valyuta kodi (masalan UZS). Standart UZS uchun «-» yuboring. Bekor: /cancel")


@router.message(StateFilter(AdminPaymentStates.waiting_currency), F.text)
async def method_currency(message: Message, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    currency = "UZS" if message.text.strip() == "-" else message.text.strip()
    try:
        method = await payment_service.create_method(
            session, name=data.get("name", ""), card_number=data.get("card_number", ""),
            holder=data.get("holder"), bank=data.get("bank"), note=data.get("note"),
            currency=currency,
        )
    except ValueError as exc:
        await message.answer(f"⚠️ {escape_html(str(exc))} Qayta kiriting.")
        return
    session.add(ActionLog(
        actor_id=message.from_user.id, action="payment_method_create", entity="payment_method",
        entity_id=method.id, after={"name": method.name, "last4": method.card_number[-4:]},
    ))
    await state.clear()
    await message.answer(f"✅ {escape_html(method.name)} kartasi saqlandi.")
    await render_method_card(message, session, method.id)


@router.callback_query(PaymentCB.filter(F.action == "method_edit"), IsAdmin(AdminRole.ADMIN))
async def on_method_edit(
    callback: CallbackQuery, callback_data: PaymentCB, session: AsyncSession, state: FSMContext,
) -> None:
    method = await payment_service.get_method(session, callback_data.target_id)
    if method is None or callback_data.value not in {"name", "card_number", "holder", "bank", "note", "currency"}:
        await alert(callback, "⚠️ Karta yoki maydon topilmadi.", show=True)
        return
    await state.set_state(AdminPaymentStates.waiting_edit)
    await state.update_data(method_id=method.id, field=callback_data.value)
    label = {"name": "nom", "card_number": "karta raqami", "holder": "egasi", "bank": "bank", "note": "izoh", "currency": "valyuta"}[callback_data.value]
    await render(callback, f"✏️ Yangi {label}ni yuboring. Ixtiyoriy maydonni tozalash: «-». Bekor: /cancel", method_cancel_kb(method.id))
    await alert(callback, "")


@router.message(StateFilter(AdminPaymentStates.waiting_edit), F.text)
async def method_edit(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Tahrir bekor qilindi.")
        return
    data = await state.get_data()
    method = await payment_service.get_method(session, int(data.get("method_id") or 0))
    if method is None:
        await state.clear()
        await message.answer("⚠️ Karta topilmadi.")
        return
    field = str(data.get("field") or "")
    before = method.card_number[-4:] if field == "card_number" else str(getattr(method, field, ""))
    try:
        await payment_service.update_method(session, method, field, message.text)
    except ValueError as exc:
        await message.answer(f"⚠️ {escape_html(str(exc))}")
        return
    after = method.card_number[-4:] if field == "card_number" else str(getattr(method, field, ""))
    session.add(ActionLog(
        actor_id=message.from_user.id, action="payment_method_edit", entity="payment_method",
        entity_id=method.id, before={field: before}, after={field: after},
    ))
    await state.clear()
    await message.answer("✅ Rekvizit yangilandi.")
    await render_method_card(message, session, method.id)


@router.callback_query(PaymentCB.filter(F.action.in_({"method_toggle", "method_up", "method_down"})), IsAdmin(AdminRole.ADMIN))
async def change_method(
    callback: CallbackQuery, callback_data: PaymentCB, session: AsyncSession,
) -> None:
    method = await payment_service.get_method(session, callback_data.target_id)
    if method is None:
        await alert(callback, "⚠️ Karta topilmadi.", show=True)
        return
    action = callback_data.action
    before = method.is_active if action == "method_toggle" else method.position
    if action == "method_toggle":
        method.is_active = not method.is_active
        await session.flush()
        changed = True
    else:
        changed = await payment_service.move_method(session, method, action.removeprefix("method_"))
    if changed:
        session.add(ActionLog(
            actor_id=callback.from_user.id, action=action, entity="payment_method",
            entity_id=method.id, before={"value": before},
            after={"value": method.is_active if action == "method_toggle" else method.position},
        ))
    page, _ = _parse_page(callback_data.value)
    await render_method_card(callback, session, method.id, page)
    await alert(callback, "✅ Yangilandi" if changed else "Chegaraga yetildi")


@router.callback_query(PaymentCB.filter(F.action == "method_delete"), IsAdmin(AdminRole.ADMIN))
async def on_method_delete(
    callback: CallbackQuery, callback_data: PaymentCB, session: AsyncSession,
) -> None:
    method = await payment_service.get_method(session, callback_data.target_id)
    if method is None:
        await alert(callback, "⚠️ Karta topilmadi.", show=True)
        return
    page, _ = _parse_page(callback_data.value)
    await render(
        callback,
        f"🗑 <b>{escape_html(method.name)}</b> · {payment_service.mask_card(method.card_number)}\n\n"
        "Kartani to'xtatasizmi? Avvalgi cheklar va sotuvchiga berilgan rekvizit tarixi "
        "saqlanishi uchun karta bazadan o'chirilmaydi.",
        method_delete_kb(method.id, page),
    )
    await alert(callback, "")


@router.callback_query(PaymentCB.filter(F.action == "method_delete_confirm"), IsAdmin(AdminRole.ADMIN))
async def on_method_delete_confirm(
    callback: CallbackQuery, callback_data: PaymentCB, session: AsyncSession,
) -> None:
    method = await payment_service.get_method(session, callback_data.target_id)
    if method is None:
        await alert(callback, "⚠️ Karta topilmadi.", show=True)
        return
    was_active = method.is_active
    method.is_active = False
    await session.flush()
    if was_active:
        session.add(ActionLog(
            actor_id=callback.from_user.id, action="payment_method_retire",
            entity="payment_method", entity_id=method.id,
            before={"active": True}, after={"active": False},
        ))
    page, _ = _parse_page(callback_data.value)
    await render_method_card(callback, session, method.id, page)
    await alert(callback, "⏸ Karta to'xtatildi.", show=True)


@router.message(StateFilter(AdminPaymentStates), F.text)
async def payment_fsm_help(message: Message, state: FSMContext) -> None:
    """Noma'lum yoki /cancel qadam: vaqtinchalik karta ma'lumotini saqlamaymiz."""
    if (message.text or "").strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Jarayon bekor qilindi.")
    else:
        await message.answer("⚠️ Avval so'ralgan qiymatni yuboring yoki /cancel bosing.")


@router.callback_query()
async def on_denied(callback: CallbackQuery) -> None:
    await alert(callback, "⛔️ To'lovlarni faqat admin boshqaradi.", show=True)
