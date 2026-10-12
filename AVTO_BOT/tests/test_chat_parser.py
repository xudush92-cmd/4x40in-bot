import unittest

from chat_parser import extract_chat_targets, extract_invalid_telegram_links


class ExtractChatTargetsTests(unittest.TestCase):
    def test_extracts_multiple_links_from_noisy_text(self):
        text = (
            "Guruhlar ro'yxati:\n"
            "1) https://t.me/Auto_Guruh1,\n"
            "2. @auto_guruh2;\n"
            "3 - t.me/auto_guruh3.\n"
            "Shularni qo'shing, iltimos!"
        )
        self.assertEqual(
            extract_chat_targets(text),
            ["@auto_guruh1", "@auto_guruh2", "@auto_guruh3"],
        )

    def test_deduplicates_username_aliases(self):
        text = "@auto_guruh https://t.me/AUTO_GURUH t.me/auto_guruh"
        self.assertEqual(extract_chat_targets(text), ["@auto_guruh"])

    def test_extracts_links_separated_only_by_punctuation(self):
        self.assertEqual(
            extract_chat_targets("t.me/first_group,t.me/second_group;@third_group"),
            ["@first_group", "@second_group", "@third_group"],
        )

    def test_extracts_invites_and_marked_peer_ids(self):
        text = "Private: https://t.me/+AbCdEfGh1234 and ID -1001234567890"
        self.assertEqual(
            extract_chat_targets(text),
            ["invite:AbCdEfGh1234", "-1001234567890"],
        )

    def test_ignores_unrelated_urls_and_regular_numbers(self):
        text = "Hello 12345 https://example.com/a @bad https://t.me/c/123/456"
        self.assertEqual(extract_chat_targets(text), [])

    def test_reports_unsupported_telegram_message_links(self):
        self.assertEqual(
            extract_invalid_telegram_links("https://t.me/c/123/456, https://example.com"),
            ["https://t.me/c/123/456"],
        )

    def test_does_not_misread_tme_path_on_another_domain(self):
        text = "https://example.com/t.me/looks_like_a_group"
        self.assertEqual(extract_chat_targets(text), [])
        self.assertEqual(extract_invalid_telegram_links(text), [])

    def test_ignores_punctuation_and_duplicate_links(self):
        text = "(@auto_group), https://t.me/auto_group."
        self.assertEqual(extract_chat_targets(text), ["@auto_group"])


if __name__ == "__main__":
    unittest.main()
