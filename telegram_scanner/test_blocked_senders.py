"""Shaxsiy yuboruvchi bloklari va skaner integratsiyasi testlari."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_tmp.close()
os.environ['SCANNER_DB_PATH'] = _tmp.name
os.environ.setdefault('ADMIN_ID', '777')
os.environ.setdefault('API_ID', '1')
os.environ.setdefault('API_HASH', 'x')
os.environ.setdefault('BOT_TOKEN', '1:x')

import bot
import database as db
import scanner_manager as sm
from telethon.tl.types import PeerUser, PeerChannel


def setUpModule():
    db.init_db()


def tearDownModule():
    os.unlink(_tmp.name)


class Client:
    def on(self, _builder):
        def register(fn):
            self.handler = fn
            return fn
        return register


class TestBlockedSenders(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with db.closing(db._connect()) as conn, conn:
            conn.execute('DELETE FROM blocked_senders')

    def test_isolation_idempotency_and_delete(self):
        self.assertTrue(db.block_sender(100, 500))
        self.assertFalse(db.block_sender(100, 500))
        self.assertTrue(db.is_sender_blocked(100, 500))
        self.assertFalse(db.is_sender_blocked(200, 500))
        self.assertTrue(db.block_sender(200, 500))
        self.assertTrue(db.unblock_sender(100, 500))
        self.assertTrue(db.is_sender_blocked(200, 500))
        db.delete_user_completely(200)
        self.assertFalse(db.is_sender_blocked(200, 500))
        self.assertFalse(db.block_sender(100, 100))

    def test_pagination(self):
        for i in range(21):
            db.block_sender(100, 501 + i)
        ids, total = db.list_blocked_senders(100, 10, 10)
        self.assertEqual((len(ids), total), (10, 21))
        text, markup = bot._blocked_page(100, 2)
        self.assertIn('21', text)
        self.assertEqual(len(markup.inline_keyboard[0]), 1)

    async def test_confirmation_only_changes_own_list(self):
        cb = SimpleNamespace(
            data='bsc:500', from_user=SimpleNamespace(id=100),
            message=SimpleNamespace(chat=SimpleNamespace(id=100, type='private'),
                                    edit_text=AsyncMock()), answer=AsyncMock())
        await bot.confirm_block_sender(cb)
        self.assertTrue(db.is_sender_blocked(100, 500))
        self.assertFalse(db.is_sender_blocked(200, 500))
        cb.data = 'bsu:500:0'
        await bot.unblock_sender_callback(cb)
        self.assertFalse(db.is_sender_blocked(100, 500))

    async def test_foreign_chat_cannot_change_list(self):
        cb = SimpleNamespace(data='bsc:500', from_user=SimpleNamespace(id=100),
                             message=SimpleNamespace(chat=SimpleNamespace(id=200, type='private'),
                                                     edit_text=AsyncMock()), answer=AsyncMock())
        await bot.confirm_block_sender(cb)
        self.assertFalse(db.is_sender_blocked(100, 500))
        cb.message.edit_text.assert_not_awaited()

    async def test_scanner_suppresses_only_owner_and_never_blocks_channel(self):
        db.block_sender(100, 500)
        verdict = SimpleNamespace(ok=True, matched=['kerak'], mode='count', required=1,
                                  score=3, threshold=3, positives={}, negatives={})
        def event(peer):
            return SimpleNamespace(
                chat_id=-100123456, is_private=False, raw_text='mashina kerak', out=False,
                id=15, message=SimpleNamespace(from_id=peer, noforwards=False, sticker=None),
                get_chat=AsyncMock(return_value=SimpleNamespace(title='test', username='grouptest', noforwards=False)),
                get_sender=AsyncMock(return_value=SimpleNamespace(id=500, first_name='Test', last_name='', username='tester', phone=None)),
            )
        one, two = Client(), Client()
        sm._make_handler(100, one)
        sm._make_handler(200, two)
        send = AsyncMock(return_value=True)
        with patch.object(sm, 'evaluate', return_value=verdict), \
             patch.object(sm, 'send_to_bot_api', send), \
             patch.object(sm, 'save_lead_review', return_value=None), \
             patch.object(sm, 'increment_user_counter'), \
             patch.object(sm, 'set_user_last_found'), \
             patch.object(sm, 'increment_counter'):
            blocked = event(PeerUser(user_id=500))
            await one.handler(blocked)
            blocked.get_chat.assert_not_awaited()
            send.assert_not_awaited()
            await two.handler(event(PeerUser(user_id=500)))
            self.assertEqual(send.await_count, 1)
            markup = send.await_args.args[1]
            self.assertTrue(any(b.get('callback_data') == 'bsp:500' for row in markup['inline_keyboard'] for b in row))
            await one.handler(event(PeerChannel(channel_id=500)))
            self.assertEqual(send.await_count, 2)
            markup = send.await_args.args[1]
            self.assertFalse(any(b.get('callback_data', '').startswith('bsp:') for row in markup['inline_keyboard'] for b in row))

    async def test_protected_card_keeps_no_raw_text_and_has_block_button(self):
        verdict = SimpleNamespace(ok=True, matched=['kerak'], mode='weight', required=1)
        event = SimpleNamespace(chat_id=-100123456, is_private=False, raw_text='maxfiy xabar', out=False,
            id=15, sender_id=500, message=SimpleNamespace(from_id=PeerUser(user_id=500), noforwards=True, sticker=None),
            get_chat=AsyncMock(return_value=SimpleNamespace(title='test', username='grouptest', noforwards=True)),
            get_sender=AsyncMock(return_value=SimpleNamespace(id=500, first_name='Test', last_name='', username=None)))
        client = Client()
        sm._make_handler(200, client)
        send = AsyncMock(return_value=True)
        with patch.object(sm, 'evaluate', return_value=verdict), patch.object(sm, 'send_to_bot_api', send), \
             patch.object(sm, 'increment_user_counter'), patch.object(sm, 'set_user_last_found'), \
             patch.object(sm, 'increment_counter'):
            await client.handler(event)
        self.assertNotIn('maxfiy xabar', send.await_args.args[0])
        markup = send.await_args.args[1]
        self.assertTrue(any(b.get('callback_data') == 'bsp:500' for row in markup['inline_keyboard'] for b in row))


if __name__ == '__main__':
    unittest.main()
