import sqlite3
from config import DB_NAME

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Iboralar jadvali
    cursor.execute('''CREATE TABLE IF NOT EXISTS phrases (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        text TEXT UNIQUE)''')
    # Guruhlar jadvali
    cursor.execute('''CREATE TABLE IF NOT EXISTS groups (
                        chat_id INTEGER PRIMARY KEY,
                        title TEXT,
                        is_active INTEGER DEFAULT 0)''')
    # Sozlamalar jadvali
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT)''')
    # Standart sozlamalar
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('is_active', '1')")
    conn.commit()
    conn.close()

def get_phrases():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT text FROM phrases")
    phrases = [row[0] for row in cursor.fetchall()]
    conn.close()
    return phrases

def add_phrase(text):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO phrases (text) VALUES (?)", (text,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_phrase(phrase_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM phrases WHERE id = ?", (phrase_id,))
    conn.commit()
    conn.close()

def get_all_phrases_with_id():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, text FROM phrases")
    phrases = cursor.fetchall()
    conn.close()
    return phrases

def save_groups(groups_list):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    for g in groups_list:
        cursor.execute("INSERT OR IGNORE INTO groups (chat_id, title) VALUES (?, ?)", (g.id, g.title))
    conn.commit()
    conn.close()

def get_groups():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id, title, is_active FROM groups")
    groups = cursor.fetchall()
    conn.close()
    return groups

def toggle_group(chat_id, status):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE groups SET is_active = ? WHERE chat_id = ?", (status, chat_id))
    conn.commit()
    conn.close()

def get_active_groups_ids():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM groups WHERE is_active = 1")
    groups = [row[0] for row in cursor.fetchall()]
    conn.close()
    return groups

def get_setting(key):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else None

def set_setting(key, value):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()
