import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("BOT_TOKEN", "123456:dummy")
os.environ.setdefault("ADMIN_ID", "999999")

import avto_bot
import database as db


class DailyMessageDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_path = db.DB_PATH
        db.DB_PATH = os.path.join(self._tmp.name, "daily.db")
        await db.init_db()

    async def asyncTearDown(self):
        await db.close_db()
        db.DB_PATH = self._old_path
        self._tmp.cleanup()

    async def test_config_targets_and_daily_delivery_claim_are_persistent(self):
        config = await db.get_daily_message_config()
        self.assertFalse(config["enabled"])
        self.assertEqual(config["send_time"], "10:00")
        self.assertIn("{referral_link}", config["active_text"])
        self.assertIn("{admin_phone}", config["expired_text"])

        now = datetime.now(timezone.utc).replace(microsecond=0)
        future = (now + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
        past = (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        await db.upsert_user(101, is_admin=1, tariff_expires_at=future)
        await db.upsert_user(102, is_admin=1, tariff_expires_at=past, running=0)
        await db.upsert_user(103, is_admin=0, tariff_expires_at=future)
        await db.upsert_user(104, is_admin=1, tariff_expires_at=None)
        await db.upsert_user(
            105, is_admin=1, tariff_expires_at=future, suspended=1
        )

        self.assertEqual(await db.get_daily_message_targets("active", 999999), [101])
        self.assertEqual(await db.get_daily_message_targets("expired", 999999), [102])
        self.assertEqual(await db.get_daily_message_targets("active", 101), [])

        await db.set_daily_message_text("active", "Taklif: {referral_link}")
        await db.set_daily_message_text("expired", "Admin: {admin_phone}")
        await db.set_daily_messages_enabled(True)
        saved = await db.get_daily_message_config()
        self.assertTrue(saved["enabled"])
        self.assertEqual(saved["active_text"], "Taklif: {referral_link}")
        self.assertEqual(saved["expired_text"], "Admin: {admin_phone}")

        self.assertTrue(await db.claim_daily_message_delivery(101, "active", "2026-10-23"))
        self.assertFalse(await db.claim_daily_message_delivery(101, "active", "2026-10-23"))
        self.assertEqual(
            await db.get_daily_message_targets("active", 999999, "2026-10-23"), []
        )
        self.assertTrue(await db.claim_daily_message_delivery(101, "active", "2026-10-24"))
        self.assertFalse(await db.claim_daily_message_delivery(101, "expired", "2026-10-23"))
        await db.finish_daily_message_delivery(101, "active", "2026-10-23", "sent")

    async def test_unknown_daily_message_segment_is_rejected(self):
        with self.assertRaises(ValueError):
            await db.set_daily_message_text("all", "not allowed")
        with self.assertRaises(ValueError):
            await db.get_daily_message_targets("all", 999999)


class DailyMessageRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_path = db.DB_PATH
        self._old_application = avto_bot.application
        self._old_states = dict(avto_bot.user_states)
        db.DB_PATH = os.path.join(self._tmp.name, "daily-runtime.db")
        avto_bot.user_states.clear()
        await db.init_db()

    async def asyncTearDown(self):
        await db.close_db()
        db.DB_PATH = self._old_path
        avto_bot.application = self._old_application
        avto_bot.user_states.clear()
        avto_bot.user_states.update(self._old_states)
        self._tmp.cleanup()

    async def test_sends_at_most_once_per_local_day_with_personalized_templates(self):
        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        future = (now_utc + timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        past = (now_utc - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        await db.upsert_user(301, name="Faol", is_admin=1, tariff_expires_at=future)
        await db.upsert_user(302, name="Tugagan", is_admin=1, tariff_expires_at=past)
        await db.set_daily_message_text("active", "Taklif havola: {referral_link}")
        await db.set_daily_message_text("expired", "Muddat tugadi: {admin_phone}")
        await db.set_daily_messages_enabled(True)

        class FakeBot:
            def __init__(self):
                self.messages = []

            async def send_message(self, uid, text):
                self.messages.append((uid, text))

        fake_bot = FakeBot()
        avto_bot.application = SimpleNamespace(bot=fake_bot)
        now_local = datetime.now(avto_bot.DAILY_MESSAGE_TIMEZONE)
        before_send_time = now_local.replace(hour=9, minute=59, second=0, microsecond=0)
        due_time = now_local.replace(hour=10, minute=1, second=0, microsecond=0)

        early = await avto_bot._send_daily_messages_if_due(now=before_send_time)
        self.assertEqual(early["sent"], 0)
        self.assertEqual(fake_bot.messages, [])

        sent = await avto_bot._send_daily_messages_if_due(now=due_time)
        self.assertEqual(sent["sent"], 2)
        self.assertEqual(
            fake_bot.messages[0],
            (301, f"Taklif havola: https://t.me/{avto_bot.BOT_USERNAME}?start=ref_301"),
        )
        self.assertIn(avto_bot.ADMIN_CONTACT_PHONE, fake_bot.messages[1][1])
        self.assertEqual(fake_bot.messages[1][0], 302)

        again = await avto_bot._send_daily_messages_if_due(now=due_time)
        self.assertEqual(again["sent"], 0)
        self.assertEqual(len(fake_bot.messages), 2)

    async def test_expiry_notice_and_daily_scheduler_do_not_duplicate_same_day(self):
        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        past = (now_utc - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        await db.upsert_user(
            303, name="Muddati tugagan", is_admin=1, tariff_expires_at=past, running=1
        )
        await db.set_daily_message_text("expired", "Tarif tugadi: {admin_phone}")
        await db.set_daily_messages_enabled(True)

        class FakeBot:
            def __init__(self):
                self.messages = []

            async def send_message(self, uid, text, **kwargs):
                self.messages.append((uid, text))

        fake_bot = FakeBot()
        avto_bot.application = SimpleNamespace(bot=fake_bot)
        avto_bot.worker_manager = None

        await avto_bot._check_tariff_expiry()
        user_messages = [message for uid, message in fake_bot.messages if uid == 303]
        self.assertEqual(user_messages, [f"Tarif tugadi: {avto_bot.ADMIN_CONTACT_PHONE}"])

        now_local = datetime.now(avto_bot.DAILY_MESSAGE_TIMEZONE).replace(
            hour=10, minute=1, second=0, microsecond=0
        )
        result = await avto_bot._send_daily_messages_if_due(now=now_local)
        self.assertEqual(result["sent"], 0)
        user_messages = [message for uid, message in fake_bot.messages if uid == 303]
        self.assertEqual(len(user_messages), 1)

    async def test_admin_can_start_stop_and_edit_daily_messages(self):
        class FakeQuery:
            def __init__(self, callback_data, uid=avto_bot.SUPER_ADMIN):
                self.from_user = SimpleNamespace(id=uid)
                self.data = callback_data
                self.edits = []

            async def answer(self, *args, **kwargs):
                pass

            async def edit_message_text(self, text, **kwargs):
                self.edits.append((text, kwargs))

        panel = avto_bot.admin_panel_kb()
        panel_data = [
            button.callback_data
            for row in panel.inline_keyboard
            for button in row
        ]
        self.assertIn("adm:daily", panel_data)
        self.assertNotIn("adm:broadcast", panel_data)

        await avto_bot.on_callback(
            SimpleNamespace(callback_query=FakeQuery("adm:daily:start")), None
        )
        self.assertTrue((await db.get_daily_message_config())["enabled"])

        edit_query = FakeQuery("adm:daily:edit:active")
        await avto_bot.on_callback(SimpleNamespace(callback_query=edit_query), None)
        self.assertEqual(
            avto_bot.user_states[avto_bot.SUPER_ADMIN]["step"],
            "admin_daily_message_active",
        )

        replies = []

        async def reply_text(text, **kwargs):
            replies.append((text, kwargs))

        message = SimpleNamespace(
            text="Do'st taklif qiling: {referral_link}",
            photo=None,
            reply_text=reply_text,
        )
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=avto_bot.SUPER_ADMIN),
            message=message,
        )
        await avto_bot._handle_admin_input(
            update, avto_bot.user_states[avto_bot.SUPER_ADMIN]
        )
        self.assertEqual(
            avto_bot.user_states[avto_bot.SUPER_ADMIN]["step"],
            "admin_daily_message_confirm",
        )
        self.assertTrue(any(
            "Saqlash" in button.text
            for row in replies[-1][1]["reply_markup"].inline_keyboard
            for button in row
        ))

        await avto_bot.on_callback(
            SimpleNamespace(callback_query=FakeQuery("adm:daily:save")), None
        )
        saved = await db.get_daily_message_config()
        self.assertEqual(saved["active_text"], "Do'st taklif qiling: {referral_link}")
        self.assertNotIn(avto_bot.SUPER_ADMIN, avto_bot.user_states)

        await avto_bot.on_callback(
            SimpleNamespace(callback_query=FakeQuery("adm:daily:stop")), None
        )
        self.assertFalse((await db.get_daily_message_config())["enabled"])

    async def test_non_super_user_cannot_change_daily_message_state(self):
        class FakeQuery:
            from_user = SimpleNamespace(id=123456)
            data = "adm:daily:start"

            async def answer(self, *args, **kwargs):
                pass

            async def edit_message_text(self, text, **kwargs):
                raise AssertionError("non-super user must not reach admin action")

        await avto_bot.on_callback(
            SimpleNamespace(callback_query=FakeQuery()), None
        )
        self.assertFalse((await db.get_daily_message_config())["enabled"])


if __name__ == "__main__":
    unittest.main()
