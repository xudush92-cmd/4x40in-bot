"""HTTP server: /health, /stats va (webhook rejimida) webhook endpoint.

Bitta aiohttp ilova — ham webhook, ham monitoring uchun.
Caddy orqali tashqariga chiqariladi (REJA.md 13-bo'lim).
"""

from __future__ import annotations

import hmac
import time
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from aiohttp import web
from loguru import logger

from app import __version__
from app.config import Settings
from app.db.base import ping_database, session_scope
from app.redis_client import redis_manager
from app.services.stats_service import get_overview
from app.utils.time import utcnow

_STARTED_AT = time.monotonic()
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
SETTINGS_KEY = web.AppKey("settings", Settings)
BOT_KEY = web.AppKey("bot", Bot)
DISPATCHER_KEY = web.AppKey("dispatcher", Dispatcher)


def _uptime() -> int:
    return int(time.monotonic() - _STARTED_AT)


async def health_handler(request: web.Request) -> web.Response:
    """/health — monitoring uchun (Docker healthcheck, uptime robot)."""
    settings: Settings = request.app[SETTINGS_KEY]
    db_ok = await ping_database()
    redis_ok = await redis_manager.is_healthy()

    status = "ok" if db_ok else "down"
    if db_ok and not redis_ok:
        status = "degraded"  # Redis ishlamasa ham bot ishlaydi (xotira rejimi)

    payload: dict[str, Any] = {
        "status": status,
        "version": __version__,
        "mode": settings.run_mode,
        "uptime_sec": _uptime(),
        "db": db_ok,
        "redis": redis_ok,
        "webhook": settings.use_webhook,
        "timestamp": utcnow().isoformat(),
    }
    return web.json_response(payload, status=200 if db_ok else 503)


async def stats_handler(request: web.Request) -> web.Response:
    """/stats — token bilan himoyalangan batafsil statistika (JSON)."""
    settings: Settings = request.app[SETTINGS_KEY]
    expected = settings.health_token.get_secret_value() if settings.health_token else ""

    if expected:
        # URL query tokenlari proksi/access log va browser tarixiga sizishi mumkin.
        provided = request.headers.get("X-Token", "")
        if not hmac.compare_digest(provided, expected):
            return web.json_response({"error": "unauthorized"}, status=401)
    else:
        # Token yo'q — faqat lokal manzillardan ruxsat
        peer = request.remote or ""
        if not (peer.startswith("127.") or peer in ("::1", "localhost")):
            return web.json_response({"error": "forbidden"}, status=403)

    try:
        async with session_scope() as session:
            data = await get_overview(session)
    except Exception as exc:  # pragma: no cover
        logger.warning("Statistikani olib bo'lmadi: {}", exc)
        return web.json_response({"error": "db_error"}, status=503)

    data["uptime_sec"] = _uptime()
    data["version"] = __version__
    return web.json_response(data)


async def webhook_handler(request: web.Request) -> web.Response:
    """Telegram update'larini qabul qilish (faqat webhook rejimida)."""
    settings: Settings = request.app[SETTINGS_KEY]
    bot: Bot = request.app[BOT_KEY]
    dispatcher: Dispatcher = request.app[DISPATCHER_KEY]

    secret = request.headers.get(SECRET_HEADER, "")
    if settings.webhook_secret_value and secret != settings.webhook_secret_value:
        logger.warning("Webhook: noto'g'ri secret_token ({})", request.remote)
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_json"}, status=400)

    try:
        update = Update.model_validate(data, context={"bot": bot})
    except Exception as exc:
        logger.warning("Webhook: update o'qilmadi ({})", exc)
        return web.json_response({"ok": False, "error": "bad_update"}, status=400)

    try:
        await dispatcher.feed_webhook_update(bot, update)
    except Exception as exc:
        logger.exception("Webhook update'ini qayta ishlashda xato: {}", exc)
        # Sukut bo'yicha 200 qaytarish Telegram'ga update bajarildi deb bildiradi.
        return web.json_response({"ok": False, "error": "dispatch_failed"}, status=503)

    return web.json_response({"ok": True})


def create_web_app(settings: Settings, bot: Bot | None, dispatcher: Dispatcher | None) -> web.Application:
    """aiohttp ilovasini yig'ish."""
    app = web.Application(client_max_size=1024**2)
    app[SETTINGS_KEY] = settings
    app[BOT_KEY] = bot
    app[DISPATCHER_KEY] = dispatcher

    app.router.add_get("/health", health_handler)
    app.router.add_get("/stats", stats_handler)

    if settings.use_webhook and bot is not None and dispatcher is not None:
        app.router.add_post(settings.webhook_path, webhook_handler)
        logger.info("Webhook endpoint: POST {}", settings.webhook_path)

    return app


async def start_web_server(
    settings: Settings, bot: Bot | None, dispatcher: Dispatcher | None
) -> web.AppRunner:
    """HTTP serverni ishga tushirish (0.0.0.0 — konteyner/preview uchun)."""
    app = create_web_app(settings, bot, dispatcher)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.health_host, port=settings.health_port)
    await site.start()
    logger.info("HTTP server: http://{}:{}/health", settings.health_host, settings.health_port)
    return runner
