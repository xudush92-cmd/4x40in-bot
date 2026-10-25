"""Eksport / import testlari (zaxira nusxa).

`python test_export.py`
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ.setdefault("SCANNER_DB_PATH", _TMP.name)
os.environ.setdefault("ADMIN_ID", "777")
os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "x")
os.environ.setdefault("BOT_TOKEN", "1:x")

import database as db  # noqa: E402
import bot as B  # noqa: E402
from matcher import parse_weighted_entries  # noqa: E402


def setUpModule():
    db.init_db()


def tearDownModule():
    try:
        os.unlink(_TMP.name)
    except OSError:
        pass


class Msg:
    def __init__(self):
        self.texts = []
        self.docs = []
        self.markups = []
        self.document = None
        self.caption = None
        self.text = None
        self.bot = None
        self.from_user = type("U", (), {"id": 777})()

    async def answer(self, text, **kw):
        self.texts.append(text)
        self.markups.append(kw.get("reply_markup"))

    async def answer_document(self, doc, **kw):
        self.docs.append(doc)
        self.texts.append(kw.get("caption", ""))


class Cb:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.message = Msg()
        self.from_user = type("U", (), {"id": 777})()

    async def answer(self, text="", **kw):
        self.answers.append(text)


class State:
    def __init__(self):
        self.state = None
        self.cleared = False

    async def set_state(self, value):
        self.state = value

    async def clear(self):
        self.cleared = True


class ExportTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with db.closing(db._connect()) as conn, conn:
            conn.execute("DELETE FROM phrases")
        db.set_match_mode("weight")
        db.set_score_threshold(1.75)
        for word, weight in (("kerak", 3.0), ("reys", -3.0),
                             ("joy bor", -4.0), ("bormi", 2.5)):
            db.add_keyword_checked(word, weight=weight)

    async def test_export_text_format(self):
        text = db.export_phrases_text()
        self.assertEqual(len(text.splitlines()), 4)
        self.assertIn("+3 kerak", text)
        self.assertIn("-3 reys", text)
        self.assertIn("-4 joy bor", text)
        self.assertIn("+2.5 bormi", text)

    async def test_export_sends_file(self):
        callback = Cb("wexport")
        await B.words_export(callback)
        self.assertEqual(len(callback.message.docs), 1)
        self.assertIn("Nusxa olindi", callback.message.texts[-1])
        self.assertIn("tayyor", callback.answers[-1])

    async def test_roundtrip_changes_nothing(self):
        """Eksport matnini qaytarib import qilsak — hech narsa o'zgarmaydi."""
        pairs = parse_weighted_entries(db.export_phrases_text())
        result = db.import_phrases(pairs)
        self.assertEqual(result["added"], [])
        self.assertEqual(result["updated"], [])
        self.assertEqual(len(result["skipped"]), 4)

    async def test_import_adds_and_updates(self):
        result = db.import_phrases([("kerak", 4.0), ("yangi", 2.0), ("ketadi", 1.5)])
        self.assertEqual(len(result["added"]), 2)
        self.assertEqual(len(result["updated"]), 1)
        self.assertEqual(db.get_phrase(db.word_id_by_text("kerak"))[2], 4.0)
        self.assertEqual(len(db.get_keywords()), 6)

    async def test_export_empty_list(self):
        with db.closing(db._connect()) as conn, conn:
            conn.execute("DELETE FROM phrases")
        callback = Cb("wexport")
        await B.words_export(callback)
        self.assertEqual(callback.message.docs, [])
        self.assertIn("bo'sh", callback.answers[-1].lower())

    async def test_import_via_message(self):
        state = State()
        await B.words_import_start(Cb("wimport"), state)
        self.assertIsNotNone(state.state)
        message = Msg()
        message.text = "+3 kerak\n-4 joy bor\n+2 bormi"
        await B.words_import_apply(message, state)
        # setUp dagi 4 ta yozuv qoladi (reys ham), 3 tasi importdan.
        self.assertEqual(len(db.get_keywords()), 4)
        self.assertIn("Import natijasi", message.texts[-1])
        self.assertTrue(state.cleared)

    async def test_empty_import_is_refused(self):
        state = State()
        message = Msg()
        message.text = "   "
        await B.words_import_apply(message, state)
        self.assertIn("Bo'sh", message.texts[-1])

    async def test_buttons_in_menu(self):
        message = Msg()
        await B.words_menu(message, State())
        labels = [b.text for row in message.markups[-1].inline_keyboard for b in row]
        self.assertTrue(any("eksport" in label.lower() for label in labels), labels)
        self.assertTrue(any("Import" in label for label in labels), labels)
        self.assertTrue(any("Yopish" in label for label in labels), labels)


if __name__ == "__main__":
    unittest.main(verbosity=2)
