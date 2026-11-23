"""Registratsiya yozuvi va shifrlangan pending sessiya haqiqatan saqlanishi."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('ADMIN_ID', '777')
os.environ.setdefault('API_ID', '1')
os.environ.setdefault('API_HASH', 'x')
os.environ.setdefault('BOT_TOKEN', '1:x')

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
import database as db
import bot


class RegistrationStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, 'DB_NAME', os.path.join(self.tmp.name, 'test.db'))
        self.db_patch.start()
        db.init_db()
        self.storage = MemoryStorage()
        self.state = FSMContext(self.storage, StorageKey(bot_id=1, chat_id=42, user_id=42))
        self.user = SimpleNamespace(id=42, first_name='Ali', username='ali_test')
        self.msg = SimpleNamespace(from_user=self.user, text='', answer=AsyncMock(), delete=AsyncMock())
        self.client = SimpleNamespace(session=SimpleNamespace(save=lambda: 'SESSION_SECRET'), disconnect=AsyncMock())
        self.admin_bot = SimpleNamespace(send_message=AsyncMock())

    async def asyncTearDown(self):
        await self.storage.close()
        self.db_patch.stop()
        self.tmp.cleanup()

    async def test_missing_user_created_before_input_and_full_flow(self):
        with patch.object(bot, 'login_cleanup', new_callable=AsyncMock):
            await bot.begin_login(self.msg, self.state)
        self.assertIsNotNone(db.get_user_full(42))
        self.msg.text = 'Ali Valiyev'
        await bot.reg_full_name(self.msg, self.state)
        self.msg.text = '+998901234567'
        self.msg.answer.return_value = SimpleNamespace(message_id=10)
        with patch.object(bot, 'request_code', new_callable=AsyncMock, return_value=5):
            await bot.reg_phone(self.msg, self.state)
        self.assertEqual(await self.state.get_state(), bot.Registration.code.state)
        me = SimpleNamespace(id=42, phone='998901234567')
        with patch.object(bot, 'sign_in_code', new_callable=AsyncMock, return_value=('ok', self.client, me)), \
             patch.object(bot, 'take_signed_client', return_value=self.client), patch.object(bot, 'bot', self.admin_bot):
            await bot._try_code(self.msg, self.state, 42, '12345')
        row = db.get_user_full(42)
        self.assertEqual(row[6:8], ('Ali Valiyev', '+998901234567'))
        self.assertTrue(row[9])
        self.assertEqual(row[10], 1)
        self.assertNotIn('SESSION_SECRET', row[9])
        self.admin_bot.send_message.assert_awaited_once()
        notice = self.admin_bot.send_message.await_args.args[1]
        self.assertIn('Ali Valiyev', notice)
        self.assertNotIn('SESSION_SECRET', notice)
        self.client.disconnect.assert_awaited_once()

    async def test_deleted_user_never_reports_success_or_sends_admin_notice(self):
        db.ensure_user_exists(42)
        db.set_registration_info(42, 'Ali Valiyev', '+998901234567')
        await self.state.update_data(phone='+998901234567')
        db.delete_user_completely(42)
        with patch.object(bot, 'take_signed_client', return_value=self.client), patch.object(bot, 'bot', self.admin_bot):
            await bot._complete_signed_in(self.msg, self.state, 42)
        self.admin_bot.send_message.assert_not_awaited()
        self.assertIn('sessiyani saqlab bo', self.msg.answer.await_args.args[0])
        self.assertNotIn('muvaffaqiyatli', str(self.msg.answer.await_args_list))
        self.assertNotIn('SESSION_SECRET', str(self.msg.answer.await_args_list))
        self.client.disconnect.assert_awaited_once()
        self.assertIsNone(db.get_user_full(42))

    async def test_missing_row_at_name_or_phone_stops_before_telegram_request(self):
        self.msg.text = 'Ali Valiyev'
        await bot.reg_full_name(self.msg, self.state)
        self.assertIn('saqlanmadi', self.msg.answer.await_args.args[0])
        self.msg.text = '+998901234567'
        with patch.object(bot, 'request_code', new_callable=AsyncMock) as request:
            await bot.reg_phone(self.msg, self.state)
        request.assert_not_awaited()
        self.assertIn('saqlanmadi', self.msg.answer.await_args.args[0])

    def test_pending_write_rejects_missing_blocked_active_and_conflicting_phone(self):
        self.assertFalse(db.set_pending_session(42, 'encrypted', expected_phone='+998901234567'))
        db.ensure_user_exists(42)
        self.assertFalse(db.set_pending_session(42, 'encrypted'))
        db.set_registration_info(42, 'Ali Valiyev', '+998901234567')
        self.assertFalse(db.set_pending_session(42, 'encrypted', expected_phone='+998901234568'))
        db.set_user_blocked(42, True)
        self.assertFalse(db.set_pending_session(42, 'encrypted'))
        db.ensure_user_exists(42)
        self.assertTrue(db.get_user(42)[3])
        db.set_user_blocked(42, False)
        self.assertTrue(db.set_pending_session(42, 'first', expected_phone='+998901234567'))
        self.assertFalse(db.set_pending_session(42, 'second'))
        self.assertEqual(db.get_user_full(42)[9], 'first')
        self.assertTrue(db.approve_pending_session(42))
        self.assertFalse(db.set_pending_session(42, 'third'))
        self.assertEqual(db.get_user_full(42)[8], 'first')

    async def test_code_free_login_still_validates_identity(self):
        db.ensure_user_exists(42)
        db.set_registration_info(42, 'Ali Valiyev', '+998901234567')
        with patch.object(bot, 'login_cleanup', new_callable=AsyncMock) as cleanup, \
             patch.object(bot, 'request_code', new_callable=AsyncMock, return_value=0), \
             patch.object(bot, 'sign_in_code', new_callable=AsyncMock, return_value=('ok', self.client, SimpleNamespace(id=99, phone='998901234567'))), \
             patch.object(bot, '_complete_signed_in', new_callable=AsyncMock) as complete:
            await bot.begin_login(self.msg, self.state)
        complete.assert_not_awaited()
        self.assertEqual(cleanup.await_count, 2)
        self.assertFalse(db.get_user_full(42)[9])
        self.assertIn('mos', self.msg.answer.await_args.args[0])

    async def test_database_write_error_does_not_claim_success(self):
        await self.state.update_data(phone='+998901234567')
        with patch.object(bot, 'take_signed_client', return_value=self.client), \
             patch.object(bot, 'set_pending_session', side_effect=RuntimeError('SECRET')), \
             patch.object(bot, 'bot', self.admin_bot):
            await bot._complete_signed_in(self.msg, self.state, 42)
        self.admin_bot.send_message.assert_not_awaited()
        self.assertNotIn('muvaffaqiyatli', str(self.msg.answer.await_args_list))
        self.assertNotIn('SECRET', str(self.msg.answer.await_args_list))
        self.client.disconnect.assert_awaited_once()


if __name__ == '__main__': unittest.main()
