"""
Guruh oynasi qoidalarini tekshiradi: tahrirlash vs pastga qayta yuborish,
eski nusxani o'chirish, jim yuborish.
"""

import asyncio
import time
from types import SimpleNamespace

import board as board_mod
from board import BoardManager
from db import Database


class FakeBot:
    def __init__(self):
        self.next_id = 100
        self.sent = []        # (message_id, text, disable_notification)
        self.edited = []      # (message_id, text)
        self.deleted = []     # message_id

    async def send_message(self, chat_id, text, reply_markup=None,
                           disable_notification=False, disable_web_page_preview=None):
        self.next_id += 1
        self.sent.append((self.next_id, text, disable_notification))
        return SimpleNamespace(message_id=self.next_id)

    async def edit_message_text(self, chat_id, message_id, text, reply_markup=None,
                                disable_web_page_preview=None):
        self.edited.append((message_id, text))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)


def _setup(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    return db


async def _seed(db):
    await db.add_route("Toshkent", "Qibray")
    await db.ensure_user(1)
    await db.update_user_fields(1, first_name="Ali", last_name="Valiyev",
                                phone="+998901234567", status="approved",
                                paid_until=int(time.time()) + 30 * 86400)
    await db.start_entry(1, 1, 2)


def test_first_sync_sends_pinless_message_silently(tmp_path, monkeypatch):
    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        await _seed(db)
        bot = FakeBot()
        bm = BoardManager(bot, db, -100, "haydovchi_bot")
        await bm.sync()
        assert len(bot.sent) == 1
        assert bot.sent[0][2] is True               # disable_notification
        assert "Ali Valiyev" in bot.sent[0][1]
        assert await db.get_board(-100) == [(0, bot.sent[0][0])]
        await db.close()

    asyncio.run(scenario())


def test_edit_in_place_when_board_is_last_message(tmp_path):
    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        await _seed(db)
        bot = FakeBot()
        bm = BoardManager(bot, db, -100, "haydovchi_bot")
        await bm.sync()                              # yuborildi
        sent_before = len(bot.sent)
        await db.start_entry(1, 1, 3)                # o'zgarish
        await bm.sync()                              # oyna hali pastda -> tahrir
        assert len(bot.sent) == sent_before          # yangi xabar yo'q
        assert len(bot.edited) == 1
        assert bot.edited[0][0] == (await db.get_board(-100))[0][1]
        await db.close()

    asyncio.run(scenario())


def test_repost_when_other_messages_came_after(tmp_path, monkeypatch):
    monkeypatch.setattr(board_mod, "REPOST_MIN_SEC", 0)

    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        await _seed(db)
        bot = FakeBot()
        bm = BoardManager(bot, db, -100, "haydovchi_bot")
        await bm.sync()
        old_mid = (await db.get_board(-100))[0][1]
        await bm.on_group_message(9001)              # boshqa odam yozdi
        await bm.sync()
        new_mid = (await db.get_board(-100))[0][1]
        assert new_mid != old_mid                    # qayta yuborildi
        assert old_mid in bot.deleted                # eskisi o'chirildi
        assert bot.sent[-1][2] is True               # jim yuborildi
        assert await db.get_chat_value(-100, "msgs_since_repost") == 0
        await db.close()

    asyncio.run(scenario())


def test_min_interval_defers_repost(tmp_path, monkeypatch):
    monkeypatch.setattr(board_mod, "REPOST_MIN_SEC", 3600)

    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        await _seed(db)
        bot = FakeBot()
        bm = BoardManager(bot, db, -100, "haydovchi_bot")
        await bm.sync()
        sent_before = len(bot.sent)
        await bm.on_group_message(9001)
        await bm.sync()                              # oraliq hali o'tmagan -> qayta yubormaydi
        assert len(bot.sent) == sent_before
        assert bm._timer is not None                 # keyinroq rejalashtirildi
        bm._timer.cancel()
        await db.close()

    asyncio.run(scenario())


def test_force_repost_always_resends(tmp_path, monkeypatch):
    monkeypatch.setattr(board_mod, "REPOST_MIN_SEC", 3600)

    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        await _seed(db)
        bot = FakeBot()
        bm = BoardManager(bot, db, -100, "haydovchi_bot")
        await bm.sync()
        await bm.force_repost()
        assert len(bot.sent) == 2
        assert len(bot.deleted) == 1
        await db.close()

    asyncio.run(scenario())


def test_manual_delete_recovers_by_repost(tmp_path):
    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        await _seed(db)

        class FlakyBot(FakeBot):
            async def edit_message_text(self, chat_id, message_id, text, **kw):
                from telegram.error import BadRequest
                raise BadRequest("Message to edit not found")

        bot = FlakyBot()
        bm = BoardManager(bot, db, -100, "haydovchi_bot")
        await bm.sync()                              # 1-marta yuborildi
        await bm.sync()                              # edit xato -> qayta yuboradi
        assert len(bot.sent) == 2
        await db.close()

    asyncio.run(scenario())


def test_stopped_entry_disappears_from_board(tmp_path):
    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        await _seed(db)
        bot = FakeBot()
        bm = BoardManager(bot, db, -100, "haydovchi_bot")
        await bm.sync()
        await db.stop_entry((await db.get_entry(1, 1))["id"])
        await bm.sync()
        assert "Ali Valiyev" not in bot.edited[-1][1]
        assert "Hozircha faol haydovchi yo'q" in bot.edited[-1][1]
        await db.close()

    asyncio.run(scenario())
