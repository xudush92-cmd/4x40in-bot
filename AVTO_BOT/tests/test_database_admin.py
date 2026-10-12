import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import database as db


class AdminDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_path = db.DB_PATH
        db.DB_PATH = os.path.join(self._tmp.name, "test.db")
        await db.init_db()

    async def asyncTearDown(self):
        await db.close_db()
        db.DB_PATH = self._old_path
        self._tmp.cleanup()

    async def test_search_suspend_broadcast_and_audit(self):
        await db.upsert_user(
            101,
            name="Ali Valiyev",
            username="ali_test",
            phone="+998901234567",
            is_admin=1,
            tariff=2,
        )
        await db.upsert_user(
            102,
            name="Pending User",
            awaiting_approval=1,
        )

        old_expiry = "2027-01-01 00:00:00"
        new_expiry = "2027-02-01 00:00:00"
        await db.set_tariff_expires(101, old_expiry)
        await db.upsert_user(101, expiry_warned=1)
        await db.set_tariff_and_expiry(101, 3, new_expiry)
        saved_user = await db.get_user(101)
        self.assertEqual(saved_user["tariff"], 3)
        self.assertEqual(saved_user["tariff_expires_at"], new_expiry)
        self.assertEqual(saved_user["expiry_warned"], 0)

        self.assertEqual([u["uid"] for u in await db.search_users("@ALI")], [101])
        self.assertEqual(await db.count_search_users("901234567"), 1)
        self.assertEqual([u["uid"] for u in await db.search_users("102")], [102])

        await db.set_user_suspended(101, suspended_until=None, reason="admin test")
        self.assertTrue(await db.is_suspended(101))
        self.assertIn(101, await db.get_broadcast_targets("suspended", exclude_uid=999))
        await db.resume_user(101)
        self.assertFalse(await db.is_suspended(101))

        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        await db.set_user_suspended(101, suspended_until=past)
        self.assertIn(101, await db.get_broadcast_targets("active", exclude_uid=999))
        self.assertNotIn(101, await db.get_broadcast_targets("suspended", exclude_uid=999))
        # An expiry sweep must not overwrite a fresh, manual Start after expiry.
        await db.set_running(101, True)
        self.assertEqual(await db.release_expired_suspensions(), [101])
        self.assertTrue(await db.get_running(101))
        self.assertFalse(await db.is_suspended(101))

        self.assertIn(101, await db.get_broadcast_targets("active", exclude_uid=999))
        self.assertIn(102, await db.get_broadcast_targets("pending", exclude_uid=999))
        await db.record_admin_action(999, 101, "test_action", "ok")
        actions = await db.get_admin_actions(101)
        self.assertEqual(actions[0]["action"], "test_action")
        self.assertEqual(actions[0]["admin_uid"], 999)


if __name__ == "__main__":
    unittest.main()
