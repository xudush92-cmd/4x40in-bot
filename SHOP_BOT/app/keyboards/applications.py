"""UX-2 sotuvchilik arizasi tugmalari (user va admin)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import ApplicationStatus
from app.db.models import SellerApplication
from app.keyboards.callbacks import AdminCB, ApplicationCB, GuideCB
from app.utils.text import truncate


def _button(text: str, action: str, application_id: int = 0, page: int = 0) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=ApplicationCB(
        action=action, application_id=application_id, page=page,
    ).pack())


def wizard_kb(*, preview: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if preview:
        rows += [[_button("✅ Ariza yuborish", "submit")], [_button("✏️ Tahrirlash", "edit")]]
    rows.append([_button("❌ Bekor qilish", "cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def status_kb(application: SellerApplication, *, can_retry: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if application.status == ApplicationStatus.REJECTED and can_retry:
        rows.append([_button("🛒 Qayta ariza", "new")])
    rows.append([_button("🔄 Holatni yangilash", "status")])
    rows.append([InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data=GuideCB(page="back").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pending_kb(applications: list[SellerApplication], page: int, pages: int) -> InlineKeyboardMarkup:
    rows = [[_button(f"#{item.id} · {truncate(item.display_name, 28)}", "card", item.id, page)]
            for item in applications]
    nav = []
    if page > 0:
        nav.append(_button("◀️", "list", page=page - 1))
    if page + 1 < pages:
        nav.append(_button("▶️", "list", page=page + 1))
    if nav:
        rows.append(nav)
    rows.extend([
        [_button("🔄 Yangilash", "list", page=page)],
        [InlineKeyboardButton(text="◀️ Savdo", callback_data=AdminCB(action="hub", value="sales").pack())],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def card_kb(application: SellerApplication, page: int = 0) -> InlineKeyboardMarkup:
    rows = []
    if application.status == ApplicationStatus.PENDING:
        rows += [[_button("✅ Tasdiqlash", "approve", application.id, page),
                  _button("❌ Rad etish", "reject", application.id, page)]]
    rows += [[_button("◀️ Navbat", "list", page=page)]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_kb(application_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button("✅ Ha, faqat panelni ochish", "approve_confirm", application_id, page)],
        [_button("◀️ Arizaga qaytish", "card", application_id, page)],
    ])


def custom_reason_kb(application_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button("◀️ Arizaga qaytish", "card", application_id, page)],
    ])


REASONS = {
    "contact": "Aloqa ma'lumotini tuzating va qayta yuboring.",
    "name": "Ism/do'kon nomini aniqlashtiring va qayta yuboring.",
    "rules": "Ariza talablarga mos emas; qo'shimcha ma'lumot uchun adminga yozing.",
}


def reject_kb(application_id: int, page: int) -> InlineKeyboardMarkup:
    rows = [[_button(text, "reason_" + code, application_id, page)]
            for code, text in REASONS.items()]
    rows += [[_button("✏️ Boshqa sababni yozish", "custom", application_id, page)],
             [_button("◀️ Arizaga qaytish", "card", application_id, page)]]
    return InlineKeyboardMarkup(inline_keyboard=rows)
