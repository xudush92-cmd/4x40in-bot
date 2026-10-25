import sqlite3
import time
from contextlib import closing

from config import DB_NAME
from matcher import canonical_entry, display_entry


def _connect() -> sqlite3.Connection:
    """Ulanish. WAL rejimi: bot va skaner bir vaqtda yozganda bloklanish kamayadi.

    WAL fayli (``-wal``/``-shm``) tarmoq diski yoki eski fayl tizimida
    ishlamasligi mumkin — u holda oddiy rejimda davom etamiz.
    """
    conn = sqlite3.connect(DB_NAME, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    return conn


def init_db() -> None:
    with closing(_connect()) as conn, conn:
        # Kalit so'zlar jadvali: HAR BIR qatorda BITTA so'z (kalit).
        # (Jadval nomi tarixiy sabab bilan 'phrases' bo'lib qolgan.)
        conn.execute("""CREATE TABLE IF NOT EXISTS phrases (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            text TEXT UNIQUE)""")
        _migrate_phrase_columns(conn)
        _migrate_old_sets(conn)
        # Eski "groups" jadvali ishlatilmaydi (guruhlar user_groups da,
        # har biri egasi bilan). Qolib ketgan bo'lsa — olib tashlaymiz.
        conn.execute("DROP TABLE IF EXISTS groups")
        # Nazorat (o'qitish) navbati: admin ko'rib chiqadigan topilgan
        # xabarlar. Egasi, ismi va telefoni SAQLANMAYDI — faqat matn va
        # ball. Shu bilan bir foydalanuvchi ma'lumoti boshqasiga
        # o'tmaydi va o'quv to'plami anonim qoladi.
        conn.execute("""CREATE TABLE IF NOT EXISTS review_items (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            text TEXT NOT NULL,
                            score REAL DEFAULT 0,
                            threshold REAL DEFAULT 0,
                            words TEXT DEFAULT '',
                            created_at INTEGER,
                            label TEXT,
                            labeled_at INTEGER)""")
        conn.execute("""CREATE INDEX IF NOT EXISTS idx_review_pending
                        ON review_items (label, id)""")
        # Sozlamalar jadvali
        conn.execute("""CREATE TABLE IF NOT EXISTS settings (
                            key TEXT PRIMARY KEY,
                            value TEXT)""")
        # Foydalanuvchilar (tarifli obunachilar) jadvali.
        # Admin (Secrets dagi ADMIN_ID) bu jadvalda bo'lishi shart emas —
        # u har doim to'liq huquqqa ega.
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
                            user_id INTEGER PRIMARY KEY,
                            first_name TEXT,
                            username TEXT,
                            is_blocked INTEGER DEFAULT 0,
                            sub_expires_at INTEGER DEFAULT 0,
                            created_at INTEGER DEFAULT 0)""")
        _migrate_user_columns(conn)
        # Har bir foydalanuvchining O'Z guruhlari (egasi bilan).
        conn.execute("""CREATE TABLE IF NOT EXISTS user_groups (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            owner_user_id INTEGER NOT NULL,
                            input_value TEXT NOT NULL,
                            chat_id INTEGER,
                            title TEXT,
                            is_active INTEGER DEFAULT 1,
                            status TEXT DEFAULT 'pending',
                            last_error TEXT,
                            UNIQUE(owner_user_id, input_value))""")
        # Bildirishnoma ustidan fikr-mulohaza (feedback): «foydali / keraksiz».
        # Har bir yuborilgan xabar va unda topilgan so'zlar saqlanadi —
        # foydalanuvchi tugma bosganda o'sha so'zlarning vazni moslashadi.
        conn.execute("""CREATE TABLE IF NOT EXISTS lead_reviews (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            owner_user_id INTEGER NOT NULL,
                            words TEXT NOT NULL,
                            verdict TEXT DEFAULT '',
                            created_at INTEGER DEFAULT 0)""")
        # Foydalanuvchi statistikasi hisoblagichlari
        conn.execute("""CREATE TABLE IF NOT EXISTS user_counters (
                            user_id INTEGER NOT NULL,
                            key TEXT NOT NULL,
                            value INTEGER DEFAULT 0,
                            PRIMARY KEY (user_id, key))""")
        # Standart sozlamalar
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('is_active', '1')"
        )
        # Xabar berish sharti: kamida nechta kalit topilsa xabar beriladi.
        # 2 — amaliy o'lchov bo'yicha eng yaxshi (qisqa mijoz xabarlari
        # odatda 2-3 kalitdan iborat).
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('match_count', '2')"
        )
        # Filtr rejimi:
        #   'count'  — nechta kalit topildi (eski xatti-harakat);
        #   'weight' — vaznlar yig'indisi (har so'zga +/− ball).
        # Standart 'count' — mavjud ro'yxatlar o'zini tutishini o'zgartirmaydi.
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('match_mode', 'count')"
        )
        # Vaznli rejim chegarasi (ball yig'indisi shundan katta bo'lsa o'tadi).
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) "
            "VALUES ('score_threshold', '1.75')"
        )


def _migrate_phrase_columns(conn) -> None:
    """Kalit so'zlarga vazn va qat'iylik ustunlarini qo'shadi.

    ``weight`` — so'zning ball qiymati: musbat (mijoz belgisi) yoki manfiy
    (haydovchi belgisi). ``strict`` — 1 bo'lsa so'zning o'zagi ham
    ishlatilmaydi, faqat aniq yozuv (imlo xatosiga mos kelmaydi).
    """
    columns = [row[1] for row in conn.execute("PRAGMA table_info(phrases)")]
    if "weight" not in columns:
        conn.execute("ALTER TABLE phrases ADD COLUMN weight REAL DEFAULT 1.0")
    if "strict" not in columns:
        conn.execute("ALTER TABLE phrases ADD COLUMN strict INTEGER DEFAULT 0")


def _migrate_user_columns(conn) -> None:
    """Mavjud users jadvaliga sessiya/registratsiya ustunlarini qo'shadi."""
    columns = [row[1] for row in conn.execute("PRAGMA table_info(users)")]
    additions = {
        "full_name": "TEXT DEFAULT ''",
        "phone": "TEXT DEFAULT ''",
        "session_enc": "TEXT DEFAULT ''",
        "pending_session_enc": "TEXT DEFAULT ''",
        "awaiting_approval": "INTEGER DEFAULT 0",
        "session_status": "TEXT DEFAULT 'none'",
        "last_warn_date": "TEXT DEFAULT ''",
        "last_found_at": "INTEGER DEFAULT 0",
        "scanner_enabled": "INTEGER DEFAULT 1",
        "own_match_count": "INTEGER DEFAULT 0",
        "own_score_threshold": "REAL DEFAULT 0",
    }
    for name, ddl in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")


SETS_SPLIT_FLAG = "legacy_sets_split"


def _migrate_old_sets(conn) -> None:
    """Eski "to'plam" yozuvlarini alohida kalit so'zlarga bo'ladi — FAQAT BIR MARTA.

    Avvalgi modelda bitta qatorda bir nechta so'z saqlanardi. Endi ko'p
    so'zli yozuv — qonuniy **ibora** (``joy bor``, ``kim olib ketadi``),
    shuning uchun bu migratsiya faqat bir marta bajariladi va vaznni
    saqlab qoladi. Aks holda har ishga tushishda iboralar bo'linib,
    vaznlari yo'qolardi.
    """
    from matcher import parse_key_words

    # Migratsiya allaqachon bajarilganmi (settings jadvali hali
    # yaratilmagan bo'lishi mumkin — shu yerda kafolatlaymiz).
    conn.execute(
        """CREATE TABLE IF NOT EXISTS settings (
               key TEXT PRIMARY KEY,
               value TEXT)"""
    )
    done = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (SETS_SPLIT_FLAG,)
    ).fetchone()
    if done:
        return

    rows = conn.execute("SELECT id, text, weight, strict FROM phrases").fetchall()
    for row_id, text, weight, strict in rows:
        words = parse_key_words(text or "")
        if len(words) <= 1:
            continue
        conn.execute("DELETE FROM phrases WHERE id = ?", (row_id,))
        for word in words:
            conn.execute(
                "INSERT OR IGNORE INTO phrases (text, weight, strict) VALUES (?, ?, ?)",
                (word, weight if weight is not None else 1.0, strict or 0),
            )
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, '1')",
        (SETS_SPLIT_FLAG,),
    )


# Bitta umumiy kalit so'zlar ro'yxati (phrases jadvali).
# Alohida stop-so'zlar / mijoz so'zlari ro'yxati YO'Q: admin faqat
# kerakli so'zlarni yozadi, ro'yxat ko'paytirilmaydi.
# Haydovchi e'lonlari emoji filtri bilan ajratiladi (ro'yxat kerak emas).


def find_lists_for_entry(entry: str) -> list[str]:
    """So'z kalitlar ro'yxatida bormi (lotin/kirill, registr hisobsiz)."""
    canonical = canonical_entry(entry)
    if not canonical:
        return []
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT text FROM phrases").fetchall()
    if any(canonical_entry(row[0]) == canonical for row in rows):
        return ["kalit so'zlar"]
    return []


def get_keywords() -> list[str]:
    """Barcha kalit so'zlar (soni cheksiz)."""
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT text FROM phrases ORDER BY id").fetchall()
    return [row[0] for row in rows]


# Eski nomlar (moslik uchun)
# 2 harfli, lekin haqiqiy so'zlar (qisqalik tekshiruvidan ozod)
_SHORT_OK = {"uk"}

# Ma'lum xato shakllar -> to'g'ri shakl. Ro'yxatga xato yozilmasin.
_BAD_FORMS = {
    "mang'ud": "mang'it",
    "mangud": "mang'it",
}


def keyword_reject_reason(word: str) -> str | None:
    """So'zni ro'yxatga qabul qilib bo'lmaydigan sabab (None — muammo yo'q).

    Qoidalar: bo'sh so'z, ma'lum xato shakl va qo'shimchali shakl
    (ro'yxatda o'zak bo'lsa, ``toshkentga`` kabi shakl kerak emas).
    """
    canonical = canonical_entry(word)
    shown = display_entry(word)
    if not canonical:
        return "bo'sh so'z"
    fix = _BAD_FORMS.get(canonical)
    if fix:
        return f"xato shakl — to'g'risi «{fix}»"
    if len(canonical) < 3 and canonical not in _SHORT_OK:
        return "juda qisqa so'z (kamida 3 harf)"
    # Qo'shimcha tekshiruvi faqat BIR SO'ZLI yozuvlar uchun. Ibora
    # (``joy bor``, ``kim olib ketadi``) o'zak+ qo'shimcha emas, shuning
    # uchun unga bu qoida qo'llanmaydi.
    if " " in canonical:
        return None
    for known in get_keywords():
        known_canonical = canonical_entry(known)
        if not known_canonical or known_canonical == canonical:
            continue
        if " " in known_canonical:
            continue
        # Qo'shimchali shakl: o'zak + 1..5 harf qo'shimcha
        if (
            len(known_canonical) >= 3
            and canonical.startswith(known_canonical)
            and 1 <= len(canonical) - len(known_canonical) <= 5
        ):
            return (
                f"qo'shimchali shakl — «{shown}» emas, "
                f"o'zak «{display_entry(known)}» yetarli"
            )
    return None


def add_keyword_checked(
    word: str, weight: float = 1.0, strict: int = 0
) -> tuple[bool, list[str]]:
    """Kalit qo'shadi: (qo'shildimi, qaysi ro'yxatlarda borligi).

    Takroriylik lotin/kirill va katta-kichik harf farqini hisobga
    olmasdan tekshiriladi: ``ТОШКЕНТ`` bilan ``toshkent`` bitta kalit.
    Ro'yxatga HAR DOIM lotin (kanonik) shakl yoziladi.

    ``weight`` — ball qiymati (manfiy bo'lsa haydovchi belgisi),
    ``strict`` — 1 bo'lsa o'zak bo'yicha ham moslashtirilmaydi.
    """
    cleaned = display_entry(word)
    if not cleaned:
        return False, []
    conflicts = find_lists_for_entry(cleaned)
    if conflicts:
        return False, conflicts
    weight = max(-10.0, min(10.0, float(weight)))
    with closing(_connect()) as conn, conn:
        try:
            conn.execute(
                "INSERT INTO phrases (text, weight, strict) VALUES (?, ?, ?)",
                (cleaned, weight, 1 if strict else 0),
            )
        except sqlite3.IntegrityError:
            return False, find_lists_for_entry(cleaned)
    return True, []


def add_keyword(word: str) -> bool:
    """Eski interfeys: True — saqlandi."""
    added, _conflicts = add_keyword_checked(word)
    return added


def delete_phrase(phrase_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM phrases WHERE id = ?", (phrase_id,))


def get_all_phrases_with_id() -> list[tuple[int, str]]:
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT id, text FROM phrases ORDER BY id"
        ).fetchall()


def get_phrases_full() -> list[tuple[int, str, float, int]]:
    """Ro'yxat to'liq: ``(id, so'z, vazn, qatiylik)``.

    Musbat vazn — mijoz belgisi, manfiy — haydovchi belgisi.
    """
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, text, weight, strict FROM phrases ORDER BY id"
        ).fetchall()
    return [
        (r[0], r[1], float(r[2] if r[2] is not None else 1.0), int(r[3] or 0))
        for r in rows
    ]


def get_keywords_weighted() -> list[tuple[str, float, int]]:
    """Skaner uchun: ``[(so'z, vazn, qatiylik), ...]``."""
    return [(text, weight, strict) for _id, text, weight, strict in get_phrases_full()]


def update_phrase(
    phrase_id: int,
    weight: float | None = None,
    strict: int | None = None,
) -> bool:
    """So'zning vaznini/qatiyligini o'zgartiradi. Topilmasa False."""
    sets, params = [], []
    if weight is not None:
        # Chegara: tasodifiy katta qiymat butun filtrni buzmasin.
        weight = max(-10.0, min(10.0, float(weight)))
        sets.append("weight = ?")
        params.append(weight)
    if strict is not None:
        sets.append("strict = ?")
        params.append(1 if strict else 0)
    if not sets:
        return False
    params.append(phrase_id)
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            f"UPDATE phrases SET {', '.join(sets)} WHERE id = ?", params
        )
        return cur.rowcount > 0


def get_phrase(phrase_id: int):
    """``(id, so'z, vazn, qatiylik)`` yoki None."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id, text, weight, strict FROM phrases WHERE id = ?",
            (phrase_id,),
        ).fetchone()
    if not row:
        return None
    return (row[0], row[1], float(row[2] if row[2] is not None else 1.0),
            int(row[3] or 0))


# --- Fikr-mulohaza (feedback) ---

def save_lead_review(owner_user_id: int, words) -> int:
    """Yuborilgan bildirishnoma uchun yozuv yaratadi, id qaytaradi."""
    import time as _t

    text = "|".join(w for w in (words or []) if w)
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO lead_reviews (owner_user_id, words, created_at) "
            "VALUES (?, ?, ?)",
            (owner_user_id, text, int(_t.time())),
        )
        return int(cur.lastrowid)


def get_lead_review(review_id: int):
    """``(id, egasi, so'zlar ro'yxati, verdict)`` yoki None."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id, owner_user_id, words, verdict FROM lead_reviews "
            "WHERE id = ?",
            (review_id,),
        ).fetchone()
    if not row:
        return None
    words = [w for w in (row[2] or "").split("|") if w]
    return (row[0], row[1], words, row[3] or "")


def set_lead_verdict(review_id: int, verdict: str) -> bool:
    """Fikrni yozadi. Allaqachon belgilangan bo'lsa False (takror bosish)."""
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "UPDATE lead_reviews SET verdict = ? "
            "WHERE id = ? AND (verdict IS NULL OR verdict = '')",
            (verdict, review_id),
        )
        return cur.rowcount > 0


def word_id_by_text(word: str) -> int | None:
    """So'zning bazadagi id'si (kanonik solishtirish bilan)."""
    target = canonical_entry(word)
    if not target:
        return None
    for pid, text, _w, _s in get_phrases_full():
        if canonical_entry(text) == target:
            return pid
    return None


def get_feedback_stats() -> dict:
    """Statistika: nechta foydali / keraksiz deb belgilangan."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT verdict, COUNT(*) FROM lead_reviews GROUP BY verdict"
        ).fetchall()
    out = {"useful": 0, "useless": 0, "pending": 0}
    for verdict, count in rows:
        if verdict == "useful":
            out["useful"] = count
        elif verdict == "useless":
            out["useless"] = count
        else:
            out["pending"] += count
    return out


def get_word_feedback_stats(min_total: int = 2) -> dict:
    """So'zlar bo'yicha fikr-mulohaza statistikasi.

    Har bir so'z nechta baholangan xabarda qatnashgan va o'sha
    xabarlar «foydali» yoki «keraksiz» deb belgilanganini hisoblaydi.

    Qaytaradi::

        {
          "total_reviews": 12,
          "useless": [(so'z, useless, jami, ulush), ...],   # kamaytirish
          "useful":  [(so'z, useful, jami, ulush), ...],    # oshirish
        }

    Ro'yxatlar ulush bo'yicha kamayish tartibida; ``min_total`` dan kam
    uchragan so'zlar tashlab yuboriladi (bitta bosish statistikani
    buzmasin).
    """
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT words, verdict FROM lead_reviews "
            "WHERE verdict IN ('useful', 'useless')"
        ).fetchall()
    counts: dict[str, dict[str, int]] = {}
    for words_text, verdict in rows:
        seen = set()
        for word in (words_text or "").split("|"):
            word = word.strip()
            if not word or word in seen:
                continue
            seen.add(word)
            item = counts.setdefault(word, {"useful": 0, "useless": 0})
            if verdict == "useful":
                item["useful"] += 1
            else:
                item["useless"] += 1

    useless, useful = [], []
    for word, item in counts.items():
        total = item["useful"] + item["useless"]
        if total < max(1, int(min_total)):
            continue
        if item["useless"]:
            useless.append((word, item["useless"], total,
                            item["useless"] / total))
        if item["useful"]:
            useful.append((word, item["useful"], total,
                           item["useful"] / total))
    useless.sort(key=lambda r: (-r[3], -r[1], r[0]))
    useful.sort(key=lambda r: (-r[3], -r[1], r[0]))
    return {"total_reviews": len(rows), "useless": useless, "useful": useful}


# --- Filtr rejimi va chegarasi ---

MATCH_MODES = ("count", "weight")


def get_match_mode() -> str:
    """``count`` — nechta kalit; ``weight`` — ballar yig'indisi."""
    value = (get_setting("match_mode") or "count").strip().lower()
    return value if value in MATCH_MODES else "count"


def set_match_mode(mode: str) -> str:
    mode = (mode or "").strip().lower()
    if mode not in MATCH_MODES:
        raise ValueError(f"noma'lum rejim: {mode}")
    set_setting("match_mode", mode)
    return mode


# Vaznli rejimda ruxsat etilgan chegaralar (botdan tanlanadi)
SCORE_THRESHOLDS = (0.5, 1.0, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0)


def get_score_threshold() -> float:
    try:
        return float(get_setting("score_threshold") or 1.75)
    except (TypeError, ValueError):
        return 1.75


def set_score_threshold(value: float) -> float:
    value = max(-10.0, min(10.0, float(value)))
    set_setting("score_threshold", value)
    return value


def get_match_count() -> int:
    """Admin belgilagan shart: nechta kalit so'z topilsa xabar beriladi."""
    with closing(_connect()) as conn:
        res = conn.execute(
            "SELECT value FROM settings WHERE key = 'match_count'"
        ).fetchone()
    try:
        return max(1, int(res[0])) if res else 3
    except (TypeError, ValueError):
        return 3


# --- Foydalanuvchilar va tariflar ---

def upsert_user(user_id: int, first_name: str = "", username: str = "") -> None:
    import time

    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO users (user_id, first_name, username, created_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET first_name = excluded.first_name, "
            "username = excluded.username",
            (user_id, first_name or "", username or "", int(time.time())),
        )


def get_user(user_id: int):
    """(user_id, first_name, username, is_blocked, sub_expires_at, created_at)."""
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT user_id, first_name, username, is_blocked, "
            "sub_expires_at, created_at FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()


def get_all_users() -> list[tuple]:
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT user_id, first_name, username, is_blocked, "
            "sub_expires_at, created_at FROM users ORDER BY created_at"
        ).fetchall()


def set_user_blocked(user_id: int, blocked: bool) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET is_blocked = ? WHERE user_id = ?",
            (1 if blocked else 0, user_id),
        )


def is_subscription_active(user_id: int) -> bool:
    import time

    row = get_user(user_id)
    if not row or row[3]:
        return False
    return (row[4] or 0) > int(time.time())


# --- Registratsiya, sessiyalar, foydalanuvchi guruhlari ---

USER_COLUMNS = (
    "user_id, first_name, username, is_blocked, sub_expires_at, created_at, "
    "COALESCE(full_name,''), COALESCE(phone,''), COALESCE(session_enc,''), "
    "COALESCE(pending_session_enc,''), COALESCE(awaiting_approval,0), "
    "COALESCE(session_status,'none'), COALESCE(last_warn_date,''), "
    "COALESCE(last_found_at,0), COALESCE(scanner_enabled,1)"
)


def get_user_full(user_id: int):
    with closing(_connect()) as conn:
        return conn.execute(
            f"SELECT {USER_COLUMNS} FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()


def get_all_users_full() -> list[tuple]:
    with closing(_connect()) as conn:
        return conn.execute(
            f"SELECT {USER_COLUMNS} FROM users ORDER BY created_at"
        ).fetchall()


def set_registration_info(user_id: int, full_name: str, phone: str = "") -> None:
    with closing(_connect()) as conn, conn:
        if phone:
            conn.execute(
                "UPDATE users SET full_name = ?, phone = ? WHERE user_id = ?",
                (full_name, phone, user_id),
            )
        else:
            conn.execute(
                "UPDATE users SET full_name = ? WHERE user_id = ?",
                (full_name, user_id),
            )


def get_user_by_phone(phone: str):
    with closing(_connect()) as conn:
        return conn.execute(
            f"SELECT {USER_COLUMNS} FROM users WHERE phone = ?", (phone,)
        ).fetchone()


def set_pending_session(user_id: int, session_enc: str) -> None:
    """Login tugadi: sessiya pending (shifrlangan) + tasdiq kutilmoqda — atomik."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET pending_session_enc = ?, awaiting_approval = 1, "
            "session_status = 'pending' WHERE user_id = ?",
            (session_enc, user_id),
        )


def approve_pending_session(user_id: int) -> bool:
    """pending_session -> session (atomik). Pending bo'lmasa False."""
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "UPDATE users SET session_enc = pending_session_enc, "
            "pending_session_enc = '', awaiting_approval = 0, "
            "session_status = 'active' WHERE user_id = ? "
            "AND pending_session_enc != ''",
            (user_id,),
        )
    return cur.rowcount > 0


def clear_pending_session(user_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET pending_session_enc = '', awaiting_approval = 0, "
            "session_status = 'none' WHERE user_id = ?",
            (user_id,),
        )


def set_session_status(user_id: int, status: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET session_status = ? WHERE user_id = ?",
            (status, user_id),
        )


def clear_session(user_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET session_enc = '', session_status = 'none' "
            "WHERE user_id = ?",
            (user_id,),
        )


def get_user_scanner_enabled(user_id: int) -> bool:
    """Foydalanuvchining UMUMIY skaneri yoniqmi (bitta Stop/Start)."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT COALESCE(scanner_enabled,1) FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return bool(row[0]) if row else True


def set_user_scanner_enabled(user_id: int, enabled: bool) -> bool:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET scanner_enabled = ? WHERE user_id = ?",
            (1 if enabled else 0, user_id),
        )
    return enabled


def get_user_match_count(user_id: int) -> int:
    """Foydalanuvchining O'Z xabar sharti.

    O'zi belgilamagan bo'lsa (0) — adminning umumiy sharti ishlatiladi.
    """
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT COALESCE(own_match_count,0) FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row and row[0]:
        return max(1, int(row[0]))
    return get_match_count()


def set_user_match_count(user_id: int, value: int) -> int:
    """Foydalanuvchi o'z shartini belgilaydi (faqat o'ziga ta'sir qiladi)."""
    value = max(1, int(value))
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET own_match_count = ? WHERE user_id = ?",
            (value, user_id),
        )
    return value


def get_user_score_threshold(user_id: int) -> float:
    """Foydalanuvchining O'Z ball chegarasi.

    O'zi belgilamagan bo'lsa (0) — adminning umumiy chegarasi ishlatiladi.
    Qaytaradi: samarali qiymat (``float``).
    """
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT COALESCE(own_score_threshold,0) FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row and row[0]:
        try:
            return float(row[0])
        except (TypeError, ValueError):
            pass
    return get_score_threshold()


def get_own_score_threshold(user_id: int) -> float:
    """Faqat foydalanuvchi o'zi belgilagan qiymat (0 = belgilanmagan)."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT COALESCE(own_score_threshold,0) FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    try:
        return float(row[0]) if row else 0.0
    except (TypeError, ValueError):
        return 0.0


def set_user_score_threshold(user_id: int, value: float) -> float:
    """Chegarani belgilaydi. ``0`` — admin standartiga qaytish."""
    value = float(value)
    if value:
        value = max(-10.0, min(10.0, value))
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET own_score_threshold = ? WHERE user_id = ?",
            (value, user_id),
        )
    return value


def delete_user_completely(user_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM user_groups WHERE owner_user_id = ?", (user_id,))
        conn.execute("DELETE FROM user_counters WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))


def set_new_term(user_id: int, days: int) -> int:
    """YANGI muddat: eskisi BEKOR bo'ladi, hozirdan boshlanadi.

    Qaytaradi: yangi tugash vaqti (unix). Ogohlantirish belgisi ham tozalanadi.
    """
    import time

    expiry = int(time.time()) + int(days) * 86400
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET sub_expires_at = ?, last_warn_date = '' "
            "WHERE user_id = ?",
            (expiry, user_id),
        )
    return expiry


def get_expiring_users(within_days: int = 3) -> list[tuple]:
    """Muddati within_days ichida tugaydigan (hali tugamagan) foydalanuvchilar."""
    import time

    now = int(time.time())
    with closing(_connect()) as conn:
        return conn.execute(
            f"SELECT {USER_COLUMNS} FROM users WHERE is_blocked = 0 "
            "AND sub_expires_at > ? AND sub_expires_at <= ?",
            (now, now + within_days * 86400),
        ).fetchall()


def mark_warned_today(user_id: int) -> None:
    import datetime

    today = datetime.date.today().isoformat()
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET last_warn_date = ? WHERE user_id = ?",
            (today, user_id),
        )


MAX_USER_GROUPS = 100


def count_user_groups(owner_user_id: int) -> int:
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM user_groups WHERE owner_user_id = ?",
            (owner_user_id,),
        ).fetchone()[0]


def add_user_group(owner_user_id: int, input_value: str):
    """(True, '') yoki (False, xato matni). Limit: MAX_USER_GROUPS."""
    if count_user_groups(owner_user_id) >= MAX_USER_GROUPS:
        return False, f"Limit: bitta foydalanuvchi ko'pi bilan {MAX_USER_GROUPS} ta guruh qo'sha oladi"
    try:
        with closing(_connect()) as conn, conn:
            conn.execute(
                "INSERT INTO user_groups (owner_user_id, input_value) VALUES (?, ?)",
                (owner_user_id, input_value),
            )
        return True, ""
    except sqlite3.IntegrityError:
        return False, "Bu guruh sizda allaqachon qo'shilgan"


def get_user_groups(owner_user_id: int) -> list[tuple]:
    """(id, owner, input, chat_id, title, is_active, status, last_error)."""
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT id, owner_user_id, input_value, chat_id, title, "
            "is_active, status, last_error FROM user_groups "
            "WHERE owner_user_id = ? ORDER BY id",
            (owner_user_id,),
        ).fetchall()


def get_all_user_groups() -> list[tuple]:
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT id, owner_user_id, input_value, chat_id, title, "
            "is_active, status, last_error FROM user_groups ORDER BY id"
        ).fetchall()


def delete_user_group(group_id: int, owner_user_id: int | None = None) -> None:
    with closing(_connect()) as conn, conn:
        if owner_user_id is None:
            conn.execute("DELETE FROM user_groups WHERE id = ?", (group_id,))
        else:
            conn.execute(
                "DELETE FROM user_groups WHERE id = ? AND owner_user_id = ?",
                (group_id, owner_user_id),
            )


def toggle_user_group(group_id: int, owner_user_id: int, status: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE user_groups SET is_active = ? WHERE id = ? "
            "AND owner_user_id = ?",
            (1 if status else 0, group_id, owner_user_id),
        )


def get_user_group(group_id: int):
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT id, owner_user_id, input_value, chat_id, title, "
            "is_active, status, last_error FROM user_groups WHERE id = ?",
            (group_id,),
        ).fetchone()


def get_pending_user_groups(owner_user_id: int | None = None) -> list[tuple]:
    with closing(_connect()) as conn:
        if owner_user_id is None:
            return conn.execute(
                "SELECT id, owner_user_id, input_value, chat_id, status "
                "FROM user_groups WHERE status IN ('pending','error')"
            ).fetchall()
        return conn.execute(
            "SELECT id, owner_user_id, input_value, chat_id, status "
            "FROM user_groups WHERE owner_user_id = ? "
            "AND status IN ('pending','error')",
            (owner_user_id,),
        ).fetchall()


def resolve_user_group(group_id: int, chat_id: int, title: str) -> bool:
    try:
        with closing(_connect()) as conn, conn:
            conn.execute(
                "UPDATE user_groups SET chat_id = ?, title = ?, status = 'ok', "
                "last_error = NULL WHERE id = ?",
                (chat_id, title, group_id),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def mark_user_group_error(group_id: int, error: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE user_groups SET status = 'error', last_error = ? WHERE id = ?",
            (str(error)[:300], group_id),
        )


def requeue_user_group(group_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE user_groups SET status = 'pending', last_error = NULL "
            "WHERE id = ?",
            (group_id,),
        )


def get_owner_active_chat_ids(owner_user_id: int) -> list[int]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT chat_id FROM user_groups WHERE owner_user_id = ? "
            "AND status = 'ok' AND is_active = 1 AND chat_id IS NOT NULL",
            (owner_user_id,),
        ).fetchall()
    return [row[0] for row in rows]


def increment_user_counter(user_id: int, key: str, amount: int = 1) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO user_counters (user_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = value + ?",
            (user_id, key, amount, amount),
        )


def get_user_counter(user_id: int, key: str) -> int:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT value FROM user_counters WHERE user_id = ? AND key = ?",
            (user_id, key),
        ).fetchone()
    return int(row[0]) if row else 0


def set_user_last_found(user_id: int) -> None:
    import time

    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET last_found_at = ? WHERE user_id = ?",
            (int(time.time()), user_id),
        )


# Markaziy rejimdagi "barcha obunachilarga tarqatish" funksiyasi ataylab
# o'chirilgan: endi topilgan xabar FAQAT guruh egasiga boradi
# (scanner_manager._make_handler -> send_to_bot_api(chat_id=owner_id)).


def increment_counter(key: str, amount: int = 1) -> int:
    """Statistika hisoblagichi (topilgan mijozlar, yuborilgan xabarlar...)."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + ?",
            (key, amount, amount),
        )
        res = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return int(res[0]) if res else 0


def get_counter(key: str) -> int:
    with closing(_connect()) as conn:
        res = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    try:
        return int(res[0]) if res else 0
    except (TypeError, ValueError):
        return 0


def get_setting(key: str) -> str | None:
    with closing(_connect()) as conn:
        res = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return res[0] if res else None


def set_setting(key: str, value) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value)),
        )

# --- Nazorat navbati (admin o'qitishi uchun) ---

REVIEW_LABELS = ("ok", "bad", "skip")


def add_review_item(text: str, score: float = 0.0, threshold: float = 0.0,
                    words=None) -> int:
    """Topilgan xabarni nazorat navbatiga qo'shadi (anonim).

    Bir xil matn ikkinchi marta qo'shilmaydi: ``0`` qaytadi. Aks holda
    bir xabar (turli guruhlarda, turli kunlarda takrorlangan bo'lsa)
    navbatni to'ldirib, adminni behuda band qilardi.
    """
    import json
    cleaned = (text or "").strip()
    if not cleaned:
        return 0
    payload = json.dumps(list(words or []), ensure_ascii=False)
    with closing(_connect()) as conn, conn:
        duplicate = conn.execute(
            "SELECT 1 FROM review_items WHERE text = ? LIMIT 1", (cleaned,)
        ).fetchone()
        if duplicate:
            return 0
        cur = conn.execute(
            "INSERT INTO review_items (text, score, threshold, words, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (cleaned, float(score), float(threshold), payload, int(time.time())),
        )
        return int(cur.lastrowid or 0)


def get_next_review_item():
    """Baholanmagan eng qadimgi xabar: ``(id, text, score, threshold, words)``."""
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT id, text, score, threshold, words FROM review_items"
            " WHERE label IS NULL ORDER BY id LIMIT 1"
        ).fetchone()


def get_review_item(item_id: int):
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT id, text, score, threshold, words, label FROM review_items"
            " WHERE id = ?", (item_id,)
        ).fetchone()


def set_review_item_label(item_id: int, label: str) -> bool:
    """Yorliqni yozadi. Allaqachon belgilangan bo'lsa False."""
    if label not in REVIEW_LABELS:
        return False
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "UPDATE review_items SET label = ?, labeled_at = ?"
            " WHERE id = ? AND label IS NULL",
            (label, int(time.time()), item_id),
        )
        return cur.rowcount > 0


def review_stats() -> dict:
    """Navbat statistikasi: jami / kutilayotgan / to'g'ri / noto'g'ri / ⚡.

    ``near`` — chegaradan past bo'lgan (ya'ni model o'tkazib yuborgan)
    xabarlar soni. Ular navbatga faqat ⚡ rejimida tushadi.
    """
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT COALESCE(label, 'pending') AS st, COUNT(*) FROM review_items"
            " GROUP BY st"
        ).fetchall()
        near = conn.execute(
            "SELECT COUNT(*) FROM review_items WHERE score < threshold"
        ).fetchone()
    data = {key: 0 for key in REVIEW_LABELS + ("pending",)}
    for status, count in rows:
        data[status] = int(count)
    data["near"] = int(near[0] or 0) if near else 0
    data["total"] = sum(
        data[key] for key in REVIEW_LABELS + ("pending",)
    )
    return data


def purge_review_items(days: int = 90) -> int:
    """Eski yozuvlarni tozalaydi (baholanmaganlar ham)."""
    limit = int(time.time()) - int(days) * 86400
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "DELETE FROM review_items WHERE created_at < ?", (limit,)
        )
        return cur.rowcount

# --- Ro'yxatni eksport / import (zaxira nusxa) ---

def export_phrases_text() -> str:
    """Ro'yxatni qayta yuklash mumkin bo'lgan matn ko'rinishida qaytaradi.

    Har qatorda bitta yozuv: ``+3 kerak`` / ``-4 joy bor``. Bu formatni
    ``AddPhrase`` ham, ``import_phrases`` ham tushunadi — ya'ni nusxa
    bazaga qaytariladi.
    """
    lines = []
    for _pid, word, weight, _strict in get_phrases_full():
        lines.append(f"{weight:+g} {word}")
    return "\n".join(lines)


def import_phrases(pairs, replace: bool = False) -> dict:
    """``[(yozuv, vazn), ...]`` ni bazaga qo'llaydi.

    Mavjud yozuvning vazni yangilanadi, yangisi qo'shiladi.
    ``replace=True`` bo'lsa faylda **yo'q** yozuvlar o'chiriladi (to'liq
    almashtirish — ro'yxat fayl bilan bir xil bo'ladi).

    Qaytaradi: ``{"added", "updated", "skipped", "invalid", "removed"}``.
    """
    added, updated, skipped, invalid, removed = [], [], [], [], []
    if replace:
        keep = set()
        for word, _weight in pairs:
            cleaned = display_entry(word)
            if cleaned:
                keep.add(canonical_entry(cleaned))
        for pid, word, _weight, _strict in get_phrases_full():
            if canonical_entry(word) not in keep:
                delete_phrase(pid)
                removed.append(word)
    for word, weight in pairs:
        cleaned = display_entry(word)
        if not cleaned:
            continue
        pid = word_id_by_text(cleaned)
        if pid is None:
            added_ok, conflicts = add_keyword_checked(cleaned, weight=weight)
            if added_ok:
                added.append((cleaned, float(weight)))
            elif conflicts:
                invalid.append((cleaned, "boshqa ro'yxatda"))
            else:
                skipped.append((cleaned, "takror"))
            continue
        row = get_phrase(pid)
        old = float(row[2]) if row else 0.0
        new = max(-10.0, min(10.0, float(weight)))
        if abs(old - new) < 0.001:
            skipped.append((cleaned, "o'zgarmagan"))
        else:
            update_phrase(pid, weight=new)
            updated.append((cleaned, old, new))
    return {
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "invalid": invalid,
        "removed": removed,
    }
