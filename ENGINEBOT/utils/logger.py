"""
utils/logger.py — strukturalashgan logging.

MAQSAD:
───────
Bitta joyda logger sozlamasi: konsolga + faylga yozish, format,
darajalar, rotation. Har modul oʻzini logger oladi:

    logger = logging.getLogger("enginebot.<module>")

QOIDALAR:
─────────
- Konsolga: faqat INFO+ (rangli) — operatorga koʻrinadi
- Faylga: DEBUG+ (rotation bilan) — debug uchun
- Per-tenant log: alohida fayl tenant_id boʻyicha (kerak boʻlsa)
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from config import LOG_DIR, LOG_LEVEL, BRAND_NAME


# ─────────────────────────────────────────────────────────────────────
# Format
# ─────────────────────────────────────────────────────────────────────
_FILE_FORMAT = "[%(asctime)s] %(levelname)-7s %(name)s :: %(message)s"
_CONSOLE_FORMAT = "[%(asctime)s] %(levelname)-7s %(name)s :: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# ─────────────────────────────────────────────────────────────────────
# Rangli console (faqat terminalda)
# ─────────────────────────────────────────────────────────────────────
class _ColorFormatter(logging.Formatter):
    """ANSI rang kodlari bilan chiroyli console output."""

    _COLORS = {
        "DEBUG": "\033[36m",      # cyan
        "INFO": "\033[32m",       # green
        "WARNING": "\033[33m",    # yellow
        "ERROR": "\033[31m",      # red
        "CRITICAL": "\033[1;31m", # bold red
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname}{self._RESET}"
        return super().format(record)


# ─────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────
_INITIALIZED = False


def setup_logging(
    level: str | None = None,
    log_dir: Path | None = None,
    *,
    enable_color: bool = True,
) -> None:
    """
    Loyihaning logger'ini sozlash.

    Idempotent — bir necha marta chaqirish xavfsiz.
    Birinchi chaqiruv main.py'da boʻlishi kerak (oxirgi holatda).
    """
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    level_name = (level or LOG_LEVEL).upper()
    level_int = getattr(logging, level_name, logging.INFO)

    log_dir = log_dir or LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    # ─── ROOT logger ─────────────────────────────────────────────────
    root = logging.getLogger("enginebot")
    root.setLevel(logging.DEBUG)  # handlerlar oʻzlari filterlaydi
    root.propagate = False

    # Eski handlerlarni olib tashlash (idempotent uchun)
    for h in list(root.handlers):
        root.removeHandler(h)

    # ─── Console handler ─────────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(level_int)
    if enable_color:
        console.setFormatter(_ColorFormatter(_CONSOLE_FORMAT, _DATE_FORMAT))
    else:
        console.setFormatter(logging.Formatter(_CONSOLE_FORMAT, _DATE_FORMAT))
    root.addHandler(console)

    # ─── File handler (rotation) ─────────────────────────────────────
    log_file = log_dir / "enginebot.log"
    file_h = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(logging.Formatter(_FILE_FORMAT, _DATE_FORMAT))
    root.addHandler(file_h)

    # ─── Error file handler (faqat ERROR+) ──────────────────────────
    error_file = log_dir / "errors.log"
    err_h = logging.handlers.RotatingFileHandler(
        error_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    err_h.setLevel(logging.ERROR)
    err_h.setFormatter(logging.Formatter(_FILE_FORMAT, _DATE_FORMAT))
    root.addHandler(err_h)

    # ─── Tashqi kutubxonalarni jim qilish ───────────────────────────
    for noisy in ("aiohttp.access", "aiohttp", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root.info(f"⚙️ {BRAND_NAME} logger ready (level={level_name}, dir={log_dir})")


def get_logger(name: str) -> logging.Logger:
    """
    Modul uchun logger olish.

    Misol:
        logger = get_logger(__name__)   # 'enginebot.<module>'
    """
    if not name.startswith("enginebot"):
        name = f"enginebot.{name}"
    return logging.getLogger(name)
