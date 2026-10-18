"""Phase 5: bank rekvizitlari, chek tarixi va faqat admin tasdiqlaydigan to'lov.

Pul bot orqali o'tmaydi. Chek — dalil, avtomatik obuna EMAS. Qaror va obuna
bitta DB tranzaksiyasida, avval sotuvchi qatori bloklanib qabul qilinadi.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import PaymentStatus, SellerStatus
from app.db.models import ActionLog, Payment, PaymentMethod, ReferralBonusLog, Seller, Subscription, Tariff
from app.services import subscription_service, tariff_service
from app.services.settings_service import settings_service
from app.utils.text import clean_text
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.services.referral_service import Quote

METHOD_PAGE = 8
PAYMENT_PAGE = 8
CARD_RE = re.compile(r"[0-9]{16,19}\Z")
CURRENCY_RE = re.compile(r"[A-Z]{3}\Z")


@dataclass(frozen=True)
class Decision:
    status: str  # approved | rejected | already | duplicate | blocked | missing | invalid
    payment: Payment | None = None
    subscription: Subscription | None = None


def normalize_card(value: str) -> str | None:
    """Bank kartasidagi bo'shliq/tirelarni olib tashlash (asl raqam hech qachon logga chiqmaydi)."""
    digits = re.sub(r"[\s-]", "", value.strip())
    return digits if CARD_RE.fullmatch(digits) else None


def mask_card(number: str) -> str:
    return f"•••• {number[-4:]}" if number else "••••"


def display_card(number: str) -> str:
    return " ".join(number[i:i + 4] for i in range(0, len(number), 4))


async def get_method(session: AsyncSession, method_id: int) -> PaymentMethod | None:
    return await session.get(PaymentMethod, method_id)


async def list_methods(
    session: AsyncSession, *, active_only: bool = False, offset: int = 0, limit: int = METHOD_PAGE,
) -> list[PaymentMethod]:
    stmt = select(PaymentMethod).order_by(PaymentMethod.position, PaymentMethod.id)
    if active_only:
        stmt = stmt.where(PaymentMethod.is_active.is_(True))
    return list((await session.execute(stmt.offset(offset).limit(limit))).scalars())


async def count_methods(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(PaymentMethod))).scalar_one())


def _currency(value: str) -> str:
    currency = (value or "").strip().upper()
    if not CURRENCY_RE.fullmatch(currency):
        raise ValueError("Valyuta uch harfli kod bo'lishi kerak (masalan UZS).")
    return currency


async def create_method(
    session: AsyncSession, *, name: str, card_number: str, holder: str | None = None,
    bank: str | None = None, note: str | None = None, currency: str = "UZS",
) -> PaymentMethod:
    title = clean_text(name, limit=64)
    card = normalize_card(card_number)
    if not title or len(title) < 2:
        raise ValueError("Rekvizit nomi kamida 2 ta belgi bo'lishi kerak.")
    if card is None:
        raise ValueError("Karta raqami 16–19 ta raqamdan iborat bo'lishi kerak.")
    max_pos = (await session.execute(select(func.coalesce(func.max(PaymentMethod.position), 0)))).scalar_one()
    method = PaymentMethod(
        name=title, card_number=card, holder=clean_text(holder, limit=128),
        bank=clean_text(bank, limit=128), note=clean_text(note, limit=500),
        currency=_currency(currency), position=int(max_pos) + 1000, is_active=True,
    )
    session.add(method)
    await session.flush()
    return method


async def update_method(session: AsyncSession, method: PaymentMethod, field: str, value: str) -> None:
    """Faqat panelga ruxsat etilgan maydonlar. Bo'sh ixtiyoriy maydon → None."""
    if field == "card_number":
        card = normalize_card(value)
        if card is None:
            raise ValueError("Karta raqami 16–19 ta raqamdan iborat bo'lishi kerak.")
        method.card_number = card
    elif field == "currency":
        method.currency = _currency(value)
    elif field == "name":
        title = clean_text(value, limit=64)
        if not title or len(title) < 2:
            raise ValueError("Rekvizit nomi kamida 2 ta belgi bo'lishi kerak.")
        method.name = title
    elif field in {"holder", "bank", "note"}:
        limit = 500 if field == "note" else 128
        setattr(method, field, clean_text(None if value.strip() == "-" else value, limit=limit))
    else:
        raise ValueError("Bunday maydon yo'q.")
    await session.flush()


async def move_method(session: AsyncSession, method: PaymentMethod, direction: str) -> bool:
    if direction not in ("up", "down"):
        return False
    methods = await list_methods(session, limit=10_000)
    index = next((i for i, row in enumerate(methods) if row.id == method.id), None)
    if index is None:
        return False
    other_index = index - 1 if direction == "up" else index + 1
    if not 0 <= other_index < len(methods):
        return False
    other = methods[other_index]
    if other.position == method.position:
        for order, row in enumerate(methods, start=1):
            row.position = order * 1000
        await session.flush()
    method.position, other.position = other.position, method.position
    await session.flush()
    return True


async def choose_method(session: AsyncSession, currency: str) -> PaymentMethod | None:
    """Oxirgi QABUL QILINGAN chek kartasidan keyingi faol kartani tanlash.

    To'lov boshlanib, chek yuborilmagan tanlovlar siklni siljitmaydi.
    """
    methods = list((await session.execute(
        select(PaymentMethod).where(
            PaymentMethod.is_active.is_(True), PaymentMethod.currency == currency
        ).order_by(PaymentMethod.position, PaymentMethod.id)
    )).scalars())
    if not methods:
        return None
    ids = [row.id for row in methods]
    previous = (await session.execute(
        select(Payment.method_id).where(Payment.method_id.in_(ids))
        .order_by(Payment.id.desc()).limit(1)
    )).scalar_one_or_none()
    if previous in ids:
        return methods[(ids.index(previous) + 1) % len(methods)]
    return methods[0]


async def submit_receipt(
    session: AsyncSession, *, seller: Seller, tariff: Tariff, method: PaymentMethod | None,
    file_id: str | None, file_unique_id: str | None,
    quoted_amount: Decimal | None = None, quoted_currency: str | None = None,
    quote: Quote | None = None,
) -> Payment:
    """Chekni yozishdan oldin Seller qatori ostida bonus/kuponni BIR MARTA band qilish.

    Bonusli 0 so'mlik chek ham faqat admin tomonidan tasdiqlanadi; avto grant yo'q.
    Rad etilsa rezerv qilingan balans va kupon qaytariladi. Eski Phase 5
    chaqiruvlari uchun quote=None bo'lsa o'sha to'lov oqimi saqlanadi.
    """
    if seller.status in (SellerStatus.BLOCKED, SellerStatus.DELETED):
        raise ValueError("Sotuvchi bloklangan yoki o'chirilgan.")
    if not tariff.is_active:
        raise ValueError("Bu tarifni hozir sotib olib bo'lmaydi.")
    amount = Decimal(str(quoted_amount)) if quoted_amount is not None else tariff.price
    currency = _currency(quoted_currency) if quoted_currency is not None else tariff.currency
    if (not amount.is_finite() or amount < 0 or amount > tariff_service.MAX_PRICE
            or (amount == 0 and (quote is None or quote.discount + quote.balance <= 0))):
        raise ValueError("Bu tarifni hozir sotib olib bo'lmaydi.")
    if currency != tariff.currency:
        raise ValueError("Tarif valyutasi o'zgargan. Katalogdan qayta boshlang.")
    if amount > 0 and (method is None or method.currency != currency):
        raise ValueError("Tarif va karta valyutasi mos emas.")
    if amount > 0 and not file_id and await settings_service.get("receipt_required", True, session):
        raise ValueError("Chek rasmini yuborish majburiy.")
    if bool(file_id) != bool(file_unique_id) or (file_id and len(file_id) > 255):
        raise ValueError("Chek rasmi haqiqiy Telegram rasmi bo'lishi kerak.")

    voucher = None
    if quote is not None:
        from app.services.referral_service import verify_quote

        # Ikkita parallel chek bitta balans/kuponni ishlatmasligi uchun.
        seller = (await session.execute(select(Seller).where(Seller.id == seller.id)
                                        .with_for_update().execution_options(populate_existing=True))).scalar_one()
        voucher = await verify_quote(session, seller, tariff, quote)
        if quote.bank != amount:
            raise ValueError("Summa mos emas. Katalogdan qayta boshlang.")
    digest = None
    if file_unique_id and await settings_service.get("receipt_duplicate_check", True, session):
        digest = hashlib.sha256(file_unique_id.encode("utf-8")).hexdigest()
    values = dict(
        seller_id=seller.id, tariff_id=tariff.id, amount=amount,
        terms=subscription_service.tariff_terms(tariff),
        base_amount=quote.base if quote else amount,
        discount_amount=quote.discount if quote else Decimal("0"),
        balance_used=quote.balance if quote else Decimal("0"),
        discount_bonus_id=quote.discount_bonus_id if quote else None,
        currency=currency, method_id=method.id if method else None,
        receipt_file_id=file_id, status=PaymentStatus.PENDING,
    )
    existing = (await session.execute(
        select(Payment.id).where(Payment.receipt_unique_hash == digest).limit(1)
    )).scalar_one_or_none() if digest else None
    if digest and existing is None:
        try:
            async with session.begin_nested():
                payment = Payment(**values, receipt_unique_hash=digest, is_duplicate_receipt=False)
                session.add(payment)
                await session.flush()
        except IntegrityError:
            # Boshqa worker birinchi xesh'ni oldin yozgan.
            existing = -1
    if not digest or existing is not None:
        payment = Payment(**values, receipt_unique_hash=None, is_duplicate_receipt=bool(digest))
        session.add(payment)
        await session.flush()
    if quote is not None:
        if quote.balance:
            seller.balance -= quote.balance
        if voucher:
            voucher.reserved_payment_id = payment.id
        await session.flush()
    return payment


async def get_payment(session: AsyncSession, payment_id: int) -> Payment | None:
    return await session.get(Payment, payment_id)


async def list_payments(
    session: AsyncSession, *, status: str = "all", seller_id: int | None = None,
    offset: int = 0, limit: int = PAYMENT_PAGE,
) -> list[Payment]:
    stmt = select(Payment)
    if status != "all":
        stmt = stmt.where(Payment.status == status)
    if seller_id is not None:
        stmt = stmt.where(Payment.seller_id == seller_id)
    return list((await session.execute(
        stmt.order_by(Payment.created_at.desc(), Payment.id.desc()).offset(offset).limit(limit)
    )).scalars())


async def count_payments(
    session: AsyncSession, *, status: str = "all", seller_id: int | None = None,
) -> int:
    stmt = select(func.count()).select_from(Payment)
    if status != "all":
        stmt = stmt.where(Payment.status == status)
    if seller_id is not None:
        stmt = stmt.where(Payment.seller_id == seller_id)
    return int((await session.execute(stmt)).scalar_one())


async def decide(
    session: AsyncSession, payment_id: int, *, admin_id: int,
    approve: bool, reason: str | None = None,
) -> Decision:
    """Bir sotuvchining bir nechta chekini ham ketma-ket, xavfsiz qaror qilamiz.

    Lock tartibi: Seller → Payment. Shu bois ikki admin bir xil chekni bosganda
    faqat bir marta, ikki alohida chekni bosganda obuna ketma-ket uzayadi.
    """
    seller_id = (await session.execute(
        select(Payment.seller_id).where(Payment.id == payment_id)
    )).scalar_one_or_none()
    if seller_id is None:
        return Decision("missing")
    seller = (await session.execute(
        select(Seller).where(Seller.id == seller_id).with_for_update()
    )).scalar_one_or_none()
    payment = (await session.execute(
        select(Payment).where(Payment.id == payment_id).with_for_update()
    )).scalar_one_or_none()
    if payment is None:
        return Decision("missing")
    if payment.status != PaymentStatus.PENDING:
        return Decision("already", payment)

    subscription = None
    if approve:
        if payment.is_duplicate_receipt:
            return Decision("duplicate", payment)
        if seller is None or seller.status in (SellerStatus.BLOCKED, SellerStatus.DELETED):
            return Decision("blocked", payment)
        tariff = await session.get(Tariff, payment.tariff_id)
        if tariff is None:
            return Decision("missing", payment)
        coupon = await session.get(ReferralBonusLog, payment.discount_bonus_id) if payment.discount_bonus_id else None
        if payment.discount_bonus_id and (coupon is None or coupon.reserved_payment_id != payment.id
                                          or coupon.redeemed_at is not None):
            return Decision("invalid", payment)  # noaniq chegirma bilan tarif berilmaydi
        subscription = await subscription_service.grant(
            session, seller, tariff, granted_by=admin_id, payment_id=payment.id,
            terms_override=payment.terms,
        )
        payment.subscription_id = subscription.id
        payment.status = PaymentStatus.APPROVED
        if coupon:
            coupon.redeemed_at = utcnow()
        from app.services.referral_service import first_payment

        await first_payment(session, payment, seller)
    else:
        explanation = clean_text(reason, limit=300)
        if not explanation or len(explanation) < 3:
            return Decision("invalid", payment)
        payment.reason = explanation
        payment.status = PaymentStatus.REJECTED
        if payment.balance_used and seller:
            seller.balance += payment.balance_used
        if payment.discount_bonus_id:
            coupon = await session.get(ReferralBonusLog, payment.discount_bonus_id)
            if coupon and coupon.reserved_payment_id == payment.id:
                coupon.reserved_payment_id = None

    payment.admin_id = admin_id
    payment.decided_at = utcnow()
    session.add(ActionLog(
        actor_id=admin_id, action="payment_approve" if approve else "payment_reject",
        entity="payment", entity_id=payment.id,
        before={"status": PaymentStatus.PENDING},
        after={"status": payment.status, "subscription_id": payment.subscription_id},
    ))
    await session.flush()
    return Decision(payment.status, payment, subscription)
