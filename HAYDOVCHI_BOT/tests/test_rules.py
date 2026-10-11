"""Biznes qoidalari: guruhlar bo'yicha ajratish, e'lonlar, obuna, taksi, migratsiya."""
import asyncio
import sqlite3
import time
from datetime import date, datetime

from db import Database, end_of_day_ts
from utils import LOCAL_TZ, parse_route

DAY = 86400
G1, G2 = -100111, -100222


def run(coro):
    return asyncio.run(coro)


async def _db(tmp_path, name="r.db"):
    db = Database(str(tmp_path / name))
    await db.open()
    return db


async def _driver(db, uid, group=G1, paid_days=30, status="approved"):
    await db.ensure_user(uid)
    paid = int(time.time()) + paid_days * DAY if paid_days else 0
    await db.update_user_fields(uid, first_name=f"F{uid}", last_name="L", phone="+998901234567",
                                status=status, paid_until=paid, group_id=group)


async def _two_groups(db):
    await db.add_group(G1, "Guruh 1")
    await db.add_group(G2, "Guruh 2")


# ── guruhlar bo'yicha ajratish ──────────────────────────────────────────
def test_routes_are_isolated_per_group(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            await _two_groups(db)
            await db.add_route(G1, "A", "B")
            await db.add_route(G2, "C", "D")
            assert [r["from_place"] for r in await db.list_routes(G1)] == ["A"]
            assert [r["from_place"] for r in await db.list_routes(G2)] == ["C"]
        finally:
            await db.close()
    run(go())


def test_board_shows_only_own_group_drivers(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            await _two_groups(db)
            r1 = await db.add_route(G1, "A", "B")
            r2 = await db.add_route(G2, "A", "B")     # bir xil nom, boshqa guruh
            await _driver(db, 1, group=G1)
            await _driver(db, 2, group=G2)
            await db.start_entry(1, r1, 2)
            await db.start_entry(2, r2, 3)
            b1 = await db.board_routes(G1)
            b2 = await db.board_routes(G2)
            assert [e["first_name"] for e in b1[0]["entries"]] == ["F1"]
            assert [e["first_name"] for e in b2[0]["entries"]] == ["F2"]
        finally:
            await db.close()
    run(go())


def test_group_settings_are_separate(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            await _two_groups(db)
            await db.set_group_field(G1, "auto_stop_hours", 4)
            await db.set_group_field(G2, "repost_after_msgs", 10)
            g1, g2 = await db.get_group(G1), await db.get_group(G2)
            assert g1["auto_stop_hours"] == 4 and g1["repost_after_msgs"] == 3
            assert g2["auto_stop_hours"] == 2 and g2["repost_after_msgs"] == 10
        finally:
            await db.close()
    run(go())


def test_auto_stop_uses_group_hours(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            await _two_groups(db)
            await db.set_group_field(G2, "auto_stop_hours", 4)
            r1 = await db.add_route(G1, "A", "B")
            r2 = await db.add_route(G2, "C", "D")
            await _driver(db, 1, group=G1)
            await _driver(db, 2, group=G2)
            e1, _ = await db.start_entry(1, r1, 2)
            e2, _ = await db.start_entry(2, r2, 2)
            old = int(time.time()) - 3 * 3600          # 3 soat oldin yangilangan
            await db._exec("UPDATE entries SET updated_at=?", (old,))
            stale = {e["id"] for e in await db.stale_entries(int(time.time()))}
            assert e1 in stale and e2 not in stale      # G1: 2 soat, G2: 4 soat
        finally:
            await db.close()
    run(go())


def test_remove_group_clears_its_data_and_unassigns_drivers(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            await _two_groups(db)
            r = await db.add_route(G1, "A", "B")
            await _driver(db, 1, group=G1)
            await db.start_entry(1, r, 2)
            await db.set_board(G1, [5, 6])
            await db.remove_group(G1)
            assert await db.group_ids() == [G2]
            assert await db.list_routes(G1) == []
            assert await db.driver_entries(1) == []
            assert await db.get_board(G1) == []
            assert (await db.get_user(1)).group_id is None
        finally:
            await db.close()
    run(go())


def test_first_group_adopts_orphan_routes(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            await db._exec("INSERT INTO routes(group_id, from_place, to_place, created_at) "
                           "VALUES (NULL, 'X', 'Y', 0)")
            await db.add_group(G1, "Guruh 1")
            assert [r["from_place"] for r in await db.list_routes(G1)] == ["X"]
        finally:
            await db.close()
    run(go())


# ── bitta faol e'lon ───────────────────────────────────────────────────
def test_one_active_entry_per_driver(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            await _two_groups(db)
            r1 = await db.add_route(G1, "A", "B")
            r2 = await db.add_route(G1, "C", "D")
            await _driver(db, 1)
            _, replaced1 = await db.start_entry(1, r1, 2)
            assert replaced1 == []
            _, replaced2 = await db.start_entry(1, r2, 3)
            assert replaced2 == ["A → B"]
            active = await db.driver_entries(1)
            assert len(active) == 1 and active[0]["route_id"] == r2
        finally:
            await db.close()
    run(go())


def test_restart_same_route_updates_seats(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            await _two_groups(db)
            r = await db.add_route(G1, "A", "B")
            await _driver(db, 1)
            await db.start_entry(1, r, 2)
            await db.start_entry(1, r, 5)
            e = await db.driver_entries(1)
            assert len(e) == 1 and e[0]["seats"] == 5
        finally:
            await db.close()
    run(go())


def test_expired_subscription_hidden_from_board(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            await _two_groups(db)
            r = await db.add_route(G1, "A", "B")
            await _driver(db, 1, paid_days=30)
            await _driver(db, 2, paid_days=0)                 # obuna belgilanmagan
            await db.start_entry(1, r, 2)
            await db.start_entry(2, r, 3)
            names = [e["first_name"] for e in (await db.board_routes(G1))[0]["entries"]]
            assert names == ["F1"]
        finally:
            await db.close()
    run(go())


def test_set_subscription_days_replaces_old_end(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            await _two_groups(db)
            await _driver(db, 1, paid_days=10)
            until = await db.set_subscription_days(1, 30)
            now = int(time.time())
            assert abs((until - now) - 30 * DAY) < 5          # hozirdan boshlab, eskisi bekor
            assert (await db.get_user(1)).paid_until == until
        finally:
            await db.close()
    run(go())


def test_expiring_warning_once(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            await _two_groups(db)
            await _driver(db, 1, paid_days=2)                 # 3 kundan kam qoldi
            now = int(time.time())
            assert len(await db.subscription_expiring(now)) == 1
            u = await db.get_user(1)
            await db.update_user_fields(1, warned_for=u.paid_until)
            assert await db.subscription_expiring(now) == []  # ikkinchi marta yubormaydi
        finally:
            await db.close()
    run(go())


def test_expired_with_entries_detected(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            await _two_groups(db)
            r = await db.add_route(G1, "A", "B")
            await _driver(db, 1, paid_days=30)
            await db.start_entry(1, r, 2)
            await db.set_subscription_end(1, int(time.time()) - 60)
            assert len(await db.subscription_expired_with_entries(int(time.time()))) == 1
        finally:
            await db.close()
    run(go())


# ── taksi ──────────────────────────────────────────────────────────────
def test_taxi_recipients_need_active_entry_in_same_group(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            await _two_groups(db)
            r1 = await db.add_route(G1, "A", "B")
            r2 = await db.add_route(G2, "C", "D")
            now = int(time.time())
            await _driver(db, 1, group=G1)       # e'loni bor, G1
            await _driver(db, 2, group=G1)       # e'loni yo'q
            await _driver(db, 3, group=G2)       # e'loni bor, lekin G2
            await db.start_entry(1, r1, 2)
            await db.start_entry(3, r2, 2)
            assert await db.taxi_recipients(G1, now) == [1]
            await db.update_user_fields(1, taxi_on=0)          # o'chirib qo'yilgan
            assert await db.taxi_recipients(G1, now) == []
        finally:
            await db.close()
    run(go())


def test_taxi_log_cooldown_data(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            await _two_groups(db)
            assert await db.taxi_last_request(G1, 55) == 0
            await db.add_taxi_log(G1, 55, 1000)
            assert await db.taxi_last_request(G1, 55) == 1000
            assert await db.taxi_last_request(G2, 55) == 0      # boshqa guruh alohida
        finally:
            await db.close()
    run(go())


# ── migratsiya: eski (guruhsiz) baza ───────────────────────────────────
OLD_SCHEMA = """
CREATE TABLE users (tg_id INTEGER PRIMARY KEY, first_name TEXT NOT NULL DEFAULT '',
  last_name TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'new', paid_until INTEGER NOT NULL DEFAULT 0,
  warned_for INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);
CREATE TABLE routes (id INTEGER PRIMARY KEY AUTOINCREMENT, from_place TEXT NOT NULL,
  to_place TEXT NOT NULL, is_open INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL);
CREATE TABLE entries (id INTEGER PRIMARY KEY AUTOINCREMENT,
  driver_id INTEGER NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
  route_id INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
  seats INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
  updated_at INTEGER NOT NULL, UNIQUE (driver_id, route_id));
CREATE TABLE board (chat_id INTEGER NOT NULL, part_idx INTEGER NOT NULL,
  message_id INTEGER NOT NULL, PRIMARY KEY (chat_id, part_idx));
CREATE TABLE chat_state (chat_id INTEGER NOT NULL, key TEXT NOT NULL, value INTEGER NOT NULL,
  PRIMARY KEY (chat_id, key));
CREATE TABLE groups (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL UNIQUE,
  title TEXT NOT NULL DEFAULT '', paused INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO settings VALUES ('auto_stop_hours', '3'), ('repost_after_msgs', '5');
INSERT INTO groups(chat_id, title, created_at) VALUES (-100999, 'Eski guruh', 0);
INSERT INTO routes(from_place, to_place, created_at) VALUES ('A', 'B', 0);
INSERT INTO users(tg_id, first_name, last_name, status, paid_until, created_at)
  VALUES (7, 'Ali', 'V', 'approved', 9999999999, 0);
INSERT INTO entries(driver_id, route_id, seats, active, updated_at) VALUES (7, 1, 2, 1, 0);
"""


def test_migrates_old_database_without_data_loss(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript(OLD_SCHEMA)
    raw.commit()
    raw.close()

    async def go():
        db = Database(str(path))
        await db.open()
        try:
            g = await db.get_group(-100999)
            assert g["auto_stop_hours"] == 3 and g["repost_after_msgs"] == 5   # eski sozlama saqlandi
            assert [r["from_place"] for r in await db.list_routes(-100999)] == ["A"]
            u = await db.get_user(7)
            assert u.group_id == -100999 and u.taxi_on == 1
            assert len(await db.driver_entries(7)) == 1                          # e'lon saqlandi
        finally:
            await db.close()
        # ikkinchi marta ochilganda xato bermasligi kerak (idempotent)
        db = Database(str(path))
        await db.open()
        await db.close()
    run(go())


# ── yo'nalish formati, vaqt, guruh ro'yxati ────────────────────────────
def test_multi_route_parse_separators():
    for s in ["Toshkent - Qibray", "Toshkent / Qibray", "Toshkent | Qibray", "Toshkent → Qibray",
              "Toshkent – Qibray", "Toshkent — Qibray", "Toshkent -> Qibray"]:
        assert parse_route(s) == ("Toshkent", "Qibray"), s


def test_end_of_day_timestamp():
    ts = end_of_day_ts(date(2026, 11, 30))
    assert datetime.fromtimestamp(ts, LOCAL_TZ).date() == date(2026, 11, 30)
    assert datetime.fromtimestamp(ts, LOCAL_TZ).hour == 23


def test_groups_add_list_remove(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            assert await db.add_group(G1, "Haydovchilar 1") is True
            assert await db.add_group(G1, "Haydovchilar 1") is False   # takror qo'shilmaydi
            await db.add_group(G2, "Haydovchilar 2")
            assert await db.group_ids() == [G1, G2]
            await db.set_group_paused(G1, True)
            g = await db.get_group(G1)
            assert g["paused"] == 1
            await db.set_group_paused(G1, False)
            assert (await db.get_group(G1))["paused"] == 0
            await db.remove_group(G1)
            assert await db.group_ids() == [G2]
        finally:
            await db.close()
    run(go())
