"""APScheduler'ni sozlash va ishga tushirish.

Poster process (`RUN_MODE=poster` yoki `all`) shu yerda ishlaydi.
Barcha vaqt holati bazada saqlanadi — restartda hech narsa yo'qolmaydi.
"""

from __future__ import annotations

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from app.config import Settings
from app.scheduler.jobs import (
    daily_stats_job,
    expire_subscriptions_job,
    heartbeat_job,
    posting_tick_job,
    retention_job,
    rights_check_job,
    subscription_reminders_job,
)


def build_scheduler(settings: Settings, bot: Bot | None = None) -> AsyncIOScheduler:
    """Job'larni ro'yxatdan o'tkazib scheduler'ni qaytaradi (hali ishga tushmaydi)."""
    scheduler = AsyncIOScheduler(
        timezone=settings.timezone,
        job_defaults={
            "coalesce": True,          # orqada qolgan ishlarni birlashtirish
            "max_instances": 1,        # bitta job bir vaqtda ikki marta ishlamasin
            "misfire_grace_time": 60,
        },
    )

    # ── Har daqiqada ──────────────────────────────────────────
    scheduler.add_job(
        heartbeat_job,
        IntervalTrigger(seconds=60),
        id="heartbeat",
        name="Heartbeat (tizim tirik)",
    )

    # ── Har 10 sekundda: aylanma joylash tick'i (Phase 4 da to'liq) ──
    if bot is not None:
        scheduler.add_job(
            posting_tick_job,
            IntervalTrigger(seconds=10),
            args=[bot],
            id="posting_tick",
            name="Aylanma joylash",
        )

        # ── Har 15 daqiqada: bot huquqlarini tekshirish ────────
        scheduler.add_job(
            rights_check_job,
            IntervalTrigger(minutes=15),
            args=[bot],
            id="rights_check",
            name="Guruh huquqlarini tekshirish",
            next_run_time=None,  # ishga tushgandan 2 daqiqa o'tib boshlanadi
        )

        # ── Har 30 daqiqada: muddati tugagan obunalar ──────────
        scheduler.add_job(
            expire_subscriptions_job,
            IntervalTrigger(minutes=30),
            args=[bot],
            id="expire_subscriptions",
            name="Obunalar muddatini tekshirish",
        )

        # ── Har soatda: tarif eslatmalari (Phase 2) ────────────
        scheduler.add_job(
            subscription_reminders_job,
            IntervalTrigger(hours=1),
            args=[bot],
            id="subscription_reminders",
            name="Tarif eslatmalari",
        )

    # ── Kunlik: loglarni tozalash ─────────────────────────────
    scheduler.add_job(
        retention_job,
        CronTrigger(hour=3, minute=30),
        id="retention",
        name="Loglarni tozalash (retention)",
    )

    # ── Kunlik: statistika jamlanmasi ─────────────────────────
    scheduler.add_job(
        daily_stats_job,
        CronTrigger(hour=0, minute=10),
        id="daily_stats",
        name="Kunlik statistika",
    )

    logger.info("Scheduler tayyor: {} ta job", len(scheduler.get_jobs()))
    return scheduler


async def start_scheduler(scheduler: AsyncIOScheduler) -> None:
    scheduler.start()
    for job in scheduler.get_jobs():
        logger.debug("Job: {} — keyingi ishga tushish: {}", job.name, job.next_run_time)


async def stop_scheduler(scheduler: AsyncIOScheduler) -> None:
    try:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler to'xtatildi")
    except Exception as exc:  # pragma: no cover
        logger.warning("Scheduler'ni to'xtatishda xato: {}", exc)
