"""
core/audit_log.py — har bir muhim amal yoziladigan audit logger.

MAQSAD:
───────
Tizimda nima sodir boʻlayotganini aniq kuzatish:
- Tenant qachon yaratildi/bloklandi?
- Kim foydalanuvchini tasdiqladi?
- Eʼlon kim tomonidan oʻchirildi?
- Toʻlov qachon kelib tushdi?

Bu — ishonch va xavfsizlik (security audit) uchun majburiy.

DARAJALAR (level):
──────────────────
- info     — odatiy amal (post yaratish, tasdiqlash)
- warn     — diqqat talab qiladi (limit yaqinlashdi, koʻp xato)
- error    — xato sodir boʻldi (DB error, API fail)
- critical — favqulodda holat (super admin block, sessiya yaroqsiz)

USAGE:
──────
    await audit.log_action(
        actor=ctx,                # RoleContext
        action=Action.CREATE_OWN_POST,
        target_type="announcement",
        target_id=post_id,
        details={"channel_id": -1001, "plugin": "taxi"},
    )

Yozilgan eslatma DB'da `audit_log` jadvalida saqlanadi va keyinchalik
super admin yoki tenant tomonidan koʻrib chiqilishi mumkin.
"""

from __future__ import annotations

import logging
from typing import Any

from core import database as db
from core.permissions import RoleContext

logger = logging.getLogger("enginebot.audit")


# ─────────────────────────────────────────────────────────────────────
# Asosiy log funksiyasi
# ─────────────────────────────────────────────────────────────────────
async def log_action(
    actor: RoleContext | None = None,
    *,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    details: dict[str, Any] | None = None,
    level: str = "info",
    actor_role: str | None = None,
    actor_id: int | None = None,
    tenant_id: int | None = None,
) -> None:
    """
    Audit yozuvi qoʻshish.

    Ikki rejim bor:
    1. RoleContext bilan: `log_action(actor=ctx, action=..., ...)`
    2. Qoʻlda: `log_action(actor_role="system", actor_id=0, action=...)`

    Tizim tomonidan generatsiya qilingan amallar uchun (scheduler,
    cleaner) actor_role="system", actor_id=0 ishlatiladi.
    """
    if actor is not None:
        actor_role = actor.role
        actor_id = actor.user_id
        if tenant_id is None:
            tenant_id = actor.tenant_id

    if actor_role is None or actor_id is None:
        logger.warning(f"audit.log_action: actor noma'lum, action={action!r}")
        actor_role = actor_role or "unknown"
        actor_id = actor_id or 0

    try:
        await db.write_audit(
            actor_role=actor_role,
            actor_id=actor_id,
            action=action,
            tenant_id=tenant_id,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
            level=level,
        )
    except Exception as e:
        # Audit yozuvi xato boʻlsa — applikatsiyani toʻxtatma,
        # faqat lokal log'ga yozib qoʻy. Audit xatosi business
        # logic'ni buzmasligi kerak.
        logger.error(
            f"audit.log_action FAILED: action={action} actor={actor_id} err={type(e).__name__}: {e}"
        )

    # Console/fayl log'ga ham parallel yozamiz — tezkor diagnostika uchun
    log_level = {
        "warn": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }.get(level, logging.INFO)
    logger.log(
        log_level,
        f"[{actor_role}#{actor_id}] {action} "
        f"tenant={tenant_id} target={target_type}#{target_id} {details or ''}",
    )


# ─────────────────────────────────────────────────────────────────────
# Tezkor yordamchilar (eng koʻp uchraydigan amallar uchun)
# ─────────────────────────────────────────────────────────────────────
async def log_tenant_event(
    actor: RoleContext, action: str, tenant_id: int, **details
) -> None:
    """Tenant'ga tegishli amalni yozish."""
    await log_action(
        actor=actor,
        action=action,
        tenant_id=tenant_id,
        target_type="tenant",
        target_id=tenant_id,
        details=details,
    )


async def log_user_event(
    actor: RoleContext, action: str, target_user_id: int, **details
) -> None:
    """Foydalanuvchi haqidagi amalni yozish."""
    await log_action(
        actor=actor,
        action=action,
        target_type="user",
        target_id=target_user_id,
        details=details,
    )


async def log_post_event(
    actor: RoleContext, action: str, post_id: int, **details
) -> None:
    """Eʼlon haqidagi amalni yozish."""
    await log_action(
        actor=actor,
        action=action,
        target_type="announcement",
        target_id=post_id,
        details=details,
    )


async def log_security_event(
    actor: RoleContext | None,
    action: str,
    *,
    actor_id: int | None = None,
    tenant_id: int | None = None,
    **details,
) -> None:
    """Xavfsizlik hodisasi (warn/error darajada)."""
    await log_action(
        actor=actor,
        action=action,
        actor_id=actor_id,
        actor_role=("system" if actor is None and actor_id is None else None),
        tenant_id=tenant_id,
        details=details,
        level="warn",
    )


async def log_system_event(
    action: str,
    *,
    tenant_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    level: str = "info",
    **details,
) -> None:
    """
    Tizim hodisasi (scheduler, cleaner, billing checker — odam emas).

    actor_role="system", actor_id=0 belgilanadi.
    """
    await log_action(
        actor_role="system",
        actor_id=0,
        action=action,
        tenant_id=tenant_id,
        target_type=target_type,
        target_id=target_id,
        details=details,
        level=level,
    )


# ─────────────────────────────────────────────────────────────────────
# Audit oʻqish (super admin va tenant uchun)
# ─────────────────────────────────────────────────────────────────────
async def get_global_audit(limit: int = 100, offset: int = 0) -> list[dict]:
    """Global audit log (faqat super admin uchun)."""
    return await db.list_audit(limit=limit, offset=offset)


async def get_tenant_audit(tenant_id: int, limit: int = 100, offset: int = 0) -> list[dict]:
    """Tenant audit log (faqat oʻz guruhi)."""
    return await db.list_audit(tenant_id=tenant_id, limit=limit, offset=offset)


async def get_user_audit(actor_id: int, limit: int = 50) -> list[dict]:
    """Maʼlum bir foydalanuvchining amallari (oxirgi N ta)."""
    return await db.list_audit(actor_id=actor_id, limit=limit)


# ─────────────────────────────────────────────────────────────────────
# Standart action nomlari (consistency uchun)
# ─────────────────────────────────────────────────────────────────────
class Actions:
    """Tez-tez ishlatiladigan action stringlari (typo'larni oldini olish)."""

    # Tenant
    TENANT_CREATED = "tenant_created"
    TENANT_APPROVED = "tenant_approved"
    TENANT_BLOCKED = "tenant_blocked"
    TENANT_UNBLOCKED = "tenant_unblocked"
    TENANT_DELETED = "tenant_deleted"
    TENANT_PAUSED = "tenant_paused"
    TENANT_TARIFF_CHANGED = "tenant_tariff_changed"

    # Channel
    CHANNEL_ADDED = "channel_added"
    CHANNEL_REMOVED = "channel_removed"

    # User
    USER_REGISTERED = "user_registered"
    USER_APPROVED = "user_approved"
    USER_BLOCKED = "user_blocked"
    USER_WARNED = "user_warned"
    USER_DELETED = "user_deleted"
    USER_LOGGED_OUT = "user_logged_out"

    # Moderator
    MODERATOR_APPOINTED = "moderator_appointed"
    MODERATOR_REMOVED = "moderator_removed"

    # Announcement
    POST_CREATED = "post_created"
    POST_PUBLISHED = "post_published"
    POST_EDITED = "post_edited"
    POST_DELETED = "post_deleted"
    POST_PAUSED = "post_paused"
    POST_RESUMED = "post_resumed"
    POST_EXPIRED = "post_expired"
    POST_ROTATED = "post_rotated"

    # Settings
    ROTATION_TOGGLED = "rotation_toggled"
    INTERVAL_CHANGED = "interval_changed"
    SCHEDULE_CHANGED = "schedule_changed"
    BOT_TOGGLED = "bot_toggled"
    POST_INTAKE_TOGGLED = "post_intake_toggled"

    # Payment
    PAYMENT_RECEIVED = "payment_received"
    PAYMENT_OVERDUE = "payment_overdue"

    # Security
    PERMISSION_DENIED = "permission_denied"
    RATE_LIMIT_HIT = "rate_limit_hit"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"

    # System
    SERVICE_STARTED = "service_started"
    SERVICE_STOPPED = "service_stopped"
    SERVICE_CRASHED = "service_crashed"
    DB_BACKUP_CREATED = "db_backup_created"
