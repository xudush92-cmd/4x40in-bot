"""
db.py — SQLite ma'lumotlar bazasi (aiosqlite).

Jadvallar:
- users       : haydovchilar (ism, familiya, telefon, holat, obuna muddati)
- routes      : yo'nalishlar (qayerdan, qayerga, ochiq/yopiq)
- entries     : haydovchining faol e'loni (bo'sh joylar). Bir haydovchida bitta faol e'lon.
- board       : har bir guruh oynasining xabar bo'laklari (chat_id bo'yicha)
- chat_state  : har bir guruh holati (oxirgi xabar id, oxirgi qayta yuborish vaqti)
- settings    : umumiy sozlamalar (kalit-qiymat)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime

import aiosqlite

from utils import LOCAL_TZ

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id       INTEGER PRIMARY KEY,
    first_name  TEXT NOT NULL DEFAULT '',
    last_name   TEXT NOT NULL DEFAULT '',
    phone       TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'new',      -- new | pending | approved | paused | blocked
    paid_until  INTEGER NOT NULL DEFAULT 0,       -- obuna tugash vaqti (epoch), 0 = yo'q
    warned_for  INTEGER NOT NULL DEFAULT 0,       -- qaysi muddat uchun ogohlantirilgan
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS routes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
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
CREATE TABLE IF NOT EXISTS groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,   -- qo'shilish tartibi uchun
    chat_id     INTEGER NOT NULL UNIQUE,
    title       TEXT NOT NULL DEFAULT '',
    paused      INTEGER NOT NULL DEFAULT 0,           -- 1 = avtomatik yangilanish to'xtatilgan
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "auto_stop_hours": "2",       # avtomatik to'xtash (1..4 soat)
    "repost_after_msgs": "3",     # guruhda shuncha yangi xabar bo'lsa, oyna pastga tushadi
}

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

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


_USER_COLS = "tg_id, first_name, last_name, phone, status, paid_until, warned_for"


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
        await self._conn.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            await self._conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v)
            )
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

    # ── guruhlar (admin botdan qo'shadi/o'chiradi) ─────────────────────
    async def list_groups(self) -> list[dict]:
        rows = await self._all("SELECT chat_id, title, paused FROM groups ORDER BY id")
        return [dict(r) for r in rows]

    async def set_group_paused(self, chat_id: int, paused: bool) -> None:
        await self._exec("UPDATE groups SET paused=? WHERE chat_id=?", (1 if paused else 0, chat_id))

    async def group_ids(self) -> list[int]:
        return [g["chat_id"] for g in await self.list_groups()]

    async def add_group(self, chat_id: int, title: str = "") -> bool:
        """Yangi guruh qo'shadi. Yangi bo'lsa True, allaqachon bo'lsa False."""
        rc = await self._exec(
            "INSERT OR IGNORE INTO groups(chat_id, title, created_at) VALUES (?, ?, ?)",
            (chat_id, title, int(time.time())),
        )
        return rc == 1

    async def remove_group(self, chat_id: int) -> None:
        async with self._lock:
            await self._conn.execute("DELETE FROM groups WHERE chat_id=?", (chat_id,))
            await self._conn.execute("DELETE FROM board WHERE chat_id=?", (chat_id,))
            await self._conn.execute("DELETE FROM chat_state WHERE chat_id=?", (chat_id,))
            await self._conn.commit()

    # ── sozlamalar ─────────────────────────────────────────────────────
    async def get_setting(self, key: str) -> str:
        row = await self._one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else DEFAULT_SETTINGS[key]

    async def set_setting(self, key: str, value: str) -> None:
        await self._exec(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    async def auto_stop_hours(self) -> int:
        return int(await self.get_setting("auto_stop_hours"))

    async def repost_after_msgs(self) -> int:
        return int(await self.get_setting("repost_after_msgs"))

    # ── guruh holati (har bir guruh uchun) ─────────────────────────────
    async def get_chat_value(self, chat_id: int, key: str, default: int = 0) -> int:
        row = await self._one(
            "SELECT value FROM chat_state WHERE chat_id=? AND key=?", (chat_id, key)
        )
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
        allowed = {"first_name", "last_name", "phone", "status", "paid_until", "warned_for"}
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
            f"SELECT {_USER_COLS} FROM users WHERE status=? ORDER BY created_at", (status,)
        )
        return [User(**dict(r)) for r in rows]

    async def count_users_by_status(self) -> dict[str, int]:
        rows = await self._all("SELECT status, COUNT(*) AS c FROM users GROUP BY status")
        return {r["status"]: r["c"] for r in rows}

    async def set_subscription_days(self, tg_id: int, days: int) -> int:
        """
        Obuna muddatini belgilaydi: hozirdan boshlab 'days' kun.
        Eski muddat bekor bo'ladi (qo'shilmaydi).
        """
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

    # ── yo'nalishlar ───────────────────────────────────────────────────
    async def add_route(self, from_place: str, to_place: str) -> int:
        async with self._lock:
            cur = await self._conn.execute(
                "INSERT INTO routes(from_place, to_place, created_at) VALUES (?, ?, ?)",
                (from_place, to_place, int(time.time())),
            )
            await self._conn.commit()
            return cur.lastrowid

    async def list_routes(self) -> list[dict]:
        rows = await self._all(
            "SELECT id, from_place, to_place, is_open FROM routes ORDER BY id"
        )
        return [dict(r) for r in rows]

    async def get_route(self, route_id: int) -> dict | None:
        row = await self._one(
            "SELECT id, from_place, to_place, is_open FROM routes WHERE id=?", (route_id,)
        )
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
            (driver_id, route_id),
        )
        return dict(row) if row else None

    async def get_entry_by_id(self, entry_id: int) -> dict | None:
        row = await self._one(
            "SELECT id, driver_id, route_id, seats, active, updated_at FROM entries WHERE id=?",
            (entry_id,),
        )
        return dict(row) if row else None

    async def start_entry(self, driver_id: int, route_id: int, seats: int) -> tuple[int, list[str]]:
        """
        Haydovchining e'lonini faollashtiradi. Bir haydovchida faqat bitta faol e'lon bo'ladi:
        boshqa yo'nalishdagi faol e'lonlari avtomatik to'xtatiladi.
        Qaytaradi: (entry_id, to'xtatilgan yo'nalishlar nomi ro'yxati).
        """
        now = int(time.time())
        async with self._lock:
            rows = await self._conn.execute(
                "SELECT e.id, r.from_place, r.to_place FROM entries e "
                "JOIN routes r ON r.id = e.route_id "
                "WHERE e.driver_id=? AND e.active=1 AND e.route_id != ?",
                (driver_id, route_id),
            )
            others = await rows.fetchall()
            await rows.close()
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
                "SELECT id FROM entries WHERE driver_id=? AND route_id=?", (driver_id, route_id)
            )
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
            "UPDATE entries SET active=0, updated_at=? WHERE id=?",
            (int(time.time()), entry_id),
        )

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
            "SELECT e.id, e.route_id, e.seats, e.active, r.from_place, r.to_place "
            "FROM entries e JOIN routes r ON r.id = e.route_id "
            "WHERE e.driver_id=? AND e.active=1 ORDER BY e.id",
            (driver_id,),
        )
        return [dict(r) for r in rows]

    async def stale_entries(self, older_than_ts: int) -> list[dict]:
        """Muddati o'tgan faol yozuvlar (haydovchi ma'lumotini yangilamagan)."""
        rows = await self._all(
            "SELECT e.id, e.driver_id, e.route_id, r.from_place, r.to_place "
            "FROM entries e JOIN routes r ON r.id = e.route_id "
            "WHERE e.active=1 AND e.updated_at < ?",
            (older_than_ts,),
        )
        return [dict(r) for r in rows]

    async def board_routes(self, now_ts: int | None = None) -> list[dict]:
        """
        Oynada ko'rinadigan ma'lumot: ochiq yo'nalishlar, har birida faol haydovchilar.
        Faqat tasdiqlangan va obunasi amal qilayotgan haydovchilar chiqadi.
        """
        now_ts = int(time.time()) if now_ts is None else now_ts
        routes = await self._all(
            "SELECT id, from_place, to_place FROM routes WHERE is_open=1 ORDER BY id"
        )
        out = []
        for r in routes:
            rows = await self._all(
                "SELECT u.first_name, u.last_name, u.phone, e.seats "
                "FROM entries e JOIN users u ON u.tg_id = e.driver_id "
                "WHERE e.route_id=? AND e.active=1 AND u.status='approved' AND u.paid_until > ? "
                "ORDER BY e.updated_at",
                (r["id"], now_ts),
            )
            out.append(
                {
                    "from_place": r["from_place"],
                    "to_place": r["to_place"],
                    "entries": [dict(x) for x in rows],
                }
            )
        return out

    async def active_entry_count(self) -> int:
        row = await self._one(
            "SELECT COUNT(*) AS c FROM entries e JOIN users u ON u.tg_id = e.driver_id "
            "WHERE e.active=1 AND u.status='approved' AND u.paid_until > ?",
            (int(time.time()),),
        )
        return row["c"]

    async def block_driver(self, driver_id: int) -> None:
        await self.update_user_fields(driver_id, status="blocked")
        await self.stop_all_for_driver(driver_id)

    # ── guruh oynasi (board) ───────────────────────────────────────────
    async def get_board(self, chat_id: int) -> list[tuple[int, int]]:
        rows = await self._all(
            "SELECT part_idx, message_id FROM board WHERE chat_id=? ORDER BY part_idx",
            (chat_id,),
        )
        return [(r["part_idx"], r["message_id"]) for r in rows]

    async def set_board(self, chat_id: int, message_ids: list[int]) -> None:
        async with self._lock:
            await self._conn.execute("DELETE FROM board WHERE chat_id=?", (chat_id,))
            for i, mid in enumerate(message_ids):
                await self._conn.execute(
                    "INSERT INTO board(chat_id, part_idx, message_id) VALUES (?, ?, ?)",
                    (chat_id, i, mid),
                )
            await self._conn.commit()
