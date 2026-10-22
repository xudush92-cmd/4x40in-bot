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

# --- Lotin <-> kirill transliteratsiya (faqat SOLISHTIRISH uchun) ---
# Bitta kalit ikkala alifbodagi xabarni ham topishi uchun har bir so'z
# variantlarga aylantiriladi: asli + boshqa alifbodagi shakli.
_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "ъ": "'",
    "э": "e", "ю": "yu", "я": "ya", "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h",
    "ь": "", "ы": "i", "щ": "shch",
}
_CYRILLIC_CHARS = set(_CYR_TO_LAT)

# Lotin -> kirill: avval ko'p harfli birikmalar, keyin yakka harflar
_LAT_DIGRAPHS = (
    ("o'", "ў"), ("g'", "ғ"),
    ("sh", "ш"), ("ch", "ч"), ("ng", "нг"),
    ("ya", "я"), ("yo", "ё"), ("yu", "ю"), ("ye", "е"),
    ("ts", "ц"),
)
_LAT_TO_CYR = {
    "a": "а", "b": "б", "d": "д", "e": "е", "f": "ф", "g": "г",
    "h": "ҳ", "i": "и", "j": "ж", "k": "к", "l": "л", "m": "м",
    "n": "н", "o": "о", "p": "п", "q": "қ", "r": "р", "s": "с",
    "t": "т", "u": "у", "v": "в", "x": "х", "y": "й", "z": "з",
}


def cyr_to_lat(word: str) -> str:
    return "".join(_CYR_TO_LAT.get(ch, ch) for ch in word)


def lat_to_cyr(word: str) -> str:
    result = word
    for src, dst in _LAT_DIGRAPHS:
        result = result.replace(src, dst)
    return "".join(_LAT_TO_CYR.get(ch, ch) for ch in result)


def _word_variants(word: str) -> set[str]:
    """So'zning solishtirish variantlari: asli + boshqa alifbodagi shakli."""
    variants = {word}
    if any(ch in _CYRILLIC_CHARS for ch in word):
        variants.add(cyr_to_lat(word))
    if any("a" <= ch <= "z" or ch == "'" for ch in word):
        variants.add(lat_to_cyr(word))
    return variants


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
    """Bitta kalit so'z xabardagi so'zga mosmi (shakl o'zgarishlari bilan).

    Lotin/kirill variantlar ham solishtiriladi: lotin kalit kirill
    xabarni ham, kirill kalit lotin xabarni ham topadi.
    """
    key_variants = _word_variants(key_word)
    msg_variants = _word_variants(message_word)
    for kv in key_variants:
        for mv in msg_variants:
            if _word_matches_single(kv, mv):
                return True
    return False


def _word_matches_single(key_word: str, message_word: str) -> bool:
    """Bitta alifbo ichida moslik (shakl o'zgarishlari bilan)."""
    if key_word == message_word:
        return True
    # odam ~ odamlar, kerak ~ kerakmi: xabardagi so'z yozuvdan uzun bo'lsa —
    # yozuv o'zak bo'lib xizmat qiladi.
    if min(len(key_word), len(message_word)) >= 3 and message_word.startswith(
        key_word
    ):
        return True
    # Yozuv xabar so'zidan uzun bo'lsa, faqat qisqa qoldiq (1-2 harf)
    # qabul qilinadi: "ketadi" ~ "ketad", "ikki" ~ "ikk".
    # Aks holda "boramiz" yozuvi xabardagi oddiy "bor" so'zini ham
    # tutib qo'yardi va mijoz xabari bloklanardi.
    if min(len(key_word), len(message_word)) >= 3 and key_word.startswith(
        message_word
    ) and len(key_word) - len(message_word) <= 2:
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


# --- Stop-so'zlar (haydovchi filtri) va mijoz so'zlari ---

def _canon(word: str) -> str:
    """So'zni solishtirish uchun yagona (lotin) ko'rinishga keltiradi."""
    if any(ch in _CYRILLIC_CHARS for ch in word):
        return cyr_to_lat(word)
    return word


def _entry_matches(entry_tokens: list[str], message_tokens: list[str]) -> bool:
    """Bitta yozuv (so'z yoki ibora) xabarda topildimi?

    Ibora — yonma-yon kelgan so'zlar ketma-ketligi sifatida tekshiriladi,
    har bir so'z shakl o'zgarishi bilan solishtiriladi.
    """
    if not entry_tokens or not message_tokens:
        return False
    canon_msg = [_canon(t) for t in message_tokens]
    canon_entry = [_canon(t) for t in entry_tokens]
    if len(canon_entry) == 1:
        return any(_word_matches_single(canon_entry[0], mt) for mt in canon_msg)
    size = len(canon_entry)
    for start in range(len(canon_msg) - size + 1):
        window = canon_msg[start:start + size]
        if all(_word_matches_single(e, m) for e, m in zip(canon_entry, window)):
            return True
    return False


def find_stop_words(message_text: str, stop_words) -> list[str]:
    """Xabardagi stop-so'zlar/iboralar ro'yxati (topilmasa bo'sh).

    Bitta stop-so'z topilsa ham xabar haydovchiniki hisoblanadi.
    """
    message_tokens = normalize_tokens(message_text)
    if not message_tokens:
        return []
    found = []
    for entry in stop_words or []:
        entry_tokens = normalize_tokens(entry)
        if entry_tokens and _entry_matches(entry_tokens, message_tokens):
            found.append(entry)
    return found


def find_client_words(message_text: str, client_words) -> list[str]:
    """Xabardagi mijozga xos so'zlar/iboralar (topilmasa bo'sh)."""
    return find_stop_words(message_text, client_words)


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u20E3]"
)


def contains_emoji(text: str | None) -> bool:
    """Matnda emoji yoki emoji-ega belgisi bormi?

    Haydovchi e'lonlari odatda emoji bilan bezatiladi; mijoz matnida
    emoji bo'lmasligi kutiladi. Shuning uchun emoji alohida belgidir.
    """
    return bool(text and _EMOJI_RE.search(text))


def canonical_entry(text: str | None) -> str:
    """Takroriylikni tekshirish uchun yozuvning yagona shakli.

    Katta-kichik harf, ortiqcha bo'shliq, tinish belgilari va
    lotin/kirill farqi hisobga olinmaydi: ``ТОШКЕНТ`` bilan
    ``toshkent`` bitta yozuv hisoblanadi.
    """
    return " ".join(_canon(token) for token in normalize_tokens(text or ""))
