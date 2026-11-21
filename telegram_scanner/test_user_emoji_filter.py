"""Shaxsiy emoji/stiker filtri, migratsiya va menyu testlari."""
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

import database as db
import filters
import bot


class UserEmojiFilterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, 'DB_NAME', os.path.join(self.tmp.name, 'test.db'))
        self.db_patch.start()
        db.init_db()
        db.upsert_user(100, 'First')
        db.upsert_user(200, 'Second')
        with db.closing(db._connect()) as conn, conn:
            conn.execute('UPDATE users SET sub_expires_at=?', (int(time.time()) + 86400,))
            for uid in (100, 200):
                conn.execute("INSERT INTO user_groups (owner_user_id,input_value,chat_id,is_active,status) VALUES (?, ?, -100123, 1, 'ok')", (uid, '@test'))
        db.set_setting('match_count', '1')
        db.add_keyword_checked('kerak', weight=3)

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_defaults_and_isolation_with_count_and_weight(self):
        for mode in ('count', 'weight'):
            db.set_match_mode(mode)
            db.set_user_emoji_sticker_filter(100, True)
            for sticker, text in ((False, '🚕 taksi kerak'), (True, 'taksi kerak')):
                self.assertEqual(filters.evaluate(100, text, is_sticker=sticker, chat_id=-100123).stage, 'emoji')
                db.set_user_emoji_sticker_filter(100, False)
                self.assertTrue(filters.evaluate(100, text, is_sticker=sticker, chat_id=-100123).ok)
                self.assertEqual(filters.evaluate(200, text, is_sticker=sticker, chat_id=-100123).stage, 'emoji')
                db.set_user_emoji_sticker_filter(100, True)
            db.set_user_emoji_sticker_filter(100, False)
            self.assertEqual(filters.evaluate(100, '🚕 tasodifiy', chat_id=-100123).stage, 'keywords')
            self.assertEqual(filters.evaluate(100, '', is_sticker=True, chat_id=-100123).stage, 'keywords')
            self.assertEqual(filters.evaluate(100, '🚕 kerak', chat_id=-999).stage, 'group')
        db.set_user_emoji_sticker_filter(100, True)
        self.assertEqual(filters.evaluate(100, '🚕 kerak', chat_id=-100123).stage, 'emoji')

    def test_persistence_missing_user_and_delete(self):
        self.assertTrue(db.get_user_emoji_sticker_filter(777))
        db.set_user_emoji_sticker_filter(777, False)
        db.init_db()
        self.assertFalse(db.get_user_emoji_sticker_filter(777))
        self.assertTrue(db.get_user_emoji_sticker_filter(200))
        db.delete_user_completely(777)
        self.assertTrue(db.get_user_emoji_sticker_filter(777))

    def test_legacy_database_migration_preserves_users_and_defaults(self):
        legacy = os.path.join(self.tmp.name, 'legacy.db')
        with patch.object(db, 'DB_NAME', legacy):
            with db.closing(db._connect()) as conn, conn:
                conn.execute('CREATE TABLE users (user_id INTEGER PRIMARY KEY, first_name TEXT, username TEXT, is_blocked INTEGER DEFAULT 0, sub_expires_at INTEGER DEFAULT 0, created_at INTEGER DEFAULT 0)')
                conn.execute("INSERT INTO users (user_id, first_name) VALUES (300, 'Old')")
            db.init_db()
            self.assertEqual(db.get_user(300)[1], 'Old')
            self.assertTrue(db.get_user_emoji_sticker_filter(300))

    async def test_menu_and_callback_are_personal(self):
        self.assertIn(bot.BTN_EMOJI_FILTER, [b.text for row in bot.user_menu_keyboard() for b in row])
        self.assertIn(bot.BTN_EMOJI_FILTER, [b.text for row in bot.scan_panel_keyboard(777) for b in row])
        cb = SimpleNamespace(data='emoji_filter:off', from_user=SimpleNamespace(id=100),
            message=SimpleNamespace(chat=SimpleNamespace(id=100, type='private'), edit_text=AsyncMock()), answer=AsyncMock())
        await bot.user_emoji_filter_change(cb)
        self.assertFalse(db.get_user_emoji_sticker_filter(100))
        self.assertTrue(db.get_user_emoji_sticker_filter(200))
        cb.data = 'emoji_filter:on'
        cb.message.chat.id = 200
        await bot.user_emoji_filter_change(cb)
        self.assertFalse(db.get_user_emoji_sticker_filter(100))
        cb.message.chat.id = 100
        await bot.user_emoji_filter_change(cb)
        self.assertTrue(db.get_user_emoji_sticker_filter(100))


if __name__ == '__main__':
    unittest.main()
