import unittest

from client_pool import ClientPool, PooledClient


class ClientPoolReferenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_release_keeps_client_busy_until_all_borrowers_release(self):
        pool = ClientPool(1, "hash", max_clients=2)
        pooled = PooledClient(uid=7, client=object(), use_count=2)
        pool._clients[7] = pooled

        await pool.release(7)
        self.assertTrue(pooled.in_use)
        self.assertEqual(pool.active_count, 1)

        await pool.release(7)
        self.assertFalse(pooled.in_use)
        self.assertEqual(pool.active_count, 0)
