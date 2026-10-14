"""Vaqt bilan ishlash yordamchilari.

Butun loyihada **UTC (timezone-aware)** ishlatiladi; foydalanuvchiga
ko'rsatishdan oldingina loyiha vaqt zonasiga o'giriladi.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings


def utcnow() -> datetime:
    """Joriy UTC vaqti (timezone-aware)."""
    return datetime.now(UTC)


def project_tz() -> ZoneInfo:
    """Loyiha vaqt zonasi (.env dagi TIMEZONE)."""
    try:
        return ZoneInfo(get_settings().timezone)
    except (ZoneInfoNotFoundError, ValueError):  # pragma: no cover — noto'g'ri sozlama
        return ZoneInfo("UTC")


def to_local(dt: datetime | None, tz: ZoneInfo | None = None) -> datetime | None:
    """UTC vaqtni loyiha zonasiga o'girish."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz or project_tz())


def fmt_dt(dt: datetime | None, pattern: str = "%d.%m.%Y %H:%M", tz: ZoneInfo | None = None) -> str:
    """Vaqtni o'qishga qulay ko'rinishda chiqarish (lokal zonada)."""
    local = to_local(dt, tz)
    return local.strftime(pattern) if local else "—"


def fmt_date(dt: datetime | None, tz: ZoneInfo | None = None) -> str:
    return fmt_dt(dt, "%d.%m.%Y", tz)


def days_left(until: datetime | None) -> int:
    """Berilgan vaqtgacha necha kun qolgani (manfiy bo'lsa — muddati o'tgan)."""
    if until is None:
        return 0
    delta = until - utcnow()
    return delta.days if delta.total_seconds() >= 0 else -((-delta).days or 1)


def days_word(n: int) -> str:
    """O'zbek tilida "kun" so'zining to'g'ri shakli."""
    n = abs(n) % 100
    if 10 < n < 20:  # 11..19
        return "kun"
    n = n % 10
    if n == 1:
        return "kun"
    return "kun"


def human_delta(dt: datetime | None) -> str:
    """'3 kun 2 soat', '5 daqiqa' kabi o'qishga qulay ko'rinish."""
    if dt is None:
        return "—"
    seconds = int((dt - utcnow()).total_seconds())
    past = seconds < 0
    seconds = abs(seconds)

    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60

    parts: list[str] = []
    if days:
        parts.append(f"{days} kun")
    if hours and len(parts) < 2:
        parts.append(f"{hours} soat")
    if minutes and not parts:
        parts.append(f"{minutes} daqiqa")
    if not parts:
        parts.append("1 daqiqadan kam")

    text = " ".join(parts)
    return f"{text} oldin" if past else text


def next_run_time(interval_sec: int, *, jitter_ratio: float = 0.1, minimum_sec: int = 60) -> datetime:
    """Keyingi joylash vaqtini hisoblash: interval ± jitter (tasodifiy siljish).

    Jitter kerak: bir xil sekundda yuzlab guruhga post ketmasligi uchun.
    """
    import random

    interval = max(minimum_sec, interval_sec)
    delta = interval * (1 + random.uniform(-jitter_ratio, jitter_ratio))
    return utcnow() + timedelta(seconds=max(minimum_sec, int(delta)))


def in_days(days: int) -> datetime:
    return utcnow() + timedelta(days=days)
