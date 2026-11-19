"""Keraksiz deb baholangan bildirishnomani adminga yuborish testlari."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_db.close()
os.environ['SCANNER_DB_PATH'] = _db.name
os.environ.setdefault('ADMIN_ID', '777')
os.environ.setdefault('API_ID', '1')
os.environ.setdefault('API_HASH', 'x')
os.environ.setdefault('BOT_TOKEN', '1:x')

import bot
import database as db
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def setUpModule():
    db.init_db()


def tearDownModule():
    os.unlink(_db.name)


class TestFeedbackAdmin(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.owner = 12345
        self.rid = db.save_lead_review(self.owner, ['mashina kerak'])
        self.markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='Asl xabar', url='https://t.me/example/123')],
            [InlineKeyboardButton(text='Keraksiz', callback_data=f'fb:{self.rid}:0')],
        ])
        self.message = SimpleNamespace(
            chat=SimpleNamespace(id=self.owner, type='private'),
            message_id=234,
            text='🚕 YANGI BUYURTMA / MIJOZ TOPILDI!\nXabar matni',
            reply_markup=self.markup,
            edit_reply_markup=AsyncMock(), answer=AsyncMock(),
        )
        self.api = SimpleNamespace(
            copy_message=AsyncMock(return_value=SimpleNamespace(message_id=123)),
            send_message=AsyncMock(),
        )
        self.cb = SimpleNamespace(
            data=f'fb:{self.rid}:0', from_user=SimpleNamespace(id=self.owner, full_name='Ali <Vali>'),
            message=self.message, bot=self.api, answer=AsyncMock(),
        )

    async def test_useless_sends_copy_once_and_keeps_source_link(self):
        await bot.feedback_callback(self.cb)
        self.api.copy_message.assert_awaited_once_with(
            chat_id=bot.ADMIN_ID, from_chat_id=self.owner, message_id=234)
        kwargs = self.api.send_message.await_args.kwargs
        self.assertEqual(kwargs['reply_to_message_id'], 123)
        self.assertIn('Ali &lt;Vali&gt;', self.api.send_message.await_args.args[1])
        markup = self.message.edit_reply_markup.await_args.kwargs['reply_markup']
        self.assertEqual(markup.inline_keyboard[0][0].url, 'https://t.me/example/123')
        self.assertEqual(len(markup.inline_keyboard), 1)
        self.assertIn('adminga yuborildi', self.message.answer.await_args.args[0])
        await bot.feedback_callback(self.cb)
        self.assertEqual(self.api.copy_message.await_count, 1)

    async def test_useful_does_not_send_to_admin(self):
        self.cb.data = f'fb:{self.rid}:1'
        await bot.feedback_callback(self.cb)
        self.api.copy_message.assert_not_awaited()
        self.api.send_message.assert_not_awaited()

    async def test_failed_copy_is_reported_and_vote_is_preserved(self):
        self.api.copy_message.side_effect = RuntimeError('offline')
        await bot.feedback_callback(self.cb)
        self.assertIn('Adminga to‘liq yuborib bo‘lmadi', self.message.answer.await_args.args[0])
        self.assertTrue(db.get_lead_review(self.rid)[3])
        self.api.send_message.assert_not_awaited()

    async def test_other_user_cannot_vote_or_send_copy(self):
        self.cb.from_user.id = 54321
        await bot.feedback_callback(self.cb)
        self.api.copy_message.assert_not_awaited()
        self.assertFalse(db.get_lead_review(self.rid)[3])

    async def test_protected_or_non_owner_chat_never_copied(self):
        self.message.text = 'HIMOYALANGAN GURUHDA MOS MATN TOPILDI'
        await bot.feedback_callback(self.cb)
        self.api.copy_message.assert_not_awaited()
        self.assertIn('Adminga to‘liq yuborib bo‘lmadi', self.message.answer.await_args.args[0])

    async def test_foreign_chat_is_not_copied(self):
        self.message.chat.id = 54321
        await bot.feedback_callback(self.cb)
        self.api.copy_message.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
