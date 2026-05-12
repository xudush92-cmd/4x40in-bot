"""sessions.py — Bozor sessiyalari, Toshkent (UTC+5) vaqt zonasi."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

TASHKENT = ZoneInfo("Asia/Tashkent")
NY       = ZoneInfo("America/New_York")

NY_SESSION_OPEN  = time(8, 0)   # NY mahalliy vaqti
NY_SESSION_CLOSE = time(17, 0)  # NY mahalliy vaqti


def now_tashkent() -> datetime:
    return datetime.now(TASHKENT)


def _next_weekday(dt: datetime) -> datetime:
    """Shanba/yakshanba bo'lsa — keyingi dushanbaga o'tkazadi."""
    while dt.weekday() >= 5:  # 5=shanba, 6=yakshanba
        dt += timedelta(days=1)
    return dt


def ny_session_window(now: datetime | None = None):
    """
    Joriy yoki keyingi NY sessiyasining boshlanish/tugash vaqtini
    Toshkent zonasida qaytaradi. Dam olish kunlarini hisobga oladi.
    """
    if now is None:
        now = now_tashkent()

    now_ny = now.astimezone(NY)
    today  = now_ny.date()

    open_ny  = datetime.combine(today, NY_SESSION_OPEN,  tzinfo=NY)
    close_ny = datetime.combine(today, NY_SESSION_CLOSE, tzinfo=NY)

    # Agar bugungi sessiya o'tib ketgan yoki dam olish kuni
    if now_ny >= close_ny or now_ny.weekday() >= 5:
        nxt = _next_weekday(
            (now_ny + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        )
        open_ny  = datetime.combine(nxt.date(), NY_SESSION_OPEN,  tzinfo=NY)
        close_ny = datetime.combine(nxt.date(), NY_SESSION_CLOSE, tzinfo=NY)

    return open_ny.astimezone(TASHKENT), close_ny.astimezone(TASHKENT)


def is_ny_session_active(now: datetime | None = None) -> bool:
    if now is None:
        now = now_tashkent()
    # Dam olish kuni — hech qachon aktiv emas
    if now.astimezone(NY).weekday() >= 5:
        return False
    open_t, close_t = ny_session_window(now)
    return open_t <= now < close_t


def humanize_timedelta(delta: timedelta) -> str:
    total = max(0, int(delta.total_seconds()))
    h, rem = divmod(total, 3600)
    m, _   = divmod(rem, 60)
    if h and m:
        return f"{h} soat {m} daqiqa"
    if h:
        return f"{h} soat"
    return f"{m} daqiqa"


def format_ny_session_info(now: datetime | None = None) -> str:
    if now is None:
        now = now_tashkent()

    now_ny     = now.astimezone(NY)
    is_weekend = now_ny.weekday() >= 5
    open_t, close_t = ny_session_window(now)
    weekday_uz = ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh', 'Ya'][open_t.weekday()]

    if is_weekend:
        wait = humanize_timedelta(open_t - now)
        return (
            "🔴 Dam olish kuni — bozor yopiq\n"
            f"   Keyingi sessiya: {weekday_uz} {open_t.strftime('%H:%M')} (Toshkent)\n"
            f"   Boshlanishiga: {wait}"
        )

    if is_ny_session_active(now):
        remaining = humanize_timedelta(close_t - now)
        return (
            "🟢 Amerika (NY) sessiyasi: OCHIQ\n"
            f"   Tugaydi: {close_t.strftime('%H:%M')} (Toshkent)\n"
            f"   Yana ish vaqti: {remaining}"
        )
    else:
        wait = humanize_timedelta(open_t - now)
        return (
            "🔴 Amerika (NY) sessiyasi: YOPIQ\n"
            f"   Boshlanadi: {weekday_uz} {open_t.strftime('%H:%M')} (Toshkent vaqti)\n"
            f"   Tugaydi:    {weekday_uz} {close_t.strftime('%H:%M')} (Toshkent vaqti)\n"
            f"   Boshlanishiga: {wait}"
        )
