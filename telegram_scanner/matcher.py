"""Kalit so'zlar to'plami bo'yicha moslashtirish (foizsiz).

Har bir so'z — alohida kalit. Bitta to'plam 2 tadan 10 tagacha
so'zdan iborat bo'ladi, masalan:

    to'plam:  toshkent samarqand odam mashina kerak yuk bugun (7 so'z)
    shart:    3 ta so'z uchrasa xabar ber

Xabarda to'plamdagi so'zlardan belgilangan soni (2 yoki 3 ta —
foydalanuvchi to'plam yaratishda tanlaydi) topilsa, xabar haqida
xabar beriladi. Foiz hisoblanmaydi.

Qo'shimcha imkoniyatlar:
  * tartib va oradagi boshqa so'zlar ahamiyatsiz;
  * katta/kichik harf, tinish belgilari hisobga olinmaydi;
  * so'z shakllari ham taniladi: "odam" ~ "odamlar",
    "toshkentdan" ~ "toshkentga" (umumiy o'zak bo'yicha).
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

MIN_WORDS = 2
MAX_WORDS = 10

_TOKEN_RE = re.compile(r"[^\W_]+(?:['’ʻʼ][^\W_]+)*", re.UNICODE)
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʻ": "'", "ʼ": "'", "`": "'"})


@dataclass
class MatchResult:
    phrase: str  # to'plam matni (so'zlar bo'shliq bilan)
    required_count: int = 2  # xabar berish uchun kerakli so'zlar soni
    matched_words: list[str] = field(default_factory=list)
    total_words: int = 0

    @property
    def matched_count(self) -> int:
        return len(self.matched_words)

    @property
    def is_match(self) -> bool:
        return (
            self.total_words >= MIN_WORDS
            and self.matched_count >= self.required_count
        )


def normalize_tokens(text: str) -> list[str]:
    """Matnni kichik harfli so'zlar ro'yxatiga aylantiradi."""
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower().translate(_APOSTROPHES))


def normalize_text(text: str) -> str:
    return " ".join(normalize_tokens(text))


def parse_key_words(text: str) -> list[str]:
    """Foydalanuvchi yuborgan matndan to'plam so'zlarini ajratadi.

    So'zlar bo'shliq, vergul yoki yangi qator bilan ajratilishi mumkin.
    Takroriy so'zlar bir marta olinadi.
    """
    cleaned = (text or "").replace(",", " ").replace(";", " ")
    return list(dict.fromkeys(normalize_tokens(cleaned)))


def validate_key_words(words: list[str]) -> str | None:
    """To'plam so'zlarini tekshiradi. Xato bo'lsa matn, bo'lmasa None."""
    if len(words) < MIN_WORDS:
        return (
            f"⚠️ To'plamda kamida {MIN_WORDS} ta kalit so'z bo'lishi kerak. "
            "So'zlarni bo'shliq bilan yozing, masalan: "
            "<i>toshkent samarqand odam mashina</i>"
        )
    if len(words) > MAX_WORDS:
        return (
            f"⚠️ Bitta to'plamda ko'pi bilan {MAX_WORDS} ta so'z bo'ladi, "
            f"siz {len(words)} ta yozdingiz. Ortiqchasini olib tashlang."
        )
    return None


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


def match_key_set(
    message_text: str,
    key_words,
    required_count: int = 2,
) -> MatchResult:
    """Xabarda to'plamdan nechta so'z topilganini hisoblaydi.

    key_words — so'zlar ro'yxati yoki bo'shliqli matn bo'lishi mumkin.
    """
    if isinstance(key_words, str):
        words = parse_key_words(key_words)
        phrase_text = key_words
    else:
        words = list(dict.fromkeys(key_words))
        phrase_text = " ".join(words)

    required = max(MIN_WORDS, min(int(required_count or 2), len(words) or 2))
    result = MatchResult(
        phrase=phrase_text,
        required_count=required,
        total_words=len(words),
    )
    if len(words) < MIN_WORDS:
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


def find_match(message_text: str, key_sets) -> MatchResult | None:
    """Eng ko'p so'zi topilgan to'plamni qaytaradi (sharti bajarilgani).

    key_sets — (matn, required_count) juftliklari yoki matnlar ro'yxati.
    Bir nechta to'plam shartni bajarsa, eng ko'p so'zi topilgani
    tanlanadi (teng bo'lsa — sharti kichikroq, ya'ni osonroq to'plam).
    """
    best: MatchResult | None = None
    for item in key_sets:
        if isinstance(item, (tuple, list)):
            text, required = item[0], item[1] if len(item) > 1 else 2
        else:
            text, required = item, 2
        result = match_key_set(message_text, text, required)
        if not result.is_match:
            continue
        if best is None or (result.matched_count, -result.required_count) > (
            best.matched_count,
            -best.required_count,
        ):
            best = result
    return best
