"""Matcher testlari: python -m unittest test_matcher -v"""
import unittest

from matcher import find_match, normalize_tokens, phrase_matches

KEY = "toshkentdan odam bor"


class TestMatcher(unittest.TestCase):
    def test_exact_phrase(self):
        self.assertTrue(phrase_matches("Toshkentdan odam bor, tel 90 123 45 67", KEY))

    def test_words_with_other_words_between(self):
        self.assertTrue(phrase_matches("Toshkentdan ertaga 2 ta odam bor ekan", KEY))

    def test_words_in_different_order(self):
        self.assertTrue(phrase_matches("Odam bor, ertaga Toshkentdan ketaman", KEY))

    def test_punctuation_and_case_ignored(self):
        self.assertTrue(phrase_matches("TOSHKENTDAN... odam, bor!", KEY))

    def test_missing_one_word_is_not_match(self):
        self.assertFalse(phrase_matches("Toshkentdan ketaman", KEY))
        self.assertFalse(phrase_matches("Odam bor", KEY))
        self.assertFalse(phrase_matches("Toshkentdan odam kerak", KEY))

    def test_single_word_key_never_matches(self):
        # Bitta so'z kalit bo'la olmaydi
        self.assertFalse(phrase_matches("toshkentdan ketaman", "toshkentdan"))

    def test_find_match_returns_phrase(self):
        phrases = ["samarqanddan mashina bor", KEY]
        self.assertEqual(find_match("Odam bor toshkentdan", phrases), KEY)
        self.assertIsNone(find_match("Salom, ishlar yaxshimi?", phrases))

    def test_normalize_apostrophe(self):
        self.assertEqual(normalize_tokens("Bog‘dod ko'chasi"), ["bog'dod", "ko'chasi"])


if __name__ == "__main__":
    unittest.main()
