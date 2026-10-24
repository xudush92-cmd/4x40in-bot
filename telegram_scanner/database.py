import sqlite3
from contextlib import closing

from config import DB_NAME
from matcher import canonical_entry


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_NAME)


def init_db() -> None:
    with closing(_connect()) as conn, conn:
        # Kalit so'zlar jadvali: HAR BIR qatorda BITTA so'z (kalit).
        # (Jadval nomi tarixiy sabab bilan 'phrases' bo'lib qolgan.)
        conn.execute("""CREATE TABLE IF NOT EXISTS phrases (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            text TEXT UNIQUE)""")
        _migrate_old_sets(conn)
        # Guruhlar jadvali
        conn.execute("""CREATE TABLE IF NOT EXISTS groups (
                            chat_id INTEGER PRIMARY KEY,
                            title TEXT,
                            is_active INTEGER DEFAULT 0)""")
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
        # Foydalanuvchi statistikasi hisoblagichlari
        conn.execute("""CREATE TABLE IF NOT EXISTS user_counters (
                            user_id INTEGER NOT NULL,
                            key TEXT NOT NULL,
                            value INTEGER DEFAULT 0,
                            PRIMARY KEY (user_id, key))""")
        # Stop-so'zlar (haydovchi e'lonlari filtri) — admin boshqaradi.
        conn.execute("""CREATE TABLE IF NOT EXISTS stop_words (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            text TEXT UNIQUE)""")
        # Mijozga xos so'zlar (ikkinchi filtr) — admin boshqaradi.
        conn.execute("""CREATE TABLE IF NOT EXISTS client_words (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            text TEXT UNIQUE)""")
        # Filtr so'zlari kodda yozilmaydi: ularni faqat admin botdan kiritadi.
        # Standart sozlamalar
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('is_active', '1')"
        )
        # Xabar berish sharti: nechta kalit so'z topilsa xabar beriladi
        # (admin botdan xohlagan vaqtda o'zgartiradi)
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('match_count', '3')"
        )


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
    }
    for name, ddl in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")


def _migrate_old_sets(conn) -> None:
    """Eski 'to'plam' yozuvlarini alohida kalit so'zlarga bo'ladi.

    Avvalgi modelda bitta qatorda bir nechta so'z saqlangan bo'lishi
    mumkin — har bir so'z alohida kalit qatoriga aylanadi.
    """
    from matcher import parse_key_words

    rows = conn.execute("SELECT id, text FROM phrases").fetchall()
    for row_id, text in rows:
        words = parse_key_words(text or "")
        if len(words) <= 1:
            continue
        conn.execute("DELETE FROM phrases WHERE id = ?", (row_id,))
        for word in words:
            conn.execute(
                "INSERT OR IGNORE INTO phrases (text) VALUES (?)", (word,)
            )


# Filtr so'zlari kodda saqlanmaydi va avtomatik yozilmaydi.
# Ularni admin botdagi tegishli bo'limlardan bazaga kiritadi.
_FILTER_TABLES = {"stop_words", "client_words"}

# Barcha so'z ro'yxatlari: bitta so'z bir nechta ro'yxatda bo'lmasligi kerak.
_WORD_LISTS = (
    ("phrases", "kalit so'zlar"),
    ("stop_words", "stop-so'zlar"),
    ("client_words", "mijoz so'zlari"),
)


def find_lists_for_entry(entry: str) -> list[str]:
    """So'z qaysi ro'yxatlarda borligini qaytaradi (nomlari bilan).

    Lotin/kirill, katta-kichik harf va tinish belgilari farqi
    hisobga olinmaydi.
    """
    canonical = canonical_entry(entry)
    if not canonical:
        return []
    found = []
    with closing(_connect()) as conn:
        for table, label in _WORD_LISTS:
            rows = conn.execute(f"SELECT text FROM {table}").fetchall()
            if any(canonical_entry(row[0]) == canonical for row in rows):
                found.append(label)
    return found


def get_filter_words(table: str) -> list[str]:
    if table not in _FILTER_TABLES:
        raise ValueError(table)
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT text FROM {table} ORDER BY id"
        ).fetchall()
    return [row[0] for row in rows]


def get_filter_words_with_id(table: str) -> list[tuple[int, str]]:
    if table not in _FILTER_TABLES:
        raise ValueError(table)
    with closing(_connect()) as conn:
        return conn.execute(
            f"SELECT id, text FROM {table} ORDER BY id"
        ).fetchall()


def add_filter_word_checked(table: str, entry: str) -> tuple[bool, list[str]]:
    """Yozuv qo'shadi: (qo'shildimi, qaysi ro'yxatlarda borligi).

    So'z boshqa ro'yxatda (kalit/stop/mijoz) bo'lsa ham qo'shilmaydi —
    chaqiruvchi bot aynan qaysi ro'yxatda ekanini ko'rsatadi.
    """
    if table not in _FILTER_TABLES:
        raise ValueError(table)
    cleaned = " ".join((entry or "").split()).lower()
    if not canonical_entry(cleaned):
        return False, []
    conflicts = find_lists_for_entry(cleaned)
    if conflicts:
        return False, conflicts
    with closing(_connect()) as conn, conn:
        try:
            conn.execute(
                f"INSERT INTO {table} (text) VALUES (?)", (cleaned,)
            )
        except sqlite3.IntegrityError:
            return False, find_lists_for_entry(cleaned)
    return True, []


def add_filter_word(table: str, entry: str) -> bool:
    """Eski interfeys: True — qo'shildi."""
    added, _conflicts = add_filter_word_checked(table, entry)
    return added


def delete_filter_word(table: str, word_id: int) -> None:
    if table not in _FILTER_TABLES:
        raise ValueError(table)
    with closing(_connect()) as conn, conn:
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (word_id,))


def get_stop_words() -> list[str]:
    return get_filter_words("stop_words")


def get_client_words() -> list[str]:
    return get_filter_words("client_words")


def get_keywords() -> list[str]:
    """Barcha kalit so'zlar (soni cheksiz)."""
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT text FROM phrases ORDER BY id").fetchall()
    return [row[0] for row in rows]


# Eski nomlar (moslik uchun)
def get_phrases() -> list[str]:
    return get_keywords()


def add_keyword_checked(word: str) -> tuple[bool, list[str]]:
    """Kalit qo'shadi: (qo'shildimi, qaysi ro'yxatlarda borligi).

    Takroriylik lotin/kirill va katta-kichik harf farqini hisobga
    olmasdan tekshiriladi: ``ТОШКЕНТ`` bilan ``toshkent`` bitta kalit.
    So'z stop/mijoz ro'yxatida bo'lsa ham kalitga qo'shilmaydi.
    """
    cleaned = " ".join((word or "").split()).lower()
    if not canonical_entry(cleaned):
        return False, []
    conflicts = find_lists_for_entry(cleaned)
    if conflicts:
        return False, conflicts
    with closing(_connect()) as conn, conn:
        try:
            conn.execute(
                "INSERT INTO phrases (text) VALUES (?)", (cleaned,)
            )
        except sqlite3.IntegrityError:
            return False, find_lists_for_entry(cleaned)
    return True, []


def add_keyword(word: str) -> bool:
    """Eski interfeys: True — saqlandi."""
    added, _conflicts = add_keyword_checked(word)
    return added


def add_phrase(text: str, required_count: int = 2) -> bool:
    return add_keyword(text)


def delete_phrase(phrase_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM phrases WHERE id = ?", (phrase_id,))


def get_all_phrases_with_id() -> list[tuple[int, str]]:
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT id, text FROM phrases ORDER BY id"
        ).fetchall()


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
