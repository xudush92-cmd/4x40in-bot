"""Faqat egasining bot chatiga yetkazish; Saved Messages nusxasi yo'q."""
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('ADMIN_ID', '777')
os.environ.setdefault('API_ID', '1')
os.environ.setdefault('API_HASH', 'x')
os.environ.setdefault('BOT_TOKEN', '1:x')

from telethon.tl.types import PeerUser
import database as db
import scanner_manager as sm


class Client:
    def __init__(self):
        self.send_message = AsyncMock()
        self.forward_messages = AsyncMock()
    def on(self, _builder):
        def register(fn):
            self.handler = fn
            return fn
        return register


def event(chat_id, mid, protected=False):
    return SimpleNamespace(
        chat_id=chat_id, is_private=False, raw_text='mashina kerak', out=False, id=mid,
        message=SimpleNamespace(from_id=PeerUser(user_id=500), noforwards=protected, sticker=None),
        get_chat=AsyncMock(return_value=SimpleNamespace(title='Test guruh', username='publicgroup', noforwards=protected)),
        get_sender=AsyncMock(return_value=SimpleNamespace(id=500, first_name='Ali', last_name='', username='testuser', phone='998901234567')),
    )


class BotChatDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, 'DB_NAME', os.path.join(self.tmp.name, 'test.db'))
        self.db_patch.start()
        db.init_db()
        for uid in (101, 202, 303):
            db.upsert_user(uid, 'Test')
        with db.closing(db._connect()) as conn, conn:
            conn.execute('UPDATE users SET sub_expires_at=?', (int(time.time()) + 86400,))
            for uid, chat in ((101, -100111), (202, -100222), (303, -100111)):
                conn.execute("INSERT INTO user_groups (owner_user_id, input_value, chat_id, is_active, status) VALUES (?, ?, ?, 1, 'ok')", (uid, str(chat), chat))
        db.set_setting('match_count', '1')
        db.set_match_mode('count')
        db.add_keyword_checked('kerak')

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    async def test_owners_only_receive_their_own_groups_and_no_saved_copies(self):
        clients = [Client() for _ in range(3)]
        handlers = [sm._make_handler(uid, client) for uid, client in zip((101, 202, 303), clients)]
        send = AsyncMock(return_value=True)
        with patch.object(sm, 'send_to_bot_api', send), patch.object(sm, 'save_lead_review', return_value=None):
            for handler in handlers:
                await handler(event(-100111, 10))
            for handler in handlers:
                await handler(event(-100222, 11))
        self.assertEqual([call.kwargs['chat_id'] for call in send.await_args_list], [101, 303, 202])
        for client in clients:
            client.send_message.assert_not_awaited()
            client.forward_messages.assert_not_awaited()

    async def test_bot_alert_contains_message_and_sender_details(self):
        client = Client()
        handler = sm._make_handler(101, client)
        send = AsyncMock(return_value=True)
        with patch.object(sm, 'send_to_bot_api', send), patch.object(sm, 'save_lead_review', return_value=None):
            await handler(event(-100111, 43))
        send.assert_awaited_once()
        alert, markup = send.await_args.args
        self.assertEqual(send.await_args.kwargs['chat_id'], 101)
        for expected in ('mashina kerak', 'Ali', '@testuser', '998901234567', 'https://t.me/publicgroup/43'):
            self.assertIn(expected, alert)
        self.assertTrue(any(button.get('url') == 'https://t.me/publicgroup/43'
                            for row in markup['inline_keyboard'] for button in row))
        client.send_message.assert_not_awaited()
        client.forward_messages.assert_not_awaited()

    async def test_protected_content_is_not_copied_or_forwarded(self):
        client = Client()
        handler = sm._make_handler(101, client)
        send = AsyncMock(return_value=True)
        with patch.object(sm, 'send_to_bot_api', send):
            await handler(event(-100111, 42, protected=True))
        self.assertEqual(send.await_args.kwargs['chat_id'], 101)
        self.assertNotIn('mashina kerak', send.await_args.args[0])
        self.assertIn('guruhdagi asl xabarni ochish', send.await_args.args[0].lower())
        client.send_message.assert_not_awaited()
        client.forward_messages.assert_not_awaited()

    async def test_shared_or_polled_event_still_checks_each_owners_group(self):
        send = AsyncMock(return_value=True)
        clients = [Client(), Client()]
        handlers = [sm._make_handler(uid, c) for uid, c in zip((202, 303), clients)]
        with patch.object(sm, 'send_to_bot_api', send), patch.object(sm, 'save_lead_review', return_value=None):
            for handler in handlers:
                await handler(sm._PolledEvent(event(-100111, 77), polled_by=101))
        self.assertEqual([call.kwargs['chat_id'] for call in send.await_args_list], [303])
        for client in clients:
            client.send_message.assert_not_awaited()
            client.forward_messages.assert_not_awaited()

    async def test_old_saved_messages_env_setting_cannot_enable_copies(self):
        client = Client()
        handler = sm._make_handler(101, client)
        with patch.dict(os.environ, {'SCANNER_SAVED_MESSAGES': '1'}), \
             patch.object(sm, 'send_to_bot_api', new_callable=AsyncMock, return_value=True), \
             patch.object(sm, 'save_lead_review', return_value=None):
            await handler(event(-100111, 99))
        client.send_message.assert_not_awaited()
        client.forward_messages.assert_not_awaited()


if __name__ == '__main__': unittest.main()
