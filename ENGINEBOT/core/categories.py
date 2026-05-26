"""
core/categories.py — kategoriyalar (kasblar/sohalar) tizimi.

V1 model: 12 ta standart kategoriya. Tenant kerakligini tanlaydi
(yoki hammasi default'da yoqilgan). Plugin tizimi shart emas — barcha
posterlar bir xil tizimda ishlaydi, faqat oʻz "kasb yorlig'i" bilan.

KENGAYTIRISH:
─────────────
Keyinchalik tenant oʻzi yangi kategoriya qoʻsha oladi (`categories`
DB jadvali tenant_id orqali). Hozircha — faqat standart 12 ta.

USAGE:
──────
    from core.categories import CATEGORIES, get_category, get_category_label

    cat = get_category("taxi")
    label = get_category_label("taxi")  # → "🚖 Taxi"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Category:
    """Bitta kategoriya haqida ma'lumot."""
    code: str          # "taxi", "plumber" — DB'da saqlanadi
    name: str          # "Taxi" — emojisiz ko'rsatish uchun
    icon: str          # "🚖" — emoji
    description: str   # qisqa tavsif (UI'da)

    @property
    def label(self) -> str:
        """UI uchun: "🚖 Taxi" """
        return f"{self.icon} {self.name}"


# ─────────────────────────────────────────────────────────────────────
# 12 ta STANDART kategoriya
# ─────────────────────────────────────────────────────────────────────
# Tartib — eng koʻp uchraydiganidan eng kam uchraydiganigacha.
# Yangi kategoriya qoʻshish — shu yerga oxiriga qoʻshish kifoya.

CATEGORIES: Final[tuple[Category, ...]] = (
    Category(
        code="taxi",
        name="Taxi",
        icon="🚖",
        description="Shaharlararo va shahar ichi taxi xizmati",
    ),
    Category(
        code="cargo",
        name="Yuk tashish",
        icon="🚛",
        description="Yuk tashish, ko'chish xizmati",
    ),
    Category(
        code="builder",
        name="Quruvchi",
        icon="🔨",
        description="Umumiy qurilish ishlari, ta'mirlash",
    ),
    Category(
        code="plumber",
        name="Santexnik",
        icon="🔧",
        description="Suv, kanalizatsiya, sanitar texnika",
    ),
    Category(
        code="electrician",
        name="Elektrik",
        icon="💡",
        description="Elektr o'tkazgich, lampochka, rozetka",
    ),
    Category(
        code="painter",
        name="Bo'yoqchi",
        icon="🎨",
        description="Devor bo'yash, oqlash, rangsozlik",
    ),
    Category(
        code="cleaner",
        name="Tozalovchi",
        icon="🧹",
        description="Uy, ofis, ta'mirdan keyin tozalash",
    ),
    Category(
        code="cook",
        name="Oshpaz",
        icon="👨‍🍳",
        description="To'y, marosim, uyga keluvchi oshpazlar",
    ),
    Category(
        code="tutor",
        name="Repetitor",
        icon="📚",
        description="Maktab, universitet fanlaridan dars",
    ),
    Category(
        code="barber",
        name="Sartarosh",
        icon="💇",
        description="Soch olish, manikur, kosmetik xizmatlar",
    ),
    Category(
        code="photographer",
        name="Fotograf",
        icon="📷",
        description="To'y, marosim, studiya suratlari",
    ),
    Category(
        code="auto_mech",
        name="Auto-usta",
        icon="🚗",
        description="Avtomobil ta'miri, diagnostika, shinamontaj",
    ),
    Category(
        code="other",
        name="Boshqa",
        icon="💼",
        description="Yuqoridagi ro'yxatda yo'q kasb yoki xizmat",
    ),
)


# ─────────────────────────────────────────────────────────────────────
# Tezkor qidiruv uchun lookup map
# ─────────────────────────────────────────────────────────────────────
_BY_CODE: Final[dict[str, Category]] = {c.code: c for c in CATEGORIES}


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────
def get_category(code: str) -> Category | None:
    """Code boʻyicha kategoriya olish (yoki None)."""
    return _BY_CODE.get(code)


def get_category_label(code: str) -> str:
    """UI uchun label: "🚖 Taxi". Kategoriya topilmasa — code qaytaradi."""
    cat = _BY_CODE.get(code)
    return cat.label if cat else code


def get_category_name(code: str) -> str:
    """Faqat nom (emoji'siz)."""
    cat = _BY_CODE.get(code)
    return cat.name if cat else code


def get_category_icon(code: str) -> str:
    """Faqat emoji."""
    cat = _BY_CODE.get(code)
    return cat.icon if cat else "💼"


def is_valid_category(code: str) -> bool:
    """Kategoriya code haqiqiymi (CATEGORIES roʻyxatida bormi)?"""
    return code in _BY_CODE


def all_codes() -> list[str]:
    """Barcha kategoriya kodlari (taxi, plumber, ...)."""
    return [c.code for c in CATEGORIES]


def all_categories() -> list[Category]:
    """Barcha kategoriyalarni roʻyxat sifatida olish."""
    return list(CATEGORIES)
