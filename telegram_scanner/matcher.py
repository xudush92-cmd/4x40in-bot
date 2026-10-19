"""Ko'p so'zli kalit (ibora) bo'yicha xabarlarni moslashtirish.

Bitta kalit = bitta so'z emas, kamida 2 ta so'zdan iborat ibora.
Masalan, kalit: "toshkentdan odam bor"

Xabar quyidagi hollarda MOS hisoblanadi:
  1) Ibora xabarda aynan ketma-ket kelgan bo'lsa:
     "Toshkentdan odam bor, tel: ..."            -> mos
  2) Iboradagi BARCHA so'zlar xabarda bor bo'lsa — tartibi boshqacha
     yoki orasida boshqa so'zlar bo'lsa ham:
     "Odam bor, ertaga Toshkentdan ketaman"      -> mos
     "Toshkentdan ertaga 2 ta odam bor ekan"     -> mos

Kamida bitta so'zi yetishmasa — mos emas:
     "Toshkentdan ketaman" (odam/bor yo'q)       -> mos emas
     "Odam bor" (toshkentdan yo'q)               -> mos emas
"""

import re

# Harf/raqam (lotin, kirill — o'zbekcha harflar bilan) va ichki apostrof
_TOKEN_RE = re.compile(r"[^\W_]+(?:['’ʻʼ][^\W_]+)*", re.UNICODE)
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʻ": "'", "ʼ": "'", "`": "'"})


def normalize_tokens(text: str) -> list[str]:
    """Matnni kichik harfli so'zlar ro'yxatiga aylantiradi.

    Tinish belgilari va ortiqcha bo'shliqlar olib tashlanadi.
    """
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower().translate(_APOSTROPHES))


def normalize_text(text: str) -> str:
    return " ".join(normalize_tokens(text))


def phrase_matches(message_text: str, phrase: str) -> bool:
    """Bitta ko'p so'zli kalit xabarga mos keladimi?"""
    phrase_tokens = normalize_tokens(phrase)
    # Kalit kamida 2 ta so'zdan iborat bo'lishi shart (shovqin bo'lmasligi uchun)
    if len(phrase_tokens) < 2:
        return False

    message_tokens = normalize_tokens(message_text)
    if not message_tokens:
        return False

    # 1) Aynan ketma-ket uchrashi
    phrase_norm = " ".join(phrase_tokens)
    if phrase_norm in " ".join(message_tokens):
        return True

    # 2) Barcha kalit so'zlar xabarda borligi (har qanday tartibda/oraliqda)
    return set(phrase_tokens).issubset(message_tokens)


def find_match(message_text: str, phrases) -> str | None:
    """Ro'yxatdagi birinchi mos kelgan iborani qaytaradi (topilmasa None)."""
    for phrase in phrases:
        if phrase_matches(message_text, phrase):
            return phrase
    return None
