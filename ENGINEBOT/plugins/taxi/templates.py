"""
plugins/taxi/templates.py — taxi e'loni shabloni va render funksiyasi.
"""

from __future__ import annotations

from typing import Mapping

from keyboards.routes import (
    get_car_color_name,
    get_region_clean_name,
    get_region_name,
)
from utils.formatters import esc, format_uzs


# ─────────────────────────────────────────────────────────────────────
# Asosiy taxi e'lon shabloni (HTML)
# ─────────────────────────────────────────────────────────────────────
def render_taxi_post(content: Mapping, user: Mapping) -> str:
    """
    Taxi e'loni rendering.

    content (announcements.content_data dan):
        from_region, to_region (region codes)
        departure_time (label)
        seats (int)
        price_type ("negotiable" | "fixed")
        price_amount (int, agar fixed bo'lsa)

    user (users jadvalidan):
        full_name, phone, profile_data: {car_model, car_color, car_plate}
    """
    profile = user.get("profile_data") or {}
    if isinstance(profile, str):
        # JSON string — DB'dan to'g'ridan kelishi mumkin
        import json
        try:
            profile = json.loads(profile)
        except Exception:
            profile = {}

    car_model = profile.get("car_model", "")
    car_color = profile.get("car_color", "")
    car_plate = profile.get("car_plate", "")

    car_color_name = get_car_color_name(car_color) if car_color else ""

    from_name = get_region_clean_name(content.get("from_region", ""))
    to_name = get_region_clean_name(content.get("to_region", ""))

    departure = content.get("departure_time", "")
    seats = content.get("seats", "?")

    if content.get("price_type") == "fixed" and content.get("price_amount"):
        price_str = format_uzs(int(content["price_amount"]))
    else:
        price_str = "Kelishuv asosida"

    lines = [
        f"🚖 <b>{esc(from_name)} → {esc(to_name)}</b>",
        "",
        f"👤 <b>{esc(user.get('full_name', '?'))}</b>",
    ]

    car_parts = [p for p in [car_model, car_color_name.replace('⚪ ', '').replace('⚫ ', '').replace('🩶 ', '').replace('🟦 ', '').replace('🟥 ', '').replace('🟫 ', '').replace('🟨 ', '').replace('🟩 ', ''), car_plate] if p]
    if car_parts:
        lines.append(f"🚗 {esc(', '.join(car_parts))}")

    lines.append(f"⏰ {esc(departure)}")
    lines.append(f"💺 {seats} ta bo'sh joy")
    lines.append(f"💰 {esc(price_str)}")

    if user.get("phone"):
        lines.append("")
        lines.append(f"📞 <code>{esc(user['phone'])}</code>")

    return "\n".join(lines)


def short_summary(content: Mapping) -> str:
    """Qisqa xulosa (ro'yxatlarda)."""
    from_name = get_region_clean_name(content.get("from_region", ""))
    to_name = get_region_clean_name(content.get("to_region", ""))
    seats = content.get("seats", "?")
    return f"🚖 {from_name} → {to_name} | 💺 {seats}"
