"""Admin katalogi: oddiy user, sotuvchi va bepul e'lon egalarini birlashtiradi.

ID yoki ism/@username bilan qidirish; Seller bilan users orasida FK yo'q,
shuning uchun qo'lda qo'shilgan sotuvchi ham ro'yxatda ko'rinadi.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import String, cast, func, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FreeAd, Seller, User

PAGE_SIZE = 10


@dataclass(frozen=True)
class DirectoryEntry:
    user_id: int
    name: str
    username: str | None
    seller_status: str | None


def _statement(search: str = ""):
    ids = union(select(User.user_id.label("uid")), select(Seller.user_id.label("uid")),
                select(FreeAd.user_id.label("uid"))).subquery()
    stmt = select(ids.c.uid, User.first_name, User.last_name, User.username,
                  Seller.display_name, Seller.status).select_from(ids).outerjoin(
                      User, User.user_id == ids.c.uid).outerjoin(
                      Seller, Seller.user_id == ids.c.uid)
    value = search.strip().lstrip("@").replace("%", "\\%").replace("_", "\\_")[:64]
    if value:
        pattern = f"%{value}%"
        stmt = stmt.where(or_(
            cast(ids.c.uid, String).ilike(pattern, escape="\\"),
            User.username.ilike(pattern, escape="\\"),
            User.first_name.ilike(pattern, escape="\\"),
            User.last_name.ilike(pattern, escape="\\"),
            Seller.display_name.ilike(pattern, escape="\\"),
        ))
    return stmt, ids


async def list_users(session: AsyncSession, *, page: int = 0,
                     search: str = "") -> tuple[list[DirectoryEntry], int]:
    query, ids = _statement(search)
    total = int((await session.execute(select(func.count()).select_from(
        query.with_only_columns(ids.c.uid).order_by(None).subquery()
    ))).scalar_one())
    rows = (await session.execute(query.order_by(
        User.last_seen_at.desc(), User.created_at.desc(),
        Seller.created_at.desc(), ids.c.uid.desc(),
    ).offset(max(0, page) * PAGE_SIZE).limit(PAGE_SIZE))).all()
    return [DirectoryEntry(int(uid),
                           " ".join(filter(None, (first, last))) or display or f"ID {uid}",
                           username, status)
            for uid, first, last, username, display, status in rows], total
