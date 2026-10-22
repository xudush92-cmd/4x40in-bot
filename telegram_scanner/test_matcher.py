"""Matcher testlari: kalitlar cheksiz, admin soni bo'yicha.
python -m unittest test_matcher -v"""
import unittest

from matcher import (
    canonical_entry,
    contains_emoji,
    find_client_words,
    find_match,
    find_stop_words,
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


class TestCyrillic(unittest.TestCase):
    """Lotin kalit kirill xabarni, kirill kalit lotin xabarni topadi."""

    def test_latin_keys_cyrillic_message(self):
        r = match_keywords("Тошкентдан одам керак, машина бор", KEYWORDS, required_count=3)
        self.assertTrue(r.is_match)
        self.assertGreaterEqual(r.matched_count, 3)

    def test_cyrillic_keys_latin_message(self):
        cyr_keys = ["тошкент", "одам", "керак", "машина"]
        r = match_keywords("Toshkentdan odam kerak, mashina bor", cyr_keys, required_count=3)
        self.assertTrue(r.is_match)

    def test_cyrillic_forms_and_case(self):
        r = match_keywords("ТОШКЕНТГА одамлар керакми", KEYWORDS, required_count=3)
        self.assertTrue(r.is_match)

    def test_cyrillic_below_count(self):
        self.assertIsNone(find_match("Тошкентдан одам бор", KEYWORDS, required_count=3))

    def test_uzbek_specific_letters(self):
        # ў (o'), ғ (g'), қ (q), ҳ (h)
        keys = ["o'zbekiston", "g'olib", "qishloq", "hozir"]
        r = match_keywords("Ўзбекистон ғолиб, қишлоқ ҳозир", keys, required_count=3)
        self.assertTrue(r.is_match)


class TestDriverFilter(unittest.TestCase):
    """Suratlardagi haydovchi e'lonlari bloklanishi, mijoz o'tishi kerak."""

    STOP = ["olamiz", "olomiz", "chiqamiz", "kelishamiz", "kobalt",
            "jentra", "lacetti", "losetti", "konditsioner", "kondisaner",
            "pochta olamiz", "odam garak", "getamiz"]
    CLIENT = ["bormi", "kerak", "garak", "joy kerak", "ketmoqchiman"]
    KEYS = ["toshkent", "xorazm", "odam", "mashina", "kerak", "yuk", "pochta"]

    def test_driver_cyrillic_emoji_blocked(self):
        text = ("👉🏢 ТОШКЕНТДАН 👉🕌 ХОРАЗИМГА 👉🛣 ЙУЛГА ЧИКАМИЗ "
                "👉👫 2 ОДАМ ОЛАМИЗ 👉📦 ПОЧТА ОЛАМИЗ 👉💵 ПУЛИНИ "
                "КЕЛИШАМИЗ 🚗 МАШИНА КОБАЛЬТ ☎️ +998")
        self.assertTrue(find_stop_words(text, self.STOP))

    def test_driver_mixed_typos_blocked(self):
        text = ("Sróshni getamiz ‼️ Toshkentdan Xorazmga getamiz "
                "2 Odom kerak PÓSHTO OLOMIZ avto JENTRA")
        self.assertTrue(find_stop_words(text, self.STOP))

    def test_driver_losetti_blocked(self):
        text = "СРОЧНИ 2-ОДАМ ГАРАК ПОЧТА ОЛАМИЗ ЛОСЕТТИ (камфорт) НАРХИНИ КЕЛИШАМИЗ"
        self.assertTrue(find_stop_words(text, self.STOP))

    def test_client_passes(self):
        text = "ТОШКЕНТДАН ХОРАЗМГА МАШИНА БОРМИ? 2 ТА ЖОЙ КЕРАК"
        self.assertFalse(find_stop_words(text, self.STOP))
        self.assertTrue(find_client_words(text, self.CLIENT))
        r = match_keywords(text, self.KEYS, required_count=3)
        self.assertTrue(r.is_match)

    def test_client_latin(self):
        text = "Xorazmga ketmoqchiman, mashina kerak"
        self.assertFalse(find_stop_words(text, self.STOP))
        self.assertTrue(find_client_words(text, self.CLIENT))


class TestEmojiAndDuplicates(unittest.TestCase):
    def test_emoji_detection(self):
        self.assertTrue(contains_emoji("Toshkentga mashina kerak 🚕"))
        self.assertTrue(contains_emoji("☎️ +998901234567"))
        self.assertFalse(contains_emoji("Toshkentga mashina kerak"))
        self.assertFalse(contains_emoji(""))

    def test_canonical_duplicates(self):
        self.assertEqual(canonical_entry("ТОШКЕНТ"), canonical_entry("toshkent"))
        self.assertEqual(canonical_entry("  ОДАМ   ОЛАМИЗ! "), "odam olamiz")
        self.assertEqual(canonical_entry("Bog‘dod"), canonical_entry("bog'dod"))


class TestShortWordGuard(unittest.TestCase):
    """Qisqa so'z uzun yozuvni "yuqtirib" olmasligi kerak.

    ``boramiz`` stop-so'zi xabardagi oddiy ``bor`` so'zini tutsa,
    "posilka bor" kabi mijoz xabarlari bloklanib qolardi.
    """

    def test_long_stop_does_not_match_short_word(self):
        self.assertEqual(find_stop_words("Toshkentdan 2 odam bor", ["boramiz"]), [])
        self.assertEqual(find_stop_words("posilka bor", ["boraman"]), [])
        # "ketadi" kabi uzunroq yozuv qisqa "ketad" xabar so'zini tutaveradi
        self.assertTrue(find_stop_words("bugun ketad", ["ketadi"]))

    def test_exact_and_stem_match_still_work(self):
        self.assertTrue(find_stop_words("ertaga chiqamiz", ["chiqamiz"]))
        self.assertTrue(find_stop_words("2 odam olamiz", ["olamiz"]))
        self.assertTrue(find_client_words("mashina kerak", ["kerak"]))
        self.assertTrue(find_client_words("mashina kerakm", ["kerak"]))

    def test_client_short_message_passes_filters(self):
        stop = ["olamiz", "chiqamiz", "boramiz", "ketamiz"]
        client = ["bormi", "kerak", "kimga"]
        keys = ["toshkent", "xorazm", "odam", "kishi", "posilka", "dona"]
        for text in (
            "Toshkentdan xorazimga 2 odam bor",
            "Toshkentdan Xorazmga 2 dona posilka bor, kimga topshiraman",
        ):
            self.assertEqual(find_stop_words(text, stop), [])
            self.assertTrue(find_client_words(text, client))
            self.assertTrue(match_keywords(text, keys, required_count=3).is_match)

    def test_driver_message_still_blocked(self):
        stop = ["olamiz", "chiqamiz", "boramiz", "ketamiz"]
        text = "Toshkentdan Xorazmga odam olamiz, 2 kishi, bugun chiqamiz"
        self.assertTrue(find_stop_words(text, stop))


if __name__ == "__main__":
    unittest.main()
