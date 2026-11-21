"""Profil havolasi va Bot API xatodagi zaxira yuborish testlari."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('ADMIN_ID', '777')
os.environ.setdefault('API_ID', '1')
os.environ.setdefault('API_HASH', 'x')
os.environ.setdefault('BOT_TOKEN', '1:x')

from telethon.tl.types import PeerUser, PeerChannel
import notifier
import scanner_manager as sm


class Response:
    def __init__(self, status): self.status = status
    async def text(self): return 'test error'
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass


class Session:
    def __init__(self): self.payloads = []
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def post(self, url, json):
        self.payloads.append(json)
        return Response(400 if len(self.payloads) == 1 else 200)


class FakeClient:
    def on(self, builder):
        def register(fn):
            self.handler = fn
            return fn
        return register


class ProfileDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejected_id_link_retry_retains_source_and_feedback(self):
        session = Session()
        text = '<a href="tg://user?id=123">Ali</a> <a href="https://t.me/c/42/1">source</a>'
        markup = {'inline_keyboard': [[{'text': 'profile', 'url': 'tg://user?id=123'}],
                                     [{'text': 'source', 'url': 'https://t.me/c/42/1'}],
                                     [{'text': 'feedback', 'callback_data': 'fb:1:1'}]]}
        with patch.object(notifier.aiohttp, 'ClientSession', return_value=session):
            self.assertTrue(await notifier.send_to_bot_api(text, markup, chat_id=100))
        retry = session.payloads[1]
        self.assertNotIn('tg://user', retry['text'])
        self.assertIn('https://t.me/c/42/1', retry['text'])
        self.assertEqual(retry['reply_markup']['inline_keyboard'], markup['inline_keyboard'][1:])
        self.assertEqual(retry['chat_id'], 100)

    async def test_handler_uses_user_peer_id_not_channel_id(self):
        verdict = SimpleNamespace(ok=True, matched=['kerak'], mode='count', required=1,
                                  score=3, threshold=3, positives={}, negatives={})
        async def run(peer, sender):
            event = SimpleNamespace(chat_id=-100123456, is_private=False, raw_text='taksi kerak',
                out=False, id=15, message=SimpleNamespace(from_id=peer, noforwards=False, sticker=None),
                get_chat=AsyncMock(return_value=SimpleNamespace(title='test', username='testgroup', noforwards=False)),
                get_sender=AsyncMock(return_value=sender))
            client = FakeClient()
            sm._make_handler(100, client)
            send = AsyncMock(return_value=True)
            with patch.object(sm, 'evaluate', return_value=verdict), patch.object(sm, 'is_sender_blocked', return_value=False), \
                 patch.object(sm, 'send_to_bot_api', send), patch.object(sm, 'save_lead_review', return_value=1), \
                 patch.object(sm, 'increment_user_counter'), patch.object(sm, 'set_user_last_found'), patch.object(sm, 'increment_counter'):
                await client.handler(event)
            return send.await_args
        user = await run(PeerUser(user_id=500), SimpleNamespace(id=500, first_name='Ali', last_name='', username=None, phone=None))
        self.assertIn('tg://user?id=500', user.args[0])
        self.assertTrue(any(b.get('url') == 'tg://user?id=500' for row in user.args[1]['inline_keyboard'] for b in row))
        self.assertEqual(user.kwargs['chat_id'], 100)
        channel = await run(PeerChannel(channel_id=500), SimpleNamespace(id=500, title='Channel', username=None, phone=None))
        self.assertNotIn('tg://user?id=500', channel.args[0])
        self.assertFalse(any(b.get('url') == 'tg://user?id=500' for row in channel.args[1]['inline_keyboard'] for b in row))


if __name__ == '__main__':
    unittest.main()
