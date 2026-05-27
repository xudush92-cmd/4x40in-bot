"""
core/tenant_manager.py — tenant lifecycle va aktivlik nazorati.

ROLI:
─────
Tenant (kanal egasi) holatini boshqaradi:
- Yangi tenant yaratish va trial sinov boshlash
- Toʻlov qabul qilish va muddat uzaytirish
- Muddat tugaganda PAUSE rejimiga oʻtkazish
- Bloklash/qaytadan aktivlashtirish
- Aktiv tenantlar roʻyxati (services uchun)

QOIDALAR:
─────────
- Bitta tenant_id = bitta Telegram user ID (kanal egasi).
- Tenant `paused` boʻlsa: eʼlonlar saqlanadi, lekin yangi qabul
  qilinmaydi va aylanish toʻxtaydi.
- Tenant `blocked` boʻlsa: hech qanday xizmat ishlamaydi.
- `is_operational(tenant)`: bot faol va toʻlov muddati tugamagan.

EVENT EMIT:
───────────
Har tenant holati oʻzgarganda event chiqadi (event_bus orqali):
- TENANT_CREATED, TENANT_APPROVED, TENANT_BLOCKED
- TENANT_PAYMENT_RECEIVED, TENANT_PAYMENT_OVERDUE
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from config import (
    DEFAULT_TZ_OFFSET,
    Tariff,
    TenantStatus,
    TARIFF_LIMITS,
    BILLING_REMINDER_DAYS,
)
from core import audit_log, database as db, notifier
from core.event_bus import Events, bus

logger = logging.getLogger("enginebot.tenant_manager")


# ─────────────────────────────────────────────────────────────────────
# Tenant yaratish va trial boshlash
# ─────────────────────────────────────────────────────────────────────
async def register_tenant(
    tenant_id: int,
    name: str = "",
    username: str = "",
    *,
    auto_trial: bool = True,
) -> dict:
    """
    Yangi tenant yaratish (yoki mavjudni qaytarish).

    auto_trial=True boʻlsa — TRIAL tarif bilan avtomatik aktivlashadi.
    auto_trial=False — status='pending' qoladi, super admin tasdiqlashi kerak.

    Returns: tenant dict (yangi yoki mavjud).
    """
    existing = await db.get_tenant(tenant_id)
    if existing is not None:
        return existing

    # ENGINEBOT'da pul tizimi yo'q — yangi tenant doim TRIAL bilan boshlanadi
    tenant = await db.create_tenant(
        tenant_id, name=name, username=username, tariff=Tariff.TRIAL
    )

    if auto_trial:
        await activate_trial(tenant_id)
        tenant = await db.get_tenant(tenant_id)

    await audit_log.log_action(
        actor_role="system",
        actor_id=0,
        action="tenant_created",
        tenant_id=tenant_id,
        target_type="tenant",
        target_id=tenant_id,
        details={"name": name, "username": username, "tariff": Tariff.TRIAL},
    )
    await bus.emit(Events.TENANT_CREATED, {"tenant_id": tenant_id, "name": name})

    logger.info(f"new tenant: {tenant_id} ({name})")
    return tenant or {}


async def activate_trial(tenant_id: int) -> None:
    """
    TRIAL tarif bilan aktivlashtirish.

    Trial muddati TARIFF_LIMITS['trial']['duration_days'] dan olinadi.
    """
    days = TARIFF_LIMITS[Tariff.TRIAL]["duration_days"]
    paid_until = (
        datetime.now(timezone(timedelta(hours=DEFAULT_TZ_OFFSET)))
        + timedelta(days=days)
    ).isoformat()

    await db.update_tenant(
        tenant_id,
        status=TenantStatus.ACTIVE,
        tariff=Tariff.TRIAL,
        paid_until=paid_until,
    )
    await notifier.notify_tenant_approved(tenant_id, Tariff.TRIAL, paid_until[:10])
    await bus.emit(
        Events.TENANT_APPROVED,
        {"tenant_id": tenant_id, "tariff": Tariff.TRIAL, "trial": True},
    )


# ─────────────────────────────────────────────────────────────────────
# Muddat uzaytirish (PULSIZ model — og'zaki kelishuv asosida)
# ─────────────────────────────────────────────────────────────────────
async def extend_subscription(
    tenant_id: int,
    tariff: str,
    period_days: int,
    approved_by: int,
    note: str = "",
) -> int:
    """
    Tenant tarif/muddatini uzaytirish — PULSIZ.

    ENGINEBOT'da pul tizimi yo'q. Super admin og'zaki kelishuv asosida
    "tarif tanlash + qancha kun" deydi va shu funksiya chaqiriladi.

    `payments` jadvaliga yozadi (amount_uzs=0) — bu tarix uchun.
    `tenants.paid_until` uzayadi (mavjud muddatga qo'shiladi yoki bugundan).

    Returns: payment_id (tarix yozuvi ID)
    """
    if tariff not in Tariff.ALL:
        raise ValueError(f"Nomaʼlum tarif: {tariff}")
    if period_days < 1:
        raise ValueError(f"Muddat 1 kundan kam bo'lmasin: {period_days}")

    payment_id = await db.add_payment(
        tenant_id=tenant_id,
        amount_uzs=0,  # PULSIZ model
        tariff=tariff,
        period_days=period_days,
        approved_by=approved_by,
        note=note or "Og'zaki kelishuv asosida",
    )

    tenant = await db.get_tenant(tenant_id)
    paid_until = (tenant or {}).get("paid_until", "")[:10]

    await notifier.notify_tenant_approved(tenant_id, tariff, paid_until)
    await audit_log.log_action(
        actor_role="super_admin",
        actor_id=approved_by,
        action="subscription_extended",
        tenant_id=tenant_id,
        target_type="tenant",
        target_id=tenant_id,
        details={
            "tariff": tariff,
            "period_days": period_days,
            "payment_id": payment_id,
        },
    )
    await bus.emit(
        Events.TENANT_PAYMENT_RECEIVED,
        {
            "tenant_id": tenant_id,
            "tariff": tariff,
            "period_days": period_days,
        },
    )
    logger.info(
        f"subscription extended: tenant={tenant_id} "
        f"tariff={tariff} period={period_days}d"
    )
    return payment_id


# ─────────────────────────────────────────────────────────────────────
# Bloklash va qayta tiklash
# ─────────────────────────────────────────────────────────────────────
async def block_tenant(
    tenant_id: int, reason: str, blocked_by: int
) -> None:
    """Tenantni bloklash (super admin tomonidan)."""
    now_iso = datetime.now(timezone(timedelta(hours=DEFAULT_TZ_OFFSET))).isoformat()
    await db.update_tenant(
        tenant_id,
        status=TenantStatus.BLOCKED,
        blocked_reason=reason,
        blocked_at=now_iso,
    )
    await notifier.notify_critical(
        user_id=tenant_id,
        tenant_id=tenant_id,
        title="Hisobingiz bloklandi",
        message=(
            f"🚨 Sizning tenant hisobingiz bloklandi.\n\n"
            f"📌 Sabab: {reason}\n\n"
            "Bahslashish uchun bot egasiga murojaat qiling."
        ),
    )
    await audit_log.log_action(
        actor_role="super_admin",
        actor_id=blocked_by,
        action="tenant_blocked",
        tenant_id=tenant_id,
        target_type="tenant",
        target_id=tenant_id,
        details={"reason": reason},
        level="warn",
    )
    await bus.emit(
        Events.TENANT_BLOCKED, {"tenant_id": tenant_id, "reason": reason}
    )
    logger.warning(f"tenant blocked: {tenant_id} reason={reason!r}")


async def unblock_tenant(tenant_id: int, unblocked_by: int) -> None:
    """Tenant blokini olib tashlash."""
    await db.update_tenant(
        tenant_id,
        status=TenantStatus.ACTIVE,
        blocked_reason=None,
        blocked_at=None,
    )
    await notifier.notify_success(
        user_id=tenant_id,
        tenant_id=tenant_id,
        title="Hisobingiz qayta aktivlashdi",
        message="✅ Sizning tenant hisobingiz qayta aktivlashdi. /start bosing.",
    )
    await audit_log.log_action(
        actor_role="super_admin",
        actor_id=unblocked_by,
        action="tenant_unblocked",
        tenant_id=tenant_id,
        target_type="tenant",
        target_id=tenant_id,
    )


async def pause_tenant(tenant_id: int, reason: str = "Muddat tugadi") -> None:
    """
    Tenantni pause holatiga qoʻyish (muddat tugaganda).

    Mavjud eʼlonlar saqlanadi, lekin yangilari qabul qilinmaydi va
    aylanish toʻxtaydi.
    """
    await db.update_tenant(tenant_id, status=TenantStatus.PAUSED)
    await db.update_settings(tenant_id, post_intake_active=False, rotation_active=False)

    await notifier.notify_tenant_paused(tenant_id, reason)
    await audit_log.log_system_event(
        action="tenant_paused",
        tenant_id=tenant_id,
        target_type="tenant",
        target_id=tenant_id,
        level="warn",
        reason=reason,
    )
    await bus.emit(
        Events.TENANT_PAYMENT_OVERDUE,
        {"tenant_id": tenant_id, "reason": reason},
    )


# ─────────────────────────────────────────────────────────────────────
# Toʻlov muddati tekshirish (billing checker uchun)
# ─────────────────────────────────────────────────────────────────────
async def check_payment_status(tenant: dict) -> dict:
    """
    Tenant toʻlov holatini baholash.

    Returns:
        {
            "tenant_id": ...,
            "status": "active" | "expiring" | "overdue",
            "days_left": int (manfiy = oʻtgan),
            "paid_until": ISO string,
        }
    """
    tenant_id = tenant["tenant_id"]
    paid_until_str = tenant.get("paid_until")
    if not paid_until_str:
        return {
            "tenant_id": tenant_id,
            "status": "no_payment",
            "days_left": -999,
            "paid_until": None,
        }

    try:
        paid_until = datetime.fromisoformat(paid_until_str)
    except ValueError:
        logger.warning(f"tenant {tenant_id} paid_until parse error: {paid_until_str!r}")
        return {
            "tenant_id": tenant_id,
            "status": "invalid",
            "days_left": 0,
            "paid_until": paid_until_str,
        }

    now = datetime.now(timezone(timedelta(hours=DEFAULT_TZ_OFFSET)))
    delta = paid_until - now
    days_left = delta.days

    if days_left < 0:
        status = "overdue"
    elif days_left <= BILLING_REMINDER_DAYS:
        status = "expiring"
    else:
        status = "active"

    return {
        "tenant_id": tenant_id,
        "status": status,
        "days_left": days_left,
        "paid_until": paid_until_str,
    }


async def enforce_billing(tenant: dict) -> bool:
    """
    Toʻlov muddatiga qarab tegishli amalni bajarish.

    - status="overdue" → tenant'ni pause qilish
    - status="expiring" → eslatma yuborish
    - status="active" → hech narsa qilmaslik

    Returns: True agar tenant bilan ish boʻlsa (state oʻzgardi).
    """
    status_info = await check_payment_status(tenant)
    tenant_id = tenant["tenant_id"]
    current_status = tenant.get("status")

    if status_info["status"] == "overdue":
        if current_status != TenantStatus.PAUSED:
            await pause_tenant(tenant_id, reason="Muddat tugadi")
            return True
        return False

    if status_info["status"] == "expiring":
        # Eslatma yuborish (har kuni emas — bir martalik daraja flag yoʻq,
        # lekin notification jadvali takror yuborilmasligini eslatadi).
        await notifier.notify_tenant_payment_reminder(
            tenant_id=tenant_id,
            days_left=status_info["days_left"],
            paid_until=status_info["paid_until"][:10],
        )
        return True

    return False


# ─────────────────────────────────────────────────────────────────────
# Yordamchilar
# ─────────────────────────────────────────────────────────────────────
def is_operational(tenant: dict | None) -> bool:
    """
    Tenant ishlamoqdami?

    True boʻlsa: status=active, bot_active=True, toʻlov muddati tugamagan.
    """
    if not tenant:
        return False
    return tenant.get("status") == TenantStatus.ACTIVE


async def list_active_tenants() -> list[dict]:
    """Hozir aktiv tenantlar (services uchun: rotation, cleaner)."""
    return await db.list_tenants(status=TenantStatus.ACTIVE)


async def list_pending_tenants() -> list[dict]:
    """Tasdiqlash kutilayotgan tenantlar (super admin uchun)."""
    return await db.list_tenants(status=TenantStatus.PENDING)


async def get_tenant_with_settings(tenant_id: int) -> dict | None:
    """Tenant + uning sozlamalari bitta dict'da."""
    tenant = await db.get_tenant(tenant_id)
    if not tenant:
        return None
    settings = await db.get_settings(tenant_id)
    return {**tenant, "settings": settings}


async def get_tariff_info(tenant: dict) -> dict[str, Any]:
    """Tenantning tarif limitlarini olish."""
    tariff = tenant.get("tariff", Tariff.TRIAL)
    return TARIFF_LIMITS.get(tariff, TARIFF_LIMITS[Tariff.TRIAL])


async def can_accept_new_post(tenant_id: int) -> tuple[bool, str]:
    """
    Tenant yangi eʼlon qabul qila oladimi?

    Returns: (can, reason)
    """
    tenant = await db.get_tenant(tenant_id)
    if not tenant:
        return False, "tenant_not_found"
    if not is_operational(tenant):
        return False, f"tenant_status:{tenant.get('status')}"

    settings = await db.get_settings(tenant_id)
    if not settings.get("bot_active"):
        return False, "bot_off"
    if not settings.get("post_intake_active"):
        return False, "post_intake_off"

    return True, "ok"
