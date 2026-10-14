"""Alembic migratsiya muhiti (async).

DB manzili quyidagi tartibda olinadi:
  1. ALEMBIC_DB_URL (testlar / qo'lda migratsiya uchun)
  2. DB_URL (.env faylidan yoki docker-compose environment'dan)
  3. Standart PostgreSQL manzili (localhost, dev uchun)
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# Loyiha ildizini import yo'liga qo'shish (alembic alohida processda ishlaydi)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.base import Base  # noqa: E402
import app.db.models  # noqa: E402,F401  — metadata to'liq bo'lishi uchun MAJBURIY

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_db_url() -> str:
    """Migratsiya uchun DB manzilini aniqlash."""
    return (
        os.getenv("ALEMBIC_DB_URL")
        or os.getenv("DB_URL")
        or "postgresql+asyncpg://shopbot:shopbot@localhost:5432/shopbot"
    )


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def run_migrations_offline() -> None:
    """--sql rejimi: SQL faylga yoziladi, DB ulanmaydi."""
    url = get_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=_is_sqlite(url),
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # SQLite ALTER TABLE cheklovlari uchun batch rejimi
        render_as_batch=_is_sqlite(str(connection.engine.url)),
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(get_db_url(), poolclass=pool.NullPool, future=True)
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
