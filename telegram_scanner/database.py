import sqlite3
from contextlib import closing

from config import DB_NAME


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_NAME)


def init_db() -> None:
    with closing(_connect()) as conn, conn:
        # Iboralar jadvali
        conn.execute("""CREATE TABLE IF NOT EXISTS phrases (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            text TEXT UNIQUE)""")
        # Guruhlar jadvali
        conn.execute("""CREATE TABLE IF NOT EXISTS groups (
                            chat_id INTEGER PRIMARY KEY,
                            title TEXT,
                            is_active INTEGER DEFAULT 0)""")
        # Sozlamalar jadvali
        conn.execute("""CREATE TABLE IF NOT EXISTS settings (
                            key TEXT PRIMARY KEY,
                            value TEXT)""")
        # Standart sozlamalar
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('is_active', '1')"
        )


def get_phrases() -> list[str]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT text FROM phrases ORDER BY id").fetchall()
    return [row[0] for row in rows]


def add_phrase(text: str) -> bool:
    """True — saqlandi, False — bu ibora allaqachon bor."""
    try:
        with closing(_connect()) as conn, conn:
            conn.execute("INSERT INTO phrases (text) VALUES (?)", (text,))
        return True
    except sqlite3.IntegrityError:
        return False


def delete_phrase(phrase_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM phrases WHERE id = ?", (phrase_id,))


def get_all_phrases_with_id() -> list[tuple[int, str]]:
    with closing(_connect()) as conn:
        return conn.execute("SELECT id, text FROM phrases ORDER BY id").fetchall()


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
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT chat_id FROM groups WHERE is_active = 1"
        ).fetchall()
    return [row[0] for row in rows]


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
