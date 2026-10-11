"""Taksi so'rovi: kimga boradi, spam cheklovi, to'xtatish tugmasi."""
import asyncio
import time
from types import SimpleNamespace

import taxi
from db import Database

G1, G2 = -100111, -100222


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
    db = Database(str(tmp_path / "taxi.db"))
    await db.open()
    await db.add_group(G1, "Guruh 1")
    await db.add_group(G2, "Guruh 2")
    r1 = await db.add_route(G1, "A", "B")
    await db.ensure_user(1)
    await db.update_user_fields(1, first_name="Ali", last_name="V", phone="+998901112233",
                                status="approved", group_id=G1,
                                paid_until=int(time.time()) + 86400 * 30)
    await db.start_entry(1, r1, 2)            # haydovchi G1 da e'londa
    return db


def test_request_reaches_active_driver_and_is_rate_limited(tmp_path):
    async def go():
        db = await _setup(tmp_path)
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


def test_no_active_driver_or_other_group(tmp_path):
    async def go():
        db = await _setup(tmp_path)
        try:
            bot = FakeBot()
            # G2 da faol haydovchi yo'q
            assert "Hozir faol taksi" in await taxi.passenger_request(bot, db, G2, _passenger())
            assert bot.sent == []
        finally:
            await db.close()
    asyncio.run(go())


def test_disabled_group_refuses(tmp_path):
    async def go():
        db = await _setup(tmp_path)
        try:
            await db.set_group_field(G1, "taxi_enabled", 0)
            bot = FakeBot()
            assert "yoqilmagan" in await taxi.passenger_request(bot, db, G1, _passenger())
            assert bot.sent == []
        finally:
            await db.close()
    asyncio.run(go())


def test_mute_stops_future_requests_for_driver(tmp_path):
    async def go():
        db = await _setup(tmp_path)
        try:
            await taxi.mute_driver(db, 1)
            bot = FakeBot()
            assert "Hozir faol taksi" in await taxi.passenger_request(bot, db, G1, _passenger())
            assert bot.sent == []
            await db.update_user_fields(1, taxi_on=1)           # menyudan qayta yoqildi
            assert (await db.taxi_recipients(G1, int(time.time()))) == [1]
        finally:
            await db.close()
    asyncio.run(go())
