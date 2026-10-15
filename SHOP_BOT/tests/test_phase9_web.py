"""Phase 9: monitoring va webhook endpointlarini oflayn aiohttp mijozida tekshirish."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer
from pydantic import SecretStr

from app.config import Settings
from app.web import server


@asynccontextmanager
async def dummy_session():
    yield object()


async def test_stats_only_accepts_header_not_url_token(monkeypatch):
    token = "private-health-test-token-12345"
    monkeypatch.setattr(server, "session_scope", dummy_session)
    overview = AsyncMock(return_value={"posts": 3})
    monkeypatch.setattr(server, "get_overview", overview)
    app = server.create_web_app(Settings(_env_file=None, health_token=SecretStr(token)), None, None)
    async with TestClient(TestServer(app)) as client:
        query = await client.get(f"/stats?token={token}")
        assert query.status == 401  # reverse proxy/access log URL'sida token qolmasin
        assert overview.await_count == 0
        bad = await client.get("/stats", headers={"X-Token": "wrong"})
        assert bad.status == 401
        good = await client.get("/stats", headers={"X-Token": token})
        assert good.status == 200
        assert (await good.json())["posts"] == 3
        assert overview.await_count == 1


async def test_webhook_absent_in_polling_and_poster_modes():
    bot = object()
    dp = SimpleNamespace(feed_webhook_update=AsyncMock())
    for settings, bot_instance, dispatcher in (
        (Settings(_env_file=None, use_webhook=False), bot, dp),
        (Settings(_env_file=None, use_webhook=True), bot, None),
    ):
        async with TestClient(TestServer(server.create_web_app(settings, bot_instance, dispatcher))) as client:
            result = await client.post("/webhook", json={"update_id": 1})
            assert result.status == 404
    dp.feed_webhook_update.assert_not_awaited()


async def test_webhook_validates_secret_body_and_reports_dispatch_errors():
    secret = "webhook-secret-for-test-only-45678"
    dp = SimpleNamespace(feed_webhook_update=AsyncMock())
    app = server.create_web_app(
        Settings(_env_file=None, use_webhook=True, webhook_secret=SecretStr(secret)), object(), dp
    )
    async with TestClient(TestServer(app)) as client:
        missing = await client.post("/webhook", json={"update_id": 1})
        assert missing.status == 403
        headers = {server.SECRET_HEADER: secret}
        invalid_json = await client.post("/webhook", data=b"{", headers=headers)
        assert invalid_json.status == 400
        bad_update = await client.post("/webhook", json={"unexpected": True}, headers=headers)
        assert bad_update.status == 400
        dp.feed_webhook_update.assert_not_awaited()
        dp.feed_webhook_update.side_effect = RuntimeError("mock dispatch failed")
        failed = await client.post("/webhook", json={"update_id": 12}, headers=headers)
        assert failed.status == 503
        assert (await failed.json())["error"] == "dispatch_failed"
        dp.feed_webhook_update.side_effect = None
        ok = await client.post("/webhook", json={"update_id": 13}, headers=headers)
        assert ok.status == 200 and (await ok.json())["ok"] is True
        assert dp.feed_webhook_update.await_count == 2
