"""Seed skripti va bot simlari (wiring) testlari."""

from __future__ import annotations

from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import func, select

from app.bot import create_bot, create_dispatcher
from app.config import get_settings
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


async def test_dispatcher_registers_routers_and_updates(clean_db) -> None:
    settings = get_settings()
    bot = create_bot(settings)
    try:
        dp = create_dispatcher(settings, MemoryStorage())
        used = set(dp.resolve_used_update_types())

        # Handler'lar qaysi update turlarini kutayotgani
        for expected in ("message", "callback_query", "my_chat_member", "chat_member"):
            assert expected in used, f"{expected} update turi ro'yxatdan o'tmagan"

        # Xato ushlagich bor
        assert len(dp.errors.handlers) >= 1
    finally:
        await bot.session.close()


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
