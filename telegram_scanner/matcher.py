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
    "toshkent" ~ "toshkentdan" / "toshkentga" (umumiy o'zak bo'yicha);
  * lotin/kirill alifbosi farqi hisobga olinmaydi, shu jumladan
    "dangasa" yozilgan kirill (ў→у, қ→к, ғ→г, ҳ→х) ham;
  * fe'l shaxsi ajratiladi: "jo'naymiz" (biz) "jo'naysiz" (siz) bilan
    aralashtirilmaydi;
  * stop-so'zlarda so'roq qo'shimchasi ajratiladi: "жой бор" (haydovchi
    e'loni) "жой борми" (mijoz savoli) bilan tenglashtirilmaydi;
  * katta ro'yxatlarda ham tez ishlashi uchun prefiks indeksi ishlatiladi.
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache

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


def _is_cyrillic(word: str) -> bool:
    return any(ch in _CYRILLIC_CHARS for ch in word)


def _lazy_latin(word: str) -> str:
    """Lotin yozuvidagi "dangasalik"ni tenglashtiradi.

    Odamlar kirillni ham, lotinni ham soddalashtirib yozadi:
    ``ў`` o'rniga ``у``, ``қ`` o'rniga ``к``, ``ҳ`` o'rniga ``х``,
    ``o'`` o'rniga ``o`` yoki ``u``. Solishtirishda ikkala tomon ham
    shu yagona shaklga keltiriladi, shunda bitta lotin so'z kirillning
    barcha yozilish variantini topadi.
    """
    w = word.replace("o'", "u").replace("g'", "g")
    return w.replace("q", "k").replace("h", "x")


@lru_cache(maxsize=16384)
def _fold_variants(word: str) -> tuple[str, ...]:
    """So'zning solishtirish uchun yagona (lotin) shakllari.

    ``word`` allaqachon normallashtirilgan (kichik harf, apostrof bir xil).
    """
    base = cyr_to_lat(word) if _is_cyrillic(word) else word
    variants = [base]
    lazy = _lazy_latin(base)
    if lazy not in variants:
        variants.append(lazy)
    plain = base.replace("o'", "o").replace("g'", "g")
    if plain not in variants:
        variants.append(plain)
    return tuple(variants)


# --- Shakl (qo'shimcha) tahlili ---

# 1-shaxs (men/biz) va 2-shaxs (sen/siz) qo'shimchalari. Ular bir-biriga
# tenglashtirilmaydi: "jo'naymiz" (haydovchi) va "jo'naysiz" (mijoz savoli)
# har xil ma'no.
_PERSON_SUFFIXES = (
    ("moqchiman", 0), ("moqchimiz", 0), ("moqchisiz", 1),
    ("yapman", 0), ("yapmiz", 0), ("yapsiz", 1), ("yapsan", 1),
    ("yapdi", None), ("yapdilar", None), ("yapti", None), ("yaptilar", None),
    ("aman", 0), ("amiz", 0), ("asiz", 1), ("asan", 1), ("adilar", None),
    ("adi", None), ("am", 0), ("man", 0), ("miz", 0),
    ("siz", 1), ("san", 1), ("ngiz", 1), ("dilar", None), ("di", None),
)


def _verb_parts(word: str) -> tuple[str, int | None, str]:
    """So'zni o'zak, shaxs va zamonga ajratadi.

    ``("olamiz")`` -> ``("ola", 0, "oddiy")``. Qo'shimcha topilmasa
    o'zak — so'zning o'zi, shaxs — ``None``.

    Zamon muhim: "jo'natamiz" (biz yuboramiz — haydovchi) va
    "jo'natmoqchiman" (yubormoqchiman — mijoz) bir o'zakdan, lekin
    har xil ma'no, shuning uchun ular tenglashtirilmaydi.
    """
    for suffix, person in _PERSON_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            if "moqchi" in suffix:
                tense = "moqchi"
            elif "yap" in suffix:
                tense = "yap"
            else:
                tense = "oddiy"
            return word[: -len(suffix)], person, tense
    return word, None, "oddiy"


_QUESTION_PARTICLE = "mi"


def _is_question_form(word: str) -> bool:
    """So'z so'roq shakldami ("bormi", "керакми")."""
    return word.endswith(_QUESTION_PARTICLE) and len(word) > len(_QUESTION_PARTICLE)


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


def _word_matches(
    key_word: str,
    message_word: str,
    strict_question: bool = False,
) -> bool:
    """Bitta yozuv xabardagi so'zga mosmi (shakl va alifbo o'zgarishlari bilan)."""
    for kv in _fold_variants(key_word):
        for mv in _fold_variants(message_word):
            if _word_matches_single(kv, mv, strict_question=strict_question):
                return True
    return False


def _word_matches_single(
    key_word: str,
    message_word: str,
    strict_question: bool = False,
) -> bool:
    """Bitta alifbo (allaqachon buklangan) ichida moslik.

    ``strict_question`` — so'roq qo'shimchasini qat'iy ajratish. Stop-so'zlar
    uchun yoqiladi: "жой бор" yozuvi "жой борми" savolini bloklamaydi.
    """
    if strict_question and _is_question_form(key_word) != _is_question_form(
        message_word
    ):
        return False
    if key_word == message_word:
        return True

    # Fe'l shaxsi: "olamiz" ~ "olaman" mos, "olamiz" ~ "olasiz" emas.
    key_stem, key_person, key_tense = _verb_parts(key_word)
    msg_stem, msg_person, msg_tense = _verb_parts(message_word)
    if key_person is not None and msg_person is not None:
        if key_person != msg_person:
            return False
        # O'zak AYNAN teng bo'lishi shart: "olamiz" ~ "olaman" (o'zak "ola")
        # mos, lekin "jo'naymiz" (o'zak "jo'na") "jo'natmoqchiman"
        # (o'zak "jo'nat") bilan aralashtirilmaydi — bular boshqa fe'llar.
        if (
            len(key_stem) >= 3
            and key_stem == msg_stem
            and key_tense == msg_tense
        ):
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
    if (
        min(len(key_word), len(message_word)) >= 3
        and key_word.startswith(message_word)
        and len(key_word) - len(message_word) <= 2
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


# --- Tez qidiruv indekslari ---
# Ro'yxat yuzlab/minglab so'zdan iborat bo'lishi mumkin. Har bir kalitni
# har bir xabar so'zi bilan solishtirish (O(n*m)) o'rniga so'zlar
# prefikslari bo'yicha indekslanadi: mos kelishi mumkin bo'lgan kalit
# nomzodlari O(1) aniqlanadi, keyin ular to'liq tekshiriladi.

_MIN_PREFIX = 3


@lru_cache(maxsize=32)
def _build_index(words: tuple[str, ...]):
    """``words`` uchun prefiks indeksi.

    Qaytaradi: (aniq shakl -> id'lar, prefiks -> id'lar, variantlar).
    """
    exact: dict[str, list[int]] = {}
    prefix: dict[str, set[int]] = {}
    variants: list[tuple[str, ...]] = []
    for idx, word in enumerate(words):
        variants.append(_fold_variants(word))
        for variant in variants[-1]:
            exact.setdefault(variant, []).append(idx)
            for size in range(_MIN_PREFIX, len(variant) + 1):
                prefix.setdefault(variant[:size], set()).add(idx)
    return exact, prefix, tuple(variants)


def _candidate_ids(message_word: str, exact, prefix) -> set[int]:
    """Xabar so'ziga o'xshash bo'lishi mumkin bo'lgan kalit id'lari."""
    found: set[int] = set()
    for variant in _fold_variants(message_word):
        found.update(exact.get(variant, ()))
        for size in range(_MIN_PREFIX, len(variant) + 1):
            ids = prefix.get(variant[:size])
            if ids:
                found.update(ids)
        # Yozuv xabar so'zidan uzun bo'lib, dumi 1-2 harf bo'lishi mumkin:
        # "ketadi" ~ "ketad". Buning uchun so'zning o'zi prefiks bo'lib
        # xizmat qiladi — u yuqoridagi tsiklda allaqachon tekshirilgan.
    return found


def _dedup_words(keywords) -> tuple[str, ...]:
    return tuple(dict.fromkeys(normalize_tokens(" ".join(keywords or []))))


def match_keywords(
    message_text: str,
    keywords,
    required_count: int = 3,
) -> MatchResult:
    """Xabarda kalitlardan nechtasi topilganini hisoblaydi.

    keywords — barcha kalit so'zlar ro'yxati (soni cheksiz).
    required_count — admin belgilagan chegara (botda o'zgartiriladi).
    """
    words = _dedup_words(keywords)
    try:
        required = int(required_count)
    except (TypeError, ValueError):
        required = 3
    required = max(1, required)

    result = MatchResult(required_count=required, total_words=len(words))
    if not words:
        return result

    message_tokens = list(dict.fromkeys(normalize_tokens(message_text)))
    if not message_tokens:
        return result

    exact, prefix, _variants = _build_index(words)
    matched: set[int] = set()
    for token in message_tokens:
        for idx in _candidate_ids(token, exact, prefix):
            if idx in matched:
                continue
            if _word_matches(words[idx], token):
                matched.add(idx)
    result.matched_words = [words[i] for i in sorted(matched)]
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
    if _is_cyrillic(word):
        return cyr_to_lat(word)
    return word


@lru_cache(maxsize=32)
def _build_entry_index(entries: tuple[str, ...]):
    """Stop/mijoz ro'yxati uchun indeks.

    Bir so'zli yozuvlar prefiks indeksiga tushadi, iboralar (bir necha
    so'z) alohida ro'yxatda qoladi.
    """
    tokens_by_id: list[tuple[str, ...]] = []
    exact: dict[str, list[int]] = {}
    prefix: dict[str, set[int]] = {}
    phrases: list[int] = []
    for idx, entry in enumerate(entries):
        tokens = tuple(normalize_tokens(entry))
        tokens_by_id.append(tokens)
        if not tokens:
            continue
        if len(tokens) > 1:
            phrases.append(idx)
            continue
        for variant in _fold_variants(tokens[0]):
            exact.setdefault(variant, []).append(idx)
            for size in range(_MIN_PREFIX, len(variant) + 1):
                prefix.setdefault(variant[:size], set()).add(idx)
    return tuple(tokens_by_id), exact, prefix, tuple(phrases)


def _phrase_matches(
    entry_tokens,
    message_tokens,
    strict_question: bool = False,
) -> bool:
    """Ibora (yonma-yon so'zlar) xabarda topildimi."""
    size = len(entry_tokens)
    if size > len(message_tokens):
        return False
    for start in range(len(message_tokens) - size + 1):
        window = message_tokens[start:start + size]
        if all(
            _word_matches(e, m, strict_question=strict_question)
            for e, m in zip(entry_tokens, window)
        ):
            return True
    return False


def _find_entries(
    message_text: str,
    entries,
    strict_question: bool = False,
) -> list[str]:
    entries = tuple(entries or ())
    if not entries:
        return []
    message_tokens = normalize_tokens(message_text)
    if not message_tokens:
        return []
    tokens_by_id, exact, prefix, phrases = _build_entry_index(entries)

    found: set[int] = set()
    for token in message_tokens:
        for idx in _candidate_ids(token, exact, prefix):
            if idx in found:
                continue
            entry_tokens = tokens_by_id[idx]
            if len(entry_tokens) != 1:
                continue
            if _word_matches(
                entry_tokens[0], token, strict_question=strict_question
            ):
                found.add(idx)
    for idx in phrases:
        if idx in found:
            continue
        entry_tokens = tokens_by_id[idx]
        if not entry_tokens:
            continue
        if _phrase_matches(
            entry_tokens, message_tokens, strict_question=strict_question
        ):
            found.add(idx)
    return [entries[i] for i in sorted(found)]


def find_stop_words(message_text: str, stop_words) -> list[str]:
    """Xabardagi stop-so'zlar/iboralar ro'yxati (topilmasa bo'sh).

    Bitta stop-so'z topilsa ham xabar haydovchiniki hisoblanadi.
    So'roq shakli qat'iy ajratiladi: "жой бор" yozuvi "жой борми"
    savolini bloklamaydi.
    """
    return _find_entries(message_text, stop_words, strict_question=True)


def find_client_words(message_text: str, client_words) -> list[str]:
    """Xabardagi mijozga xos so'zlar/iboralar (topilmasa bo'sh).

    Bu yerda so'roq shakli qat'iy emas: "bormi" yozuvi "бор" so'zi
    bilan ham mos keladi — mijoz xabarini o'tkazib yubormaslik muhim.
    """
    return _find_entries(message_text, client_words, strict_question=False)


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
    ``toshkent`` bitta yozuv hisoblanadi. "Dangasa" yozilgan kirill
    (``қарши`` / ``карши``) ham bitta yozuv sifatida qaraladi.
    """
    tokens = normalize_tokens(text or "")
    return " ".join(_lazy_latin(_canon(token)) for token in tokens)
