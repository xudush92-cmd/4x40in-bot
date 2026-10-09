"""
board.py — guruh ma'lumot oynalarini boshqarish (bir nechta guruh uchun).

Qoidalar:
- Oyna guruh ichida, pin banner YO'Q. Oddiy xabar sifatida turadi.
- O'zgarish bo'lsa 30 soniya kutiladi (debounce).
- Oyna guruhning ENG OXIRGI xabari bo'lsa — TAHRIRLANADI (joyi o'zgarmaydi).
- Oynadan keyin boshqa xabar yozilgan bo'lsa — PASTGA QAYTA YUBORILADI, eskisi o'chadi.
  Yangi nusxa jim (bildirishnomasiz) yuboriladi.
- Ikki qayta yuborish orasi kamida 2 daqiqa; oyna qo'lda o'chirilgan bo'lsa darhol tiklanadi.
- Vaqt bo'yicha tekshiruv: guruhda yangi xabar bo'lsa.
"""

from __future__ import annotations

import asyncio
import logging
import time

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, TelegramError

from db import DEBOUNCE_SEC, REPOST_MIN_SEC, Database
from utils import EntryView, RouteView, now_local, render_parts

log = logging.getLogger("haydovchi.board")

KEY_LAST_MSG = "last_msg_id"
KEY_LAST_REPOST = "last_repost_at"
KEY_MSGS_SINCE = "msgs_since_repost"


def routes_to_views(rows: list[dict]) -> list[RouteView]:
    views = []
    for r in rows:
        entries = [
            EntryView(
                driver_name=f"{e['first_name']} {e['last_name']}".strip(),
                phone=e["phone"],
                seats=int(e["seats"]),
            )
            for e in r["entries"]
        ]
        views.append(RouteView(title=f"{r['from_place']} → {r['to_place']}", entries=entries))
    return views


class BoardManager:
    """Bitta guruh oynasi."""

    def __init__(self, bot: Bot, db: Database, chat_id: int, bot_username: str):
        self.bot = bot
        self.db = db
        self.chat_id = chat_id
        self.bot_username = bot_username
        self._lock = asyncio.Lock()
        self._timer: asyncio.Task | None = None

    # ── tashqi interfeys ──────────────────────────────────────────────

    def request_update(self, delay: float | None = None) -> None:
        if self._timer and not self._timer.done():
            return
        d = DEBOUNCE_SEC if delay is None else delay
        self._timer = asyncio.create_task(self._run_later(d))

    async def _run_later(self, delay: float) -> None:
        await asyncio.sleep(delay)
        self._timer = None
        try:
            await self.sync()
        except Exception:
            log.exception("Oynani yangilashda xato (guruh %s)", self.chat_id)

    async def on_group_message(self, message_id: int) -> None:
        await self.db.set_chat_value(self.chat_id, KEY_LAST_MSG, message_id)
        cnt = await self.db.get_chat_value(self.chat_id, KEY_MSGS_SINCE, 0)
        await self.db.set_chat_value(self.chat_id, KEY_MSGS_SINCE, cnt + 1)

    async def periodic_check(self) -> None:
        if await self.db.get_chat_value(self.chat_id, KEY_MSGS_SINCE, 0) > 0:
            await self.sync()

    async def force_repost(self) -> None:
        await self.sync(force=True)

    # ── ichki mantiq ──────────────────────────────────────────────────

    def _keyboard(self) -> InlineKeyboardMarkup:
        url = f"https://t.me/{self.bot_username}?start=driver"
        return InlineKeyboardMarkup([[InlineKeyboardButton("🚗 Haydovchi bo'lish", url=url)]])

    async def _build_parts(self) -> list[str]:
        rows = await self.db.board_routes()
        return render_parts(routes_to_views(rows), now_local())

    async def sync(self, force: bool = False) -> None:
        async with self._lock:
            parts = await self._build_parts()
            stored = await self.db.get_board(self.chat_id)
            now = time.time()

            missing = False
            if not force and stored and len(stored) == len(parts):
                last_msg = await self.db.get_chat_value(self.chat_id, KEY_LAST_MSG, 0)
                if stored[-1][1] == last_msg:
                    result = await self._edit_all(stored, parts)
                    if result == "ok":
                        return
                    missing = result == "missing"

            if not force and stored and not missing:
                last_repost = await self.db.get_chat_value(self.chat_id, KEY_LAST_REPOST, 0)
                wait = REPOST_MIN_SEC - (now - last_repost)
                if wait > 0:
                    self.request_update(delay=wait)
                    return

            await self._repost(parts, stored)

    async def _edit_all(self, stored: list[tuple[int, int]], parts: list[str]) -> str:
        """'ok' | 'missing' (qo'lda o'chirilgan) | 'fail'."""
        last_idx = len(stored) - 1
        for (idx, mid), text in zip(stored, parts):
            markup = self._keyboard() if idx == last_idx else None
            try:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=mid,
                    text=text,
                    reply_markup=markup,
                    disable_web_page_preview=True,
                )
            except BadRequest as e:
                msg = str(e).lower()
                if "not modified" in msg:
                    continue
                if "not found" in msg or "can't be edited" in msg:
                    log.warning("Oyna xabari topilmadi (%s): %s", mid, e)
                    return "missing"
                log.warning("Tahrirlab bo'lmadi (%s): %s", mid, e)
                return "fail"
            except TelegramError as e:
                log.warning("Tahrirlashda Telegram xatosi: %s", e)
                return "fail"
        return "ok"

    async def _repost(self, parts: list[str], stored: list[tuple[int, int]]) -> None:
        new_ids: list[int] = []
        last_idx = len(parts) - 1
        for i, text in enumerate(parts):
            markup = self._keyboard() if i == last_idx else None
            msg = await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                reply_markup=markup,
                disable_notification=True,
                disable_web_page_preview=True,
            )
            new_ids.append(msg.message_id)

        for _, old_mid in stored:
            if old_mid in new_ids:
                continue
            try:
                await self.bot.delete_message(chat_id=self.chat_id, message_id=old_mid)
            except TelegramError as e:
                log.info("Eski xabarni o'chirib bo'lmadi (%s): %s", old_mid, e)

        await self.db.set_board(self.chat_id, new_ids)
        await self.db.set_chat_value(self.chat_id, KEY_LAST_MSG, new_ids[-1])
        await self.db.set_chat_value(self.chat_id, KEY_LAST_REPOST, int(time.time()))
        await self.db.set_chat_value(self.chat_id, KEY_MSGS_SINCE, 0)
        log.info("Guruh %s oynasi yangilandi: %d qism", self.chat_id, len(new_ids))


class BoardHub:
    """Barcha guruhlar oynalari bir joyda."""

    def __init__(self):
        self.boards: dict[int, BoardManager] = {}

    def add(self, board: BoardManager) -> None:
        self.boards[board.chat_id] = board

    def get(self, chat_id: int) -> BoardManager | None:
        return self.boards.get(chat_id)

    def request_update_all(self) -> None:
        for b in self.boards.values():
            b.request_update()

    async def periodic_all(self) -> None:
        for b in self.boards.values():
            try:
                await b.periodic_check()
            except Exception:
                log.exception("Davriy tekshiruv (guruh %s)", b.chat_id)

    async def force_all(self) -> None:
        for b in self.boards.values():
            try:
                await b.force_repost()
            except Exception:
                log.exception("Majburiy yangilash (guruh %s)", b.chat_id)
