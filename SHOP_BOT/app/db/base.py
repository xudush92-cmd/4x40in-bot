"""Baza, engine va sessiya boshqaruvi.

Asosiy tamoyillar:
  * Har bir update uchun bitta sessiya (middleware orqali) — ochiq sessiya qolmaydi.
  * `session_scope()` — skriptlar/scheduler uchun qulay kontekst menejeri.
  * Engine bir marta yaratiladi va butun process davomida qayta ishlatiladi.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import get_settings
from app.utils.time import utcnow

# PostgreSQL uchun JSONB, boshqa bazalar (masalan testlarda SQLite) uchun oddiy JSON
JSONType = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    """Barcha modellar uchun asos."""

    type_annotation_map = {
        dict[str, Any]: JSONType,
        list[str]: JSONType,
        list[int]: JSONType,
        list[Any]: JSONType,
    }


class TimestampMixin:
    """created_at / updated_at ustunlari (UTC, timezone-aware)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


def _engine_kwargs(url: str) -> dict[str, Any]:
    """Bazaga qarab engine sozlamalari."""
    kwargs: dict[str, Any] = {"echo": False, "future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        # SQLite testlarda: cheksiz pool o'rniga oddiy ulanish
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
        kwargs["pool_recycle"] = 1800
    return kwargs


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine(url: str | None = None) -> AsyncEngine:
    """Engine'ni (bir marta) yaratib qaytaradi."""
    global _engine
    if _engine is None:
        db_url = url or get_settings().db_url
        _engine = create_async_engine(db_url, **_engine_kwargs(db_url))
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Sessiya fabrikasi."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Xatoda rollback, muvaffaqiyatda commit qiladigan sessiya."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def ping_database() -> bool:
    """Ulanishni tekshirish (health endpoint uchun)."""
    from sqlalchemy import text

    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def dispose_engine() -> None:
    """Process yopilishida ulanishlarni yopish."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def reset_engine() -> None:
    """Testlarda engine'ni qayta yaratish uchun (muhit o'zgarganda)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


async def create_all(url: str | None = None) -> None:
    """Jadvallarni yaratish (faqat testlar/tezkor ishga tushirish uchun).

    Ishlab chiqarishda migratsiya ishlatiladi: `alembic upgrade head`.
    """
    engine = get_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


__all__ = [
    "Base",
    "JSONType",
    "TimestampMixin",
    "create_all",
    "dispose_engine",
    "get_engine",
    "get_session_factory",
    "ping_database",
    "reset_engine",
    "session_scope",
    "utcnow",
    "datetime",
]
