import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('ADMIN_ID', '777')
os.environ.setdefault('API_ID', '1')
os.environ.setdefault('API_HASH', 'x')
os.environ.setdefault('BOT_TOKEN', '1:x')
import bot


def group(i, owner=777, value=None, title=None, active=1, status='ok', error=''):
    return (i, owner, value or f'@group_{i:05d}', -1000000000000 - i,
            title or f'Guruh {i}', active, status, error)


def callback(data, uid=777, chat_id=None, chat_type='private'):
    msg = SimpleNamespace(chat=SimpleNamespace(type=chat_type, id=uid if chat_id is None else chat_id), edit_text=AsyncMock(), answer=AsyncMock())
    return SimpleNamespace(data=data, from_user=SimpleNamespace(id=uid), message=msg, answer=AsyncMock())


class GroupListTests(unittest.TestCase):
    def test_links_pagination_and_status(self):
        groups = [group(i) for i in range(1, 11)]
        groups[1] = group(2, active=0)
        groups[2] = group(3, status='left')
        text, keyboard = bot._group_list_page(groups, 0)
        self.assertIn('10 ta</b> (faol: 8)', text)
        self.assertIn('<a href="https://t.me/group_00001">Guruh 1</a>', text)
        self.assertIn('2. ⏸', text)
        self.assertIn('3. 🚪', text)
        self.assertNotIn('Guruh 9', text)
        self.assertTrue(any(b.callback_data == 'ugl:page:1' for row in keyboard.inline_keyboard for b in row))
        text, _ = bot._group_list_page(groups, 1)
        self.assertIn('9. ✅', text)
        self.assertIn('10. ✅', text)

    def test_invite_not_exposed_or_used_as_link(self):
        row = group(1, value='https://t.me/+secretInvite', title='Maxfiy')
        text, _ = bot._group_list_page([row], 0)
        self.assertNotIn('secretInvite', text)
        self.assertNotIn('<a href=', text)
        self.assertIn('Maxfiy', text)
        self.assertNotIn('secretInvite', bot._user_group_text((1, 777, 'https://t.me/+secretInvite', None, '', 1, 'ok', '')))

    def test_escape_and_clamp(self):
        text, _ = bot._group_list_page([group(1, title='<b>X</b>')], 50)
        self.assertIn('&lt;b&gt;X&lt;/b&gt;', text)
        self.assertIn('1/1', text)
        text, _ = bot._group_list_page([], 2)
        self.assertIn('bo\'sh', text)


class GroupActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_and_user_list_send_one_message(self):
        for handler in (bot.admin_list_groups, bot.user_list_groups):
            msg = SimpleNamespace(from_user=SimpleNamespace(id=777), answer=AsyncMock())
            state = SimpleNamespace(clear=AsyncMock())
            with patch.object(bot, 'get_user_groups', return_value=[group(i) for i in range(1, 25)]):
                await handler(msg, state)
            msg.answer.assert_awaited_once()
            self.assertIn('24 ta', msg.answer.await_args.args[0])

    async def test_ask_does_not_delete(self):
        cb = callback('ugl:ask:4:0')
        with patch.object(bot, 'get_user_group', return_value=group(4)), patch.object(bot, 'delete_user_group') as delete:
            await bot.group_list_action(cb, SimpleNamespace())
        delete.assert_not_called()
        markup = cb.message.edit_text.await_args.kwargs['reply_markup']
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, 'ugl:delete:4:0')

    async def test_confirm_owner_delete_and_refresh(self):
        cb = callback('ugl:delete:4:0')
        with patch.object(bot, 'get_user_group', return_value=group(4)), patch.object(bot, 'delete_user_group') as delete, patch.object(bot, 'get_user_groups', return_value=[]):
            await bot.group_list_action(cb, SimpleNamespace())
        delete.assert_called_once_with(4, 777)
        self.assertIn("bo'sh", cb.message.edit_text.await_args.args[0])

    async def test_cannot_delete_another_users_group(self):
        cb = callback('ugl:delete:4:0')
        with patch.object(bot, 'get_user_group', return_value=group(4, owner=888)), patch.object(bot, 'delete_user_group') as delete:
            await bot.group_list_action(cb, SimpleNamespace())
        delete.assert_not_called()
        self.assertTrue(cb.answer.await_args.kwargs['show_alert'])

    async def test_group_chat_cannot_access_list(self):
        cb = callback('ugl:page:0', chat_id=-123, chat_type='supergroup')
        with patch.object(bot, 'get_user_groups') as get:
            await bot.group_list_action(cb, SimpleNamespace())
        get.assert_not_called()

    async def test_retry_and_page(self):
        cb = callback('ugl:retry:4:0')
        with patch.object(bot, 'get_user_group', return_value=group(4, status='error')), patch.object(bot, 'requeue_user_group') as retry, patch.object(bot, 'get_user_groups', return_value=[group(4, status='pending')]):
            await bot.group_list_action(cb, SimpleNamespace())
        retry.assert_called_once_with(4)
        self.assertIn('⏳', cb.message.edit_text.await_args.args[0])

    async def test_bad_callback_does_not_delete(self):
        cb = callback('ugl:delete:bad:0')
        with patch.object(bot, 'delete_user_group') as delete:
            await bot.group_list_action(cb, SimpleNamespace())
        delete.assert_not_called()


if __name__ == '__main__':
    unittest.main()
