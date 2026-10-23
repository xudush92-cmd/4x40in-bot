import os
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("BOT_TOKEN", "123456:dummy")
os.environ.setdefault("ADMIN_ID", "999999")

import avto_bot
import database as db
from telethon.tl.types import Channel, Chat, ChatPhotoEmpty


class FakePermissions:
    def __init__(
        self,
        *,
        admin=False,
        creator=False,
        left=False,
        banned=False,
        default=True,
        banned_rights=None,
    ):
        self.is_admin = admin
        self.is_creator = creator
        self.has_left = left
        self.is_banned = banned
        self.has_default_permissions = default
        self.participant = SimpleNamespace(
            left=left,
            banned_rights=banned_rights,
        )


class FakeTelegramClient:
    def __init__(self, dialogs, participant_permissions, default_rights=None):
        self.dialogs = dialogs
        self.participant_permissions = participant_permissions
        self.default_rights = default_rights or {}

    async def get_me(self, input_peer=False):
        return object()

    def iter_dialogs(self, limit=None, ignore_migrated=False):
        async def iterate():
            for dialog in self.dialogs[:limit]:
                yield dialog
        return iterate()

    async def get_permissions(self, entity, user=None):
        if user is not None:
            return self.participant_permissions[entity.id]
        return self.default_rights.get(
            entity.id, SimpleNamespace(send_messages=False)
        )


def basic_group(uid, title):
    return Chat(
        id=uid,
        title=title,
        photo=ChatPhotoEmpty(),
        participants_count=10,
        date=datetime.now(timezone.utc),
        version=1,
    )


def supergroup(uid, title, username=None):
    return Channel(
        id=uid,
        title=title,
        photo=ChatPhotoEmpty(),
        date=datetime.now(timezone.utc),
        broadcast=False,
        megagroup=True,
        username=username,
    )


def broadcast_channel(uid, title):
    return Channel(
        id=uid,
        title=title,
        photo=ChatPhotoEmpty(),
        date=datetime.now(timezone.utc),
        broadcast=True,
        megagroup=False,
    )


class FakeQuery:
    def __init__(self, data, uid):
        self.data = data
        self.from_user = SimpleNamespace(id=uid)
        self.edits = []
        self.answers = []

    async def answer(self, *args, **kwargs):
        self.answers.append((args, kwargs))

    async def edit_message_text(self, text, **kwargs):
        self.edits.append((text, kwargs))


class GroupScannerTests(unittest.IsolatedAsyncioTestCase):
    def test_main_menu_uses_scanner_instead_of_manual_chat_entry(self):
        markup = avto_bot.kb_main(interval=5, running=False, super_admin=False)
        labels = [button.text for row in markup.keyboard for button in row]
        self.assertIn("🔍 Guruhlarni skanerlash", labels)
        self.assertNotIn("➕ Chat qo'sh", labels)

    async def test_scan_rows_include_group_details_and_confirm_button_is_green(self):
        groups = [
            {
                "chat_id": "-1001",
                "title": "Group Alpha",
                "writable": True,
                "existing_status": None,
            },
            {
                "chat_id": "-1002",
                "title": "Read Only Beta",
                "writable": False,
                "existing_status": "waiting",
            },
            {
                "chat_id": "-1003",
                "title": "Already Active Gamma",
                "writable": True,
                "existing_status": "active",
            },
        ]
        avto_bot.user_states[404] = {
            "step": "group_scan_review",
            "ts": avto_bot.time.time(),
            "groups": groups,
            "selected": {0, 1},
            "page": 0,
            "note": "",
        }

        text, markup = await avto_bot._build_group_scan_message(404)
        buttons = {
            button.callback_data: button
            for row in markup.inline_keyboard
            for button in row
        }

        self.assertNotIn("Group Alpha", text, "group details should not be duplicated above the buttons")
        first_info, first_select = markup.inline_keyboard[0]
        self.assertEqual(first_info.callback_data, "gscan:info:0")
        self.assertEqual(first_select.callback_data, "gscan:toggle:0")
        self.assertIn("Group Alpha", first_info.text)
        self.assertIn("✅ yozish mumkin", first_info.text)
        self.assertEqual(first_select.text, "☑️ Tanlangan")
        second_info, second_select = markup.inline_keyboard[1]
        self.assertIn("Read Only Beta", second_info.text)
        self.assertIn("⛔ yozish yo'q", second_info.text)
        self.assertIn("kutishda", second_info.text)
        self.assertEqual(second_select.text, "☑️ Tanlangan")
        active_info, active_select = markup.inline_keyboard[2]
        self.assertIn("faol", active_info.text)
        self.assertEqual(active_select.text, "🟢 Faol")
        self.assertLessEqual(avto_bot._utf16_units(first_info.text), 64)
        self.assertEqual(buttons["gscan:confirm"].style, "success")

        info_query = FakeQuery("gscan:info:0", 404)
        await avto_bot.on_callback(SimpleNamespace(callback_query=info_query), None)
        self.assertTrue(info_query.answers[0][1]["show_alert"])
        self.assertIn("Group Alpha", info_query.answers[0][0][0])
        self.assertIn("Yozish mumkin", info_query.answers[0][0][0])
        self.assertEqual(buttons["gscan:confirm"].to_dict()["style"], "success")

    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_path = db.DB_PATH
        self._old_application = avto_bot.application
        db.DB_PATH = os.path.join(self._tmp.name, "test.db")
        avto_bot.application = None
        avto_bot.user_states.pop(404, None)
        await db.init_db()
        await db.upsert_user(404, name="Scanner User", is_admin=1, tariff=1)

    async def asyncTearDown(self):
        avto_bot.user_states.pop(404, None)
        avto_bot.application = self._old_application
        await db.close_db()
        db.DB_PATH = self._old_path
        self._tmp.cleanup()

    def _client_for(self, entities, *, blocked_ids=()):
        dialogs = [SimpleNamespace(entity=entity, name=entity.title) for entity in entities]
        participants = {}
        defaults = {}
        for entity in entities:
            if isinstance(entity, Channel) and entity.broadcast:
                continue
            if entity.id in blocked_ids:
                participants[entity.id] = FakePermissions(default=True)
                defaults[entity.id] = SimpleNamespace(send_messages=True)
            elif isinstance(entity, Channel) and entity.megagroup:
                participants[entity.id] = FakePermissions(admin=True, default=False)
            else:
                participants[entity.id] = FakePermissions(default=True)
                defaults[entity.id] = SimpleNamespace(send_messages=False)
        return FakeTelegramClient(dialogs, participants, defaults)

    async def test_scan_is_groups_only_and_additions_wait_for_confirmation(self):
        group = basic_group(11, "Basic Group")
        mega = supergroup(12, "Super Group", username="supergroup_test")
        no_write = basic_group(13, "Read Only Group")
        channel = broadcast_channel(14, "Broadcast Channel")
        client = self._client_for([group, mega, no_write, channel], blocked_ids={13})

        groups, note, truncated, dialog_count = await avto_bot._scan_user_groups(client, 404)

        self.assertEqual([row["title"] for row in groups], ["Basic Group", "Super Group", "Read Only Group"])
        self.assertEqual(groups[0]["writable"], True)
        self.assertEqual(groups[1]["writable"], True)
        self.assertEqual(groups[2]["writable"], False)
        self.assertEqual(note, "")
        self.assertFalse(truncated)
        self.assertEqual(dialog_count, 4)
        self.assertEqual(await db.count_chats(404), 0, "scanning must not add groups")

        avto_bot.user_states[404] = {
            "step": "group_scan_review",
            "ts": avto_bot.time.time(),
            "groups": groups,
            # First two are preselected; selecting the blocked group explicitly
            # should add it in waiting state rather than activate it.
            "selected": {0, 1, 2},
            "page": 0,
            "note": note,
        }
        query = FakeQuery("gscan:confirm", 404)
        await avto_bot._confirm_group_scan(404, query)

        records = await db.get_chat_records(404)
        self.assertEqual(len(records), 3)
        statuses = {record["title"]: record["status"] for record in records}
        self.assertEqual(statuses["Basic Group"], "active")
        self.assertEqual(statuses["Super Group"], "active")
        self.assertEqual(statuses["Read Only Group"], "waiting")
        self.assertIn("Kutish holatida qo'shildi", query.edits[-1][0])

    async def test_waiting_group_is_reactivated_only_after_manual_confirmation(self):
        group = supergroup(22, "Recoverable Group", username="recoverable_test")
        chat_id = avto_bot._canonical_chat_storage(group, "fallback")
        await db.add_chat(404, chat_id, max_chats=5, status="waiting", title=group.title)
        client = self._client_for([group])

        groups, _, _, _ = await avto_bot._scan_user_groups(client, 404)
        self.assertEqual(groups[0]["existing_status"], "waiting")
        self.assertTrue(groups[0]["writable"])
        self.assertEqual(await db.get_active_chats(404), [], "scan alone must not reactivate")

        avto_bot.user_states[404] = {
            "step": "group_scan_review",
            "ts": avto_bot.time.time(),
            "groups": groups,
            "selected": {0},
            "page": 0,
            "note": "",
        }
        query = FakeQuery("gscan:confirm", 404)
        await avto_bot._confirm_group_scan(404, query)

        self.assertEqual(await db.get_active_chats(404), [chat_id])
        self.assertEqual(await db.count_waiting_chats(404), 0)
        self.assertIn("Kutishdan faol holatga qaytdi: 1", query.edits[-1][0])

    async def test_cancelled_waiting_group_scan_leaves_database_unchanged(self):
        group = basic_group(31, "Still Waiting")
        chat_id = avto_bot._canonical_chat_storage(group, "fallback")
        await db.add_chat(404, chat_id, max_chats=5, status="waiting", title=group.title)
        groups, _, _, _ = await avto_bot._scan_user_groups(
            self._client_for([group], blocked_ids={31}), 404
        )
        avto_bot.user_states[404] = {
            "step": "group_scan_review",
            "ts": avto_bot.time.time(),
            "groups": groups,
            "selected": {0},
            "page": 0,
            "note": "",
        }

        query = FakeQuery("gscan:cancel", 404)
        await avto_bot.on_callback(SimpleNamespace(callback_query=query), None)

        self.assertEqual((await db.get_chat_records(404))[0]["status"], "waiting")
        self.assertNotIn(404, avto_bot.user_states)
        self.assertIn("Hech bir guruh o'zgartirilmadi", query.edits[-1][0])


if __name__ == "__main__":
    unittest.main()
