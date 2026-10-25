"""Nazorat (o'qitish) rejimi testlari: navbat, slayd, vazn, maxfiylik.

`python -m unittest test_review -v` (yoki `python test_review.py`)
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ.setdefault("SCANNER_DB_PATH", _TMP.name)
os.environ.setdefault("ADMIN_ID", "777")
os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "x")
os.environ.setdefault("BOT_TOKEN", "1:x")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database as db  # noqa: E402
import review  # noqa: E402


def setUpModule():
    db.init_db()


def tearDownModule():
    try:
        os.unlink(_TMP.name)
    except OSError:
        pass


class Msg:
    """aiogram Message o'rnini bosuvchi."""

    def __init__(self, chat_id: int = 777, chat_type: str = "private"):
        self.texts: list[str] = []
        self.markups: list = []
        self.chat = type("C", (), {"id": chat_id, "type": chat_type})()
        self.from_user = type("U", (), {"id": 777})()

    async def answer(self, text, **kw):
        self.texts.append(text)
        self.markups.append(kw.get("reply_markup"))


class Cb:
    """aiogram CallbackQuery o'rnini bosuvchi."""

    def __init__(self, data: str):
        self.data = data
        self.answers: list[str] = []
        self.from_user = type("U", (), {"id": 777})()
        self.message = Msg(chat_id=-1001, chat_type="supergroup")

    async def _edit(self, text, **kw):
        self.message.texts.append(text)

    async def answer(self, text="", **kw):
        self.answers.append(text)


class State:
    async def clear(self):
        pass


class ReviewTestBase(unittest.IsolatedAsyncioTestCase):
    """Har test oldidan baza va API tozalanadi."""

    async def asyncSetUp(self):
        calls = self.calls = []
        next_id = self.next_id = [1000]

        async def fake_api(method, payload):
            calls.append((method, dict(payload)))
            if method == "sendMessage":
                next_id[0] += 1
                return {"message_id": next_id[0]}
            if method == "editMessageText":
                if payload.get("message_id") != review._message_id():
                    return None
                return {"message_id": payload["message_id"]}
            return None

        self._real_api = review._api
        review._api = fake_api
        with db.closing(db._connect()) as conn, conn:
            for table in ("phrases", "review_items", "lead_reviews", "settings",
                          "user_groups", "users"):
                try:
                    conn.execute(f"DELETE FROM {table}")
                except Exception:
                    pass
        # Tozalashdan KEYIN: aksariyat testlar uchun guruh allaqachon ulangan.
        review._set_message_id(None)
        review.set_review_chat(-1001)
        db.set_match_mode("weight")
        db.set_score_threshold(1.75)
        for word, weight in (("kerak", 3.0), ("iltimos", 1.0), ("reys", -3.0)):
            db.add_keyword_checked(word, weight=weight)

    async def asyncTearDown(self):
        review._api = self._real_api
        review.set_review_chat(0)

    def sent(self, kind: str) -> list[dict]:
        return [payload for method, payload in self.calls if method == kind]


class TestSchema(ReviewTestBase):
    def test_table_exists(self):
        with db.closing(db._connect()) as conn:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(review_items)")]
        self.assertIn("text", cols)
        self.assertIn("label", cols)

    def test_anonymized(self):
        """Egasi, ismi, telefoni, guruhi — saqlanmaydi."""
        with db.closing(db._connect()) as conn:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(review_items)")]
        for forbidden in ("owner_id", "user_id", "phone", "sender", "chat_id",
                          "group", "username"):
            self.assertNotIn(forbidden, cols)


class TestQueue(ReviewTestBase):
    async def test_enqueue_counts(self):
        await review.enqueue("menga mashina kerak iltimos", 4.0, 1.75, ["kerak"])
        await review.enqueue("2 joy bor tel 90", -1.0, 1.75, ["joy bor"])
        stats = db.review_stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["pending"], 2)

    async def test_first_slide_is_sent(self):
        await review.enqueue("menga mashina kerak iltimos", 4.0, 1.75,
                             ["kerak", "iltimos"])
        messages = self.sent("sendMessage")
        self.assertEqual(len(messages), 1)
        text = messages[0]["text"]
        self.assertIn("menga mashina kerak iltimos", text)
        self.assertIn("4", text)
        self.assertIn("1.75", text)

    async def test_second_item_edits_same_message(self):
        """Guruh to'lmaydi: yangi xabar emas, o'sha slayd tahrirlanadi."""
        await review.enqueue("birinchi", 2.0, 1.75, ["kerak"])
        await review.enqueue("ikkinchi", 2.0, 1.75, ["iltimos"])
        self.assertEqual(len(self.sent("sendMessage")), 1)
        self.assertEqual(len(self.sent("editMessageText")), 1)

    async def test_next_item_is_oldest_pending(self):
        first = await review.enqueue("birinchi", 2.0, 1.75, ["kerak"])
        await review.enqueue("ikkinchi", 2.0, 1.75, ["iltimos"])
        self.assertEqual(db.get_next_review_item()[0], first)

    async def test_empty_queue_message(self):
        await review.refresh()
        text = self.sent("sendMessage")[-1]["text"]
        self.assertIn("Navbat bo'sh", text)


class TestLabeling(ReviewTestBase):
    async def test_ok_strengthens_weights(self):
        item = await review.enqueue("menga mashina kerak iltimos", 4.0, 1.75,
                                    ["kerak", "iltimos"])
        before = db.get_phrase(db.word_id_by_text("kerak"))[2]
        status, changes, stats = await review.label(item, "ok")
        self.assertEqual(status, "ok")
        self.assertEqual(db.get_phrase(db.word_id_by_text("kerak"))[2], before + 0.25)
        self.assertEqual(db.get_phrase(db.word_id_by_text("iltimos"))[2], 1.25)
        self.assertEqual(stats["pending"], 0)

    async def test_bad_weakens_only_positive(self):
        item = await review.enqueue("reys kerak", 0.0, 1.75, ["kerak", "reys"])
        kerak = db.get_phrase(db.word_id_by_text("kerak"))[2]
        reys = db.get_phrase(db.word_id_by_text("reys"))[2]
        await review.label(item, "bad")
        self.assertEqual(db.get_phrase(db.word_id_by_text("kerak"))[2], kerak - 0.25)
        self.assertEqual(db.get_phrase(db.word_id_by_text("reys"))[2], reys)

    async def test_skip_keeps_weights(self):
        item = await review.enqueue("kerak", 0.0, 1.75, ["kerak"])
        before = db.get_phrase(db.word_id_by_text("kerak"))[2]
        status, changes, _stats = await review.label(item, "skip")
        self.assertEqual(status, "ok")
        self.assertEqual(changes, [])
        self.assertEqual(db.get_phrase(db.word_id_by_text("kerak"))[2], before)

    async def test_second_vote_is_ignored(self):
        item = await review.enqueue("kerak", 0.0, 1.75, ["kerak"])
        await review.label(item, "ok")
        weight = db.get_phrase(db.word_id_by_text("kerak"))[2]
        status, changes, _stats = await review.label(item, "bad")
        self.assertEqual(status, "done")
        self.assertEqual(changes, [])
        self.assertEqual(db.get_phrase(db.word_id_by_text("kerak"))[2], weight)

    async def test_unknown_item(self):
        status, _changes, _stats = await review.label(999999, "ok")
        self.assertEqual(status, "missing")

    async def test_bad_choice(self):
        item = await review.enqueue("kerak", 0.0, 1.75, ["kerak"])
        status, _changes, _stats = await review.label(item, "hack")
        self.assertEqual(status, "bad-choice")
        self.assertIsNone(db.get_review_item(item)[5])

    async def test_label_turns_slide_to_next(self):
        item = await review.enqueue("kerak", 0.0, 1.75, ["kerak"])
        callback = Cb(f"rv:ok:{item}")
        from bot import review_callback
        await review_callback(callback, State())
        self.assertEqual(db.get_review_item(item)[5], "ok")
        # Slayd yangilandi (tahrir orqali) — endi navbat bo'sh.
        edits = self.sent("editMessageText")
        self.assertTrue(edits, "slayd yangilanmadi")
        self.assertIn("Navbat bo'sh", edits[-1]["text"])


class TestStats(ReviewTestBase):
    async def test_stats_counter(self):
        a = await review.enqueue("kerak", 2.0, 1.75, ["kerak"])
        b = await review.enqueue("reys", 2.0, 1.75, ["reys"])
        c = await review.enqueue("ketadi", 2.0, 1.75, ["kerak"])
        await review.label(a, "ok")
        await review.label(b, "bad")
        await review.label(c, "skip")
        stats = db.review_stats()
        self.assertEqual((stats["ok"], stats["bad"], stats["skip"]), (1, 1, 1))
        self.assertEqual(stats["pending"], 0)
        self.assertEqual(stats["total"], 3)

    def test_stats_text(self):
        self.assertIn("Nazorat statistikasi", review.stats_text())


class TestSetup(ReviewTestBase):
    async def test_group_becomes_review_chat(self):
        from bot import review_start
        message = Msg(chat_id=-1001, chat_type="supergroup")
        await review_start(message, State())
        self.assertEqual(review.review_chat_id(), -1001)
        self.assertIn("nazorat guruhi qilib belgilandi", message.texts[-1])
        self.assertEqual(len(self.sent("sendMessage")), 1)

    async def test_private_chat_is_refused(self):
        from bot import review_start
        review.set_review_chat(0)
        message = Msg(chat_id=777, chat_type="private")
        await review_start(message, State())
        self.assertIn("guruhda", message.texts[-1])
        self.assertFalse(review.review_chat_id())

    async def test_stop_disables(self):
        from bot import review_stop
        message = Msg()
        await review_stop(message, State())
        self.assertFalse(review.review_chat_id())
        before = len(self.calls)
        await review.enqueue("kerak", 0.0, 1.75, ["kerak"])
        self.assertEqual(len(self.calls), before)

    async def test_deleted_slide_is_resent(self):
        review._set_message_id(1)

        async def dead_api(method, payload):
            self.calls.append((method, dict(payload)))
            if method == "editMessageText":
                return None
            self.next_id[0] += 1
            return {"message_id": self.next_id[0]}

        review._api = dead_api
        await review.enqueue("kerak", 0.0, 1.75, ["kerak"])
        self.assertEqual(len(self.sent("sendMessage")), 1)
        self.assertEqual(review._message_id(), self.next_id[0])


class TestUserFeedbackIsStatsOnly(ReviewTestBase):
    async def test_user_vote_does_not_change_weights(self):
        """Foydalanuvchi ✅/❌ bosadi — vazn o'zgarmaydi, faqat statistika."""
        import feedback as fb
        review_id = db.save_lead_review(555, ["kerak"])
        before = db.get_phrase(db.word_id_by_text("kerak"))[2]
        status = fb.record_vote(review_id, True)
        self.assertEqual(status, "ok")
        self.assertEqual(db.get_phrase(db.word_id_by_text("kerak"))[2], before)
        stats = db.get_feedback_stats()
        self.assertEqual(stats["useful"], 1)

    async def test_admin_vote_changes_weights(self):
        """Admin bosadi — vazn o'zgaradi (yagona o'quv manbasi)."""
        import feedback as fb
        review_id = db.save_lead_review(777, ["kerak"])
        before = db.get_phrase(db.word_id_by_text("kerak"))[2]
        status, changes = fb.apply_feedback(review_id, True)
        self.assertEqual(status, "ok")
        self.assertEqual(db.get_phrase(db.word_id_by_text("kerak"))[2], before + 0.25)

    async def test_user_vote_twice_is_ignored(self):
        import feedback as fb
        review_id = db.save_lead_review(555, ["kerak"])
        self.assertEqual(fb.record_vote(review_id, False), "ok")
        self.assertEqual(fb.record_vote(review_id, False), "done")


if __name__ == "__main__":
    unittest.main(verbosity=2)
