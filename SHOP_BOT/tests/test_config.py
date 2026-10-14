"""Konfiguratsiya testlari."""

from __future__ import annotations

import pytest

from app.config import Settings, get_settings


def test_admin_ids_parsing() -> None:
    s = Settings(bot_token="1:2", admin_ids="111, 222 ,333")
    assert s.admin_ids == [111, 222, 333]


def test_admin_ids_parsing_semicolon_and_list() -> None:
    assert Settings(bot_token="1:2", admin_ids="5;6").admin_ids == [5, 6]
    assert Settings(bot_token="1:2", admin_ids=[7, 8]).admin_ids == [7, 8]


def test_admin_ids_empty(monkeypatch) -> None:
    assert Settings(bot_token="1:2", admin_ids="").admin_ids == []
    monkeypatch.delenv("ADMIN_IDS", raising=False)
    assert Settings(bot_token="1:2").admin_ids == []
    assert Settings(bot_token="1:2", admin_ids=None).admin_ids == []


def test_webhook_url_building() -> None:
    s = Settings(
        bot_token="1:2",
        webhook_base_url="https://bot.example.uz/",
        webhook_path="/webhook",
        use_webhook=True,
    )
    assert s.webhook_url == "https://bot.example.uz/webhook"
    assert s.is_webhook_ready is True


def test_webhook_not_ready_without_url() -> None:
    s = Settings(bot_token="1:2", use_webhook=True)
    assert s.is_webhook_ready is False


def test_validate_for_bot_reports_problems() -> None:
    s = Settings(bot_token="", admin_ids="")
    with pytest.raises(RuntimeError) as exc:
        s.validate_for_bot()
    message = str(exc.value)
    assert "BOT_TOKEN" in message
    assert "ADMIN_IDS" in message


def test_validate_for_bot_webhook_secret() -> None:
    s = Settings(bot_token="1:2", admin_ids="1", use_webhook=True, webhook_base_url="https://x.uz")
    with pytest.raises(RuntimeError) as exc:
        s.validate_for_bot()
    assert "WEBHOOK_SECRET" in str(exc.value)


def test_sqlite_flag() -> None:
    assert Settings(bot_token="1:2", db_url="sqlite+aiosqlite:///x.db").is_sqlite is True
    assert Settings(bot_token="1:2", db_url="postgresql+asyncpg://u:p@h/d").is_sqlite is False


def test_settings_from_environment() -> None:
    """Test muhitidagi .env o'zgaruvchilari to'g'ri o'qilishini tekshirish."""
    settings = get_settings()
    assert settings.admin_ids == [111111, 222222]
    assert settings.is_sqlite is True
    assert settings.dev_mode is True
