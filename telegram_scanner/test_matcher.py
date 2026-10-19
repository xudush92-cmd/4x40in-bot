"""Matcher testlari: kalitlar cheksiz, admin soni bo'yicha.
python -m unittest test_matcher -v"""
import unittest

from matcher import (
    find_match,
    match_keywords,
    normalize_tokens,
    parse_key_words,
)

KEYWORDS = ["toshkent", "samarqand", "odam", "mashina", "kerak", "yuk", "bugun"]


class TestMatchCount(unittest.TestCase):
    def test_three_found_of_many(self):
        r = match_keywords("Toshkentdan odam bor, mashina kerak", KEYWORDS, required_count=3)
        self.assertTrue(r.is_match)
        self.assertGreaterEqual(r.matched_count, 3)

    def test_below_admin_count_no_match(self):
        # 2 ta topildi, admin 3 belgilagan — xabar berilmaydi
        r = match_keywords("Toshkentdan odam bor", KEYWORDS, required_count=3)
        self.assertFalse(r.is_match)
        self.assertIsNone(find_match("Toshkentdan odam bor", KEYWORDS, required_count=3))

    def test_admin_count_two(self):
        self.assertIsNotNone(find_match("Odam bor, mashina bormi?", KEYWORDS, required_count=2))

    def test_admin_count_one(self):
        self.assertIsNotNone(find_match("Faqat yuk bor", KEYWORDS, required_count=1))

    def test_many_keywords_unlimited(self):
        many = [f"kalit{i}" for i in range(50)] + KEYWORDS
        r = match_keywords("Toshkent odam mashina", many, required_count=3)
        self.assertTrue(r.is_match)
        self.assertEqual(r.total_words, 57)

    def test_count_larger_than_found(self):
        r = match_keywords("Toshkent odam", KEYWORDS, required_count=5)
        self.assertFalse(r.is_match)


class TestParsingAndForms(unittest.TestCase):
    def test_each_word_separate_key(self):
        self.assertEqual(
            parse_key_words("toshkent, odam; mashina"),
            ["toshkent", "odam", "mashina"],
        )
        self.assertEqual(parse_key_words("odam odam"), ["odam"])

    def test_plural_and_case_suffix(self):
        r = match_keywords("Toshkentga odamlar bor", KEYWORDS, required_count=2)
        self.assertTrue(r.is_match)

    def test_word_forms_in_message(self):
        self.assertIsNotNone(
            find_match("Toshkentdan yuklar ketmoqda, mashina bormi", KEYWORDS, required_count=3)
        )

    def test_normalize_apostrophe(self):
        self.assertEqual(normalize_tokens("Bog‘dod ko'chasi"), ["bog'dod", "ko'chasi"])

    def test_no_keywords_no_match(self):
        self.assertIsNone(find_match("Toshkent odam mashina", [], required_count=1))


if __name__ == "__main__":
    unittest.main()
