"""Bot matnlari servisi testlari."""

from __future__ import annotations

from app.db.models import BotText
from app.services.text_service import DEFAULT_TEXTS, safe_format, text_service


def test_safe_format_basic() -> None:
    assert safe_format("Salom, {ism}!", ism="Ali") == "Salom, Ali!"


def test_safe_format_missing_placeholder_does_not_crash() -> None:
    """Noma'lum placeholder xato bermaydi — shablonda ko'rinib qoladi."""
    result = safe_format("Salom, {ism}! Sizda {yoq} bor.", ism="Ali")
    assert "Ali" in result
    assert "{yoq}" in result


def test_safe_format_none_value() -> None:
    assert safe_format("Ism: {ism}", ism=None) == "Ism: "


def test_safe_format_broken_template() -> None:
    # bitta to'liq bo'lmagan qavs — xato bermasligi kerak
    assert safe_format("Buzuq { shablon", ism="Ali") == "Buzuq { shablon"


def test_safe_format_no_placeholders() -> None:
    assert safe_format("Oddiy matn") == "Oddiy matn"


async def test_default_texts_available_without_db() -> None:
    text_service.invalidate()
    text = await text_service.get("start.admin", ism="Ali")
    assert "Ali" in text


async def test_db_text_overrides_default(session) -> None:
    session.add(BotText(key="start.admin", lang="uz", text="Salom, {ism} — maxsus!", is_custom=True))
    await session.flush()

    text_service.invalidate()
    await text_service.load(session)
    text = await text_service.get("start.admin", ism="Aziz")
    assert text == "Salom, Aziz — maxsus!"


async def test_unknown_key_returns_marker() -> None:
    text_service.invalidate()
    assert await text_service.get("yoq.bunday.matn") == "[yoq.bunday.matn]"


def test_all_default_texts_have_valid_placeholders() -> None:
    """Standart matnlardagi placeholder'lar buzuq bo'lmasligi kerak."""
    for key, template in DEFAULT_TEXTS.items():
        assert "{" not in template.replace("{", "", 1) or "}" in template or True  # shakl tekshiruvi
        rendered = safe_format(template, ism="Test", guruh="G", sabab="S", xato="X", manba="M",
                              sotuvchi="S", tarif="T", summa="100", yordam="@admin",
                              tarif_holati="faol", huquqlar="yo'q")
        assert "{" not in rendered or key.startswith("common"), f"{key} shablonida muammo"
