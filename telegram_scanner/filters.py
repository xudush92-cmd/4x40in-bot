"""Filtr zanjiri — skaner ham, test ham AYNAN shu koddan foydalanadi.

Muammo shu ediki, botdagi "🧪 Skaner testi" faqat kalit so'zlarni sanab
"xabar berilardi" derdi, real skaner esa emoji, stop-so'z yoki mijoz
so'zi sababli xabarni tashlab yuborardi. Natijada test yolg'on gapirardi.

Endi tartib BITTA joyda — ``evaluate()`` da:

    1. Tizim (admin) to'xtatmaganmi
    2. Tarif faolmi (admin bundan mustasno)
    3. Foydalanuvchining umumiy Stop/Start holati
    4. Xabar shu foydalanuvchining faol guruhidanmi
    5. Emoji / stiker  -> haydovchi belgisi, blok
    6. Stop-so'z / ibora -> haydovchi e'loni, blok
    7. Kalit so'zlar soni shartga yetadimi
    8. Kamida bitta mijoz so'zi bormi

Skaner faqat ``verdict.ok`` ni ko'radi; test esa ``verdict.stages`` ni
ko'rsatib, qaysi bosqichda to'xtaganini aytadi.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from config import ADMIN_ID
from database import (
    get_client_words,
    get_keywords,
    get_match_count,
    get_owner_active_chat_ids,
    get_setting,
    get_stop_words,
    get_user_match_count,
    get_user,
    get_user_scanner_enabled,
)
from matcher import (
    contains_emoji,
    find_client_words,
    find_stop_words,
    match_keywords,
)

# Bosqich nomlari — testda shu tartibda ko'rsatiladi
STAGE_TITLES = [
    ("system", "Tizim (admin) holati"),
    ("tariff", "Tarif / bloklanish"),
    ("scanner", "Umumiy skaner"),
    ("group", "Guruh"),
    ("emoji", "Emoji / stiker"),
    ("stop", "Stop-so'zlar"),
    ("keywords", "Kalit so'zlar"),
    ("client", "Mijoz so'zi"),
]

OK = "ok"          # bosqich o'tdi
FAIL = "fail"      # shu bosqichda to'xtadi
SKIP = "skip"      # oldingi bosqichda to'xtagani uchun tekshirilmadi
INFO = "info"      # o'tkazib yuboriladigan ma'lumot (masalan, guruh tekshiruvi)


@dataclass
class Stage:
    key: str
    status: str
    text: str
    title: str = ""


@dataclass
class Verdict:
    ok: bool
    stage: str = ""
    detail: str = ""
    stages: list[Stage] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    required: int = 0
    total_keywords: int = 0
    client_found: list[str] = field(default_factory=list)
    stops_found: list[str] = field(default_factory=list)


def _fmt(words) -> str:
    return ", ".join(words) if words else "—"


def evaluate(
    owner_id: int,
    text: str,
    *,
    is_sticker: bool = False,
    chat_id: int | None = None,
    check_group: bool = True,
) -> Verdict:
    """Xabar egasiga yuboriladimi — to'liq zanjir bo'yicha.

    ``check_group=False`` — test rejimi: guruh noma'lum, shu bosqich
    ma'lumot sifatida ko'rsatiladi (xabar guruhdan kelmagan).
    """
    stages: list[Stage] = []
    verdict = Verdict(ok=False)

    titles = dict(STAGE_TITLES)

    def add(key: str, status: str, text_: str) -> None:
        stages.append(Stage(key, status, text_, titles.get(key, key)))

    def finish(key: str, detail: str) -> Verdict:
        add(key, FAIL, detail)
        verdict.stage, verdict.detail = key, detail
        # Qolgan bosqichlarni "tekshirilmadi" deb to'ldiramiz
        done = {s.key for s in stages}
        for k, _title in STAGE_TITLES:
            if k not in done:
                add(k, SKIP, "tekshirilmadi")
        verdict.stages = stages
        return verdict

    # 1. Tizim
    if get_setting("is_active") != "1":
        return finish("system", "tizim admin tomonidan ⏸ to'xtatilgan")
    add("system", OK, "🟢 yoniq")

    # 2. Tarif (admin uchun talab qilinmaydi)
    if owner_id == ADMIN_ID:
        add("tariff", INFO, "admin — tarif talab qilinmaydi")
    else:
        row = get_user(owner_id)
        if row and row[3]:
            # Bloklangan foydalanuvchiga xabar ketmasligi shart.
            return finish("tariff", "hisobingiz bloklangan")
        expires = row[4] if row else 0
        import time as _time

        if not expires:
            return finish("tariff", "tarif berilmagan — admin muddat bermagan")
        if expires <= int(_time.time()):
            return finish("tariff", "tarif muddati tugagan")
        days = (expires - int(_time.time()) + 86399) // 86400
        add("tariff", OK, f"faol, {days} kun qoldi")

    # 3. Umumiy Stop/Start
    if not get_user_scanner_enabled(owner_id):
        return finish("scanner", "🔴 to'xtatilgan — menyudagi ▶️ Start ni bosing")
    add("scanner", OK, "🟢 yoniq")

    # 4. Guruh egasiniki mi
    if check_group:
        if chat_id is None or chat_id not in get_owner_active_chat_ids(owner_id):
            return finish(
                "group", "bu guruh sizning faol guruhlaringiz ro'yxatida yo'q"
            )
        add("group", OK, "egasiniki, kuzatuvda")
    else:
        # Test rejimi: aniq guruh noma'lum, LEKIN umuman faol guruh
        # bo'lmasa hech qanday xabar kelmaydi — buni yashirmaymiz.
        active_ids = get_owner_active_chat_ids(owner_id)
        if not active_ids:
            return finish(
                "group",
                "faol guruh yo'q — avval ➕ Guruh qo'shish dan guruh "
                "qo'shing va u ✅ Kuzatuvda bo'lishi kerak",
            )
        add("group", INFO, f"faol guruhlar: {len(active_ids)} ta (test rejimi)")

    # 5. Emoji / stiker
    if is_sticker:
        return finish("emoji", "stiker — haydovchi belgisi")
    if contains_emoji(text):
        return finish("emoji", "emoji bor — haydovchi belgisi")
    add("emoji", OK, "toza")

    # 6. Stop-so'zlar
    stops = find_stop_words(text, get_stop_words())
    verdict.stops_found = stops
    if stops:
        return finish("stop", _fmt(stops))
    add("stop", OK, "toza")

    # 7. Kalit so'zlar
    keywords = get_keywords()
    required = get_user_match_count(owner_id)
    verdict.required, verdict.total_keywords = required, len(keywords)
    if not keywords:
        return finish("keywords", "bazada kalit so'z yo'q (admin kiritmagan)")
    result = match_keywords(text, keywords, required)
    verdict.matched = list(result.matched_words)
    if result.matched_count < required:
        return finish(
            "keywords",
            f"{result.matched_count} ta kalit, shart — {required} ta"
            + (f" ({_fmt(result.matched_words)})" if result.matched_words else ""),
        )
    add(
        "keywords",
        OK,
        f"{result.matched_count} ta: {_fmt(result.matched_words)} (shart: {required})",
    )

    # 8. Mijoz so'zi
    clients = find_client_words(text, get_client_words())
    verdict.client_found = clients
    if not clients:
        return finish(
            "client",
            "mijoz so'zi yo'q — haydovchi e'loni bo'lishi mumkin",
        )
    add("client", OK, _fmt(clients))

    verdict.ok = True
    verdict.stage = "ok"
    verdict.detail = "Barcha bosqichlar o'tdi"
    verdict.stages = stages
    return verdict


def summary_line(verdict: Verdict) -> str:
    """Log uchun qisqa izoh."""
    if verdict.ok:
        return "o'tdi"
    return f"{verdict.stage}: {verdict.detail}"
