import sqlite3
from contextlib import closing

from config import DB_NAME


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
        # Qo'lda qo'shilgan guruhlar jadvali (asosiy).
        # chat_id userbot tekshirgach to'ldiriladi, ungacha NULL bo'ladi.
        conn.execute("""CREATE TABLE IF NOT EXISTS managed_groups (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            input_value TEXT UNIQUE,
                            chat_id INTEGER UNIQUE,
                            title TEXT,
                            is_active INTEGER DEFAULT 1,
                            status TEXT DEFAULT 'pending',
                            last_error TEXT)""")
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


def get_keywords() -> list[str]:
    """Barcha kalit so'zlar (soni cheksiz)."""
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT text FROM phrases ORDER BY id").fetchall()
    return [row[0] for row in rows]


# Eski nomlar (moslik uchun)
def get_phrases() -> list[str]:
    return get_keywords()


def add_keyword(word: str) -> bool:
    """True — saqlandi, False — bu so'z allaqachon kalitlarda bor."""
    try:
        with closing(_connect()) as conn, conn:
            conn.execute("INSERT INTO phrases (text) VALUES (?)", (word,))
        return True
    except sqlite3.IntegrityError:
        return False


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


# --- Qo'lda qo'shilgan guruhlar (managed_groups) ---

def add_managed_group(input_value: str) -> bool:
    """True — qo'shildi, False — bu manzil/ID allaqachon bor."""
    try:
        with closing(_connect()) as conn, conn:
            conn.execute(
                "INSERT INTO managed_groups (input_value) VALUES (?)",
                (input_value,),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def get_managed_groups() -> list[tuple]:
    """(id, input_value, chat_id, title, is_active, status, last_error)."""
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT id, input_value, chat_id, title, is_active, status, "
            "last_error FROM managed_groups ORDER BY id"
        ).fetchall()


def delete_managed_group(group_id: int) -> None:
    """Guruh butunlay o'chib ketadi (tiklanmaydi)."""
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM managed_groups WHERE id = ?", (group_id,))


def toggle_managed_group(group_id: int, status: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE managed_groups SET is_active = ? WHERE id = ?",
            (1 if status else 0, group_id),
        )


def get_pending_groups() -> list[tuple]:
    """Userbot tekshirishi kerak bo'lgan guruhlar (pending/error)."""
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT id, input_value, chat_id, status FROM managed_groups "
            "WHERE status IN ('pending', 'error')"
        ).fetchall()


def resolve_managed_group(group_id: int, chat_id: int, title: str) -> bool:
    """Userbot guruhni topdi: haqiqiy ID/nom yoziladi, status='ok'.

    False — bu chat_id boshqa yozuvda allaqachon bor (dublikat).
    """
    try:
        with closing(_connect()) as conn, conn:
            conn.execute(
                "UPDATE managed_groups SET chat_id = ?, title = ?, "
                "status = 'ok', last_error = NULL WHERE id = ?",
                (chat_id, title, group_id),
            )
        return True
    except sqlite3.IntegrityError:
        mark_managed_group_error(group_id, "Bu guruh ro'yxatda allaqachon bor (dublikat)")
        return False


def mark_managed_group_error(group_id: int, error: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE managed_groups SET status = 'error', last_error = ? "
            "WHERE id = ?",
            (str(error)[:300], group_id),
        )


def requeue_managed_group(group_id: int) -> None:
    """Qayta tekshirish: statusni 'pending' ga qaytaradi."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE managed_groups SET status = 'pending', last_error = NULL "
            "WHERE id = ?",
            (group_id,),
        )


def get_active_chat_ids() -> list[int]:
    """Skaner qilinadigan guruhlar: tekshiruvdan o'tgan VA yoqilgan."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT chat_id FROM managed_groups "
            "WHERE status = 'ok' AND is_active = 1 AND chat_id IS NOT NULL"
        ).fetchall()
    return [row[0] for row in rows]


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


def extend_subscription(user_id: int, days: int = 30) -> int:
    """Obunani uzaytiradi (mavjud muddatdan davom etadi). Yangi tugash vaqtini qaytaradi."""
    import time

    now = int(time.time())
    row = get_user(user_id)
    current = row[4] if row and row[4] else 0
    new_expiry = max(now, current) + int(days) * 86400
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET sub_expires_at = ? WHERE user_id = ?",
            (new_expiry, user_id),
        )
    return new_expiry


def is_subscription_active(user_id: int) -> bool:
    import time

    row = get_user(user_id)
    if not row or row[3]:
        return False
    return (row[4] or 0) > int(time.time())


def get_active_subscriber_ids() -> list[int]:
    """Tarifi faol va bloklanmagan foydalanuvchilar."""
    import time

    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT user_id FROM users WHERE is_blocked = 0 "
            "AND sub_expires_at > ?",
            (int(time.time()),),
        ).fetchall()
    return [row[0] for row in rows]


# --- Registratsiya, sessiyalar, foydalanuvchi guruhlari ---

USER_COLUMNS = (
    "user_id, first_name, username, is_blocked, sub_expires_at, created_at, "
    "COALESCE(full_name,''), COALESCE(phone,''), COALESCE(session_enc,''), "
    "COALESCE(pending_session_enc,''), COALESCE(awaiting_approval,0), "
    "COALESCE(session_status,'none'), COALESCE(last_warn_date,''), "
    "COALESCE(last_found_at,0)"
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


def get_notification_recipients(admin_id: int) -> list[int]:
    """Bildirishnoma oluvchilar: admin + faol obunachilar (takrorsiz)."""
    recipients = []
    for uid in [admin_id, *get_active_subscriber_ids()]:
        if uid and uid not in recipients:
            recipients.append(uid)
    return recipients


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


def save_groups(groups_list) -> None:
    with closing(_connect()) as conn, conn:
        for g in groups_list:
            title = getattr(g, "title", None) or getattr(g, "first_name", "") or str(g.id)
            conn.execute(
                "INSERT INTO groups (chat_id, title) VALUES (?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title",
                (g.id, title),
            )


def get_groups() -> list[tuple[int, str, int]]:
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT chat_id, title, is_active FROM groups ORDER BY title"
        ).fetchall()


def toggle_group(chat_id: int, status: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE groups SET is_active = ? WHERE chat_id = ?",
            (1 if status else 0, chat_id),
        )


def get_active_groups_ids() -> list[int]:
    # Skaner faqat qo'lda qo'shilib tekshirilgan guruhlarni ko'radi
    return get_active_chat_ids()


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
