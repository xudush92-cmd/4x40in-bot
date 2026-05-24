"""
database.py — SQLite asosidagi storage.

JSON fayllar o'rniga yagona SQLite bazada barcha ma'lumotlar saqlanadi.
Afzalliklari:
- Concurrent access xavfsiz (WAL mode)
- Corruption riski deyarli yo'q
- 1000+ foydalanuvchi uchun tez ishlaydi
- Backup = bitta fayl nusxalash
"""

import aiosqlite
import json
import os
from datetime import time as dtime
from typing import Any

DB_PATH = os.path.join("data", "avto_bot.db")
os.makedirs("data", exist_ok=True)


async def init_db() -> None:
    """Bazani yaratish va jadvallarni sozlash."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                uid INTEGER PRIMARY KEY,
                name TEXT DEFAULT '',
                username TEXT DEFAULT '',
                session TEXT,
                pending_session TEXT,
                is_admin INTEGER DEFAULT 0,
                interval_min INTEGER DEFAULT 4,
                schedule_start TEXT DEFAULT '00:00',
                schedule_end TEXT DEFAULT '23:59',
                running INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                chat_id TEXT NOT NULL,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(uid, chat_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                text_content TEXT DEFAULT '',
                entities TEXT DEFAULT '[]',
                photo_path TEXT,
                link_preview INTEGER DEFAULT 1,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS report_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        await db.commit()


# ─────────────────────────────────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────────────────────────────────
async def get_user(uid: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE uid=?", (uid,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def upsert_user(uid: int, **kwargs) -> None:
    """Foydalanuvchini yaratish yoki yangilash."""
    async with aiosqlite.connect(DB_PATH) as db:
        existing = await get_user(uid)
        if existing is None:
            cols = ["uid"] + list(kwargs.keys())
            vals = [uid] + list(kwargs.values())
            placeholders = ",".join(["?"] * len(vals))
            col_names = ",".join(cols)
            await db.execute(f"INSERT INTO users ({col_names}) VALUES ({placeholders})", vals)
        else:
            if kwargs:
                sets = ",".join(f"{k}=?" for k in kwargs)
                vals = list(kwargs.values()) + [uid]
                await db.execute(f"UPDATE users SET {sets} WHERE uid=?", vals)
        await db.commit()


async def delete_user(uid: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE uid=?", (uid,))
        await db.execute("DELETE FROM chats WHERE uid=?", (uid,))
        await db.execute("DELETE FROM posts WHERE uid=?", (uid,))
        await db.commit()


async def get_session(uid: int) -> str | None:
    user = await get_user(uid)
    return user["session"] if user else None


async def set_session(uid: int, sess: str) -> None:
    await upsert_user(uid, session=sess)


async def del_session(uid: int) -> None:
    await upsert_user(uid, session=None)


async def get_pending(uid: int) -> str | None:
    user = await get_user(uid)
    return user["pending_session"] if user else None


async def set_pending(uid: int, sess: str) -> None:
    await upsert_user(uid, pending_session=sess)


async def del_pending(uid: int) -> None:
    await upsert_user(uid, pending_session=None)


async def get_admins() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT uid FROM users WHERE is_admin=1") as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]


async def add_admin(uid: int) -> None:
    await upsert_user(uid, is_admin=1)


async def remove_admin(uid: int) -> None:
    await upsert_user(uid, is_admin=0)


async def is_admin(uid: int) -> bool:
    user = await get_user(uid)
    return bool(user and user["is_admin"])


async def get_user_info(uid: int) -> dict:
    user = await get_user(uid)
    if not user:
        return {}
    return {"name": user["name"], "username": user["username"]}


async def set_user_info(uid: int, name: str, username: str) -> None:
    await upsert_user(uid, name=name, username=username)


# ─────────────────────────────────────────────────────────────────────────
# INTERVAL & SCHEDULE
# ─────────────────────────────────────────────────────────────────────────
async def get_interval(uid: int) -> int:
    user = await get_user(uid)
    return user["interval_min"] if user else 4


async def set_interval(uid: int, minutes: int) -> None:
    await upsert_user(uid, interval_min=minutes)


async def get_schedule(uid: int) -> tuple[dtime, dtime]:
    user = await get_user(uid)
    if not user:
        return dtime(0, 0), dtime(23, 59)
    try:
        sh, sm = map(int, user["schedule_start"].split(":"))
        eh, em = map(int, user["schedule_end"].split(":"))
        return dtime(sh, sm), dtime(eh, em)
    except Exception:
        return dtime(0, 0), dtime(23, 59)


async def set_schedule(uid: int, start: dtime, end: dtime) -> None:
    await upsert_user(
        uid,
        schedule_start=start.strftime("%H:%M"),
        schedule_end=end.strftime("%H:%M"),
    )


async def get_running(uid: int) -> bool:
    user = await get_user(uid)
    return bool(user and user["running"])


async def set_running(uid: int, value: bool) -> None:
    await upsert_user(uid, running=int(value))


# ─────────────────────────────────────────────────────────────────────────
# CHATS
# ─────────────────────────────────────────────────────────────────────────
async def get_chats(uid: int) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT chat_id FROM chats WHERE uid=? ORDER BY id", (uid,)
        ) as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]


async def add_chat(uid: int, chat_id: str) -> bool:
    """Chat qo'shadi. Agar allaqachon bo'lsa False qaytaradi."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO chats (uid, chat_id) VALUES (?, ?)", (uid, chat_id)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_chat(uid: int, index: int) -> str | None:
    """Index bo'yicha chatni o'chiradi. O'chirilgan chat_id qaytaradi."""
    chats = await get_chats(uid)
    if 0 <= index < len(chats):
        chat_id = chats[index]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM chats WHERE uid=? AND chat_id=?", (uid, chat_id)
            )
            await db.commit()
        return chat_id
    return None


async def clear_chats(uid: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM chats WHERE uid=?", (uid,))
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────
# POSTS
# ─────────────────────────────────────────────────────────────────────────
async def get_posts(uid: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM posts WHERE uid=? ORDER BY id", (uid,)
        ) as cur:
            rows = await cur.fetchall()
            return [
                {
                    "id": r["id"],
                    "text": r["text_content"],
                    "entities": json.loads(r["entities"]),
                    "photo": r["photo_path"],
                    "link_preview": bool(r["link_preview"]),
                }
                for r in rows
            ]


async def add_post(uid: int, text: str, entities: list, photo_path: str | None) -> int:
    """Post qo'shadi. Post ID qaytaradi."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO posts (uid, text_content, entities, photo_path) VALUES (?, ?, ?, ?)",
            (uid, text, json.dumps(entities, ensure_ascii=False), photo_path),
        )
        await db.commit()
        return cur.lastrowid


async def remove_post(uid: int, index: int) -> dict | None:
    """Index bo'yicha postni o'chiradi."""
    posts = await get_posts(uid)
    if 0 <= index < len(posts):
        post = posts[index]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM posts WHERE id=?", (post["id"],))
            await db.commit()
        return post
    return None


async def clear_posts(uid: int) -> list[dict]:
    """Barcha postlarni o'chiradi. O'chirilgan postlar ro'yxatini qaytaradi."""
    posts = await get_posts(uid)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM posts WHERE uid=?", (uid,))
        await db.commit()
    return posts


# ─────────────────────────────────────────────────────────────────────────
# ALL RUNNING USERS (restart-dan keyin tiklash uchun)
# ─────────────────────────────────────────────────────────────────────────
async def get_all_running() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT uid FROM users WHERE running=1 AND session IS NOT NULL AND is_admin=1"
        ) as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]


# ─────────────────────────────────────────────────────────────────────────
# MIGRATION — JSON'dan SQLite'ga ko'chirish (bir martalik)
# ─────────────────────────────────────────────────────────────────────────
async def migrate_from_json() -> int:
    """Agar eski JSON fayllar mavjud bo'lsa — ularni SQLite'ga import qiladi.
    Import qilingan foydalanuvchilar sonini qaytaradi."""
    import_count = 0
    json_dir = "data"

    # Sessions
    sessions_path = os.path.join(json_dir, "sessions.json")
    if os.path.exists(sessions_path):
        try:
            with open(sessions_path, "r") as f:
                sessions = json.load(f)
            for uid_str, sess in sessions.items():
                uid = int(uid_str)
                await upsert_user(uid, session=sess, is_admin=1)
                import_count += 1
        except Exception:
            pass

    # Pending
    pending_path = os.path.join(json_dir, "pending.json")
    if os.path.exists(pending_path):
        try:
            with open(pending_path, "r") as f:
                pending = json.load(f)
            for uid_str, sess in pending.items():
                await upsert_user(int(uid_str), pending_session=sess)
        except Exception:
            pass

    # Users info
    users_path = os.path.join(json_dir, "users.json")
    if os.path.exists(users_path):
        try:
            with open(users_path, "r") as f:
                users = json.load(f)
            for uid_str, info in users.items():
                await upsert_user(
                    int(uid_str),
                    name=info.get("name", ""),
                    username=info.get("username", ""),
                )
        except Exception:
            pass

    # Intervals
    intervals_path = os.path.join(json_dir, "intervals.json")
    if os.path.exists(intervals_path):
        try:
            with open(intervals_path, "r") as f:
                intervals = json.load(f)
            for uid_str, val in intervals.items():
                await upsert_user(int(uid_str), interval_min=int(val))
        except Exception:
            pass

    # Schedule
    schedule_path = os.path.join(json_dir, "schedule.json")
    if os.path.exists(schedule_path):
        try:
            with open(schedule_path, "r") as f:
                schedules = json.load(f)
            for uid_str, sched in schedules.items():
                await upsert_user(
                    int(uid_str),
                    schedule_start=sched.get("start", "00:00"),
                    schedule_end=sched.get("end", "23:59"),
                )
        except Exception:
            pass

    # Chats
    chats_path = os.path.join(json_dir, "chats.json")
    if os.path.exists(chats_path):
        try:
            with open(chats_path, "r") as f:
                all_chats = json.load(f)
            for uid_str, chat_list in all_chats.items():
                uid = int(uid_str)
                for chat_id in chat_list:
                    await add_chat(uid, chat_id)
        except Exception:
            pass

    # Posts
    posts_path = os.path.join(json_dir, "posts.json")
    if os.path.exists(posts_path):
        try:
            with open(posts_path, "r") as f:
                all_posts = json.load(f)
            for uid_str, post_list in all_posts.items():
                uid = int(uid_str)
                for post in post_list:
                    await add_post(
                        uid,
                        post.get("text", ""),
                        post.get("entities", []),
                        post.get("photo"),
                    )
        except Exception:
            pass

    # Running
    running_path = os.path.join(json_dir, "running.json")
    if os.path.exists(running_path):
        try:
            with open(running_path, "r") as f:
                running = json.load(f)
            for uid_str, val in running.items():
                if val:
                    await upsert_user(int(uid_str), running=1)
        except Exception:
            pass

    return import_count
