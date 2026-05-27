"""
utils/formatters.py — eʼlon va xabar matnlarini formatlash.

MAQSAD:
───────
Plugin yozgan content_data dict'ini guruhda chiqadigan chiroyli
matnga aylantirish. Telegram HTML formatdan foydalaniladi (parse_mode=HTML).

PRINSIPLAR:
───────────
1. PLUGIN AGNOSTIC: har plugin oʻz template'ini beradi, formatter
   shunchaki placeholder'ni almashtiradi.

2. XAVFSIZ: foydalanuvchi kiritgan matn HTML escape qilinadi
   (XSS himoya, parse error himoyasi).

3. CONSISTENT: barcha eʼlonlar bir xil shaklda — boshlovchi sarlavha
   + bo'lim chiziqlari + brand footer.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Mapping

from config import BRAND_NAME, DEFAULT_TZ_OFFSET, get_brand_footer

# ─────────────────────────────────────────────────────────────────────
# HTML escape (xavfsizlik)
# ─────────────────────────────────────────────────────────────────────
def esc(value: Any) -> str:
    """
    Foydalanuvchi matnini HTML uchun xavfsiz qilish.

    Telegram HTML parse_mode'da <, >, & belgilari maxsus, escape kerak.
    """
    return html.escape(str(value), quote=False)


# ─────────────────────────────────────────────────────────────────────
# Template render
# ─────────────────────────────────────────────────────────────────────
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def render_template(template: str, data: Mapping[str, Any]) -> str:
    """
    Sodda template engine: {key} → data[key] (HTML escape qilingan).

    Template'da {key} koʻrinishidagi placeholder'lar data dict'idan
    olinadi. Topilmagan placeholder boʻsh string bilan almashinadi.

    Misol:
        render_template(
            "🚖 {from_city} → {to_city} ({seats} joy)",
            {"from_city": "Toshkent", "to_city": "Samarqand", "seats": 3},
        )
        → "🚖 Toshkent → Samarqand (3 joy)"
    """
    def _replace(m: re.Match) -> str:
        key = m.group(1)
        return esc(data.get(key, ""))

    return _PLACEHOLDER_RE.sub(_replace, template)


# ─────────────────────────────────────────────────────────────────────
# E'lon karkasi (eng tashqi qism)
# ─────────────────────────────────────────────────────────────────────
def wrap_announcement(
    body: str,
    *,
    is_new: bool = False,
    is_rotated: bool = False,
    rotation_count: int = 0,
    contact_buttons: bool = False,
) -> str:
    """
    Eʼlon body'ini katta karkasga oʻrash.

    Format:
        🆕 YANGI EʼLON  (yoki 🔄 YANGILANGAN)
        ━━━━━━━━━━━━━━━━━━

        <body>

        ━━━━━━━━━━━━━━━━━━
        🕐 Joylangan: 14:23
        ⚙️ ENGINEBOT — ...
    """
    header = ""
    if is_new:
        header = "🆕 <b>YANGI EʼLON</b>"
    elif is_rotated:
        header = f"🔄 <b>YANGILANGAN</b>" + (
            f" ({rotation_count} marta)" if rotation_count > 1 else ""
        )

    parts: list[str] = []
    if header:
        parts.append(header)
        parts.append("━━━━━━━━━━━━━━━━━━")
        parts.append("")

    parts.append(body.rstrip())
    parts.append("")
    parts.append("━━━━━━━━━━━━━━━━━━")
    parts.append(f"🕐 {now_uz_str()}")
    parts.append(get_brand_footer().lstrip("\n"))

    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────
# Vaqt formatlash (UZ)
# ─────────────────────────────────────────────────────────────────────
_UZ_TZ = timezone(timedelta(hours=DEFAULT_TZ_OFFSET))


def now_uz() -> datetime:
    """Hozirgi vaqt UZ TZ da."""
    return datetime.now(_UZ_TZ)


def now_uz_str(fmt: str = "%H:%M") -> str:
    return now_uz().strftime(fmt)


def format_datetime(dt: datetime | str | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    if dt is None:
        return "—"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt
    return dt.strftime(fmt)


def format_date(dt: datetime | str | None) -> str:
    return format_datetime(dt, "%d.%m.%Y")


def format_relative(dt: datetime | str | None) -> str:
    """
    "5 daq oldin", "2 soat oldin", "3 kun oldin" formatda.
    """
    if dt is None:
        return "—"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UZ_TZ)

    delta = now_uz() - dt
    total_sec = int(delta.total_seconds())

    if total_sec < 0:
        return f"keyinchalik"
    if total_sec < 60:
        return "hozirgina"
    if total_sec < 3600:
        return f"{total_sec // 60} daq oldin"
    if total_sec < 86400:
        return f"{total_sec // 3600} soat oldin"
    if total_sec < 30 * 86400:
        return f"{total_sec // 86400} kun oldin"
    if total_sec < 365 * 86400:
        return f"{total_sec // (30 * 86400)} oy oldin"
    return f"{total_sec // (365 * 86400)} yil oldin"


# ─────────────────────────────────────────────────────────────────────
# Statistika kartochka
# ─────────────────────────────────────────────────────────────────────
def format_stats_card(title: str, items: Dict[str, Any]) -> str:
    """
    Statistika kartochkasi:

    📊 <title>
    ━━━━━━━━━━━
    • Key 1: Value 1
    • Key 2: Value 2
    """
    lines = [f"📊 <b>{esc(title)}</b>", "━━━━━━━━━━━━━━━━━━"]
    for k, v in items.items():
        lines.append(f"   • <b>{esc(k)}:</b> {esc(v)}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# Foydalanuvchi profili (UI uchun)
# ─────────────────────────────────────────────────────────────────────
def format_user_short(user: Mapping[str, Any]) -> str:
    """Qisqa user info (bir qatorda)."""
    name = esc(user.get("full_name") or user.get("username") or f"#{user.get('user_id')}")
    uid = user.get("user_id", "?")
    phone = user.get("phone", "")
    parts = [name, f"#{uid}"]
    if phone:
        parts.append(esc(phone))
    return " | ".join(parts)


def format_user_card(user: Mapping[str, Any]) -> str:
    """Toʻliq user kartochkasi."""
    lines = [
        f"👤 <b>{esc(user.get('full_name', 'Nomaʼlum'))}</b>",
        f"🆔 ID: <code>{user.get('user_id')}</code>",
    ]
    if user.get("username"):
        lines.append(f"📎 @{esc(user['username'])}")
    if user.get("phone"):
        lines.append(f"📱 {esc(user['phone'])}")

    status = user.get("status", "?")
    status_emoji = {"active": "🟢", "pending": "🟡", "blocked": "🔴"}.get(status, "❓")
    lines.append(f"{status_emoji} Holat: {status}")

    if user.get("warnings_count", 0) > 0:
        lines.append(f"⚠️ Ogohlantirishlar: {user['warnings_count']}")

    if user.get("rating") is not None:
        rating = float(user["rating"])
        stars = "⭐" * int(rating)
        lines.append(f"{stars} Reyting: {rating:.1f}")

    if user.get("created_at"):
        lines.append(f"📅 Roʻyxat: {format_date(user['created_at'])}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# Tenant kartochkasi
# ─────────────────────────────────────────────────────────────────────
def format_tenant_card(tenant: Mapping[str, Any], stats: Mapping[str, Any] | None = None) -> str:
    """Super admin uchun tenant batafsil kartochkasi."""
    status = tenant.get("status", "?")
    status_emoji = {
        "active": "🟢",
        "pending": "🟡",
        "paused": "⏸",
        "blocked": "🔴",
        "deleted": "🗑",
    }.get(status, "❓")

    lines = [
        f"🏢 <b>{esc(tenant.get('name', 'Nomaʼlum'))}</b>",
        f"🆔 ID: <code>{tenant.get('tenant_id')}</code>",
    ]
    if tenant.get("username"):
        lines.append(f"📎 @{esc(tenant['username'])}")
    if tenant.get("phone"):
        lines.append(f"📱 {esc(tenant['phone'])}")

    lines.append(f"{status_emoji} Holat: {status}")
    lines.append(f"📦 Tarif: <b>{tenant.get('tariff', '?').upper()}</b>")

    if tenant.get("paid_until"):
        lines.append(f"📅 Muddat: {format_date(tenant['paid_until'])}")

    # PULSIZ model — total_paid_uzs ko'rsatilmaydi (faqat audit/tarix uchun bor).

    if tenant.get("blocked_reason"):
        lines.append(f"🚫 Block sababi: {esc(tenant['blocked_reason'])}")

    if tenant.get("created_at"):
        lines.append(f"🕐 Qoʻshilgan: {format_date(tenant['created_at'])}")

    if stats:
        lines.append("")
        lines.append("📊 <b>Statistika:</b>")
        lines.append(f"   • Foydalanuvchilar: {stats.get('users_total', 0)} ta")
        lines.append(f"   • Aktiv eʼlonlar: {stats.get('posts_active', 0)} ta")
        lines.append(f"   • Kanallar: {stats.get('channels_active', 0)} ta")

    return "\n".join(lines)
