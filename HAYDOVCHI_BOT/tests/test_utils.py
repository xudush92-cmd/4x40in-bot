from datetime import datetime

from utils import (
    MAX_PART_CHARS,
    EntryView,
    RouteView,
    normalize_phone,
    parse_route,
    render_parts,
)

NOW = datetime(2026, 10, 9, 14, 32)


def test_normalize_phone_variants():
    assert normalize_phone("+998 90 123 45 67") == "+998901234567"
    assert normalize_phone("998901234567") == "+998901234567"
    assert normalize_phone("90 123 45 67") == "+998901234567"
    assert normalize_phone("901234567") == "+998901234567"


def test_normalize_phone_invalid():
    assert normalize_phone("") is None
    assert normalize_phone("12345") is None
    assert normalize_phone("+7 999 123 45 67") is None


def test_parse_route_separators():
    assert parse_route("Toshkent - Qibray") == ("Toshkent", "Qibray")
    assert parse_route("Toshkent->Qibray") == ("Toshkent", "Qibray")
    assert parse_route("Toshkent → Qibray") == ("Toshkent", "Qibray")


def test_parse_route_invalid():
    assert parse_route("Toshkent") is None
    assert parse_route("Toshkent -") is None
    assert parse_route("- Qibray") is None
    assert parse_route("A - B - C") is None


def test_render_empty_routes():
    parts = render_parts([], NOW)
    assert len(parts) == 1
    assert "Hozircha ochiq yo'nalish yo'q" in parts[0]


def test_render_contains_full_info():
    routes = [
        RouteView(
            title="Toshkent → Qibray",
            entries=[EntryView("Ali Valiyev", "+998901234567", 2)],
        ),
        RouteView(title="Parkent → Toshkent", entries=[]),
    ]
    (text,) = render_parts(routes, NOW)
    assert "14:32" in text
    assert "Toshkent → Qibray" in text
    assert "Ali Valiyev" in text
    assert "+998901234567" in text
    assert "2 ta bo'sh" in text
    assert "Hozircha faol haydovchi yo'q" in text
    assert "Faol haydovchilar: 1 ta" in text


def test_zero_seats_shown_as_full():
    routes = [RouteView("A → B", [EntryView("Ali", "+998901234567", 0)])]
    (text,) = render_parts(routes, NOW)
    assert "to'ldi" in text


def test_split_keeps_routes_whole_and_under_limit():
    routes = []
    for i in range(60):
        routes.append(
            RouteView(
                title=f"Shahar{i} → Qishloq{i}",
                entries=[EntryView(f"Haydovchi Familiya{i}", "+998901234567", 3)] * 3,
            )
        )
    parts = render_parts(routes, NOW)
    assert len(parts) > 1
    for p in parts:
        assert len(p) <= 4096
    # har bir yo'nalish faqat bitta bo'lakda uchraydi
    for i in range(60):
        hits = [p for p in parts if f"Shahar{i} →" in p]
        assert len(hits) == 1
    # qismlar raqamlanadi
    assert f"(1/{len(parts)}-qism)" in parts[0]
    assert all(len(p) <= MAX_PART_CHARS + 300 for p in parts)
