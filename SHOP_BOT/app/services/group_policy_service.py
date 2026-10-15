"""Phase 6: har guruhning mustaqil posbon/tozalovchi/ruxsat siyosati.

Telegram API bu yerda yo'q. Qoidalar bazada saqlanadi, xabar uchun qaror bittadan
ortiq yozilmaydi; noma'lum API natijasi avtomatik takrorlanmaydi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from aiogram.enums import ContentType
from aiogram.types import Message
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import Penalty, PermissionKind
from app.db.models import (
    ActionLog,
    CleanerSetting,
    Group,
    GroupMessageAction,
    GuardSetting,
    Permission,
    Violation,
    Warning,
)
from app.utils.text import clean_text
from app.utils.time import ensure_aware, utcnow

GUARD_BOOLEANS = frozenset({
    "enabled", "dry_run", "link_filter", "forward_filter", "mention_filter", "exemption_for_admins"
})
CLEANER_BOOLEANS = frozenset({
    "enabled", "dry_run", "delete_join_leave", "delete_service", "delete_links",
    "delete_violations", "delete_old_ads", "keep_pinned",
})
PERMISSION_KINDS = frozenset(item.value for item in PermissionKind)
_LINK_RE = re.compile(r"(?i)(?:https?://|tg://|www\.|t\.me/)[^\s<>]+")
_MENTION_RE = re.compile(r"(?<![\w@])@[a-zA-Z0-9_]{5,32}\b")
_MENTION_TYPES = frozenset({"mention", "text_mention"})
_SERVICE_TYPES = frozenset({
    ContentType.NEW_CHAT_TITLE, ContentType.NEW_CHAT_PHOTO, ContentType.DELETE_CHAT_PHOTO,
    ContentType.PINNED_MESSAGE, ContentType.MESSAGE_AUTO_DELETE_TIMER_CHANGED,
    ContentType.VIDEO_CHAT_SCHEDULED, ContentType.VIDEO_CHAT_STARTED,
    ContentType.VIDEO_CHAT_ENDED, ContentType.VIDEO_CHAT_PARTICIPANTS_INVITED,
    ContentType.FORUM_TOPIC_CREATED, ContentType.FORUM_TOPIC_EDITED,
    ContentType.FORUM_TOPIC_CLOSED, ContentType.FORUM_TOPIC_REOPENED,
    ContentType.GENERAL_FORUM_TOPIC_HIDDEN, ContentType.GENERAL_FORUM_TOPIC_UNHIDDEN,
    ContentType.CHAT_BACKGROUND_SET, ContentType.BOOST_ADDED,
})


@dataclass(frozen=True)
class Match:
    source: str  # guard | cleaner
    kind: str    # link | forward | mention | banned_word | join_leave | service


def safe_guard(group_id: int) -> GuardSetting:
    """Yangi guruhda hech qanday jazo avtomatik ishlamaydi."""
    return GuardSetting(
        group_id=group_id, enabled=False, dry_run=True, link_filter=True,
        forward_filter=False, mention_filter=False, banned_words=[], allowed_domains=[],
        penalty=Penalty.WARN, mute_minutes=10, warn_limit=3,
        escalate={"warn_window_hours": 24}, exemption_for_admins=True,
        require_subscription=False, require_counter=False,
    )


def safe_cleaner(group_id: int) -> CleanerSetting:
    return CleanerSetting(
        group_id=group_id, enabled=False, dry_run=True, delete_join_leave=False,
        delete_service=False, delete_links=False, delete_violations=False,
        delete_old_ads=False, keep_last_ads=1, delete_after_seconds=0,
        keep_pinned=True, is_hard_delete=True,
    )


async def ensure_guard(session: AsyncSession, group_id: int) -> GuardSetting:
    policy = await session.get(GuardSetting, group_id)
    if policy is None:
        policy = safe_guard(group_id)
        session.add(policy)
        await session.flush()
    return policy


async def ensure_cleaner(session: AsyncSession, group_id: int) -> CleanerSetting:
    policy = await session.get(CleanerSetting, group_id)
    if policy is None:
        policy = safe_cleaner(group_id)
        session.add(policy)
        await session.flush()
    return policy


def _number(value: object, low: int, high: int) -> int:
    if isinstance(value, bool) or not str(value).strip().isascii() or not str(value).strip().isdigit():
        raise ValueError(f"{low}–{high} orasida raqam kiriting.")
    number = int(str(value).strip())
    if not low <= number <= high:
        raise ValueError(f"{low}–{high} orasida raqam kiriting.")
    return number


def parse_domains(value: str) -> list[str]:
    """Aniq domen + subdomen uchun ruxsat; `evil-example.com` o'xshash emas."""
    raw = [token.strip().lower() for token in re.split(r"[\s,;]+", value) if token.strip()]
    if len(raw) > 30:
        raise ValueError("Ko'pi bilan 30 ta domen kiriting.")
    result: list[str] = []
    for token in raw:
        if token.startswith("*."):
            token = token[2:]
        try:
            host = urlsplit("https://" + token).hostname
            if not host or token != host or len(host) > 253:
                raise ValueError
            host = host.encode("idna").decode("ascii")
            if not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host):
                raise ValueError
        except (ValueError, UnicodeError):
            raise ValueError("Domenlarni faqat `example.uz` ko'rinishida kiriting.") from None
        if host not in result:
            result.append(host)
    return result


def parse_words(value: str) -> list[str]:
    raw = [clean_text(word) for word in re.split(r"[,\n;]+", value)]
    words = [word.casefold() for word in raw if word]
    if len(words) > 30 or any(not 2 <= len(word) <= 50 for word in words):
        raise ValueError("2–50 belgili, ko'pi bilan 30 ta so'z/ibora kiriting.")
    return list(dict.fromkeys(words))


async def edit_guard(
    session: AsyncSession, group: Group, field: str, value: object, actor_id: int,
) -> GuardSetting:
    if group.settings is None:
        raise ValueError("Guruh sozlamalari topilmadi.")
    policy = await ensure_guard(session, group.id)
    before_gate = {"group_enabled": group.settings.guard_enabled, "dry_run": policy.dry_run}
    if field in GUARD_BOOLEANS:
        if not isinstance(value, bool):
            raise ValueError("Yoqish/o'chirish qiymati noto'g'ri.")
        before: object = bool(getattr(policy, field))
        setattr(policy, field, value)
        if field == "enabled":
            group.settings.guard_enabled = value
            if value:
                policy.dry_run = True  # tezkor yoqish hech qachon darhol jazo bermasin
    elif field in {"warn_limit", "mute_minutes"}:
        before = getattr(policy, field)
        setattr(policy, field, _number(value, 1, 20 if field == "warn_limit" else 10080))
    elif field == "warn_window_hours":
        before = int((policy.escalate or {}).get("warn_window_hours", 24))
        policy.escalate = {**(policy.escalate or {}), "warn_window_hours": _number(value, 1, 720)}
    elif field == "penalty":
        if value not in (Penalty.WARN, Penalty.MUTE, Penalty.BAN):
            raise ValueError("Jazo turi noto'g'ri.")
        before = policy.penalty
        policy.penalty = str(value)
    elif field == "allowed_domains":
        before = policy.allowed_domains or []
        policy.allowed_domains = parse_domains(str(value))
    elif field == "banned_words":
        before = policy.banned_words or []
        policy.banned_words = parse_words(str(value))
    else:
        # require_subscription/counter faqat Phase 7 tekshiruvi tayyor bo'lganda yoqiladi.
        raise ValueError("Bu sozlama hozircha mavjud emas (majburiy kanal/sanoqchi — Phase 7).")
    after = getattr(policy, field) if field != "warn_window_hours" else policy.escalate["warn_window_hours"]
    before_values, after_values = {field: before}, {field: after}
    if field == "enabled":
        before_values.update(before_gate)
        after_values.update(group_enabled=group.settings.guard_enabled, dry_run=policy.dry_run)
    if before_values != after_values:
        session.add(ActionLog(
            actor_id=actor_id, action="guard_setting", entity="guard_settings", entity_id=group.id,
            group_id=group.id, before=before_values, after=after_values,
        ))
    await session.flush()
    return policy


async def edit_cleaner(
    session: AsyncSession, group: Group, field: str, value: object, actor_id: int,
) -> CleanerSetting:
    if group.settings is None:
        raise ValueError("Guruh sozlamalari topilmadi.")
    policy = await ensure_cleaner(session, group.id)
    before_gate = {"group_enabled": group.settings.cleaner_enabled, "dry_run": policy.dry_run}
    if field in CLEANER_BOOLEANS:
        if not isinstance(value, bool):
            raise ValueError("Yoqish/o'chirish qiymati noto'g'ri.")
        before: object = bool(getattr(policy, field))
        setattr(policy, field, value)
        if field == "enabled":
            group.settings.cleaner_enabled = value
            if value:
                policy.dry_run = True
    elif field in {"keep_last_ads", "delete_after_seconds"}:
        before = getattr(policy, field)
        setattr(policy, field, _number(value, 1, 20) if field == "keep_last_ads" else _number(value, 0, 3600))
    else:
        raise ValueError("Bu tozalovchi sozlamasi mavjud emas.")
    after = getattr(policy, field)
    before_values, after_values = {field: before}, {field: after}
    if field == "enabled":
        before_values.update(before_gate)
        after_values.update(group_enabled=group.settings.cleaner_enabled, dry_run=policy.dry_run)
    if before_values != after_values:
        session.add(ActionLog(
            actor_id=actor_id, action="cleaner_setting", entity="cleaner_settings", entity_id=group.id,
            group_id=group.id, before=before_values, after=after_values,
        ))
    await session.flush()
    return policy


async def grant_permission(
    session: AsyncSession, *, group_id: int | None, user_id: int, kind: str,
    days: int | None, reason: str, actor_id: int,
) -> Permission:
    if user_id <= 0 or kind not in PERMISSION_KINDS:
        raise ValueError("Foydalanuvchi ID yoki ruxsat turi noto'g'ri.")
    if days is not None:
        days = _number(days, 1, 365)
    explanation = clean_text(reason)
    if not explanation or not 3 <= len(explanation) <= 255:
        raise ValueError("Sabab 3–255 ta belgi bo'lsin.")
    if group_id is not None and await session.get(Group, group_id) is None:
        raise ValueError("Guruh topilmadi.")
    now = utcnow()
    expiry = now + timedelta(days=days) if days else None
    # Muddati o'tgan ruxsatni tarixda qoldiramiz; bitta aktiv scope/kind unique.
    stmt = select(Permission).where(
        Permission.user_id == user_id, Permission.kind == kind, Permission.is_active.is_(True),
        Permission.group_id == group_id if group_id is not None else Permission.group_id.is_(None),
    ).order_by(Permission.id.desc()).with_for_update()
    rows = (await session.execute(stmt)).scalars().all()
    valid = [row for row in rows if row.expires_at is None or ensure_aware(row.expires_at) > now]
    for old in rows:
        if old not in valid or (valid and old.id != valid[0].id):
            old.is_active = False
    existing = valid[0] if valid else None
    if existing is None:
        # Ikkita admin parallel bosganida unique indeks faqat bittasini qo'yadi.
        try:
            async with session.begin_nested():
                permission = Permission(
                    user_id=user_id, group_id=group_id, kind=kind, reason=explanation,
                    granted_by=actor_id, expires_at=expiry, is_active=True,
                )
                session.add(permission)
                await session.flush()
            before = None
        except IntegrityError:
            existing = (await session.execute(stmt)).scalars().first()
            if existing is None:
                raise
    if existing is not None:
        before = {"reason": existing.reason, "expires_at": existing.expires_at.isoformat() if existing.expires_at else None}
        existing.reason, existing.expires_at, existing.granted_by = explanation, expiry, actor_id
        permission = existing
    await session.flush()
    session.add(ActionLog(
        actor_id=actor_id, action="permission_grant", entity="permission", entity_id=permission.id,
        group_id=group_id,
        before=before,
        after={"user_id": user_id, "kind": kind, "expires_at": expiry.isoformat() if expiry else None},
    ))
    return permission


async def revoke_permission(session: AsyncSession, permission: Permission, actor_id: int) -> bool:
    # Parallel adminlar faqat bittadan muvaffaqiyatli bekor qilsin/audit yozsin.
    changed = await session.execute(update(Permission).where(
        Permission.id == permission.id, Permission.is_active.is_(True),
    ).values(is_active=False).returning(Permission.id))
    if changed.scalar_one_or_none() is None:
        return False
    session.add(ActionLog(
        actor_id=actor_id, action="permission_revoke", entity="permission", entity_id=permission.id,
        group_id=permission.group_id, before={"active": True}, after={"active": False},
    ))
    await session.flush()
    return True


async def permission_kinds(session: AsyncSession, user_id: int, group_id: int) -> frozenset[str]:
    if user_id <= 0:
        return frozenset()
    rows = (await session.execute(select(Permission.kind).where(
        Permission.user_id == user_id, Permission.is_active.is_(True),
        or_(Permission.group_id == group_id, Permission.group_id.is_(None)),
        or_(Permission.expires_at.is_(None), Permission.expires_at > utcnow()),
    ))).scalars().all()
    return frozenset(rows)


async def list_permissions(session: AsyncSession, group_id: int | None, *, limit: int = 100) -> list[Permission]:
    stmt = select(Permission).where(
        Permission.is_active.is_(True),
        or_(Permission.expires_at.is_(None), Permission.expires_at > utcnow()),
        Permission.group_id == group_id if group_id is not None else Permission.group_id.is_(None),
    ).order_by(Permission.id.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars())


def _domain(url: str) -> str | None:
    try:
        candidate = url if "://" in url else "https://" + url
        hostname = urlsplit(candidate.rstrip(".,!?)]}")).hostname
        return hostname.encode("idna").decode("ascii") if hostname else None
    except (ValueError, UnicodeError):
        return None


def _allowed(url: str, domains: list[str]) -> bool:
    host = _domain(url)
    if not host:
        return False
    return any(host.lower() == domain or host.lower().endswith("." + domain) for domain in domains)


def _urls(message: Message) -> list[str]:
    text = "\n".join(filter(None, (message.text, message.caption)))
    urls = [match.group() for match in _LINK_RE.finditer(text)]
    for entity in (*(message.entities or ()), *(message.caption_entities or ())):
        if str(entity.type) == "text_link" and entity.url:
            urls.append(entity.url)
        # Oddiy URL matnda ham bor; Telegram offset UTF-16 bo'lishi mumkin,
        # Python satrini shu offset bilan kesish emoji bor matnda xato qiladi.
    return urls


def _violation(message: Message, guard: GuardSetting) -> str | None:
    text = "\n".join(filter(None, (message.text, message.caption)))
    if guard.banned_words:
        for word in guard.banned_words:
            if re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text, flags=re.IGNORECASE):
                return "banned_word"
    if guard.forward_filter and (message.forward_origin is not None or message.is_automatic_forward):
        return "forward"
    if guard.mention_filter and (
        _MENTION_RE.search(text) or any(str(e.type) in _MENTION_TYPES for e in
                                       (*(message.entities or ()), *(message.caption_entities or ())))
    ):
        return "mention"
    if guard.link_filter and any(not _allowed(url, guard.allowed_domains or []) for url in _urls(message)):
        return "link"
    return None


def classify(
    message: Message, guard: GuardSetting | None, cleaner: CleanerSetting | None,
    permissions: frozenset[str] = frozenset(), *, violation_guard: GuardSetting | None = None,
) -> Match | None:
    """Bitta xabarga bitta amal; cleaner o'zicha guard filtrlaridan foydalana oladi.

    `guard` faqat ishga tushirilgan posbon; `violation_guard` cleanerning alohida
    sozlangan qoidabuzar-xabar filtri uchun namuna (guard o'chgan bo'lsa ham).
    """
    if PermissionKind.FULL_EXEMPT in permissions:
        return None
    guard_ok = guard is not None and guard.enabled and PermissionKind.GUARD_EXEMPT not in permissions
    cleaner_ok = cleaner is not None and cleaner.enabled and PermissionKind.CLEANER_EXEMPT not in permissions
    reference = violation_guard or guard
    if cleaner_ok:
        if cleaner.delete_join_leave and (message.new_chat_members or message.left_chat_member):
            return Match("cleaner", "join_leave")
        if cleaner.delete_service and message.content_type in _SERVICE_TYPES:
            return Match("cleaner", "service")
    if guard_ok:
        violation = _violation(message, guard)
        if violation == "link" and PermissionKind.LINK_ALLOWED in permissions:
            violation = None
        if violation:
            return Match("guard", violation)
    if cleaner_ok:
        if cleaner.delete_violations and reference is not None:
            kind = _violation(message, reference)
            if kind and not (kind == "link" and PermissionKind.LINK_ALLOWED in permissions):
                return Match("cleaner", kind)
        if cleaner.delete_links and PermissionKind.LINK_ALLOWED not in permissions:
            domains = reference.allowed_domains or [] if reference else []
            if any(not _allowed(url, domains) for url in _urls(message)):
                return Match("cleaner", "link")
    return None


async def reserve_action(
    session: AsyncSession, *, group_id: int, message_id: int, user_id: int | None,
    match: Match, dry_run: bool, due_at: datetime | None = None,
    text_excerpt: str | None = None,
) -> GroupMessageAction | None:
    """UNIQUE(group_id,message_id) ikkita worker/yetkazilgan dublikatni bloklaydi."""
    try:
        async with session.begin_nested():
            action = GroupMessageAction(
                group_id=group_id, message_id=message_id, user_id=user_id,
                source=match.source, kind=match.kind,
                planned_action="log" if dry_run else "delete",
                status="done" if dry_run else "pending" if due_at else "running",
                due_at=due_at, is_dry_run=dry_run,
            )
            session.add(action)
            await session.flush()
    except IntegrityError:
        return None
    if match.source == "guard":
        session.add(Violation(
            group_id=group_id, user_id=user_id or 0, message_id=message_id,
            kind=match.kind, text_excerpt=clean_text(text_excerpt, limit=100),
            action="logged", is_dry_run=dry_run,
        ))
    await session.flush()
    return action


async def increment_warning(
    session: AsyncSession, *, group_id: int, user_id: int, window_hours: int,
) -> int:
    """Bitta sotuvchi uchun ogohlantirish sonini atomar oshirish (PG + SQLite)."""
    now = utcnow()
    cutoff = now - timedelta(hours=window_hours)
    stmt = update(Warning).where(Warning.group_id == group_id, Warning.user_id == user_id).values(
        count=case((Warning.last_at >= cutoff, Warning.count + 1), else_=1), last_at=now
    ).returning(Warning.count)
    count = (await session.execute(stmt)).scalar_one_or_none()
    if count is not None:
        return int(count)
    try:
        async with session.begin_nested():
            session.add(Warning(group_id=group_id, user_id=user_id, count=1, last_at=now))
            await session.flush()
        return 1
    except IntegrityError:
        return int((await session.execute(stmt)).scalar_one())


def consequence_values(penalty: str, warn_limit: int, count: int) -> str:
    """Ban faqat guruh admini BAN rejimini qo'lda tasdiqlaganidan so'ng."""
    limit = max(1, int(warn_limit or 3))
    if penalty == Penalty.BAN and count >= limit * 2:
        return "ban"
    if penalty in (Penalty.MUTE, Penalty.BAN) and count >= limit:
        return "mute"
    return "warn"


def consequence(policy: GuardSetting, count: int) -> str:
    return consequence_values(policy.penalty, policy.warn_limit, count)


async def recent_actions(session: AsyncSession, group_id: int, *, limit: int = 8) -> list[GroupMessageAction]:
    return list((await session.execute(select(GroupMessageAction).where(
        GroupMessageAction.group_id == group_id
    ).order_by(GroupMessageAction.id.desc()).limit(limit))).scalars())


async def action_totals(session: AsyncSession, group_id: int) -> dict[str, int]:
    rows = (await session.execute(select(GroupMessageAction.status, func.count()).where(
        GroupMessageAction.group_id == group_id
    ).group_by(GroupMessageAction.status))).all()
    return dict(rows)
