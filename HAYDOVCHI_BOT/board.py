"""
board.py — Telegram guruhlaridagi ma'lumot oynalarini boshqarish.

Har Telegram guruhning o'z oynasi bor; oynada shu guruh jamlanmasining ma'lumoti chiqadi.
Sozlamalar (pauza, repost chegarasi, taksi) jamlanma darajasida. Repost hisoblagichi esa
har guruhda o'zining.

Qoida (skaner):
- Har SCAN_SEC (30) soniyada skaner ishlaydi.
- Haydovchi ma'lumoti o'zgargan bo'lsa (dirty) — oyna yangilanadi.
- Guruhda o'z sozlamasidagi (standart 3) ta yangi xabar yozilgan bo'lsa — oyna pastga tushadi.
- Yangi xabar bo'lmasa va o'zgarish bo'lmasa — hech narsa qilinmaydi.

Yangilash turi:
- Oyna guruhning ENG OXIRGI xabari bo'lsa — TAHRIRLANADI (joyi o'zgarmaydi, bildirishnoma yo'q).
- Aks holda — PASTGA QAYTA YUBORILADI, eskisi o'chadi, yangisi jim yuboriladi.
- Oyna qo'lda o'chirilgan bo'lsa — darhol tiklanadi.
- To'xtatib qo'yilgan (paused) guruh avtomatik yangilanmaydi; qo'lda yangilash mumkin.
- Oyna ostida "🚕 Taksi chaqirish" tugmasi bo'ladi (guruh sozlamasi yoqilgan bo'lsa).
- Har guruh o'z yo'nalish va haydovchilari bilan alohida oyna chiqaradi.
"""

from __future__ import annotations

import asyncio
import logging
import time

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, TelegramError

from db import Database
from utils import EntryView, RouteView, now_local, render_parts

log = logging.getLogger("haydovchi.board")

SCAN_SEC = 30

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
        self.dirty = True          # boshlanishda bir marta yangilanadi
        self._lock = asyncio.Lock()

    # ── tashqi interfeys ──────────────────────────────────────────────

    def mark_dirty(self) -> None:
        """Haydovchi ma'lumoti o'zgardi — keyingi skanerda yangilanadi."""
        self.dirty = True

    async def on_group_message(self, message_id: int) -> None:
        """Guruhda boshqa birov xabar yozdi."""
        await self.db.set_chat_value(self.chat_id, KEY_LAST_MSG, message_id)
        cnt = await self.db.get_chat_value(self.chat_id, KEY_MSGS_SINCE, 0)
        await self.db.set_chat_value(self.chat_id, KEY_MSGS_SINCE, cnt + 1)

    async def scan(self) -> None:
        """Skaner: kerak bo'lsa yangilaydi (guruhning o'z sozlamasi bo'yicha)."""
        ctx = await self.db.get_chat_ctx(self.chat_id)
        if ctx is None or ctx["paused"]:
            return
        msgs = await self.db.get_chat_value(self.chat_id, KEY_MSGS_SINCE, 0)
        if self.dirty or msgs >= ctx["repost_after_msgs"]:
            await self.sync()

    async def force_repost(self) -> None:
        await self.sync(force=True)

    async def delete_all(self) -> None:
        """Guruh olib tashlanganda oynaning xabarlarini o'chiradi."""
        for _, mid in await self.db.get_board(self.chat_id):
            try:
                await self.bot.delete_message(chat_id=self.chat_id, message_id=mid)
            except TelegramError:
                pass

    async def last_update_info(self) -> tuple[int, int]:
        """(oxirgi qayta yuborish vaqti epoch, shundan beri kelgan xabarlar soni)."""
        ts = await self.db.get_chat_value(self.chat_id, KEY_LAST_REPOST, 0)
        cnt = await self.db.get_chat_value(self.chat_id, KEY_MSGS_SINCE, 0)
        return ts, cnt

    # ── ichki mantiq ──────────────────────────────────────────────────

    def _keyboard(self, taxi_enabled: bool) -> InlineKeyboardMarkup:
        """Oxirgi qism tagidagi tugmalar: taksi (ixtiyoriy) va haydovchi bo'lish."""
        url = f"https://t.me/{self.bot_username}?start=driver"
        rows = []
        if taxi_enabled:
            rows.append([InlineKeyboardButton("🚕 Taksi chaqirish", callback_data=f"tx:{self.chat_id}")])
        rows.append([InlineKeyboardButton("🚗 Haydovchi bo'lish", url=url)])
        return InlineKeyboardMarkup(rows)

    async def _build_parts(self, collection_id: int) -> list[str]:
        rows = await self.db.board_routes(collection_id)
        return render_parts(routes_to_views(rows), now_local())

    async def sync(self, force: bool = False) -> None:
        async with self._lock:
            ctx = await self.db.get_chat_ctx(self.chat_id)
            if ctx is None:            # guruh jamlanmadan olib tashlangan
                return
            taxi = bool(ctx["taxi_enabled"])
            parts = await self._build_parts(ctx["collection_id"])
            stored = await self.db.get_board(self.chat_id)

            done = False
            if not force and stored and len(stored) == len(parts):
                last_msg = await self.db.get_chat_value(self.chat_id, KEY_LAST_MSG, 0)
                if stored[-1][1] == last_msg:
                    done = await self._edit_all(stored, parts, taxi) == "ok"
            if not done:
                await self._repost(parts, stored, taxi)
            # Muvaffaqiyatli bo'lgandagina "o'zgargan" belgisini olib tashlaymiz
            self.dirty = False

    async def _edit_all(self, stored: list[tuple[int, int]], parts: list[str], taxi: bool) -> str:
        """'ok' | 'missing' | 'fail'. Oyna ortda qolgan bo'lsa, qayta yuborish kerak."""
        last_idx = len(stored) - 1
        for (idx, mid), text in zip(stored, parts):
            markup = self._keyboard(taxi) if idx == last_idx else None
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

    async def _repost(self, parts: list[str], stored: list[tuple[int, int]], taxi: bool) -> None:
        new_ids: list[int] = []
        last_idx = len(parts) - 1
        for i, text in enumerate(parts):
            markup = self._keyboard(taxi) if i == last_idx else None
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
    """Barcha Telegram guruh oynalari bir joyda."""

    def __init__(self):
        self.boards: dict[int, BoardManager] = {}

    def add(self, board: BoardManager) -> None:
        self.boards[board.chat_id] = board

    def remove(self, chat_id: int) -> BoardManager | None:
        return self.boards.pop(chat_id, None)

    def get(self, chat_id: int) -> BoardManager | None:
        return self.boards.get(chat_id)

    def mark_all_dirty(self) -> None:
        for b in self.boards.values():
            b.mark_dirty()

    async def scan_all(self) -> None:
        for b in list(self.boards.values()):
            try:
                await b.scan()
            except Exception:
                log.exception("Skaner xatosi (guruh %s)", b.chat_id)

    async def force_all(self) -> None:
        for b in list(self.boards.values()):
            try:
                await b.force_repost()
            except Exception:
                log.exception("Majburiy yangilash (guruh %s)", b.chat_id)
