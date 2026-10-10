"""
Guruh oynasi qoidalarini tekshiradi: 30 soniyalik skaner, tahrirlash vs pastga
qayta yuborish, eski nusxani o'chirish, jim yuborish, to'xtatilgan guruh.
"""

import asyncio
import time
from types import SimpleNamespace

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


def test_first_sync_sends_silently(tmp_path):
    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        try:
            await _seed(db)
            bot = FakeBot()
            bm = BoardManager(bot, db, -100, "haydovchi_bot")
            await bm.sync()
            assert len(bot.sent) == 1
            assert bot.sent[0][2] is True               # disable_notification
            assert "Ali Valiyev" in bot.sent[0][1]
            assert "+998901234567" in bot.sent[0][1]    # to'liq telefon
            assert await db.get_board(-100) == [(0, bot.sent[0][0])]
        finally:
            await db.close()

    asyncio.run(scenario())


def test_edit_in_place_when_board_is_last_message(tmp_path):
    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        try:
            await _seed(db)
            bot = FakeBot()
            bm = BoardManager(bot, db, -100, "haydovchi_bot")
            await bm.sync()
            sent_before = len(bot.sent)
            await db.start_entry(1, 1, 3)           # o'zgarish
            bm.mark_dirty()
            await bm.scan(3)                        # oyna hali pastda -> tahrir
            assert len(bot.sent) == sent_before     # yangi xabar yo'q
            assert len(bot.edited) == 1
            assert bot.edited[0][0] == (await db.get_board(-100))[0][1]
        finally:
            await db.close()

    asyncio.run(scenario())


def test_no_change_no_update(tmp_path):
    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        try:
            await _seed(db)
            bot = FakeBot()
            bm = BoardManager(bot, db, -100, "haydovchi_bot")
            await bm.sync()
            sent, edited = len(bot.sent), len(bot.edited)
            await bm.scan(3)                        # na o'zgarish, na 3 ta xabar
            assert len(bot.sent) == sent and len(bot.edited) == edited
        finally:
            await db.close()

    asyncio.run(scenario())


def test_two_messages_do_not_repost_three_do(tmp_path):
    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        try:
            await _seed(db)
            bot = FakeBot()
            bm = BoardManager(bot, db, -100, "haydovchi_bot")
            await bm.sync()
            old_mid = (await db.get_board(-100))[0][1]
            await bm.on_group_message(9001)
            await bm.on_group_message(9002)
            await bm.scan(3)                        # 2 < 3 -> qayta yubormaydi
            assert (await db.get_board(-100))[0][1] == old_mid
            await bm.on_group_message(9003)
            await bm.scan(3)                        # 3 >= 3 -> pastga tushadi
            new_mid = (await db.get_board(-100))[0][1]
            assert new_mid != old_mid
            assert old_mid in bot.deleted           # eskisi o'chirildi
            assert bot.sent[-1][2] is True          # jim yuborildi
            assert await db.get_chat_value(-100, "msgs_since_repost") == 0
        finally:
            await db.close()

    asyncio.run(scenario())


def test_driver_change_during_busy_chat_updates_on_scan(tmp_path):
    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        try:
            await _seed(db)
            bot = FakeBot()
            bm = BoardManager(bot, db, -100, "haydovchi_bot")
            await bm.sync()
            old_mid = (await db.get_board(-100))[0][1]
            await bm.on_group_message(9001)         # boshqa xabar: oyna endi oxirgi emas
            await db.update_user_fields(1, first_name="Anvar")
            bm.mark_dirty()
            await bm.scan(3)                        # o'zgarish bor -> yangilanadi (repost)
            assert "Anvar Valiyev" in bot.sent[-1][1]
            assert old_mid in bot.deleted
        finally:
            await db.close()

    asyncio.run(scenario())


def test_paused_group_is_not_scanned(tmp_path):
    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        try:
            await _seed(db)
            bot = FakeBot()
            bm = BoardManager(bot, db, -100, "haydovchi_bot", paused=True)
            await bm.scan(3)
            assert bot.sent == [] and bot.edited == []
        finally:
            await db.close()

    asyncio.run(scenario())


def test_failed_update_keeps_dirty_flag(tmp_path):
    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        try:
            await _seed(db)

            class DownBot(FakeBot):
                async def send_message(self, *a, **kw):
                    raise RuntimeError("network down")

            bm = BoardManager(DownBot(), db, -100, "haydovchi_bot")
            try:
                await bm.sync()
            except RuntimeError:
                pass
            assert bm.dirty is True                 # keyingi skanerda qayta urinadi
        finally:
            await db.close()

    asyncio.run(scenario())


def test_force_repost_always_resends(tmp_path):
    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        try:
            await _seed(db)
            bot = FakeBot()
            bm = BoardManager(bot, db, -100, "haydovchi_bot")
            await bm.sync()
            await bm.force_repost()
            assert len(bot.sent) == 2
            assert len(bot.deleted) == 1
        finally:
            await db.close()

    asyncio.run(scenario())


def test_manual_delete_recovers_by_repost(tmp_path):
    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        try:
            await _seed(db)

            class FlakyBot(FakeBot):
                async def edit_message_text(self, chat_id, message_id, text, **kw):
                    from telegram.error import BadRequest
                    raise BadRequest("Message to edit not found")

            bot = FlakyBot()
            bm = BoardManager(bot, db, -100, "haydovchi_bot")
            await bm.sync()                         # 1-marta yuborildi
            bm.mark_dirty()
            await bm.sync()                         # edit xato -> qayta yuboradi
            assert len(bot.sent) == 2
        finally:
            await db.close()

    asyncio.run(scenario())


def test_stopped_entry_disappears_from_board(tmp_path):
    async def scenario():
        db = _setup(tmp_path)
        await db.open()
        try:
            await _seed(db)
            bot = FakeBot()
            bm = BoardManager(bot, db, -100, "haydovchi_bot")
            await bm.sync()
            await db.stop_entry((await db.get_entry(1, 1))["id"])
            bm.mark_dirty()
            await bm.sync()
            assert "Ali Valiyev" not in bot.edited[-1][1]
            assert "Hozircha faol haydovchi yo'q" in bot.edited[-1][1]
        finally:
            await db.close()

    asyncio.run(scenario())
