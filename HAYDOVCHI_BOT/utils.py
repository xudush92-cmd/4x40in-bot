"""
utils.py — yordamchi (sof) funksiyalar. Telegram yoki bazaga bog'liq emas,
shuning uchun testlash oson.

- normalize_phone  : telefonni +998XXXXXXXXX ko'rinishiga keltiradi
- parse_route      : "Toshkent - Qibray" matnini (qayerdan, qayerga) ga ajratadi
- render_parts     : guruh oynasi matnini 4096 belgilik bo'laklarga bo'ladi
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Telegram xabar chegarasi 4096. Xavfsizlik uchun 3800 atrofida bo'lamiz.
MAX_PART_CHARS = 3800

# Toshkent vaqti (UTC+5, yoz-qish vaqti yo'q)
LOCAL_TZ = timezone(timedelta(hours=5))

SEAT_OPTIONS = list(range(0, 9))  # 0..8 ta bo'sh joy


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def normalize_phone(raw: str) -> str | None:
    """
    Telefonni +998XXXXXXXXX ko'rinishiga keltiradi.
    Qabul qiladi: "+998 90 123 45 67", "998901234567", "90 123 45 67", "901234567".
    Noto'g'ri bo'lsa None qaytaradi.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 9:
        digits = "998" + digits
    if len(digits) == 12 and digits.startswith("998"):
        return "+" + digits
    return None


_ROUTE_SPLIT = re.compile(r"\s*(?:->|→|—|–|-|>|/|\|)\s*")


def parse_route(text: str) -> tuple[str, str] | None:
    """
    "Toshkent - Qibray" -> ("Toshkent", "Qibray")
    Ajratuvchilar: -, –, —, ->, >, →, /, |
    Ikki qism bo'lmasa yoki bo'sh bo'lsa None.
    """
    if not text:
        return None
    parts = _ROUTE_SPLIT.split(text.strip())
    if len(parts) != 2:
        return None
    a, b = parts[0].strip(), parts[1].strip()
    if not a or not b:
        return None
    return a, b


def seats_label(seats: int) -> str:
    if seats <= 0:
        return "🔴 to'ldi"
    return f"🪑 {seats} ta bo'sh"


@dataclass
class EntryView:
    """Oynada ko'rsatiladigan bitta haydovchi yozuvi."""
    driver_name: str
    phone: str
    seats: int


@dataclass
class RouteView:
    """Bitta yo'nalish va unda faol haydovchilar."""
    title: str  # "Toshkent → Qibray"
    entries: list[EntryView]


def _route_block(route: RouteView) -> str:
    lines = [f"📍 {route.title}"]
    if not route.entries:
        lines.append("   ⚪ Hozircha faol haydovchi yo'q")
    else:
        for e in route.entries:
            lines.append(f"   👤 {e.driver_name}  📞 {e.phone}  {seats_label(e.seats)}")
    return "\n".join(lines)


def _header(updated_at: datetime, active_count: int, part_no: int, total: int) -> str:
    title = "🚗 HAYDOVCHILAR MA'LUMOTI"
    if total > 1:
        title += f" ({part_no}/{total}-qism)"
    return (
        f"{title}\n"
        f"🕐 Yangilangan: {updated_at.strftime('%H:%M')} | "
        f"🟢 Faol haydovchilar: {active_count} ta"
    )


def render_parts(
    routes: list[RouteView],
    updated_at: datetime,
    max_chars: int = MAX_PART_CHARS,
) -> list[str]:
    """
    Yo'nalishlarni bo'laklarga bo'ladi. Bitta yo'nalish ikkiga bo'linmaydi.
    Har bo'lakning boshida sarlavha bo'ladi. Bo'sh ro'yxat uchun ham bitta bo'lak qaytadi.
    """
    active_count = sum(len(r.entries) for r in routes)

    if not routes:
        body = "⚪ Hozircha ochiq yo'nalish yo'q."
        return [_header(updated_at, 0, 1, 1) + "\n" + "━" * 20 + "\n" + body]

    # 1-bosqich: yo'nalish bloklarini ajratish
    blocks = [_route_block(r) for r in routes]

    # 2-bosqich: bloklarni bo'laklarga yig'ish
    # Sarlavha uzunligini taxminan hisobga olamiz (keyin qayta tekshiramiz)
    sep = "\n\n"
    groups: list[list[str]] = [[]]
    for block in blocks:
        current = groups[-1]
        candidate = sep.join(current + [block])
        # sarlavha ~150 belgi deb hisoblaymiz
        if current and len(candidate) + 150 > max_chars:
            groups.append([block])
        else:
            current.append(block)

    total = len(groups)
    parts = []
    for i, group in enumerate(groups, start=1):
        head = _header(updated_at, active_count, i, total)
        parts.append(head + "\n" + "━" * 20 + "\n\n" + sep.join(group))
    return parts
