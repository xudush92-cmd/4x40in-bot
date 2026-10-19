"""Kalit so'zlar bo'yicha moslashtirish (foizsiz, to'plamsiz).

Model:
  * Har bir so'z — bitta alohida kalit. Kalitlar soni CHEKSIZ —
    admin xohlagancha so'z qo'shadi.
  * Admin bitta son belgilaydi: "nechta kalit so'z topilsa xabar ber".
    Masalan, son = 3 bo'lsa, xabarda kalitlardan istalgan 3 tasi
    uchrashi kifoya (qaysi 3 tasi ekanligi muhim emas).

Qo'shimcha imkoniyatlar:
  * so'z tartibi va oradagi boshqa so'zlar ahamiyatsiz;
  * katta/kichik harf, tinish belgilari hisobga olinmaydi;
  * so'z shakllari ham taniladi: "odam" ~ "odamlar",
    "toshkent" ~ "toshkentdan" / "toshkentga" (umumiy o'zak bo'yicha).
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

_TOKEN_RE = re.compile(r"[^\W_]+(?:['’ʻʼ][^\W_]+)*", re.UNICODE)
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʻ": "'", "ʼ": "'", "`": "'"})


@dataclass
class MatchResult:
    required_count: int = 3  # admin belgilagan: nechta so'z topilsa xabar beriladi
    matched_words: list[str] = field(default_factory=list)  # topilgan kalitlar
    total_words: int = 0  # bazadagi jami kalitlar soni

    @property
    def matched_count(self) -> int:
        return len(self.matched_words)

    @property
    def is_match(self) -> bool:
        return self.matched_count >= self.required_count >= 1


def normalize_tokens(text: str) -> list[str]:
    """Matnni kichik harfli so'zlar ro'yxatiga aylantiradi."""
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower().translate(_APOSTROPHES))


def normalize_text(text: str) -> str:
    return " ".join(normalize_tokens(text))


def parse_key_words(text: str) -> list[str]:
    """Foydalanuvchi yuborgan matndan kalit so'zlarni ajratadi.

    So'zlar bo'shliq, vergul yoki yangi qator bilan ajratilishi mumkin.
    Har bir so'z — alohida kalit. Takrorlar bir marta olinadi.
    """
    cleaned = (text or "").replace(",", " ").replace(";", " ")
    return list(dict.fromkeys(normalize_tokens(cleaned)))


def _common_prefix_len(a: str, b: str) -> int:
    n = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        n += 1
    return n


def _word_matches(key_word: str, message_word: str) -> bool:
    """Bitta kalit so'z xabardagi so'zga mosmi (shakl o'zgarishlari bilan)."""
    if key_word == message_word:
        return True
    # odam ~ odamlar, kerak ~ kerakmi: biri ikkinchisining boshi bo'lsa
    if min(len(key_word), len(message_word)) >= 3 and (
        message_word.startswith(key_word) or key_word.startswith(message_word)
    ):
        return True
    # toshkent ~ toshkentdan / toshkentga: uzun umumiy o'zak
    prefix = _common_prefix_len(key_word, message_word)
    if prefix >= 5 and prefix >= 0.75 * min(len(key_word), len(message_word)):
        return True
    # kichik yozuv xatolari: toshkent ~ toshket
    if (
        min(len(key_word), len(message_word)) >= 5
        and SequenceMatcher(None, key_word, message_word).ratio() >= 0.85
    ):
        return True
    return False


def match_keywords(
    message_text: str,
    keywords,
    required_count: int = 3,
) -> MatchResult:
    """Xabarda kalitlardan nechtasi topilganini hisoblaydi.

    keywords — barcha kalit so'zlar ro'yxati (soni cheksiz).
    required_count — admin belgilagan chegara (botda o'zgartiriladi).
    """
    words = list(dict.fromkeys(normalize_tokens(" ".join(keywords or []))))
    try:
        required = int(required_count)
    except (TypeError, ValueError):
        required = 3
    required = max(1, required)

    result = MatchResult(required_count=required, total_words=len(words))
    if not words:
        return result

    message_tokens = set(normalize_tokens(message_text))
    if not message_tokens:
        return result

    result.matched_words = [
        word
        for word in words
        if any(_word_matches(word, msg_word) for msg_word in message_tokens)
    ]
    return result


def find_match(
    message_text: str,
    keywords,
    required_count: int = 3,
) -> MatchResult | None:
    """Chegara bajarilsa MatchResult, bajarilmasa None qaytaradi."""
    result = match_keywords(message_text, keywords, required_count)
    return result if result.is_match else None
