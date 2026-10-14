"""Test muhiti: SQLite (vaqtinchalik fayl), soxta token, keshsiz Redis.

Muhim: muhit o'zgaruvchilari `app` modullari import qilinishidan OLDIN
o'rnatilishi kerak (chunki `redis_manager` import paytida sozlamani o'qiydi).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

_TMP_DIR = Path(tempfile.mkdtemp(prefix="shopbot-tests-"))

os.environ.update(
    {
        "BOT_TOKEN": "123456789:TEST-TOKEN-FOR-UNIT-TESTS",
        "ADMIN_IDS": "111111,222222",
        "DB_URL": f"sqlite+aiosqlite:///{_TMP_DIR / 'test.db'}",
        "REDIS_URL": "redis://127.0.0.1:6399/15",  # ataylab bo'sh port (Redis yo'q)
        "DEV_MODE": "true",
        "LOG_LEVEL": "WARNING",
        "TIMEZONE": "Asia/Tashkent",
        "USE_WEBHOOK": "false",
    }
)

from app.config import get_settings, reset_settings_cache  # noqa: E402
from app.db.base import Base, create_all, dispose_engine, get_session_factory  # noqa: E402
import app.db.models  # noqa: E402,F401 — metadata to'liq bo'lishi uchun


@pytest.fixture(scope="session", autouse=True)
def _configure_env() -> None:
    reset_settings_cache()
    get_settings()


@pytest_asyncio.fixture
async def session():
    """Toza bazada bitta sessiya.

    Har testdan oldin barcha jadvallar o'chirilib, qaytadan yaratiladi —
    testlar bir-biriga ta'sir qilmaydi (izolyatsiya).
    """
    from app.db.base import Base, get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await create_all()

    factory = get_session_factory()
    async with factory() as db_session:
        yield db_session
        await db_session.rollback()
    await dispose_engine()


@pytest_asyncio.fixture
async def clean_db():
    """Bo'sh baza (jadvallar yaratilgan, ma'lumot yo'q)."""
    await create_all()
    yield
    await dispose_engine()


@pytest.fixture
def tmp_dir() -> Path:
    return _TMP_DIR


@pytest.fixture(autouse=True)
def _reset_caches():
    """Har testdan keyin keshlarni tozalash (testlar bir-biriga ta'sir qilmasin)."""
    from app.services.settings_service import settings_service
    from app.services.text_service import text_service

    settings_service.invalidate()
    text_service.invalidate()
    yield
    settings_service.invalidate()
    text_service.invalidate()


def pytest_report_header() -> str:
    return f"SHOP-BOT testlari | baza: {get_settings().db_url}"
