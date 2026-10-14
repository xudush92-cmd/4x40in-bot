"""Log tizimini sozlash (loguru) + standart logging'ni ushlab olish."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from loguru import logger

_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>"
)


class _InterceptHandler(logging.Handler):
    """Standart logging yozuvlarini loguru'ga yo'naltirish."""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging(level: str = "INFO", log_dir: str = "logs", *, to_file: bool = True) -> None:
    """Loguru'ni sozlash: konsol + kunlik aylanadigan fayl."""
    logger.remove()

    logger.add(
        sys.stdout,
        level=level,
        format=_CONSOLE_FORMAT,
        colorize=True,
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )

    if to_file:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        logger.add(
            path / "shopbot_{time:YYYY-MM-DD}.log",
            level=level,
            rotation="00:00",        # har kuni yangi fayl
            retention="14 days",     # 14 kundan eskisini o'chirish
            compression="zip",
            encoding="utf-8",
            enqueue=True,
            backtrace=True,
            diagnose=False,          # sirlar logga tushmasligi uchun
        )

    # Standart logging'ni ushlash (aiogram, sqlalchemy, apscheduler, aiohttp)
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    for name in ("aiogram", "aiogram.event", "sqlalchemy.engine", "apscheduler", "aiohttp.access"):
        std_logger = logging.getLogger(name)
        std_logger.handlers = [_InterceptHandler()]
        std_logger.propagate = False
        if name in ("sqlalchemy.engine", "aiohttp.access"):
            std_logger.setLevel(logging.WARNING)  # shovqinni kamaytirish

    logger.debug("Log tizimi sozlandi (level={}, dir={})", level, log_dir)


def log_error(source: str, exc: BaseException, **context: Any) -> None:
    """Xatoni bir xil formatda logga yozish (error_log jadvaliga yozish bilan birga ishlatiladi)."""
    logger.bind(source=source, **context).opt(exception=exc).error("{}: {}", source, exc)
