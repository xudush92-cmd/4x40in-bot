"""Super admin uchun rollar: audit, o'zini/seed adminlarini himoya qilish."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.constants import AdminRole
from app.db.models import ActionLog, Admin
from app.middlewares.user_context import invalidate_admin_cache

_ROLES = {AdminRole.SUPER, AdminRole.ADMIN, AdminRole.MODERATOR}


class AdminError(ValueError):
    """Panelga ko'rsatiladigan xavfsiz boshqaruv xatosi."""


async def add(session: AsyncSession, user_id: int, role: str, actor_id: int) -> Admin:
    if role not in _ROLES or user_id <= 0 or user_id >= 2**63:
        raise AdminError("Foydalanuvchi ID yoki rol noto'g'ri.")
    if user_id in get_settings().admin_ids and role != AdminRole.SUPER:
        raise AdminError(".env super admini rolini tushirib bo'lmaydi.")
    row = (await session.execute(select(Admin).where(Admin.user_id == user_id)
                                 .with_for_update())).scalar_one_or_none()
    if row is not None and row.is_active:
        raise AdminError("Bu odam allaqachon faol admin; rolini kartadan o'zgartiring.")
    if row is None:
        row = Admin(user_id=user_id, role=role, is_active=True, added_by=actor_id)
        session.add(row)
    else:
        row.role, row.is_active, row.added_by = role, True, actor_id
    session.add(ActionLog(actor_id=actor_id, action="admin_add", entity="admin",
                          entity_id=user_id, after={"role": role, "active": True}))
    await session.flush()
    invalidate_admin_cache(user_id)
    return row


async def modify(session: AsyncSession, user_id: int, actor_id: int,
                 *, role: str | None = None, deactivate: bool = False) -> Admin:
    if role is not None and role not in _ROLES:
        raise AdminError("Rol noto'g'ri.")
    row = (await session.execute(select(Admin).where(Admin.user_id == user_id)
                                 .with_for_update())).scalar_one_or_none()
    if row is None or not row.is_active:
        raise AdminError("Faol admin topilmadi.")
    if user_id in get_settings().admin_ids and (deactivate or role != AdminRole.SUPER):
        raise AdminError(".env super adminini o'chirish/rolini tushirish mumkin emas.")
    if user_id == actor_id and (deactivate or (role is not None and role != row.role)):
        raise AdminError("O'zingizning rolingizni tushirish yoki o'chirish mumkin emas.")
    if role == row.role and not deactivate:
        return row
    if row.role == AdminRole.SUPER and (deactivate or role != AdminRole.SUPER):
        # Barcha super qatorlarini qulflash: ikki so'rov bir vaqtning o'zida
        # oxirgi ikkita superni alohida demote qila olmasin.
        supers = (await session.execute(select(Admin).where(
            Admin.role == AdminRole.SUPER, Admin.is_active.is_(True),
        ).with_for_update())).scalars().all()
        if len(supers) <= 1:
            raise AdminError("Oxirgi super adminni o'chirib bo'lmaydi.")
    before = {"role": row.role, "active": row.is_active}
    if role is not None:
        row.role = role
    if deactivate:
        row.is_active = False
    session.add(ActionLog(actor_id=actor_id, action="admin_deactivate" if deactivate else "admin_role",
                          entity="admin", entity_id=user_id, before=before,
                          after={"role": row.role, "active": row.is_active}))
    await session.flush()
    invalidate_admin_cache(user_id)
    return row
