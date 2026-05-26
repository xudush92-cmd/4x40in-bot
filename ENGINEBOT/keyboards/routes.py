"""
keyboards/routes.py — O'zbekiston viloyatlari (taxi plugin uchun).

Eng koʻp ishlatiladigan yoʻnalishlar uchun tezkor tanlash.
Plugin'ga bogʻliq ravishda kategoriya boshqacha boʻlishi mumkin
(masalan koʻchmas mulk uchun tumanlar) — lekin taxi MVP uchun shu yetadi.
"""

from __future__ import annotations

from keyboards.common_kb import inline_grid, Btn

# ─────────────────────────────────────────────────────────────────────
# O'zbekiston viloyatlari va shaharlari
# ─────────────────────────────────────────────────────────────────────
REGIONS: list[tuple[str, str]] = [
    ("🏛 Toshkent sh.", "tashkent_city"),
    ("🌆 Toshkent v.", "tashkent_region"),
    ("🕌 Samarqand", "samarkand"),
    ("🌹 Buxoro", "bukhara"),
    ("🌄 Andijon", "andijan"),
    ("🌳 Fargʻona", "fergana"),
    ("🌻 Namangan", "namangan"),
    ("🐫 Xorazm", "khorezm"),
    ("⛰ Qashqadaryo", "qashqadaryo"),
    ("🏔 Surxondaryo", "surxondaryo"),
    ("🌾 Sirdaryo", "sirdaryo"),
    ("🌅 Jizzax", "jizzakh"),
    ("⚒ Navoiy", "navoiy"),
    ("🏞 Qoraqalpogʻiston", "karakalpakstan"),
]


# ID → Display name
REGION_NAMES: dict[str, str] = {code: name for name, code in REGIONS}


def get_region_name(code: str) -> str:
    """Code'dan koʻrinadigan nomni olish (emoji bilan)."""
    return REGION_NAMES.get(code, code)


def get_region_clean_name(code: str) -> str:
    """Emoji'siz nom (e'lon matni uchun)."""
    name = REGION_NAMES.get(code, code)
    # Birinchi space dan keyingi qism
    parts = name.split(" ", 1)
    return parts[1] if len(parts) > 1 else name


# ─────────────────────────────────────────────────────────────────────
# Region tanlash inline keyboard
# ─────────────────────────────────────────────────────────────────────
def regions_keyboard(
    callback_prefix: str,
    *,
    exclude: str | None = None,
    columns: int = 2,
):
    """
    Viloyatlar inline keyboard.

    callback_prefix : masalan "from_region" → "from_region:tashkent_city"
    exclude         : 'qaerga' tanlashda 'qaerdan' viloyatini ko'rsatmaslik
    columns         : ustunlar soni

    Returns: InlineKeyboardMarkup
    """
    items = [
        (name, f"{callback_prefix}:{code}")
        for name, code in REGIONS
        if code != exclude
    ]
    return inline_grid(
        items,
        columns=columns,
        extra_rows=[[(Btn.BACK, f"{callback_prefix}:back")]],
    )


# ─────────────────────────────────────────────────────────────────────
# Vaqt tanlash (taxi: "qachon ketmoqchisiz?")
# ─────────────────────────────────────────────────────────────────────
TIME_PRESETS: list[tuple[str, str]] = [
    ("🚀 Hozir", "now"),
    ("⏰ 1 soatdan keyin", "in_1h"),
    ("⏰ 2 soatdan keyin", "in_2h"),
    ("📅 Bugun kechqurun", "today_evening"),
    ("📅 Ertaga", "tomorrow"),
    ("📅 Indinga", "day_after"),
    ("✏️ Boshqa vaqt", "custom"),
]


def time_keyboard(callback_prefix: str = "departure_time"):
    """Vaqt tanlash inline keyboard."""
    items = [(name, f"{callback_prefix}:{code}") for name, code in TIME_PRESETS]
    return inline_grid(
        items,
        columns=1,
        extra_rows=[[(Btn.BACK, f"{callback_prefix}:back")]],
    )


# ─────────────────────────────────────────────────────────────────────
# Joy soni
# ─────────────────────────────────────────────────────────────────────
def seats_keyboard(callback_prefix: str = "seats", max_seats: int = 7):
    """Bo'sh joy soni tanlash."""
    items = [(str(i), f"{callback_prefix}:{i}") for i in range(1, max_seats + 1)]
    return inline_grid(
        items,
        columns=4,
        extra_rows=[[(Btn.BACK, f"{callback_prefix}:back")]],
    )


# ─────────────────────────────────────────────────────────────────────
# Narx turi
# ─────────────────────────────────────────────────────────────────────
PRICE_TYPES: list[tuple[str, str]] = [
    ("💰 Kelishuv asosida", "negotiable"),
    ("📍 Belgilangan narx", "fixed"),
]


def price_type_keyboard(callback_prefix: str = "price_type"):
    items = [(name, f"{callback_prefix}:{code}") for name, code in PRICE_TYPES]
    return inline_grid(
        items,
        columns=1,
        extra_rows=[[(Btn.BACK, f"{callback_prefix}:back")]],
    )


# ─────────────────────────────────────────────────────────────────────
# Mashina rangi
# ─────────────────────────────────────────────────────────────────────
CAR_COLORS: list[tuple[str, str]] = [
    ("⚪ Oq", "white"),
    ("⚫ Qora", "black"),
    ("🩶 Kulrang", "grey"),
    ("🟦 Koʻk", "blue"),
    ("🟥 Qizil", "red"),
    ("🟫 Jigarrang", "brown"),
    ("🟨 Sariq", "yellow"),
    ("🟩 Yashil", "green"),
    ("✏️ Boshqa", "other"),
]

_CAR_COLOR_NAMES: dict[str, str] = {code: name for name, code in CAR_COLORS}


def get_car_color_name(code: str) -> str:
    return _CAR_COLOR_NAMES.get(code, code)


def car_color_keyboard(callback_prefix: str = "car_color"):
    items = [(name, f"{callback_prefix}:{code}") for name, code in CAR_COLORS]
    return inline_grid(
        items,
        columns=2,
        extra_rows=[[(Btn.BACK, f"{callback_prefix}:back")]],
    )
