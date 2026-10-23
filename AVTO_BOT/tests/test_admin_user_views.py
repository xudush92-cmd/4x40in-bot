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


class AdminUserViewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_path = db.DB_PATH
        db.DB_PATH = os.path.join(self._tmp.name, "test.db")
        avto_bot.worker_manager = None
        await db.init_db()
        await db.upsert_user(
            avto_bot.SUPER_ADMIN,
            name="Super Admin",
            is_admin=1,
            phone="+998900000000",
        )
        await db.upsert_user(
            202,
            name="Abror Saidov",
            username="abror_test",
            phone="+998901112233",
            is_admin=1,
            tariff=2,
        )
        await db.upsert_user(
            203,
            name="Zebo Karimova",
            username="zebo_test",
            phone="+998971112233",
            is_admin=1,
            tariff=3,
        )
        await db.upsert_user(
            204,
            name="Login",
            phone="+998931234567",
            is_admin=1,
        )
        await db.upsert_user(
            205,
            name="Sardor Pending",
            phone="+998991234567",
            awaiting_approval=1,
        )

    async def asyncTearDown(self):
        await db.close_db()
        db.DB_PATH = self._old_path
        self._tmp.cleanup()

    async def test_admin_list_is_separated_paginated_and_shows_full_phone(self):
        text, markup = await avto_bot.format_admin_list()

        self.assertIn("👥 ADMINLAR (4 ta — 1 super + 3 oddiy)", text)
        self.assertIn("\n\n👤 Abror Saidov", text)
        self.assertIn("📱 +998901112233", text)
        self.assertIn("📱 +998971112233", text)
        self.assertIn("Ism/familiya kiritilmagan", text)
        self.assertLess(len(text.encode("utf-16-le")) // 2, 4096)
        self.assertTrue(markup.inline_keyboard)

    async def test_users_button_builds_name_roster_and_card_shows_phone(self):
        text, markup = await avto_bot._build_user_list()
        buttons = [button for row in markup.inline_keyboard for button in row]
        user_buttons = [button for button in buttons if (button.callback_data or "").startswith("adm:ucard:")]

        self.assertIn("Ism bo'yicha A–Z", text)
        self.assertEqual(
            [button.callback_data for button in user_buttons],
            ["adm:ucard:202", "adm:ucard:204", "adm:ucard:205", "adm:ucard:203"],
        )
        self.assertTrue(any("Abror Saidov" in button.text for button in user_buttons))
        self.assertTrue(any("Zebo Karimova" in button.text for button in user_buttons))
        self.assertFalse(any(str(avto_bot.SUPER_ADMIN) in (button.callback_data or "") for button in user_buttons))

        card, _ = await avto_bot._build_user_card(202)
        self.assertIn("📱 Telefon: +998901112233", card)
        self.assertIn("\n\n📌 Hisob:", card)
        self.assertEqual((await db.get_user(204))["name"], "Login")

    async def test_admin_roster_separates_valid_and_expired_tariff_users(self):
        future = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
        past = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
        await db.set_tariff_expires(202, future)
        await db.set_tariff_expires(203, past)

        active_text, active_markup = await avto_bot.format_admin_list(segment="active")
        expired_text, expired_markup = await avto_bot.format_admin_list(segment="expired")

        self.assertIn("FAOL TARIFI BOR FOYDALANUVCHILAR (1 ta)", active_text)
        self.assertIn("Abror Saidov", active_text)
        self.assertNotIn("Zebo Karimova", active_text)
        self.assertIn("MUDDATI TUGAGAN FOYDALANUVCHILAR (1 ta)", expired_text)
        self.assertIn("Zebo Karimova", expired_text)
        self.assertNotIn("Abror Saidov", expired_text)
        callbacks = {
            button.callback_data
            for row in active_markup.inline_keyboard
            for button in row
        }
        self.assertIn("adm:list:filter:active", callbacks)
        self.assertIn("adm:list:filter:expired", callbacks)
        self.assertTrue(expired_markup.inline_keyboard)

        active_users, active_users_markup = await avto_bot._build_user_list(segment="active")
        expired_users, expired_users_markup = await avto_bot._build_user_list(segment="expired")
        active_user_callbacks = {
            button.callback_data
            for row in active_users_markup.inline_keyboard
            for button in row
            if (button.callback_data or "").startswith("adm:ucard:")
        }
        active_user_labels = [
            button.text
            for row in active_users_markup.inline_keyboard
            for button in row
            if (button.callback_data or "").startswith("adm:ucard:")
        ]
        expired_user_labels = [
            button.text
            for row in expired_users_markup.inline_keyboard
            for button in row
            if (button.callback_data or "").startswith("adm:ucard:")
        ]
        self.assertEqual(active_user_callbacks, {"adm:ucard:202"})
        self.assertTrue(any("Abror Saidov" in label for label in active_user_labels))
        self.assertFalse(any("Zebo Karimova" in label for label in active_user_labels))
        self.assertTrue(any("Zebo Karimova" in label for label in expired_user_labels))
        self.assertFalse(any("Abror Saidov" in label for label in expired_user_labels))

    async def test_admin_can_view_a_users_referral_list(self):
        await db.upsert_user(206, name="Dilshod Karimov", is_admin=1)
        await db.upsert_user(207, name="Madina Usmonova")
        self.assertTrue(await db.set_referrer(206, 202))
        self.assertTrue(await db.set_referrer(207, 202))
        self.assertEqual(await db.try_count_referral(206), 202)

        card, card_markup = await avto_bot._build_user_card(202)
        self.assertIn("Taklif qilganlari: 2 ta (faol 1, kutilmoqda 1)", card)
        card_callbacks = {
            button.callback_data
            for row in card_markup.inline_keyboard
            for button in row
        }
        self.assertIn("adm:refs:202:page:0", card_callbacks)

        referrals, markup = await avto_bot._build_admin_referrals(202)
        self.assertIn("Jami: 2 · ✅ Faol: 1 · ⏳ Kutilmoqda: 1", referrals)
        self.assertIn("Dilshod Karimov", referrals)
        self.assertIn("Madina Usmonova", referrals)
        self.assertTrue(markup.inline_keyboard)

    async def test_user_delete_requires_a_second_explicit_confirmation(self):
        class FakeQuery:
            def __init__(self, callback_data):
                self.from_user = SimpleNamespace(id=avto_bot.SUPER_ADMIN)
                self.data = callback_data
                self.edits = []

            async def answer(self, *args, **kwargs):
                pass

            async def edit_message_text(self, text, **kwargs):
                self.edits.append((text, kwargs))

        old_wipe = avto_bot._wipe_user_media
        avto_bot._wipe_user_media = lambda uid: None
        try:
            select_query = FakeQuery("rmadm:202")
            await avto_bot.on_callback(
                SimpleNamespace(callback_query=select_query), None
            )
            self.assertIsNotNone(await db.get_user(202))
            self.assertIn("butunlay o'chirmoqchimisiz", select_query.edits[-1][0])
            markup = select_query.edits[-1][1]["reply_markup"]
            callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
            self.assertIn("rmadm:confirm:202", callbacks)
            self.assertIn("rmadm:cancel", callbacks)

            cancel_query = FakeQuery("rmadm:cancel")
            await avto_bot.on_callback(
                SimpleNamespace(callback_query=cancel_query), None
            )
            self.assertIsNotNone(await db.get_user(202))

            confirm_query = FakeQuery("rmadm:confirm:202")
            await avto_bot.on_callback(
                SimpleNamespace(callback_query=confirm_query), None
            )
            self.assertIsNone(await db.get_user(202))
            self.assertIn("butunlay o'chirildi", confirm_query.edits[-1][0])
        finally:
            avto_bot._wipe_user_media = old_wipe


class RegistrationNameValidationTests(unittest.TestCase):
    def test_requires_first_and_last_name_for_new_registration(self):
        self.assertTrue(avto_bot._has_first_and_last_name("Akmal Karimov"))
        self.assertTrue(avto_bot._has_first_and_last_name("Ўғилбек Қодиров"))
        self.assertFalse(avto_bot._has_first_and_last_name("Login"))
        self.assertFalse(avto_bot._has_first_and_last_name("🔑 Login"))
        self.assertFalse(avto_bot._has_first_and_last_name("Ali 12345"))
