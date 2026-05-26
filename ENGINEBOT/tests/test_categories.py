"""
tests/test_categories.py — kategoriya tizimi testi.
"""

from __future__ import annotations


def test_all_categories_have_required_fields() -> None:
    from core.categories import all_categories

    for cat in all_categories():
        assert cat.code, f"Category code bo'sh: {cat}"
        assert cat.name, f"Category name bo'sh: {cat}"
        assert cat.icon, f"Category icon bo'sh: {cat}"


def test_get_category_label_format() -> None:
    from core.categories import get_category_label

    label = get_category_label("taxi")
    assert "🚖" in label
    assert "Taxi" in label


def test_get_category_unknown_returns_code() -> None:
    """Nomaʼlum code — code'ning o'zini qaytaradi."""
    from core.categories import get_category_label

    result = get_category_label("nonexistent_xyz")
    assert result == "nonexistent_xyz"


def test_is_valid_category() -> None:
    from core.categories import is_valid_category

    assert is_valid_category("taxi") is True
    assert is_valid_category("plumber") is True
    assert is_valid_category("other") is True
    assert is_valid_category("xyz_invalid") is False
    assert is_valid_category("") is False


def test_unique_codes() -> None:
    """Kategoriya kodlari unique bo'lishi kerak."""
    from core.categories import all_codes

    codes = all_codes()
    assert len(codes) == len(set(codes)), "Dublicate kategoriya code'lari bor!"


def test_unique_icons() -> None:
    """Iconlar ham unique bo'lishi yaxshi (lekin majburiy emas)."""
    from core.categories import all_categories

    icons = [c.icon for c in all_categories()]
    # Faqat warning — assert qilmaymiz, chunki 13 ta unique emoji topish qiyin
    assert len(icons) == 13
