"""
tests/test_rate_limiter.py — rate_limiter logikasi testi.

Pure Python — aiogram kerak emas.
"""

from __future__ import annotations

import time


def test_rate_limiter_allows_within_limit() -> None:
    """Limit ichida — ruxsat."""
    from core.rate_limiter import RateLimiter

    limiter = RateLimiter()
    uid = 100

    # Birinchi 3 ta soʻrov ruxsat (login limit = 3)
    assert limiter.is_allowed(uid, "login") is True
    assert limiter.is_allowed(uid, "login") is True
    assert limiter.is_allowed(uid, "login") is True


def test_rate_limiter_blocks_after_limit() -> None:
    """Limit oʻtgandan keyin block."""
    from core.rate_limiter import RateLimiter

    limiter = RateLimiter()
    uid = 200

    # 3 ta login ruxsat (login: 3 / 5 daq)
    for _ in range(3):
        assert limiter.is_allowed(uid, "login") is True

    # 4-marta — block
    assert limiter.is_allowed(uid, "login") is False


def test_rate_limiter_per_user_isolation() -> None:
    """Bitta userning limiti boshqaga taʼsir qilmasin."""
    from core.rate_limiter import RateLimiter

    limiter = RateLimiter()
    user_a = 300
    user_b = 301

    # User A — limit'ga yetdi
    for _ in range(3):
        limiter.is_allowed(user_a, "login")
    assert limiter.is_allowed(user_a, "login") is False

    # User B — hech qaysi limit'ga yetmagan, ruxsat
    assert limiter.is_allowed(user_b, "login") is True


def test_rate_limiter_unknown_action_passes() -> None:
    """Nomaʼlum action — cheklanmaydi."""
    from core.rate_limiter import RateLimiter

    limiter = RateLimiter()
    uid = 400
    for _ in range(100):
        assert limiter.is_allowed(uid, "unknown_action") is True


def test_get_block_message_returns_none_when_allowed() -> None:
    """Bloklanmaganda — None."""
    from core.rate_limiter import limiter, get_block_message

    msg = get_block_message(99999, "command")
    assert msg is None


def test_rate_limit_reset() -> None:
    """Reset bilan limitni tozalash."""
    from core.rate_limiter import RateLimiter

    limiter = RateLimiter()
    uid = 500

    # Limit'ga yetadi
    for _ in range(3):
        limiter.is_allowed(uid, "login")
    assert limiter.is_allowed(uid, "login") is False

    # Reset
    limiter.reset(uid, "login")
    assert limiter.is_allowed(uid, "login") is True
