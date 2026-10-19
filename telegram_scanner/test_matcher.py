"""Matcher testlari (foizsiz, 2–10 so'z, 2/3 ta shart):
python -m unittest test_matcher -v"""
import unittest

from matcher import (
    find_match,
    match_key_set,
    normalize_tokens,
    parse_key_words,
    validate_key_words,
)

SET7 = "toshkent samarqand odam mashina kerak yuk bugun"
SET4 = "toshkent odam mashina kerak"


class TestValidation(unittest.TestCase):
    def test_word_count_limits(self):
        self.assertIsNotNone(validate_key_words(["toshkent"]))          # 1 ta — kam
        self.assertIsNone(validate_key_words(["toshkent", "odam"]))     # 2 ta — OK
        ten = [f"soz{i}" for i in range(10)]
        self.assertIsNone(validate_key_words(ten))                      # 10 ta — OK
        self.assertIsNotNone(validate_key_words(ten + ["ortiqcha"]))    # 11 ta — ko'p

    def test_duplicates_counted_once(self):
        self.assertEqual(parse_key_words("odam odam mashina"), ["odam", "mashina"])
        self.assertEqual(
            parse_key_words("toshkent, odam; mashina"),
            ["toshkent", "odam", "mashina"],
        )


class TestRequiredCount(unittest.TestCase):
    def test_required_3_of_7(self):
        # 3 ta so'z yetarli
        r = match_key_set("Toshkentdan odam bor, mashina kerak", SET7, required_count=3)
        self.assertTrue(r.is_match)
        self.assertIn("toshkent", r.matched_words)

    def test_below_required_no_match(self):
        # atigi 2 ta topildi, shart 3 ta — xabar berilmaydi
        r = match_key_set("Toshkentdan odam bor", SET7, required_count=3)
        self.assertFalse(r.is_match)

    def test_required_2_of_4(self):
        r = match_key_set("Odam bor, mashina bormi?", SET4, required_count=2)
        self.assertTrue(r.is_match)

    def test_below_required_2_no_match(self):
        r = match_key_set("Faqat odam bor", SET4, required_count=2)
        self.assertFalse(r.is_match)
        self.assertEqual(r.matched_count, 1)

    def test_two_word_set_needs_both(self):
        r = match_key_set("Toshkentdan odam bor", "toshkent odam", required_count=2)
        self.assertTrue(r.is_match)
        r = match_key_set("Faqat odam bor", "toshkent odam", required_count=2)
        self.assertFalse(r.is_match)


class TestWordForms(unittest.TestCase):
    def test_plural_and_case_suffix(self):
        r = match_key_set("Toshkentga odamlar bor", SET4, required_count=2)
        self.assertTrue(r.is_match)

    def test_no_percent_attribute(self):
        r = match_key_set("Toshkent odam mashina", SET4, required_count=2)
        self.assertFalse(hasattr(r, "percent"))


class TestFindMatch(unittest.TestCase):
    def test_best_set_wins(self):
        sets = [
            (SET4, 2),   # 3 ta topiladi
            (SET7, 3),   # 5 ta topiladi — shu yutadi
        ]
        msg = "Toshkent samarqand odam mashina kerak bugun"
        result = find_match(msg, sets)
        self.assertIsNotNone(result)
        self.assertEqual(result.phrase, SET7)
        self.assertEqual(result.matched_count, 6)

    def test_no_match(self):
        self.assertIsNone(find_match("Salom, ishlar yaxshimi?", [(SET7, 3)]))

    def test_plain_strings_default_required_2(self):
        result = find_match("Toshkent odam", [SET4])
        self.assertIsNotNone(result)
        self.assertEqual(result.required_count, 2)

    def test_normalize_apostrophe(self):
        self.assertEqual(normalize_tokens("Bog‘dod ko'chasi"), ["bog'dod", "ko'chasi"])


if __name__ == "__main__":
    unittest.main()
