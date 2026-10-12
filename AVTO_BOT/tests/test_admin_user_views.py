import os
import tempfile
import unittest
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
