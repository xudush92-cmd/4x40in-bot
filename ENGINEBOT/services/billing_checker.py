"""
services/billing_checker.py — to'lov muddatini tekshirish servisi.

VAZIFASI:
─────────
Har 1 soatda barcha aktiv tenantlarni tekshirib:
  - Muddat tugaganlarni → PAUSE
  - Muddat yaqin (< 3 kun) → eslatma yuborish
"""

from __future__ import annotations

import asyncio

from config import TenantStatus
from core import database as db
from core.error_handler import safe_loop
from core.tenant_manager import enforce_billing
from utils import logger as log_mod

logger = log_mod.get_logger("services.billing")


async def billing_run_once() -> None:
    """Cheksiz billing checker — har 1 soatda."""
    while True:
        try:
            await _check_all_tenants()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"billing tick error: {type(e).__name__}: {e}")

        await asyncio.sleep(3600)  # 1 soat


async def start_billing_checker() -> None:
    """Billing checker servisini ishga tushirish."""
    await safe_loop("billing_checker", billing_run_once, restart_delay=60)


async def _check_all_tenants() -> None:
    """Barcha aktiv tenantlarni billing bo'yicha tekshirish."""
    tenants = await db.list_tenants(status=TenantStatus.ACTIVE, limit=10000)
    if not tenants:
        return

    logger.info(f"billing: {len(tenants)} aktiv tenant tekshirilmoqda")
    actions_taken = 0

    for tenant in tenants:
        try:
            taken = await enforce_billing(tenant)
            if taken:
                actions_taken += 1
        except Exception as e:
            logger.error(
                f"billing: tenant #{tenant.get('tenant_id')} xato: {type(e).__name__}: {e}"
            )

    if actions_taken > 0:
        logger.info(f"billing: {actions_taken} tenant uchun amal bajarildi")
