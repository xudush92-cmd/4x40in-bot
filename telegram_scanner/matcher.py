"""Ko'p so'zli kalit bo'yicha foizli (kamida 70%) moslashtirish.

Bitta kalit = bitta so'z emas — 2 tadan 10 tagacha (yoki undan ko'p)
so'zdan iborat to'plam. Masalan 8 so'zli kalit:

    "toshkentdan samarqandga odam bor mashina kerak ertaga"

Qoida: kalitdagi so'zlarning kamida 70% i xabarda topilsa, xabar
haqida xabar (notification) beriladi. So'zlar soni bo'yicha:

    kalitda  7 ta so'z -> kamida 5 tasi topilishi kerak (71%)
    kalitda 10 ta so'z -> kamida 7 tasi topilishi kerak (70%)
    kalitda  3 ta so'z -> 3 tasi ham kerak (2/3 = 66% < 70%)
    kalitda  2 ta so'z -> 2 tasi ham kerak (1/2 = 50% < 70%)

Qo'shimcha imkoniyatlar (jonli yozuvlarni o'tkazib yubormaslik uchun):
  * tartib va oradagi boshqa so'zlar ahamiyatsiz;
  * katta/kichik harf, tinish belgilari hisobga olinmaydi;
  * so'z shakllari ham taniladi: "odam" ~ "odamlar",
    "toshkentdan" ~ "toshkentga" (umumiy o'zak bo'yicha).
"""

import math
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Standart chegara: 70%. config.py dagi MATCH_THRESHOLD bilan o'zgartiriladi.
DEFAULT_THRESHOLD = 0.70

_TOKEN_RE = re.compile(r"[^\W_]+(?:['’ʻʼ][^\W_]+)*", re.UNICODE)
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʻ": "'", "ʼ": "'", "`": "'"})


@dataclass
class MatchResult:
    phrase: str
    matched_words: list[str] = field(default_factory=list)
    total_words: int = 0
    threshold: float = DEFAULT_THRESHOLD

    @property
    def matched_count(self) -> int:
        return len(self.matched_words)

    @property
    def ratio(self) -> float:
        return self.matched_count / self.total_words if self.total_words else 0.0

    @property
    def percent(self) -> int:
        return round(self.ratio * 100)

    @property
    def is_match(self) -> bool:
        return self.total_words >= 2 and self.ratio >= self.threshold


def normalize_tokens(text: str) -> list[str]:
    """Matnni kichik harfli so'zlar ro'yxatiga aylantiradi."""
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower().translate(_APOSTROPHES))


def normalize_text(text: str) -> str:
    return " ".join(normalize_tokens(text))


def required_count(total_words: int, threshold: float = DEFAULT_THRESHOLD) -> int:
    """70% ga yetish uchun nechta so'z topilishi kerakligi (yuqoriga yaxlitlanadi)."""
    if total_words < 2:
        return total_words
    return math.ceil(threshold * total_words)


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
    # toshkentdan ~ toshkentga: uzun umumiy o'zak
    prefix = _common_prefix_len(key_word, message_word)
    if prefix >= 5 and prefix >= 0.75 * min(len(key_word), len(message_word)):
        return True
    # kichik yozuv xatolari: toshkentdan ~ toshketdan
    if (
        min(len(key_word), len(message_word)) >= 5
        and SequenceMatcher(None, key_word, message_word).ratio() >= 0.85
    ):
        return True
    return False


def match_score(
    message_text: str,
    phrase: str,
    threshold: float = DEFAULT_THRESHOLD,
) -> MatchResult:
    """Xabar va kalit o'xshashligini hisoblaydi (match bo'lmasa ham)."""
    # Takroriy so'zlar kalitda bir marta hisoblanadi
    key_tokens = list(dict.fromkeys(normalize_tokens(phrase)))
    result = MatchResult(phrase=phrase, total_words=len(key_tokens), threshold=threshold)
    if len(key_tokens) < 2:
        return result

    message_tokens = set(normalize_tokens(message_text))
    if not message_tokens:
        return result

    result.matched_words = [
        word
        for word in key_tokens
        if any(_word_matches(word, msg_word) for msg_word in message_tokens)
    ]
    return result


def phrase_matches(
    message_text: str,
    phrase: str,
    threshold: float = DEFAULT_THRESHOLD,
) -> bool:
    """Kalit so'zlarining kamida `threshold` (70%) qismi xabarda bormi?"""
    return match_score(message_text, phrase, threshold).is_match


def find_match(
    message_text: str,
    phrases,
    threshold: float = DEFAULT_THRESHOLD,
) -> MatchResult | None:
    """Eng yuqori o'xshashlikdagi (≥70%) kalitni qaytaradi, topilmasa None.

    Bir nechta kalit mos kelsa, foizi eng kattasi tanlanadi
    (teng bo'lsa — so'zi ko'proq topilgani).
    """
    best: MatchResult | None = None
    for phrase in phrases:
        result = match_score(message_text, phrase, threshold)
        if not result.is_match:
            continue
        if best is None or (result.ratio, result.matched_count) > (
            best.ratio,
            best.matched_count,
        ):
            best = result
    return best
