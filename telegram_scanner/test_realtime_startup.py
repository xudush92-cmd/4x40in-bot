"""Updates during startup must wait until the session owner is verified."""
import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

_tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_tmp.close()
os.environ['SCANNER_DB_PATH'] = _tmp.name
os.environ.setdefault('ADMIN_ID', '777')
os.environ.setdefault('API_ID', '1')
os.environ.setdefault('API_HASH', 'x')
os.environ.setdefault('BOT_TOKEN', '1:x')

import database as db
import scanner_manager as sm


def setUpModule():
    db.init_db()


def tearDownModule():
    os.unlink(_tmp.name)


class TestRealtimeStartup(unittest.IsolatedAsyncioTestCase):
    async def test_message_is_registered_before_connect_but_waits_for_identity(self):
        owner = 123456
        event = SimpleNamespace(is_private=False, chat_id=-100123, raw_text='message',
                                message=SimpleNamespace(sticker=None, noforwards=False),
                                id=1, out=False)
        verdict = SimpleNamespace(ok=False, stage='keywords', detail='no match')
        evaluate = unittest.mock.Mock(return_value=verdict)
        task = None

        class FakeClient:
            def __init__(self, *args):
                self.handler = None
            def on(self, builder):
                def register(fn):
                    self.handler = fn
                    return fn
                return register
            async def connect(self):
                nonlocal task
                self_test.assertIsNotNone(self.handler)
                task = asyncio.create_task(self.handler(event))
                await asyncio.sleep(0)
                evaluate.assert_not_called()
            async def is_user_authorized(self):
                evaluate.assert_not_called()
                return True
            async def get_me(self):
                evaluate.assert_not_called()
                return SimpleNamespace(id=owner)
            async def disconnect(self):
                if task:
                    task.cancel()

        self_test = self
        row = [None] * 15
        row[8] = 'session'
        row[10] = 0
        with patch.object(sm, 'get_user_full', return_value=row), \
             patch.object(sm, 'decrypt_session', return_value='unused'), \
             patch.object(sm, 'StringSession', return_value=object()), \
             patch.object(sm, 'TelegramClient', FakeClient), \
             patch.object(sm, 'instrument_telethon_client'), \
             patch.object(sm, 'set_session_status'), \
             patch.object(sm, '_resolve_owner_groups', new_callable=AsyncMock), \
             patch.object(sm, 'evaluate', evaluate), patch.object(sm, '_log_skip'):
            try:
                self.assertTrue(await sm._start_user_client(owner))
                await task
                evaluate.assert_called_once()
            finally:
                sm._clients.pop(owner, None)
                sm._last_session_notice.pop(owner, None)

    async def test_mismatched_account_does_not_process_waiting_message(self):
        owner = 123457
        event = SimpleNamespace(is_private=False, chat_id=-100123, raw_text='message',
                                message=SimpleNamespace(sticker=None, noforwards=False),
                                id=1, out=False)
        evaluate = unittest.mock.Mock()
        task = None

        class FakeClient:
            def __init__(self, *args): self.handler = None
            def on(self, builder):
                def register(fn):
                    self.handler = fn
                    return fn
                return register
            async def connect(self):
                nonlocal task
                task = asyncio.create_task(self.handler(event))
                await asyncio.sleep(0)
            async def is_user_authorized(self): return True
            async def get_me(self): return SimpleNamespace(id=999)
            async def disconnect(self):
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        row = [None] * 15
        row[8] = 'session'
        row[10] = 0
        with patch.object(sm, 'get_user_full', return_value=row), \
             patch.object(sm, 'decrypt_session', return_value='unused'), \
             patch.object(sm, 'StringSession', return_value=object()), \
             patch.object(sm, 'TelegramClient', FakeClient), \
             patch.object(sm, 'instrument_telethon_client'), \
             patch.object(sm, 'set_session_status'), \
             patch.object(sm, '_notify_session_problem', new_callable=AsyncMock), \
             patch.object(sm, 'evaluate', evaluate):
            self.assertFalse(await sm._start_user_client(owner))
            evaluate.assert_not_called()
            self.assertNotIn(owner, sm._clients)


if __name__ == '__main__':
    unittest.main()
