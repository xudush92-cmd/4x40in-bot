import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('ADMIN_ID', '777')
os.environ.setdefault('API_ID', '1')
os.environ.setdefault('API_HASH', 'x')
os.environ.setdefault('BOT_TOKEN', '1:x')
import scanner_manager as manager


class SessionHealthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clients = patch.dict(manager._clients, {}, clear=True)
        self.clients.start()
        self.states = patch.dict(manager._session_health_states, {}, clear=True)
        self.states.start()
        self.version = patch.object(manager, 'TELETHON_VERSION', '1.34.0')
        self.version.start()

    async def asyncTearDown(self):
        self.version.stop()
        self.states.stop()
        self.clients.stop()

    async def test_running_stopped_disconnect_and_unsupported_version(self):
        future = asyncio.get_running_loop().create_future()
        client = SimpleNamespace(is_connected=lambda: True, _updates_handle=future)
        self.assertEqual(manager._session_health(client), ('connected', 'running'))
        future.set_result(None)
        self.assertEqual(manager._session_health(client), ('connected', 'stopped'))
        client.is_connected = lambda: False
        self.assertEqual(manager._session_health(client), ('disconnected', 'stopped'))
        with patch.object(manager, 'TELETHON_VERSION', '1.99'):
            self.assertEqual(manager._session_health(client), ('disconnected', 'unknown'))
        client.is_connected = Mock(side_effect=RuntimeError('secret'))
        self.assertEqual(manager._session_health(client), ('unknown', 'stopped'))

    async def test_sample_records_only_transitions_and_removes_departed_owner(self):
        future = asyncio.get_running_loop().create_future()
        client = SimpleNamespace(is_connected=lambda: True, _updates_handle=future)
        manager._clients[123] = client
        record = Mock()
        with patch.object(manager.scan_delay_diagnostics, 'record_session_health', record):
            manager._sample_session_health()
            manager._sample_session_health()
            self.assertEqual(record.call_count, 1)
            record.assert_called_with(123, connection='connected', update_loop='running')
            future.set_result(None)
            manager._sample_session_health()
            self.assertEqual(record.call_count, 2)
            record.assert_called_with(123, connection='connected', update_loop='stopped')
            manager._clients[123] = SimpleNamespace(is_connected=lambda: True, _updates_handle=future)
            manager._sample_session_health()
            self.assertEqual(record.call_count, 3)
            del manager._clients[123]
            manager._sample_session_health()
            self.assertNotIn(123, manager._session_health_states)

    async def test_diagnostics_failure_does_not_change_client(self):
        future = asyncio.get_running_loop().create_future()
        client = SimpleNamespace(is_connected=lambda: True, _updates_handle=future)
        manager._clients[123] = client
        with patch.object(manager.scan_delay_diagnostics, 'record_session_health', side_effect=RuntimeError('secret message')):
            manager._sample_session_health()
        self.assertIs(manager._clients[123], client)
        self.assertFalse(future.done())
        future.cancel()

    async def test_unknown_without_real_future(self):
        client = SimpleNamespace(is_connected=lambda: True, _updates_handle=object())
        self.assertEqual(manager._session_health(client), ('connected', 'unknown'))


if __name__ == '__main__':
    unittest.main()
