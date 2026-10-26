"""O'rganuvchi navbat o'chirilganini va alohida feedback saqlanganini tekshiradi."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["SCANNER_DB_PATH"] = _TMP.name
os.environ.setdefault("ADMIN_ID", "777")
os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "x")
os.environ.setdefault("BOT_TOKEN", "1:x")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database as db  # noqa: E402
import feedback as fb  # noqa: E402
import review  # noqa: E402 — faqat avvalgi slaydni yangilanishda yopish uchun


def setUpModule():
    db.init_db()


def tearDownModule():
    try:
        os.unlink(_TMP.name)
    except OSError:
        pass


class TrainingQueueDisabled(unittest.TestCase):
    def test_admin_menu_no_longer_shows_training_panel(self):
        from bot import admin_panel_keyboard

        labels = [button.text for row in admin_panel_keyboard() for button in row]
        self.assertFalse(any("Nazorat" in label or "baholash" in label for label in labels))

    def test_training_handlers_are_not_registered(self):
        import bot

        for name in ("review_start", "open_review_panel", "review_callback", "review_stop"):
            self.assertFalse(hasattr(bot, name), name)

    def test_scanner_has_no_training_queue_hook(self):
        import scanner_manager

        self.assertFalse(hasattr(scanner_manager, "review"))
        self.assertFalse(hasattr(scanner_manager, "_queue_near_miss"))

    def test_upgrade_closes_old_training_slide(self):
        async def fake_api(method, payload):
            return {"message_id": payload.get("message_id")}

        review.set_review_chat(777)
        review._set_message_id(123)
        with patch.object(review, "_api", new=AsyncMock(side_effect=fake_api)) as api:
            import asyncio
            asyncio.run(review.disable())
        self.assertFalse(review.review_chat_id())
        self.assertIsNone(review._message_id())
        api.assert_awaited_once()
        self.assertEqual(api.await_args.args[0], "editMessageText")


class FeedbackRemainsSeparate(unittest.TestCase):
    def setUp(self):
        with db.closing(db._connect()) as conn, conn:
            conn.execute("DELETE FROM phrases")
            conn.execute("DELETE FROM lead_reviews")
        db.add_keyword_checked("kerak", weight=3.0)

    def _weight(self):
        return db.get_phrase(db.word_id_by_text("kerak"))[2]

    def test_user_feedback_changes_statistics_only(self):
        review_id = db.save_lead_review(555, ["kerak"])
        before = self._weight()
        self.assertEqual(fb.record_vote(review_id, True), "ok")
        self.assertEqual(self._weight(), before)
        self.assertEqual(db.get_feedback_stats()["useful"], 1)

    def test_admin_feedback_can_still_adjust_weight(self):
        review_id = db.save_lead_review(777, ["kerak"])
        before = self._weight()
        status, changes = fb.apply_feedback(review_id, True)
        self.assertEqual(status, "ok")
        self.assertTrue(changes)
        self.assertGreater(self._weight(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
