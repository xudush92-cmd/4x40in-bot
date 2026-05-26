"""
tests/conftest.py — pytest sozlamalari (mock muhit).

Test'lar uchun fake bot/env muhitini tayyorlaydi.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Test'lar uchun fake env (config.py'ni o'qishidan oldin)
os.environ.setdefault("BOT_TOKEN", "123456:TEST-TOKEN-FOR-PYTEST")
os.environ.setdefault("SUPER_ADMIN_ID", "999999")

# Vaqtinchalik DB
_TEST_DB = Path(tempfile.gettempdir()) / "enginebot_test.db"
os.environ["DB_PATH"] = str(_TEST_DB)

# ENGINEBOT papkasini path'ga qo'shish
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def pytest_sessionstart(session):
    """Test sessiyasi boshlanishida vaqtinchalik DB'ni tozalash."""
    if _TEST_DB.exists():
        _TEST_DB.unlink()


def pytest_sessionfinish(session, exitstatus):
    """Test tugagandan keyin vaqtinchalik DB'ni o'chirish."""
    if _TEST_DB.exists():
        _TEST_DB.unlink()
