#!/usr/bin/env python3
"""Vaznli rejim testlari: baza, matcher, filtr zanjiri.

Ishga tushirish:  python3 test_weights.py
Baza vaqtinchalik faylga yoziladi (SCANNER_DB_PATH), loyiha bazasiga
tegmaydi.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --- Vaqtinchalik baza: config va database shundan o'qiydi ---
_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["SCANNER_DB_PATH"] = _TMP.name
os.environ.setdefault("ADMIN_ID", "1")
os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "x")
os.environ.setdefault("BOT_TOKEN", "1:x")

import database as db  # noqa: E402
from matcher import (  # noqa: E402
    _find_entries_strict,
    parse_weighted_entries,
    score_text,
)

ADMIN = 1


def setUpModule():
    db.init_db()


def tearDownModule():
    try:
        os.unlink(_TMP.name)
    except OSError:
        pass


def reset_words():
    with db.closing(db._connect()) as conn, conn:
        conn.execute("DELETE FROM phrases")
    db.set_match_mode("weight")
    db.set_score_threshold(1.75)


class TestSchema(unittest.TestCase):
    def setUp(self):
        reset_words()

    def test_defaults(self):
        row = db.get_phrase(db.add_keyword_checked("kerak") and 0 or 0) if False else None
        self.assertIsNone(row)
        ok, _ = db.add_keyword_checked("kerak")
        self.assertTrue(ok)
        words = db.get_keywords_weighted()
        self.assertEqual(words, [("kerak", 1.0, 0)])

    def test_add_with_weight(self):
        db.add_keyword_checked("joy bor", weight=-4.0)
        db.add_keyword_checked("bormi", weight=2.5, strict=1)
        table = {w: (wt, st) for w, wt, st in db.get_keywords_weighted()}
        self.assertEqual(table["joy bor"], (-4.0, 0))
        self.assertEqual(table["bormi"], (2.5, 1))

    def test_update_and_clamp(self):
        db.add_keyword_checked("reys")
        pid = db.get_phrases_full()[0][0]
        self.assertTrue(db.update_phrase(pid, weight=-3.0))
        self.assertEqual(db.get_phrase(pid)[2], -3.0)
        db.update_phrase(pid, weight=-999)
        self.assertEqual(db.get_phrase(pid)[2], -10.0)

    def test_strict_toggle(self):
        db.add_keyword_checked("reys")
        pid = db.get_phrases_full()[0][0]
        db.update_phrase(pid, strict=1)
        self.assertEqual(db.get_phrase(pid)[3], 1)
        db.update_phrase(pid, strict=0)
        self.assertEqual(db.get_phrase(pid)[3], 0)

    def test_mode_and_threshold(self):
        self.assertEqual(db.set_match_mode("weight"), "weight")
        self.assertEqual(db.get_match_mode(), "weight")
        self.assertEqual(db.set_match_mode("count"), "count")
        with self.assertRaises(ValueError):
            db.set_match_mode("boshqa")
        db.set_score_threshold(2.5)
        self.assertEqual(db.get_score_threshold(), 2.5)

    def test_migration_keeps_old_rows(self):
        """Eski baza (weight ustunisiz) yangilanganda so'zlar qoladi."""
        import sqlite3, tempfile as tf
        raw = tf.NamedTemporaryFile(suffix=".db", delete=False)
        raw.close()
        conn = sqlite3.connect(raw.name)
        conn.execute("CREATE TABLE phrases (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT UNIQUE)")
        conn.execute("INSERT INTO phrases (text) VALUES ('eski')")
        conn.commit()
        conn.close()
        old = os.environ["SCANNER_DB_PATH"]
        os.environ["SCANNER_DB_PATH"] = raw.name
        import importlib
        import config
        importlib.reload(config)
        importlib.reload(db)
        try:
            db.init_db()
            rows = db.get_phrases_full()
            self.assertEqual(rows, [(1, "eski", 1.0, 0)])
        finally:
            os.environ["SCANNER_DB_PATH"] = old
            importlib.reload(config)
            importlib.reload(db)
            os.unlink(raw.name)


class TestWeightedInput(unittest.TestCase):
    """Admin kiritgan matnni vazn bilan ajratish."""

    def test_plain_words_default_plus_one(self):
        self.assertEqual(
            parse_weighted_entries("kerak kerek izl"),
            [("kerak", 1.0), ("kerek", 1.0), ("izl", 1.0)],
        )

    def test_weight_prefix_per_line(self):
        got = parse_weighted_entries("+3 kerak\n+2.5 bormi\n-3 reys")
        self.assertEqual(got, [("kerak", 3.0), ("bormi", 2.5), ("reys", -3.0)])

    def test_negative_multiword_is_phrase(self):
        # Haydovchi belgisi aniq bo'lishi kerak — manfiy vaznda ibora.
        self.assertEqual(
            parse_weighted_entries("-4 joy bor"), [("joy bor", -4.0)]
        )
        self.assertEqual(
            parse_weighted_entries("-4 xizmat ko'rsatamiz"),
            [("xizmat ko'rsatamiz", -4.0)],
        )

    def test_positive_multiword_splits(self):
        # Mijoz kalitlari yakka so'z — musbat vaznda bo'linadi.
        self.assertEqual(
            parse_weighted_entries("+3 kerak kerek"),
            [("kerak", 3.0), ("kerek", 3.0)],
        )

    def test_explicit_phrase_markers(self):
        self.assertEqual(
            parse_weighted_entries('-2 "kim bor"'), [("kim bor", -2.0)]
        )
        self.assertEqual(
            parse_weighted_entries("+2: kim bor"), [("kim bor", 2.0)]
        )

    def test_comma_means_separate_words(self):
        self.assertEqual(
            parse_weighted_entries("+2.5 bormi, kerak"),
            [("bormi", 2.5), ("kerak", 2.5)],
        )

    def test_multiple_entries_one_line(self):
        self.assertEqual(
            parse_weighted_entries("-3 reys +2 yukim"),
            [("reys", -3.0), ("yukim", 2.0)],
        )

    def test_last_weight_wins_for_duplicates(self):
        self.assertEqual(
            parse_weighted_entries("reys\n-3 reys"), [("reys", -3.0)]
        )

    def test_empty_and_blank(self):
        self.assertEqual(parse_weighted_entries(""), [])
        self.assertEqual(parse_weighted_entries("\n\n  \n"), [])


class TestScore(unittest.TestCase):
    def test_positive_only(self):
        r = score_text("menga mashina kerak", [("kerak", 3.0)])
        self.assertEqual(r.score, 3.0)
        self.assertTrue(r.is_match)

    def test_negative_subtracts(self):
        r = score_text("2 joy bor tel", [("joy bor", -4.0), ("kerak", 3.0)])
        self.assertEqual(r.score, -4.0)
        self.assertFalse(r.is_match)

    def test_negative_phrase_does_not_hit_client_word(self):
        """Tor manfiy ibora «xizmat kerak» (mijoz) xabarini o'chirmaydi.

        Muhim qoida: manfiy ro'yxatga UMUMIY so'z emas, haydovchi
        SHAKLI yoziladi (``xizmat ko'rsatamiz``, ``yuk tashish`` emas).
        """
        r = score_text(
            "menga yuk tashish xizmati kerak 2 tonna",
            [("xizmat ko'rsatamiz", -4.0), ("kerak", 3.0)],
        )
        self.assertEqual(r.negatives, {})
        self.assertGreaterEqual(r.score, 3.0)
        self.assertTrue(r.is_match)

    def test_negative_phrase_matches_driver_ad(self):
        r = score_text(
            "bizda yuk tashish xizmat ko'rsatamiz, arzon",
            [("xizmat ko'rsatamiz", -4.0), ("kerak", 3.0)],
        )
        self.assertEqual(r.negatives, {"xizmat ko'rsatamiz": -4.0})
        self.assertFalse(r.is_match)

    def test_negative_suffix_match_works(self):
        # Manfiy yozuvda ham qo'shimcha shakli topiladi: reys ~ reyslar
        r = score_text("har kuni reyslar bor", [("reys", -3.0)])
        self.assertIn("reys", r.negatives)

    def test_threshold_comparison(self):
        r = score_text("kerak", [("kerak", 2.0)], threshold=2.0)
        self.assertTrue(r.is_match)
        r = score_text("kerak", [("kerak", 2.0)], threshold=2.5)
        self.assertFalse(r.is_match)

    def test_zero_weight_ignored(self):
        r = score_text("kerak", [("kerak", 0.0)])
        self.assertEqual(r.score, 0.0)
        self.assertEqual(r.positives, {})

    def test_emoji_penalty(self):
        r = score_text("mashina kerak 🚕", [("kerak", 3.0)], emoji_penalty=2.5)
        self.assertEqual(r.score, 0.5)
        self.assertEqual(r.emoji_penalty, 2.5)

    def test_strict_negatives_do_not_fuzzy_match(self):
        # "tashaymiz" manfiy yozuvi "tashaydi" xabar so'ziga mos kelmaydi
        self.assertEqual(_find_entries_strict("kim tashaydi", ["tashaymiz"]), [])
        self.assertEqual(_find_entries_strict("biz tashaymiz", ["tashaymiz"]),
                         ["tashaymiz"])

    def test_positive_question_strict(self):
        r = score_text("2 joy bor", [("bormi", 2.5)])
        self.assertEqual(r.positives, {})
        r = score_text("2 joy bormi", [("bormi", 2.5)])
        self.assertEqual(r.positives, {"bormi": 2.5})


class TestFilterChain(unittest.TestCase):
    """filters.evaluate() — real skaner zanjiri."""

    def setUp(self):
        reset_words()
        db.set_setting("is_active", "1")
        db.set_user_scanner_enabled(ADMIN, True)
        # Test rejimida ham kamida bitta faol guruh kerak (aks holda
        # zanjir guruh bosqichida to'xtaydi — bu to'g'ri xatti-harakat).
        with db.closing(db._connect()) as conn, conn:
            conn.execute("DELETE FROM user_groups")
            conn.execute(
                "INSERT INTO user_groups "
                "(owner_user_id, input_value, chat_id, title, is_active, status) "
                "VALUES (?, ?, ?, ?, 1, 'ok')",
                (ADMIN, "@test", -1001234567890, "Test guruh"),
            )

    def _verdict(self, text):
        import filters
        return filters.evaluate(ADMIN, text, check_group=False)

    def test_weight_mode_passes_client(self):
        db.add_keyword_checked("kerak", weight=3.0)
        db.add_keyword_checked("bormi", weight=2.5)
        v = self._verdict("menga bugun bitta mashina kerak iltimos")
        self.assertTrue(v.ok, v.detail)
        self.assertEqual(v.mode, "weight")
        self.assertEqual(v.score, 3.0)

    def test_weight_mode_blocks_driver(self):
        db.add_keyword_checked("kerak", weight=3.0)
        db.add_keyword_checked("joy bor", weight=-4.0)
        v = self._verdict("2 joy bor, tel 90 123 45 67")
        self.assertFalse(v.ok)
        self.assertEqual(v.stage, "keywords")
        self.assertEqual(v.negatives, {"joy bor": -4.0})

    def test_weight_mode_respects_threshold(self):
        db.add_keyword_checked("ketadi", weight=1.0)
        db.set_score_threshold(1.75)
        v = self._verdict("ertaga ketadi")
        self.assertFalse(v.ok)
        db.set_score_threshold(0.5)
        v = self._verdict("ertaga ketadi")
        self.assertTrue(v.ok)

    def test_count_mode_unchanged(self):
        db.set_match_mode("count")
        db.set_setting("match_count", "1")
        db.add_keyword_checked("kerak", weight=3.0)
        v = self._verdict("menga mashina kerak")
        self.assertTrue(v.ok)
        self.assertEqual(v.mode, "count")
        db.set_setting("match_count", "2")
        v = self._verdict("menga mashina kerak")
        self.assertFalse(v.ok)

    def test_emoji_stage_still_first(self):
        db.add_keyword_checked("kerak", weight=3.0)
        v = self._verdict("mashina kerak 🚕")
        self.assertFalse(v.ok)
        self.assertEqual(v.stage, "emoji")


if __name__ == "__main__":
    unittest.main(verbosity=2)
