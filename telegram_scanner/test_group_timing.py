"""Opt-in guruh diagnostikasi maxfiyligi va bosqich o'lchovlari."""
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('ADMIN_ID', '777')
os.environ.setdefault('API_ID', '1')
os.environ.setdefault('API_HASH', 'x')
os.environ.setdefault('BOT_TOKEN', '1:x')

from scan_diagnostics import GroupTimingDiagnostics, parse_group_timing_pairs, group_timing_configuration
from group_timing_report import summarize, percentile
import scanner_manager as sm
from telethon.tl.types import PeerUser


class TestGroupConfiguration(unittest.TestCase):
    def test_configuration_is_off_by_default_strict_and_bounded(self):
        self.assertEqual(parse_group_timing_pairs(''), ())
        self.assertEqual(parse_group_timing_pairs('101:-1001,102:-1002'), ((101, -1001), (102, -1002)))
        self.assertEqual(parse_group_timing_pairs('101:-1001,broken'), ())
        self.assertEqual(parse_group_timing_pairs('101:123'), ())
        self.assertEqual(parse_group_timing_pairs(','.join(f'101:{-i}' for i in range(1, 12))), ())
        self.assertEqual(parse_group_timing_pairs('101:-1001,101:-1001'), ((101, -1001),))

    def test_group_timing_requires_short_expiry_and_stops_automatically(self):
        from unittest.mock import patch
        future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)).isoformat()
        with patch.dict(os.environ, {'SCANNER_GROUP_TIMING_PAIRS': '101:-1001',
                                     'SCANNER_GROUP_TIMING_UNTIL_UTC': future}):
            pairs, remaining = group_timing_configuration()
            self.assertEqual(pairs, ((101, -1001),))
            self.assertTrue(0 < remaining <= 1800)
        with patch.dict(os.environ, {'SCANNER_GROUP_TIMING_PAIRS': '101:-1001',
                                     'SCANNER_GROUP_TIMING_UNTIL_UTC': ''}):
            self.assertEqual(group_timing_configuration(), ((), 0.0))
        with tempfile.TemporaryDirectory() as directory:
            diag = GroupTimingDiagnostics(directory, [(101, -1001)], duration_seconds=0)
            self.assertFalse(diag.enabled(101, -1001))

    def test_whitelist_writes_only_selected_and_no_message_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            diag = GroupTimingDiagnostics(directory, [(900001, -1001)])
            now = dt.datetime.now(dt.timezone.utc)
            diag.evaluation(900001, -1002, 33, now, now, 2, 3, False, 'secret content')
            self.assertFalse(list(Path(directory).iterdir()))
            diag.evaluation(900001, -1001, 34, now - dt.timedelta(seconds=2), now, 2, 3, True, 'ok')
            diag.notification(900001, -1001, 34, now - dt.timedelta(seconds=2), now, 5, 7, True)
            path = Path(directory) / 'owner_900001.jsonl'
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([row['stage'] for row in rows], ['group_evaluation', 'group_notification'])
            self.assertEqual(rows[0]['source_to_receive_ms'], 2000)
            self.assertEqual(rows[1]['send_ms'], 7)
            for row in rows:
                self.assertFalse({'text', 'phone', 'sender', 'session', 'token', 'keyword', 'detail'} & row.keys())
            if os.name == 'posix':
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            # Truncated or bad records do not prevent offline report generation.
            with path.open('a') as f: f.write('{bad json\n')
            groups, times = summarize(Path(directory), now - dt.timedelta(hours=1), now + dt.timedelta(minutes=1))
            record = groups[(900001, -1001)]
            self.assertEqual(record['matched'], 1)
            self.assertEqual(record['attempts'], 1)
            self.assertEqual(record['source'], [2000])
            self.assertEqual(record['total'], [2012])
            self.assertEqual(len(times), 2)
            self.assertEqual(percentile([1, 2, 3], .95), 3)


class Client:
    def on(self, builder):
        def register(fn):
            self.handler = fn
            return fn
        return register


class TestGroupTimingHandler(unittest.IsolatedAsyncioTestCase):
    async def test_end_to_end_selected_only_and_send_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            diag = GroupTimingDiagnostics(directory, [(900002, -100100)])
            client = Client()
            sm._make_handler(900002, client)
            event = SimpleNamespace(is_private=False, chat_id=-100100, raw_text='PRIVATE MESSAGE', out=False, id=10,
                message=SimpleNamespace(date=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1),
                                        from_id=PeerUser(user_id=550), noforwards=False, sticker=None),
                get_chat=AsyncMock(return_value=SimpleNamespace(title='group', username='publicgroup', noforwards=False)),
                get_sender=AsyncMock(return_value=SimpleNamespace(id=550, first_name='Private name', last_name='', username='user', phone='998901112233')))
            verdict = SimpleNamespace(ok=True, stage='ok', matched=['SECRET KEY'], mode='count', required=1,
                                      score=1, threshold=1, positives={}, negatives={})
            with patch.object(sm, 'group_timing', diag), patch.object(sm, 'evaluate', return_value=verdict), \
                 patch.object(sm, 'is_sender_blocked', return_value=False), \
                 patch.object(sm, 'send_to_bot_api', new_callable=AsyncMock, return_value=False), \
                 patch.object(sm, 'save_lead_review', return_value=None), \
                 patch.object(sm, 'increment_user_counter'), patch.object(sm, 'set_user_last_found'), \
                 patch.object(sm, 'increment_counter'):
                await client.handler(event)
                event.chat_id = -100101
                await client.handler(event)
            content = (Path(directory) / 'owner_900002.jsonl').read_text()
            rows = [json.loads(line) for line in content.splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]['stage'], 'group_evaluation')
            self.assertEqual(rows[1]['stage'], 'group_notification')
            self.assertFalse(rows[1]['success'])
            for secret in ('PRIVATE MESSAGE', 'Private name', '998901112233', 'SECRET KEY'):
                self.assertNotIn(secret, content)


if __name__ == '__main__':
    unittest.main()
