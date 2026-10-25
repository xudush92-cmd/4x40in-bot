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
    score_text,
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

    def test_more_specific_key_wins_for_same_token(self):
        r = match_keywords("borm", ["bor", "borm"], required_count=1)
        self.assertEqual(r.matched_words, ["borm"])
        self.assertEqual(r.matched_count, 1)

    def test_separate_occurrences_can_match_separate_keys(self):
        r = match_keywords("bor borm", ["bor", "borm"], required_count=2)
        self.assertEqual(r.matched_words, ["bor", "borm"])
        self.assertTrue(r.is_match)

    def test_spelling_aliases_count_as_one_keyword(self):
        r = match_keywords("jonat", ["jo'nat", "jonat"], required_count=1)
        self.assertEqual(r.matched_count, 1)

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
        # Diqqat: ``bormi`` kaliti endi oddiy ``bor`` bilan tenglashtirilmaydi
        # (quyidagi TestQuestionKeyRequired), shuning uchun mijoz savoli
        # so'roq shaklida yozilgan variantlar sinaladi.
        client = ["bormi", "kerak", "kimga"]
        keys = ["toshkent", "xorazm", "odam", "kishi", "posilka", "dona"]
        for text in (
            "Toshkentdan xorazimga 2 odam bor, mashina bormi",
            "Toshkentdan Xorazmga 2 dona posilka bor, kimga topshiraman",
        ):
            self.assertEqual(find_stop_words(text, stop), [])
            self.assertTrue(find_client_words(text, client))
            self.assertTrue(match_keywords(text, keys, required_count=3).is_match)
        # Haydovchining "2 odam bor" e'loni endi mijoz kaliti bilan
        # belgilanmaydi — bu ataylab shunday.
        self.assertEqual(
            find_client_words("Toshkentdan xorazimga 2 odam bor", ["bormi"]), []
        )

    def test_driver_message_still_blocked(self):
        stop = ["olamiz", "chiqamiz", "boramiz", "ketamiz"]
        text = "Toshkentdan Xorazmga odam olamiz, 2 kishi, bugun chiqamiz"
        self.assertTrue(find_stop_words(text, stop))


class TestLazyCyrillic(unittest.TestCase):
    """O'zbek kirill alifbosini "dangasa" yozish ham tanilishi kerak.

    Odamlar ў→у, қ→к, ғ→г, ҳ→х deb yozadi.
    """

    def test_lazy_cyrillic_matches_latin_key(self):
        for text in ("қарши", "карши", "ҚАРШИ"):
            self.assertTrue(find_stop_words(text, ["qarshi"]), text)
        for text in ("ҳозир", "хозир", "ХОЗИР"):
            self.assertTrue(find_stop_words(text, ["hozir"]), text)
        for text in ("жўнаймиз", "жунаймиз"):
            self.assertTrue(find_stop_words(text, ["jo'naymiz"]), text)

    def test_lazy_cyrillic_in_keywords(self):
        keys = ["toshkent", "xorazm", "pochta"]
        text = "Тошкентдан Хоразмга почта бор, ким олиб кетади"
        r = match_keywords(text, keys, required_count=3)
        self.assertEqual(sorted(r.matched_words), ["pochta", "toshkent", "xorazm"])

    def test_apostrophe_forms_still_match(self):
        self.assertTrue(find_stop_words("бўш жойимиз", ["bo'sh joyimiz"]))
        self.assertTrue(find_stop_words("bo'sh joy", ["bo'sh joy"]))


class TestVerbPerson(unittest.TestCase):
    """1-shaxs (biz) va 2-shaxs (siz) aralashtirilmaydi."""

    def test_first_person_forms_match(self):
        self.assertTrue(find_stop_words("olaman", ["olamiz"]))
        self.assertTrue(find_stop_words("ketaman", ["ketamiz"]))
        self.assertTrue(find_stop_words("Жўнайман", ["jo'naymiz"]))

    def test_first_and_second_person_do_not_match(self):
        self.assertEqual(find_stop_words("жўнайсиз", ["jo'naymiz"]), [])
        self.assertEqual(find_stop_words("ketaсиз", ["ketamiz"]), [])
        self.assertEqual(find_stop_words("borasiz", ["boramiz"]), [])

    def test_client_question_not_blocked_by_driver_form(self):
        # Mijoz "qachon jo'nasiz?" deb so'raydi — haydovchining
        # "jo'naymiz" stop-so'zi buni bloklamasligi kerak.
        text = "Тошкентдан Хоразмга 2 одам бор, қачон жўнайсизлар"
        self.assertEqual(find_stop_words(text, ["jo'naymiz"]), [])

    def test_intent_and_present_forms_do_not_match(self):
        # "jo'natmoqchiman" (mijoz niyati) "jo'natamiz" (haydovchi) bilan
        # tenglashtirilmaydi.
        text = "Тошкентдан Хоразмга посилка жўнатмоқчиман, 3 дона"
        self.assertEqual(find_stop_words(text, ["jo'natamiz"]), [])
        self.assertTrue(find_client_words(text, ["jo'natmoqchiman"]))


class TestVariantCollapse(unittest.TestCase):
    """Bitta so'zning ikki yozuvi xabarda ikki marta sanalmasin."""

    def score(self, text, entries):
        return score_text(text, entries, threshold=1.75)

    def test_apostrophe_variants_counted_once(self):
        # jo'nat va jonat — bir so'zning ikki yozilishi
        r = self.score("Posilka jo'natamiz", [("jo'nat", 3.0), ("jonat", 3.0)])
        self.assertEqual(r.score, 3.0, r.positives)
        self.assertEqual(len(r.positives), 1)

    def test_different_words_not_collapsed(self):
        r = self.score("yukim bor", [("yo'q", -3.0), ("yuk", 3.0)])
        self.assertEqual(r.score, 3.0, r.positives)
        self.assertEqual(list(r.positives), ["yuk"])

    def test_bosh_and_bosh_collapse(self):
        # ``bosh`` va ``bo'sh`` — yaqin shakllar; ikki tomonda tursa ham
        # faqat bittasi ishlaydi (kuchlirog'i).
        r = self.score("bo'sh joy", [("bo'sh", -2.5), ("bosh", 1.0)])
        self.assertEqual(len(r.positives) + len(r.negatives), 1)
        self.assertEqual(r.score, -2.5)

    def test_opposite_signs_do_not_cancel(self):
        # +3 va -3 bir-birini bekor qilmasin — kuchliroq/manfiy qoladi
        r = self.score("jo'natamiz", [("jo'nat", 3.0), ("jonat", -1.0)])
        self.assertEqual(r.score, 3.0, (r.positives, r.negatives))

    def test_strongest_negative_kept(self):
        r = self.score("jo'natamiz", [("jonat", -2.0), ("jo'nat", -4.0)])
        self.assertEqual(r.score, -4.0, r.negatives)

    def test_multiword_entries(self):
        r = self.score("joy bor edi", [("joy bor", -4.0), ("joy bo'r", -3.0)])
        self.assertEqual(r.score, -4.0, r.negatives)

    def test_unrelated_entries_all_count(self):
        r = self.score("mashina kerak iltimos", [("kerak", 3.0), ("iltimos", 1.0)])
        self.assertEqual(r.score, 4.0, r.positives)


class TestQuestionParticle(unittest.TestCase):
    """"жой бор" (haydovchi e'loni) va "жой борми" (mijoz savoli) farqi."""

    STOP = ["joy bor", "bor joyimiz"]
    CLIENT = ["bormi", "joy kerak"]

    def test_driver_statement_blocked(self):
        self.assertTrue(find_stop_words("Тошкент Хоразм 2 жой бор", self.STOP))
        self.assertTrue(find_stop_words("Toshkent Xorazm 2 joy bor", self.STOP))

    def test_client_question_not_blocked(self):
        self.assertEqual(find_stop_words("Тошкент Хоразм 2 жой борми?", self.STOP), [])
        self.assertEqual(find_stop_words("Toshkent Xorazm joy bormi?", self.STOP), [])
        self.assertTrue(find_client_words("Toshkent Xorazm joy bormi?", self.CLIENT))

    def test_bare_stop_word_does_not_block_question(self):
        # Yakka "бор" stop-so'zi so'roq shaklini bloklamaydi — aks holda
        # "жой борми?" kabi mijoz savollari yo'qolardi.
        self.assertEqual(find_stop_words("жой борми?", ["бор"]), [])
        self.assertTrue(find_stop_words("жой бор", ["бор"]))


class TestLargeKeywordList(unittest.TestCase):
    """Indeks katta ro'yxatda ham to'g'ri ishlashi kerak."""

    def test_2000_keywords_still_match(self):
        keys = ["toshkent", "xorazm", "posilka"] + ["soz%04d" % i for i in range(2000)]
        text = "Тошкентдан Хоразмга 2 дона посилка бор"
        r = match_keywords(text, keys, required_count=3)
        self.assertEqual(sorted(r.matched_words), ["posilka", "toshkent", "xorazm"])

    def test_no_false_positive_from_padding(self):
        keys = ["toshkent", "soz0001"]
        self.assertEqual(match_keywords("об-ҳаво қандай", keys, 1).matched_count, 0)


class TestApostropheFoldGuard(unittest.TestCase):
    """Qisqa so'zlarda ``o'``->``u`` almashtirilmasligi kerak.

    Aks holda ``yo'q`` kaliti xabardagi ``yuk``/``yukim`` so'zini tutib
    oladi — domenda ``yuk`` eng ko'p uchraydigan so'z.
    """

    def test_yoq_does_not_match_yuk(self):
        for text in ("yuk bor", "yukim katta", "yuklar keldi", "2 tonna yuk"):
            self.assertEqual(
                match_keywords(text, ["yo'q"], 1).matched_count, 0, text
            )

    def test_yoq_still_matches_itself(self):
        for text in ("yo'q", "yoq", "йўқ", "YO'Q"):
            self.assertEqual(
                match_keywords(text, ["yo'q"], 1).matched_count, 1, text
            )

    def test_dumb_cyrillic_ambiguity_is_not_guessed(self):
        # "йук" — "dangasa" yozuvda ham "йўқ" (yo'q), ham "юк" (yuk) bo'lishi
        # mumkin. Noaniqlikni taxmin qilmaymiz: "yo'q" kaliti uni tutmaydi,
        # "yuk" kaliti esa tutadi.
        self.assertEqual(match_keywords("йук", ["yo'q"], 1).matched_count, 0)
        self.assertEqual(match_keywords("йук", ["yuk"], 1).matched_count, 1)

    def test_canonical_keeps_yoq_and_yuk_apart(self):
        # Takror tekshiruvi ham ularni bir xil deb hisoblamasligi kerak,
        # aks holda admin "yuk" kalitini qo'sha olmaydi.
        self.assertNotEqual(canonical_entry("yo'q"), canonical_entry("yuk"))
        self.assertEqual(canonical_entry("yo'q"), canonical_entry("йўқ"))

    def test_other_short_collisions_closed(self):
        self.assertEqual(match_keywords("tuk keldi", ["to'q"], 1).matched_count, 0)
        self.assertEqual(match_keywords("bush joy", ["bo'sh"], 1).matched_count, 1)

    def test_long_latin_words_keep_dumb_cyrillic_match(self):
        # Uzun so'zlarda o'->u saqlanadi: lotin kalit "dangasa" kirill
        # yozuvini ham topadi.
        self.assertEqual(match_keywords("жунат", ["jo'nat"], 1).matched_count, 1)
        self.assertEqual(match_keywords("жунаймиз", ["jo'naymiz"], 1).matched_count, 1)

    def test_driver_word_still_found(self):
        self.assertEqual(match_keywords("yuk bor", ["yuk"], 1).matched_count, 1)


class TestQuestionKeyRequired(unittest.TestCase):
    """``bormi`` kaliti faqat so'roq shaklini topadi, ``bor`` ni emas."""

    def test_question_key_ignores_statement(self):
        for text in ("2 joy bor", "Toshkent Xorazm joy bor", "2 odam bor"):
            self.assertEqual(
                match_keywords(text, ["bormi"], 1).matched_count, 0, text
            )

    def test_question_key_matches_question(self):
        for text in ("joy bormi", "joy bormi?", "жой борми", "mashina bormi"):
            self.assertEqual(
                match_keywords(text, ["bormi"], 1).matched_count, 1, text
            )

    def test_base_key_still_matches_question(self):
        # Teskari yo'nalish ochiq: ``kerak`` kaliti ``kerakmi`` ni topadi.
        self.assertEqual(match_keywords("mashina kerakmi", ["kerak"], 1).matched_count, 1)


class TestShortWordPrefixGuard(unittest.TestCase):
    """Uzunroq kalit 3 harfli olmoshni "yuqtirib" olmasligi kerak."""

    def test_menga_does_not_match_men(self):
        self.assertEqual(
            find_client_words("men ham shu sohada ishlayman", ["menga"]), []
        )

    def test_menga_matches_itself(self):
        self.assertTrue(find_client_words("menga mashina kerak", ["menga"]))

    def test_normal_stem_match_kept(self):
        self.assertTrue(find_client_words("bugun ketad", ["ketadi"]))


if __name__ == "__main__":
    unittest.main()
