"""Phase 8: /start ref_<kod> va faqat tasdiqlangan birinchi to'lov referali.

Sanoqchidan mutlaqo alohida: bu yerda guruh taklifi hisoblanmaydi.
Bonussiz yoki daromadga ta'sir qiladigan holat avval o'chirilgan (`referral_enabled=false`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import BonusType, PaymentStatus, ReferralTrigger, SellerStatus
from app.db.models import (
    ActionLog,
    Payment,
    Referral,
    ReferralBonusLog,
    ReferralSetting,
    Seller,
    Tariff,
)
from app.services import seller_service, subscription_service, tariff_service
from app.services.settings_service import settings_service
from app.utils.time import ensure_aware, utcnow

BONUS_DEFAULT = {BonusType.DAYS: "7", BonusType.BALANCE: "50000", BonusType.DISCOUNT: "10"}
MAX_BONUS_DAYS = Decimal("3650")
MAX_BONUS_BALANCE = Decimal("10000000")
MAX_DISCOUNT_PERCENT = Decimal("50")  # 500% manfiy chek chiqaradi — oshirilmaydi
# Minimal chek hech qachon sotib olinadigan maksimal tarifdan oshmasin.
MAX_MIN_PAYMENT = tariff_service.MAX_PRICE
DEFAULTS = {
    "trigger": ReferralTrigger.FIRST_PAYMENT,
    "bonus_type": BonusType.DAYS,
    "bonus_value": "7",
    "min_payment": "50000",
}


def _decimal(value: object) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Musbat qiymat kiriting.") from exc
    if not number.is_finite():
        raise ValueError("Musbat qiymat kiriting.")
    return number


def validate(key: str, value: object, *, bonus_type: str = BonusType.DAYS) -> str | int:
    if key == "trigger":
        if value not in (ReferralTrigger.SIGNUP, ReferralTrigger.FIRST_PAYMENT):
            raise ValueError("Shart: signup yoki first_payment.")
        return str(value)
    if key == "bonus_type":
        if value not in (BonusType.DAYS, BonusType.BALANCE, BonusType.DISCOUNT):
            raise ValueError("Bonus turi noto'g'ri.")
        return str(value)
    if key in {"bonus_value", "min_payment"}:
        number = _decimal(value)
        if key == "min_payment":
            if 0 <= number <= MAX_MIN_PAYMENT and number == number.quantize(Decimal("0.01")):
                return str(number)
            raise ValueError(f"Minimal chek 0–{MAX_MIN_PAYMENT:.0f} UZS orasida bo'lsin.")
        ranges = {BonusType.DAYS: (Decimal("1"), MAX_BONUS_DAYS),
                  BonusType.BALANCE: (Decimal("1000"), MAX_BONUS_BALANCE),
                  BonusType.DISCOUNT: (Decimal("1"), MAX_DISCOUNT_PERCENT)}
        low, high = ranges.get(bonus_type, (Decimal("1"), Decimal("365")))
        if (key == "bonus_value" and low <= number <= high and number == number.quantize(Decimal("0.01"))
                and (bonus_type != BonusType.DAYS or number == number.to_integral_value())):
            return str(number)
        raise ValueError(f"Qiymat {low}–{high} orasida bo'lsin.")
    raise ValueError("Bunday referal sozlamasi yo'q.")


async def config(session: AsyncSession) -> dict[str, str | int]:
    values: dict[str, str | int] = dict(DEFAULTS)
    rows = (await session.execute(select(ReferralSetting))).scalars().all()
    for row in rows:
        if row.key in values:
            values[row.key] = row.value
    return values


async def set_config(session: AsyncSession, key: str, value: object, actor_id: int) -> None:
    values = await config(session)
    cleaned = validate(key, value, bonus_type=str(values["bonus_type"]))
    row = await session.get(ReferralSetting, key)
    before = row.value if row else DEFAULTS[key]
    if row is None:
        session.add(ReferralSetting(key=key, value=cleaned, updated_by=actor_id))
    else:
        row.value, row.updated_by = cleaned, actor_id
    if before != cleaned:
        session.add(ActionLog(actor_id=actor_id, action="referral_setting", entity="referral_setting",
                              before={key: before}, after={key: cleaned}))
    if key == "bonus_type" and before != cleaned:
        # Turi almashsa eski qiymat boshqa birlikda tasodifan qo'llanmasin.
        value_row = await session.get(ReferralSetting, "bonus_value")
        if value_row is None:
            session.add(ReferralSetting(key="bonus_value", value=BONUS_DEFAULT[cleaned], updated_by=actor_id))
        else:
            value_row.value, value_row.updated_by = BONUS_DEFAULT[cleaned], actor_id
        session.add(ActionLog(actor_id=actor_id, action="referral_setting", entity="referral_setting",
                              before={"bonus_value": values["bonus_value"]},
                              after={"bonus_value": BONUS_DEFAULT[cleaned]}))
    await session.flush()


async def referral_active(session: AsyncSession) -> bool:
    values = await settings_service.get_all(session)
    return bool(values.get("referral_enabled")) and not (
        values.get("kill_switch") or values.get("maintenance_mode")
    )


async def register(session: AsyncSession, *, code: str, referee_id: int,
                   user_is_new: bool) -> Referral | None:
    """Yangi /start (oldin botni ishlatmagan) uchun dublikatdan himoyalangan yozuv."""
    if (not user_is_new or referee_id <= 0 or len(code) != seller_service.CODE_LENGTH
            or any(c not in seller_service.CODE_ALPHABET for c in code.upper())
            or not await referral_active(session)):
        return None
    referrer = await seller_service.get_seller_by_referral_code(session, code)
    if (referrer is None or referrer.user_id == referee_id or
            referrer.status in (SellerStatus.BLOCKED, SellerStatus.DELETED)):
        return None
    # Anti-fraud dublikat tekshiruvi bir nechta workerda ham izchil qolsin.
    referrer = (await session.execute(select(Seller).where(
        Seller.id == referrer.id,
    ).with_for_update())).scalar_one()
    if await session.scalar(select(Referral.id).where(Referral.referee_id == referee_id)) is not None:
        return None
    conf = await config(session)
    try:
        async with session.begin_nested():
            row = Referral(referrer_id=referrer.user_id, referee_id=referee_id,
                           code=code.upper(), trigger=str(conf["trigger"]), status="pending",
                           bonus_type=str(conf["bonus_type"]), bonus_value=_decimal(conf["bonus_value"]))
            session.add(row)
            await session.flush()
    except IntegrityError:
        return None  # UNIQUE(referee_id) — boshqa worker birinchi yozgan
    referee = await seller_service.get_seller(session, referee_id)
    if referee is not None and referee.referred_by is None:
        referee.referred_by = referrer.user_id
    if row.trigger == ReferralTrigger.SIGNUP:
        row.trigger_at = utcnow()
        await session.flush()
        await apply_ready(session, row)
    return row


async def apply_ready(session: AsyncSession, row: Referral) -> bool:
    """Bitta referrerdagi obuna/balansni bloklab, bonusni faqat BIR MARTA yozish."""
    if row.status != "pending" or row.trigger_at is None:
        return False
    locked = (await session.execute(select(Referral).where(Referral.id == row.id)
                                    .with_for_update().execution_options(populate_existing=True))).scalar_one()
    if locked.status != "pending":
        return False
    seller = (await session.execute(select(Seller).where(Seller.user_id == locked.referrer_id)
                                    .with_for_update())).scalar_one_or_none()
    if seller is None or seller.status in (SellerStatus.DELETED, SellerStatus.BLOCKED):
        return False
    value = _decimal(locked.bonus_value)
    if locked.bonus_type == BonusType.DAYS:
        sub = await subscription_service.active_for(session, seller.id)
        if sub is None:
            return False  # faol tarif paydo bo'lganda job qayta ko'radi
        sub.expires_at = max(ensure_aware(sub.expires_at), utcnow()) + timedelta(days=int(value))
        sub.reminder_sent_at = None
    elif locked.bonus_type == BonusType.BALANCE:
        if seller.balance + value > Decimal("9999999999.99"):
            return False
        seller.balance += value  # balans UZS; xarajat faqat tasdiqlangan chekda
    elif locked.bonus_type != BonusType.DISCOUNT:
        return False
    # Discount: bir martalik kupon; to'lov chekida foydalaniladi (alohida).
    session.add(ReferralBonusLog(referral_id=locked.id, seller_id=seller.id,
                                 bonus_type=locked.bonus_type, value=value, applied_at=utcnow()))
    locked.status, locked.applied_at = "applied", utcnow()
    session.add(ActionLog(actor_id=locked.referrer_id, action="referral_bonus", entity="referral",
                          entity_id=locked.id, after={"type": locked.bonus_type, "value": str(value)}))
    await session.flush()
    return True


async def first_payment(session: AsyncSession, payment: Payment, referee_seller: Seller) -> bool:
    """Faqat admin tasdiqlagan BIRINCHI chek; boshqa valyutani UZSga qo'shmaymiz."""
    if payment.status != PaymentStatus.APPROVED or not await referral_active(session):
        return False
    row = (await session.execute(select(Referral).where(
        Referral.referee_id == referee_seller.user_id,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None or row.status != "pending" or row.trigger != ReferralTrigger.FIRST_PAYMENT:
        return False
    # Session autoflush=False: shu tranzaksiyadagi tasdiqni ham so'rov ko'rsin.
    await session.flush()
    first_id = (await session.execute(select(Payment.id).where(
        Payment.seller_id == referee_seller.id, Payment.status == PaymentStatus.APPROVED,
    ).order_by(Payment.id).limit(1))).scalar_one_or_none()
    if first_id != payment.id:
        return False
    conf = await config(session)
    if payment.currency != "UZS" or payment.amount < _decimal(conf["min_payment"]):
        row.status, row.trigger_at = "rejected", utcnow()
        await session.flush()
        return False
    row.first_payment_id, row.trigger_at = payment.id, utcnow()
    await session.flush()  # apply_ready(populate_existing) trigger vaqtini o'chirmasin
    return await apply_ready(session, row)


async def process_pending(session: AsyncSession, limit: int = 100) -> int:
    """Shart bajarilgan, ammo referrerda hali faol tarif bo'lmagan bonuslar."""
    if not await referral_active(session):
        return 0
    ids = (await session.execute(select(Referral.id).where(
        Referral.status == "pending", Referral.trigger_at.is_not(None),
    ).order_by(Referral.id).limit(limit))).scalars().all()
    credited = 0
    for ref_id in ids:
        row = await session.get(Referral, ref_id)
        if row is not None and await apply_ready(session, row):
            credited += 1
    return credited


@dataclass(frozen=True)
class Quote:
    base: Decimal
    discount: Decimal
    balance: Decimal
    bank: Decimal
    discount_bonus_id: int | None


def discounted(base: Decimal, percent: Decimal) -> Decimal:
    return (base * percent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def quote_for(session: AsyncSession, seller: Seller, tariff: Tariff) -> Quote:
    """Checkout'dan avval ko'rsatiladigan narx; mablag' faqat chek yuborilganda band qilinadi."""
    voucher = (await session.execute(select(ReferralBonusLog).where(
        ReferralBonusLog.seller_id == seller.id,
        ReferralBonusLog.bonus_type == BonusType.DISCOUNT,
        ReferralBonusLog.reserved_payment_id.is_(None),
        ReferralBonusLog.redeemed_at.is_(None),
    ).order_by(ReferralBonusLog.id).limit(1))).scalar_one_or_none()
    base = tariff.price
    discount = discounted(base, voucher.value) if voucher else Decimal("0")
    balance = min(seller.balance, base - discount) if tariff.currency == "UZS" else Decimal("0")
    return Quote(base=base, discount=discount, balance=balance,
                 bank=base - discount - balance, discount_bonus_id=voucher.id if voucher else None)


async def verify_quote(session: AsyncSession, seller: Seller, tariff: Tariff, quote: Quote) -> ReferralBonusLog | None:
    """Chek paytida row-lock ostida quote'ni tasdiqlash: bir kupon/balans ikki marta emas."""
    # Phase 5 narx snapshotini saqlaymiz: katalogdan keyin tarif narxi
    # o'zgarsa ham foydalanuvchi ko'rgan summa (FSM'dagi quote) amal qiladi.
    if not 0 < quote.base <= tariff_service.MAX_PRICE or quote.discount < 0 or quote.balance < 0:
        raise ValueError("To'lov narxi noto'g'ri, katalogdan qayta tanlang.")
    voucher = None
    if quote.discount_bonus_id is not None:
        voucher = (await session.execute(select(ReferralBonusLog).where(
            ReferralBonusLog.id == quote.discount_bonus_id,
        ).with_for_update())).scalar_one_or_none()
        if (voucher is None or voucher.seller_id != seller.id or voucher.bonus_type != BonusType.DISCOUNT
                or voucher.redeemed_at is not None or voucher.reserved_payment_id is not None):
            raise ValueError("Referal chegirmasi boshqa chekda ishlatilgan. Katalogdan qayta boshlang.")
    if quote.discount != (discounted(quote.base, voucher.value) if voucher else 0):
        raise ValueError("Chegirma o'zgargan. Katalogdan qayta tanlang.")
    if (quote.balance > seller.balance or (quote.balance and tariff.currency != "UZS")
            or quote.bank != quote.base - quote.discount - quote.balance or quote.bank < 0):
        raise ValueError("Bonus balansi o'zgargan. Katalogdan qayta tanlang.")
    return voucher


async def seller_stats(session: AsyncSession, seller_id: int) -> dict[str, int]:
    seller = await session.get(Seller, seller_id)
    if seller is None:
        return {"invited": 0, "rewarded": 0, "pending": 0}
    rows = (await session.execute(select(Referral.status, func.count(Referral.id)).where(
        Referral.referrer_id == seller.user_id,
    ).group_by(Referral.status))).all()
    counts = {status: int(count) for status, count in rows}
    return {"invited": sum(counts.values()), "rewarded": counts.get("applied", 0),
            "pending": counts.get("pending", 0)}
