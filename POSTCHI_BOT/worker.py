"""
worker.py — E'lonlarni interval bilan yuboruvchi yagona rejalashtiruvchi.

MANTIQ:
- Bitta fon loop (scheduler) har WORKER_TICK_S soniyada ishlaydi.
- Har "tick" da: barcha running=1 foydalanuvchilar olinadi.
- Har foydalanuvchining FAOL e'loni → tanlangan VILOYAT guruhlariga yuboriladi.
- HAR GURUH O'Z intervali bilan: (uid, group_id) juftligi uchun oxirgi
  yuborishdan beri guruh intervali o'tgan bo'lsa — qayta yuboriladi.
- Flood himoya: guruhlar orasida SEND_DELAY_S kutish.
- Xato bardoshlilik: bitta guruh xato bersa, qolganlarga yuboraveradi.
  Ketma-ket MAX_GROUP_FAILS xato → guruh nofaol qilinadi.

Nega yagona loop (per-user worker emas):
- Interval GURUHGA bog'liq, foydalanuvchiga emas. Yagona scheduler
  per-guruh vaqtni tabiiy boshqaradi va kodni soddalashtiradi.

Holat (next_send) xotirada saqlanadi: {(uid, group_id): next_timestamp}.
Restart-dan keyin bo'sh — hamma e'lon tez orada (kichik tarqoqlik bilan)
yuboriladi. Bu xavfsiz.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time

from telegram.error import Forbidden, BadRequest, RetryAfter, TimedOut

import database as db
from sender import send_ad_to_group
from config import SEND_DELAY_S, MAX_GROUP_FAILS, WORKER_TICK_S

logger = logging.getLogger("PostchiBot")


class Scheduler:
    """E'lon yuborish rejalashtiruvchisi (yagona fon loop)."""

    def __init__(self, bot):
        self.bot = bot
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        # {(uid, group_id): next_send_epoch}
        self._next: dict[tuple[int, int], float] = {}

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._loop(), name="postchi-scheduler")
            logger.info("Scheduler ishga tushdi")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._task, timeout=10)
        logger.info("Scheduler to'xtadi")

    async def _sleep_or_stop(self, seconds: float) -> bool:
        """True qaytarsa — stop signali keldi."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False

    async def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                with contextlib.suppress(Exception):
                    await self._tick()
                if await self._sleep_or_stop(WORKER_TICK_S):
                    break
        except asyncio.CancelledError:
            pass

    async def _tick(self) -> None:
        """Bir aylanish: barcha running userlar e'lonini tekshirib yuboradi."""
        now = time.time()
        running_uids = await db.get_all_running()
        if not running_uids:
            return

        for uid in running_uids:
            if self._stop.is_set():
                break

            user = await db.get_user(uid)
            if not user or not user.get("running"):
                continue
            ad_id = user.get("active_ad_id")
            region_id = user.get("selected_region_id")
            if not ad_id or not region_id:
                continue

            ad = await db.get_ad(ad_id)
            if not ad:
                # E'lon o'chirilgan — to'xtatamiz
                await db.set_running(uid, False)
                continue

            groups = await db.get_active_groups_in_region(region_id)
            if not groups:
                continue

            for g in groups:
                if self._stop.is_set():
                    break
                group_id = g["id"]
                interval_s = max(1, int(g.get("interval_min", 10))) * 60
                key = (uid, group_id)

                # Birinchi marta ko'rilgan juftlik — kichik tarqoqlik bilan
                # rejaga qo'yamiz (yukni yoyish uchun)
                if key not in self._next:
                    self._next[key] = now + random.randint(0, min(60, interval_s))
                    continue

                if now < self._next[key]:
                    continue

                # Yuborish vaqti keldi
                await self._send_one(uid, ad, g, region_id)
                self._next[key] = time.time() + interval_s

                # Flood himoya — guruhlar orasida kutish
                if await self._sleep_or_stop(SEND_DELAY_S):
                    break

    async def _send_one(self, uid: int, ad: dict, group: dict, region_id: int) -> None:
        """Bitta e'lonni bitta guruhga yuboradi (xato bardoshli)."""
        group_id = group["id"]
        chat_id = group["chat_id"]
        try:
            await asyncio.wait_for(
                send_ad_to_group(self.bot, chat_id, ad), timeout=30
            )
            await db.mark_group_sent(group_id)
            await db.log_send(ad["id"], uid, group_id, region_id, "ok")
            logger.info("OK %s → guruh %s", uid, chat_id)

        except RetryAfter as e:
            # Telegram flood — kutamiz (bu guruh aybi emas, fail hisoblanmaydi)
            wait_s = int(getattr(e, "retry_after", 5)) + 1
            logger.warning("RetryAfter %ss (guruh %s)", wait_s, chat_id)
            await self._sleep_or_stop(wait_s)

        except (Forbidden, BadRequest) as e:
            # Bot chiqarilgan / yozish taqiqlangan / chat yo'q — guruh aybi
            await db.log_send(ad["id"], uid, group_id, region_id, "error")
            fails = await db.incr_group_fail(group_id)
            logger.warning(
                "Xato %s → guruh %s: %s (%s/%s)",
                uid, chat_id, type(e).__name__, fails, MAX_GROUP_FAILS,
            )
            if fails >= MAX_GROUP_FAILS:
                await db.set_group_active(chat_id, False)
                logger.warning("Guruh nofaol qilindi (ko'p xato): %s", chat_id)

        except (TimedOut, asyncio.TimeoutError):
            await db.log_send(ad["id"], uid, group_id, region_id, "error")
            await db.incr_group_fail(group_id)
            logger.warning("Timeout %s → guruh %s", uid, chat_id)

        except Exception as e:
            await db.log_send(ad["id"], uid, group_id, region_id, "error")
            logger.error("Kutilmagan xato → guruh %s: %s", chat_id, e)
