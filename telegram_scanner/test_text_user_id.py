"""Matndagi ID alohida bildirilmaydi va telefon bilan adashmaydi."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('ADMIN_ID', '777')
os.environ.setdefault('API_ID', '1')
os.environ.setdefault('API_HASH', 'x')
os.environ.setdefault('BOT_TOKEN', '1:x')

import notifier
import scanner_manager as sm


class Client:
    def on(self, _builder):
        def register(fn):
            self.handler = fn
            return fn
        return register


class TextUserIdTests(unittest.IsolatedAsyncioTestCase):
    def test_id_is_not_treated_as_phone(self):
        self.assertEqual(notifier.find_phone_text('User ID: 123456789'), "Matnda ko'rsatilmagan")
        self.assertIn('901234567', notifier.find_phone_text('User ID: 123456789\nTel: 901234567'))

    async def test_protected_notice_hides_text_id_and_retains_source(self):
        verdict = SimpleNamespace(ok=True, matched=['kerak'], mode='count', required=1)
        event = SimpleNamespace(chat_id=-100123456, is_private=False,
            raw_text='maxfiy asl matn\nUser ID: 123456789', out=False, id=15, sender_id=None,
            message=SimpleNamespace(from_id=None, noforwards=True, sticker=None),
            get_chat=AsyncMock(return_value=SimpleNamespace(title='test', username='grouptest', noforwards=True)),
            get_sender=AsyncMock(return_value=None))
        client = Client()
        sm._make_handler(200, client)
        send = AsyncMock(return_value=True)
        with patch.object(sm, 'evaluate', return_value=verdict), patch.object(sm, 'send_to_bot_api', send), \
             patch.object(sm, 'increment_user_counter'), patch.object(sm, 'set_user_last_found'), patch.object(sm, 'increment_counter'):
            await client.handler(event)
        text, markup = send.await_args.args
        self.assertNotIn('maxfiy asl matn', text)
        self.assertNotIn('123456789', text)
        self.assertNotIn('Matnda yozilgan ID', text)
        self.assertNotIn('Topilgan kalitlar', text)
        self.assertIn('🔑 kerak', text)
        self.assertIn("Matnda ko&#x27;rsatilmagan", text)
        self.assertFalse(any('tg://user' in b.get('url', '') for row in markup['inline_keyboard'] for b in row))
        self.assertTrue(any('grouptest/15' in b.get('url', '') for row in markup['inline_keyboard'] for b in row))
        self.assertEqual(send.await_args.kwargs['chat_id'], 200)


if __name__ == '__main__': unittest.main()
