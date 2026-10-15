"""Phase 4: e'lon navbati va post holatini bazada boshqarish.

Telegram'ga yuborish bu qatlamda YO'Q: claim alohida tranzaksiyada commit
qilinadi, keyin Bot API chaqiriladi, natija yana alohida tranzaksiyada yoziladi.
`status=sending` va lease — process xabar yuborish o'rtasida o'lsa, noma'lum
natijani avtomatik qayta yubormaslik uchun (Bot API idempotency key bermaydi).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.constants import MIN_INTERVAL_SEC, AdStatus, SellerStatus, SubscriptionStatus
from app.db.models import (
    Ad,
    Category,
    CleanerSetting,
    CleanupLog,
    ErrorLog,
    Group,
    GroupRotation,
    GroupSettings,
    PostedMessage,
    PostLog,
    Seller,
    Subscription,
    Tariff,
)
from app.services.group_service import pause_group
from app.services.settings_service import settings_service
from app.utils.time import ensure_aware

LEASE_SECONDS = 300  # Telegram so'rovlaridan uzun; muddati o'tsa xavfsiz pauza
DUE_BATCH = 100


@dataclass(frozen=True)
class PostingResult:
    status: str  # sent | busy | not_due | unavailable | deferred | empty | invalid | retry | error | uncertain
    detail: str = ""
    ad_id: int | None = None
    message_ids: tuple[int, ...] = ()
    notify: bool = False


@dataclass(frozen=True)
class PostingClaim:
    group_id: int
    chat_id: int
    category_id: int
    ad_id: int
    log_id: int
    lease_until: datetime
    wrapped: bool


def timezone_for(name: str | None, fallback: str = "Asia/Tashkent") -> ZoneInfo:
    try:
        return ZoneInfo(name or fallback)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def local_day(now: datetime, tz: ZoneInfo) -> date:
    return (ensure_aware(now) or now.replace(tzinfo=UTC)).astimezone(tz).date()


def quiet_until(now: datetime, start: str | None, end: str | None, tz: ZoneInfo) -> datetime | None:
    """Tinch vaqt ichida bo'lsak, uning UTC'dagi tugash vaqti (DST ham hisobda)."""
    if not start or not end or start == end:
        return None
    try:
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        begin, finish = time(sh, sm), time(eh, em)
    except (TypeError, ValueError):
        return None
    current = (ensure_aware(now) or now.replace(tzinfo=UTC)).astimezone(tz)
    clock = current.time().replace(tzinfo=None)
    if begin < finish:  # shu kun ichida
        if not begin <= clock < finish:
            return None
        end_day = current.date()
    else:  # 23:00–08:00 (yarim tundan o'tadi)
        if clock >= begin:
            end_day = current.date() + timedelta(days=1)
        elif clock < finish:
            end_day = current.date()
        else:
            return None
    return datetime.combine(end_day, finish, tzinfo=tz).astimezone(UTC)


def tomorrow(now: datetime, tz: ZoneInfo) -> datetime:
    next_day = local_day(now, tz) + timedelta(days=1)
    return datetime.combine(next_day, time.min, tzinfo=tz).astimezone(UTC)


def next_interval(now: datetime, seconds: int | None, jitter_percent: int | None = 10) -> datetime:
    """Jitterdan keyin HAM minimal 60 sekundni saqlaymiz."""
    interval = max(MIN_INTERVAL_SEC, int(seconds or MIN_INTERVAL_SEC))
    jitter = max(0, min(30, int(jitter_percent or 0))) / 100
    delta = max(MIN_INTERVAL_SEC, round(interval * (1 + random.uniform(-jitter, jitter))))
    return (ensure_aware(now) or now.replace(tzinfo=UTC)) + timedelta(seconds=delta)


def _allowed(value: object, target_id: int) -> bool:
    """NULL = hammasi; bo'sh ro'yxat = hech biri (tarif cheklovi)."""
    if value is None:
        return True
    if not isinstance(value, list):
        return False
    return target_id in value or str(target_id) in value


async def due_group_ids(session: AsyncSession, now: datetime, limit: int = DUE_BATCH) -> list[int]:
    rows = await session.execute(
        select(GroupRotation.group_id)
        .join(Group, Group.id == GroupRotation.group_id)
        .join(GroupSettings, GroupSettings.group_id == Group.id)
        .where(
            Group.is_active.is_(True), Group.is_supergroup.is_(True),
            Group.bot_is_admin.is_(True), GroupSettings.posting_enabled.is_(True),
            GroupRotation.next_post_at.is_not(None), GroupRotation.next_post_at <= now,
        )
        .order_by(GroupRotation.next_post_at, GroupRotation.group_id)
        .limit(limit)
    )
    return list(rows.scalars())


async def eligible_ad(
    session: AsyncSession, category: Category, now: datetime, *, force_ad_id: int | None = None
) -> tuple[int | None, bool]:
    """Kursordan keyingi haqiqatan sotib olingan faol e'lon (wrap bilan).

    `ads_left` — yangi e'lon yaratish uchun BO'SH joy, post limiti emas: sotuvchi
    oxirgi slotini ishlatganida ads_left=0, o'sha e'lon baribir post qilinishi kerak.
    """
    stmt = (
        select(Ad.id, Ad.position, Tariff.allowed_category_ids, Tariff.allowed_group_ids)
        .join(Seller, Seller.id == Ad.seller_id)
        .join(Subscription, Subscription.seller_id == Seller.id)
        .join(Tariff, Tariff.id == Subscription.tariff_id)
        .where(
            Ad.category_id == category.id, Ad.status == AdStatus.ACTIVE,
            (Ad.next_eligible_at.is_(None)) | (Ad.next_eligible_at <= now),
            Seller.status == SellerStatus.ACTIVE,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.starts_at <= now, Subscription.expires_at > now,
            Subscription.ads_limit > 0, Subscription.ads_used <= Subscription.ads_limit,
        )
        .order_by(Ad.position, Ad.id)
    )
    if force_ad_id is not None:
        stmt = stmt.where(Ad.id == force_ad_id)
    candidates = [
        (ad_id, position)
        for ad_id, position, cats, groups in (await session.execute(stmt)).all()
        if _allowed(cats, category.id) and _allowed(groups, category.group_id)
    ]
    if not candidates:
        return None, False
    if force_ad_id is not None:
        return candidates[0][0], False

    cursor_id = category.rotation.cursor_ad_id if category.rotation else None
    if cursor_id is not None:
        previous = (await session.execute(
            select(Ad.position).where(Ad.id == cursor_id, Ad.category_id == category.id)
        )).scalar_one_or_none()
        if previous is not None:
            for ad_id, position in candidates:
                if (position, ad_id) > (previous, cursor_id):
                    return ad_id, False
            return candidates[0][0], True
    return candidates[0][0], False


async def _future_eligible(session: AsyncSession, category: Category, now: datetime) -> datetime | None:
    """Faqat next_eligible_at sabab kutayotgan e'lon bo'lsa uning vaqtini topish."""
    rows = await session.execute(
        select(Ad.next_eligible_at, Tariff.allowed_category_ids, Tariff.allowed_group_ids)
        .join(Seller, Seller.id == Ad.seller_id)
        .join(Subscription, Subscription.seller_id == Seller.id)
        .join(Tariff, Tariff.id == Subscription.tariff_id)
        .where(
            Ad.category_id == category.id, Ad.status == AdStatus.ACTIVE,
            Ad.next_eligible_at > now, Seller.status == SellerStatus.ACTIVE,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.starts_at <= now, Subscription.expires_at > now,
            Subscription.ads_limit > 0, Subscription.ads_used <= Subscription.ads_limit,
        )
        .order_by(Ad.next_eligible_at)
    )
    for when, cats, groups in rows:
        if _allowed(cats, category.id) and _allowed(groups, category.group_id):
            return ensure_aware(when)
    return None


async def _cas_next(session: AsyncSession, rotation: GroupRotation, value: datetime) -> bool:
    old = rotation.next_post_at
    condition = (GroupRotation.next_post_at.is_(None) if old is None else GroupRotation.next_post_at == old)
    result = await session.execute(
        update(GroupRotation)
        .where(GroupRotation.group_id == rotation.group_id, condition)
        .values(next_post_at=value)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return False
    set_committed_value(rotation, "next_post_at", value)
    return True


async def _locked_rotation(session: AsyncSession, group_id: int) -> GroupRotation | None:
    # PostgreSQL: boshqa poster kutmay o'tadi. SQLite testda FOR UPDATE yo'q,
    # lekin _cas_next atomar shart bilan ikkinchi worker'ni to'xtatadi.
    return (await session.execute(
        select(GroupRotation).where(GroupRotation.group_id == group_id)
        .with_for_update(skip_locked=True)
    )).scalar_one_or_none()


async def claim_post(
    session: AsyncSession, group_id: int, now: datetime, *, force_ad_id: int | None = None
) -> tuple[PostingClaim | None, PostingResult]:
    """Bitta guruhni band qilish. CHAQIRUVCHI shu tranzaksiyani Telegram'dan OLDIN commit qiladi."""
    rotation = await _locked_rotation(session, group_id)
    if rotation is None:
        return None, PostingResult("busy", "Navbat boshqa worker'da yoki mavjud emas.")
    group = await session.get(Group, group_id)
    if group is None or group.settings is None:
        return None, PostingResult("unavailable", "Guruh sozlamalari topilmadi.")
    settings = group.settings
    if not group.is_active or not group.is_supergroup or not group.bot_is_admin or not settings.posting_enabled:
        return None, PostingResult("unavailable", "Guruh faol supergroup va bot admin bo'lishi kerak.")
    if force_ad_id is None and (
        rotation.next_post_at is None or ensure_aware(rotation.next_post_at) > now
    ):
        return None, PostingResult("not_due", "Hali joylash vaqti kelmadi.")
    if force_ad_id is not None and rotation.last_post_at and (
        (now - ensure_aware(rotation.last_post_at)).total_seconds() < MIN_INTERVAL_SEC
    ):
        return None, PostingResult("deferred", "Bu guruhda postlar orasida kamida 60 sekund bo'lishi kerak.")

    # Oldingi yuborish yakunlanmagan. Lease o'tsa ham takroriy postga yo'l yo'q:
    # Telegram xabarni qabul qilgan bo'lishi mumkin. Adminga tekshirtiramiz.
    sending = (await session.execute(
        select(PostLog).where(PostLog.group_id == group_id, PostLog.status == "sending")
        .order_by(PostLog.id.desc()).limit(1)
    )).scalar_one_or_none()
    if sending is not None:
        if rotation.next_post_at and ensure_aware(rotation.next_post_at) <= now:
            sending.status = "uncertain"
            sending.error = "Poster uzildi: Telegram'ga yuborilgan-yuborilmagani noma'lum"
            await pause_group(session, group, reason="error")
            group.last_error = sending.error
            session.add(ErrorLog(source="poster", group_id=group_id, message=sending.error, is_critical=True))
            return None, PostingResult("uncertain", sending.error, sending.ad_id, notify=True)
        return None, PostingResult("busy", "Bu guruhda joylash davom etmoqda.")

    zone_name = settings.timezone or str(await settings_service.get("timezone", "Asia/Tashkent", session))
    tz = timezone_for(zone_name)
    today = local_day(now, tz)
    used = rotation.today_count if rotation.today_date == today else 0
    defer = quiet_until(now, settings.quiet_start, settings.quiet_end, tz)
    if used >= max(1, settings.daily_post_limit):
        defer = max(defer or now, tomorrow(now, tz))
        defer = quiet_until(defer, settings.quiet_start, settings.quiet_end, tz) or defer
    if defer is not None:
        if await _cas_next(session, rotation, defer):
            return None, PostingResult("deferred", f"Tinch soat yoki kunlik limit: {defer.isoformat()}")
        return None, PostingResult("busy")

    categories = list((await session.execute(
        select(Category).where(Category.group_id == group_id, Category.is_active.is_(True))
        .order_by(Category.position, Category.id)
    )).scalars())
    categories = [c for c in categories if c.rotation is not None and not c.rotation.is_paused]
    if force_ad_id is not None:
        forced_ad = await session.get(Ad, force_ad_id)
        categories = [c for c in categories if forced_ad is not None and forced_ad.category_id == c.id]
        if not categories:
            return None, PostingResult("invalid", "E'lon shu guruhning faol toifasida emas.")
    else:
        categories.sort(key=lambda c: (
            ensure_aware(c.rotation.next_post_at) or datetime.min.replace(tzinfo=UTC), c.position, c.id
        ))

    next_times: list[datetime] = []
    selected: tuple[Category, int, bool] | None = None
    for category in categories:
        due = ensure_aware(category.rotation.next_post_at)
        if force_ad_id is None and due is not None and due > now:
            next_times.append(due)
            continue
        ad_id, wrapped = await eligible_ad(session, category, now, force_ad_id=force_ad_id)
        if ad_id is not None:
            selected = (category, ad_id, wrapped)
            break
        if force_ad_id is None:
            future = await _future_eligible(session, category, now)
            if future is not None:
                next_times.append(future)
    if selected is None:
        if force_ad_id is not None:
            return None, PostingResult("invalid", "E'lon faol emas, obuna yoki tarif ruxsati yo'q.")
        if next_times:
            later = max(min(next_times), (ensure_aware(rotation.last_post_at) or now - timedelta(seconds=MIN_INTERVAL_SEC)) + timedelta(seconds=MIN_INTERVAL_SEC))
            if await _cas_next(session, rotation, later):
                return None, PostingResult("deferred", f"Keyingi nomzod: {later.isoformat()}")
            return None, PostingResult("busy")
        await pause_group(session, group, reason="empty_queue")
        group.last_error = "Navbatda obunasi faol e'lon yo'q"
        session.add(PostLog(group_id=group_id, status="skipped", error=group.last_error))
        return None, PostingResult("empty", group.last_error, notify=True)

    category, ad_id, wrapped = selected
    lease = now + timedelta(seconds=LEASE_SECONDS)
    if not await _cas_next(session, rotation, lease):
        return None, PostingResult("busy", "Boshqa worker oldin band qildi.")
    log = PostLog(group_id=group_id, category_id=category.id, ad_id=ad_id, status="sending")
    session.add(log)
    await session.flush()
    return PostingClaim(group_id, group.tg_chat_id, category.id, ad_id, log.id, lease, wrapped), PostingResult("claimed", ad_id=ad_id)


async def _next_group_time(session: AsyncSession, group: Group, now: datetime, tz: ZoneInfo) -> datetime:
    settings = group.settings
    assert settings is not None
    categories = (await session.execute(
        select(Category).where(Category.group_id == group.id, Category.is_active.is_(True))
    )).scalars().all()
    times = [ensure_aware(c.rotation.next_post_at) or now for c in categories if c.rotation and not c.rotation.is_paused]
    later = max(now + timedelta(seconds=MIN_INTERVAL_SEC), min(times, default=next_interval(now, settings.interval_sec, settings.jitter_percent)))
    if group.rotation and group.rotation.today_date == local_day(now, tz) and group.rotation.today_count >= max(1, settings.daily_post_limit):
        later = max(later, tomorrow(now, tz))
    return quiet_until(later, settings.quiet_start, settings.quiet_end, tz) or later


async def finish_post(
    session: AsyncSession, claim: PostingClaim, message_ids: list[int], now: datetime
) -> PostingResult:
    """Muvaffaqiyat: xabar ID'lari, statistika, kursor va keyingi vaqt bir tranzaksiyada."""
    log = await session.get(PostLog, claim.log_id)
    if log is None or log.status != "sending":
        detail = f"Joylash jurnali o'zgargan: chat {claim.chat_id}, xabarlar {message_ids}; qo'lda tekshiring"
        if log is not None:
            log.status = "uncertain"
            log.message_ids = message_ids
            log.error = detail
        session.add(ErrorLog(source="poster", group_id=claim.group_id, message=detail, is_critical=True))
        group = await session.get(Group, claim.group_id)
        if group is not None:
            await pause_group(session, group, reason="error")
            group.last_error = detail[:500]
        return PostingResult("uncertain", detail, claim.ad_id, tuple(message_ids), notify=True)
    group = await session.get(Group, claim.group_id)
    ad = await session.get(Ad, claim.ad_id)
    category = await session.get(Category, claim.category_id)
    if (
        group is None or ad is None or category is None
        or category.rotation is None or group.rotation is None
        or category.group_id != claim.group_id or ad.category_id != claim.category_id
    ):
        log.status = "uncertain"
        log.message_ids = message_ids  # xabarlar Telegram'da bor; qo'lda o'chirish mumkin
        log.error = "Post yuborildi, lekin e'lon/guruh/toifa o'zgargan: qo'lda tekshiring"
        session.add(ErrorLog(source="poster", group_id=group.id if group else None, message=log.error, is_critical=True))
        if group is not None:
            await pause_group(session, group, reason="error")
        return PostingResult("uncertain", log.error, claim.ad_id, tuple(message_ids), notify=True)
    rotation = group.rotation
    settings = group.settings
    assert settings is not None
    zone_name = settings.timezone or str(await settings_service.get("timezone", "Asia/Tashkent", session))
    tz = timezone_for(zone_name)

    log.status = "ok"
    log.seller_id = ad.seller_id
    log.message_ids = message_ids
    log.duration_ms = max(0, round((now - (ensure_aware(log.created_at) or now)).total_seconds() * 1000))
    session.add(PostedMessage(
        ad_id=ad.id, group_id=group.id, category_id=category.id,
        message_ids=message_ids, sent_at=now, is_deleted=False,
    ))
    ad.post_count = (ad.post_count or 0) + 1
    ad.last_posted_at = now
    ad.group_id = category.group_id  # Phase 3 davridagi eski e'lonlarni ham tuzatish
    category.rotation.cursor_ad_id = ad.id
    category.rotation.last_post_at = now
    category.rotation.cycle_count = (category.rotation.cycle_count or 0) + int(claim.wrapped)
    category.rotation.next_post_at = next_interval(
        now, category.interval_override or settings.interval_sec, settings.jitter_percent
    )
    # `next_eligible_at` admin/kelgusi individual cheklovlar uchun: uni bu yerda
    # avtomatik yozmaymiz, aks holda interval o'zgarsa eski muddat to'sib qo'yadi.

    today = local_day(now, tz)
    rotation.today_count = (rotation.today_count if rotation.today_date == today else 0) + 1
    rotation.today_date = today
    rotation.last_post_at = now
    rotation.cycle_count = (rotation.cycle_count or 0) + int(claim.wrapped)
    rotation.error_streak = 0
    # Admin post orasida pauza/tumbler/intervalni o'zgartirgan bo'lishi mumkin.
    if group.is_active and settings.posting_enabled and ensure_aware(rotation.next_post_at) == claim.lease_until:
        rotation.next_post_at = await _next_group_time(session, group, now, tz)
    return PostingResult("sent", "E'lon joylandi.", ad.id, tuple(message_ids))


async def fail_post(
    session: AsyncSession, claim: PostingClaim, reason: str, now: datetime,
    *, retry_after: float | None = None, forbidden: bool = False, uncertain: bool = False,
    message_ids: list[int] | None = None,
) -> PostingResult:
    log = await session.get(PostLog, claim.log_id)
    if log is None or log.status != "sending":
        detail = f"Xato jurnali o'zgargan: chat {claim.chat_id}, xabarlar {message_ids or []}; qo'lda tekshiring"
        if log is not None:
            log.status = "uncertain"
            log.message_ids = message_ids or None
            log.error = detail
        session.add(ErrorLog(source="poster", group_id=claim.group_id, message=detail, is_critical=True))
        group = await session.get(Group, claim.group_id)
        if group is not None:
            await pause_group(session, group, reason="error")
            group.last_error = detail[:500]
        return PostingResult("uncertain", detail, claim.ad_id, tuple(message_ids or ()), notify=True)
    group = await session.get(Group, claim.group_id)
    log.error = reason[:2000]
    log.message_ids = message_ids or None
    if group is None or group.rotation is None or group.settings is None:
        log.status = "uncertain"
        session.add(ErrorLog(source="poster", message=f"chat {claim.chat_id}: {reason}", is_critical=True))
        return PostingResult("uncertain", reason, claim.ad_id, tuple(message_ids or ()), notify=True)
    rotation = group.rotation
    if uncertain:
        log.status = "uncertain"
        await pause_group(session, group, reason="error")
        group.last_error = reason[:500]
        session.add(ErrorLog(source="poster", group_id=claim.group_id, message=reason, is_critical=True))
        return PostingResult("uncertain", reason, claim.ad_id, tuple(message_ids or ()), notify=True)
    if retry_after is not None:
        log.status = "skipped"
        if group.is_active and group.settings.posting_enabled and ensure_aware(rotation.next_post_at) == claim.lease_until:
            rotation.next_post_at = now + timedelta(seconds=max(1, retry_after))
        return PostingResult("retry", f"Telegram FloodWait: {retry_after}s", claim.ad_id)

    log.status = "error"
    rotation.error_streak = (rotation.error_streak or 0) + 1
    group.last_error = reason[:500]
    session.add(ErrorLog(source="poster", group_id=claim.group_id, message=reason[:4000]))
    paused = forbidden or rotation.error_streak >= 3
    if paused:
        await pause_group(session, group, reason="error")
    elif group.is_active and group.settings.posting_enabled and ensure_aware(rotation.next_post_at) == claim.lease_until:
        rotation.next_post_at = now + timedelta(seconds=max(MIN_INTERVAL_SEC, 60 * (2 ** min(rotation.error_streak, 5))))
    return PostingResult("error", reason, claim.ad_id, notify=paused)


async def abandon_post(session: AsyncSession, claim: PostingClaim, now: datetime) -> None:
    """Claim'dan keyin global pauza yoqilsa: xabar ketmasin, muddat yangilansin."""
    log = await session.get(PostLog, claim.log_id)
    group = await session.get(Group, claim.group_id)
    if log and log.status == "sending":
        log.status = "skipped"
        log.error = "Global/guruh pauzasi"
    if group and group.rotation and group.settings and ensure_aware(group.rotation.next_post_at) == claim.lease_until:
        group.rotation.next_post_at = next_interval(now, group.settings.interval_sec, group.settings.jitter_percent)


async def rebase_paused(session: AsyncSession, now: datetime, limit: int = DUE_BATCH) -> int:
    """Kill switch/texnik rejimda muddati o'tgan vaqtlarni siljitish (qarz yo'q)."""
    changed = 0
    for group_id in await due_group_ids(session, now, limit):
        rotation = await _locked_rotation(session, group_id)
        if rotation is None or rotation.next_post_at is None or ensure_aware(rotation.next_post_at) > now:
            continue
        group = await session.get(Group, group_id)
        if group is None or group.settings is None:
            continue
        new_time = next_interval(now, group.settings.interval_sec, group.settings.jitter_percent)
        if await _cas_next(session, rotation, new_time):
            changed += 1
    return changed


async def old_posts_for_cleanup(
    session: AsyncSession, claim: PostingClaim
) -> list[PostedMessage]:
    """Tozalovchi ruxsat etsa har e'londan oxirgi N ta postni qoldirish."""
    policy = await session.get(CleanerSetting, claim.group_id)
    if policy is None or not policy.enabled or not policy.delete_old_ads:
        return []
    posts = (await session.execute(
        select(PostedMessage)
        .where(PostedMessage.ad_id == claim.ad_id, PostedMessage.group_id == claim.group_id,
               PostedMessage.is_deleted.is_(False))
        .order_by(PostedMessage.sent_at.desc(), PostedMessage.id.desc())
    )).scalars().all()
    return list(posts[max(0, policy.keep_last_ads):])


async def record_cleanup(
    session: AsyncSession, post_id: int, *, deleted: bool, error: str | None = None
) -> None:
    post = await session.get(PostedMessage, post_id)
    if post is None:
        return
    if deleted:
        post.is_deleted = True
        post.delete_error = None
        session.add(CleanupLog(group_id=post.group_id, kind="old_ad", deleted_count=len(post.message_ids or [])))
    else:
        post.delete_error = (error or "Noma'lum xato")[:500]
