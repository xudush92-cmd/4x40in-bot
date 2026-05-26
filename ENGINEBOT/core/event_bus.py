"""
core/event_bus.py — pluginlar uchun event tizimi.

MAQSAD:
───────
Pluginlar bir-biriga toʻgʻridan-toʻgʻri bogʻlanmasdan **event** orqali
aloqa qilsin. Yangi plugin qoʻshish — eski kodga TEGMASLIK kerak.

MISOL:
──────
    # Plugin emit qiladi
    await bus.emit("post_created", {
        "post_id": 123,
        "tenant_id": 456,
        "user_id": 789,
    })

    # Boshqa modullar tinglaydi
    @bus.on("post_created")
    async def update_stats(data):
        ...

    @bus.on("post_created")
    async def notify_subscribers(data):
        ...

XAVFSIZLIK:
───────────
- Bitta listener crash boʻlsa boshqalari ishlashda davom etadi
- Asyncio task'lar bilan parallel chaqiriladi (sekinlik kuchaytirmaydi)
- Listener'lar weakref EMAS — explicit `off()` chaqirish kerak
- Eslatma: bitta jarayon ichida ishlaydi (in-memory). Distributed
  setup uchun keyinchalik Redis pub/sub qoʻshish mumkin.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict, Optional, Union

logger = logging.getLogger("enginebot.event_bus")


# Listener tipi: dict argument oladi, async/sync boʻlishi mumkin.
# Eslatma: Python 3.9 bilan ham ishlasin deb Dict/Union ishlatamiz
# (3.10+ da `dict[str, Any] | None` qisqa shaklda yozish ham mumkin).
EventHandler = Callable[[Dict[str, Any]], Optional[Awaitable[None]]]


# ─────────────────────────────────────────────────────────────────────
# Standart event nomlari (typo'larni oldini olish)
# ─────────────────────────────────────────────────────────────────────
class Events:
    """Tizimdagi standart event nomlari."""

    # Tenant lifecycle
    TENANT_CREATED = "tenant.created"
    TENANT_APPROVED = "tenant.approved"
    TENANT_BLOCKED = "tenant.blocked"
    TENANT_PAYMENT_RECEIVED = "tenant.payment_received"
    TENANT_PAYMENT_OVERDUE = "tenant.payment_overdue"

    # Channel
    CHANNEL_CONNECTED = "channel.connected"
    CHANNEL_DISCONNECTED = "channel.disconnected"

    # User lifecycle
    USER_REGISTERED = "user.registered"
    USER_APPROVED = "user.approved"
    USER_BLOCKED = "user.blocked"
    USER_WARNED = "user.warned"

    # Post lifecycle
    POST_CREATED = "post.created"
    POST_PUBLISHED = "post.published"
    POST_ROTATED = "post.rotated"
    POST_EXPIRED = "post.expired"
    POST_DELETED = "post.deleted"

    # Settings
    ROTATION_ENABLED = "settings.rotation_enabled"
    ROTATION_DISABLED = "settings.rotation_disabled"
    INTERVAL_CHANGED = "settings.interval_changed"

    # System
    SERVICE_STARTED = "system.service_started"
    SERVICE_STOPPED = "system.service_stopped"


# ─────────────────────────────────────────────────────────────────────
# EventBus — asosiy klass
# ─────────────────────────────────────────────────────────────────────
class EventBus:
    """In-memory event bus. Bir nechta listener bitta eventni tinglaydi."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[EventHandler]] = defaultdict(list)

    def on(self, event: str) -> Callable[[EventHandler], EventHandler]:
        """
        Decorator: handlerni eventga ulash.

        Misol:
            @bus.on(Events.POST_CREATED)
            async def handle(data):
                ...
        """
        def _decorator(fn: EventHandler) -> EventHandler:
            self._listeners[event].append(fn)
            logger.debug(f"event listener qoʻshildi: {event} → {fn.__name__}")
            return fn
        return _decorator

    def add_listener(self, event: str, handler: EventHandler) -> None:
        """Programmatik tarzda listener qoʻshish (decorator alternativi)."""
        self._listeners[event].append(handler)

    def off(self, event: str, handler: EventHandler) -> bool:
        """Listenerni olib tashlash. True = topildi va olib tashlandi."""
        listeners = self._listeners.get(event, [])
        if handler in listeners:
            listeners.remove(handler)
            return True
        return False

    def listener_count(self, event: str) -> int:
        return len(self._listeners.get(event, []))

    async def emit(
        self,
        event: str,
        data: dict[str, Any] | None = None,
        *,
        wait: bool = False,
    ) -> None:
        """
        Eventni emit qilish.

        Args:
            event : event nomi (Events.* dan foydalaning)
            data  : qoʻshimcha maʼlumot (har handler dict oladi)
            wait  : True boʻlsa — barcha handlerlar tugashini kutadi.
                    False (default) — fire-and-forget.

        Bitta handler crash boʻlsa boshqalari ishlashda davom etadi.
        """
        listeners = list(self._listeners.get(event, []))
        if not listeners:
            return

        data = data or {}
        logger.debug(f"emit {event} → {len(listeners)} listener")

        coros: list[asyncio.Task | None] = []
        for handler in listeners:
            try:
                result = handler(data)
                if inspect.isawaitable(result):
                    if wait:
                        coros.append(asyncio.create_task(_safe_await(handler, result)))
                    else:
                        # Fire-and-forget — chaqiruvchi kutmaydi
                        asyncio.create_task(_safe_await(handler, result))
            except Exception as e:
                logger.error(
                    f"event {event!r} handler {handler.__name__} sync xato: "
                    f"{type(e).__name__}: {e}"
                )

        if wait and coros:
            await asyncio.gather(*coros, return_exceptions=True)


async def _safe_await(handler: EventHandler, awaitable) -> None:
    """Handler natijasini xavfsiz await qilish (xato boʻlsa log'ga)."""
    try:
        await awaitable
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(
            f"event handler {handler.__name__} crash: {type(e).__name__}: {e}"
        )


# ─────────────────────────────────────────────────────────────────────
# Global instance — barcha modullar shu bilan ishlaydi
# ─────────────────────────────────────────────────────────────────────
bus = EventBus()
