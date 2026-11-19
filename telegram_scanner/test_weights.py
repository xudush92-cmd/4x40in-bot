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
    _strict_word_match,
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

    def test_prefix_related_words_can_be_separate_weighted_keys(self):
        self.assertIsNone(db.keyword_reject_reason("bor"))
        db.add_keyword_checked("bor", weight=1.0)
        self.assertIsNone(db.keyword_reject_reason("borm"))
        added, conflicts = db.add_keyword_checked("borm", weight=2.0)
        self.assertTrue(added)
        self.assertEqual(conflicts, [])
        table = {word: weight for word, weight, _strict in db.get_keywords_weighted()}
        self.assertEqual(table["bor"], 1.0)
        self.assertEqual(table["borm"], 2.0)

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

    def test_w_sh_variants_in_weighted_phrases_and_negative_entries(self):
        for text in ("mawina kerak", "mashina kerak", "машина керак"):
            with self.subTest(text=text):
                result = score_text(text, [("mashina kerak", 3.0)], threshold=3.0)
                self.assertEqual(result.score, 3.0)
        result = score_text("mawina bor", [("mashina bor", -4.0)], threshold=1.0)
        self.assertEqual(result.score, -4.0)
        result = score_text("mashina kerak", [("mawina kerak", 3.0)], threshold=3.0)
        self.assertEqual(result.score, 3.0)

    def test_w_sh_phrase_aliases_score_once(self):
        result = score_text("mawina kerak", [("mawina kerak", 3.0),
                                             ("mashina kerak", 3.0)], threshold=3.0)
        self.assertEqual(result.score, 3.0)
        self.assertEqual(len(result.positives), 1)

    def test_new_alphabet_aliases_do_not_duplicate_weighted_keys(self):
        entries = parse_weighted_entries("+3: shahar\n+3: şahar\n+3: шаҳар")
        self.assertEqual(entries, [("shahar", 3.0)])
        result = score_text("ŞAHAR", entries, threshold=3.0)
        self.assertEqual(result.score, 3.0)
        self.assertEqual(result.positives, {"shahar": 3.0})

    def test_fuzzy_single_word_aliases_only_score_once_per_token(self):
        entries = [("pochta", 3.0), ("pocta", 3.0), ("pochto", 3.0)]
        result = score_text("pocht", entries, threshold=3.0)
        self.assertEqual(result.score, 3.0)
        self.assertEqual(len(result.positives), 1)

    def test_fuzzy_phrase_aliases_only_score_once_per_occurrence(self):
        entries = [
            ("pochta bor", 3.0),
            ("pocta bor", 3.0),
            ("pochto bor", 3.0),
            ("moshin borm", 3.0),
        ]
        first = score_text("Moshina bormi\n\npochta bor", entries, threshold=3.0)
        second = score_text("pochta bor xizmati bor", entries, threshold=3.0)
        repeated = score_text("pochta bor va pocta bor", entries, threshold=3.0)
        self.assertEqual(first.score, 6.0)
        self.assertEqual(first.positives, {"pochta bor": 3.0, "moshin borm": 3.0})
        self.assertEqual(second.score, 3.0)
        self.assertEqual(second.positives, {"pochta bor": 3.0})
        self.assertEqual(repeated.score, 3.0)
        self.assertEqual(repeated.positives, {"pochta bor": 3.0})

    def test_distinct_phrase_occurrences_keep_independent_scores(self):
        entries = [
            ("pochta bor", 3.0),
            ("pocta bor", 3.0),
            ("odam bor", 2.0),
        ]
        result = score_text("pochta bor odam bor", entries, threshold=3.0)
        self.assertEqual(result.score, 5.0)
        self.assertEqual(result.positives, {"pochta bor": 3.0, "odam bor": 2.0})

    def test_empty_and_blank(self):
        self.assertEqual(parse_weighted_entries(""), [])
        self.assertEqual(parse_weighted_entries("\n\n  \n"), [])


class TestScore(unittest.TestCase):
    def test_more_specific_key_uses_its_own_weight(self):
        r = score_text("borm", [("bor", 1.0), ("borm", 2.0)])
        self.assertEqual(r.positives, {"borm": 2.0})
        self.assertEqual(r.score, 2.0)

    def test_root_still_matches_when_no_specific_key_is_present(self):
        r = score_text("bormo", [("bor", 1.0)])
        self.assertEqual(r.positives, {"bor": 1.0})

    def test_separate_occurrences_count_both_specific_keys(self):
        r = score_text("bor borm", [("bor", 1.0), ("borm", 2.0)])
        self.assertEqual(r.positives, {"bor": 1.0, "borm": 2.0})
        self.assertEqual(r.score, 3.0)

    def test_exact_form_wins_over_reverse_partial_match(self):
        r = score_text("ketadi", [("ketadi", 1.0), ("ketadimi", 2.0)])
        self.assertEqual(r.positives, {"ketadi": 1.0})

    def test_specific_negative_wins_over_positive_root(self):
        r = score_text("kerakmas", [("kerak", 2.0), ("kerakmas", -3.0)])
        self.assertEqual(r.positives, {})
        self.assertEqual(r.negatives, {"kerakmas": -3.0})
        self.assertEqual(r.score, -3.0)

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

    def test_joined_place_name_matches_spaced_form_without_prefix_inflation(self):
        text = "yangi bozordan urganchga moshina kerak"
        entries = [
            ("mashina", 0.5, 0),
            ("kerak", 0.5, 0),
            ("urganchga", 0.5, 0),
            ("yangibozordan", 0.5, 0),
            ("yangibozorga", 0.5, 0),
            ("yangibozorda", 0.5, 0),
            ("yangiyo'ldan", 0.5, 0),
            ("yangiyo'lga", 0.5, 0),
            ("yangiyo'lda", 0.5, 0),
        ]
        result = score_text(text, entries, threshold=3.0)
        self.assertEqual(result.positives, {
            "mashina": 0.5,
            "kerak": 0.5,
            "urganchga": 0.5,
            "yangibozordan": 0.5,
        })
        self.assertEqual(result.score, 2.0)
        self.assertFalse(result.is_match)

    def test_short_common_prefix_does_not_match_longer_place_key(self):
        result = score_text("yangi", [("yangibozordan", 1.0, 0)], 0.5)
        self.assertEqual(result.positives, {})
        self.assertEqual(result.score, 0.0)

    def test_place_suffix_variants_still_match(self):
        result = score_text("toshkentdan", [("toshkentga", 1.0, 0)], 1.0)
        self.assertEqual(result.positives, {"toshkentga": 1.0})

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

    def test_locked_word_matches_exact_form_only(self):
        r = score_text("ketadimi", [("ketadi", 1.0, 1)])
        self.assertEqual(r.positives, {})
        r = score_text("ketadi", [("ketadi", 1.0, 1)])
        self.assertEqual(r.positives, {"ketadi": 1.0})

    def test_locked_phrase_requires_exact_consecutive_words(self):
        entries = [("kim bor", 2.0, 1)]
        self.assertEqual(score_text("kim bor", entries).positives, {"kim bor": 2.0})
        self.assertEqual(score_text("kimda bor", entries).positives, {})
        self.assertEqual(score_text("kim bori", entries).positives, {})

    def test_base_key_matches_question_form(self):
        """Teskari yo'nalish ochiq: ``ketadi`` kaliti ``ketadimi`` ni topadi.

        Bu mijoz shakli — yo'qolsa mijoz xabari o'tkazib yuboriladi.
        """
        r = score_text("pochta ketadimi Qashqaryoga", [("ketadi", 1.0)])
        self.assertEqual(r.positives, {"ketadi": 1.0})
        r = score_text("mashina kerakmi", [("kerak", 3.0)])
        self.assertEqual(r.positives, {"kerak": 3.0})
        r = score_text("mashina kerak", [("kerakmi", 2.0)])
        self.assertEqual(r.positives, {})


class TestDatabaseWAL(unittest.TestCase):
    """Bot va skaner bir vaqtda yozadi — WAL rejimi yoqilgan bo'lishi kerak."""

    def test_journal_mode_is_wal(self):
        with db.closing(db._connect()) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "wal")

    def test_connection_usable(self):
        """WAL yoqilgandan keyin oddiy yozish/o'qish buzilmaydi."""
        db.add_keyword_checked("waltest", weight=1.5)
        self.assertIn("waltest", db.get_keywords())
        with db.closing(db._connect()) as conn:
            conn.execute("DELETE FROM phrases WHERE text = ?", ("waltest",))
            conn.commit()


class TestPhraseSurvivesRestart(unittest.TestCase):
    """Ko'p so'zli ibora restartdan keyin ham butun va vazni bilan qoladi.

    Regressiya: ``_migrate_old_sets`` har ``init_db()`` da ishlab,
    ``joy bor`` ni ``joy`` + ``bor`` ga bo'lib, vaznini yo'qotardi.
    """

    def test_phrase_kept_after_init(self):
        reset_words()
        db.add_keyword_checked("joy bor", weight=-4.0)
        db.add_keyword_checked("kerak", weight=3.0)
        for _ in range(3):
            db.init_db()
        rows = db.get_phrases_full()
        self.assertIn(("joy bor", -4.0), [(r[1], r[2]) for r in rows])
        self.assertNotIn("joy", [r[1] for r in rows])
        self.assertNotIn("bor", [r[1] for r in rows])

    def test_export_keeps_phrase(self):
        reset_words()
        db.add_keyword_checked("kim olib ketadi", weight=3.0)
        db.add_keyword_checked("reys", weight=-3.0)
        db.init_db()
        text = db.export_phrases_text()
        self.assertIn("+3: kim olib ketadi", text)
        self.assertIn("-3 reys", text)

    def test_legacy_split_only_once_with_weight(self):
        reset_words()
        with db.closing(db._connect()) as conn, conn:
            conn.execute("DELETE FROM settings WHERE key = 'legacy_sets_split'")
            conn.execute(
                "INSERT INTO phrases (text, weight, strict) VALUES ('reys har kuni', -3.5, 1)"
            )
        db.init_db()
        rows = {r[1]: (r[2], r[3]) for r in db.get_phrases_full()}
        self.assertEqual(rows.get("reys"), (-3.5, 1))
        self.assertEqual(rows.get("har"), (-3.5, 1))
        # Ikkinchi init hech narsani o'zgartirmaydi.
        before = db.get_phrases_full()
        db.init_db()
        self.assertEqual(db.get_phrases_full(), before)


class TestNegativeScoring(unittest.TestCase):
    """Manfiylar qo'shilmaydi — faqat eng kuchlisi hisoblanadi.

    Regressiya: bitta ibora bir nechta manfiy yozuvga mos tushsa
    (``bo'sh joy bor`` -> ``joy bor`` + ``bo'sh joy`` + ``bo'sh``),
    xabar uch marta jazolangani uchun ball **-10.5** chiqardi.
    """

    def test_overlapping_negatives_counted_once(self):
        r = score_text(
            "bo'sh joy bor",
            [("joy bor", -4.0), ("bo'sh joy", -4.0), ("bo'sh", -2.5)],
        )
        self.assertEqual(r.score, -4.0)
        self.assertFalse(r.is_match)

    def test_single_strong_negative_is_enough(self):
        r = score_text("reys bor, bo'sh joy bor", [("reys", -3.0), ("joy bor", -4.0)])
        self.assertEqual(r.score, -4.0)

    def test_positives_still_add_up(self):
        r = score_text("mashina kerak", [("mashina", 1.0), ("kerak", 3.0)])
        self.assertEqual(r.score, 4.0)
        self.assertTrue(r.is_match)

    def test_strong_client_signal_not_vetoed_by_two_weak_negatives(self):
        r = score_text(
            "mashina kerak, kim chiqadi",
            [("mashina", 1.0), ("kerak", 3.0), ("chiqadi", -2.5), ("chiqdim", -2.5)],
        )
        self.assertEqual(r.score, 1.5)


class TestCyrillicNegation(unittest.TestCase):
    """Kirill yozuvidagi inkor ham manfiy yozuvni topadi.

    Regressiya: ``машина керак эмас`` o'tib ketardi — manfiy iboralar
    ``cyr_to_lat`` qo'llanmaydigan qidiruvdan o'tardi, shuning uchun
    ``керак эмас`` lotin ``kerak emas`` bilan mos kelmasdi.
    """

    def test_strict_finds_cyrillic_negation(self):
        self.assertEqual(
            _find_entries_strict("машина керак эмас", ["kerak emas"]),
            ["kerak emas"],
        )

    def test_negation_does_not_pass(self):
        r = score_text(
            "машина керак эмас", [("kerak", 3.0), ("mashina", 1.0), ("kerak emas", -3.0)]
        )
        self.assertIn("kerak emas", r.negatives)
        self.assertFalse(r.is_match)

    def test_kerek_spelling_variant(self):
        # ``керек эмас`` — bir harf farqi bilan ham inkor topiladi.
        r = score_text(
            "машина керек эмас", [("kerak", 3.0), ("mashina", 1.0), ("kerak emas", -3.0)]
        )
        self.assertFalse(r.is_match)

    def test_cyrillic_client_message_still_passes(self):
        r = score_text("Машина керак Тошкентдан", [("kerak", 3.0), ("mashina", 1.0)])
        self.assertTrue(r.is_match)

    def test_cyrillic_driver_ad_blocked(self):
        r = score_text("Ташкентдан чиқдим, 2 жой бор", [("joy bor", -4.0)])
        self.assertIn("joy bor", r.negatives)

    def test_one_letter_rule_needs_long_words(self):
        # Qisqa so'zlarda bitta harf farqi tasodifiy moslik beradi.
        self.assertFalse(_strict_word_match("bor", "bir"))
        self.assertTrue(_strict_word_match("kerak", "kerek"))


class TestUserThreshold(unittest.TestCase):
    """Per-user chegara: har foydalanuvchi o'zi tanlaydi, admin fallback."""

    def setUp(self):
        reset_words()
        with db.closing(db._connect()) as conn, conn:
            conn.execute("DELETE FROM users")
            conn.execute("DELETE FROM user_groups")
        db.upsert_user(ADMIN)
        db.upsert_user(555)
        db.set_new_term(555, 30)   # oddiy foydalanuvchiga tarif kerak
        db.set_setting("is_active", "1")
        db.set_user_scanner_enabled(ADMIN, True)
        db.set_user_scanner_enabled(555, True)
        for uid in (ADMIN, 555):
            with db.closing(db._connect()) as conn, conn:
                conn.execute(
                    "INSERT INTO user_groups "
                    "(owner_user_id, input_value, chat_id, title, is_active, status) "
                    "VALUES (?, ?, ?, ?, 1, 'ok')",
                    (uid, f"@g{uid}", -1001234567890 - uid, "Test"),
                )

    def test_default_is_admin_value(self):
        db.set_score_threshold(1.75)
        self.assertEqual(db.get_user_score_threshold(ADMIN), 1.75)
        self.assertEqual(db.get_user_score_threshold(555), 1.75)
        self.assertEqual(db.get_own_score_threshold(555), 0.0)

    def test_own_threshold_overrides(self):
        db.set_score_threshold(1.75)
        db.set_user_score_threshold(555, 3.0)
        self.assertEqual(db.get_user_score_threshold(555), 3.0)
        # Boshqalarga ta'sir qilmaydi
        self.assertEqual(db.get_user_score_threshold(ADMIN), 1.75)

    def test_reset_to_admin(self):
        db.set_score_threshold(2.0)
        db.set_user_score_threshold(555, 3.0)
        db.set_user_score_threshold(555, 0)
        self.assertEqual(db.get_user_score_threshold(555), 2.0)
        self.assertEqual(db.get_own_score_threshold(555), 0.0)

    def test_fallback_when_user_missing(self):
        db.set_score_threshold(1.5)
        self.assertEqual(db.get_user_score_threshold(999999), 1.5)

    def test_clamped(self):
        db.set_user_score_threshold(555, 99.0)
        self.assertEqual(db.get_own_score_threshold(555), 10.0)
        db.set_user_score_threshold(555, -99.0)
        self.assertEqual(db.get_own_score_threshold(555), -10.0)

    def test_filter_uses_own_threshold(self):
        import filters

        db.add_keyword_checked("ketadi", weight=1.0)
        db.set_match_mode("weight")
        db.set_score_threshold(1.75)
        text = "ertaga ketadi"
        # Admin: 1.0 < 1.75 -> o'tmaydi
        self.assertFalse(filters.evaluate(ADMIN, text, check_group=False).ok)
        # Foydalanuvchi past chegara tanladi -> o'tadi
        db.set_user_score_threshold(555, 0.5)
        v = filters.evaluate(555, text, check_group=False)
        self.assertTrue(v.ok)
        self.assertTrue(v.own_threshold)
        self.assertEqual(v.threshold, 0.5)
        # Admin hali ham o'z chegarasida
        v2 = filters.evaluate(ADMIN, text, check_group=False)
        self.assertFalse(v2.ok)
        self.assertFalse(v2.own_threshold)

    def test_upgrade_keeps_existing_users(self):
        """Migratsiya: own_score_threshold ustuni qo'shilganda userlar qoladi."""
        row = db.get_user_full(555)
        self.assertIsNotNone(row)
        self.assertEqual(db.get_own_score_threshold(555), 0.0)


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


class TestSignupGroupScanIntegration(unittest.IsolatedAsyncioTestCase):
    """Offline smoke test: registration -> group -> filter -> notification."""

    OWNER = 555_555
    CHAT_ID = -1001234567890

    async def asyncSetUp(self):
        self.db = db
        db.delete_user_completely(self.OWNER)
        with db.closing(db._connect()) as conn, conn:
            conn.execute("DELETE FROM phrases")
            conn.execute("DELETE FROM lead_reviews WHERE owner_user_id = ?", (self.OWNER,))
        db.set_setting("is_active", "1")
        db.set_match_mode("weight")
        db.set_score_threshold(3.0)

        # Registration and admin approval are exercised against a temporary DB.
        db.upsert_user(self.OWNER, "Sinov", "sinov_user")
        db.set_registration_info(self.OWNER, "Sinov Foydalanuvchi", "998900000000")
        db.set_pending_session(self.OWNER, "fake-encrypted-session")
        self.assertTrue(db.approve_pending_session(self.OWNER))
        db.set_new_term(self.OWNER, 7)
        db.set_user_scanner_enabled(self.OWNER, True)
        user = db.get_user_full(self.OWNER)
        self.assertEqual(user[6], "Sinov Foydalanuvchi")
        self.assertEqual(user[8], "fake-encrypted-session")
        self.assertEqual(user[10], 0)

        # A private group is added and resolved to its active Telegram ID.
        added, error = db.add_user_group(self.OWNER, str(self.CHAT_ID))
        self.assertTrue(added, error)
        group_id = db.get_user_groups(self.OWNER)[0][0]
        self.assertTrue(db.resolve_user_group(group_id, self.CHAT_ID, "Sinov guruhi"))
        self.assertEqual(db.get_owner_active_chat_ids(self.OWNER), [self.CHAT_ID])

        # Global weighted keys stay in the canonical old Latin form.
        db.add_keyword_checked("shahar", weight=3.0)
        db.add_keyword_checked("odam bor", weight=3.0)

    async def asyncTearDown(self):
        db.delete_user_completely(self.OWNER)
        with db.closing(db._connect()) as conn, conn:
            conn.execute("DELETE FROM phrases")
            conn.execute("DELETE FROM lead_reviews WHERE owner_user_id = ?", (self.OWNER,))

    async def test_new_and_cyrillic_messages_reach_notification(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch
        import scanner_manager

        class Client:
            def on(self, _builder):
                def register(handler):
                    self.handler = handler
                    return handler
                return register

        class Event:
            is_private = False
            out = False
            chat_id = TestSignupGroupScanIntegration.CHAT_ID
            message = SimpleNamespace(noforwards=False, sticker=None)

            def __init__(self, text, message_id, out=False):
                self.raw_text = text
                self.id = message_id
                self.out = out

            async def get_chat(self):
                return SimpleNamespace(
                    title="Sinov guruhi", username="sinov_group", noforwards=False
                )

            async def get_sender(self):
                return SimpleNamespace(
                    first_name="Sinov", last_name="Mijoz", username="sinov_mijoz",
                    id=777001, phone=None,
                )

        # The actual filter chain, DB-owned active group, handler, formatting,
        # and notification dispatch are tested. Telegram/API calls are mocked.
        client = Client()
        scanner_manager._make_handler(self.OWNER, client)
        notifications = AsyncMock(return_value=True)
        with patch.object(scanner_manager, "send_to_bot_api", notifications):
            await client.handler(Event("Şahar tomondan odam bor", 101))
            await client.handler(Event("Шаҳар томондан одам бор", 102))
            # The connected account's own outgoing group messages are scanned too.
            await client.handler(Event("Şahar tomondan odam bor", 103, out=True))

        self.assertEqual(notifications.await_count, 3)
        for call in notifications.await_args_list:
            text = call.args[0]
            self.assertIn("YANGI BUYURTMA / MIJOZ TOPILDI", text)
            self.assertIn("Sinov guruhi", text)
            self.assertIn("Sinov Mijoz", text)
            self.assertIn("shahar", text)
            self.assertIn("odam bor", text)
        self.assertEqual(db.get_user_counter(self.OWNER, "leads_found"), 3)

    def test_exact_group_duplicate_is_rejected_and_timestamped(self):
        group = db.get_user_groups(self.OWNER)[0]
        self.assertGreater(db.get_user_group_created_at(group[0]), 0)
        added, error = db.add_user_group(self.OWNER, str(self.CHAT_ID))
        self.assertFalse(added)
        self.assertIn("allaqachon", error)
        self.assertEqual(len(db.get_user_groups(self.OWNER)), 1)

    async def test_leaving_pauses_group_and_rejoining_restores_it(self):
        group_id = db.get_user_groups(self.OWNER)[0][0]
        self.assertTrue(db.mark_user_group_left(group_id))
        self.assertEqual(db.get_owner_active_chat_ids(self.OWNER), [])
        self.assertFalse(db.mark_user_group_left(group_id))
        self.assertTrue(db.resolve_user_group(group_id, self.CHAT_ID, "Sinov guruhi"))
        self.assertEqual(db.get_owner_active_chat_ids(self.OWNER), [self.CHAT_ID])

    def test_filter_modes_reuse_one_database_connection(self):
        import filters

        db.add_keyword_checked("kerak", weight=2.0)
        db.set_setting("match_count", "1")
        db.set_score_threshold(1.75)

        original_connect = db._connect
        for mode in ("count", "weight"):
            db.set_match_mode(mode)
            calls = 0

            def counted_connect():
                nonlocal calls
                calls += 1
                return original_connect()

            db._connect = counted_connect
            try:
                verdict = filters.evaluate(ADMIN, "kerak", check_group=False)
            finally:
                db._connect = original_connect

            self.assertTrue(verdict.ok, (mode, verdict.detail))
            self.assertEqual(calls, 1, mode)


if __name__ == "__main__":
    unittest.main(verbosity=2)
