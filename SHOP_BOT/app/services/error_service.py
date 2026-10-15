"""Phase 8: xato jurnali ro'yxati va auditli hal qilish."""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActionLog, ErrorLog
from app.utils.time import utcnow

FILTERS = frozenset({"open", "resolved", "critical", "all"})


def _filter(status: str):
    if status == "open":
        return ErrorLog.resolved_at.is_(None)
    if status == "resolved":
        return ErrorLog.resolved_at.is_not(None)
    if status == "critical":
        return ErrorLog.is_critical.is_(True)
    if status == "all":
        return None
    raise ValueError("Xato jurnali filtri noto'g'ri.")


async def list_errors(session: AsyncSession, *, status: str = "open", page: int = 0,
                      limit: int = 8) -> tuple[list[ErrorLog], int]:
    criterion = _filter(status)
    stmt = select(ErrorLog)
    count = select(func.count(ErrorLog.id))
    if criterion is not None:
        stmt, count = stmt.where(criterion), count.where(criterion)
    total = int((await session.execute(count)).scalar_one())
    rows = (await session.execute(stmt.order_by(
        ErrorLog.created_at.desc(), ErrorLog.id.desc(),
    ).offset(max(0, page) * limit).limit(limit))).scalars().all()
    return list(rows), total


async def resolve(session: AsyncSession, error_id: int, actor_id: int) -> bool:
    if error_id <= 0 or actor_id <= 0:
        return False
    changed = await session.execute(update(ErrorLog).where(
        ErrorLog.id == error_id, ErrorLog.resolved_at.is_(None),
    ).values(resolved_at=utcnow(), resolved_by=actor_id).returning(ErrorLog.id))
    if changed.scalar_one_or_none() is None:
        return False
    session.add(ActionLog(actor_id=actor_id, action="error_resolved", entity="error_log",
                          entity_id=error_id, after={"resolved": True}))
    await session.flush()
    return True
