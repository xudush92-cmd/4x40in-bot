"""Taksi so'rovi: kimga boradi, spam cheklovi, to'xtatish tugmasi (jamlanma darajasida)."""
import asyncio
import time
from types import SimpleNamespace

import taxi
from db import Database

G1, G2, G3 = -100111, -100222, -100333   # G1 va G3 — bir jamlanmada; G2 — boshqa jamlanmada


class FakeBot:
    def __init__(self, fail_for=()):
        self.sent = []          # (chat_id, text, markup)
        self.fail_for = set(fail_for)

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        from telegram.error import TelegramError
        if chat_id in self.fail_for:
            raise TelegramError("blocked")
        self.sent.append((chat_id, text, reply_markup))


def _passenger(uid=55, username="vali"):
    return SimpleNamespace(id=uid, full_name="Vali Aliyev", username=username)


async def _setup(tmp_path):
    """
    J1 (c1): G1, G3 guruhlari; haydovchi 1 — J1 da e'londa.
    J2 (c2): G2 guruhi; haydovchi 2 — J2 da e'londa.
    """
    db = Database(str(tmp_path / "taxi.db"))
    await db.open()
    c1 = await db.add_collection("J1")
    c2 = await db.add_collection("J2")
    await db.add_chat(G1, "Guruh 1", c1)
    await db.add_chat(G3, "Guruh 3", c1)
    await db.add_chat(G2, "Guruh 2", c2)
    r1 = await db.add_route(c1, "A", "B")
    r2 = await db.add_route(c2, "C", "D")
    paid = int(time.time()) + 86400 * 30
    await db.ensure_user(1)
    await db.update_user_fields(1, first_name="Ali", last_name="V", phone="+998901112233",
                                status="approved", group_id=c1, paid_until=paid)
    await db.ensure_user(2)
    await db.update_user_fields(2, first_name="Bek", last_name="T", phone="+998901112244",
                                status="approved", group_id=c2, paid_until=paid)
    await db.start_entry(1, r1, 2)
    await db.start_entry(2, r2, 1)
    return db, c1, c2


def test_request_reaches_active_driver_and_is_rate_limited(tmp_path):
    async def go():
        db, _, _ = await _setup(tmp_path)
        try:
            bot = FakeBot()
            answer = await taxi.passenger_request(bot, db, G1, _passenger())
            assert answer.startswith("✅")
            assert len(bot.sent) == 1 and bot.sent[0][0] == 1
            assert "Vali Aliyev (@vali)" in bot.sent[0][1]
            labels = [b.text for row in bot.sent[0][2].inline_keyboard for b in row]
            assert "👤 Bog'lanish" in labels and taxi.BTN_MUTE in labels
            # ikkinchi bosish darhol — spam cheklovi
            again = await taxi.passenger_request(bot, db, G1, _passenger())
            assert "soniyadan keyin" in again and len(bot.sent) == 1
        finally:
            await db.close()
    asyncio.run(go())


def test_cooldown_is_shared_across_chats_of_same_collection(tmp_path):
    async def go():
        db, _, _ = await _setup(tmp_path)
        try:
            bot = FakeBot()
            await taxi.passenger_request(bot, db, G1, _passenger())
            # boshqa guruh, lekin bir jamlanma — yo'lovchi yana darhol so'ray olmaydi
            again = await taxi.passenger_request(bot, db, G3, _passenger())
            assert "soniyadan keyin" in again and len(bot.sent) == 1
        finally:
            await db.close()
    asyncio.run(go())


def test_request_goes_only_to_drivers_of_the_same_collection(tmp_path):
    async def go():
        db, _, _ = await _setup(tmp_path)
        try:
            bot = FakeBot()
            # G2 (J2) — faqat J2 haydovchisi (2) olishi kerak; J1 haydovchisi (1) emas
            answer = await taxi.passenger_request(bot, db, G2, _passenger())
            assert answer.startswith("✅")
            assert [s[0] for s in bot.sent] == [2]
        finally:
            await db.close()
    asyncio.run(go())


def test_no_active_driver_in_collection(tmp_path):
    async def go():
        db, c1, _ = await _setup(tmp_path)
        try:
            await db.stop_all_for_driver(1)                       # J1 da e'lon yo'q
            bot = FakeBot()
            assert "Hozir faol taksi" in await taxi.passenger_request(bot, db, G1, _passenger())
            assert bot.sent == []
        finally:
            await db.close()
    asyncio.run(go())


def test_unknown_chat_refuses(tmp_path):
    async def go():
        db, _, _ = await _setup(tmp_path)
        try:
            bot = FakeBot()
            assert "yoqilmagan" in await taxi.passenger_request(bot, db, -100999, _passenger())
            assert bot.sent == []
        finally:
            await db.close()
    asyncio.run(go())


def test_disabled_collection_refuses(tmp_path):
    async def go():
        db, c1, _ = await _setup(tmp_path)
        try:
            await db.set_collection_field(c1, "taxi_enabled", 0)
            bot = FakeBot()
            assert "yoqilmagan" in await taxi.passenger_request(bot, db, G1, _passenger())
            assert bot.sent == []
        finally:
            await db.close()
    asyncio.run(go())


def test_mute_stops_future_requests_for_driver(tmp_path):
    async def go():
        db, _, _ = await _setup(tmp_path)
        try:
            await taxi.mute_driver(db, 1)
            bot = FakeBot()
            assert "Hozir faol taksi" in await taxi.passenger_request(bot, db, G1, _passenger())
            assert bot.sent == []
            await db.update_user_fields(1, taxi_on=1)           # menyudan qayta yoqildi
            assert (await db.taxi_recipients(1, int(time.time()))) == [1]
        finally:
            await db.close()
    asyncio.run(go())
