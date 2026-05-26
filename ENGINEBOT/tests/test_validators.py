"""
tests/test_validators.py — validators.py funksiyalari testi.

aiogram, aiosqlite kerak emas — pure Python.
"""

from __future__ import annotations


def test_validate_phone_uzbekistan() -> None:
    from utils.validators import validate_phone

    # To'g'ri formatlar
    ok, normalized, _ = validate_phone("+998901234567")
    assert ok is True
    assert normalized == "+998901234567"

    # Probel bilan
    ok, normalized, _ = validate_phone("+998 90 123 45 67")
    assert ok is True
    assert normalized == "+998901234567"

    # +o'rniga qoldirilgan
    ok, normalized, _ = validate_phone("998901234567")
    assert ok is True
    assert normalized.startswith("+998")

    # Notog'ri
    ok, _, err = validate_phone("123")
    assert ok is False
    assert err  # error message bor


def test_validate_interval_min_10() -> None:
    """Min 10 daq qoidasi qat'iy."""
    from utils.validators import validate_interval

    # Min'dan kichik
    ok, _, err = validate_interval("5")
    assert ok is False
    assert "10" in err  # min mention

    # 10 daq — OK
    ok, val, _ = validate_interval("10")
    assert ok is True
    assert val == "10"

    # 60 daq — OK
    ok, val, _ = validate_interval("60")
    assert ok is True


def test_validate_channel_formats() -> None:
    from utils.validators import validate_channel

    # @username
    ok, normalized, _ = validate_channel("@toshkent_taxi")
    assert ok is True
    assert normalized.startswith("@")

    # Numeric
    ok, normalized, _ = validate_channel("-1001234567890")
    assert ok is True

    # t.me link
    ok, normalized, _ = validate_channel("https://t.me/sometaxichannel")
    assert ok is True
    assert normalized.startswith("@")

    # Bo'sh
    ok, _, _ = validate_channel("")
    assert ok is False


def test_validate_name() -> None:
    from utils.validators import validate_name

    ok, name, _ = validate_name("Akmal Karimov")
    assert ok is True
    assert name == "Akmal Karimov"

    # Juda qisqa
    ok, _, _ = validate_name("A")
    assert ok is False

    # Bo'sh
    ok, _, _ = validate_name("")
    assert ok is False


def test_validate_reason() -> None:
    from utils.validators import validate_reason

    ok, reason, _ = validate_reason("Spam yuboryapti")
    assert ok is True
    assert reason == "Spam yuboryapti"

    # Juda qisqa
    ok, _, _ = validate_reason("X")
    assert ok is False
