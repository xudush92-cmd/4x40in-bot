"""Kod faqat tugmada: tez bosishlar, tartib, bitta yuborish."""
import asyncio
import os
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
import bot


class TestKeypad(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.storage = MemoryStorage()
        self.state = FSMContext(self.storage, StorageKey(bot_id=1, chat_id=42, user_id=42))
        await self.state.set_state(bot.Registration.code)
        await self.state.update_data(code_buffer='', code_length=5, phone='+998900000000', code_message_id=10)
        self.message = SimpleNamespace(message_id=10, edit_text=AsyncMock(),
                                       answer=AsyncMock(return_value=SimpleNamespace(message_id=10)))

    async def asyncTearDown(self):
        await bot._stop_code_render(42)
        await self.storage.close()

    def cb(self, action):
        return SimpleNamespace(from_user=SimpleNamespace(id=42), data='code:' + action,
                               message=self.message, answer=AsyncMock())

    async def test_rapid_order_coalesces_and_never_renders_code(self):
        callbacks = [self.cb(n) for n in '12345']
        await asyncio.gather(*(bot.code_numpad(c, self.state) for c in callbacks))
        self.assertEqual((await self.state.get_data())['code_buffer'], '12345')
        for c in callbacks: c.answer.assert_awaited_once()
        self.assertEqual(self.message.edit_text.await_count, 0)
        task = bot._code_render_tasks[42]
        await task
        self.message.edit_text.assert_awaited_once()
        text = self.message.edit_text.await_args.args[0]
        self.assertIn('●●●●●', text)
        self.assertNotIn('12345', text)

    async def test_slow_screen_edit_does_not_block_more_digits(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow_edit(*args, **kwargs):
            started.set()
            await release.wait()
        self.message.edit_text.side_effect = slow_edit
        await bot.code_numpad(self.cb('1'), self.state)
        await asyncio.wait_for(started.wait(), timeout=2)
        await asyncio.wait_for(bot.code_numpad(self.cb('2'), self.state), timeout=1)
        self.assertEqual((await self.state.get_data())['code_buffer'], '12')
        release.set()
        await bot._code_render_tasks[42]
        self.assertEqual(self.message.edit_text.await_count, 2)
        self.assertIn('●●○○○', self.message.edit_text.await_args.args[0])

    async def test_exact_length_back_and_single_submission(self):
        for n in '1234': await bot.code_numpad(self.cb(n), self.state)
        incomplete = self.cb('ok')
        await bot.code_numpad(incomplete, self.state)
        self.assertTrue(incomplete.answer.await_args.kwargs['show_alert'])
        await bot.code_numpad(self.cb('back'), self.state)
        for n in '456': await bot.code_numpad(self.cb(n), self.state)
        self.assertEqual((await self.state.get_data())['code_buffer'], '12345')
        with patch.object(bot, '_try_code', new_callable=AsyncMock) as verify:
            await asyncio.gather(bot.code_numpad(self.cb('ok'), self.state),
                                 bot.code_numpad(self.cb('ok'), self.state))
        verify.assert_awaited_once_with(self.message, self.state, 42, '12345')
        self.assertEqual(await self.state.get_state(), bot.Registration.verifying.state)
        self.assertEqual((await self.state.get_data())['code_buffer'], '')

    async def test_cancel_cleans_up_and_old_callback_does_not_append(self):
        await bot.code_numpad(self.cb('1'), self.state)
        with patch.object(bot, 'login_cleanup', new_callable=AsyncMock) as cleanup:
            await bot.code_numpad(self.cb('cancel'), self.state)
        cleanup.assert_awaited_once_with(42)
        await bot.code_numpad(self.cb('2'), self.state)
        self.assertIsNone(await self.state.get_state())
        self.assertEqual(await self.state.get_data(), {})
        self.assertNotIn(42, bot._code_render_tasks)

    async def test_wrong_code_reenables_input(self):
        await self.state.set_state(bot.Registration.verifying)
        with patch.object(bot, 'sign_in_code', new_callable=AsyncMock, return_value=('wrong', None, None)):
            await bot._try_code(self.message, self.state, 42, '12345')
        self.assertEqual(await self.state.get_state(), bot.Registration.code.state)
        await bot.code_numpad(self.cb('7'), self.state)
        self.assertEqual((await self.state.get_data())['code_buffer'], '7')

    async def test_old_keypad_cannot_write_into_new_login(self):
        old = self.cb('4')
        old.message = SimpleNamespace(message_id=9, edit_text=AsyncMock())
        await bot.code_numpad(old, self.state)
        self.assertEqual((await self.state.get_data())['code_buffer'], '')
        old.message.edit_text.assert_not_awaited()

    async def test_code_text_is_deleted_not_submitted(self):
        msg = SimpleNamespace(text='12345', delete=AsyncMock(),
                              answer=AsyncMock(return_value=SimpleNamespace(message_id=11)))
        with patch.object(bot, '_try_code', new_callable=AsyncMock) as verify:
            await bot.code_as_text(msg, self.state)
        msg.delete.assert_awaited_once()
        verify.assert_not_awaited()
        self.assertNotIn('12345', str(msg.answer.await_args_list))


if __name__ == '__main__': unittest.main()
