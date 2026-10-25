"""🧾 Diagnostika va 👁 Kuzatuv testlari.

`python test_diag.py`
"""
from __future__ import annotations

import logging
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("ADMIN_ID", "777")
os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "x")
os.environ.setdefault("BOT_TOKEN", "1:x")

import logbuffer  # noqa: E402
import watch  # noqa: E402


class TestLogBuffer(unittest.TestCase):
    def setUp(self):
        logbuffer.clear()
        logbuffer.install()
        self.log = logging.getLogger("test.diag")

    def test_lines_are_collected(self):
        self.log.info("birinchi qator")
        self.log.info("ikkinchi qator")
        tail = logbuffer.tail(10)
        self.assertIn("birinchi qator", tail)
        self.assertIn("ikkinchi qator", tail)

    def test_tail_limits_count(self):
        for i in range(50):
            self.log.info("qator-%s", i)
        lines = logbuffer.tail(5).splitlines()
        self.assertEqual(len(lines), 5)
        self.assertIn("qator-49", lines[-1])

    def test_phone_is_redacted(self):
        self.log.info("aloqa 90 123 45 67 va +998 93 111 22 33")
        tail = logbuffer.tail(5)
        self.assertIn("[raqam]", tail)
        self.assertNotIn("90 123 45 67", tail)
        self.assertNotIn("93 111 22 33", tail)

    def test_scores_are_not_redacted(self):
        self.log.info("ball=4/1.75, chegara 1.75, +3 kerak, 2 kishi")
        tail = logbuffer.tail(5)
        self.assertIn("ball=4/1.75", tail)
        self.assertIn("2 kishi", tail)

    def test_install_is_idempotent(self):
        before = len(logging.getLogger().handlers)
        logbuffer.install()
        logbuffer.install()
        self.assertEqual(len(logging.getLogger().handlers), before)

    def test_clear(self):
        self.log.info("nima bo'lsa ham")
        logbuffer.clear()
        self.assertEqual(logbuffer.size(), 0)


class TestRedact(unittest.TestCase):
    def test_short_numbers_kept(self):
        self.assertEqual(logbuffer.redact("2 joy bor"), "2 joy bor")

    def test_long_number_masked(self):
        self.assertEqual(logbuffer.redact("tel 901234567"), "tel [raqam]")

    def test_phone_with_spaces(self):
        self.assertIn("[raqam]", logbuffer.redact("+998 90 123 45 67"))


class _Verdict:
    """filters.Verdict o'rniga sodda soxta obyekt."""

    def __init__(self, score=4.0, threshold=1.75, ok=True, stage="ok",
                 positives=None, negatives=None):
        self.score = score
        self.threshold = threshold
        self.ok = ok
        self.stage = stage
        self.positives = positives or {}
        self.negatives = negatives or {}


class TestWatch(unittest.TestCase):
    def tearDown(self):
        watch.disable()

    def test_disabled_by_default(self):
        watch.disable()
        self.assertFalse(watch.is_active())
        self.assertEqual(watch.remaining(), 0)

    def test_enable_and_disable(self):
        watch.enable(5)
        self.assertTrue(watch.is_active())
        self.assertEqual(watch.remaining(), 5)
        watch.disable()
        self.assertFalse(watch.is_active())

    def test_minutes_are_clamped(self):
        self.assertEqual(watch.enable(0), 1)
        self.assertEqual(watch.enable(9999), watch.MAX_MINUTES)

    def test_expires(self):
        watch.enable(1)
        watch._until = time.time() - 1
        self.assertFalse(watch.is_active())
        self.assertEqual(watch.remaining(), 0)

    def test_card_for_passed_message(self):
        verdict = _Verdict(4.0, 1.75, True, "ok",
                           {"kerak": 3.0, "mashina": 1.0}, {})
        card = watch.card_text("mashina kerak", verdict)
        self.assertIn("mashina kerak", card)
        self.assertIn("ball <b>4</b> / 1.75", card)
        self.assertIn("+3 kerak", card)
        self.assertIn("yuborildi", card)

    def test_card_for_near_miss(self):
        verdict = _Verdict(1.5, 1.75, False, "keywords", {"odam": 1.0}, {})
        card = watch.card_text("odam bor", verdict)
        self.assertIn("chegarada", card)

    def test_card_for_emoji_block(self):
        verdict = _Verdict(0.0, 1.75, False, "emoji")
        card = watch.card_text("🚖 reys", verdict)
        self.assertIn("emoji", card)

    def test_card_escapes_html(self):
        verdict = _Verdict(4.0, 1.75, True, "ok", {"kerak": 3.0}, {})
        card = watch.card_text("<b>yomon</b> matn", verdict)
        self.assertIn("&lt;b&gt;", card)

    def test_card_truncates_long_text(self):
        verdict = _Verdict(4.0, 1.75, True, "ok", {}, {})
        card = watch.card_text("so'z " * 300, verdict)
        self.assertIn("…", card)


if __name__ == "__main__":
    unittest.main(verbosity=2)
