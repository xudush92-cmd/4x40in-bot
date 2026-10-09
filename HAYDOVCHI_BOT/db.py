"""
db.py — SQLite ma'lumotlar bazasi (aiosqlite).

Jadvallar:
- users     : haydovchilar (ism, familiya, telefon, holat)
- routes    : yo'nalishlar (qayerdan, qayerga, ochiq/yopiq)
- entries   : haydovchining faol yo'nalishdagi e'loni (bo'sh joylar)
- board     : guruh oynasining xabar bo'laklari (message_id lar)
- chat_state: guruh holati (oxirgi xabar id, oxirgi qayta yuborish vaqti)
- settings  : sozlamalar (kalit-qiymat)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id       INTEGER PRIMARY KEY,
    first_name  TEXT NOT NULL DEFAULT '',
    last_name   TEXT NOT NULL DEFAULT '',
    phone       TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'new',      -- new | pending | approved | blocked
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
    part_idx    INTEGER PRIMARY KEY,
    message_id  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_state (
    key         TEXT PRIMARY KEY,
    value       INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "auto_stop_hours": "2",      # avtomatik to'xtash (1..4 soat)
    "periodic_minutes": "15",    # vaqt bo'yicha tekshiruv oralig'i
}

# Qat'iy (kod ichida o'zgarmas) vaqt qiymatlari
DEBOUNCE_SEC = 30          # o'zgarishlarni shu vaqt yig'ib bitta yangilanish
REPOST_MIN_SEC = 120       # ikki qayta yuborish orasidagi minimal vaqt


@dataclass
class User:
    tg_id: int
    first_name: str
    last_name: str
    phone: str
    status: str

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


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
    async def _exec(self, sql: str, params: tuple = ()) -> None:
        async with self._lock:
            await self._conn.execute(sql, params)
            await self._conn.commit()

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

    async def periodic_minutes(self) -> int:
        return int(await self.get_setting("periodic_minutes"))

    # ── guruh holati ───────────────────────────────────────────────────
    async def get_chat_value(self, key: str, default: int = 0) -> int:
        row = await self._one("SELECT value FROM chat_state WHERE key=?", (key,))
        return row["value"] if row else default

    async def set_chat_value(self, key: str, value: int) -> None:
        await self._exec(
            "INSERT INTO chat_state(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    # ── foydalanuvchilar (haydovchilar) ────────────────────────────────
    async def get_user(self, tg_id: int) -> User | None:
        row = await self._one(
            "SELECT tg_id, first_name, last_name, phone, status FROM users WHERE tg_id=?",
            (tg_id,),
        )
        if not row:
            return None
        return User(**dict(row))

    async def ensure_user(self, tg_id: int) -> None:
        await self._exec(
            "INSERT OR IGNORE INTO users(tg_id, created_at) VALUES (?, ?)",
            (tg_id, int(time.time())),
        )

    async def update_user_fields(self, tg_id: int, **fields) -> None:
        allowed = {"first_name", "last_name", "phone", "status"}
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
            "SELECT tg_id, first_name, last_name, phone, status FROM users "
            "WHERE status=? ORDER BY created_at",
            (status,),
        )
        return [User(**dict(r)) for r in rows]

    async def count_users_by_status(self) -> dict[str, int]:
        rows = await self._all("SELECT status, COUNT(*) AS c FROM users GROUP BY status")
        return {r["status"]: r["c"] for r in rows}

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

    async def start_entry(self, driver_id: int, route_id: int, seats: int) -> int:
        """Yozuv yaratadi yoki qayta faollashtiradi. Entry id qaytaradi."""
        now = int(time.time())
        await self._exec(
            "INSERT INTO entries(driver_id, route_id, seats, active, updated_at) "
            "VALUES (?, ?, ?, 1, ?) "
            "ON CONFLICT(driver_id, route_id) DO UPDATE SET "
            "seats=excluded.seats, active=1, updated_at=excluded.updated_at",
            (driver_id, route_id, seats, now),
        )
        entry = await self.get_entry(driver_id, route_id)
        return entry["id"]

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
        async with self._lock:
            cur = await self._conn.execute(
                "UPDATE entries SET active=0, updated_at=? WHERE driver_id=? AND active=1",
                (int(time.time()), driver_id),
            )
            await self._conn.commit()
            return cur.rowcount

    async def stop_route_entries(self, route_id: int) -> int:
        """Yo'nalish yopilganda uning barcha faol e'lonlarini to'xtatadi."""
        async with self._lock:
            cur = await self._conn.execute(
                "UPDATE entries SET active=0, updated_at=? WHERE route_id=? AND active=1",
                (int(time.time()), route_id),
            )
            await self._conn.commit()
            return cur.rowcount

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

    async def board_routes(self) -> list[dict]:
        """
        Oynada ko'rinadigan ma'lumot: ochiq yo'nalishlar, har birida faol haydovchilar.
        Faqat tasdiqlangan (approved) haydovchilar chiqadi.
        """
        routes = await self._all(
            "SELECT id, from_place, to_place FROM routes WHERE is_open=1 ORDER BY id"
        )
        out = []
        for r in routes:
            rows = await self._all(
                "SELECT u.first_name, u.last_name, u.phone, e.seats "
                "FROM entries e JOIN users u ON u.tg_id = e.driver_id "
                "WHERE e.route_id=? AND e.active=1 AND u.status='approved' "
                "ORDER BY e.updated_at",
                (r["id"],),
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
            "WHERE e.active=1 AND u.status='approved'"
        )
        return row["c"]

    async def block_driver(self, driver_id: int) -> None:
        await self.update_user_fields(driver_id, status="blocked")
        await self.stop_all_for_driver(driver_id)

    # ── guruh oynasi (board) ───────────────────────────────────────────
    async def get_board(self) -> list[tuple[int, int]]:
        rows = await self._all("SELECT part_idx, message_id FROM board ORDER BY part_idx")
        return [(r["part_idx"], r["message_id"]) for r in rows]

    async def set_board(self, message_ids: list[int]) -> None:
        async with self._lock:
            await self._conn.execute("DELETE FROM board")
            for i, mid in enumerate(message_ids):
                await self._conn.execute(
                    "INSERT INTO board(part_idx, message_id) VALUES (?, ?)", (i, mid)
                )
            await self._conn.commit()
