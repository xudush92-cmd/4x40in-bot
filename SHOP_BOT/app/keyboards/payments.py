"""Phase 5: admin chek/karta paneli va sotuvchining to'lov tugmalari."""

from __future__ import annotations

from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import PaymentStatus
from app.db.models import Payment, PaymentMethod
from app.keyboards.callbacks import AdminCB, PaymentCB, SellerPanelCB
from app.keyboards.common import nav_row
from app.services.payment_service import mask_card
from app.utils.text import truncate

REASONS: tuple[tuple[str, str], ...] = (
    ("sum", "💰 Summa mos emas"),
    ("proof", "🧾 Chek aniq ko'rinmaydi"),
    ("duplicate", "🔴 Chek oldin ishlatilgan"),
    ("transfer", "🏦 To'lov topilmadi"),
)


def _button(text: str, action: str, target_id: int = 0, value: str = "0") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=PaymentCB(
        action=action, target_id=target_id, value=value,
    ).pack())


def payment_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button("📥 Kelgan cheklar", "list", value="0|pending")],
        [_button("🕘 To'lovlar tarixi", "list", value="0|all")],
        [_button("💳 Rekvizitlar (kartalar)", "methods")],
        [InlineKeyboardButton(text="◀️ Boshqaruv paneli", callback_data=AdminCB(action="menu").pack())],
    ])


def payment_list_kb(payments: list[Payment], *, page: int, pages: int, status: str) -> InlineKeyboardMarkup:
    rows = [
        [_button(
            f"{'🔴' if payment.is_duplicate_receipt else '🕓' if payment.status == PaymentStatus.PENDING else '✅' if payment.status == PaymentStatus.APPROVED else '❌'} "
            f"#{payment.id} {truncate(payment.seller.display_name if payment.seller else '—', 24)}",
            "card", payment.id, f"{page}|{status}",
        )]
        for payment in payments
    ]
    rows.append([
        _button(f"{'• ' if status == key else ''}{label}", "list", value=f"0|{key}")
        for key, label in (("pending", "📥"), ("approved", "✅"), ("rejected", "❌"), ("all", "Hammasi"))
    ])
    rows.append(nav_row(
        prev_data=PaymentCB(action="list", value=f"{page - 1}|{status}").pack() if page else None,
        next_data=PaymentCB(action="list", value=f"{page + 1}|{status}").pack() if page + 1 < pages else None,
        page=page, total_pages=pages,
        refresh_data=PaymentCB(action="list", value=f"{page}|{status}").pack(),
    ))
    rows.append([_button("◀️ To'lovlar", "home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_card_kb(payment: Payment, *, page: int = 0, status: str = "pending") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if payment.status == PaymentStatus.PENDING:
        if not payment.is_duplicate_receipt:
            rows.append([_button("✅ Tasdiqlash", "approve", payment.id, f"{page}|{status}")])
        rows.append([_button("❌ Sabab bilan rad etish", "reject", payment.id, f"{page}|{status}")])
    rows.append([_button("◀️ Cheklar ro'yxati", "list", value=f"{page}|{status}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reject_reasons_kb(payment_id: int, *, page: int = 0, status: str = "pending") -> InlineKeyboardMarkup:
    rows = [[_button(label, "reason", payment_id, key)] for key, label in REASONS]
    rows += [
        [_button("✏️ Boshqa sabab yozaman", "reason", payment_id, "custom")],
        [_button("◀️ Bekor", "card", payment_id, f"{page}|{status}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def methods_list_kb(methods: list[PaymentMethod], *, page: int, pages: int) -> InlineKeyboardMarkup:
    rows = [[_button(
        f"{'🟢' if row.is_active else '⏸'} {truncate(row.name, 24)} · {mask_card(row.card_number)}",
        "method_card", row.id, str(page),
    )] for row in methods]
    rows.append(nav_row(
        prev_data=PaymentCB(action="methods", value=str(page - 1)).pack() if page else None,
        next_data=PaymentCB(action="methods", value=str(page + 1)).pack() if page + 1 < pages else None,
        page=page, total_pages=pages,
        refresh_data=PaymentCB(action="methods", value=str(page)).pack(),
    ))
    rows += [[_button("➕ Yangi karta", "method_new")], [_button("◀️ To'lovlar", "home")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def method_card_kb(method: PaymentMethod, *, page: int = 0) -> InlineKeyboardMarkup:
    rows = [
        [_button("⏸ To'xtatish" if method.is_active else "▶️ Faollashtirish", "method_toggle", method.id, str(page))],
        [_button("⬆️", "method_up", method.id, str(page)), _button("⬇️", "method_down", method.id, str(page))],
        [_button("✏️ Nom", "method_edit", method.id, "name"), _button("💳 Raqam", "method_edit", method.id, "card_number")],
        [_button("👤 Egasi", "method_edit", method.id, "holder"), _button("🏦 Bank", "method_edit", method.id, "bank")],
        [_button("💱 Valyuta", "method_edit", method.id, "currency"), _button("📝 Izoh", "method_edit", method.id, "note")],
        [_button("🗑 O'chirish", "method_delete", method.id, str(page))],
        [_button("◀️ Kartalar", "methods", value=str(page))],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def method_delete_kb(method_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button("🗑 Ha, to'xtatish", "method_delete_confirm", method_id, str(page))],
        [_button("❌ Bekor", "method_card", method_id, str(page))],
    ])


def method_cancel_kb(method_id: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button("❌ Bekor qilish", "method_card" if method_id else "methods", method_id)],
    ])


def seller_pay_kb(card_number: str, *, receipt_required: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📋 Karta raqamini nusxalash", copy_text=CopyTextButton(text=card_number))],
    ]
    if not receipt_required:
        rows.append([InlineKeyboardButton(
            text="✅ Cheksiz yuborish (admin tekshiradi)",
            callback_data=SellerPanelCB(action="submit_no_receipt").pack(),
        )])
    rows.append([InlineKeyboardButton(
        text="❌ Bekor qilish", callback_data=SellerPanelCB(action="cancel_pay").pack(),
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def seller_history_kb(payments: list[Payment], *, page: int, pages: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text=f"{'🕓' if item.status == PaymentStatus.PENDING else '✅' if item.status == PaymentStatus.APPROVED else '❌'} #{item.id} · {truncate(item.tariff.name if item.tariff else '—', 24)}",
        callback_data=SellerPanelCB(action="payment_detail", value=str(item.id)).pack(),
    )] for item in payments]
    rows.append(nav_row(
        prev_data=SellerPanelCB(action="payments", value=str(page - 1)).pack() if page else None,
        next_data=SellerPanelCB(action="payments", value=str(page + 1)).pack() if page + 1 < pages else None,
        page=page, total_pages=pages,
        refresh_data=SellerPanelCB(action="payments", value=str(page)).pack(),
    ))
    rows.append([InlineKeyboardButton(
        text="◀️ Sotuvchi paneli", callback_data=SellerPanelCB(action="menu").pack(),
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def seller_history_detail_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ To'lovlarim", callback_data=SellerPanelCB(action="payments").pack())],
    ])
