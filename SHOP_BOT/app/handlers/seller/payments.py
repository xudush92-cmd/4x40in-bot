"""Phase 5: sotuvchi tarifni tanlaydi → rekvizit → chek → admin navbati."""

from __future__ import annotations

from decimal import Decimal
from math import ceil

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import PaymentStatus
from app.db.models import ActionLog, Payment, Seller
from app.filters import IsSeller, PrivateChat
from app.keyboards.callbacks import SellerPanelCB
from app.keyboards.payments import (
    seller_history_detail_kb,
    seller_history_kb,
    seller_pay_kb,
)
from app.keyboards.seller_panel import back_to_menu_kb
from app.services import payment_service, seller_service, tariff_service
from app.services.notify import notify_payment_admins
from app.services.settings_service import settings_service
from app.states import SellerPaymentStates
from app.utils.text import escape_html, fmt_amount, truncate
from app.utils.tg import alert, render
from app.utils.time import fmt_dt

router = Router(name="seller:payments")
router.callback_query.filter(SellerPanelCB.filter(), PrivateChat(), IsSeller())
router.message.filter(StateFilter(SellerPaymentStates), PrivateChat(), IsSeller())


async def _owner(session: AsyncSession, user_id: int) -> Seller:
    # IsSeller() avval tekshiradi. DB'da o'chib ketgan holat uchun ham ehtiyot.
    seller = await seller_service.get_seller(session, user_id)
    if seller is None:
        raise ValueError("Sotuvchi yozuvi topilmadi.")
    return seller


@router.callback_query(SellerPanelCB.filter(F.action == "pay"))
async def start_payment(
    callback: CallbackQuery, callback_data: SellerPanelCB, session: AsyncSession, state: FSMContext,
) -> None:
    try:
        tariff_id = int(callback_data.value)
    except ValueError:
        await alert(callback, "⚠️ Tarif tugmasi eskirgan.", show=True)
        return
    tariff = await tariff_service.get_tariff(session, tariff_id)
    if tariff is None or not tariff.is_active or tariff.price <= 0:
        await alert(callback, "⚠️ Tarif faol emas yoki pullik emas. Katalogni yangilang.", show=True)
        return
    method = await payment_service.choose_method(session, tariff.currency)
    if method is None:
        await render(
            callback,
            "⚠️ Bu valyuta uchun faol to'lov kartasi yo'q. Iltimos, admin bilan bog'laning.",
            back_to_menu_kb(),
        )
        await alert(callback, "Karta topilmadi", show=True)
        return
    await state.set_state(SellerPaymentStates.waiting_receipt)
    await state.update_data(
        tariff_id=tariff.id, method_id=method.id,
        amount=str(tariff.price), currency=tariff.currency,
    )
    receipt_required = bool(await settings_service.get("receipt_required", True, session))
    lines = [
        "💳 <b>To'lov rekviziti</b>",
        f"📦 Tarif: <b>{escape_html(tariff.name)}</b>",
        f"💰 Summa: <b>{fmt_amount(tariff.price, tariff.currency)}</b>",
        f"🏦 Karta: <b>{escape_html(method.name)}</b>",
        f"🔢 Raqam: <code>{method.card_number}</code>",
    ]
    if method.holder:
        lines.append(f"👤 Egasi: {escape_html(method.holder)}")
    if method.bank:
        lines.append(f"🏛 Bank: {escape_html(method.bank)}")
    if method.note:
        lines.append(f"📝 Izoh: {escape_html(truncate(method.note, 350))}")
    lines += [
        "", "⚠️ To'lov miqdori va karta raqamini tekshiring.",
        "Pul o'tkazgach chekni <b>rasm sifatida</b> shu chatga yuboring." if receipt_required
        else "Chek rasmini yuboring yoki «Cheksiz yuborish»ni bosing — admin o'tkazmani qo'lda tekshiradi.",
        "<i>Obuna faqat admin tasdiqlagandan keyin beriladi. Bot o'zi pul yechmaydi.</i>",
    ]
    await render(callback, "\n".join(lines), seller_pay_kb(method.card_number, receipt_required=receipt_required))
    await alert(callback, "")


async def _submit(
    target: Message | CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot,
    *, file_id: str | None, file_unique_id: str | None,
) -> None:
    data = await state.get_data()
    seller = await _owner(session, target.from_user.id)
    tariff = await tariff_service.get_tariff(session, int(data.get("tariff_id") or 0))
    method = await payment_service.get_method(session, int(data.get("method_id") or 0))
    if tariff is None or method is None:
        await state.clear()
        await render(target, "⚠️ Rekvizit yoki tarif o'zgargan. Admin bilan bog'laning.", back_to_menu_kb())
        return
    try:
        payment = await payment_service.submit_receipt(
            session, seller=seller, tariff=tariff, method=method,
            file_id=file_id, file_unique_id=file_unique_id,
            quoted_amount=Decimal(str(data.get("amount") or 0)),
            quoted_currency=str(data.get("currency") or tariff.currency),
        )
    except ValueError as exc:
        await render(target, f"⚠️ {escape_html(str(exc))}\nKatalogga qaytish yoki admin bilan bog'lanish mumkin.")
        return

    session.add(ActionLog(
        actor_id=seller.user_id, action="payment_submitted", entity="payment", entity_id=payment.id,
        after={"status": payment.status, "duplicate": payment.is_duplicate_receipt},
    ))
    # Telegram orqali adminga yuborishdan OLDIN chek va audit yozuvini saqlaymiz.
    await session.commit()
    await state.clear()
    note = "\n🔴 Chek avval ham yuborilgan — admin yangi chek so'rashi mumkin." if payment.is_duplicate_receipt else ""
    try:
        await render(
            target,
            f"📥 <b>Chek #{payment.id} qabul qilindi.</b>\n"
            "Admin tekshiradi; tasdiqlansa obuna avtomatik faollashadi."
            f"{note}",
            back_to_menu_kb(),
        )
        if isinstance(target, CallbackQuery):
            await alert(target, "Chek navbatga qo'shildi")
    except TelegramAPIError as exc:
        # Sotuvchi botni bloklagan bo'lsa ham adminning chek xabari yo'qolmasin.
        logger.warning("Chek #{} qabul xabari sotuvchiga yuborilmadi: {}", payment.id, exc)
    try:
        await notify_payment_admins(bot, payment.id)
    except Exception as exc:  # navbat commit bo'lgan; xabar xatosi to'lovni o'chirmaydi
        logger.exception("Chek #{} xabarnomasi yuborilmadi: {}", payment.id, exc)


@router.message(StateFilter(SellerPaymentStates.waiting_receipt), F.photo)
async def receive_photo(message: Message, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    photo = message.photo[-1]
    await _submit(message, session, state, bot, file_id=photo.file_id, file_unique_id=photo.file_unique_id)


@router.callback_query(SellerPanelCB.filter(F.action == "submit_no_receipt"))
async def submit_without_photo(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot,
) -> None:
    if await state.get_state() != SellerPaymentStates.waiting_receipt.state:
        await alert(callback, "⚠️ Avval katalogdan tarifni tanlang.", show=True)
        return
    await _submit(callback, session, state, bot, file_id=None, file_unique_id=None)


@router.callback_query(SellerPanelCB.filter(F.action == "cancel_pay"))
async def cancel_payment(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await render(callback, "❌ To'lov jarayoni bekor qilindi. Pul o'tkazgan bo'lsangiz admin bilan bog'laning.", back_to_menu_kb())
    await alert(callback, "")


@router.message(StateFilter(SellerPaymentStates.waiting_receipt), F.text)
async def receipt_text(message: Message, state: FSMContext) -> None:
    if (message.text or "").strip().lower() in {"/cancel", "/start"}:
        await state.clear()
        await message.answer("❌ To'lov jarayoni bekor qilindi.", reply_markup=back_to_menu_kb())
        return
    await message.answer("🧾 Chekni rasm ko'rinishida yuboring. Bekor qilish: /cancel")


@router.message(StateFilter(SellerPaymentStates.waiting_receipt))
async def receipt_other(message: Message) -> None:
    await message.answer("⚠️ Iltimos, chekni foto sifatida yuboring (hujjat emas). Bekor: /cancel")


@router.callback_query(SellerPanelCB.filter(F.action == "payments"))
async def history(callback: CallbackQuery, callback_data: SellerPanelCB, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    seller = await _owner(session, callback.from_user.id)
    total = await payment_service.count_payments(session, seller_id=seller.id)
    pages = max(1, ceil(total / payment_service.PAYMENT_PAGE))
    try:
        page = max(0, min(int(callback_data.value), pages - 1))
    except ValueError:
        page = 0
    payments = await payment_service.list_payments(
        session, seller_id=seller.id, offset=page * payment_service.PAYMENT_PAGE
    )
    text = f"🧾 <b>To'lovlarim</b>\nJami: {total} · sahifa {page + 1}/{pages}\n"
    if not payments:
        text += "\nHozircha chek yuborilmagan. Tariflarni ko'rib chiqishingiz mumkin."
    await render(callback, text, seller_history_kb(payments, page=page, pages=pages))
    await alert(callback, "")


@router.callback_query(SellerPanelCB.filter(F.action == "payment_detail"))
async def history_detail(callback: CallbackQuery, callback_data: SellerPanelCB, session: AsyncSession) -> None:
    seller = await _owner(session, callback.from_user.id)
    try:
        payment_id = int(callback_data.value)
    except ValueError:
        await alert(callback, "⚠️ Chek topilmadi.", show=True)
        return
    payment: Payment | None = await payment_service.get_payment(session, payment_id)
    if payment is None or payment.seller_id != seller.id:
        await alert(callback, "⚠️ Chek topilmadi.", show=True)
        return
    label = {
        PaymentStatus.PENDING: "🕓 Tekshiruvda", PaymentStatus.APPROVED: "✅ Tasdiqlandi",
        PaymentStatus.REJECTED: "❌ Rad etildi", PaymentStatus.CANCELLED: "⏸ Bekor qilindi",
    }.get(payment.status, payment.status)
    text = (
        f"🧾 <b>Chek #{payment.id}</b>\n"
        f"💳 Tarif: {escape_html(payment.tariff.name if payment.tariff else '—')}\n"
        f"💰 Summa: {fmt_amount(payment.amount, payment.currency)}\n"
        f"📌 Holat: <b>{label}</b>\n"
        f"📅 Yuborildi: {fmt_dt(payment.created_at)}"
    )
    if payment.reason:
        text += f"\n❌ Sabab: {escape_html(payment.reason)}"
    if payment.is_duplicate_receipt:
        text += "\n🔴 Bu chek oldin yuborilgan — yangi chek kerak bo'lishi mumkin."
    if payment.status == PaymentStatus.PENDING:
        text += "\n\nAdmin javobini kuting. Tasdiq/rad natijasi shu chatga keladi."
    await render(callback, text, seller_history_detail_kb())
    await alert(callback, "")
