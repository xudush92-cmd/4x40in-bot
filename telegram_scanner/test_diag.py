"""🧾 Diagnostika va 👁 Kuzatuv testlari.

`python test_diag.py`
"""
from __future__ import annotations

import logging
import os
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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


class TestProtectedContent(unittest.TestCase):
    def setUp(self):
        import scanner_manager

        self.sm = scanner_manager

    def test_chat_level_protection_is_detected(self):
        self.assertTrue(self.sm._is_protected_content(
            chat=SimpleNamespace(noforwards=True),
            message=SimpleNamespace(noforwards=False),
        ))

    def test_message_level_protection_is_detected(self):
        self.assertTrue(self.sm._is_protected_content(
            chat=SimpleNamespace(noforwards=False),
            message=SimpleNamespace(noforwards=True),
        ))

    def test_unprotected_content_is_not_flagged(self):
        self.assertFalse(self.sm._is_protected_content(
            chat=SimpleNamespace(noforwards=False),
            message=SimpleNamespace(noforwards=False),
        ))

    def test_diagnostics_never_store_message_text(self):
        self.sm._note_event(777, False, -100123, "protected text should not persist")
        self.assertEqual(self.sm._last_event[777][2], "")
        self.sm.reset_diagnostics(777)


class _HandlerClient:
    def on(self, _builder):
        def register(handler):
            self.handler = handler
            return handler
        return register


class _ProtectedEvent:
    def __init__(self):
        self.chat_id = -100123456789
        self.is_private = False
        self.raw_text = "Toshkentdan odam bor, telefon 998901234567"
        self.out = False
        self.id = 50
        self.message = SimpleNamespace(noforwards=False, sticker=None)
        self.sender_calls = 0

    async def get_chat(self):
        return SimpleNamespace(
            title="Protected group", username=None, noforwards=True
        )

    async def get_sender(self):
        self.sender_calls += 1
        return SimpleNamespace(
            first_name="Visible Sender",
            last_name="Name",
            username="visible_user",
            id=321,
            phone="998991112233",
        )


class TestProtectedMessageNotification(unittest.IsolatedAsyncioTestCase):
    async def test_match_alert_shows_only_selected_visible_details(self):
        import scanner_manager

        event = _ProtectedEvent()
        client = _HandlerClient()
        verdict = SimpleNamespace(ok=True, matched=["odam bor"])
        with (
            patch.object(scanner_manager, "evaluate", return_value=verdict),
            patch.object(scanner_manager, "send_to_bot_api", new_callable=AsyncMock) as send,
            patch.object(scanner_manager, "increment_user_counter"),
            patch.object(scanner_manager, "set_user_last_found"),
            patch.object(scanner_manager, "increment_counter"),
            patch.object(scanner_manager, "save_lead_review") as save_review,
        ):
            scanner_manager._make_handler(123, client)
            await client.handler(event)

        send.assert_awaited_once()
        text, markup = send.await_args.args[:2]
        self.assertIn("HIMOYALANGAN GURUHDA MOS MATN TOPILDI", text)
        self.assertIn("Protected group", text)
        self.assertNotIn(event.raw_text, text)
        self.assertIn("Visible Sender Name", text)
        self.assertIn("@visible_user", text)
        self.assertIn("998901234567", text)
        self.assertNotIn("998991112233", text)
        self.assertIn("odam bor", text)
        self.assertNotIn("Ball:", text)
        self.assertEqual(event.sender_calls, 1)
        save_review.assert_not_called()
        self.assertEqual(len(markup["inline_keyboard"]), 2)
        profile_button, message_button = [row[0] for row in markup["inline_keyboard"]]
        self.assertEqual(profile_button["url"], "https://t.me/visible_user")
        self.assertEqual(message_button["url"], "https://t.me/c/123456789/50")
        self.assertNotIn("callback_data", profile_button)
        self.assertNotIn("callback_data", message_button)


class TestGroupMembershipAudit(unittest.IsolatedAsyncioTestCase):
    CHAT_ID = -1001234567890
    OWNER_ID = 12345

    async def test_left_group_is_paused_and_owner_notified_once(self):
        import scanner_manager

        group = (
            1, self.OWNER_ID, str(self.CHAT_ID), self.CHAT_ID,
            "Test group", 1, "ok", None,
        )
        client = SimpleNamespace(get_dialogs=AsyncMock(return_value=[]))
        with (
            patch.object(scanner_manager, "get_user_groups", return_value=[group]),
            patch.object(scanner_manager, "mark_user_group_left", return_value=True) as mark_left,
            patch.object(scanner_manager, "send_to_bot_api", new_callable=AsyncMock) as send,
        ):
            self.assertTrue(
                await scanner_manager._audit_owner_group_membership(self.OWNER_ID, client)
            )
        mark_left.assert_called_once_with(1)
        send.assert_awaited_once()
        self.assertEqual(send.await_args.kwargs["chat_id"], self.OWNER_ID)
        self.assertIn("guruhdan chiqib ketilgani", send.await_args.args[0].lower())

    async def test_rejoining_group_restores_watch(self):
        import scanner_manager

        group = (
            1, self.OWNER_ID, str(self.CHAT_ID), self.CHAT_ID,
            "Old title", 1, "left", "a'zo emas",
        )
        entity = SimpleNamespace(peer_id=self.CHAT_ID, title="Current title")
        client = SimpleNamespace(
            get_dialogs=AsyncMock(return_value=[SimpleNamespace(entity=entity)])
        )
        with (
            patch.object(scanner_manager, "get_user_groups", return_value=[group]),
            patch.object(scanner_manager.utils, "get_peer_id", side_effect=lambda e: e.peer_id),
            patch.object(scanner_manager, "resolve_user_group", return_value=True) as restore,
            patch.object(scanner_manager, "send_to_bot_api", new_callable=AsyncMock) as send,
        ):
            self.assertTrue(
                await scanner_manager._audit_owner_group_membership(self.OWNER_ID, client)
            )
        restore.assert_called_once_with(1, self.CHAT_ID, "Current title")
        send.assert_awaited_once()
        self.assertIn("qayta tiklandi", send.await_args.args[0])

    async def test_dialog_fetch_failure_does_not_mark_group_left(self):
        import scanner_manager

        group = (
            1, self.OWNER_ID, str(self.CHAT_ID), self.CHAT_ID,
            "Test group", 1, "ok", None,
        )
        client = SimpleNamespace(get_dialogs=AsyncMock(side_effect=RuntimeError("offline")))
        with (
            patch.object(scanner_manager, "get_user_groups", return_value=[group]),
            patch.object(scanner_manager, "mark_user_group_left") as mark_left,
            patch.object(scanner_manager, "send_to_bot_api", new_callable=AsyncMock) as send,
        ):
            self.assertFalse(
                await scanner_manager._audit_owner_group_membership(self.OWNER_ID, client)
            )
        mark_left.assert_not_called()
        send.assert_not_awaited()


class TestGroupResolutionDedup(unittest.IsolatedAsyncioTestCase):
    OWNER_ID = 12345
    CHAT_ID = -1001234567890

    async def _resolve_duplicate(self, *, old_created, new_created):
        import scanner_manager

        class FakeChat:
            def __init__(self):
                self.chat_id = TestGroupResolutionDedup.CHAT_ID
                self.title = "Same group"
                self.username = "same_group"

        class FakeChannel:
            pass

        old = (1, self.OWNER_ID, "@same_group", self.CHAT_ID, "Same group", 1, "ok", None)
        new = (2, self.OWNER_ID, "-1001234567890", None, None, 1, "pending", None)
        entity = FakeChat()
        client = SimpleNamespace(
            get_dialogs=AsyncMock(return_value=[SimpleNamespace(entity=entity)])
        )
        with (
            patch.object(scanner_manager, "get_pending_user_groups", return_value=[
                (2, self.OWNER_ID, new[2], None, "pending")
            ]),
            patch.object(scanner_manager, "get_user_groups", return_value=[old, new]),
            patch.object(
                scanner_manager, "get_user_group_created_at",
                side_effect={1: old_created, 2: new_created}.__getitem__,
            ),
            patch.object(scanner_manager, "delete_user_group") as delete,
            patch.object(scanner_manager, "mark_user_group_duplicate") as mark_dup,
            patch.object(scanner_manager, "send_to_bot_api", new_callable=AsyncMock),
            patch.object(scanner_manager, "Chat", FakeChat),
            patch.object(scanner_manager, "Channel", FakeChannel),
            patch.object(scanner_manager.utils, "get_peer_id", side_effect=lambda e: e.chat_id),
        ):
            await scanner_manager._resolve_owner_groups(self.OWNER_ID, client)
        return delete, mark_dup

    async def test_new_alias_duplicate_is_removed(self):
        import time

        now = int(time.time())
        delete, mark_dup = await self._resolve_duplicate(
            old_created=now - 1, new_created=now
        )
        delete.assert_called_once_with(2, self.OWNER_ID)
        mark_dup.assert_not_called()

    async def test_old_duplicate_is_not_auto_deleted(self):
        delete, mark_dup = await self._resolve_duplicate(
            old_created=0, new_created=0
        )
        delete.assert_not_called()
        mark_dup.assert_called_once_with(2, self.CHAT_ID, "Same group")


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
