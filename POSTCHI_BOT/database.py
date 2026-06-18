"""
database.py — POSTCHI_BOT SQLite storage.

Arxitektura AVTO_BOT dan olingan ishonchli uslub:
- Yagona uzoq yashovchi ulanish (_conn)
- _op_lock barcha operatsiyalarni serial qiladi (tranzaksiya yaxlitligi)
- INSERT OR IGNORE + UPDATE = atomik upsert (race-free)
- WAL mode — concurrent access xavfsiz

Jadvallar:
- regions    — viloyatlar
- groups     — guruhlar (viloyatga biriktirilgan, har biri o'z intervali)
- users      — foydalanuvchilar (ism, telefon, rol, faol e'lon/viloyat)
- ads        — e'lonlar (5 tagacha, kontakt bilan)
- send_log   — yuborish tarixi (statistika uchun)
"""

from __future__ import annotations

import asyncio
import contextlib
import os

import aiosqlite

from config import DB_PATH, DEFAULT_INTERVAL_MIN

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────
# YAGONA ULANISH
# ─────────────────────────────────────────────────────────────────────────
_conn: aiosqlite.Connection | None = None
_init_lock = asyncio.Lock()
_op_lock = asyncio.Lock()


async def _get_conn() -> aiosqlite.Connection:
    """Yagona ulanishni qaytaradi (birinchi chaqiruvda yaratadi)."""
    global _conn
    if _conn is None:
        async with _init_lock:
            if _conn is None:
                c = await aiosqlite.connect(DB_PATH)
                c.row_factory = aiosqlite.Row
                await c.execute("PRAGMA journal_mode=WAL")
                await c.execute("PRAGMA busy_timeout=5000")
                await c.execute("PRAGMA foreign_keys=ON")
                await c.commit()
                _conn = c
    return _conn


async def close_db() -> None:
    """Ulanishni yopish (graceful shutdown)."""
    global _conn
    async with _init_lock:
        if _conn is not None:
            with contextlib.suppress(Exception):
                await _conn.close()
            _conn = None


# ─────────────────────────────────────────────────────────────────────────
# INIT
# ─────────────────────────────────────────────────────────────────────────
async def init_db() -> None:
    db = await _get_conn()
    async with _op_lock:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS regions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute(f"""
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL UNIQUE,
                title TEXT DEFAULT '',
                region_id INTEGER,
                interval_min INTEGER DEFAULT {DEFAULT_INTERVAL_MIN},
                owner_uid INTEGER,
                is_active INTEGER DEFAULT 1,
                is_paused INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                last_sent_at TEXT,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (region_id) REFERENCES regions(id) ON DELETE SET NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                uid INTEGER PRIMARY KEY,
                name TEXT DEFAULT '',
                username TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                is_approved INTEGER DEFAULT 0,
                is_blocked INTEGER DEFAULT 0,
                awaiting_approval INTEGER DEFAULT 0,
                selected_region_id INTEGER,
                active_ad_id INTEGER,
                running INTEGER DEFAULT 0,
                referred_by INTEGER,
                referral_counted INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                text_content TEXT DEFAULT '',
                entities TEXT DEFAULT '[]',
                photo_path TEXT,
                contact TEXT DEFAULT '',
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS send_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ad_id INTEGER,
                uid INTEGER,
                group_id INTEGER,
                region_id INTEGER,
                status TEXT,
                sent_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("CREATE INDEX IF NOT EXISTS idx_groups_region ON groups(region_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_ads_uid ON ads(uid)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sendlog_ad ON send_log(ad_id)")

        await db.commit()


# ─────────────────────────────────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────────────────────────────────
async def get_user(uid: int) -> dict | None:
    db = await _get_conn()
    async with _op_lock:
        async with db.execute("SELECT * FROM users WHERE uid=?", (uid,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def upsert_user(uid: int, **kwargs) -> None:
    """Foydalanuvchini yaratish yoki yangilash — atomik, race-free."""
    db = await _get_conn()
    async with _op_lock:
        await db.execute("INSERT OR IGNORE INTO users (uid) VALUES (?)", (uid,))
        if kwargs:
            sets = ", ".join(f"{k}=?" for k in kwargs.keys())
            vals = list(kwargs.values()) + [uid]
            await db.execute(f"UPDATE users SET {sets} WHERE uid=?", vals)
        await db.commit()


async def delete_user(uid: int) -> None:
    """Foydalanuvchini va e'lonlarini o'chirish."""
    db = await _get_conn()
    async with _op_lock:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute("DELETE FROM ads WHERE uid=?", (uid,))
            await db.execute("DELETE FROM users WHERE uid=?", (uid,))
            await db.commit()
        except Exception:
            with contextlib.suppress(Exception):
                await db.rollback()
            raise


async def set_user_info(uid: int, name: str, username: str) -> None:
    await upsert_user(uid, name=name, username=username)


async def set_phone(uid: int, phone: str) -> None:
    await upsert_user(uid, phone=phone)


async def is_approved(uid: int) -> bool:
    user = await get_user(uid)
    return bool(user and user["is_approved"] and not user["is_blocked"])


async def set_approved(uid: int, value: bool) -> None:
    await upsert_user(uid, is_approved=1 if value else 0, awaiting_approval=0)


async def set_blocked(uid: int, value: bool) -> None:
    await upsert_user(uid, is_blocked=1 if value else 0)


async def is_awaiting_approval(uid: int) -> bool:
    user = await get_user(uid)
    return bool(user and user["awaiting_approval"])


async def set_awaiting_approval(uid: int, value: bool) -> None:
    await upsert_user(uid, awaiting_approval=1 if value else 0)


async def set_selected_region(uid: int, region_id: int | None) -> None:
    await upsert_user(uid, selected_region_id=region_id)


async def set_active_ad(uid: int, ad_id: int | None) -> None:
    await upsert_user(uid, active_ad_id=ad_id)


async def get_running(uid: int) -> bool:
    user = await get_user(uid)
    return bool(user and user["running"])


async def set_running(uid: int, value: bool) -> None:
    await upsert_user(uid, running=1 if value else 0)


async def get_approved_users() -> list[dict]:
    db = await _get_conn()
    async with _op_lock:
        async with db.execute(
            "SELECT * FROM users WHERE is_approved=1 ORDER BY created_at DESC"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_pending_users() -> list[dict]:
    db = await _get_conn()
    async with _op_lock:
        async with db.execute(
            "SELECT * FROM users WHERE awaiting_approval=1 ORDER BY created_at"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_all_running() -> list[int]:
    """Restart-dan keyin tiklash uchun: running=1 va faol e'lon+viloyat bor."""
    db = await _get_conn()
    async with _op_lock:
        async with db.execute(
            "SELECT uid FROM users WHERE running=1 AND is_approved=1 "
            "AND active_ad_id IS NOT NULL AND selected_region_id IS NOT NULL"
        ) as cur:
            return [r[0] for r in await cur.fetchall()]


# ─────────────────────────────────────────────────────────────────────────
# REGIONS (viloyatlar)
# ─────────────────────────────────────────────────────────────────────────
async def add_region(name: str) -> tuple[bool, str]:
    db = await _get_conn()
    async with _op_lock:
        try:
            await db.execute("INSERT INTO regions (name) VALUES (?)", (name,))
            await db.commit()
            return True, "ok"
        except aiosqlite.IntegrityError:
            return False, "duplicate"


async def get_regions() -> list[dict]:
    db = await _get_conn()
    async with _op_lock:
        async with db.execute("SELECT * FROM regions ORDER BY name") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_region(region_id: int) -> dict | None:
    db = await _get_conn()
    async with _op_lock:
        async with db.execute("SELECT * FROM regions WHERE id=?", (region_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def rename_region(region_id: int, new_name: str) -> None:
    db = await _get_conn()
    async with _op_lock:
        await db.execute("UPDATE regions SET name=? WHERE id=?", (new_name, region_id))
        await db.commit()


async def delete_region(region_id: int) -> None:
    """Viloyatni o'chiradi. Guruhlar region_id=NULL bo'ladi (ON DELETE SET NULL)."""
    db = await _get_conn()
    async with _op_lock:
        await db.execute("DELETE FROM regions WHERE id=?", (region_id,))
        await db.commit()


async def count_groups_in_region(region_id: int) -> int:
    db = await _get_conn()
    async with _op_lock:
        async with db.execute(
            "SELECT COUNT(*) FROM groups WHERE region_id=? AND is_active=1", (region_id,)
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


# ─────────────────────────────────────────────────────────────────────────
# GROUPS (guruhlar)
# ─────────────────────────────────────────────────────────────────────────
async def upsert_group(chat_id: int, title: str, owner_uid: int | None) -> None:
    """Bot guruhga admin qilinganda chaqiriladi (atomik upsert)."""
    db = await _get_conn()
    async with _op_lock:
        await db.execute(
            "INSERT OR IGNORE INTO groups (chat_id, title, owner_uid) VALUES (?, ?, ?)",
            (chat_id, title, owner_uid),
        )
        # Mavjud bo'lsa: nom va faollikni yangilaymiz (qayta admin qilingan bo'lishi mumkin)
        await db.execute(
            "UPDATE groups SET title=?, is_active=1, fail_count=0 WHERE chat_id=?",
            (title, chat_id),
        )
        await db.commit()


async def get_group_by_chat(chat_id: int) -> dict | None:
    db = await _get_conn()
    async with _op_lock:
        async with db.execute("SELECT * FROM groups WHERE chat_id=?", (chat_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_group(group_id: int) -> dict | None:
    db = await _get_conn()
    async with _op_lock:
        async with db.execute("SELECT * FROM groups WHERE id=?", (group_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_all_groups() -> list[dict]:
    db = await _get_conn()
    async with _op_lock:
        async with db.execute("SELECT * FROM groups ORDER BY added_at DESC") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_unassigned_groups() -> list[dict]:
    """Bot admin bo'lgan, lekin viloyatga biriktirilmagan guruhlar."""
    db = await _get_conn()
    async with _op_lock:
        async with db.execute(
            "SELECT * FROM groups WHERE region_id IS NULL AND is_active=1 ORDER BY added_at"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_active_groups_in_region(region_id: int) -> list[dict]:
    """Yuborish uchun: viloyatdagi faol, pauzada bo'lmagan guruhlar."""
    db = await _get_conn()
    async with _op_lock:
        async with db.execute(
            "SELECT * FROM groups WHERE region_id=? AND is_active=1 AND is_paused=0",
            (region_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_groups_by_owner(owner_uid: int) -> list[dict]:
    db = await _get_conn()
    async with _op_lock:
        async with db.execute(
            "SELECT * FROM groups WHERE owner_uid=? ORDER BY added_at DESC", (owner_uid,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def assign_group_region(group_id: int, region_id: int, interval_min: int) -> None:
    db = await _get_conn()
    async with _op_lock:
        await db.execute(
            "UPDATE groups SET region_id=?, interval_min=? WHERE id=?",
            (region_id, interval_min, group_id),
        )
        await db.commit()


async def set_group_interval(group_id: int, interval_min: int) -> None:
    db = await _get_conn()
    async with _op_lock:
        await db.execute(
            "UPDATE groups SET interval_min=? WHERE id=?", (interval_min, group_id)
        )
        await db.commit()


async def set_group_active(chat_id: int, value: bool) -> None:
    """Bot admin huquqini yo'qotsa/chiqarilsa — nofaol qilamiz."""
    db = await _get_conn()
    async with _op_lock:
        await db.execute(
            "UPDATE groups SET is_active=? WHERE chat_id=?",
            (1 if value else 0, chat_id),
        )
        await db.commit()


async def set_group_paused(group_id: int, value: bool) -> None:
    """Guruh egasi vaqtincha to'xtatadi/qayta yoqadi."""
    db = await _get_conn()
    async with _op_lock:
        await db.execute(
            "UPDATE groups SET is_paused=? WHERE id=?",
            (1 if value else 0, group_id),
        )
        await db.commit()


async def delete_group(group_id: int) -> None:
    db = await _get_conn()
    async with _op_lock:
        await db.execute("DELETE FROM groups WHERE id=?", (group_id,))
        await db.commit()


async def mark_group_sent(group_id: int) -> None:
    """Muvaffaqiyatli yuborildi — vaqtni yozamiz, fail nollaymiz."""
    db = await _get_conn()
    async with _op_lock:
        await db.execute(
            "UPDATE groups SET last_sent_at=datetime('now'), fail_count=0 WHERE id=?",
            (group_id,),
        )
        await db.commit()


async def incr_group_fail(group_id: int) -> int:
    """Xato hisoblagichini oshiradi, yangi qiymatni qaytaradi."""
    db = await _get_conn()
    async with _op_lock:
        await db.execute(
            "UPDATE groups SET fail_count=fail_count+1 WHERE id=?", (group_id,)
        )
        await db.commit()
        async with db.execute(
            "SELECT fail_count FROM groups WHERE id=?", (group_id,)
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


# ─────────────────────────────────────────────────────────────────────────
# ADS (e'lonlar)
# ─────────────────────────────────────────────────────────────────────────
async def count_ads(uid: int) -> int:
    db = await _get_conn()
    async with _op_lock:
        async with db.execute("SELECT COUNT(*) FROM ads WHERE uid=?", (uid,)) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def add_ad(
    uid: int,
    text: str,
    entities: str,
    photo_path: str | None,
    contact: str,
    max_ads: int,
) -> tuple[bool, str, int | None]:
    """E'lon qo'shadi (atomik limit tekshiruvi bilan)."""
    db = await _get_conn()
    async with _op_lock:
        await db.execute("BEGIN IMMEDIATE")
        try:
            async with db.execute(
                "SELECT COUNT(*) FROM ads WHERE uid=?", (uid,)
            ) as cur:
                row = await cur.fetchone()
                cnt = int(row[0]) if row else 0
            if cnt >= max_ads:
                await db.rollback()
                return False, "limit", None
            cur = await db.execute(
                "INSERT INTO ads (uid, text_content, entities, photo_path, contact) "
                "VALUES (?, ?, ?, ?, ?)",
                (uid, text, entities, photo_path, contact),
            )
            ad_id = cur.lastrowid
            await db.commit()
            return True, "ok", ad_id
        except Exception:
            with contextlib.suppress(Exception):
                await db.rollback()
            raise


async def get_ads(uid: int) -> list[dict]:
    db = await _get_conn()
    async with _op_lock:
        async with db.execute(
            "SELECT * FROM ads WHERE uid=? ORDER BY id", (uid,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_ad(ad_id: int) -> dict | None:
    db = await _get_conn()
    async with _op_lock:
        async with db.execute("SELECT * FROM ads WHERE id=?", (ad_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def update_ad(
    ad_id: int, text: str, entities: str, photo_path: str | None, contact: str
) -> None:
    db = await _get_conn()
    async with _op_lock:
        await db.execute(
            "UPDATE ads SET text_content=?, entities=?, photo_path=?, contact=? WHERE id=?",
            (text, entities, photo_path, contact, ad_id),
        )
        await db.commit()


async def delete_ad(ad_id: int) -> None:
    db = await _get_conn()
    async with _op_lock:
        await db.execute("DELETE FROM ads WHERE id=?", (ad_id,))
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────
# SEND LOG (statistika)
# ─────────────────────────────────────────────────────────────────────────
async def log_send(
    ad_id: int, uid: int, group_id: int, region_id: int, status: str
) -> None:
    db = await _get_conn()
    async with _op_lock:
        await db.execute(
            "INSERT INTO send_log (ad_id, uid, group_id, region_id, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (ad_id, uid, group_id, region_id, status),
        )
        await db.commit()


async def count_sends_today(group_id: int | None = None, uid: int | None = None) -> int:
    """Bugungi muvaffaqiyatli yuborishlar soni (guruh yoki user bo'yicha)."""
    db = await _get_conn()
    async with _op_lock:
        q = "SELECT COUNT(*) FROM send_log WHERE status='ok' AND sent_at >= date('now')"
        params: list = []
        if group_id is not None:
            q += " AND group_id=?"
            params.append(group_id)
        if uid is not None:
            q += " AND uid=?"
            params.append(uid)
        async with db.execute(q, params) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def count_active_users_in_group(group_id: int) -> int:
    """Shu guruhga e'lon bergan noyob foydalanuvchilar soni (bugun)."""
    db = await _get_conn()
    async with _op_lock:
        async with db.execute(
            "SELECT COUNT(DISTINCT uid) FROM send_log "
            "WHERE group_id=? AND status='ok' AND sent_at >= date('now')",
            (group_id,),
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def get_ad_send_stats(ad_id: int) -> dict:
    """E'lon bo'yicha statistika: nechta guruhga ok/xato."""
    db = await _get_conn()
    async with _op_lock:
        async with db.execute(
            "SELECT status, COUNT(*) FROM send_log WHERE ad_id=? GROUP BY status",
            (ad_id,),
        ) as cur:
            rows = await cur.fetchall()
            stats = {"ok": 0, "error": 0}
            for r in rows:
                if r[0] == "ok":
                    stats["ok"] = int(r[1])
                else:
                    stats["error"] += int(r[1])
            return stats


# ─────────────────────────────────────────────────────────────────────────
# REFERAL
# ─────────────────────────────────────────────────────────────────────────
async def set_referrer(uid: int, referrer_uid: int) -> bool:
    if uid == referrer_uid:
        return False
    db = await _get_conn()
    async with _op_lock:
        async with db.execute("SELECT uid FROM users WHERE uid=?", (referrer_uid,)) as cur:
            if await cur.fetchone() is None:
                return False
        await db.execute("INSERT OR IGNORE INTO users (uid) VALUES (?)", (uid,))
        async with db.execute("SELECT referred_by FROM users WHERE uid=?", (uid,)) as cur:
            row = await cur.fetchone()
            if row and row[0] is not None:
                return False
        await db.execute("UPDATE users SET referred_by=? WHERE uid=?", (referrer_uid, uid))
        await db.commit()
        return True


async def try_count_referral(uid: int) -> int | None:
    """Tasdiqlangan user uchun referalni BIR MARTA hisoblaydi."""
    db = await _get_conn()
    async with _op_lock:
        async with db.execute(
            "SELECT referred_by, referral_counted FROM users WHERE uid=?", (uid,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        referrer, counted = row[0], row[1]
        if referrer is None or counted:
            return None
        await db.execute("UPDATE users SET referral_counted=1 WHERE uid=?", (uid,))
        await db.commit()
        return int(referrer)


async def count_referrals(referrer_uid: int) -> int:
    db = await _get_conn()
    async with _op_lock:
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE referred_by=? AND referral_counted=1",
            (referrer_uid,),
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0
