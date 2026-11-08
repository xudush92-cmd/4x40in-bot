"""Kechikkan guruh xabarlarini maxfiy, per-owner fayllarga qayd etish.

Faqat Telegram vaqt belgilari, ichki ishlov davomiyligi va zarur IDlar yoziladi.
Xabar matni, kalit so'zlar, yuboruvchi/telefon, sessiya yoki token yozilmaydi.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


DELAY_THRESHOLD_SECONDS = 10.0
DEFAULT_NO_UPDATES_TIMEOUT_SECONDS = 15 * 60
MIN_NO_UPDATES_TIMEOUT_SECONDS = 60
MAX_NO_UPDATES_TIMEOUT_SECONDS = 15 * 60
NO_UPDATES_TIMEOUT_ENV = "SCANNER_TELETHON_NO_UPDATES_TIMEOUT_SECONDS"
_MAX_FILE_BYTES = 256 * 1024
_BACKUP_COUNT = 2


def _utc_iso(value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


class _PrivateRotatingFileHandler(RotatingFileHandler):
    """Rotating JSONL fayllarini faqat servis egasiga o'qiladigan yaratadi."""

    def _open(self):
        fd = os.open(
            self.baseFilename,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        os.chmod(self.baseFilename, 0o600)
        return os.fdopen(fd, self.mode, encoding=self.encoding, errors=self.errors)


@dataclass(frozen=True)
class DelayedMessageTrace:
    owner_id: int
    chat_id: int
    message_id: int
    message_date_utc: str
    received_at_utc: str
    source_to_receive_ms: int
    received_monotonic: float


class ScanDiagnostics:
    """Har bir egaga alohida JSONL faylga kechikish bosqichlarini yozadi."""

    def __init__(
        self,
        directory: str | Path,
        *,
        threshold_seconds: float = DELAY_THRESHOLD_SECONDS,
    ) -> None:
        self.directory = Path(directory)
        self.threshold_seconds = max(0.0, float(threshold_seconds))
        self._loggers: dict[int, logging.Logger] = {}
        self._lock = threading.Lock()

    def _owner_logger(self, owner_id: int) -> logging.Logger:
        owner_id = int(owner_id)
        with self._lock:
            cached = self._loggers.get(owner_id)
            if cached is not None:
                return cached

            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.directory, 0o700)
            logger = logging.getLogger(f"scan_diagnostics.owner.{owner_id}")
            logger.setLevel(logging.INFO)
            logger.propagate = False
            if not logger.handlers:
                path = self.directory / f"owner_{owner_id}.jsonl"
                handler = _PrivateRotatingFileHandler(
                    path,
                    maxBytes=_MAX_FILE_BYTES,
                    backupCount=_BACKUP_COUNT,
                    encoding="utf-8",
                )
                handler.setFormatter(logging.Formatter("%(message)s"))
                logger.addHandler(handler)
            self._loggers[owner_id] = logger
            return logger

    def _write(self, owner_id: int, record: dict[str, Any]) -> None:
        try:
            payload = {
                "logged_at_utc": _utc_iso(dt.datetime.now(dt.timezone.utc)),
                "owner_id": int(owner_id),
                **record,
            }
            self._owner_logger(owner_id).info(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            )
        except Exception:
            # Diagnostika buzilsa, skanerlashni to'xtatmasin.
            logging.getLogger(__name__).warning(
                "Kechikish diagnostikasini faylga yozib bo'lmadi"
            )

    def begin_trace(
        self,
        *,
        owner_id: int,
        chat_id: int,
        message_id: int,
        message_date: dt.datetime | None,
        received_at: dt.datetime | None = None,
        received_monotonic: float | None = None,
    ) -> DelayedMessageTrace | None:
        """Faqat belgilangan chegaradan kech kelgan guruh xabarini boshlaydi."""
        if not isinstance(message_date, dt.datetime):
            return None
        received_at = received_at or dt.datetime.now(dt.timezone.utc)
        if message_date.tzinfo is None:
            message_date = message_date.replace(tzinfo=dt.timezone.utc)
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=dt.timezone.utc)
        delay_ms = int(
            (received_at.astimezone(dt.timezone.utc)
             - message_date.astimezone(dt.timezone.utc)).total_seconds() * 1000
        )
        if delay_ms < self.threshold_seconds * 1000:
            return None

        trace = DelayedMessageTrace(
            owner_id=int(owner_id),
            chat_id=int(chat_id),
            message_id=int(message_id),
            message_date_utc=_utc_iso(message_date),
            received_at_utc=_utc_iso(received_at),
            source_to_receive_ms=delay_ms,
            received_monotonic=(
                time.monotonic() if received_monotonic is None else received_monotonic
            ),
        )
        self._write(owner_id, {
            "stage": "received",
            "chat_id": trace.chat_id,
            "message_id": trace.message_id,
            "message_date_utc": trace.message_date_utc,
            "received_at_utc": trace.received_at_utc,
            "source_to_receive_ms": trace.source_to_receive_ms,
        })
        return trace

    def record_evaluation(
        self,
        trace: DelayedMessageTrace | None,
        *,
        matched: bool,
        filter_duration_ms: float,
        handler_to_filter_ms: float,
    ) -> None:
        if trace is None:
            return
        self._write(trace.owner_id, {
            "stage": "evaluated",
            "chat_id": trace.chat_id,
            "message_id": trace.message_id,
            "source_to_receive_ms": trace.source_to_receive_ms,
            "handler_to_filter_ms": round(max(0.0, handler_to_filter_ms), 1),
            "filter_duration_ms": round(max(0.0, filter_duration_ms), 1),
            "matched": bool(matched),
        })

    def record_notification(
        self,
        trace: DelayedMessageTrace | None,
        *,
        success: bool,
        duration_ms: float,
    ) -> None:
        if trace is None:
            return
        self._write(trace.owner_id, {
            "stage": "notification",
            "chat_id": trace.chat_id,
            "message_id": trace.message_id,
            "source_to_receive_ms": trace.source_to_receive_ms,
            "duration_ms": round(max(0.0, duration_ms), 1),
            "success": bool(success),
        })

    def record_loop_lag(self, owner_id: int, lag_ms: float) -> None:
        """Faqat sezilarli asyncio event-loop kechikishini qayd etadi."""
        if lag_ms < 250:
            return
        self._write(owner_id, {
            "stage": "event_loop_lag",
            "lag_ms": round(max(0.0, lag_ms), 1),
        })

    def record_channel_difference(
        self,
        owner_id: int,
        *,
        channel_id: int,
        request_pts: int | None,
        started_at: dt.datetime,
        duration_ms: float,
        response: Any = None,
        error_type: str | None = None,
    ) -> None:
        """Xabar mazmunisiz channel-difference RPC natijasini qayd etadi."""
        messages = getattr(response, "new_messages", ()) or ()
        other_updates = getattr(response, "other_updates", ()) or ()
        now = dt.datetime.now(dt.timezone.utc)
        ages_ms = []
        for message in messages:
            message_date = getattr(message, "date", None)
            if isinstance(message_date, dt.datetime):
                if message_date.tzinfo is None:
                    message_date = message_date.replace(tzinfo=dt.timezone.utc)
                ages_ms.append(int((now - message_date.astimezone(dt.timezone.utc)).total_seconds() * 1000))
        oldest_message_age_ms = max(ages_ms, default=None)
        duration_ms = max(0.0, duration_ms)

        # Oddiy, tez va bo'sh difference so'rovlarini yozmaymiz.
        if not error_type and duration_ms < 1000 and (oldest_message_age_ms or 0) < self.threshold_seconds * 1000:
            return

        self._write(owner_id, {
            "stage": "channel_difference",
            "channel_id": int(channel_id),
            "request_pts": request_pts,
            "started_at_utc": _utc_iso(started_at),
            "completed_at_utc": _utc_iso(now),
            "duration_ms": round(duration_ms, 1),
            "response_type": type(response).__name__ if response is not None else None,
            "new_message_count": len(messages),
            "other_update_count": len(other_updates),
            "oldest_message_age_ms": oldest_message_age_ms,
            "server_timeout_s": getattr(response, "timeout", None),
            "error_type": error_type,
        })


# Config papkasidagi diagnostics/ ichida, egasi bo'yicha alohida fayllar.
from config import BASE_DIR  # noqa: E402  (module init stays dependency-light above)

scan_diagnostics = ScanDiagnostics(BASE_DIR / "diagnostics")


def configure_telethon_no_updates_timeout() -> int:
    """Temporarily tune Telethon's shared no-updates deadline via env.

    This affects channel and account update deadlines. The 60-second floor
    avoids an overly aggressive poll loop; default behavior remains 15 minutes.
    """
    raw_value = os.getenv(NO_UPDATES_TIMEOUT_ENV, "").strip()
    if not raw_value:
        return DEFAULT_NO_UPDATES_TIMEOUT_SECONDS
    try:
        seconds = int(raw_value)
    except ValueError:
        logging.getLogger(__name__).warning(
            "%s yaroqsiz; Telethon default muddati ishlatiladi",
            NO_UPDATES_TIMEOUT_ENV,
        )
        return DEFAULT_NO_UPDATES_TIMEOUT_SECONDS
    if not MIN_NO_UPDATES_TIMEOUT_SECONDS <= seconds <= MAX_NO_UPDATES_TIMEOUT_SECONDS:
        logging.getLogger(__name__).warning(
            "%s 60..900 oralig'ida bo'lishi kerak; default ishlatiladi",
            NO_UPDATES_TIMEOUT_ENV,
        )
        return DEFAULT_NO_UPDATES_TIMEOUT_SECONDS
    try:
        from telethon._updates import messagebox
        messagebox.NO_UPDATES_TIMEOUT = seconds
    except Exception:
        logging.getLogger(__name__).exception(
            "Telethon no-updates muddati sozlanmadi; default ishlatiladi"
        )
        return DEFAULT_NO_UPDATES_TIMEOUT_SECONDS
    return seconds


def instrument_telethon_client(client, owner_id: int) -> bool:
    """Safely time GetChannelDifference RPCs for this client only.

    Uses the pinned Telethon 1.34 ``_call`` hook, but records only request
    metadata and response counts/types; never serializes update objects.
    """
    if getattr(client, "_scan_difference_timing_attached", False):
        return False
    try:
        from telethon.tl.functions.updates import GetChannelDifferenceRequest
    except Exception:
        return False

    original_call = client._call

    async def _timed_call(sender, request, ordered=False, flood_sleep_threshold=None):
        if not isinstance(request, GetChannelDifferenceRequest):
            return await original_call(
                sender,
                request,
                ordered=ordered,
                flood_sleep_threshold=flood_sleep_threshold,
            )

        started_at = dt.datetime.now(dt.timezone.utc)
        started_monotonic = time.monotonic()
        channel_id = getattr(getattr(request, "channel", None), "channel_id", 0)
        request_pts = getattr(request, "pts", None)
        try:
            response = await original_call(
                sender,
                request,
                ordered=ordered,
                flood_sleep_threshold=flood_sleep_threshold,
            )
        except Exception as exc:
            scan_diagnostics.record_channel_difference(
                owner_id,
                channel_id=channel_id,
                request_pts=request_pts,
                started_at=started_at,
                duration_ms=(time.monotonic() - started_monotonic) * 1000,
                error_type=type(exc).__name__,
            )
            raise

        scan_diagnostics.record_channel_difference(
            owner_id,
            channel_id=channel_id,
            request_pts=request_pts,
            started_at=started_at,
            duration_ms=(time.monotonic() - started_monotonic) * 1000,
            response=response,
        )
        return response

    client._call = _timed_call
    client._scan_difference_timing_attached = True
    return True
