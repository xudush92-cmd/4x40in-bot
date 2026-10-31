"""Bildirishnoma formatlari: sanash va vazn rejimlari."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ADMIN_ID", "777")
os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "x")
os.environ.setdefault("BOT_TOKEN", "1:x")

from notifier import build_notification_text, build_profile_link  # noqa: E402


class TestNotificationText(unittest.TestCase):
    def _build(self, **overrides):
        values = {
            "group_title": "Test guruh",
            "sender_name": "Ali",
            "username": "@alice",
            "user_id": 123,
            "phone": "Matnda ko'rsatilmagan",
            "raw_text": "mashina kerak",
            "matched_words": ["mashina", "kerak"],
            "required_count": 2,
            "message_link": None,
        }
        values.update(overrides)
        return build_notification_text(**values)

    def test_profile_link_prefers_public_username_https(self):
        text = self._build()
        self.assertIn('href="https://t.me/alice"', text)
        self.assertNotIn("tg://user?id=", text)
        self.assertEqual(build_profile_link("@ali_123"), "https://t.me/ali_123")

    def test_missing_username_does_not_emit_privacy_sensitive_tg_link(self):
        text = self._build(username="Yo'q")
        self.assertNotIn("tg://user?id=", text)
        self.assertIn("guruhdagi asl xabarni oching", text)
        self.assertIsNone(build_profile_link("Yo'q"))

    def test_count_mode_shows_count_requirement(self):
        text = self._build(match_mode="count", required_count=2)
        self.assertIn("kamida 2 ta — bajarildi", text)
        self.assertNotIn("⚖️ <b>Ball:</b>", text)

    def test_weight_mode_shows_score_not_zero_count(self):
        text = self._build(
            match_mode="weight",
            required_count=0,
            score=4.25,
            score_threshold=2.0,
            positive_weights={"mashina": 1.0, "kerak": 3.25},
        )
        self.assertIn("⚖️ <b>Ball:</b> 4.25 / 2 — o'tdi", text)
        self.assertIn("🔎 <b>Mosgan vaznlar:</b> +1 mashina, +3.25 kerak", text)
        self.assertNotIn("kamida 0 ta", text)

    def test_weight_mode_lists_negative_signals_and_escapes(self):
        text = self._build(
            match_mode="weight",
            score=0.0,
            score_threshold=2.0,
            positive_weights={"<kerak>": 2.0},
            negative_weights={"kerak emas": -3.0},
        )
        self.assertIn("+2 &lt;kerak&gt;", text)
        self.assertIn("-3 kerak emas", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
