import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('ADMIN_ID', '777')
os.environ.setdefault('API_ID', '1')
os.environ.setdefault('API_HASH', 'x')
os.environ.setdefault('BOT_TOKEN', '1:x')

from keyword_audit import build_keyword_audit
import bot


class TestKeywordAudit(unittest.TestCase):
    def test_weighted_audit_uses_actual_matcher_and_reports_every_entry(self):
        entries = [('odam bor', 3.0, 0), ('odamkk', -5.0, 0), ('pochta', 1.0, 0)]
        report = build_keyword_audit(entries, 'weight', 3, 1)
        self.assertIn('Jami namuna: 3', report)
        self.assertIn('Namuna: odam bor', report)
        self.assertIn('Manfiy: odamkk (-5)', report)
        self.assertIn('Ball: -2/3', report)
        self.assertIn('DIQQAT: musbat namuna', report)
        self.assertIn('Namuna: odamkk', report)
        self.assertIn('Namuna: pochta', report)
        self.assertEqual(entries[0], ('odam bor', 3.0, 0))

    def test_strict_negative_does_not_match_other_sample(self):
        report = build_keyword_audit([('odam bor', 3., 0), ('odamkk', -5., 1)], 'weight', 3, 1)
        first = report.split('2. Namuna:')[0]
        self.assertIn('Manfiy: yoq', first)
        self.assertIn('Ball: 3/3', first)

    def test_count_mode_and_empty(self):
        report = build_keyword_audit([('mashina', 2., 0), ('kerak', -4., 0)], 'count', 3, 2)
        self.assertIn('Son rejimida manfiy ball', report)
        self.assertIn('Topildi: 1/2', report)
        self.assertIn('Jami namuna: 0', build_keyword_audit([], 'weight', 3, 1))


class TestAuditHandler(unittest.IsolatedAsyncioTestCase):
    async def test_private_admin_gets_document(self):
        msg = SimpleNamespace(chat=SimpleNamespace(type='private', id=777), answer=AsyncMock(), answer_document=AsyncMock())
        cb = SimpleNamespace(message=msg, from_user=SimpleNamespace(id=777), answer=AsyncMock())
        with patch.object(bot, 'get_keywords_weighted', return_value=[('odam bor', 3., 0)]), \
             patch.object(bot, 'get_match_mode', return_value='weight'), \
             patch.object(bot, 'get_user_score_threshold', return_value=3.), \
             patch.object(bot, 'get_user_match_count', return_value=1):
            await bot.words_audit(cb)
        msg.answer_document.assert_awaited_once()
        self.assertEqual(msg.answer_document.await_args.args[0].filename, 'kalitlar-tekshiruvi.txt')

    async def test_group_never_receives_report(self):
        msg = SimpleNamespace(chat=SimpleNamespace(type='supergroup', id=-123), answer=AsyncMock(), answer_document=AsyncMock())
        cb = SimpleNamespace(message=msg, from_user=SimpleNamespace(id=777), answer=AsyncMock())
        await bot.words_audit(cb)
        msg.answer_document.assert_not_awaited()
        self.assertTrue(cb.answer.await_args.kwargs['show_alert'])


if __name__ == '__main__':
    unittest.main()
