"""Bozor sessiyalari — vaqtni Toshkent (UTC+5) zonasiga o'girish."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

TASHKENT = ZoneInfo("Asia/Tashkent")
NY = ZoneInfo("America/New_York")

NY_SESSION_OPEN = time(8, 0)    # NY mahalliy vaqti — sessiya boshlanishi
NY_SESSION_CLOSE = time(17, 0)  # NY mahalliy vaqti — sessiya tugashi


def now_tashkent() -> datetime:
    return datetime.now(TASHKENT)


def ny_session_window(now: datetime | None = None):
    """Joriy yoki keyingi NY sessiyasining boshlanish/tugash vaqtini Toshkent zonasida qaytaradi.

    Agar bugungi NY sessiyasi hali tugamagan bo'lsa — bugungi sessiyani qaytaradi.
    Aks holda — ertangi sessiyani.
    """
    if now is None:
        now = now_tashkent()
    now_ny = now.astimezone(NY)
    today = now_ny.date()
    open_ny = datetime.combine(today, NY_SESSION_OPEN, tzinfo=NY)
    close_ny = datetime.combine(today, NY_SESSION_CLOSE, tzinfo=NY)
    if now_ny >= close_ny:
        nxt = today + timedelta(days=1)
        open_ny = datetime.combine(nxt, NY_SESSION_OPEN, tzinfo=NY)
        close_ny = datetime.combine(nxt, NY_SESSION_CLOSE, tzinfo=NY)
    return open_ny.astimezone(TASHKENT), close_ny.astimezone(TASHKENT)


def is_ny_session_active(now: datetime | None = None) -> bool:
    if now is None:
        now = now_tashkent()
    open_t, close_t = ny_session_window(now)
    if now < open_t:
        return False
    return open_t <= now < close_t


def humanize_timedelta(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 0:
        total = 0
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    if h and m:
        return f"{h} soat {m} daqiqa"
    if h:
        return f"{h} soat"
    return f"{m} daqiqa"


def format_ny_session_info(now: datetime | None = None) -> str:
    if now is None:
        now = now_tashkent()
    open_t, close_t = ny_session_window(now)
    weekday_uz = ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh', 'Ya'][open_t.weekday()]

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
            f"   Tugaydi:   {weekday_uz} {close_t.strftime('%H:%M')} (Toshkent vaqti)\n"
            f"   Boshlanishiga: {wait}"
        )
