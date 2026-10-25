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
  * so'roq shaklini qat'iy ajratish imkoniyati bor (ixtiyoriy):
    "жой бор" "жой борми" bilan tenglashtirilmaydi;
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


def _lazy_latin(word: str, fold_apostrophe: bool = True) -> str:
    """Lotin yozuvidagi "dangasalik"ni tenglashtiradi.

    Odamlar kirillni ham, lotinni ham soddalashtirib yozadi:
    ``ў`` o'rniga ``у``, ``қ`` o'rniga ``к``, ``ҳ`` o'rniga ``х``.

    ``fold_apostrophe=True`` — ``o'``/``g'`` ni ``u``/``g`` ga aylantiradi.
    Bu kirill manbali so'z uchun kerak (``жўнаймиз`` -> ``жунаймиз``) va
    uzun lotin so'zlar uchun ham (``jo'nat`` ~ ``жунат``).

    Qisqa so'zlarda bu almashtirish XAVFLI: ``yo'q`` -> ``yuk``,
    ``to'q`` -> ``tuk``, ``so'z`` -> ``suz``. Natijada kalit ``yo'q``
    xabardagi ``yuk``/``yukim`` so'zini tutib oladi (domenda ``yuk`` eng
    ko'p uchraydigan so'z). Shuning uchun qisqa so'zlarda o'chiriladi.
    """
    w = word
    if fold_apostrophe:
        w = w.replace("o'", "u").replace("g'", "g")
    return w.replace("q", "k").replace("h", "x")


@lru_cache(maxsize=16384)
def _fold_variants(word: str) -> tuple[str, ...]:
    """So'zning solishtirish uchun yagona (lotin) shakllari.

    ``word`` allaqachon normallashtirilgan (kichik harf, apostrof bir xil).
    """
    is_cyr = _is_cyrillic(word)
    base = cyr_to_lat(word) if is_cyr else word
    variants = [base]
    # ``o'``->``u`` almashtirish kirillda doim, lotinda esa faqat so'z
    # yetarlicha uzun bo'lsa qo'llanadi (qisqa so'zlarda u boshqa haqiqiy
    # so'z bilan to'qnashadi: yo'q ~ yuk, to'q ~ tuk, so'z ~ suz).
    long_enough = len(base.replace("'", "")) >= 4
    lazy = _lazy_latin(base, fold_apostrophe=is_cyr or long_enough)
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
    question_key_only: bool = False,
) -> bool:
    """Bitta yozuv xabardagi so'zga mosmi (shakl va alifbo o'zgarishlari bilan)."""
    for kv in _fold_variants(key_word):
        for mv in _fold_variants(message_word):
            if _word_matches_single(
                kv, mv,
                strict_question=strict_question,
                question_key_only=question_key_only,
            ):
                return True
    return False


def _word_matches_single(
    key_word: str,
    message_word: str,
    strict_question: bool = False,
    question_key_only: bool = False,
) -> bool:
    """Bitta alifbo (allaqachon buklangan) ichida moslik.

    So'roq qo'shimchasi ikki xil boshqariladi:

    * ``strict_question=True`` — **simmetrik**: so'roq shakli umuman
      boshqa shakl bilan tenglashtirilmaydi. Stop-so'zlar uchun kerak:
      "жой бор" (e'lon) "жой борми?" (savol) ni bloklamasin.
    * ``question_key_only=True`` — **assimmetrik**: kalit so'roq shaklida
      yozilgan bo'lsa (``bormi``), u faqat so'roq shaklidagi so'zga mos
      keladi. Teskari yo'nalish ochiq: ``kerak`` kaliti ``kerakmi`` ni,
      ``ketadi`` kaliti ``ketadimi`` ni topaveradi (mijoz shakli
      yo'qolmasin).
    """
    if strict_question and _is_question_form(key_word) != _is_question_form(
        message_word
    ):
        return False
    if key_word == message_word:
        return True

    if question_key_only and _is_question_form(key_word) and not _is_question_form(
        message_word
    ):
        return False

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
    # qabul qilinadi: "ketadi" ~ "ketad".
    # Xabar so'zi kamida 4 harf bo'lishi shart: aks holda "menga" kaliti
    # xabardagi "men" olmoshi bilan mos kelib, "men ham shu sohada
    # ishlayman" kabi begona xabarga ball qo'shardi.
    # Aks holda "boramiz" yozuvi xabardagi oddiy "bor" so'zini ham
    # tutib qo'yardi va mijoz xabari bloklanardi.
    if (
        min(len(key_word), len(message_word)) >= 4
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
    question_key_only: bool = False,
) -> bool:
    """Ibora (yonma-yon so'zlar) xabarda topildimi."""
    size = len(entry_tokens)
    if size > len(message_tokens):
        return False
    for start in range(len(message_tokens) - size + 1):
        window = message_tokens[start:start + size]
        if all(
            _word_matches(
                e, m,
                strict_question=strict_question,
                question_key_only=question_key_only,
            )
            for e, m in zip(entry_tokens, window)
        ):
            return True
    return False


def _find_entries(
    message_text: str,
    entries,
    strict_question: bool = False,
    question_key_only: bool = False,
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
                entry_tokens[0], token,
                strict_question=strict_question,
                question_key_only=question_key_only,
            ):
                found.add(idx)
    for idx in phrases:
        if idx in found:
            continue
        entry_tokens = tokens_by_id[idx]
        if not entry_tokens:
            continue
        if _phrase_matches(
            entry_tokens, message_tokens,
            strict_question=strict_question,
            question_key_only=question_key_only,
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


def find_client_words(message_text, client_words) -> list[str]:
    """Xabardagi mijozga xos so'zlar/iboralar (topilmasa bo'sh).

    So'roq shakli qat'iy ajratiladi: ``bormi`` yozuvi xabardagi oddiy
    ``bor`` so'zi bilan tenglashtirilmaydi (haydovchining "2 joy bor"
    e'loni mijoz savoli deb hisoblanmasin).
    """
    return _find_entries(message_text, client_words, question_key_only=True)


# --- Vaznli hisoblash (score) ---
# Har bir kalit so'zning bazada vazni bor: musbat — mijoz belgisi,
# manfiy — haydovchi belgisi. Xabar ball yig'indisi bo'yicha baholanadi.
#
# Ikki xil moslik ishlatiladi:
#   * musbat yozuv — odatdagi moslik (o'zak, shakl, imlo xatosi);
#     so'roq shakli qat'iy, chunki ``bormi`` mijoz belgisi.
#   * manfiy yozuv — QAT'IY moslik: faqat aniq so'z yoki o'zak.
#     Imlo xatosi/prefiks bo'yicha yaqinlik ishlatilmaydi, aks holda
#     "xizmat" kabi manfiy so'z "xizmat kerak" (mijoz) xabarini ham
#     o'chirib qo'yardi.
_NEG_FUZZY_MIN = 4  # manfiy yozuv o'zak bo'lib xizmat qilishi uchun


def _find_entries_strict(message_text: str, entries) -> list[str]:
    """Manfiy yozuvlar uchun qat'iy qidiruv (imlo xatosi hisobga olinmaydi).

    Bitta so'zli yozuv: xabar so'zi unga teng yoki undan boshlanadi
    (``reys`` ~ ``reyslar``), lekin ``tashaymiz`` ~ ``tashaydi`` kabi
    boshqa shakl mos kelmaydi. Ko'p so'zli yozuv (ibora): yonma-yon
    aynan teng bo'lishi kerak.
    """
    entries = list(entries or ())
    if not entries:
        return []
    message_tokens = normalize_tokens(message_text)
    if not message_tokens:
        return []
    found: list[str] = []
    for entry in entries:
        entry_tokens = normalize_tokens(entry)
        if not entry_tokens:
            continue
        if len(entry_tokens) == 1:
            key = entry_tokens[0]
            for token in message_tokens:
                if token == key:
                    found.append(entry)
                    break
                if len(key) < _NEG_FUZZY_MIN or len(token) < _NEG_FUZZY_MIN:
                    continue
                # Oldinga: qo'shimcha har qanday uzunlikda bo'lishi mumkin
                # (``reys`` ~ ``reyslar``, ``xizmat`` ~ ``xizmatimiz``).
                if token.startswith(key):
                    found.append(entry)
                    break
                # Orqaga: xabar so'zi kalitning o'zagi bo'lsa, faqat qisqa
                # qoldiq (1-2 harf) — aks holda ``tashaymiz`` kaliti
                # ``tashaydi`` bilan aralashardi.
                if key.startswith(token) and len(key) - len(token) <= 2:
                    found.append(entry)
                    break
        else:
            size = len(entry_tokens)
            for start in range(len(message_tokens) - size + 1):
                if message_tokens[start:start + size] == entry_tokens:
                    found.append(entry)
                    break
    return found


def _variant_signature(entry: str) -> tuple[frozenset, ...]:
    """Yozuvning "bir xil so'z" ekanini aniqlash uchun belgisi.

    Har bir so'z uchun ``_fold_variants`` bergan shakllar to'plami olinadi:
    ``jo'nat`` -> {jo'nat, junat, jonat}. Ikki yozuvning to'plamlari kesishsa
    — ular bir so'zning har xil yozilishi (``jo'nat`` / ``jonat``).
    """
    return tuple(frozenset(_fold_variants(t)) for t in normalize_tokens(entry))


def _same_signature(a, b) -> bool:
    """Ikki yozuv bir xil so'z(lar)dan iboratmi."""
    if len(a) != len(b) or not a:
        return False
    return all(left & right for left, right in zip(a, b))


def _collapse_variants(
    positives: dict[str, float], negatives: dict[str, float]
) -> tuple[dict[str, float], dict[str, float]]:
    """Bir so'zning bir necha yozuvi topilsa — faqat bittasi sanaladi.

    Ro'yxatda ``jo'nat`` va ``jonat`` ikkalasi ham bo'lsa, xabar ikkala
    vaznni ham olardi (``jo'natamiz`` -> +3 +3 = +6). Endi bitta hisoblanadi:
    mutlaq qiymati kattasi qoladi (``-4`` ``-2`` dan kuchli). Teng bo'lsa
    manfiy qoladi — ortiqcha xabar yubormaslik xavfsizroq.
    """
    chosen: list[tuple[tuple[frozenset, ...], str, float]] = []
    out_pos: dict[str, float] = {}
    out_neg: dict[str, float] = {}

    def place(word: str, weight: float) -> None:
        if weight > 0:
            out_pos[word] = weight
        else:
            out_neg[word] = weight

    def drop(word: str) -> None:
        out_pos.pop(word, None)
        out_neg.pop(word, None)

    for word, weight in list(positives.items()) + list(negatives.items()):
        signature = _variant_signature(word)
        for known_signature, known_word, known_weight in chosen:
            if _same_signature(known_signature, signature):
                better = abs(weight) > abs(known_weight) or (
                    abs(weight) == abs(known_weight) and weight < known_weight
                )
                if better:
                    drop(known_word)
                    place(word, weight)
                    chosen = [
                        (signature, word, weight) if w == known_word else (s, w, wt)
                        for s, w, wt in chosen
                    ]
                break
        else:
            chosen.append((signature, word, weight))
            place(word, weight)
    return out_pos, out_neg


@dataclass
class ScoreResult:
    score: float = 0.0
    threshold: float = 1.75
    positives: dict[str, float] = field(default_factory=dict)
    negatives: dict[str, float] = field(default_factory=dict)
    emoji_penalty: float = 0.0

    @property
    def is_match(self) -> bool:
        return self.score >= self.threshold

    @property
    def total(self) -> float:
        return self.score


def score_text(
    message_text: str,
    entries,
    threshold: float = 1.75,
    emoji_penalty: float = 0.0,
) -> ScoreResult:
    """Xabarning ballini hisoblaydi.

    ``entries`` — ``[(so'z, vazn), ...]`` yoki
    ``[(so'z, vazn, qatiylik), ...]``. Nol vaznli yozuvlar tashlab
    yuboriladi. Musbat yozuvlar odatdagi, manfiy yozuvlar qat'iy
    moslik bilan qidiriladi.

    Hisoblash: **musbatlar yig'indisi + eng kuchli manfiy**. Manfiy
    so'zlar qo'shilmaydi — bitta aniq haydovchi belgisi yetarli, aks
    holda bir-birini qoplaydigan iboralar bitta xabarni bir necha
    marta jazolaydi.
    """
    result = ScoreResult(threshold=float(threshold))
    pos_entries: dict[str, float] = {}
    neg_entries: dict[str, float] = {}
    for row in entries or ():
        word = row[0]
        try:
            weight = float(row[1])
        except (TypeError, ValueError):
            continue
        if not word or weight == 0:
            continue
        if weight > 0:
            pos_entries[word] = weight
        else:
            neg_entries[word] = weight

    if pos_entries:
        for word in _find_entries(
            message_text, list(pos_entries), question_key_only=True
        ):
            result.positives[word] = pos_entries[word]
    if neg_entries:
        for word in _find_entries_strict(message_text, list(neg_entries)):
            result.negatives[word] = neg_entries[word]

    # Bitta so'z ro'yxatda ikki xil yozuv bilan tursa (``jo'nat``/``jonat``),
    # xabar ikki marta ball olmasin — kuchlirog'i qoladi.
    (
        result.positives,
        result.negatives,
    ) = _collapse_variants(result.positives, result.negatives)

    # Musbatlar QO'SHILADI (bir nechta zaif signal birga kuch beradi),
    # manfiylardan esa faqat ENG KUCHLISI hisoblanadi: bitta aniq haydovchi
    # belgisi yetarli, qolganlari ustiga qo'shilib ketsa bitta ibora
    # (``bo'sh joy bor`` -> ``joy bor`` + ``bo'sh joy`` + ``bo'sh``)
    # xabarni uch marta jazolaydi.
    score = sum(result.positives.values()) + (
        min(result.negatives.values()) if result.negatives else 0.0
    )
    if emoji_penalty and contains_emoji(message_text):
        result.emoji_penalty = float(emoji_penalty)
        score -= result.emoji_penalty
    result.score = score
    return result


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u20E3]"
)


def contains_emoji(text: str | None) -> bool:
    """Matnda emoji yoki emoji-ega belgisi bormi?

    Haydovchi e'lonlari odatda emoji bilan bezatiladi; mijoz matnida
    emoji bo'lmasligi kutiladi. Shuning uchun emoji alohida belgidir.
    """
    return bool(text and _EMOJI_RE.search(text))


_WEIGHT_PREFIX_RE = re.compile(r"^\s*([+-]\d+(?:\.\d+)?)\s*(:)?\s*(.+)$")
_NEXT_WEIGHT_SPLIT = re.compile(r"\s+(?=[+-]\d+(?:\.\d+)?\s*:?\s*\S)")


def parse_weighted_entries(text: str) -> list[tuple[str, float]]:
    """Admin kiritgan matnni ``(yozuv, vazn)`` juftlariga ajratadi.

    Qoidalar:

    * vazn yozilmasa — standart **+1** (mijoz belgisi);
    * ``+3 kerak kerek`` — musbat vazn + bir necha so'z = **har biri
      alohida yozuv** (mijoz kalitlari odatda yakka so'z bo'ladi);
    * ``-4 har kuni`` — manfiy vazn + bir necha so'z = **ibora**
      (haydovchi belgisi aniq bo'lishi kerak);
    * ``-4: joy bor`` yoki ``-4 "joy bor"`` — har qanday holatda ibora;
    * ``-3 reys +2 yukim`` — bir qatorda bir nechta vaznli yozuv;
    * ``+2.5 bormi, kerak`` — vergul bo'lsa, har so'z alohida yozuv.

    Musbat vazn — mijoz belgisi, manfiy — haydovchi belgisi.
    """
    out: list[tuple[str, float]] = []
    for line in (text or "").splitlines():
        for piece in _NEXT_WEIGHT_SPLIT.split(line.strip()):
            piece = piece.strip()
            if not piece:
                continue
            match = _WEIGHT_PREFIX_RE.match(piece)
            if not match:
                for word in parse_key_words(piece):
                    out.append((word, 1.0))
                continue
            try:
                weight = float(match.group(1))
            except ValueError:
                weight = 1.0
            colon = bool(match.group(2))
            rest = match.group(3).strip()
            if not rest:
                continue
            if rest[:1] in ("\"", "'") and rest[-1:] == rest[:1]:
                rest = rest[1:-1].strip()
                colon = True
            if "," in rest or ";" in rest:
                for word in parse_key_words(rest):
                    out.append((word, weight))
                continue
            tokens = parse_key_words(rest)
            if not tokens:
                continue
            # Ibora: ochiq belgi (``:``/qo'shtirnoq) yoki manfiy vazn +
            # bir necha so'z. Aks holda har so'z alohida yozuv bo'ladi.
            if colon or (weight < 0 and len(tokens) > 1):
                entry = display_entry(rest)
                if entry:
                    out.append((entry, weight))
                continue
            for word in tokens:
                out.append((word, weight))
    merged: dict[str, float] = {}
    for entry, weight in out:
        merged[entry] = weight
    return list(merged.items())


def display_entry(text: str | None) -> str:
    """Ro'yxatga YOZILADIGAN ko'rinish: kichik harf, bir xil apostrof, lotin.

    ``canonical_entry`` dan farqi — solishtirish uchun soddalashtirish
    (``q``->``k``, ``o'``->``u``) QILINMAYDI: foydalanuvchi qanday so'zni
    ko'rsa, ro'yxatda shunday turadi. Kirill so'z lotinga o'giriladi.
    """
    tokens = normalize_tokens(text or "")
    return " ".join(cyr_to_lat(t) if _is_cyrillic(t) else t for t in tokens)


def canonical_entry(text: str | None) -> str:
    """Takroriylikni tekshirish uchun yozuvning yagona shakli.

    Katta-kichik harf, ortiqcha bo'shliq, tinish belgilari va
    lotin/kirill farqi hisobga olinmaydi: ``ТОШКЕНТ`` bilan
    ``toshkent`` bitta yozuv hisoblanadi. "Dangasa" yozilgan kirill
    (``қарши`` / ``карши``) ham bitta yozuv sifatida qaraladi.
    """
    tokens = normalize_tokens(text or "")
    out = []
    for token in tokens:
        base = _canon(token)
        # ``_fold_variants`` bilan bir xil qoida: qisqa so'zlarda
        # ``o'``->``u`` qo'llanmaydi. Aks holda ``yo'q`` va ``yuk``
        # "bir xil yozuv" bo'lib qolardi va admin ikkalasini ham
        # ro'yxatga qo'sha olmasdi.
        out.append(
            _lazy_latin(base, fold_apostrophe=len(base.replace("'", "")) >= 4)
        )
    return " ".join(out)
