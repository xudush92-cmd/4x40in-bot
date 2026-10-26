"""Ro'yxatdagi tezkor +/- vazn tugmalari."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["SCANNER_DB_PATH"] = _TMP.name
os.environ.setdefault("ADMIN_ID", "777")
os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "x")
os.environ.setdefault("BOT_TOKEN", "1:x")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database as db  # noqa: E402
import bot  # noqa: E402


def setUpModule():
    db.init_db()


def tearDownModule():
    try:
        os.unlink(_TMP.name)
    except OSError:
        pass


class FakeMessage:
    def __init__(self):
        self.edits = []
        self.answers = []

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


class FakeCallback:
    def __init__(self, data):
        self.data = data
        self.message = FakeMessage()
        self.answers = []

    async def answer(self, text="", **kwargs):
        self.answers.append(text)


class QuickWeightButtons(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with db.closing(db._connect()) as conn, conn:
            conn.execute("DELETE FROM phrases")
        db.set_match_mode("weight")
        db.add_keyword_checked("ketadi", weight=1.0)
        self.pid = db.get_phrases_full()[0][0]

    def test_each_word_row_has_minus_word_plus(self):
        _text, markup = bot._words_page(0)
        row = markup.inline_keyboard[0]
        self.assertEqual(len(row), 3)
        self.assertEqual(row[0].text, "➖0.5")
        self.assertIn("ketadi", row[1].text)
        self.assertEqual(row[2].text, "➕0.5")
        self.assertEqual(row[0].callback_data, f"wqadj:{self.pid}:-0.5:0")
        self.assertEqual(row[2].callback_data, f"wqadj:{self.pid}:0.5:0")

    async def test_minus_button_updates_weight_and_keeps_list_open(self):
        callback = FakeCallback(f"wqadj:{self.pid}:-0.5:0")
        await bot.word_list_weight_adjust(callback)
        self.assertEqual(db.get_phrase(self.pid)[2], 0.5)
        self.assertEqual(len(callback.message.edits), 1)
        markup = callback.message.edits[0][1]["reply_markup"]
        self.assertIn("ketadi", markup.inline_keyboard[0][1].text)
        self.assertEqual(callback.answers, ["⚖️ ketadi: +0.5"])

    async def test_plus_button_can_return_from_zero_to_positive(self):
        db.update_phrase(self.pid, weight=0.0)
        _text, markup = bot._words_page(0)
        self.assertTrue(markup.inline_keyboard[0][1].text.startswith("⚪0"))
        callback = FakeCallback(f"wqadj:{self.pid}:0.5:0")
        await bot.word_list_weight_adjust(callback)
        self.assertEqual(db.get_phrase(self.pid)[2], 0.5)

    async def test_weight_is_clamped_at_ten(self):
        db.update_phrase(self.pid, weight=10.0)
        callback = FakeCallback(f"wqadj:{self.pid}:0.5:0")
        await bot.word_list_weight_adjust(callback)
        self.assertEqual(db.get_phrase(self.pid)[2], 10.0)
        self.assertEqual(callback.answers, ["Vazn +10 chegarasida."])
        self.assertEqual(callback.message.edits, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
