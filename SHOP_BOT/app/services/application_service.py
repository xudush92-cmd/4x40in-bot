"""UX-2: sotuvchilik arizasi, alohida navbat va atomar admin qarori.

`SellerStatus.PENDING` — tarifi yo'q sotuvchi; ariza statusi EMAS.
Har bir yozish amali chaqiruvchining sessiyasida bajariladi. Telegram DM faqat
chaqiruvchi commit qilgandan keyin yuboriladi. UNIQUE (ochiq ariza), sotuvchi
user_id UNIQUE va shartli UPDATE (qaror) parallel amallarni himoya qiladi.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole, ApplicationStatus, SellerStatus
from app.db.models import ActionLog, Admin, Referral, Seller, SellerApplication, User
from app.services import seller_service
from app.utils.text import clean_text
from app.utils.time import ensure_aware, fmt_dt, utcnow

MAX_NAME = 64
MAX_REASON = 500
RETRY_AFTER = timedelta(hours=1)
MAX_APPLICATIONS_PER_DAY = 3
_USERNAME = re.compile(r"^@[A-Za-z0-9_]{5,32}$")
_PHONE = re.compile(r"^\+?[0-9]{9,15}$")


class ApplicationError(ValueError):
    """Foydalanuvchiga ko'rsatish mumkin bo'lgan biznes qoida xatosi."""


def validate_name(raw: str | None) -> str:
    name = clean_text(raw)
    if name is None or not 2 <= len(name) <= MAX_NAME:
        raise ApplicationError("Ism/do'kon nomi 2–64 belgi bo'lishi kerak.")
    return name


def validate_contact(raw: str | None) -> tuple[str, str]:
    """Faqat Telegram @username yoki xalqaro telefon; ortiqcha qirqish yo'q."""
    value = (raw or "").strip()
    if len(value) > MAX_NAME:
        raise ApplicationError("Aloqa 64 belgidan uzun bo'lmasin.")
    if _USERNAME.fullmatch(value):
        return "username", value
    # Telefonning faqat ko'rinish bo'sh joylari olib tashlanadi; xatoli
    # belgilarni yashirib yubormaslik uchun boshqa belgilarni qabul qilmaymiz.
    phone = re.sub(r"[\s()\-]", "", value)
    if _PHONE.fullmatch(phone):
        return "phone", phone
    raise ApplicationError("@username (5–32 belgi) yoki telefon (+998901234567) yuboring.")


def validate_reason(raw: str | None) -> str:
    reason = clean_text(raw)
    if reason is None or not 3 <= len(reason) <= MAX_REASON:
        raise ApplicationError("Rad sababi 3–500 belgi bo'lishi kerak.")
    return reason


async def latest_for(session: AsyncSession, user_id: int) -> SellerApplication | None:
    return (await session.execute(
        select(SellerApplication).where(SellerApplication.user_id == user_id)
        .order_by(SellerApplication.id.desc()).limit(1)
    )).scalar_one_or_none()


async def pending_for(
    session: AsyncSession, user_id: int, *, lock: bool = False,
) -> SellerApplication | None:
    stmt = select(SellerApplication).where(
        SellerApplication.user_id == user_id,
        SellerApplication.status == ApplicationStatus.PENDING,
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one_or_none()


async def count_pending(session: AsyncSession) -> int:
    return int((await session.execute(
        select(func.count()).select_from(SellerApplication)
        .where(SellerApplication.status == ApplicationStatus.PENDING)
    )).scalar_one())


async def list_pending(session: AsyncSession, *, offset: int = 0, limit: int = 6) -> list[SellerApplication]:
    return list((await session.execute(
        select(SellerApplication).where(SellerApplication.status == ApplicationStatus.PENDING)
        .order_by(SellerApplication.created_at, SellerApplication.id)
        .offset(offset).limit(limit)
    )).scalars().all())


async def lock_user(session: AsyncSession, user_id: int) -> None:
    """Mavjud user uchun ariza yuborish va qo'lda qo'shishni tartiblaydi (PG).

    Admin botga hali yozmagan IDni ham qo'sha oladi; user qatori bo'lmasa
    sellers.user_id UNIQUE va ariza pending UNIQUE hamon xavfsizlikni saqlaydi.
    """
    await session.execute(select(User.user_id).where(User.user_id == user_id).with_for_update())


async def precheck(
    session: AsyncSession, user_id: int, *, now: datetime | None = None,
) -> SellerApplication | None:
    """Ustani boshlashdan oldin ham sotuvchi, pending va tezlikni tekshirish."""
    await lock_user(session, user_id)
    if await seller_service.get_seller(session, user_id) is not None:
        raise ApplicationError("Bu ID allaqachon sotuvchi. Holatni /start orqali ko'ring yoki adminga yozing.")
    pending = await pending_for(session, user_id)
    if pending is not None:
        return pending

    when = now or utcnow()
    previous = await latest_for(session, user_id)
    if previous and previous.status == ApplicationStatus.APPROVED:
        raise ApplicationError("Arizangiz tasdiqlangan, lekin sotuvchi yozuvi topilmadi. Adminga yozing.")
    if previous and previous.status == ApplicationStatus.REJECTED and previous.decided_at:
        retry = ensure_aware(previous.decided_at) + RETRY_AFTER
        if retry > when:
            raise ApplicationError(f"Qayta ariza uchun {fmt_dt(retry)} gacha kuting (rad qaroridan 1 soat).")
    recent = (await session.execute(
        select(func.count()).select_from(SellerApplication).where(
            SellerApplication.user_id == user_id,
            SellerApplication.created_at >= when - timedelta(days=1),
        )
    )).scalar_one()
    if int(recent) >= MAX_APPLICATIONS_PER_DAY:
        raise ApplicationError("24 soatda ko'pi bilan 3 ta ariza. Keyinroq qayta urinib ko'ring.")
    return None


async def submit(
    session: AsyncSession, user_id: int, raw_name: str, raw_contact: str,
    *, now: datetime | None = None,
) -> tuple[SellerApplication, bool]:
    """Bitta ariza: ikki bosish bitta ID, rad etilgach yangi ID.

    Admin qo'lda qo'shgan (shu jumladan bloklangan/o'chirilgan) seller uchun
    yangi ariza yo'q. Sovutish: rad qaroridan 1 soat; 24 soatda jami 3 ta.
    """
    name = validate_name(raw_name)
    kind, contact = validate_contact(raw_contact)
    pending = await precheck(session, user_id, now=now)
    if pending is not None:
        return pending, False

    when = now or utcnow()
    try:
        # Boshqa update bilan to'qnashganda faqat INSERT ni rollback qilib,
        # g'olib arizani shu sessiyada o'qish mumkin bo'lsin (PostgreSQL ham).
        async with session.begin_nested():
            application = SellerApplication(
                user_id=user_id, display_name=name, contact_type=kind,
                contact_value=contact, status=ApplicationStatus.PENDING,
                created_at=when, updated_at=when,
            )
            session.add(application)
            await session.flush()
    except IntegrityError:
        pending = await pending_for(session, user_id)
        if pending is not None:
            return pending, False
        raise

    session.add(ActionLog(
        actor_id=user_id, action="seller_application_submitted", entity="seller_application",
        entity_id=application.id, after={"status": ApplicationStatus.PENDING},
    ))
    return application, True


async def decide(
    session: AsyncSession, application_id: int, actor_id: int, *,
    approve: bool, reason: str | None = None,
) -> tuple[SellerApplication | None, bool]:
    """Admin/super-admin qarori: CAS + seller + audit BIR tranzaksiyada.

    Eskirgan callback ikkinchi qarorni yozmaydi va qayta DM yubormaydi.
    `begin_nested` ichidagi xato seller/statusni birga rollback qiladi.
    """
    admin = (await session.execute(select(Admin).where(
        Admin.user_id == actor_id, Admin.is_active.is_(True),
        Admin.role.in_((AdminRole.ADMIN, AdminRole.SUPER)),
    ))).scalar_one_or_none()
    if admin is None:
        raise ApplicationError("Bu qarorni faqat admin yoki super-admin qabul qiladi.")
    clean_reason = None if approve else validate_reason(reason)

    async with session.begin_nested():
        application = (await session.execute(
            select(SellerApplication).where(SellerApplication.id == application_id).with_for_update()
            .execution_options(populate_existing=True)
        )).scalar_one_or_none()
        if application is None or application.status != ApplicationStatus.PENDING:
            return application, False

        # CAS SQLite'da FOR UPDATE yo'qligida ham eski callbackni to'xtatadi.
        when = utcnow()
        new_status = ApplicationStatus.APPROVED if approve else ApplicationStatus.REJECTED
        result = await session.execute(update(SellerApplication).where(
            SellerApplication.id == application.id,
            SellerApplication.status == ApplicationStatus.PENDING,
        ).values(status=new_status, decided_at=when, decided_by=actor_id,
                 reject_reason=clean_reason))
        if result.rowcount != 1:
            await session.refresh(application)
            return application, False

        seller: Seller | None = None
        if approve:
            seller = await seller_service.get_seller(session, application.user_id)
            if seller is not None and seller.status in {SellerStatus.BLOCKED, SellerStatus.DELETED}:
                raise ApplicationError("Bu sotuvchi bloklangan/o'chirilgan: avval admin qo'lda ko'rib chiqsin.")
            if seller is None:
                try:
                    # Boshqa admin aynan shu lahzada qo'lda qo'shgan bo'lsa,
                    # sotuvchilar jadvalidagi user_id UNIQUE ni ushlab qolamiz.
                    async with session.begin_nested():
                        seller, _ = await seller_service.get_or_create_seller(
                            session, application.user_id,
                            display_name=application.display_name,
                            phone=application.contact_value if application.contact_type == "phone" else None,
                            contact=application.contact_value if application.contact_type == "username" else None,
                            added_by=actor_id,
                        )
                except IntegrityError:
                    seller = await seller_service.get_seller(session, application.user_id)
                    if seller is None:
                        raise  # referal kodi yoki boshqa kutilmagan UNIQUE buzilishi
                    if seller.status in {SellerStatus.BLOCKED, SellerStatus.DELETED}:
                        raise ApplicationError("Bu sotuvchi bloklangan/o'chirilgan: admin ko'rsin.") from None
            # /start ref_<kod> arizadan OLDIN qayd qilingan bo'lishi mumkin.
            await _attach_referrer(session, seller)
            application.seller_id = seller.id
        session.add(ActionLog(
            actor_id=actor_id,
            action="seller_application_approved" if approve else "seller_application_rejected",
            entity="seller_application", entity_id=application.id,
            before={"status": ApplicationStatus.PENDING},
            after={"status": new_status, "seller_id": seller.id if seller else None},
        ))
        await session.flush()
    return application, True


async def _attach_referrer(session: AsyncSession, seller: Seller) -> None:
    """Eski shaxsiy start referali seller yaratilgach ham profilga bog'lansin."""
    if seller.referred_by is None:
        referrer_id = (await session.execute(select(Referral.referrer_id).where(
            Referral.referee_id == seller.user_id,
        ))).scalar_one_or_none()
        if referrer_id is not None:
            seller.referred_by = referrer_id


async def approve_manually(
    session: AsyncSession, seller: Seller, actor_id: int,
) -> SellerApplication | None:
    """Admin ID orqali qo'shsa, ochiq ariza o'sha tranzaksiyada yopiladi."""
    if seller.status in {SellerStatus.BLOCKED, SellerStatus.DELETED}:
        return None
    async with session.begin_nested():
        pending = await pending_for(session, seller.user_id, lock=True)
        if pending is None:
            return None
        result = await session.execute(update(SellerApplication).where(
            SellerApplication.id == pending.id,
            SellerApplication.status == ApplicationStatus.PENDING,
        ).values(status=ApplicationStatus.APPROVED, seller_id=seller.id,
                 decided_at=utcnow(), decided_by=actor_id))
        if result.rowcount != 1:
            return None
        await _attach_referrer(session, seller)
        session.add(ActionLog(
            actor_id=actor_id, action="seller_application_approved_manually",
            entity="seller_application", entity_id=pending.id,
            before={"status": ApplicationStatus.PENDING},
            after={"status": ApplicationStatus.APPROVED, "seller_id": seller.id},
        ))
        await session.flush()
    return pending
