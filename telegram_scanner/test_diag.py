"""🧾 Diagnostika va 👁 Kuzatuv testlari.

`python test_diag.py`
"""
from __future__ import annotations

import logging
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("ADMIN_ID", "777")
os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "x")
os.environ.setdefault("BOT_TOKEN", "1:x")

import logbuffer  # noqa: E402
import watch  # noqa: E402


class TestLogBuffer(unittest.TestCase):
    def setUp(self):
        logbuffer.clear()
        logbuffer.install()
        self.log = logging.getLogger("test.diag")

    def test_lines_are_collected(self):
        self.log.info("birinchi qator")
        self.log.info("ikkinchi qator")
        tail = logbuffer.tail(10)
        self.assertIn("birinchi qator", tail)
        self.assertIn("ikkinchi qator", tail)

    def test_tail_limits_count(self):
        for i in range(50):
            self.log.info("qator-%s", i)
        lines = logbuffer.tail(5).splitlines()
        self.assertEqual(len(lines), 5)
        self.assertIn("qator-49", lines[-1])

    def test_phone_is_redacted(self):
        self.log.info("aloqa 90 123 45 67 va +998 93 111 22 33")
        tail = logbuffer.tail(5)
        self.assertIn("[raqam]", tail)
        self.assertNotIn("90 123 45 67", tail)
        self.assertNotIn("93 111 22 33", tail)

    def test_scores_are_not_redacted(self):
        self.log.info("ball=4/1.75, chegara 1.75, +3 kerak, 2 kishi")
        tail = logbuffer.tail(5)
        self.assertIn("ball=4/1.75", tail)
        self.assertIn("2 kishi", tail)

    def test_install_is_idempotent(self):
        before = len(logging.getLogger().handlers)
        logbuffer.install()
        logbuffer.install()
        self.assertEqual(len(logging.getLogger().handlers), before)

    def test_clear(self):
        self.log.info("nima bo'lsa ham")
        logbuffer.clear()
        self.assertEqual(logbuffer.size(), 0)


class TestRedact(unittest.TestCase):
    def test_short_numbers_kept(self):
        self.assertEqual(logbuffer.redact("2 joy bor"), "2 joy bor")

    def test_long_number_masked(self):
        self.assertEqual(logbuffer.redact("tel 901234567"), "tel [raqam]")

    def test_phone_with_spaces(self):
        self.assertIn("[raqam]", logbuffer.redact("+998 90 123 45 67"))


class TestRedactDetails(unittest.TestCase):
    """Redakt qatorlarni buzmasligi va texnik ID larni saqlashi kerak."""

    def test_newlines_are_not_swallowed(self):
        text = "qator 25.10 12:31:00 I x\nkeyingi qator 12:31:01"
        self.assertEqual(logbuffer.redact(text), text)

    def test_technical_ids_kept(self):
        for line in (
            "[SCAN] skip owner=777 chat=-1001234567890",
            "bot id=123456789 - 'WPION'",
            "update id=555123456 handled",
        ):
            self.assertEqual(logbuffer.redact(line), line)

    def test_phone_still_masked(self):
        self.assertEqual(logbuffer.redact("tel 901234567"), "tel [raqam]")
        self.assertEqual(logbuffer.redact("tel:+998901234567"), "tel:[raqam]")


class TestSingleSession(unittest.IsolatedAsyncioTestCase):
    """Sessiya ikki marta ko'tarilmaydi (ikki marta xabar ketmasin)."""

    async def asyncSetUp(self):
        import scanner_manager

        self.sm = scanner_manager
        scanner_manager._clients.clear()
        scanner_manager._starting.clear()
        self.real = scanner_manager._start_user_client
        self.calls = []

    async def asyncTearDown(self):
        self.sm._start_user_client = self.real
        self.sm._clients.clear()
        self.sm._starting.clear()

    async def test_concurrent_start_once(self):
        import asyncio

        async def fake(owner_id):
            self.calls.append(owner_id)
            await asyncio.sleep(0.05)   # ulanish "davom etmoqda"
            return True

        self.sm._start_user_client = fake
        results = await asyncio.gather(
            self.sm.start_user_client(777),
            self.sm.start_user_client(777),
            self.sm.start_user_client(777),
        )
        self.assertEqual(self.calls, [777])
        self.assertEqual(results, [True, True, True])

    async def test_flag_cleared_after_error(self):
        async def boom(owner_id):
            raise RuntimeError("tarmoq")

        self.sm._start_user_client = boom
        with self.assertRaises(RuntimeError):
            await self.sm.start_user_client(777)
        self.assertFalse(self.sm._starting)

        async def ok(owner_id):
            self.calls.append(owner_id)
            return True

        self.sm._start_user_client = ok
        self.assertTrue(await self.sm.start_user_client(777))
        self.assertEqual(self.calls, [777])

    async def test_existing_client_returns_true(self):
        self.sm._clients[777] = object()
        self.assertTrue(await self.sm.start_user_client(777))
        self.assertEqual(self.calls, [])


class _Verdict:
    """filters.Verdict o'rniga sodda soxta obyekt."""

    def __init__(self, score=4.0, threshold=1.75, ok=True, stage="ok",
                 positives=None, negatives=None):
        self.score = score
        self.threshold = threshold
        self.ok = ok
        self.stage = stage
        self.positives = positives or {}
        self.negatives = negatives or {}


class TestSkipLogThrottle(unittest.TestCase):
    """Bir xil blok sababi log buferini bosib ketmasin."""

    def setUp(self):
        import scanner_manager

        self.sm = scanner_manager
        self.sm._skip_state.clear()
        self.log = logging.getLogger("scanner_manager")
        self.handler = logging.Handler()
        self.records = []
        self.handler.emit = self.records.append
        self.log.addHandler(self.handler)
        self.log.setLevel(logging.INFO)
        self.real_time = self.sm.time.time
        self.now = 1000.0
        self.sm.time.time = lambda: self.now

    def tearDown(self):
        self.sm.time.time = self.real_time
        self.sm._skip_state.clear()
        self.log.removeHandler(self.handler)

    def test_system_skip_is_summarized_once_per_minute(self):
        verdict = _Verdict(ok=False, stage="system")
        verdict.detail = "tizim to'xtatilgan"
        for _ in range(5):
            self.sm._log_skip(777, -1001, verdict)
        self.assertEqual(len(self.records), 1)
        self.now += 61
        self.sm._log_skip(777, -1001, verdict)
        self.assertEqual(len(self.records), 2)
        self.assertIn("+4 ta shunga o'xshash", self.records[-1].getMessage())

    def test_system_skip_groups_share_one_bucket(self):
        verdict = _Verdict(ok=False, stage="system")
        verdict.detail = "tizim to'xtatilgan"
        self.sm._log_skip(777, -1001, verdict)
        self.sm._log_skip(777, -1002, verdict)
        self.assertEqual(len(self.records), 1)

    def test_group_skip_is_tracked_per_chat(self):
        verdict = _Verdict(ok=False, stage="group")
        verdict.detail = "guruh faol emas"
        self.sm._log_skip(777, -1001, verdict)
        self.sm._log_skip(777, -1002, verdict)
        self.sm._log_skip(777, -1001, verdict)
        self.assertEqual(len(self.records), 2)


class TestWatch(unittest.TestCase):
    def tearDown(self):
        watch.disable()

    def test_disabled_by_default(self):
        watch.disable()
        self.assertFalse(watch.is_active())
        self.assertEqual(watch.remaining(), 0)

    def test_enable_and_disable(self):
        watch.enable(5)
        self.assertTrue(watch.is_active())
        self.assertEqual(watch.remaining(), 5)
        watch.disable()
        self.assertFalse(watch.is_active())

    def test_minutes_are_clamped(self):
        self.assertEqual(watch.enable(0), 1)
        self.assertEqual(watch.enable(9999), watch.MAX_MINUTES)

    def test_expires(self):
        watch.enable(1)
        watch._until = time.time() - 1
        self.assertFalse(watch.is_active())
        self.assertEqual(watch.remaining(), 0)

    def test_card_for_passed_message(self):
        verdict = _Verdict(4.0, 1.75, True, "ok",
                           {"kerak": 3.0, "mashina": 1.0}, {})
        card = watch.card_text("mashina kerak", verdict)
        self.assertIn("mashina kerak", card)
        self.assertIn("ball <b>4</b> / 1.75", card)
        self.assertIn("+3 kerak", card)
        self.assertIn("yuborildi", card)

    def test_card_for_near_miss(self):
        verdict = _Verdict(1.5, 1.75, False, "keywords", {"odam": 1.0}, {})
        card = watch.card_text("odam bor", verdict)
        self.assertIn("chegarada", card)

    def test_card_for_emoji_block(self):
        verdict = _Verdict(0.0, 1.75, False, "emoji")
        card = watch.card_text("🚖 reys", verdict)
        self.assertIn("emoji", card)

    def test_card_escapes_html(self):
        verdict = _Verdict(4.0, 1.75, True, "ok", {"kerak": 3.0}, {})
        card = watch.card_text("<b>yomon</b> matn", verdict)
        self.assertIn("&lt;b&gt;", card)

    def test_card_truncates_long_text(self):
        verdict = _Verdict(4.0, 1.75, True, "ok", {}, {})
        card = watch.card_text("so'z " * 300, verdict)
        self.assertIn("…", card)


class TestVoiceTranscriptionArchive(unittest.IsolatedAsyncioTestCase):
    """Ovoz arxivi va transkripsiya deduplikatsiyasi."""

    async def asyncSetUp(self):
        import tempfile
        import scanner_manager
        import database

        self.sm = scanner_manager
        self.db = database
        self.old_db_name = database.DB_NAME
        self.db_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_tmp.close()
        database.DB_NAME = self.db_tmp.name
        database.init_db()
        database.set_setting("voice_transcript_collection", "1")

        self.tmpdir = tempfile.TemporaryDirectory()
        self.old_dir = self.sm.VOICE_TRANSCRIPT_DIR
        self.sm.VOICE_TRANSCRIPT_DIR = __import__("pathlib").Path(self.tmpdir.name)
        self.old_batch = self.sm.VOICE_TRANSCRIPT_BATCH_BYTES
        self.old_owner_limit = self.sm.VOICE_TRANSCRIPT_MAX_OWNER_BYTES
        self.old_total_limit = self.sm.VOICE_TRANSCRIPT_MAX_TOTAL_BYTES
        self.old_sender = self.sm.send_document_to_bot_api
        self.old_transcript_locks = self.sm._transcript_locks.copy()
        self.sm._transcript_locks.clear()
        self.sm.VOICE_TRANSCRIPT_BATCH_BYTES = 5
        self.sm.VOICE_TRANSCRIPT_MAX_OWNER_BYTES = 100
        self.sm.VOICE_TRANSCRIPT_MAX_TOTAL_BYTES = 200

    async def asyncTearDown(self):
        import os

        self.sm.VOICE_TRANSCRIPT_DIR = self.old_dir
        self.sm.VOICE_TRANSCRIPT_BATCH_BYTES = self.old_batch
        self.sm.VOICE_TRANSCRIPT_MAX_OWNER_BYTES = self.old_owner_limit
        self.sm.VOICE_TRANSCRIPT_MAX_TOTAL_BYTES = self.old_total_limit
        self.sm.send_document_to_bot_api = self.old_sender
        self.sm._transcript_locks.clear()
        self.sm._transcript_locks.update(self.old_transcript_locks)
        self.db.DB_NAME = self.old_db_name
        self.tmpdir.cleanup()
        try:
            os.unlink(self.db_tmp.name)
        except OSError:
            pass

    async def test_voice_note_detector_excludes_regular_audio(self):
        from types import SimpleNamespace
        from telethon.tl.types import DocumentAttributeAudio

        voice = SimpleNamespace(media=SimpleNamespace(document=SimpleNamespace(
            attributes=[DocumentAttributeAudio(duration=4, voice=True)]
        )))
        music = SimpleNamespace(media=SimpleNamespace(document=SimpleNamespace(
            attributes=[DocumentAttributeAudio(duration=180, voice=False)]
        )))
        self.assertTrue(self.sm._is_voice_note(voice))
        self.assertFalse(self.sm._is_voice_note(music))

    async def test_archive_sends_and_removes_only_local_copy(self):
        from pathlib import Path

        sent = []

        async def fake_send(path, filename, chat_id=None):
            sent.append((filename, chat_id, Path(path).read_bytes()))
            return True

        self.sm.send_document_to_bot_api = fake_send
        self.assertTrue(await self.sm._append_voice_transcript(123, "ovoz matni"))
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][2], "ovoz matni\n\n".encode("utf-8"))
        self.assertEqual(sent[0][1], 777)
        self.assertFalse((Path(self.tmpdir.name) / "123.txt").exists())

    async def test_failed_upload_keeps_local_copy(self):
        from pathlib import Path

        async def fake_send(path, filename, chat_id=None):
            return False

        self.sm.send_document_to_bot_api = fake_send
        await self.sm._append_voice_transcript(123, "ovoz matni")
        self.assertTrue((Path(self.tmpdir.name) / "123.txt").exists())

    async def test_repeated_transcripts_are_kept_verbatim_without_counting(self):
        from pathlib import Path

        self.sm.VOICE_TRANSCRIPT_BATCH_BYTES = 100
        await self.sm._append_voice_transcript(123, "kerak")
        await self.sm._append_voice_transcript(123, "kerak")
        data = (Path(self.tmpdir.name) / "123.txt").read_text(encoding="utf-8")
        self.assertEqual(data, "kerak\n\nkerak\n\n")

    async def test_collection_off_does_not_write(self):
        from pathlib import Path

        self.db.set_setting("voice_transcript_collection", "0")
        self.assertFalse(await self.sm._append_voice_transcript(123, "matn"))
        self.assertFalse((Path(self.tmpdir.name) / "123.txt").exists())

    async def test_same_message_is_transcribed_once(self):
        from types import SimpleNamespace

        class FakeClient:
            def __init__(self):
                self.calls = 0

            async def __call__(self, request):
                self.calls += 1
                return SimpleNamespace(
                    pending=False, text="mashina kerak", trial_remains_num=1,
                    trial_remains_until_date=None,
                )

        client = FakeClient()
        event = SimpleNamespace(chat_id=-100123, id=45, input_chat=object())
        first = await self.sm._transcribe_voice(123, client, event)
        second = await self.sm._transcribe_voice(123, client, event)
        self.assertEqual(first, "mashina kerak")
        self.assertIsNone(second)
        self.assertEqual(client.calls, 1)

    async def test_pending_transcription_uses_telegram_update(self):
        from types import SimpleNamespace

        class FakeClient:
            async def __call__(self, request):
                key = (123, -100124, 46)
                self_update = SimpleNamespace(
                    transcription_id=9001, pending=False, text="urganchga kerak"
                )
                self.sm._pending_transcriptions[key].put_nowait(self_update)
                return SimpleNamespace(
                    pending=True, transcription_id=9001, text="",
                    trial_remains_num=2, trial_remains_until_date=None,
                )

        client = FakeClient()
        client.sm = self.sm
        event = SimpleNamespace(chat_id=-100124, id=46, input_chat=object())
        result = await self.sm._transcribe_voice(123, client, event)
        self.assertEqual(result, "urganchga kerak")
        self.assertNotIn((123, -100124, 46), self.sm._pending_transcriptions)

    async def test_flood_wait_blocks_other_groups_for_same_owner(self):
        from types import SimpleNamespace
        from telethon.errors import FloodWaitError

        class FakeClient:
            def __init__(self):
                self.calls = 0

            async def __call__(self, request):
                self.calls += 1
                raise FloodWaitError(None, capture=45)

        client = FakeClient()

        async def fake_send(text, chat_id=None, **kwargs):
            return True

        self.sm.send_to_bot_api = fake_send
        event = SimpleNamespace(chat_id=-100125, id=47, input_chat=object())
        self.assertIsNone(await self.sm._transcribe_voice(123, client, event))
        event_other_group = SimpleNamespace(chat_id=-100126, id=48, input_chat=object())
        self.assertIsNone(await self.sm._transcribe_voice(123, client, event_other_group))
        self.assertEqual(client.calls, 1)
        self.assertGreater(
            int(self.sm.get_setting(self.sm._voice_key("account_block_until", 123, 0))),
            int(time.time()),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
