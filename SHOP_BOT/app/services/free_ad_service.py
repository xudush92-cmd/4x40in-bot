"""Bepul e'lon: guruhga bog'langan 30 kun, sarflanadigan haqiqiy takliflar.

Pullik Seller/Ad/Subscription bilan aloqasi yo'q. Bitta guruhda har odamga
bitta faol e'lon, lekin har guruh va har yangi 30 kun uchun yangi imkoniyat.
Vaqt grant shartlar (tasdiq, N taklif, start va a'zolik) jam bo'lganda boshlanadi.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import InviteSource, SellerStatus
from app.db.models import (
    Category,
    CounterSetting,
    FreeAd,
    FreeEntitlement,
    FreeInviteUse,
    FreePostLog,
    Group,
    GroupSettings,
    InviteEvent,
    Seller,
    User,
)
from app.services.group_service import resume_group
from app.utils.time import ensure_aware, utcnow

FREE_DAYS = 30  # kalendar oy emas, qat'iy 30 x 24 soat; eskisi uzaytirilmaydi
MAX_FREE_CAPTION = 900  # Telegram photo caption'ining 1024 UTF-16 chegarasidan past
MIN_FREE_INTERVAL = 60


async def groups(session: AsyncSession) -> list[Group]:
    """Guruh nomli tugmalar: kanallar emas, bot admin bo'lgan toifali guruhlar."""
    return list((await session.execute(
        select(Group).where(
            Group.is_supergroup.is_(True), Group.bot_is_admin.is_(True),
            or_(Group.is_active.is_(True), Group.paused_reason == "empty_queue"),
            exists(select(Category.id).where(
                Category.group_id == Group.id, Category.is_active.is_(True)
            )),
        ).order_by(Group.id)
    )).scalars())


async def group_for(session: AsyncSession, group_id: int) -> Group | None:
    group = await session.get(Group, group_id)
    if group is None or not group.is_supergroup or not group.bot_is_admin:
        return None
    active_category = (await session.execute(select(Category.id).where(
        Category.group_id == group_id, Category.is_active.is_(True),
    ).limit(1))).scalar_one_or_none()
    return group if active_category is not None else None


async def terms(session: AsyncSession, group: Group) -> CounterSetting | None:
    """Bepul yo'l faqat shu guruhning jonli, qo'lda qo'shish sanoqchisi bilan."""
    setting = await session.get(CounterSetting, group.id)
    if not (group.settings and group.settings.free_ads_enabled and group.settings.counter_enabled
            and setting and setting.enabled
            and not setting.dry_run and not setting.require_subscription
            and setting.required_n > 0
            and (setting.count_sources or {}).get(InviteSource.ADDED_BY)):
        return None
    return setting


def ready_group(group: Group) -> bool:
    return bool(group.is_active and group.is_supergroup and group.bot_is_admin
                and group.settings and group.settings.posting_enabled
                and group.settings.free_ads_enabled and group.rotation)


async def is_member(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Telegram a'zolik noaniq bo'lsa yangi bepul huquq/post bermaymiz."""
    try:
        row = await bot.get_chat_member(chat_id, user_id)
    except TelegramAPIError:
        return False
    status = str(row.status)
    return status in {"member", "administrator", "creator"} or (
        status == "restricted" and bool(getattr(row, "is_member", False))
    )


def valid_caption(caption: str) -> bool:
    """Telegram photo caption chegarasi UTF-16 code unit bilan o'lchanadi."""
    return 10 <= len(caption) and len(caption.encode("utf-16-le")) // 2 <= MAX_FREE_CAPTION


def interval(group: Group) -> timedelta:
    """Har odamning shaxsiy taymeri; group.rotation.next_post_at EMAS."""
    assert group.settings is not None
    return timedelta(seconds=max(MIN_FREE_INTERVAL, group.settings.interval_sec))


async def get_ad(session: AsyncSession, user_id: int, group_id: int) -> FreeAd | None:
    return (await session.execute(select(FreeAd).where(
        FreeAd.user_id == user_id, FreeAd.group_id == group_id,
    ))).scalar_one_or_none()


async def entitlement(session: AsyncSession, user_id: int, group_id: int,
                      *, lock: bool = False) -> FreeEntitlement | None:
    stmt = select(FreeEntitlement).where(
        FreeEntitlement.user_id == user_id, FreeEntitlement.group_id == group_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def unspent_ids(session: AsyncSession, group_id: int, user_id: int,
                      *, limit: int | None = None) -> list[int]:
    """Faqat tasdiqlangan direct-add; havola, bot, admin bonus va eski grant emas."""
    stmt = select(InviteEvent.id).where(
        InviteEvent.group_id == group_id,
        InviteEvent.inviter_id == user_id,
        InviteEvent.source == InviteSource.ADDED_BY,
        InviteEvent.counted.is_(True),
        ~exists(select(FreeInviteUse.event_id).where(FreeInviteUse.event_id == InviteEvent.id)),
    ).order_by(InviteEvent.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await session.execute(stmt)).scalars())


async def unspent_count(session: AsyncSession, group_id: int, user_id: int) -> int:
    return int((await session.execute(select(func.count(InviteEvent.id)).where(
        InviteEvent.group_id == group_id, InviteEvent.inviter_id == user_id,
        InviteEvent.source == InviteSource.ADDED_BY, InviteEvent.counted.is_(True),
        ~exists(select(FreeInviteUse.event_id).where(FreeInviteUse.event_id == InviteEvent.id)),
    ))).scalar_one())


async def is_blocked(session: AsyncSession, user_id: int) -> bool:
    user = await session.get(User, user_id)
    if user is not None and user.is_blocked:
        return True
    row = (await session.execute(select(Seller.id).where(
        Seller.user_id == user_id, Seller.status.in_((SellerStatus.BLOCKED, SellerStatus.DELETED)),
    ).limit(1))).scalar_one_or_none()
    return row is not None


async def submit(session: AsyncSession, user_id: int, group_id: int,
                 photo_id: str, caption: str) -> FreeAd:
    """Suratni admin navbatiga qo'yish. Hech qachon o'z-o'zidan tasdiqlamaydi."""
    caption = caption.strip()
    if not photo_id or len(photo_id) > 255 or not valid_caption(caption):
        raise ValueError("Bitta surat va izohda kamida 10 belgi, ko'pi bilan 900 birlik (emoji 2 birlik) yuboring.")
    group = await group_for(session, group_id)
    if group is None or not (group.is_active or group.paused_reason == "empty_queue"):
        raise ValueError("Bu guruh hozir e'lon qabul qilmaydi.")
    setting = await terms(session, group)
    if not setting:
        raise ValueError("Bu guruhda bepul e'lon yoki qo'lda a'zo qo'shish sanoqchisi jonli emas.")
    if not group.settings or (not group.settings.posting_enabled and group.paused_reason != "empty_queue"):
        raise ValueError("Bu guruhda joylash hozir o'chirilgan.")
    if await is_blocked(session, user_id):
        raise ValueError("Hisobingiz cheklangan; yordam uchun adminga yozing.")

    ad = (await session.execute(select(FreeAd).where(
        FreeAd.user_id == user_id, FreeAd.group_id == group_id,
    ).with_for_update())).scalar_one_or_none()
    if ad is None:
        ad = FreeAd(user_id=user_id, group_id=group_id, desired_running=True,
                    post_count=0, revision=0)
        session.add(ad)
    ad.revision += 1
    ad.pending_photo_id = photo_id
    ad.pending_caption = caption
    ad.review_status = "pending"
    ad.rejected_reason = None
    # Tahrir paytida eski tasdiqlangan e'lon avtomatik yuborilmasin.
    ad.next_post_at = None
    if group.paused_reason == "empty_queue":
        # Eski pullik navbat bo'shligi uchun pauza qilingan guruhda invite
        # hisoblash ham to'xtagan. Faqat shu avtomatik pauzani tiklaymiz.
        await resume_group(session, group)
    await session.flush()
    return ad


async def maybe_activate(session: AsyncSession, ad: FreeAd, now: datetime,
                         *, member_ok: bool, allow_new: bool = True) -> bool:
    """Haqiqiy a'zolik tasdiqlansa yangi davrni ochish va shaxsiy taymerni qo'yish.

    Bitta PG tranzaksiyasi/ad+entitlement row lock va UNIQUE(event_id) bir
    qo'shilishni ikki marta sarflashga yo'l qo'ymaydi. Caller commit qiladi.
    """
    if not member_ok:
        return False
    # Admin/user callback va scheduler bir vaqtda kelsa, yo'q entitlement'ning
    # o'zini qulflab bo'lmaydi. Bitta FreeAd qatori barcha grantlarni
    # seriyalashtiradi; populate_existing boshqa sessiya yangilagan holatni oladi.
    await session.flush()
    ad = (await session.execute(select(FreeAd).where(FreeAd.id == ad.id)
                                .with_for_update()
                                .execution_options(populate_existing=True))).scalar_one_or_none()
    if ad is None or not ad.desired_running or ad.review_status != "approved":
        return False
    if not ad.approved_photo_id or not ad.approved_caption or await is_blocked(session, ad.user_id):
        return False
    group = await group_for(session, ad.group_id)
    if group is None or not ready_group(group):
        return False
    access = await entitlement(session, ad.user_id, ad.group_id, lock=True)
    granted = False
    if access is None or ensure_aware(access.expires_at) <= now:
        if not allow_new:
            ad.next_post_at = None
            return False
        policy = await terms(session, group)
        if policy is None:
            ad.next_post_at = None
            return False
        ids = await unspent_ids(session, ad.group_id, ad.user_id, limit=policy.required_n)
        if len(ids) < policy.required_n:
            ad.next_post_at = None
            return False
        if access is None:
            access = FreeEntitlement(user_id=ad.user_id, group_id=ad.group_id,
                                     valid_from=now, expires_at=now + timedelta(days=FREE_DAYS),
                                     period=1)
            session.add(access)
            await session.flush()
        else:
            access.period += 1
            access.valid_from = now
            access.expires_at = now + timedelta(days=FREE_DAYS)
        session.add_all(FreeInviteUse(event_id=event_id, entitlement_id=access.id,
                                      period=access.period) for event_id in ids)
        granted = True
        ad.next_post_at = None  # yangi oy: oldingi davrdan qolgan due amal qilmaydi
    if ad.next_post_at is None:
        # Sending jarayonida pauza/tahrir bo'lsa boshqa claim yaratmaymiz.
        sending = (await session.execute(select(FreePostLog.id).where(
            FreePostLog.free_ad_id == ad.id, FreePostLog.status == "sending",
        ).limit(1))).scalar_one_or_none()
        if sending is None:
            ad.next_post_at = now + interval(group)
    return granted


async def review(session: AsyncSession, ad_id: int, revision: int, actor: int,
                 *, approve: bool) -> FreeAd:
    ad = (await session.execute(select(FreeAd).where(FreeAd.id == ad_id)
                                .with_for_update())).scalar_one_or_none()
    if ad is None or ad.review_status != "pending" or ad.revision != revision:
        raise ValueError("Bu qaror eskirgan yoki e'lon allaqachon ko'rib chiqilgan.")
    if approve:
        if not ad.pending_photo_id or not ad.pending_caption:
            raise ValueError("Tasdiqlash uchun rasm va matn yo'q.")
        ad.approved_photo_id = ad.pending_photo_id
        ad.approved_caption = ad.pending_caption
        ad.review_status = "approved"
        ad.rejected_reason = None
    else:
        # Yangi tahrir rad etilsa avvalgi tasdiqlangan mazmun o'zgarishsiz qoladi.
        ad.review_status = "approved" if ad.approved_photo_id else "rejected"
        ad.rejected_reason = "E'lon mazmuni moderator tomonidan rad etildi. Tuzatib qayta yuboring."
    ad.pending_photo_id = None
    ad.pending_caption = None
    ad.reviewed_by = actor
    ad.reviewed_at = utcnow()
    ad.next_post_at = None
    await session.flush()
    return ad


async def revoke(session: AsyncSession, ad_id: int, revision: int, actor: int) -> FreeAd:
    """Admin tasdiqni bekor qilsa post darhol to'xtaydi; user Start aylanib o'tolmaydi."""
    ad = (await session.execute(select(FreeAd).where(FreeAd.id == ad_id)
                                .with_for_update())).scalar_one_or_none()
    if ad is None or ad.review_status != "approved" or ad.revision != revision:
        raise ValueError("Tasdiq allaqachon o'zgargan; kartani yangilang.")
    in_flight = (await session.execute(select(FreePostLog.id).where(
        FreePostLog.free_ad_id == ad.id, FreePostLog.status == "sending",
    ).limit(1))).scalar_one_or_none()
    if in_flight:
        raise ValueError("Post hozir yuborilmoqda; natija aniqlangach qayta urinib ko'ring.")
    ad.approved_photo_id = None
    ad.approved_caption = None
    ad.review_status = "rejected"
    ad.rejected_reason = "Admin tasdiqni bekor qildi. Yangi e'lonni qayta yuboring."
    ad.desired_running = False
    ad.next_post_at = None
    ad.reviewed_by = actor
    ad.reviewed_at = utcnow()
    await session.flush()
    return ad


async def set_running(session: AsyncSession, ad: FreeAd, running: bool) -> None:
    ad.desired_running = running
    ad.next_post_at = None
    await session.flush()


async def rebase_group_due(session: AsyncSession, group: Group,
                           now: datetime | None = None) -> int:
    """Admin guruhni qayta yoqsa/interval o'zgarsa eski due qarzga aylanmasin."""
    now = now or utcnow()
    if not group.settings:
        return 0
    rows = (await session.execute(select(FreeAd).where(
        FreeAd.group_id == group.id, FreeAd.desired_running.is_(True),
        FreeAd.review_status == "approved", FreeAd.next_post_at.is_not(None),
    ).with_for_update())).scalars().all()
    changed = 0
    for ad in rows:
        sending = (await session.execute(select(FreePostLog.id).where(
            FreePostLog.free_ad_id == ad.id, FreePostLog.status == "sending",
        ).limit(1))).scalar_one_or_none()
        if sending is not None:
            continue  # in-flight xabar va uning lease'i o'zgarmasin
        access = await entitlement(session, ad.user_id, ad.group_id)
        ad.next_post_at = (now + interval(group) if access and
                           ensure_aware(access.expires_at) > now else None)
        changed += 1
    await session.flush()
    return changed


async def waiting_ids(session: AsyncSession, now: datetime, *, after_id: int = 0,
                      limit: int = 100) -> list[int]:
    """Taklif kutayotgan yoki muddati tugagan davrlar; cursor navbatni och qoldirmaydi."""
    return list((await session.execute(
        select(FreeAd.id).outerjoin(FreeEntitlement,
            (FreeEntitlement.user_id == FreeAd.user_id)
            & (FreeEntitlement.group_id == FreeAd.group_id))
        .join(Group, Group.id == FreeAd.group_id)
        .join(GroupSettings, GroupSettings.group_id == Group.id)
        .where(FreeAd.id > after_id, FreeAd.desired_running.is_(True),
               Group.is_active.is_(True), GroupSettings.posting_enabled.is_(True),
               GroupSettings.free_ads_enabled.is_(True),
               FreeAd.review_status == "approved",
               or_(FreeAd.next_post_at.is_(None), FreeEntitlement.expires_at <= now))
        .order_by(FreeAd.id).limit(limit)
    )).scalars())


async def due_ids(session: AsyncSession, now: datetime, *, limit: int = 100) -> list[int]:
    """Guruh umumiy 30 daqiqalik aylanmasi emas, har user'ning due vaqti."""
    return list((await session.execute(select(FreeAd.id).where(
        FreeAd.next_post_at.is_not(None), FreeAd.next_post_at <= now,
        FreeAd.desired_running.is_(True), FreeAd.review_status == "approved",
    ).order_by(FreeAd.next_post_at, FreeAd.id).limit(limit))).scalars())


async def due_one_per_group(session: AsyncSession, now: datetime,
                            *, limit: int = 100) -> list[int]:
    """Texnik navbat: har guruhdan bitta; bir guruh boshqalarni och qoldirmaydi."""
    grouped = list((await session.execute(
        select(FreeAd.group_id, func.min(FreeAd.next_post_at).label("first_due"))
        .join(Group, Group.id == FreeAd.group_id)
        .join(GroupSettings, GroupSettings.group_id == Group.id)
        .join(FreeEntitlement, (FreeEntitlement.group_id == FreeAd.group_id)
              & (FreeEntitlement.user_id == FreeAd.user_id))
        .where(FreeAd.next_post_at <= now, FreeAd.desired_running.is_(True),
               FreeAd.review_status == "approved", Group.is_active.is_(True),
               Group.bot_is_admin.is_(True), GroupSettings.posting_enabled.is_(True),
               GroupSettings.free_ads_enabled.is_(True), FreeEntitlement.expires_at > now)
        .group_by(FreeAd.group_id).order_by("first_due", FreeAd.group_id).limit(limit)
    )).all())
    result = []
    for group_id, _ in grouped:
        ad_id = (await session.execute(select(FreeAd.id)
            .join(FreeEntitlement, (FreeEntitlement.group_id == FreeAd.group_id)
                  & (FreeEntitlement.user_id == FreeAd.user_id))
            .where(FreeAd.group_id == group_id, FreeAd.next_post_at <= now,
                   FreeAd.desired_running.is_(True), FreeAd.review_status == "approved",
                   FreeEntitlement.expires_at > now)
            .order_by(FreeAd.next_post_at, FreeAd.id).limit(1))).scalar_one_or_none()
        if ad_id is not None:
            result.append(ad_id)
    return result
