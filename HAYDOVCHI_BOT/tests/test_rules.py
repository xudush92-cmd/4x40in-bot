"""Biznes qoidalari: jamlanmalar, guruhlar, e'lonlar, obuna, taksi, migratsiya."""
import asyncio
import sqlite3
import time
from datetime import date, datetime

from db import Database, end_of_day_ts
from utils import LOCAL_TZ, parse_route

DAY = 86400
G1, G2, G3 = -100111, -100222, -100333


def run(coro):
    return asyncio.run(coro)


async def _db(tmp_path, name="r.db"):
    db = Database(str(tmp_path / name))
    await db.open()
    return db


async def _driver(db, uid, cid, paid_days=30, status="approved"):
    await db.ensure_user(uid)
    paid = int(time.time()) + paid_days * DAY if paid_days else 0
    await db.update_user_fields(uid, first_name=f"F{uid}", last_name="L", phone="+998901234567",
                                status=status, paid_until=paid, group_id=cid)


async def _two_collections(db):
    """J1: G1 guruhi; J2: G2 guruhi. Qaytaradi: (c1, c2)."""
    c1 = await db.add_collection("Jamlanma 1")
    c2 = await db.add_collection("Jamlanma 2")
    await db.add_chat(G1, "Guruh 1", c1)
    await db.add_chat(G2, "Guruh 2", c2)
    return c1, c2


# ── jamlanmalar bo'yicha ajratish ───────────────────────────────────────
def test_routes_are_isolated_per_collection(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            c1, c2 = await _two_collections(db)
            await db.add_route(c1, "A", "B")
            await db.add_route(c2, "C", "D")
            assert [r["from_place"] for r in await db.list_routes(c1)] == ["A"]
            assert [r["from_place"] for r in await db.list_routes(c2)] == ["C"]
        finally:
            await db.close()
    run(go())


def test_board_shows_only_own_collection_drivers(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            c1, c2 = await _two_collections(db)
            r1 = await db.add_route(c1, "A", "B")
            r2 = await db.add_route(c2, "A", "B")     # bir xil nom, boshqa jamlanma
            await _driver(db, 1, c1)
            await _driver(db, 2, c2)
            await db.start_entry(1, r1, 2)
            await db.start_entry(2, r2, 3)
            b1 = await db.board_routes(c1)
            b2 = await db.board_routes(c2)
            assert [e["first_name"] for e in b1[0]["entries"]] == ["F1"]
            assert [e["first_name"] for e in b2[0]["entries"]] == ["F2"]
        finally:
            await db.close()
    run(go())


def test_driver_of_other_collection_is_hidden_from_board(tmp_path):
    """J1 haydovchisi J2 yo'nalishida e'lon qo'ysa ham J2 oynasida ko'rinmaydi."""
    async def go():
        db = await _db(tmp_path)
        try:
            c1, c2 = await _two_collections(db)
            r2 = await db.add_route(c2, "X", "Y")
            await _driver(db, 1, c1)
            await db.start_entry(1, r2, 2)
            assert (await db.board_routes(c2))[0]["entries"] == []
        finally:
            await db.close()
    run(go())


def test_collection_settings_are_separate(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            c1, c2 = await _two_collections(db)
            await db.set_collection_field(c1, "auto_stop_hours", 4)
            await db.set_collection_field(c2, "repost_after_msgs", 10)
            a, b = await db.get_collection(c1), await db.get_collection(c2)
            assert a["auto_stop_hours"] == 4 and a["repost_after_msgs"] == 3
            assert b["auto_stop_hours"] == 2 and b["repost_after_msgs"] == 10
        finally:
            await db.close()
    run(go())


def test_auto_stop_uses_collection_hours(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            c1, c2 = await _two_collections(db)
            await db.set_collection_field(c2, "auto_stop_hours", 4)
            r1 = await db.add_route(c1, "A", "B")
            r2 = await db.add_route(c2, "C", "D")
            await _driver(db, 1, c1)
            await _driver(db, 2, c2)
            e1, _ = await db.start_entry(1, r1, 2)
            e2, _ = await db.start_entry(2, r2, 2)
            old = int(time.time()) - 3 * 3600          # 3 soat oldin yangilangan
            await db._exec("UPDATE entries SET updated_at=?", (old,))
            stale = {e["id"] for e in await db.stale_entries(int(time.time()))}
            assert e1 in stale and e2 not in stale      # J1: 2 soat, J2: 4 soat
        finally:
            await db.close()
    run(go())


def test_delete_collection_clears_data_and_unassigns_drivers(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            c1, c2 = await _two_collections(db)
            r = await db.add_route(c1, "A", "B")
            await _driver(db, 1, c1)
            await db.start_entry(1, r, 2)
            await db.set_board(G1, [5, 6])
            await db.add_taxi_log(c1, 9, 1000)
            removed = await db.delete_collection(c1)
            assert removed == [G1]
            assert await db.get_collection(c1) is None
            assert await db.all_chat_ids() == [G2]          # G1 jamlanmadan ajratildi
            assert await db.list_routes(c1) == []
            assert await db.driver_entries(1) == []
            assert await db.get_board(G1) == []
            assert await db.taxi_requests_count(c1) == 0
            assert (await db.get_user(1)).group_id is None
        finally:
            await db.close()
    run(go())


def test_deleted_collection_does_not_come_back_on_reopen(tmp_path):
    async def go():
        db = await _db(tmp_path)
        c1, _ = await _two_collections(db)
        await db.delete_collection(c1)
        await db.close()
        db = await _db(tmp_path)
        try:
            assert [c["id"] for c in await db.list_collections()] == [c1 + 1]
        finally:
            await db.close()
    run(go())


# ── guruhlar (chats): qo'shish, ko'chirish, olib tashlash ──────────────
def test_chats_add_move_remove(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            c1 = await db.add_collection("Haydovchilar 1")
            c2 = await db.add_collection("Haydovchilar 2")
            assert await db.add_chat(G1, "G", c1) is True
            assert await db.add_chat(G1, "G", c1) is False         # takror qo'shilmaydi
            assert [c["chat_id"] for c in await db.list_chats(c1)] == [G1]
            await db.move_chat(G1, c2)
            assert await db.list_chats(c1) == []
            assert [c["chat_id"] for c in await db.list_chats(c2)] == [G1]
            ctx = await db.get_chat_ctx(G1)
            assert ctx["collection_id"] == c2 and ctx["name"] == "Haydovchilar 2"
            await db.remove_chat(G1)
            assert await db.get_chat(G1) is None
            assert (await db.get_collection(c2))["chat_count"] == 0
        finally:
            await db.close()
    run(go())


def test_chat_ctx_follows_collection_settings(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            c1, _ = await _two_collections(db)
            await db.set_collection_field(c1, "paused", 1)
            await db.set_collection_field(c1, "taxi_enabled", 0)
            ctx = await db.get_chat_ctx(G1)
            assert ctx["paused"] == 1 and ctx["taxi_enabled"] == 0
            assert await db.get_chat_ctx(-100999) is None
        finally:
            await db.close()
    run(go())


def test_chat_state_is_independent_per_chat(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            c1, _ = await _two_collections(db)
            await db.add_chat(G3, "Guruh 3", c1)                   # G1 va G3 — bir jamlanmada
            await db.set_chat_value(G1, "msgs_since_repost", 4)
            assert await db.get_chat_value(G3, "msgs_since_repost") == 0
        finally:
            await db.close()
    run(go())


# ── bitta faol e'lon ───────────────────────────────────────────────────
def test_one_active_entry_per_driver(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            c1, _ = await _two_collections(db)
            r1 = await db.add_route(c1, "A", "B")
            r2 = await db.add_route(c1, "C", "D")
            await _driver(db, 1, c1)
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
            c1, _ = await _two_collections(db)
            r = await db.add_route(c1, "A", "B")
            await _driver(db, 1, c1)
            await db.start_entry(1, r, 2)
            await db.start_entry(1, r, 5)
            e = await db.driver_entries(1)
            assert len(e) == 1 and e[0]["seats"] == 5
        finally:
            await db.close()
    run(go())


def test_change_driver_collection_stops_entries(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            c1, c2 = await _two_collections(db)
            r = await db.add_route(c1, "A", "B")
            await _driver(db, 1, c1)
            await db.start_entry(1, r, 2)
            await db.change_driver_collection(1, c2)
            assert await db.driver_entries(1) == []
            assert (await db.get_user(1)).group_id == c2
        finally:
            await db.close()
    run(go())


def test_expired_subscription_hidden_from_board(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            c1, _ = await _two_collections(db)
            r = await db.add_route(c1, "A", "B")
            await _driver(db, 1, c1, paid_days=30)
            await _driver(db, 2, c1, paid_days=0)                  # obuna belgilanmagan
            await db.start_entry(1, r, 2)
            await db.start_entry(2, r, 3)
            names = [e["first_name"] for e in (await db.board_routes(c1))[0]["entries"]]
            assert names == ["F1"]
        finally:
            await db.close()
    run(go())


def test_set_subscription_days_replaces_old_end(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            c1, _ = await _two_collections(db)
            await _driver(db, 1, c1, paid_days=10)
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
            c1, _ = await _two_collections(db)
            await _driver(db, 1, c1, paid_days=2)                 # 3 kundan kam qoldi
            now = int(time.time())
            assert len(await db.subscription_expiring(now)) == 1
            u = await db.get_user(1)
            await db.update_user_fields(1, warned_for=u.paid_until)
            assert await db.subscription_expiring(now) == []      # ikkinchi marta yubormaydi
        finally:
            await db.close()
    run(go())


def test_expired_with_entries_detected(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            c1, _ = await _two_collections(db)
            r = await db.add_route(c1, "A", "B")
            await _driver(db, 1, c1, paid_days=30)
            await db.start_entry(1, r, 2)
            await db.set_subscription_end(1, int(time.time()) - 60)
            assert len(await db.subscription_expired_with_entries(int(time.time()))) == 1
        finally:
            await db.close()
    run(go())


# ── taksi ──────────────────────────────────────────────────────────────
def test_taxi_recipients_need_active_entry_in_same_collection(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            c1, c2 = await _two_collections(db)
            r1 = await db.add_route(c1, "A", "B")
            r2 = await db.add_route(c2, "C", "D")
            now = int(time.time())
            await _driver(db, 1, c1)       # e'loni bor, J1
            await _driver(db, 2, c1)       # e'loni yo'q
            await _driver(db, 3, c2)       # e'loni bor, lekin J2
            await db.start_entry(1, r1, 2)
            await db.start_entry(3, r2, 2)
            assert await db.taxi_recipients(c1, now) == [1]
            await db.update_user_fields(1, taxi_on=0)          # o'chirib qo'yilgan
            assert await db.taxi_recipients(c1, now) == []
        finally:
            await db.close()
    run(go())


def test_taxi_log_cooldown_data(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            c1, c2 = await _two_collections(db)
            assert await db.taxi_last_request(c1, 55) == 0
            await db.add_taxi_log(c1, 55, 1000)
            assert await db.taxi_last_request(c1, 55) == 1000
            assert await db.taxi_last_request(c2, 55) == 0      # boshqa jamlanma alohida
        finally:
            await db.close()
    run(go())


# ── migratsiya: eski bazalar ───────────────────────────────────────────
# 1) har guruh alohida (groups jadvali bor, bog'liq yozuvlar chat_id bilan) — joriy ishlab
#    turgan "7df9851" holati.
GROUP_SCHEMA = """
CREATE TABLE groups (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL UNIQUE,
  title TEXT NOT NULL DEFAULT '', paused INTEGER NOT NULL DEFAULT 0,
  auto_stop_hours INTEGER NOT NULL DEFAULT 2, repost_after_msgs INTEGER NOT NULL DEFAULT 3,
  taxi_enabled INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL);
CREATE TABLE users (tg_id INTEGER PRIMARY KEY, first_name TEXT NOT NULL DEFAULT '',
  last_name TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'new', paid_until INTEGER NOT NULL DEFAULT 0,
  warned_for INTEGER NOT NULL DEFAULT 0, group_id INTEGER, taxi_on INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL);
CREATE TABLE routes (id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER,
  from_place TEXT NOT NULL, to_place TEXT NOT NULL, is_open INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL);
CREATE TABLE entries (id INTEGER PRIMARY KEY AUTOINCREMENT,
  driver_id INTEGER NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
  route_id INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
  seats INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
  updated_at INTEGER NOT NULL, UNIQUE (driver_id, route_id));
CREATE TABLE board (chat_id INTEGER NOT NULL, part_idx INTEGER NOT NULL,
  message_id INTEGER NOT NULL, PRIMARY KEY (chat_id, part_idx));
CREATE TABLE chat_state (chat_id INTEGER NOT NULL, key TEXT NOT NULL, value INTEGER NOT NULL,
  PRIMARY KEY (chat_id, key));
CREATE TABLE taxi_log (id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER NOT NULL,
  passenger_id INTEGER NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO groups(id, chat_id, title, auto_stop_hours, repost_after_msgs, created_at)
  VALUES (1, -100999, 'Eski guruh', 3, 5, 0), (2, -100888, '', 2, 3, 0);
INSERT INTO routes(id, group_id, from_place, to_place, created_at)
  VALUES (1, -100999, 'A', 'B', 0), (2, -100888, 'C', 'D', 0);
INSERT INTO users(tg_id, first_name, last_name, status, paid_until, group_id, created_at)
  VALUES (7, 'Ali', 'V', 'approved', 9999999999, -100999, 0),
         (8, 'Bek', 'T', 'approved', 9999999999, -100888, 0);
INSERT INTO entries(driver_id, route_id, seats, active, updated_at) VALUES (7, 1, 2, 1, 0);
INSERT INTO taxi_log(group_id, passenger_id, created_at) VALUES (-100999, 55, 1000);
INSERT INTO board(chat_id, part_idx, message_id) VALUES (-100999, 0, 77);
"""

# 2) eski, guruhsiz baza (bosqich 1): groups jadvali yo'q, sozlamalar settings da.
PRE_GROUP_SCHEMA = """
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
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO settings VALUES ('auto_stop_hours', '3'), ('repost_after_msgs', '5');
INSERT INTO routes(from_place, to_place, created_at) VALUES ('A', 'B', 0);
INSERT INTO users(tg_id, first_name, last_name, status, paid_until, created_at)
  VALUES (7, 'Ali', 'V', 'approved', 9999999999, 0);
INSERT INTO entries(driver_id, route_id, seats, active, updated_at) VALUES (7, 1, 2, 1, 0);
"""


def test_migrates_group_database_to_collections(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript(GROUP_SCHEMA)
    raw.commit()
    raw.close()

    async def go():
        db = Database(str(path))
        await db.open()
        try:
            # har guruh alohida jamlanma; id lari saqlangan
            c1 = await db.get_collection(1)
            assert c1["name"] == "Eski guruh" and c1["auto_stop_hours"] == 3
            assert c1["repost_after_msgs"] == 5
            c2 = await db.get_collection(2)
            assert c2["name"] == "Jamlanma 2"                      # bo'sh nom -> standart
            assert (await db.get_chat(-100999))["collection_id"] == 1
            assert (await db.get_chat(-100888))["collection_id"] == 2
            # bog'liq yozuvlar jamlanma id ga o'tgan
            assert [r["from_place"] for r in await db.list_routes(1)] == ["A"]
            assert [r["from_place"] for r in await db.list_routes(2)] == ["C"]
            u7, u8 = await db.get_user(7), await db.get_user(8)
            assert u7.group_id == 1 and u8.group_id == 2
            assert u7.taxi_on == 1
            assert len(await db.driver_entries(7)) == 1            # e'lon saqlandi
            assert await db.taxi_requests_count(1) == 1            # taksi tarixi saqlandi
            assert await db.get_board(-100999) == [(0, 77)]        # oyna yozuvi saqlandi
        finally:
            await db.close()
        # ikkinchi marta ochilganda takrorlanmaydi va o'chirilgan jamlanma qaytmaydi
        db = Database(str(path))
        await db.open()
        try:
            await db.delete_collection(2)
        finally:
            await db.close()
        db = Database(str(path))
        await db.open()
        try:
            assert [c["id"] for c in await db.list_collections()] == [1]
        finally:
            await db.close()
    run(go())


def test_migrates_pre_group_database(tmp_path):
    path = tmp_path / "pre.db"
    raw = sqlite3.connect(path)
    raw.executescript(PRE_GROUP_SCHEMA)
    raw.commit()
    raw.close()

    async def go():
        db = Database(str(path))
        await db.open()
        try:
            # guruhsiz eski baza: yo'nalish va haydovchi bo'sh, bog'liq jamlanma yo'q
            assert (await db.get_user(7)).group_id is None
            assert await db.driver_entries(7) == []   # jamlanmasiz e'lon ko'rinmaydi
            assert await db.list_collections() == []
        finally:
            await db.close()
    run(go())


# ── yo'nalish formati, vaqt ────────────────────────────────────────────
def test_multi_route_parse_separators():
    for s in ["Toshkent - Qibray", "Toshkent / Qibray", "Toshkent | Qibray", "Toshkent → Qibray",
              "Toshkent – Qibray", "Toshkent — Qibray", "Toshkent -> Qibray"]:
        assert parse_route(s) == ("Toshkent", "Qibray"), s


def test_end_of_day_timestamp():
    ts = end_of_day_ts(date(2026, 11, 30))
    assert datetime.fromtimestamp(ts, LOCAL_TZ).date() == date(2026, 11, 30)
    assert datetime.fromtimestamp(ts, LOCAL_TZ).hour == 23


def test_collection_add_list_pause(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            c1 = await db.add_collection("Toshkent haydovchilari")
            c2 = await db.add_collection("Samarqand haydovchilari")
            assert [c["id"] for c in await db.list_collections()] == [c1, c2]
            await db.set_collection_field(c1, "paused", 1)
            assert (await db.get_collection(c1))["paused"] == 1
            await db.set_collection_field(c1, "paused", 0)
            assert (await db.get_collection(c1))["paused"] == 0
            try:
                await db.set_collection_field(c1, "id", 5)
                raise AssertionError("ruxsat berilmasligi kerak")
            except ValueError:
                pass
        finally:
            await db.close()
    run(go())
