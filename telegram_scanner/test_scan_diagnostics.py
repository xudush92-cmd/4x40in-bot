import datetime as dt
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from scan_diagnostics import (
    DEFAULT_NO_UPDATES_TIMEOUT_SECONDS,
    NO_UPDATES_TIMEOUT_ENV,
    ScanDiagnostics,
    configure_telethon_no_updates_timeout,
    instrument_telethon_client,
)


class TestScanDiagnostics(unittest.TestCase):
    def test_delayed_message_is_written_per_owner_without_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            diagnostics = ScanDiagnostics(temp_dir, threshold_seconds=10)
            received_at = dt.datetime.now(dt.timezone.utc)
            message_date = received_at - dt.timedelta(seconds=42)
            trace = diagnostics.begin_trace(
                owner_id=987654321,
                chat_id=-1001234567890,
                message_id=456,
                message_date=message_date,
                received_at=received_at,
                received_monotonic=time.monotonic(),
            )
            self.assertIsNotNone(trace)
            diagnostics.record_evaluation(
                trace,
                matched=True,
                filter_duration_ms=1.4,
                handler_to_filter_ms=4.2,
            )
            diagnostics.record_notification(
                trace,
                success=True,
                duration_ms=215.7,
            )

            owner_file = Path(temp_dir) / "owner_987654321.jsonl"
            self.assertTrue(owner_file.exists())
            rows = [json.loads(line) for line in owner_file.read_text().splitlines()]
            self.assertEqual([row["stage"] for row in rows], [
                "received", "evaluated", "notification",
            ])
            self.assertGreaterEqual(rows[0]["source_to_receive_ms"], 42000)
            self.assertEqual(rows[1]["matched"], True)
            self.assertEqual(rows[2]["success"], True)
            for row in rows:
                self.assertEqual(row["owner_id"], 987654321)
                self.assertEqual(row["chat_id"], -1001234567890)
                self.assertNotIn("text", row)
                self.assertNotIn("keyword", row)
                self.assertNotIn("sender", row)
                self.assertNotIn("phone", row)
                self.assertNotIn("session", row)
                self.assertNotIn("token", row)

            if os.name == "posix":
                self.assertEqual(os.stat(temp_dir).st_mode & 0o777, 0o700)
                self.assertEqual(os.stat(owner_file).st_mode & 0o777, 0o600)

    def test_under_threshold_is_not_written(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            diagnostics = ScanDiagnostics(temp_dir, threshold_seconds=10)
            received_at = dt.datetime.now(dt.timezone.utc)
            trace = diagnostics.begin_trace(
                owner_id=987654322,
                chat_id=-1001234567891,
                message_id=457,
                message_date=received_at - dt.timedelta(seconds=9),
                received_at=received_at,
            )
            self.assertIsNone(trace)
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_missing_message_date_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            diagnostics = ScanDiagnostics(temp_dir)
            trace = diagnostics.begin_trace(
                owner_id=987654323,
                chat_id=-1001234567892,
                message_id=458,
                message_date=None,
            )
            self.assertIsNone(trace)
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_match_timing_is_opt_in_private_and_captures_fast_messages(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp_dir:
            diagnostics = ScanDiagnostics(temp_dir)
            received = dt.datetime.now(dt.timezone.utc)
            with patch.dict(os.environ, {"SCANNER_MATCH_TIMING_ENABLED": "0"}):
                diagnostics.record_match_notification(
                    12, message_date=received, received_at=received,
                    before_send_ms=10, send_ms=20, success=True)
                self.assertEqual(list(Path(temp_dir).iterdir()), [])
            with patch.dict(os.environ, {"SCANNER_MATCH_TIMING_ENABLED": "1"}):
                diagnostics.record_match_notification(
                    12, message_date=received - dt.timedelta(seconds=2),
                    received_at=received, before_send_ms=10, send_ms=20, success=True)
            row = json.loads((Path(temp_dir) / "owner_12.jsonl").read_text())
            self.assertEqual(row['stage'], 'matched_notification_timing')
            self.assertEqual(row['source_to_receive_ms'], 2000)
            self.assertEqual(row['send_ms'], 20)
            self.assertTrue(row['success'])
            for key in ('chat_id', 'message_id', 'text', 'sender', 'phone', 'token'):
                self.assertNotIn(key, row)

    def test_loop_lag_only_records_above_threshold(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            diagnostics = ScanDiagnostics(temp_dir)
            diagnostics.record_loop_lag(987654324, 249)
            self.assertEqual(list(Path(temp_dir).iterdir()), [])
            diagnostics.record_loop_lag(987654324, 251)
            path = Path(temp_dir) / "owner_987654324.jsonl"
            row = json.loads(path.read_text().splitlines()[0])
            self.assertEqual(row["stage"], "event_loop_lag")
            self.assertEqual(row["lag_ms"], 251)

    def test_no_updates_timeout_override_is_bounded_and_reversible(self):
        from unittest.mock import patch
        from telethon._updates import messagebox

        original = messagebox.NO_UPDATES_TIMEOUT
        try:
            with patch.dict(os.environ, {NO_UPDATES_TIMEOUT_ENV: "60"}):
                self.assertEqual(configure_telethon_no_updates_timeout(), 60)
            self.assertEqual(messagebox.NO_UPDATES_TIMEOUT, 60)
            with patch.dict(os.environ, {NO_UPDATES_TIMEOUT_ENV: "10"}):
                self.assertEqual(
                    configure_telethon_no_updates_timeout(),
                    DEFAULT_NO_UPDATES_TIMEOUT_SECONDS,
                )
            self.assertEqual(messagebox.NO_UPDATES_TIMEOUT, 60)
        finally:
            messagebox.NO_UPDATES_TIMEOUT = original

    def test_fast_channel_difference_too_long_is_always_recorded_without_payload(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp_dir:
            diagnostics = ScanDiagnostics(temp_dir)
            from telethon.tl.types.updates import ChannelDifferenceTooLong
            response = ChannelDifferenceTooLong(
                dialog=SimpleNamespace(secret='SECRET SESSION'),
                messages=[SimpleNamespace(message='SECRET MESSAGE', phone='SECRET PHONE')],
                chats=[], users=[], final=True, timeout=30,
            )
            diagnostics.record_channel_difference(
                99, channel_id=123, request_pts=42,
                started_at=dt.datetime.now(dt.timezone.utc), duration_ms=1, response=response,
            )
            path = Path(temp_dir) / 'owner_99.jsonl'
            raw = path.read_text()
            row = json.loads(raw)
            self.assertEqual(row['response_type'], 'ChannelDifferenceTooLong')
            self.assertEqual(row['new_message_count'], 0)
            self.assertNotIn('SECRET', raw)
            self.assertNotIn('messages', row)
            self.assertNotIn('dialog', row)

    def test_fast_regular_difference_stays_selective(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp_dir:
            diagnostics = ScanDiagnostics(temp_dir)
            diagnostics.record_channel_difference(
                99, channel_id=123, request_pts=42,
                started_at=dt.datetime.now(dt.timezone.utc), duration_ms=1,
                response=SimpleNamespace(new_messages=[], other_updates=[]),
            )
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_session_health_allowlists_and_no_sensitive_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            diagnostics = ScanDiagnostics(temp_dir)
            diagnostics.record_session_health(100, connection='SECRET SESSION', update_loop='SECRET MESSAGE')
            raw = (Path(temp_dir) / 'owner_100.jsonl').read_text()
            row = json.loads(raw)
            self.assertEqual(row['connection'], 'unknown')
            self.assertEqual(row['update_loop'], 'unknown')
            self.assertNotIn('SECRET', raw)
            self.assertEqual(set(row) - {'logged_at_utc', 'owner_id'}, {'stage', 'connection', 'update_loop'})

    def test_reconnect_events_are_allowlisted_without_sensitive_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            diagnostics = ScanDiagnostics(temp_dir)
            diagnostics.record_session_event(101, event='SECRET DATA')
            self.assertFalse((Path(temp_dir) / 'owner_101.jsonl').exists())
            for event in ('reconnect_attempt', 'reconnect_succeeded', 'reconnect_failed'):
                diagnostics.record_session_event(101, event=event)
            raw = (Path(temp_dir) / 'owner_101.jsonl').read_text()
            rows = [json.loads(line) for line in raw.splitlines()]
            self.assertEqual([row['event'] for row in rows], ['reconnect_attempt', 'reconnect_succeeded', 'reconnect_failed'])
            self.assertNotIn('SECRET', raw)

    def test_diagnostic_exception_does_not_break_rpc(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import patch
        from telethon.tl import types
        from telethon.tl.functions.updates import GetChannelDifferenceRequest
        class Client:
            def __init__(self, fail=False): self.fail = fail
            async def _call(self, *args, **kwargs):
                if self.fail:
                    raise ValueError('original failure')
                return 'original result'
        request = GetChannelDifferenceRequest(channel=types.InputChannel(1, 2), filter=types.ChannelMessagesFilterEmpty(), pts=1, limit=100)
        async def run():
            with patch('scan_diagnostics.scan_diagnostics', SimpleNamespace(record_channel_difference=lambda *a, **k: (_ for _ in ()).throw(RuntimeError('secret')))):
                client = Client()
                instrument_telethon_client(client, 1)
                self.assertEqual(await client._call(None, request), 'original result')
                client = Client(fail=True)
                instrument_telethon_client(client, 1)
                with self.assertRaisesRegex(ValueError, 'original failure'):
                    await client._call(None, request)
        asyncio.run(run())

    def test_channel_difference_timing_stores_only_metadata(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from telethon.tl import types
        from telethon.tl.functions.updates import GetChannelDifferenceRequest

        class FakeClient:
            async def _call(self, sender, request, ordered=False, flood_sleep_threshold=None):
                now = dt.datetime.now(dt.timezone.utc)
                return SimpleNamespace(
                    new_messages=[SimpleNamespace(
                        date=now - dt.timedelta(seconds=35),
                        message="DO NOT LOG MESSAGE CONTENT",
                    )],
                    other_updates=[],
                    timeout=30,
                )

        async def run_test(temp_dir):
            import asyncio

            diagnostics = ScanDiagnostics(temp_dir)
            request = GetChannelDifferenceRequest(
                channel=types.InputChannel(123456789, 999),
                filter=types.ChannelMessagesFilterEmpty(),
                pts=77,
                limit=100,
            )
            client = FakeClient()
            with patch("scan_diagnostics.scan_diagnostics", diagnostics):
                self.assertTrue(instrument_telethon_client(client, 987654325))
                result = await client._call(None, request)
            self.assertIsNotNone(result)

        with tempfile.TemporaryDirectory() as temp_dir:
            import asyncio

            asyncio.run(run_test(temp_dir))
            path = Path(temp_dir) / "owner_987654325.jsonl"
            row = json.loads(path.read_text().splitlines()[0])
            self.assertEqual(row["stage"], "channel_difference")
            self.assertEqual(row["channel_id"], 123456789)
            self.assertEqual(row["request_pts"], 77)
            self.assertEqual(row["new_message_count"], 1)
            self.assertGreaterEqual(row["oldest_message_age_ms"], 35000)
            self.assertNotIn("DO NOT LOG MESSAGE CONTENT", path.read_text())
            self.assertNotIn("message", row)


if __name__ == "__main__":
    unittest.main()
