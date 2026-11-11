"""Status text and warning delivery regression tests (isolated temporary DB)."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_db.close()
os.environ['SCANNER_DB_PATH'] = _db.name
os.environ.setdefault('ADMIN_ID', '777')
os.environ.setdefault('API_ID', '1')
os.environ.setdefault('API_HASH', 'x')
os.environ.setdefault('BOT_TOKEN', '1:x')

import bot
import database
import filters
import scanner_manager as sm


class TestStatusText(unittest.TestCase):
    def test_filter_report_does_not_promise_delivery_or_group_check(self):
        verdict = filters.Verdict(ok=True, mode='weight', required=5)
        with patch.object(filters, 'evaluate', return_value=verdict) as evaluate, \
             patch.object(bot, '_session_block_note', return_value=None), \
             patch.object(bot, '_scan_diag_lines', return_value=[]):
            report = bot.scan_test_report(777, 'namuna')
        evaluate.assert_called_once_with(777, 'namuna', check_group=False)
        self.assertIn('filtrdan O‘TDI', report)
        self.assertIn('Guruhga tegishlilik', report)
        self.assertNotIn('xabar KELADI', report)
        self.assertNotIn('Shart juda yuqori', report)

    def test_zero_events_does_not_assert_cause(self):
        with patch.object(sm, 'scan_diagnostics', return_value={
            'client': True, 'connected': True, 'events': 0, 'watched': []
        }):
            text = '\n'.join(bot._scan_diag_lines(777))
        self.assertIn('bo‘lmagan bo‘lishi mumkin', text)
        self.assertNotIn('bildirishnomalar o\'chirilgan', text)

    def test_account_and_scanner_status_show_weight_mode(self):
        row = (777, 'Ali', None, 0, 0, 0, 'Ali', None, 'session', None, 0, 'ok', None, 0, 1)
        with patch.object(bot, 'get_user_full', return_value=row), \
             patch.object(bot, 'get_match_mode', return_value='weight'), \
             patch.object(bot, 'get_user_score_threshold', return_value=2.5), \
             patch.object(bot, 'get_score_threshold', return_value=1.75), \
             patch.object(bot, 'get_all_user_groups', return_value=[]), \
             patch.object(bot, 'get_keywords', return_value=[]), \
             patch.object(bot, 'get_setting', return_value='1'):
            self.assertIn('Ball chegarasi: <b>2.5</b>', bot.account_status_text(777))
            self.assertIn('Standart ball chegarasi: <b>1.75</b>', bot.scanner_status_text())


class TestWarningDelivery(unittest.IsolatedAsyncioTestCase):
    async def test_session_failure_retries_and_success_starts_cooldown(self):
        owner = 123456789
        sm._last_session_notice.pop(owner, None)
        sm._last_session_notice_attempt.pop(owner, None)
        send = AsyncMock(side_effect=[False, True])
        with patch.object(sm, 'send_to_bot_api', send), patch.object(sm.time, 'time', return_value=10000) as clock:
            await sm._notify_session_problem(owner, invalid=True)
            self.assertNotIn(owner, sm._last_session_notice)
            await sm._notify_session_problem(owner, invalid=True)
            self.assertEqual(send.await_count, 1)
            clock.return_value += sm._SESSION_NOTICE_RETRY
            await sm._notify_session_problem(owner, invalid=True)
            self.assertIn(owner, sm._last_session_notice)
            clock.return_value += sm._SESSION_NOTICE_RETRY
            await sm._notify_session_problem(owner, invalid=True)
            self.assertEqual(send.await_count, 2)
        sm._last_session_notice.pop(owner, None)
        sm._last_session_notice_attempt.pop(owner, None)

    async def test_expiry_marks_only_success_and_continues_after_error(self):
        rows = []
        for uid in (1, 2, 3):
            row = [None] * 15
            row[0], row[4], row[12] = uid, 9999999999, None
            rows.append(row)
        sender = AsyncMock(side_effect=[False, RuntimeError('offline'), True])
        with patch.object(database, 'get_expiring_users', return_value=rows), \
             patch.object(sm, 'mark_warned_today') as mark:
            await sm._send_expiry_warnings(sender)
        self.assertEqual(sender.await_count, 3)
        mark.assert_called_once_with(3)


if __name__ == '__main__':
    unittest.main()
