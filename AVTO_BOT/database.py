"""
database.py — SQLite asosidagi storage.

JSON fayllar o'rniga yagona SQLite bazada barcha ma'lumotlar saqlanadi.
Afzalliklari:
- Concurrent access xavfsiz (WAL mode)
- Corruption riski deyarli yo'q
- 1000+ foydalanuvchi uchun tez ishlaydi
- Backup = bitta fayl nusxalash
- INSERT ON CONFLICT — atomic upsert (race-free)
- Idempotent migration — JSON fayllar .migrated suffix bilan belgilanadi
"""

import aiosqlite
import json
import os
from datetime import time as dtime

DB_PATH = os.path.join("data", "avto_bot.db")
os.makedirs("data", exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────
# INIT
# ─────────────────────────────────────────────────────────────────────────
async def init_db() -> None:
    """Bazani yaratish va jadvallarni sozlash."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("PRAGMA foreign_keys=ON")

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

        # Indekslar — tezroq query
        await db.execute("CREATE INDEX IF NOT EXISTS idx_chats_uid ON chats(uid)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_posts_uid ON posts(uid)")

        await db.commit()


# ─────────────────────────────────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────────────────────────────────
# Default qiymatlar — birinchi marta yaratilganda ishlatiladi
_USER_DEFAULTS = {
    "name": "",
    "username": "",
    "session": None,
    "pending_session": None,
    "is_admin": 0,
    "interval_min": 4,
    "schedule_start": "00:00",
    "schedule_end": "23:59",
    "running": 0,
}


async def get_user(uid: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE uid=?", (uid,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def upsert_user(uid: int, **kwargs) -> None:
    """
    Foydalanuvchini yaratish yoki yangilash — atomic, race-free.

    INSERT OR IGNORE bilan satr borligini ta'minlaymiz, keyin UPDATE
    qilamiz. Hammasi bitta connection ichida.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout=5000")

        # 1) Satr yo'q bo'lsa yaratamiz (default qiymatlar bilan)
        await db.execute(
            "INSERT OR IGNORE INTO users (uid) VALUES (?)", (uid,)
        )

        # 2) Yangilanadigan field bo'lsa — UPDATE
        if kwargs:
            sets = ", ".join(f"{k}=?" for k in kwargs.keys())
            vals = list(kwargs.values()) + [uid]
            await db.execute(f"UPDATE users SET {sets} WHERE uid=?", vals)

        await db.commit()


async def delete_user(uid: int) -> None:
    """Foydalanuvchini va u bilan bog'liq barcha ma'lumotni o'chirish."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("DELETE FROM chats WHERE uid=?", (uid,))
        await db.execute("DELETE FROM posts WHERE uid=?", (uid,))
        await db.execute("DELETE FROM users WHERE uid=?", (uid,))
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────
# Sessions / pending
# ─────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────
# Adminlar
# ─────────────────────────────────────────────────────────────────────────
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
# Interval va schedule
# ─────────────────────────────────────────────────────────────────────────
async def get_interval(uid: int) -> int:
    user = await get_user(uid)
    return user["interval_min"] if user else _USER_DEFAULTS["interval_min"]


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
# CHATS — atomic count + insert (race-safe)
# ─────────────────────────────────────────────────────────────────────────
async def get_chats(uid: int) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT chat_id FROM chats WHERE uid=? ORDER BY id", (uid,)
        ) as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]


async def count_chats(uid: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM chats WHERE uid=?", (uid,)
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def add_chat(uid: int, chat_id: str, max_chats: int | None = None) -> tuple[bool, str]:
    """
    Chat qo'shadi (atomic).

    Returns:
        (True, "ok") — qo'shildi
        (False, "duplicate") — allaqachon mavjud
        (False, "limit") — max_chats limitidan oshib ketdi
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        # Transaction ichida count + insert — atomic
        await db.execute("BEGIN IMMEDIATE")
        try:
            if max_chats is not None:
                async with db.execute(
                    "SELECT COUNT(*) FROM chats WHERE uid=?", (uid,)
                ) as cur:
                    row = await cur.fetchone()
                    cnt = int(row[0]) if row else 0
                if cnt >= max_chats:
                    await db.execute("ROLLBACK")
                    return False, "limit"

            try:
                await db.execute(
                    "INSERT INTO chats (uid, chat_id) VALUES (?, ?)",
                    (uid, chat_id),
                )
                await db.commit()
                return True, "ok"
            except aiosqlite.IntegrityError:
                await db.execute("ROLLBACK")
                return False, "duplicate"
        except Exception:
            try:
                await db.execute("ROLLBACK")
            except Exception:
                pass
            raise


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
# POSTS — atomic count + insert (race-safe)
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


async def count_posts(uid: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM posts WHERE uid=?", (uid,)
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def add_post(
    uid: int,
    text: str,
    entities: list,
    photo_path: str | None,
    max_posts: int | None = None,
) -> tuple[bool, str, int | None]:
    """
    Post qo'shadi (atomic).

    Returns:
        (True, "ok", post_id) — qo'shildi
        (False, "limit", None) — max_posts limitidan oshib ketdi
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("BEGIN IMMEDIATE")
        try:
            if max_posts is not None:
                async with db.execute(
                    "SELECT COUNT(*) FROM posts WHERE uid=?", (uid,)
                ) as cur:
                    row = await cur.fetchone()
                    cnt = int(row[0]) if row else 0
                if cnt >= max_posts:
                    await db.execute("ROLLBACK")
                    return False, "limit", None

            cur = await db.execute(
                "INSERT INTO posts (uid, text_content, entities, photo_path) VALUES (?, ?, ?, ?)",
                (uid, text, json.dumps(entities, ensure_ascii=False), photo_path),
            )
            post_id = cur.lastrowid
            await db.commit()
            return True, "ok", post_id
        except Exception:
            try:
                await db.execute("ROLLBACK")
            except Exception:
                pass
            raise


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
# MIGRATION — JSON'dan SQLite'ga ko'chirish (idempotent)
#
# Har bir muvaffaqiyatli o'qilgan JSON fayl ".migrated" suffix bilan
# rename qilinadi. Shu sababli keyingi restartlarda qayta o'qilmaydi
# va post/chat dublikatlari yaratilmaydi.
# ─────────────────────────────────────────────────────────────────────────
async def migrate_from_json() -> dict:
    """
    Eski JSON fayllarini SQLite'ga ko'chiradi.

    Returns:
        Statistika dict: {"users": N, "chats": N, "posts": N, "files": [...]}
    """
    stats = {"users": 0, "chats": 0, "posts": 0, "files": []}
    json_dir = "data"

    def _path(name: str) -> str:
        return os.path.join(json_dir, name)

    def _is_pending(name: str) -> bool:
        """Fayl bor va hali migratsiya qilinmagan."""
        p = _path(name)
        return os.path.exists(p) and not os.path.exists(p + ".migrated")

    def _mark_migrated(name: str) -> None:
        """Faylga .migrated qo'shamiz (qayta o'qilmasligi uchun)."""
        p = _path(name)
        try:
            os.rename(p, p + ".migrated")
            stats["files"].append(name)
        except OSError:
            pass

    # Sessions
    if _is_pending("sessions.json"):
        try:
            with open(_path("sessions.json"), "r", encoding="utf-8") as f:
                sessions = json.load(f)
            for uid_str, sess in sessions.items():
                await upsert_user(int(uid_str), session=sess, is_admin=1)
                stats["users"] += 1
            _mark_migrated("sessions.json")
        except Exception:
            pass

    # Pending
    if _is_pending("pending.json"):
        try:
            with open(_path("pending.json"), "r", encoding="utf-8") as f:
                pending = json.load(f)
            for uid_str, sess in pending.items():
                await upsert_user(int(uid_str), pending_session=sess)
            _mark_migrated("pending.json")
        except Exception:
            pass

    # Users info
    if _is_pending("users.json"):
        try:
            with open(_path("users.json"), "r", encoding="utf-8") as f:
                users = json.load(f)
            for uid_str, info in users.items():
                await upsert_user(
                    int(uid_str),
                    name=info.get("name", ""),
                    username=info.get("username", ""),
                )
            _mark_migrated("users.json")
        except Exception:
            pass

    # Intervals
    if _is_pending("intervals.json"):
        try:
            with open(_path("intervals.json"), "r", encoding="utf-8") as f:
                intervals = json.load(f)
            for uid_str, val in intervals.items():
                await upsert_user(int(uid_str), interval_min=int(val))
            _mark_migrated("intervals.json")
        except Exception:
            pass

    # Schedule
    if _is_pending("schedule.json"):
        try:
            with open(_path("schedule.json"), "r", encoding="utf-8") as f:
                schedules = json.load(f)
            for uid_str, sched in schedules.items():
                await upsert_user(
                    int(uid_str),
                    schedule_start=sched.get("start", "00:00"),
                    schedule_end=sched.get("end", "23:59"),
                )
            _mark_migrated("schedule.json")
        except Exception:
            pass

    # Chats — UNIQUE(uid, chat_id) tufayli dubl bo'lmaydi
    if _is_pending("chats.json"):
        try:
            with open(_path("chats.json"), "r", encoding="utf-8") as f:
                all_chats = json.load(f)
            for uid_str, chat_list in all_chats.items():
                uid = int(uid_str)
                for chat_id in chat_list:
                    ok, _ = await add_chat(uid, chat_id)
                    if ok:
                        stats["chats"] += 1
            _mark_migrated("chats.json")
        except Exception:
            pass

    # Posts — UNIQUE constraint yo'q, lekin .migrated suffix tufayli
    # qayta import bo'lmaydi
    if _is_pending("posts.json"):
        try:
            with open(_path("posts.json"), "r", encoding="utf-8") as f:
                all_posts = json.load(f)
            for uid_str, post_list in all_posts.items():
                uid = int(uid_str)
                for post in post_list:
                    ok, _, _ = await add_post(
                        uid,
                        post.get("text", ""),
                        post.get("entities", []),
                        post.get("photo"),
                    )
                    if ok:
                        stats["posts"] += 1
            _mark_migrated("posts.json")
        except Exception:
            pass

    # Running
    if _is_pending("running.json"):
        try:
            with open(_path("running.json"), "r", encoding="utf-8") as f:
                running = json.load(f)
            for uid_str, val in running.items():
                if val:
                    await upsert_user(int(uid_str), running=1)
            _mark_migrated("running.json")
        except Exception:
            pass

    return stats
