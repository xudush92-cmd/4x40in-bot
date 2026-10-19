"""Matcher testlari (70% qoidasi): python -m unittest test_matcher -v"""
import unittest

from matcher import (
    find_match,
    match_score,
    normalize_tokens,
    phrase_matches,
    required_count,
)

KEY3 = "toshkentdan odam bor"
KEY7 = "toshkentdan samarqandga odam bor mashina kerak ertaga"
KEY10 = "toshkentdan samarqandga odam bor mashina kerak ertaga ikki kishi yuk"


class TestThresholdTable(unittest.TestCase):
    def test_required_count(self):
        self.assertEqual(required_count(7), 5)    # 5/7 = 71%
        self.assertEqual(required_count(10), 7)   # 7/10 = 70%
        self.assertEqual(required_count(3), 3)    # 2/3 = 66% < 70%
        self.assertEqual(required_count(2), 2)    # 1/2 = 50% < 70%


class TestSmallKey(unittest.TestCase):
    def test_exact_phrase(self):
        self.assertTrue(phrase_matches("Toshkentdan odam bor, tel 90 123 45 67", KEY3))

    def test_two_of_three_is_below_70(self):
        # 2/3 = 66% — yetarli emas
        self.assertFalse(phrase_matches("Toshkentdan ketaman", KEY3))
        self.assertFalse(phrase_matches("Odam bor", KEY3))

    def test_single_word_key_never_matches(self):
        self.assertFalse(phrase_matches("toshkentdan ketaman", "toshkentdan"))

    def test_punctuation_and_case_ignored(self):
        self.assertTrue(phrase_matches("TOSHKENTDAN... odam, bor!", KEY3))


class TestSevenAndTenWords(unittest.TestCase):
    def test_7_words_5_found_matches(self):
        # toshkentdan, odam, bor, mashina, kerak = 5/7 = 71%
        msg = "Toshkentdan odam bor, mashina kerak bizga"
        result = find_match(msg, [KEY7])
        self.assertIsNotNone(result)
        self.assertEqual(result.matched_count, 5)
        self.assertEqual(result.percent, 71)

    def test_7_words_4_found_no_match(self):
        # 4/7 = 57% — xabar berilmaydi
        self.assertIsNone(find_match("Toshkentdan odam bor, mashina bor", [KEY7]))

    def test_10_words_7_found_matches(self):
        msg = "Samarqandga odam bor, mashina kerak, ertaga yuk bor"
        result = find_match(msg, [KEY10])
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result.percent, 70)

    def test_10_words_6_found_no_match(self):
        # 6/10 = 60% — xabar berilmaydi
        msg = "Odam bor, mashina kerak, ertaga yuk ketadi"
        self.assertLess(match_score(msg, KEY10).percent, 70)
        self.assertIsNone(find_match(msg, [KEY10]))


class TestWordForms(unittest.TestCase):
    def test_plural_and_case_suffix(self):
        # odam ~ odamlar, toshkentdan ~ toshkentga
        self.assertTrue(phrase_matches("Toshkentga odamlar bor", KEY3))

    def test_word_order_irrelevant(self):
        self.assertTrue(phrase_matches("Odam bor, ertaga Toshkentdan ketaman", KEY3))


class TestBestMatch(unittest.TestCase):
    def test_best_phrase_wins(self):
        phrases = [KEY3, KEY7]
        msg = "Toshkentdan samarqandga odam bor mashina kerak ertaga"
        result = find_match(msg, phrases)
        self.assertEqual(result.phrase, KEY7)  # 7/7 = 100% KEY3 dan yuqori

    def test_no_match(self):
        self.assertIsNone(find_match("Salom, ishlar yaxshimi?", [KEY7, KEY10]))

    def test_normalize_apostrophe(self):
        self.assertEqual(normalize_tokens("Bog‘dod ko'chasi"), ["bog'dod", "ko'chasi"])


if __name__ == "__main__":
    unittest.main()
