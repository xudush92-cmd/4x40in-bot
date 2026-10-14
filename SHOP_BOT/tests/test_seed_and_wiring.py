"""Seed skripti va bot simlari (wiring) testlari."""

from __future__ import annotations

import os
import subprocess
import sys

from sqlalchemy import func, select

from app.db.base import session_scope
from app.db.models import Admin, BotText, Setting, Tariff
from app.keyboards import ADMIN_SECTIONS, admin_main_kb, settings_kb
from app.keyboards.callbacks import AdminCB
from app.services.text_service import DEFAULT_TEXTS
from scripts.seed import SAMPLE_TARIFFS, seed


async def test_seed_creates_all_data(clean_db) -> None:
    await seed()

    async with session_scope() as session:
        admins = (await session.execute(select(func.count()).select_from(Admin))).scalar_one()
        settings_count = (await session.execute(select(func.count()).select_from(Setting))).scalar_one()
        texts = (await session.execute(select(func.count()).select_from(BotText))).scalar_one()
        tariffs = (await session.execute(select(func.count()).select_from(Tariff))).scalar_one()

    assert admins == 2  # test muhitida ADMIN_IDS="111111,222222"
    assert settings_count > 10
    assert texts == len(DEFAULT_TEXTS)
    assert tariffs == len(SAMPLE_TARIFFS)


async def test_seed_is_idempotent(clean_db) -> None:
    await seed()
    await seed()  # ikkinchi marta — dublikat yaratmasligi kerak

    async with session_scope() as session:
        admins = (await session.execute(select(func.count()).select_from(Admin))).scalar_one()
        tariffs = (await session.execute(select(func.count()).select_from(Tariff))).scalar_one()

    assert admins == 2
    assert tariffs == len(SAMPLE_TARIFFS)


def test_dispatcher_registers_routers_and_updates() -> None:
    """`create_dispatcher` (haqiqiy ishga tushish yo'li) to'g'ri ulanadi.

    Router daraxtini bir jarayonda faqat bir marta qurish mumkin
    (aiogram cheklovi), shu sababli tekshiruv alohida jarayonda bajariladi.
    """
    code = (
        "from aiogram.fsm.storage.memory import MemoryStorage\n"
        "from app.bot import create_bot, create_dispatcher\n"
        "from app.config import get_settings\n"
        "settings = get_settings()\n"
        "bot = create_bot(settings)\n"
        "dp = create_dispatcher(settings, MemoryStorage())\n"
        "used = set(dp.resolve_used_update_types())\n"
        "expected = {'message', 'callback_query', 'my_chat_member', 'chat_member'}\n"
        "assert expected <= used, sorted(used)\n"
        "assert len(dp.errors.handlers) >= 1\n"
        "assert dp.fsm is not None\n"
        "print('WIRING_OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=120,
    )
    assert "WIRING_OK" in result.stdout, result.stderr


def test_admin_keyboard_has_all_sections() -> None:
    kb = admin_main_kb(role="super")
    callbacks = [button.callback_data for row in kb.inline_keyboard for button in row]

    for key, _label, _phase in ADMIN_SECTIONS:
        expected = AdminCB(action="section", value=key).pack()
        assert expected in callbacks, f"{key} bo'limi tugmasi yo'q"


def test_admin_keyboard_hides_admins_for_regular_admin() -> None:
    kb_admin = admin_main_kb(role="admin")
    callbacks = [button.callback_data for row in kb_admin.inline_keyboard for button in row]
    assert AdminCB(action="section", value="admins").pack() not in callbacks
    assert AdminCB(action="section", value="stats").pack() in callbacks


def test_callback_data_roundtrip() -> None:
    packed = AdminCB(action="section", value="payments").pack()
    parsed = AdminCB.unpack(packed)
    assert parsed.action == "section"
    assert parsed.value == "payments"


def test_settings_keyboard_toggles() -> None:
    kb = settings_kb({"kill_switch": True, "maintenance_mode": False})
    texts = [button.text for row in kb.inline_keyboard for button in row]
    assert any("HAMMASINI" in text and text.startswith("🟢") for text in texts)
    assert any("Texnik rejim" in text and text.startswith("🔴") for text in texts)
