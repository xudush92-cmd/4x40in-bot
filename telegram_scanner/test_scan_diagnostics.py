import datetime as dt
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from scan_diagnostics import ScanDiagnostics


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


if __name__ == "__main__":
    unittest.main()
