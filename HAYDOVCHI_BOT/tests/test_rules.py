"""Yangi qoidalar: bitta faol e'lon, obuna, ko'p yo'nalish kiritish, avto-to'xtash."""
import asyncio
import time

from db import Database, end_of_day_ts
from utils import parse_route
from datetime import date

DAY = 86400


def run(coro):
    return asyncio.run(coro)


async def _db(tmp_path):
    db = Database(str(tmp_path / "r.db"))
    await db.open()
    return db


async def _driver(db, uid, paid_days=30, status="approved"):
    await db.ensure_user(uid)
    paid = int(time.time()) + paid_days * DAY if paid_days else 0
    await db.update_user_fields(uid, first_name=f"F{uid}", last_name="L", phone="+998901234567",
                                status=status, paid_until=paid)


def test_one_active_entry_per_driver(tmp_path):
    async def go():
        db = await _db(tmp_path)
        await db.add_route("A", "B")
        await db.add_route("C", "D")
        await _driver(db, 1)
        _, replaced1 = await db.start_entry(1, 1, 2)
        assert replaced1 == []
        _, replaced2 = await db.start_entry(1, 2, 3)
        assert replaced2 == ["A → B"]          # eski yo'nalish avtomatik to'xtadi
        active = await db.driver_entries(1)
        assert len(active) == 1 and active[0]["route_id"] == 2
        await db.close()
    run(go())


def test_restart_same_route_updates_seats(tmp_path):
    async def go():
        db = await _db(tmp_path)
        await db.add_route("A", "B")
        await _driver(db, 1)
        await db.start_entry(1, 1, 2)
        await db.start_entry(1, 1, 5)
        e = await db.driver_entries(1)
        assert len(e) == 1 and e[0]["seats"] == 5
        await db.close()
    run(go())


def test_expired_subscription_hidden_from_board(tmp_path):
    async def go():
        db = await _db(tmp_path)
        await db.add_route("A", "B")
        await _driver(db, 1, paid_days=30)
        await _driver(db, 2, paid_days=0)                 # obuna belgilanmagan
        await db.start_entry(1, 1, 2)
        await db.start_entry(2, 1, 3)
        rows = await db.board_routes()
        names = [e["first_name"] for e in rows[0]["entries"]]
        assert names == ["F1"]
        await db.close()
    run(go())


def test_set_subscription_days_replaces_old_end(tmp_path):
    async def go():
        db = await _db(tmp_path)
        await _driver(db, 1, paid_days=10)
        until = await db.set_subscription_days(1, 30)
        now = int(time.time())
        assert abs((until - now) - 30 * DAY) < 5          # hozirdan boshlab, eskisi bekor
        assert (await db.get_user(1)).paid_until == until
        await db.close()
    run(go())


def test_expiring_warning_once(tmp_path):
    async def go():
        db = await _db(tmp_path)
        await _driver(db, 1, paid_days=2)                 # 3 kundan kam qoldi
        now = int(time.time())
        assert len(await db.subscription_expiring(now)) == 1
        u = await db.get_user(1)
        await db.update_user_fields(1, warned_for=u.paid_until)
        assert await db.subscription_expiring(now) == []  # ikkinchi marta yubormaydi
        await db.close()
    run(go())


def test_expired_with_entries_detected(tmp_path):
    async def go():
        db = await _db(tmp_path)
        await db.add_route("A", "B")
        await _driver(db, 1, paid_days=30)
        await db.start_entry(1, 1, 2)
        await db.set_subscription_end(1, int(time.time()) - 60)
        found = await db.subscription_expired_with_entries(int(time.time()))
        assert len(found) == 1
        await db.close()
    run(go())


def test_stale_entry_auto_stop(tmp_path):
    async def go():
        db = await _db(tmp_path)
        await db.add_route("A", "B")
        await _driver(db, 1, paid_days=30)
        eid, _ = await db.start_entry(1, 1, 2)
        await db._exec("UPDATE entries SET updated_at=? WHERE id=?", (int(time.time()) - 3 * 3600, eid))
        stale = await db.stale_entries(int(time.time()) - 2 * 3600)
        assert [s["id"] for s in stale] == [eid]
        await db.stop_entry(eid)
        assert await db.driver_entries(1) == []
        await db.close()
    run(go())


def test_multi_route_parse_separators():
    for s in ["Toshkent - Qibray", "Toshkent / Qibray", "Toshkent | Qibray", "Toshkent → Qibray"]:
        assert parse_route(s) == ("Toshkent", "Qibray"), s


def test_end_of_day_timestamp():
    from datetime import datetime
    from utils import LOCAL_TZ
    ts = end_of_day_ts(date(2026, 11, 30))
    assert datetime.fromtimestamp(ts, LOCAL_TZ).date() == date(2026, 11, 30)
    assert datetime.fromtimestamp(ts, LOCAL_TZ).hour == 23


def test_groups_add_list_remove(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            assert await db.add_group(-100111, "Haydovchilar 1") is True
            assert await db.add_group(-100111, "Haydovchilar 1") is False   # takror qo'shilmaydi
            await db.add_group(-100222, "Haydovchilar 2")
            assert await db.group_ids() == [-100111, -100222]
            await db.set_board(-100111, [5, 6])
            await db.remove_group(-100111)
            assert await db.group_ids() == [-100222]
            assert await db.get_board(-100111) == []                   # oyna yozuvlari tozalanadi
        finally:
            await db.close()
    run(go())


def test_same_board_content_for_all_groups(tmp_path):
    """Bir xil yo'nalish va haydovchilar barcha guruhlarda bir xil ko'rinadi."""
    async def go():
        db = await _db(tmp_path)
        await db.add_route("A", "B")
        await _driver(db, 1)
        await db.start_entry(1, 1, 2)
        await db.add_group(-100111, "G1")
        await db.add_group(-100222, "G2")
        from board import routes_to_views
        from utils import render_parts, now_local
        rows = await db.board_routes()
        t1 = render_parts(routes_to_views(rows), now_local())
        t2 = render_parts(routes_to_views(rows), now_local())
        assert t1 == t2
        await db.close()
    run(go())


def test_repost_threshold_default_and_change(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            assert await db.repost_after_msgs() == 3
            await db.set_setting("repost_after_msgs", "5")
            assert await db.repost_after_msgs() == 5
        finally:
            await db.close()
    run(go())


def test_group_pause_flag(tmp_path):
    async def go():
        db = await _db(tmp_path)
        try:
            await db.add_group(-100333, "G3")
            await db.set_group_paused(-100333, True)
            g = [x for x in await db.list_groups() if x["chat_id"] == -100333][0]
            assert g["paused"] == 1 or g["paused"] is True
            await db.set_group_paused(-100333, False)
            g = [x for x in await db.list_groups() if x["chat_id"] == -100333][0]
            assert not g["paused"]
        finally:
            await db.close()
    run(go())
