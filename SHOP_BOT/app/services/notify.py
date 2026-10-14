"""Adminlarga xabar berish va xatolarni jurnalga yozish.

REJA.md 8.7: "Xato bo'lsa (bot admin emas, guruh topilmadi) shu guruh
to'xtatiladi va adminga xabar beriladi."
"""

from __future__ import annotations

import traceback as tb
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramAPIError
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.constants import AdminRole
from app.db.models import Admin, ErrorLog
from app.services.text_service import text_service


async def get_admin_ids(session: AsyncSession | None = None) -> list[int]:
    """Faol adminlar ro'yxati: DB'dagi adminlar + .env dagi super adminlar."""
    ids: set[int] = set(get_settings().admin_ids)

    if session is not None:
        rows = (
            await session.execute(select(Admin).where(Admin.is_active.is_(True)))
        ).scalars().all()
        ids.update(row.user_id for row in rows)
    else:
        from app.db.base import session_scope

        async with session_scope() as own_session:
            rows = (
                await own_session.execute(select(Admin).where(Admin.is_active.is_(True)))
            ).scalars().all()
            ids.update(row.user_id for row in rows)

    return sorted(ids)


async def notify_admins(
    bot: Bot,
    text: str,
    *,
    disable_notification: bool = False,
    session: AsyncSession | None = None,
) -> int:
    """Barcha adminlarga xabar yuborish. Yuborilganlar sonini qaytaradi."""
    sent = 0
    for admin_id in await get_admin_ids(session):
        try:
            await bot.send_message(
                admin_id, text, disable_notification=disable_notification,
                disable_web_page_preview=True,
            )
            sent += 1
        except TelegramRetryAfter as exc:
            logger.warning("Admin {} ga xabar: FloodWait {}s", admin_id, exc.retry_after)
            break
        except TelegramForbiddenError:
            logger.debug("Admin {} botni bloklagan", admin_id)
        except TelegramAPIError as exc:
            logger.warning("Admin {} ga xabar yuborilmadi: {}", admin_id, exc)
    return sent


async def notify_critical(bot: Bot, text: str, **context: Any) -> None:
    """Muhim xabar: logga yoziladi + adminlarga yuboriladi."""
    logger.bind(**context).error("CRITICAL: {}", text)
    try:
        await notify_admins(bot, "🚨 " + text)
    except Exception as exc:  # pragma: no cover — bildirishnoma yuborilmasa bot to'xtamasin
        logger.warning("Kritik xabarni yuborishda xato: {}", exc)


async def save_error(
    session: AsyncSession | None,
    source: str,
    message: str,
    *,
    exc: BaseException | None = None,
    group_id: int | None = None,
    user_id: int | None = None,
    context: dict[str, Any] | None = None,
    is_critical: bool = False,
) -> int | None:
    """Xatoni `error_log` jadvaliga yozish. Yozuv ID'sini qaytaradi."""
    record = ErrorLog(
        level="CRITICAL" if is_critical else "ERROR",
        source=source,
        group_id=group_id,
        user_id=user_id,
        message=message[:4000],
        traceback="".join(tb.format_exception(type(exc), exc, exc.__traceback__))[:8000] if exc else None,
        context=context,
        is_critical=is_critical,
    )

    try:
        if session is not None:
            session.add(record)
            await session.flush()
            return record.id
        from app.db.base import session_scope

        async with session_scope() as own_session:
            own_session.add(record)
            await own_session.flush()
            return record.id
    except Exception as db_exc:  # DB ham ishlamasa — hech bo'lmasa logga yozamiz
        logger.bind(source=source).error("Xatoni bazaga yozib bo'lmadi: {}", db_exc)
        return None


async def notify_payment_received(bot: Bot, *, seller: str, tariff: str, amount: str) -> None:
    """Yangi chek kelganda adminlarga xabar (REJA.md 8.2)."""
    text = await text_service.get(
        "notify.payment_received", sotuvchi=seller, tarif=tariff, summa=amount
    )
    await notify_admins(bot, text)


async def ensure_super_admins(session: AsyncSession) -> int:
    """`.env` dagi ADMIN_IDS ni `admins` jadvaliga super admin sifatida yozish."""
    created = 0
    for admin_id in get_settings().admin_ids:
        row = (await session.execute(select(Admin).where(Admin.user_id == admin_id))).scalar_one_or_none()
        if row is None:
            session.add(Admin(user_id=admin_id, role=AdminRole.SUPER, title="Super admin (.env)", is_active=True))
            created += 1
        elif row.role != AdminRole.SUPER:
            row.role = AdminRole.SUPER
            row.is_active = True
    if created:
        await session.flush()
        logger.info("{} ta super admin qo'shildi", created)
    return created
