"""Bot matnlari servisi testlari."""

from __future__ import annotations

import re

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


async def test_default_texts_available_without_db(session) -> None:
    """Bazada yozuv bo'lmasa ham standart matn qaytadi (DB'siz ishlamaydi —
    kesh bo'sh bo'lsa `DEFAULT_TEXTS`ga tushadi)."""
    text_service.invalidate()
    await text_service.load(session)  # baza bo'sh → kesh bo'sh qoladi
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
    """Har bir standart matndagi barcha placeholder'larga qiymat berilsa,
    natijada hech qanday `{...}` qolib ketmasligi kerak.

    Bu matn shabloni bilan kod tomonidagi kalitlar nomuvofiq bo'lsa
    (masalan matnda `{kun}` bor, kod esa `kun` bermasa) darhol ushlaydi.
    """
    placeholders = {
        match for template in DEFAULT_TEXTS.values() for match in re.findall(r"\{(\w+)\}", template)
    }
    assert placeholders, "standart matnlarda placeholder topilmadi"

    values = {name: "TEST" for name in placeholders}
    for key, template in DEFAULT_TEXTS.items():
        rendered = safe_format(template, **values)
        assert "{" not in rendered and "}" not in rendered, f"{key}: {rendered[:120]}"
