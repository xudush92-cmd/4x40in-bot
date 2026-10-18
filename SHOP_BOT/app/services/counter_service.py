"""Phase 7: guruhlar kesimidagi haqiqiy takliflar va muddatli sanash.

Telegram API bu servisda yo'q. `invite_events(group_id,invitee_id)` foydalanuvchi
qayta kirsa yoki update ikki marta kelsa ham ikkinchi marta sanamaslikka xizmat qiladi.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import CounterMode, InviteSource, PermissionKind, SellerStatus, SubscriptionStatus
from app.db.models import (
    ActionLog,
    Category,
    CounterAudit,
    CounterJoinRequest,
    CounterSetting,
    CounterTotal,
    Group,
    InviteEvent,
    InviteLink,
    Seller,
    Subscription,
    Tariff,
)
from app.services.group_policy_service import permission_kinds
from app.utils.text import clean_text
from app.utils.time import ensure_aware, utcnow

# N sharti uchun faqat Telegramdagi «A'zo qo'shish». Eski link eventlari arxivda.
SOURCES = (InviteSource.ADDED_BY,)
BOOLEANS = frozenset({"enabled", "dry_run"})
NUMBERS = {"required_n": (0, 1000), "min_stay_minutes": (0, 100800)}
MAX_MANUAL_ADJUST = 10000  # faqat admin, sabab va audit bilan


def safe_counter(group_id: int) -> CounterSetting:
    """Yangi guruhda sanash/jazo o'chiq, jonli rejim alohida tasdiqlanadi."""
    return CounterSetting(
        group_id=group_id, enabled=False, dry_run=True, required_n=3, mode=CounterMode.SOFT,
        min_stay_minutes=10, link_member_limit=20,
        # Yangi guruhga Telegramdagi «A'zo qo'shish» yetarli; bot havolasi
        # yoki uning invite huquqi shart emas. Eski guruhning manbalari
        # saqlanadi, linkni admin xohlasa alohida yoqishi mumkin.
        count_sources={"link": False, "added_by": True},
        notify_inviter=False,
    )


async def ensure_counter(session: AsyncSession, group_id: int) -> CounterSetting:
    row = await session.get(CounterSetting, group_id)
    if row is None:
        row = safe_counter(group_id)
        session.add(row)
        await session.flush()
    return row


def _int(value: object, lo: int, hi: int) -> int:
    raw = str(value).strip()
    if isinstance(value, bool) or not raw.isascii() or not raw.isdigit() or not lo <= int(raw) <= hi:
        raise ValueError(f"{lo}–{hi} orasida raqam kiriting.")
    return int(raw)


async def edit_counter(session: AsyncSession, group: Group, field: str, value: object,
                       actor_id: int) -> CounterSetting:
    if group.settings is None:
        raise ValueError("Guruh sozlamalari topilmadi.")
    row = await ensure_counter(session, group.id)
    before = {"value": getattr(row, field, None), "group_enabled": group.settings.counter_enabled,
              "dry_run": row.dry_run} if field != "source" else {
                  "value": row.count_sources, "group_enabled": group.settings.counter_enabled,
                  "dry_run": row.dry_run,
              }
    if field in BOOLEANS:
        if not isinstance(value, bool):
            raise ValueError("Yoqish/o'chirish qiymati noto'g'ri.")
        setattr(row, field, value)
        if field == "enabled":
            group.settings.counter_enabled = value
            if value:
                row.dry_run = True
    elif field in NUMBERS:
        number = _int(value, *NUMBERS[field])
        changed_n = field == "required_n" and row.required_n != number
        setattr(row, field, number)
        if changed_n:
            # Talab o'zgarsa eski foydalanuvchilarning saqlangan statusi
            # ham joriy N bilan mos bo'lsin; har guruh alohida yangilanadi.
            await session.execute(update(CounterTotal).where(
                CounterTotal.group_id == group.id,
            ).values(
                is_unlocked=CounterTotal.counted >= row.required_n,
                unlocked_at=case(
                    (CounterTotal.counted >= row.required_n,
                     func.coalesce(CounterTotal.unlocked_at, utcnow())),
                    else_=None,
                ),
            ))
    elif field == "mode":
        if value not in {CounterMode.SOFT, CounterMode.HARD}:
            raise ValueError("Sanoqchi rejimi noto'g'ri.")
        row.mode = str(value)
        if row.mode == CounterMode.HARD:
            row.dry_run = True  # hard faqat alohida jonli tasdiq bilan
    elif field == "source":
        if not isinstance(value, str) or value not in SOURCES:
            raise ValueError("Taklif manbasi noto'g'ri.")
        row.count_sources = {**(row.count_sources or {}), value: not (row.count_sources or {}).get(value, False)}
    else:
        raise ValueError("Sanoqchi sozlamasi mavjud emas.")
    after = {"value": row.count_sources if field == "source" else getattr(row, field),
             "group_enabled": group.settings.counter_enabled, "dry_run": row.dry_run}
    if before != after:
        session.add(ActionLog(
            actor_id=actor_id, action="counter_setting", entity="counter_settings",
            entity_id=group.id, group_id=group.id, before=before, after={"field": field, **after},
        ))
    await session.flush()
    return row


async def paid_for_group(session: AsyncSession, group_id: int, user_id: int) -> bool:
    """Faol pullik tarif qamrab olgan guruhda taklif talabini qo'llama.

    Obuna Seller orqali saqlanadi; oddiy odam ham tarif sotib oladi.
    Faqat pullik/sinov bo'lmagan tarif taklifdan ozod etadi.
    """
    if group_id <= 0 or user_id <= 0:
        return False
    now = utcnow()
    subscriptions = (await session.execute(
        select(Subscription.terms, Tariff.allowed_group_ids, Tariff.allowed_category_ids,
               Tariff.price, Tariff.is_trial)
        .join(Subscription, Subscription.tariff_id == Tariff.id)
        .join(Seller, Seller.id == Subscription.seller_id)
        .where(
            Seller.user_id == user_id, Seller.status == SellerStatus.ACTIVE,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.starts_at <= now, Subscription.expires_at > now,
        )
    )).all()
    if not subscriptions:
        return False
    categories = set((await session.execute(select(Category.id).where(
        Category.group_id == group_id, Category.is_active.is_(True),
    ))).scalars())
    if not categories:
        return False

    def allows(value: object, target: int) -> bool:
        return value is None or (isinstance(value, list)
                                 and (target in value or str(target) in value))

    return any(
        Decimal(str((terms or {}).get("price", price) or 0)) > 0
        and not (terms or {}).get("is_trial", trial)
        and allows((terms or {}).get("allowed_group_ids", groups), group_id) and
        ((terms or {}).get("allowed_category_ids", allowed_categories) is None or
         any(allows((terms or {}).get("allowed_category_ids", allowed_categories),
                    category_id) for category_id in categories))
        for terms, groups, allowed_categories, price, trial in subscriptions
    )


async def reserve_personal_link(session: AsyncSession, group_id: int, user_id: int,
                                actor_id: int) -> tuple[InviteLink, bool, str | None]:
    """API'dan OLDIN bitta DB rezervatsiya. Natija: row, yaratilsinmi, eski URL.

    'pending:' rezervatsiya noaniq qolsa yangi link avtomatik yaratilmaydi;
    admin yoki foydalanuvchi keyin eski noaniq yozuvni qo'lda bekor qiladi.
    """
    group = await session.get(Group, group_id)
    setting = await session.get(CounterSetting, group_id)
    if not (group and group.is_active and group.is_supergroup and group.bot_is_admin
            and (group.bot_rights or {}).get("can_invite_users") and group.settings
            and group.settings.counter_enabled and setting and setting.enabled):
        raise ValueError("Guruh sanoqchisi faol emas yoki botda invite huquqi yo'q.")
    if user_id <= 0:
        raise ValueError("Foydalanuvchi ID noto'g'ri.")
    stmt = select(InviteLink).where(
        InviteLink.group_id == group_id, InviteLink.user_id == user_id,
        InviteLink.is_active.is_(True),
    ).with_for_update()
    current = (await session.execute(stmt)).scalar_one_or_none()
    if current and (current.invite_link.startswith("pending:")
                    or current.join_count < setting.link_member_limit):
        return current, False, None
    previous = current.invite_link if current else None
    if current:
        current.is_active, current.revoked_at = False, utcnow()
        await session.flush()
    try:
        async with session.begin_nested():
            row = InviteLink(group_id=group_id, user_id=user_id,
                             invite_link="pending:" + uuid4().hex,
                             name=f"SB:{group_id}:{user_id}"[:32],
                             join_count=0, is_active=True)
            session.add(row)
            await session.flush()
    except IntegrityError:
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise
        return row, False, None
    session.add(ActionLog(actor_id=actor_id, action="invite_reserve", entity="invite_link",
                          entity_id=row.id, group_id=group_id,
                          after={"user_id": user_id, "replaces": bool(previous)}))
    return row, True, previous


async def finish_personal_link(session: AsyncSession, link_id: int,
                               value: str | None) -> bool:
    row = await session.get(InviteLink, link_id)
    if row is None or not row.is_active or not row.invite_link.startswith("pending:"):
        return False
    if value is None:
        row.is_active, row.revoked_at = False, utcnow()
    elif value.startswith("https://t.me/") and len(value) <= 255:
        row.invite_link = value
    else:
        raise ValueError("Telegram taklif havolasi noto'g'ri.")
    await session.flush()
    return True


async def cancel_personal_link(session: AsyncSession, row: InviteLink,
                               actor_id: int) -> bool:
    changed = await session.execute(update(InviteLink).where(
        InviteLink.id == row.id, InviteLink.is_active.is_(True),
    ).values(is_active=False, revoked_at=utcnow()).returning(InviteLink.id))
    if changed.scalar_one_or_none() is None:
        return False
    session.add(ActionLog(actor_id=actor_id, action="invite_cancel", entity="invite_link",
                          entity_id=row.id, group_id=row.group_id,
                          after={"user_id": row.user_id, "link": "bekor qilindi"}))
    return True


async def total_for(session: AsyncSession, group_id: int, user_id: int) -> int:
    count = await session.get(CounterTotal, (group_id, user_id))
    return max(0, count.counted) if count else 0


async def _total_locked(session: AsyncSession, group_id: int, user_id: int) -> CounterTotal:
    stmt = (select(CounterTotal).where(
        CounterTotal.group_id == group_id, CounterTotal.user_id == user_id,
    ).with_for_update().execution_options(populate_existing=True))
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        try:
            async with session.begin_nested():
                row = CounterTotal(group_id=group_id, user_id=user_id, counted=0)
                session.add(row)
                await session.flush()
        except IntegrityError:
            row = (await session.execute(stmt)).scalar_one()
    return row


async def adjust(session: AsyncSession, *, group_id: int, user_id: int, delta: int,
                 actor_id: int, reason: str) -> int:
    if user_id <= 0 or delta == 0 or not -MAX_MANUAL_ADJUST <= delta <= MAX_MANUAL_ADJUST:
        raise ValueError(f"ID yoki tuzatish qiymati noto'g'ri (1–{MAX_MANUAL_ADJUST}).")
    explanation = clean_text(reason)
    if not explanation or not 3 <= len(explanation) <= 255:
        raise ValueError("Sabab 3–255 belgidan iborat bo'lsin.")
    if await session.get(Group, group_id) is None:
        raise ValueError("Guruh topilmadi.")
    row = await _total_locked(session, group_id, user_id)
    previous = row.counted
    row.counted = max(0, row.counted + delta)
    actual = row.counted - previous
    if actual == 0:
        raise ValueError("Hisob allaqachon 0; kamaytirib bo'lmaydi.")
    row.last_count_at = utcnow()
    required = (await ensure_counter(session, group_id)).required_n
    row.is_unlocked = row.counted >= required
    if row.is_unlocked and row.unlocked_at is None:
        row.unlocked_at = utcnow()
    elif not row.is_unlocked:
        row.unlocked_at = None
    session.add(CounterAudit(group_id=group_id, user_id=user_id, delta=actual,
                             reason=explanation, admin_id=actor_id))
    session.add(ActionLog(actor_id=actor_id, action="counter_adjust", entity="counter_totals",
                          entity_id=user_id, group_id=group_id,
                          before={"counted": previous}, after={"counted": row.counted, "reason": explanation}))
    await session.flush()
    return row.counted


async def reset_count(session: AsyncSession, *, group_id: int, user_id: int,
                      actor_id: int) -> bool:
    """Katta sonlarni ham bitta atomar amalda nolga tushirish va auditlash."""
    if user_id <= 0 or await session.get(Group, group_id) is None:
        raise ValueError("Guruh yoki ID noto'g'ri.")
    row = await _total_locked(session, group_id, user_id)
    if row.counted == 0:
        return False
    previous = row.counted
    required = (await ensure_counter(session, group_id)).required_n
    row.counted, row.is_unlocked = 0, required == 0
    row.unlocked_at = (row.unlocked_at or utcnow()) if row.is_unlocked else None
    row.last_count_at = utcnow()
    session.add(CounterAudit(group_id=group_id, user_id=user_id, delta=-previous,
                             reason="Admin hisobni nolga tushirdi", admin_id=actor_id))
    session.add(ActionLog(actor_id=actor_id, action="counter_adjust", entity="counter_totals",
                          entity_id=user_id, group_id=group_id,
                          before={"counted": previous},
                          after={"counted": 0, "reason": "Admin hisobni nolga tushirdi"}))
    await session.flush()
    return True


async def record_request(session: AsyncSession, *, group_id: int, user_id: int,
                         invite_link: str) -> bool:
    link = (await session.execute(select(InviteLink.id).where(
        InviteLink.group_id == group_id, InviteLink.invite_link == invite_link,
        InviteLink.is_active.is_(True),
    ))).scalar_one_or_none()
    if link is None:
        return False
    row = await session.get(CounterJoinRequest, (group_id, user_id))
    if row is None:
        row = CounterJoinRequest(group_id=group_id, user_id=user_id, invite_link=invite_link,
                                 expires_at=utcnow() + timedelta(days=1))
        session.add(row)
    else:
        row.invite_link, row.expires_at = invite_link, utcnow() + timedelta(days=1)
    await session.flush()
    return True


async def request_link(session: AsyncSession, group_id: int, user_id: int) -> str | None:
    row = await session.get(CounterJoinRequest, (group_id, user_id))
    if row is None:
        return None
    link = row.invite_link if ensure_aware(row.expires_at) > utcnow() else None
    await session.delete(row)
    await session.flush()  # bir sessiyada dublikat event'ga qayta bermaymiz
    return link


async def reserve_join(session: AsyncSession, *, group_id: int, invitee_id: int,
                       inviter_id: int | None, source: str, invite_link: str | None = None,
                       message_id: int | None = None, is_bot: bool = False) -> InviteEvent | None:
    """A'zo bo'lganida bir marta qayd: request yolg'iz sanalmaydi."""
    group = await session.get(Group, group_id)
    setting = await session.get(CounterSetting, group_id)
    if not (group and group.is_active and group.settings and group.settings.counter_enabled
            and setting and setting.enabled):
        return None
    if not inviter_id or inviter_id <= 0 or invitee_id <= 0:
        return None  # manbasiz kirish haqiqiy shaxsiy linkka to'siq bo'lmasin
    if source == InviteSource.ADDED_BY and inviter_id == invitee_id:
        # Odatdagi xizmat xabarida from_user=kirgan odam. Keyinchalik kelgan
        # chat_member.invite_link ni UNIQUE orqali noto'g'ri berkitib qo'ymaymiz.
        return None
    if source == InviteSource.LINK:
        linked = (await session.execute(select(InviteLink.user_id).where(
            InviteLink.group_id == group_id, InviteLink.invite_link == invite_link,
        ))).scalar_one_or_none()
        if linked != inviter_id:
            return None  # faqat bot yaratgan, DB'da egasi bor havola sanaladi
    reason = ("self_invite" if inviter_id == invitee_id else "bot" if is_bot
              else "source_disabled" if source not in SOURCES or not (setting.count_sources or {}).get(source)
              else None)
    try:
        async with session.begin_nested():
            entry = InviteEvent(
                group_id=group_id, inviter_id=inviter_id, invitee_id=invitee_id,
                invite_link=invite_link, source=source, message_id=message_id,
                counted=False, reject_reason=reason,
            )
            session.add(entry)
            await session.flush()
    except IntegrityError:
        # Xizmat xabaridan keyin kelgan Telegram chat_member'ning linki
        # kuchliroq dalil; sanalmagan fallbackni egasiga qayta bog'laymiz.
        if source == InviteSource.LINK:
            previous = (await session.execute(select(InviteEvent).where(
                InviteEvent.group_id == group_id, InviteEvent.invitee_id == invitee_id,
            ).with_for_update())).scalar_one_or_none()
            if previous and not previous.counted and previous.source == InviteSource.ADDED_BY:
                previous.inviter_id = inviter_id
                previous.source = InviteSource.LINK
                previous.invite_link = invite_link
                previous.reject_reason = reason
                await session.flush()
                if invite_link:
                    await session.execute(update(InviteLink).where(
                        InviteLink.group_id == group_id, InviteLink.invite_link == invite_link,
                    ).values(join_count=InviteLink.join_count + 1))
                return previous
        return None
    if source == InviteSource.LINK and invite_link:
        await session.execute(update(InviteLink).where(
            InviteLink.group_id == group_id, InviteLink.invite_link == invite_link,
        ).values(join_count=InviteLink.join_count + 1))
    return entry


async def reject_unattributed_direct(session: AsyncSession, *, group_id: int,
                                     invitee_id: int) -> bool:
    """Join request/folder a'zosining oldingi xizmat xabari admini sanalmasin."""
    result = await session.execute(update(InviteEvent).where(
        InviteEvent.group_id == group_id, InviteEvent.invitee_id == invitee_id,
        InviteEvent.source == InviteSource.ADDED_BY, InviteEvent.counted.is_(False),
        or_(InviteEvent.reject_reason.is_(None), InviteEvent.reject_reason == "checking"),
    ).values(reject_reason="unattributed_join").returning(InviteEvent.id))
    return result.scalar_one_or_none() is not None


async def abandon_early(session: AsyncSession, *, group_id: int, invitee_id: int) -> bool:
    result = await session.execute(update(InviteEvent).where(
        InviteEvent.group_id == group_id, InviteEvent.invitee_id == invitee_id,
        InviteEvent.counted.is_(False),
        or_(InviteEvent.reject_reason.is_(None), InviteEvent.reject_reason == "checking"),
    ).values(reject_reason="left_early").returning(InviteEvent.id))
    return result.scalar_one_or_none() is not None


async def claim_due(*, limit: int = 100) -> list[int]:
    """Ikkita poster worker bitta nomzodni qayta tekshirmaydi (CAS)."""
    from app.db.base import session_scope

    now = utcnow()
    stale = now - timedelta(minutes=5)
    # Eski 'checking' worker yiqilgan bo'lsa 5 daqiqadan keyin qayta
    # tekshiriladi. Bu faqat getChatMember O'QISH; credit DB'da idempotent.
    available = or_(InviteEvent.reject_reason.is_(None),
                    (InviteEvent.reject_reason == "checking") & (InviteEvent.updated_at < stale))
    async with session_scope() as session:
        claimed: list[int] = []
        last_id = 0
        while len(claimed) < limit:
            # Keyset pagination: 400 ta hali muddati yetmagan eski event
            # 1 ta tayyorroq yangi eventni abadiy berkitib qo'ymasin.
            due = (await session.execute(select(InviteEvent.id).where(
                InviteEvent.id > last_id, InviteEvent.counted.is_(False), available,
                InviteEvent.updated_at <= now - timedelta(seconds=30),
            ).order_by(InviteEvent.id).limit(limit * 4))).scalars().all()
            if not due:
                break
            last_id = due[-1]
            for entry_id in due:
                row = await session.get(InviteEvent, entry_id)
                if row is None:
                    continue
                setting = await session.get(CounterSetting, row.group_id)
                if setting is None or ensure_aware(row.created_at) + timedelta(
                    minutes=setting.min_stay_minutes,
                ) > now:
                    continue
                changed = await session.execute(update(InviteEvent).where(
                    InviteEvent.id == entry_id, InviteEvent.counted.is_(False), available,
                ).values(reject_reason="checking", updated_at=now).returning(InviteEvent.id))
                if changed.scalar_one_or_none() is not None:
                    claimed.append(entry_id)
                    if len(claimed) >= limit:
                        break
    return claimed


async def retry_check(session: AsyncSession, entry: InviteEvent) -> None:
    """Telegram holati noma'lum: qaror bermay qayta tekshirishga qo'yamiz."""
    if entry.reject_reason == "checking" and not entry.counted:
        entry.reject_reason = None
        entry.updated_at = utcnow()


async def credit_join(session: AsyncSession, entry_id: int, *, still_member: bool) -> int | None:
    """A'zolik tekshiruvidan keyin aynan bir marta qo'shish; 0 = rad etildi."""
    stmt = (select(InviteEvent).where(InviteEvent.id == entry_id).with_for_update()
            .execution_options(populate_existing=True))
    event = (await session.execute(stmt)).scalar_one_or_none()
    if event is None or event.counted or event.reject_reason != "checking":
        return None
    if not still_member:
        event.reject_reason = "left_early"
        return 0
    if not event.inviter_id or event.inviter_id <= 0 or event.inviter_id == event.invitee_id:
        event.reject_reason = "invalid_inviter"
        return 0
    group = await session.get(Group, event.group_id)
    setting = await session.get(CounterSetting, event.group_id)
    if not (group and setting):
        event.reject_reason = "group_missing"
        return 0
    if not (group.is_active and group.settings and group.settings.counter_enabled and setting.enabled):
        event.reject_reason = None  # pauza yangi kreditni to'sadi, mavjud navbatni yo'qotmaydi
        event.updated_at = utcnow()
        return None
    if event.source not in SOURCES or not (setting.count_sources or {}).get(event.source):
        event.reject_reason = "source_disabled"
        return 0
    now = utcnow()
    if ensure_aware(event.created_at) + timedelta(minutes=setting.min_stay_minutes) > now:
        event.reject_reason = None
        return None
    owner = await _total_locked(session, event.group_id, event.inviter_id)
    # N har guruhda tarixiy haqiqiy a'zolar bo'yicha; kunlik kvota yo'q.
    owner.counted += 1
    owner.last_count_at = now
    owner.is_unlocked = owner.counted >= setting.required_n
    if owner.is_unlocked and owner.unlocked_at is None:
        owner.unlocked_at = now
    event.counted = True
    event.reject_reason = None
    event.updated_at = now
    await session.flush()
    return owner.counted


async def recent_invites(session: AsyncSession, group_id: int, *, limit: int = 10) -> list[InviteEvent]:
    return list((await session.execute(select(InviteEvent).where(
        InviteEvent.group_id == group_id,
    ).order_by(InviteEvent.id.desc()).limit(limit))).scalars())


async def counter_exempt(session: AsyncSession, group_id: int, user_id: int) -> bool:
    kinds = await permission_kinds(session, user_id, group_id)
    return PermissionKind.COUNTER_EXEMPT in kinds or PermissionKind.FULL_EXEMPT in kinds


__all__ = [
    "safe_counter", "ensure_counter", "edit_counter", "paid_for_group", "reserve_personal_link", "finish_personal_link",
    "cancel_personal_link", "total_for", "adjust", "reset_count", "record_request", "request_link",
    "reserve_join", "reject_unattributed_direct", "abandon_early", "claim_due", "retry_check", "credit_join",
    "recent_invites", "counter_exempt",
]
