#!/usr/bin/env python3
"""Feedback («foydali / keraksiz») testlari.

Ishga tushirish:  python3 test_feedback.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["SCANNER_DB_PATH"] = _TMP.name
os.environ.setdefault("ADMIN_ID", "1")
os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "x")
os.environ.setdefault("BOT_TOKEN", "1:x")

import database as db  # noqa: E402
import feedback as fb  # noqa: E402


def setUpModule():
    db.init_db()


def tearDownModule():
    try:
        os.unlink(_TMP.name)
    except OSError:
        pass


def reset():
    with db.closing(db._connect()) as conn, conn:
        conn.execute("DELETE FROM phrases")
        conn.execute("DELETE FROM lead_reviews")


class TestShift(unittest.TestCase):
    def test_positive_up_and_down(self):
        self.assertEqual(fb._shift(3.0, 0.25), 3.25)
        self.assertEqual(fb._shift(3.0, -0.25), 2.75)

    def test_zero_is_never_reached(self):
        # Musbat vazn 0 dan o'tib ketsa — kichik manfiy bo'ladi, 0 emas.
        self.assertEqual(fb._shift(0.25, -0.5), -0.25)
        self.assertEqual(fb._shift(-0.25, 0.5), 0.25)

    def test_clamped(self):
        self.assertEqual(fb._shift(9.9, 1.0), 10.0)
        self.assertEqual(fb._shift(-9.9, -1.0), -10.0)


class TestApplyFeedback(unittest.TestCase):
    def setUp(self):
        reset()
        for word, weight in (
            ("kerak", 3.0),
            ("bormi", 2.5),
            ("joy bor", -4.0),
            ("reys", -3.0),
        ):
            db.add_keyword_checked(word, weight=weight)
        self.weights = {w: wt for w, wt, _s in db.get_keywords_weighted()}

    def _review(self, words):
        return db.save_lead_review(777, words)

    def test_useful_strengthens_positive(self):
        rid = self._review(["kerak", "bormi", "joy bor"])
        status, changes = fb.apply_feedback(rid, True)
        self.assertEqual(status, "ok")
        table = {w: wt for w, wt, _s in db.get_keywords_weighted()}
        self.assertEqual(table["kerak"], 3.25)
        self.assertEqual(table["bormi"], 2.75)
        # Manfiy zaiflashadi (0 tomon)
        self.assertEqual(table["joy bor"], -3.75)
        self.assertEqual(len(changes), 3)

    def test_useless_weakens_positive_only(self):
        rid = self._review(["kerak", "reys"])
        status, changes = fb.apply_feedback(rid, False)
        self.assertEqual(status, "ok")
        table = {w: wt for w, wt, _s in db.get_keywords_weighted()}
        self.assertEqual(table["kerak"], 2.75)
        # Manfiy tegilmaydi — u o'z ishini qildi
        self.assertEqual(table["reys"], -3.0)
        self.assertEqual(len(changes), 1)

    def test_repeat_press_ignored(self):
        rid = self._review(["kerak"])
        self.assertEqual(fb.apply_feedback(rid, True)[0], "ok")
        status, changes = fb.apply_feedback(rid, True)
        self.assertEqual(status, "done")
        self.assertEqual(changes, [])
        table = {w: wt for w, wt, _s in db.get_keywords_weighted()}
        self.assertEqual(table["kerak"], 3.25)  # ikki marta oshmadi

    def test_missing_review(self):
        self.assertEqual(fb.apply_feedback(999999, True), ("missing", []))

    def test_unknown_words_skipped(self):
        rid = self._review(["tarang", "kerak"])
        status, changes = fb.apply_feedback(rid, True)
        self.assertEqual(status, "ok")
        self.assertEqual([c[1] for c in changes], ["kerak"])

    def test_empty_words(self):
        rid = self._review([])
        status, changes = fb.apply_feedback(rid, False)
        self.assertEqual(status, "ok")
        self.assertEqual(changes, [])

    def test_stats(self):
        fb.apply_feedback(self._review(["kerak"]), True)
        fb.apply_feedback(self._review(["bormi"]), False)
        self._review(["reys"])
        stats = db.get_feedback_stats()
        self.assertEqual(stats["useful"], 1)
        self.assertEqual(stats["useless"], 1)
        self.assertEqual(stats["pending"], 1)


class TestTexts(unittest.TestCase):
    def setUp(self):
        reset()
        db.add_keyword_checked("kerak", weight=3.0)

    def test_messages(self):
        self.assertIn("topilmadi", fb.feedback_text("missing", [], True))
        self.assertIn("allaqachon", fb.feedback_text("done", [], True))
        rid = db.save_lead_review(1, ["kerak"])
        status, changes = fb.apply_feedback(rid, True)
        text = fb.feedback_text(status, changes, True)
        self.assertIn("kerak", text)
        self.assertIn("3.25", text)

    def test_no_changes_message(self):
        rid = db.save_lead_review(1, ["yo'q-so'z"])
        status, changes = fb.apply_feedback(rid, True)
        self.assertIn("vazn o'zgarmadi", fb.feedback_text(status, changes, True))


class TestNotifierRow(unittest.TestCase):
    def test_callback_data(self):
        try:
            from notifier import build_feedback_row
        except ModuleNotFoundError as exc:  # aiohttp faqat serverda
            self.skipTest(f"notifier import qilinmadi: {exc}")

        row = build_feedback_row(42)
        self.assertEqual(row[0]["callback_data"], "fb:42:1")
        self.assertEqual(row[1]["callback_data"], "fb:42:0")
        self.assertEqual(row[0]["text"], "✅ Foydali")
        self.assertEqual(row[1]["text"], "❌ Keraksiz")


if __name__ == "__main__":
    unittest.main(verbosity=2)
