"""
db.py — SQLite ma'lumotlar bazasi (aiosqlite).

Tuzilma (jamlanma modeli):
- collections : JAMLANMALAR. Admin nomini beradi va yaratadi. Yo'nalish, haydovchi, e'lon va
                sozlamalar shu darajada. Sozlamalar: pauza, avto-to'xtash, repost, taksi.
- chats       : jamlanmaga kiruvchi Telegram guruhlari (bir jamlanmada bir nechta bo'lishi mumkin).
                Har guruhda o'z oynasi bor.
- users       : haydovchilar. group_id = jamlanma (collections.id), NULL = biriktirilmagan.
- routes      : yo'nalishlar. group_id = jamlanma (collections.id).
- entries     : haydovchining faol e'loni. Bir haydovchida bitta faol e'lon.
- board       : har Telegram guruh oynasining xabar bo'laklari (chat_id bo'yicha)
- chat_state  : har Telegram guruh holati (oxirgi xabar id, repost hisoblagichi)
- taxi_log    : taksi so'rovlari (jamlanma bo'yicha, spamdan himoya)
- settings    : eski versiya qoldig'i (faqat migratsiyada o'qiladi)

Eski (har guruh alohida) bazani ochganda `_migrate_groups()` har bir eski guruhni alohida
jamlanmaga aylantiradi, `chats` ga yozadi, bog'liq yozuvlarni ko'chiradi va eski `groups`
jadvalini `legacy_groups` deb qayta nomlaydi. Shu sababli migratsiya bir marta bajariladi
va qayta ishga tushirilganda takrorlanmaydi. Ma'lumot o'chmaydi.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime

import aiosqlite

from utils import LOCAL_TZ

log = logging.getLogger("haydovchi.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS collections (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    paused            INTEGER NOT NULL DEFAULT 0,          -- 1 = avtomatik yangilanish to'xtatilgan
    auto_stop_hours   INTEGER NOT NULL DEFAULT 2,          -- avto-to'xtash (1..4 soat)
    repost_after_msgs INTEGER NOT NULL DEFAULT 3,          -- shuncha yangi xabardan keyin pastga tushadi
    taxi_enabled      INTEGER NOT NULL DEFAULT 1,          -- oyna ostida "Taksi chaqirish" tugmasi
    created_at        INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chats (
    chat_id        INTEGER PRIMARY KEY,                    -- Telegram guruh ID (manfiy)
    title          TEXT NOT NULL DEFAULT '',
    collection_id  INTEGER NOT NULL,
    created_at     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    tg_id       INTEGER PRIMARY KEY,
    first_name  TEXT NOT NULL DEFAULT '',
    last_name   TEXT NOT NULL DEFAULT '',
    phone       TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'new',      -- new | pending | approved | paused | blocked
    paid_until  INTEGER NOT NULL DEFAULT 0,       -- obuna tugash vaqti (epoch), 0 = yo'q
    warned_for  INTEGER NOT NULL DEFAULT 0,       -- qaysi muddat uchun ogohlantirilgan
    group_id    INTEGER,                          -- jamlanma (collections.id), NULL = yo'q
    taxi_on     INTEGER NOT NULL DEFAULT 1,       -- taksi so'rovlarini olsinmi
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS routes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    INTEGER,                          -- jamlanma (collections.id)
    from_place  TEXT NOT NULL,
    to_place    TEXT NOT NULL,
    is_open     INTEGER NOT NULL DEFAULT 1,
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id   INTEGER NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    route_id    INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    seats       INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1,
    updated_at  INTEGER NOT NULL,
    UNIQUE (driver_id, route_id)
);
CREATE TABLE IF NOT EXISTS board (
    chat_id     INTEGER NOT NULL,
    part_idx    INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    PRIMARY KEY (chat_id, part_idx)
);
CREATE TABLE IF NOT EXISTS chat_state (
    chat_id     INTEGER NOT NULL,
    key         TEXT NOT NULL,
    value       INTEGER NOT NULL,
    PRIMARY KEY (chat_id, key)
);
CREATE TABLE IF NOT EXISTS taxi_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id     INTEGER NOT NULL,                     -- jamlanma (collections.id)
    passenger_id INTEGER NOT NULL,
    created_at   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);
"""

COLLECTION_FIELDS = {"name", "paused", "auto_stop_hours", "repost_after_msgs", "taxi_enabled"}

WARN_BEFORE_SEC = 3 * 86400  # obuna tugashidan necha kun oldin ogohlantirish


def end_of_day_ts(d) -> int:
    """Sana (date) ning kun oxiri (Toshkent vaqti) epoch ko'rinishida."""
    dt = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=LOCAL_TZ)
    return int(dt.timestamp())


def ts_to_date_str(ts: int) -> str:
    return datetime.fromtimestamp(ts, LOCAL_TZ).strftime("%Y-%m-%d")


@dataclass
class User:
    tg_id: int
    first_name: str
    last_name: str
    phone: str
    status: str
    paid_until: int = 0
    warned_for: int = 0
    group_id: int | None = None
    taxi_on: int = 1

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


_USER_COLS = ("tg_id, first_name, last_name, phone, status, paid_until, warned_for, "
              "group_id, taxi_on")
_COLL_COLS = "id, name, paused, auto_stop_hours, repost_after_msgs, taxi_enabled"


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._legacy_patch()             # eski jadvallarga yetishmayotgan ustunlar
        await self._conn.executescript(SCHEMA)  # yangi jadvallar (mavjudlari o'zgarmaydi)
        await self._migrate_groups()           # eski "groups" -> jamlanma + chatlar
        # jamlanmasiz (eski guruhsiz baza) yo'nalishlardagi e'lonlar ochilmaydi; yo'nalishlar saqlanadi
        await self._conn.execute(
            "UPDATE entries SET active=0 WHERE active=1 AND route_id IN "
            "(SELECT id FROM routes WHERE group_id IS NULL)"
        )
        await self._conn.execute("CREATE INDEX IF NOT EXISTS idx_routes_group ON routes(group_id)")
        await self._conn.execute("CREATE INDEX IF NOT EXISTS idx_users_group ON users(group_id)")
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_taxi_group ON taxi_log(group_id, passenger_id)")
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    # ── yordamchi ──────────────────────────────────────────────────────
    async def _exec(self, sql: str, params: tuple = ()) -> int:
        async with self._lock:
            cur = await self._conn.execute(sql, params)
            await self._conn.commit()
            return cur.rowcount

    async def _one(self, sql: str, params: tuple = ()):
        async with self._lock:
            cur = await self._conn.execute(sql, params)
            row = await cur.fetchone()
            await cur.close()
            return row

    async def _all(self, sql: str, params: tuple = ()):
        async with self._lock:
            cur = await self._conn.execute(sql, params)
            rows = await cur.fetchall()
            await cur.close()
            return rows

    async def _columns(self, table: str) -> set[str]:
        rows = await self._all(f"PRAGMA table_info({table})")
        return {r["name"] for r in rows}

    async def _table_exists(self, table: str) -> bool:
        row = await self._one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        return row is not None

    # ── migratsiya ─────────────────────────────────────────────────────
    async def _legacy_patch(self) -> None:
        """Eski jadvallarga yetishmayotgan ustunlarni qo'shadi (yangi jadvallarni yaratmaydi)."""
        c = self._conn
        if await self._table_exists("groups"):
            gcols = await self._columns("groups")
            added = []
            for col, ddl in [
                ("auto_stop_hours", "INTEGER NOT NULL DEFAULT 2"),
                ("repost_after_msgs", "INTEGER NOT NULL DEFAULT 3"),
                ("taxi_enabled", "INTEGER NOT NULL DEFAULT 1"),
            ]:
                if col not in gcols:
                    await c.execute(f"ALTER TABLE groups ADD COLUMN {col} {ddl}")
                    added.append(col)
            if added and await self._table_exists("settings"):
                cur = await c.execute("SELECT key, value FROM settings")
                old = {r["key"]: r["value"] for r in await cur.fetchall()}
                await cur.close()
                for col in added:
                    if col in old:
                        await c.execute(f"UPDATE groups SET {col}=?", (int(old[col]),))
            await c.commit()

        if await self._table_exists("routes"):
            if "group_id" not in await self._columns("routes"):
                await c.execute("ALTER TABLE routes ADD COLUMN group_id INTEGER")
        if await self._table_exists("users"):
            ucols = await self._columns("users")
            if "group_id" not in ucols:
                await c.execute("ALTER TABLE users ADD COLUMN group_id INTEGER")
            if "taxi_on" not in ucols:
                await c.execute("ALTER TABLE users ADD COLUMN taxi_on INTEGER NOT NULL DEFAULT 1")
        await c.commit()

    async def _migrate_groups(self) -> None:
        """Eski 'groups' jadvalidagi har bir guruhni alohida jamlanmaga aylantiradi (bir marta)."""
        if not await self._table_exists("groups"):
            return
        c = self._conn
        async with self._lock:
            try:
                # 1) har guruh -> jamlanma (id saqlanadi)
                await c.execute(
                    "INSERT INTO collections(id, name, paused, auto_stop_hours, repost_after_msgs, "
                    "taxi_enabled, created_at) "
                    "SELECT id, CASE WHEN TRIM(title)='' THEN 'Jamlanma ' || id ELSE title END, "
                    "paused, auto_stop_hours, repost_after_msgs, taxi_enabled, created_at "
                    "FROM groups WHERE id NOT IN (SELECT id FROM collections)"
                )
                # 2) har guruh -> Telegram chat
                await c.execute(
                    "INSERT INTO chats(chat_id, title, collection_id, created_at) "
                    "SELECT chat_id, title, id, created_at FROM groups "
                    "WHERE chat_id NOT IN (SELECT chat_id FROM chats)"
                )
                # 3) biriktirilmagan yo'nalishlar birinchi guruhga (eski xulq)
                await c.execute(
                    "UPDATE routes SET group_id = (SELECT chat_id FROM groups ORDER BY id LIMIT 1) "
                    "WHERE group_id IS NULL"
                )
                # 4) bog'liq yozuvlar: chat_id -> jamlanma id
                for table in ("routes", "users", "taxi_log"):
                    await c.execute(
                        f"UPDATE {table} SET group_id = (SELECT g.id FROM groups g "
                        f"WHERE g.chat_id = {table}.group_id) "
                        f"WHERE group_id IN (SELECT chat_id FROM groups)"
                    )
                # 5) eski jadval qayta nomlanadi — migratsiya qayta ishlamaydi
                await c.execute("ALTER TABLE groups RENAME TO legacy_groups")
                await c.commit()
                log.info("Eski guruhlar jamlanmaga ko'chirildi.")
            except Exception:
                await c.rollback()
                raise

    # ── jamlanmalar (collections) ──────────────────────────────────────
    async def list_collections(self) -> list[dict]:
        rows = await self._all(
            f"SELECT {_COLL_COLS}, (SELECT COUNT(*) FROM chats h WHERE h.collection_id=c.id) "
            "AS chat_count FROM collections c ORDER BY c.id"
        )
        return [dict(r) for r in rows]

    async def get_collection(self, cid: int) -> dict | None:
        row = await self._one(
            f"SELECT {_COLL_COLS}, (SELECT COUNT(*) FROM chats h WHERE h.collection_id=c.id) "
            "AS chat_count FROM collections c WHERE id=?",
            (cid,),
        )
        return dict(row) if row else None

    async def add_collection(self, name: str) -> int:
        async with self._lock:
            cur = await self._conn.execute(
                "INSERT INTO collections(name, created_at) VALUES (?, ?)", (name, int(time.time()))
            )
            await self._conn.commit()
            return cur.lastrowid

    async def set_collection_field(self, cid: int, field: str, value) -> None:
        if field not in COLLECTION_FIELDS:
            raise ValueError(f"Noma'lum jamlanma maydoni: {field}")
        await self._exec(f"UPDATE collections SET {field}=? WHERE id=?", (value, cid))

    async def delete_collection(self, cid: int) -> list[int]:
        """
        Jamlanmani o'chiradi: guruhlari bog'lanishi, yo'nalishlari, e'lonlari, taksi yozuvlari.
        Haydovchilar jamlanmasiz qoladi. Qaytaradi: o'chirilgan guruhlarning chat_id lari.
        """
        async with self._lock:
            c = self._conn
            rows = await (await c.execute(
                "SELECT chat_id FROM chats WHERE collection_id=?", (cid,))).fetchall()
            chat_ids = [r["chat_id"] for r in rows]
            await c.execute("UPDATE entries SET active=0 WHERE route_id IN "
                            "(SELECT id FROM routes WHERE group_id=?)", (cid,))
            await c.execute("DELETE FROM routes WHERE group_id=?", (cid,))
            await c.execute("UPDATE users SET group_id=NULL WHERE group_id=?", (cid,))
            await c.execute("DELETE FROM taxi_log WHERE group_id=?", (cid,))
            for chat_id in chat_ids:
                await c.execute("DELETE FROM board WHERE chat_id=?", (chat_id,))
                await c.execute("DELETE FROM chat_state WHERE chat_id=?", (chat_id,))
            await c.execute("DELETE FROM chats WHERE collection_id=?", (cid,))
            await c.execute("DELETE FROM collections WHERE id=?", (cid,))
            await c.commit()
            return chat_ids

    # ── Telegram guruhlari (chats) ─────────────────────────────────────
    async def list_chats(self, cid: int) -> list[dict]:
        rows = await self._all(
            "SELECT chat_id, title, collection_id FROM chats WHERE collection_id=? "
            "ORDER BY created_at, chat_id", (cid,))
        return [dict(r) for r in rows]

    async def all_chat_ids(self) -> list[int]:
        rows = await self._all("SELECT chat_id FROM chats ORDER BY created_at, chat_id")
        return [r["chat_id"] for r in rows]

    async def get_chat(self, chat_id: int) -> dict | None:
        row = await self._one(
            "SELECT chat_id, title, collection_id FROM chats WHERE chat_id=?", (chat_id,))
        return dict(row) if row else None

    async def get_chat_ctx(self, chat_id: int) -> dict | None:
        """Guruh + uning jamlanmasi sozlamalari birga (oyna va taksi uchun)."""
        row = await self._one(
            "SELECT h.chat_id, h.title, h.collection_id, c.name, c.paused, c.auto_stop_hours, "
            "c.repost_after_msgs, c.taxi_enabled FROM chats h "
            "JOIN collections c ON c.id = h.collection_id WHERE h.chat_id=?",
            (chat_id,),
        )
        return dict(row) if row else None

    async def add_chat(self, chat_id: int, title: str, cid: int) -> bool:
        """Guruhni jamlanmaga qo'shadi. Yangi bo'lsa True; allaqachon bo'lsa False."""
        rc = await self._exec(
            "INSERT OR IGNORE INTO chats(chat_id, title, collection_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, title, cid, int(time.time())),
        )
        return rc == 1

    async def move_chat(self, chat_id: int, cid: int) -> None:
        await self._exec("UPDATE chats SET collection_id=? WHERE chat_id=?", (cid, chat_id))

    async def remove_chat(self, chat_id: int) -> None:
        async with self._lock:
            c = self._conn
            await c.execute("DELETE FROM chats WHERE chat_id=?", (chat_id,))
            await c.execute("DELETE FROM board WHERE chat_id=?", (chat_id,))
            await c.execute("DELETE FROM chat_state WHERE chat_id=?", (chat_id,))
            await c.commit()

    # ── guruh holati (chat_state) ──────────────────────────────────────
    async def get_chat_value(self, chat_id: int, key: str, default: int = 0) -> int:
        row = await self._one(
            "SELECT value FROM chat_state WHERE chat_id=? AND key=?", (chat_id, key))
        return row["value"] if row else default

    async def set_chat_value(self, chat_id: int, key: str, value: int) -> None:
        await self._exec(
            "INSERT INTO chat_state(chat_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(chat_id, key) DO UPDATE SET value=excluded.value",
            (chat_id, key, value),
        )

    # ── foydalanuvchilar (haydovchilar) ────────────────────────────────
    async def get_user(self, tg_id: int) -> User | None:
        row = await self._one(f"SELECT {_USER_COLS} FROM users WHERE tg_id=?", (tg_id,))
        return User(**dict(row)) if row else None

    async def ensure_user(self, tg_id: int) -> None:
        await self._exec(
            "INSERT OR IGNORE INTO users(tg_id, created_at) VALUES (?, ?)",
            (tg_id, int(time.time())),
        )

    async def update_user_fields(self, tg_id: int, **fields) -> None:
        allowed = {"first_name", "last_name", "phone", "status", "paid_until", "warned_for",
                   "group_id", "taxi_on"}
        cols = [k for k in fields if k in allowed]
        if not cols:
            return
        sets = ", ".join(f"{c}=?" for c in cols)
        await self._exec(
            f"UPDATE users SET {sets} WHERE tg_id=?",
            tuple(fields[c] for c in cols) + (tg_id,),
        )

    async def users_by_status(self, status: str) -> list[User]:
        rows = await self._all(
            f"SELECT {_USER_COLS} FROM users WHERE status=? ORDER BY created_at", (status,))
        return [User(**dict(r)) for r in rows]

    async def collection_drivers(self, cid: int) -> list[User]:
        """Jamlanmaga biriktirilgan haydovchilar (tasdiqlangan, to'xtatilgan, bloklangan)."""
        rows = await self._all(
            f"SELECT {_USER_COLS} FROM users WHERE group_id=? AND status IN "
            "('approved','paused','blocked') ORDER BY created_at",
            (cid,),
        )
        return [User(**dict(r)) for r in rows]

    async def count_users_by_status(self) -> dict[str, int]:
        rows = await self._all("SELECT status, COUNT(*) AS c FROM users GROUP BY status")
        return {r["status"]: r["c"] for r in rows}

    async def set_subscription_days(self, tg_id: int, days: int) -> int:
        """Obuna muddatini belgilaydi: hozirdan boshlab 'days' kun. Eski muddat bekor bo'ladi."""
        new_until = int(time.time()) + days * 86400
        await self.update_user_fields(tg_id, paid_until=new_until, warned_for=0)
        return new_until

    async def set_subscription_end(self, tg_id: int, ts: int) -> None:
        await self.update_user_fields(tg_id, paid_until=ts)

    async def subscription_expiring(self, now_ts: int) -> list[User]:
        """Obunasi tugashiga 3 kundan kam qolgan, hali ogohlantirilmagan haydovchilar."""
        rows = await self._all(
            f"SELECT {_USER_COLS} FROM users WHERE status='approved' "
            "AND paid_until > ? AND paid_until <= ? AND warned_for != paid_until",
            (now_ts, now_ts + WARN_BEFORE_SEC),
        )
        return [User(**dict(r)) for r in rows]

    async def subscription_expired_with_entries(self, now_ts: int) -> list[dict]:
        """Obunasi tugagan, lekin hali faol e'loni bor haydovchilar."""
        rows = await self._all(
            "SELECT e.id, e.driver_id, r.from_place, r.to_place FROM entries e "
            "JOIN users u ON u.tg_id = e.driver_id JOIN routes r ON r.id = e.route_id "
            "WHERE e.active=1 AND u.paid_until > 0 AND u.paid_until < ?",
            (now_ts,),
        )
        return [dict(r) for r in rows]

    async def block_driver(self, driver_id: int) -> None:
        await self.update_user_fields(driver_id, status="blocked")
        await self.stop_all_for_driver(driver_id)

    async def change_driver_collection(self, driver_id: int, cid: int | None) -> None:
        """Haydovchini boshqa jamlanmaga o'tkazadi. Eski e'loni to'xtaydi."""
        await self.stop_all_for_driver(driver_id)
        await self.update_user_fields(driver_id, group_id=cid)

    # ── yo'nalishlar (jamlanma bo'yicha) ───────────────────────────────
    async def add_route(self, cid: int, from_place: str, to_place: str) -> int:
        async with self._lock:
            cur = await self._conn.execute(
                "INSERT INTO routes(group_id, from_place, to_place, created_at) VALUES (?, ?, ?, ?)",
                (cid, from_place, to_place, int(time.time())),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def list_routes(self, cid: int) -> list[dict]:
        rows = await self._all(
            "SELECT id, group_id, from_place, to_place, is_open FROM routes "
            "WHERE group_id=? ORDER BY id", (cid,))
        return [dict(r) for r in rows]

    async def get_route(self, route_id: int) -> dict | None:
        row = await self._one(
            "SELECT id, group_id, from_place, to_place, is_open FROM routes WHERE id=?",
            (route_id,))
        return dict(row) if row else None

    async def set_route_open(self, route_id: int, is_open: bool) -> None:
        await self._exec("UPDATE routes SET is_open=? WHERE id=?", (1 if is_open else 0, route_id))

    async def delete_route(self, route_id: int) -> None:
        await self._exec("DELETE FROM routes WHERE id=?", (route_id,))

    # ── haydovchi e'lonlari (entries) ──────────────────────────────────
    async def get_entry(self, driver_id: int, route_id: int) -> dict | None:
        row = await self._one(
            "SELECT id, driver_id, route_id, seats, active, updated_at FROM entries "
            "WHERE driver_id=? AND route_id=?",
            (driver_id, route_id))
        return dict(row) if row else None

    async def get_entry_by_id(self, entry_id: int) -> dict | None:
        row = await self._one(
            "SELECT id, driver_id, route_id, seats, active, updated_at FROM entries WHERE id=?",
            (entry_id,))
        return dict(row) if row else None

    async def start_entry(self, driver_id: int, route_id: int, seats: int) -> tuple[int, list[str]]:
        """
        Haydovchining e'lonini faollashtiradi. Bir haydovchida faqat bitta faol e'lon bo'ladi:
        boshqa yo'nalishdagi faol e'lonlari avtomatik to'xtatiladi.
        Qaytaradi: (entry_id, to'xtatilgan yo'nalishlar nomlari).
        """
        now = int(time.time())
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT r.from_place, r.to_place FROM entries e "
                "JOIN routes r ON r.id = e.route_id "
                "WHERE e.driver_id=? AND e.active=1 AND e.route_id != ?",
                (driver_id, route_id),
            )
            others = await cur.fetchall()
            await cur.close()
            replaced = [f"{r['from_place']} → {r['to_place']}" for r in others]
            await self._conn.execute(
                "UPDATE entries SET active=0, updated_at=? WHERE driver_id=? AND active=1 "
                "AND route_id != ?",
                (now, driver_id, route_id),
            )
            await self._conn.execute(
                "INSERT INTO entries(driver_id, route_id, seats, active, updated_at) "
                "VALUES (?, ?, ?, 1, ?) "
                "ON CONFLICT(driver_id, route_id) DO UPDATE SET "
                "seats=excluded.seats, active=1, updated_at=excluded.updated_at",
                (driver_id, route_id, seats, now),
            )
            await self._conn.commit()
            cur = await self._conn.execute(
                "SELECT id FROM entries WHERE driver_id=? AND route_id=?", (driver_id, route_id))
            entry_id = (await cur.fetchone())["id"]
            await cur.close()
        return entry_id, replaced

    async def set_entry_seats(self, entry_id: int, seats: int) -> None:
        await self._exec(
            "UPDATE entries SET seats=?, updated_at=? WHERE id=?",
            (seats, int(time.time()), entry_id),
        )

    async def stop_entry(self, entry_id: int) -> None:
        await self._exec(
            "UPDATE entries SET active=0, updated_at=? WHERE id=?", (int(time.time()), entry_id))

    async def stop_all_for_driver(self, driver_id: int) -> int:
        return await self._exec(
            "UPDATE entries SET active=0, updated_at=? WHERE driver_id=? AND active=1",
            (int(time.time()), driver_id),
        )

    async def stop_route_entries(self, route_id: int) -> int:
        """Yo'nalish yopilganda uning barcha faol e'lonlarini to'xtatadi."""
        return await self._exec(
            "UPDATE entries SET active=0, updated_at=? WHERE route_id=? AND active=1",
            (int(time.time()), route_id),
        )

    async def driver_entries(self, driver_id: int) -> list[dict]:
        rows = await self._all(
            "SELECT e.id, e.route_id, e.seats, e.active, r.group_id, r.from_place, r.to_place "
            "FROM entries e JOIN routes r ON r.id = e.route_id "
            "WHERE e.driver_id=? AND e.active=1 ORDER BY e.id",
            (driver_id,),
        )
        return [dict(r) for r in rows]

    async def collection_active_entries(self, cid: int) -> list[dict]:
        rows = await self._all(
            "SELECT e.id, e.driver_id, e.seats, u.first_name, u.last_name, u.phone, "
            "r.from_place, r.to_place FROM entries e "
            "JOIN routes r ON r.id = e.route_id JOIN users u ON u.tg_id = e.driver_id "
            "WHERE r.group_id=? AND e.active=1 ORDER BY e.updated_at",
            (cid,),
        )
        return [dict(r) for r in rows]

    async def stale_entries(self, now_ts: int) -> list[dict]:
        """Har jamlanmaning o'z avto-to'xtash vaqti bo'yicha muddati o'tgan faol e'lonlar."""
        rows = await self._all(
            "SELECT e.id, e.driver_id, e.route_id, r.group_id, r.from_place, r.to_place "
            "FROM entries e JOIN routes r ON r.id = e.route_id "
            "JOIN collections c ON c.id = r.group_id "
            "WHERE e.active=1 AND e.updated_at < ? - c.auto_stop_hours * 3600",
            (now_ts,),
        )
        return [dict(r) for r in rows]

    async def board_routes(self, cid: int, now_ts: int | None = None) -> list[dict]:
        """
        Oynada ko'rinadigan ma'lumot: jamlanmaning ochiq yo'nalishlari, har birida faol haydovchilar.
        Faqat shu jamlanmaga biriktirilgan, tasdiqlangan, obunasi amal qilayotgan haydovchilar.
        """
        now_ts = int(time.time()) if now_ts is None else now_ts
        routes = await self._all(
            "SELECT id, from_place, to_place FROM routes WHERE group_id=? AND is_open=1 ORDER BY id",
            (cid,),
        )
        out = []
        for r in routes:
            rows = await self._all(
                "SELECT u.first_name, u.last_name, u.phone, e.seats "
                "FROM entries e JOIN users u ON u.tg_id = e.driver_id "
                "WHERE e.route_id=? AND e.active=1 AND u.status='approved' AND u.paid_until > ? "
                "AND u.group_id=? ORDER BY e.updated_at",
                (r["id"], now_ts, cid),
            )
            out.append({
                "from_place": r["from_place"],
                "to_place": r["to_place"],
                "entries": [dict(x) for x in rows],
            })
        return out

    async def active_entry_count(self, cid: int | None = None) -> int:
        now = int(time.time())
        if cid is None:
            row = await self._one(
                "SELECT COUNT(*) AS c FROM entries e JOIN users u ON u.tg_id = e.driver_id "
                "WHERE e.active=1 AND u.status='approved' AND u.paid_until > ?", (now,))
        else:
            row = await self._one(
                "SELECT COUNT(*) AS c FROM entries e JOIN users u ON u.tg_id = e.driver_id "
                "JOIN routes r ON r.id = e.route_id "
                "WHERE e.active=1 AND u.status='approved' AND u.paid_until > ? AND r.group_id=?",
                (now, cid))
        return row["c"]

    # ── taksi so'rovlari (jamlanma bo'yicha) ───────────────────────────
    async def taxi_recipients(self, cid: int, now_ts: int) -> list[int]:
        """Jamlanmada hozir faol e'loni bor, taksi yoqqan, obunasi amal qilayotgan haydovchilar."""
        rows = await self._all(
            "SELECT DISTINCT u.tg_id FROM users u "
            "JOIN entries e ON e.driver_id = u.tg_id AND e.active=1 "
            "JOIN routes r ON r.id = e.route_id AND r.group_id = ? "
            "WHERE u.status='approved' AND u.taxi_on=1 AND u.paid_until > ? AND u.group_id=?",
            (cid, now_ts, cid),
        )
        return [r["tg_id"] for r in rows]

    async def taxi_last_request(self, cid: int, passenger_id: int) -> int:
        row = await self._one(
            "SELECT MAX(created_at) AS t FROM taxi_log WHERE group_id=? AND passenger_id=?",
            (cid, passenger_id))
        return row["t"] or 0

    async def add_taxi_log(self, cid: int, passenger_id: int, now_ts: int) -> None:
        await self._exec(
            "INSERT INTO taxi_log(group_id, passenger_id, created_at) VALUES (?, ?, ?)",
            (cid, passenger_id, now_ts))

    async def taxi_requests_count(self, cid: int | None = None) -> int:
        if cid is None:
            row = await self._one("SELECT COUNT(*) AS c FROM taxi_log")
        else:
            row = await self._one("SELECT COUNT(*) AS c FROM taxi_log WHERE group_id=?", (cid,))
        return row["c"]

    # ── oyna (board) ───────────────────────────────────────────────────
    async def get_board(self, chat_id: int) -> list[tuple[int, int]]:
        rows = await self._all(
            "SELECT part_idx, message_id FROM board WHERE chat_id=? ORDER BY part_idx", (chat_id,))
        return [(r["part_idx"], r["message_id"]) for r in rows]

    async def set_board(self, chat_id: int, message_ids: list[int]) -> None:
        async with self._lock:
            await self._conn.execute("DELETE FROM board WHERE chat_id=?", (chat_id,))
            for i, mid in enumerate(message_ids):
                await self._conn.execute(
                    "INSERT INTO board(chat_id, part_idx, message_id) VALUES (?, ?, ?)",
                    (chat_id, i, mid))
            await self._conn.commit()
