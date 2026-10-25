"""Oxirgi log qatorlarini xotirada ushlab turadi — 🧾 Diagnostika uchun.

Nega kerak: bot ishlab turganini ko'rish uchun har safar serverga kirish
(``journalctl``) noqulay. Endi loglar halqa buferida turadi va admin
tugma bilan oxirgi qatorlarni ``.txt`` fayl qilib oladi.

Maxfiylik: fayl yuborishdan oldin telefon raqamlar ``[raqam]`` ga
almashtiriladi — log boshqa odamga ko'rsatilsa ham raqam ko'rinmaydi.
"""
from __future__ import annotations

import collections
import logging
import re
import threading

# Xotirada saqlanadigan qatorlar soni (bot uchun bir necha kun yetadi).
CAPACITY = 2000

_lines: collections.deque[str] = collections.deque(maxlen=CAPACITY)
_lock = threading.Lock()

# Telefon/uzun raqamlar: 9 va undan ortiq raqam ketma-ket kelsa yopiladi.
_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{7,}\d")


def redact(text: str) -> str:
    """Telefon raqamlarni ``[raqam]`` bilan almashtiradi."""

    def _repl(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        return "[raqam]" if len(digits) >= 9 else match.group(0)

    return _PHONE_RE.sub(_repl, text)


class RingBufferHandler(logging.Handler):
    """Log yozuvlarini halqa buferiga yig'adi."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = f"{self.format(record)}"
        except Exception:  # pragma: no cover - formatting xatosi
            return
        with _lock:
            _lines.append(line)


def install(level: int = logging.INFO, capacity: int | None = None) -> None:
    """Root loggerga bufer ushlagichini qo'shadi (bir marta)."""
    global _lines
    if capacity:
        with _lock:
            _lines = collections.deque(_lines, maxlen=capacity)
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, RingBufferHandler):
            return
    # Root logger darajasi INFO dan past bo'lsa, loglar handlerga umuman
    # yetib bormaydi (standart daraja WARNING) — shuning uchun tushiramiz.
    current = root.level if root.level > 0 else logging.WARNING
    if current > level:
        root.setLevel(level)
    handler = RingBufferHandler()
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname).1s %(name)s: %(message)s",
            datefmt="%d.%m %H:%M:%S",
        )
    )
    root.addHandler(handler)


def tail(count: int = 300, do_redact: bool = True) -> str:
    """Oxirgi ``count`` qatorni qaytaradi (raqamlar yopilgan holda)."""
    with _lock:
        rows = list(_lines)[-max(1, int(count)):]
    text = "\n".join(rows)
    return redact(text) if do_redact else text


def size() -> int:
    with _lock:
        return len(_lines)


def clear() -> None:
    with _lock:
        _lines.clear()
