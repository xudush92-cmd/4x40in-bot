"""
AVTO BOT — Telegram avto-poster bot.

Foydalanuvchilar o'z Telegram hisoblari orqali tanlangan chatlarga
belgilangan vaqt oraliqlarida avtomatik reklama joylashtiradi.

XAVFSIZLIK:
- Kod va parol DISK-ga saqlanmaydi (faqat StringSession saqlanadi).
- JSON yozish atomik (os.replace) va asyncio.Lock bilan.
- FloodWait, AuthKeyUnregistered, ChatWriteForbidden xatolari to'g'ri ishlanadi.
- Super admin har bir yangi foydalanuvchi uchun ON/OFF tasdiq beradi.

ISHLATISH:
    pip install python-telegram-bot telethon python-dotenv
    cp .env.example .env  # va to'ldiring
    python avto_bot.py
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

from dotenv import load_dotenv

from telethon import TelegramClient
from telethon.errors import (
    AuthKeyUnregisteredError,
    ChannelPrivateError,
    ChatWriteForbiddenError,
    FloodWaitError,
    PasswordHashInvalidError,
    PeerIdInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
    UserDeactivatedBanError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.sessions import StringSession
from telethon.tl.types import (
    MessageEntityBold,
    MessageEntityBotCommand,
    MessageEntityCashtag,
    MessageEntityCode,
    MessageEntityCustomEmoji,
    MessageEntityEmail,
    MessageEntityHashtag,
    MessageEntityItalic,
    MessageEntityMention,
    MessageEntityMentionName,
    MessageEntityPhone,
    MessageEntityPre,
    MessageEntitySpoiler,
    MessageEntityStrike,
    MessageEntityTextUrl,
    MessageEntityUnderline,
    MessageEntityUrl,
)

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MessageEntity,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ─────────────────────────────────────────────────────────────────────────
# ENV
# ─────────────────────────────────────────────────────────────────────────
load_dotenv()


def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(
            f"Environment variable '{name}' yo'q. .env faylini tekshiring."
        )
    return v


API_ID = int(_require_env("API_ID"))
API_HASH = _require_env("API_HASH")
BOT_TOKEN = _require_env("BOT_TOKEN")
SUPER_ADMIN = int(_require_env("ADMIN_ID"))

# ─────────────────────────────────────────────────────────────────────────
# KONSTANTALAR
# ─────────────────────────────────────────────────────────────────────────
MAX_CHATS = 10
MAX_POSTS = 20
MIN_INTERVAL_MIN = 4
MAX_INTERVAL_MIN = 1440          # 24 soat
LOGIN_TIMEOUT_S = 300            # 5 daqiqa
SEND_DELAY_S = 5                 # chatlar orasidagi pauza
INTERVAL_JITTER_S = 30           # interval ±jitter
DEFAULT_TZ_OFFSET = 5            # UTC+5 (Toshkent)

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

CHATS_FILE = os.path.join(DATA_DIR, "chats.json")
ADMINS_FILE = os.path.join(DATA_DIR, "admins.json")
POSTS_FILE = os.path.join(DATA_DIR, "posts.json")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")
PENDING_FILE = os.path.join(DATA_DIR, "pending.json")
INTERVALS_FILE = os.path.join(DATA_DIR, "intervals.json")
SCHEDULE_FILE = os.path.join(DATA_DIR, "schedule.json")
RUNNING_FILE = os.path.join(DATA_DIR, "running.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
LOG_FILE = "avto_bot.log"

# ─────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────
logger = logging.getLogger("AvtoBot")
logger.setLevel(logging.INFO)
_fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_fh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
_sh = logging.StreamHandler()
_sh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%H:%M:%S"))
logger.addHandler(_fh)
logger.addHandler(_sh)


def log(msg: str, level: str = "info") -> None:
    getattr(logger, level)(msg)


# ─────────────────────────────────────────────────────────────────────────
# ATOMIK + LOCK-LI JSON SAQLASH
# ─────────────────────────────────────────────────────────────────────────
_locks: dict[str, asyncio.Lock] = {}


def _lock(path: str) -> asyncio.Lock:
    if path not in _locks:
        _locks[path] = asyncio.Lock()
    return _locks[path]


async def jload(path: str, default: Any) -> Any:
    async with _lock(path):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            log(f"JSON o'qish xatosi ({path}): {e}", "error")
        return default


async def jsave(path: str, data: Any) -> None:
    async with _lock(path):
        d = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            with contextlib.suppress(Exception):
                os.remove(tmp)
            log(f"JSON saqlash xatosi ({path}): {e}", "error")


async def jpatch(path: str, key: str, value: Any) -> None:
    """Bitta dict-fayl ichida key/value yangilash (atomik read-modify-write)."""
    async with _lock(path):
        data: dict = {}
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
        except Exception as e:
            log(f"JSON o'qish xatosi ({path}): {e}", "error")
        if not isinstance(data, dict):
            data = {}
        data[key] = value
        d = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            with contextlib.suppress(Exception):
                os.remove(tmp)
            log(f"JSON saqlash xatosi ({path}): {e}", "error")


async def jdrop(path: str, key: str) -> None:
    async with _lock(path):
        try:
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or key not in data:
                return
            data.pop(key, None)
            d = os.path.dirname(path) or "."
            fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=d)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            log(f"JSON o'chirish xatosi ({path}): {e}", "error")


# ─────────────────────────────────────────────────────────────────────────
# STORAGE — yuqori darajadagi yordamchilar
# ─────────────────────────────────────────────────────────────────────────
async def get_session(uid: int) -> str | None:
    return (await jload(SESSIONS_FILE, {})).get(str(uid))


async def set_session(uid: int, sess: str) -> None:
    await jpatch(SESSIONS_FILE, str(uid), sess)


async def del_session(uid: int) -> None:
    await jdrop(SESSIONS_FILE, str(uid))


async def get_pending(uid: int) -> str | None:
    return (await jload(PENDING_FILE, {})).get(str(uid))


async def set_pending(uid: int, sess: str) -> None:
    await jpatch(PENDING_FILE, str(uid), sess)


async def del_pending(uid: int) -> None:
    await jdrop(PENDING_FILE, str(uid))


async def get_admins() -> list[int]:
    raw = await jload(ADMINS_FILE, [])
    if not isinstance(raw, list):
        return []
    return [int(x) for x in raw if isinstance(x, (int, str)) and str(x).lstrip("-").isdigit()]


async def add_admin(uid: int) -> None:
    async with _lock(ADMINS_FILE):
        admins = []
        if os.path.exists(ADMINS_FILE):
            with open(ADMINS_FILE, "r", encoding="utf-8") as f:
                try:
                    admins = json.load(f)
                except Exception:
                    admins = []
        if not isinstance(admins, list):
            admins = []
        if uid not in admins and uid != SUPER_ADMIN:
            admins.append(uid)
        d = os.path.dirname(ADMINS_FILE) or "."
        fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=d)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(admins, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ADMINS_FILE)


async def remove_admin(uid: int) -> None:
    async with _lock(ADMINS_FILE):
        admins = []
        if os.path.exists(ADMINS_FILE):
            with open(ADMINS_FILE, "r", encoding="utf-8") as f:
                try:
                    admins = json.load(f)
                except Exception:
                    admins = []
        if not isinstance(admins, list):
            admins = []
        admins = [a for a in admins if a != uid]
        d = os.path.dirname(ADMINS_FILE) or "."
        fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=d)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(admins, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ADMINS_FILE)


async def is_approved(uid: int) -> bool:
    if uid == SUPER_ADMIN:
        return True
    return uid in await get_admins()


def is_super(uid: int) -> bool:
    return uid == SUPER_ADMIN


async def get_user_info(uid: int) -> dict:
    return (await jload(USERS_FILE, {})).get(str(uid), {})


async def set_user_info(uid: int, info: dict) -> None:
    await jpatch(USERS_FILE, str(uid), info)


async def del_user_info(uid: int) -> None:
    await jdrop(USERS_FILE, str(uid))


async def get_chats(uid: int) -> list[str]:
    return (await jload(CHATS_FILE, {})).get(str(uid), [])


async def set_chats(uid: int, chats: list[str]) -> None:
    await jpatch(CHATS_FILE, str(uid), chats)


async def del_chats(uid: int) -> None:
    await jdrop(CHATS_FILE, str(uid))


async def get_posts(uid: int) -> list[dict]:
    return (await jload(POSTS_FILE, {})).get(str(uid), [])


async def set_posts(uid: int, posts: list[dict]) -> None:
    await jpatch(POSTS_FILE, str(uid), posts)


async def del_posts(uid: int) -> None:
    await jdrop(POSTS_FILE, str(uid))


async def get_interval(uid: int) -> int:
    raw = (await jload(INTERVALS_FILE, {})).get(str(uid), MIN_INTERVAL_MIN)
    try:
        m = int(raw)
    except Exception:
        m = MIN_INTERVAL_MIN
    return max(MIN_INTERVAL_MIN, min(MAX_INTERVAL_MIN, m))


async def set_interval(uid: int, minutes: int) -> None:
    minutes = max(MIN_INTERVAL_MIN, min(MAX_INTERVAL_MIN, minutes))
    await jpatch(INTERVALS_FILE, str(uid), minutes)


async def del_interval(uid: int) -> None:
    await jdrop(INTERVALS_FILE, str(uid))


async def get_schedule(uid: int) -> tuple[dtime, dtime]:
    raw = (await jload(SCHEDULE_FILE, {})).get(str(uid))
    if not raw:
        return dtime(0, 0), dtime(23, 59)
    try:
        sh, sm = map(int, raw["start"].split(":"))
        eh, em = map(int, raw["end"].split(":"))
        return dtime(sh, sm), dtime(eh, em)
    except Exception:
        return dtime(0, 0), dtime(23, 59)


async def set_schedule(uid: int, start: dtime, end: dtime) -> None:
    await jpatch(
        SCHEDULE_FILE,
        str(uid),
        {"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")},
    )


async def del_schedule(uid: int) -> None:
    await jdrop(SCHEDULE_FILE, str(uid))


async def get_running(uid: int) -> bool:
    return bool((await jload(RUNNING_FILE, {})).get(str(uid), False))


async def set_running(uid: int, value: bool) -> None:
    await jpatch(RUNNING_FILE, str(uid), bool(value))


async def del_running(uid: int) -> None:
    await jdrop(RUNNING_FILE, str(uid))


# ─────────────────────────────────────────────────────────────────────────
# VAQT YORDAMCHILARI
# ─────────────────────────────────────────────────────────────────────────
def now_local() -> datetime:
    return datetime.now(timezone(timedelta(hours=DEFAULT_TZ_OFFSET)))


def in_window(now: datetime, start: dtime, end: dtime) -> bool:
    cur = now.time()
    if start <= end:
        return start <= cur <= end
    # tunda o'tuvchi oyna (masalan 22:00 - 06:00)
    return cur >= start or cur <= end


def seconds_to_window_open(now: datetime, start: dtime, end: dtime) -> int:
    """Oyna ochilguncha qancha soniya kutish kerak. Ichida bo'lsa 0."""
    if in_window(now, start, end):
        return 0
    today = now.date()
    candidate = datetime.combine(today, start, tzinfo=now.tzinfo)
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    return max(1, int((candidate - now).total_seconds()))


# ─────────────────────────────────────────────────────────────────────────
# ENTITY KONVERTOR (PTB → Telethon)
# ─────────────────────────────────────────────────────────────────────────
def entity_to_dict(e: MessageEntity) -> dict:
    d: dict[str, Any] = {"type": e.type, "offset": e.offset, "length": e.length}
    if e.url:
        d["url"] = e.url
    if e.language:
        d["language"] = e.language
    if e.custom_emoji_id:
        d["custom_emoji_id"] = e.custom_emoji_id
    if e.user:
        d["user_id"] = e.user.id
    return d


def dicts_to_telethon_entities(items: list[dict]) -> list:
    out = []
    for d in items or []:
        t = d.get("type")
        off = int(d.get("offset", 0))
        ln = int(d.get("length", 0))
        if t == "bold":
            out.append(MessageEntityBold(off, ln))
        elif t == "italic":
            out.append(MessageEntityItalic(off, ln))
        elif t == "underline":
            out.append(MessageEntityUnderline(off, ln))
        elif t == "strikethrough":
            out.append(MessageEntityStrike(off, ln))
        elif t == "spoiler":
            out.append(MessageEntitySpoiler(off, ln))
        elif t == "code":
            out.append(MessageEntityCode(off, ln))
        elif t == "pre":
            out.append(MessageEntityPre(off, ln, language=d.get("language", "") or ""))
        elif t == "text_link":
            out.append(MessageEntityTextUrl(off, ln, url=d.get("url", "")))
        elif t == "text_mention":
            uid = d.get("user_id")
            if uid:
                out.append(MessageEntityMentionName(off, ln, user_id=int(uid)))
        elif t == "url":
            out.append(MessageEntityUrl(off, ln))
        elif t == "mention":
            out.append(MessageEntityMention(off, ln))
        elif t == "hashtag":
            out.append(MessageEntityHashtag(off, ln))
        elif t == "cashtag":
            out.append(MessageEntityCashtag(off, ln))
        elif t == "bot_command":
            out.append(MessageEntityBotCommand(off, ln))
        elif t == "email":
            out.append(MessageEntityEmail(off, ln))
        elif t == "phone_number":
            out.append(MessageEntityPhone(off, ln))
        elif t == "custom_emoji":
            cid = d.get("custom_emoji_id")
            if cid:
                out.append(MessageEntityCustomEmoji(off, ln, document_id=int(cid)))
    return out


# ─────────────────────────────────────────────────────────────────────────
# IN-MEMORY HOLAT
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class LoginCtx:
    client: TelegramClient
    phone: str
    phone_code_hash: str
    started_at: float


@dataclass
class Worker:
    uid: int
    task: asyncio.Task
    stop_event: asyncio.Event


user_states: dict[int, dict] = {}     # FSM (login, post qo'shish va h.k.)
login_ctx: dict[int, LoginCtx] = {}   # Login jarayonidagi temp clientlar
workers: dict[int, Worker] = {}       # Faol posting tasklar
application: Application | None = None


# ─────────────────────────────────────────────────────────────────────────
# MENYU
# ─────────────────────────────────────────────────────────────────────────
def kb_login() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton("🔑 Login")]], resize_keyboard=True)


def kb_pending() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("⏳ Tasdiq kutilmoqda...")]], resize_keyboard=True
    )


def kb_main(interval: int, sched: tuple[dtime, dtime], running: bool, super_admin: bool) -> ReplyKeyboardMarkup:
    on = "🟢 ON" if running else "🔴 OFF"
    s = sched[0].strftime("%H:%M")
    e = sched[1].strftime("%H:%M")
    rows = [
        [KeyboardButton("▶️ Start"), KeyboardButton("⛔ Stop")],
        [KeyboardButton(f"📊 Status ({on})"), KeyboardButton("💬 Chatlar")],
        [KeyboardButton("➕ Chat qo'sh"), KeyboardButton("➖ Chat o'chir")],
        [KeyboardButton("📝 Post qo'sh"), KeyboardButton("🗑 Post o'chir")],
        [KeyboardButton("📋 Postlar"), KeyboardButton("🧹 Tozalash")],
        [KeyboardButton(f"⏱ Interval: {interval} daq"), KeyboardButton(f"🕒 Vaqt: {s}–{e}")],
        [KeyboardButton("🚪 Logout")],
    ]
    if super_admin:
        rows.append([KeyboardButton("👥 Adminlar")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


async def menu_for(uid: int) -> ReplyKeyboardMarkup:
    if not await is_approved(uid):
        if await get_pending(uid):
            return kb_pending()
        return kb_login()
    if not await get_session(uid):
        return kb_login()
    interval = await get_interval(uid)
    sched = await get_schedule(uid)
    running = uid in workers
    return kb_main(interval, sched, running, is_super(uid))


# ─────────────────────────────────────────────────────────────────────────
# LOGIN OQIMI YORDAMCHILARI
# ─────────────────────────────────────────────────────────────────────────
async def cleanup_login(uid: int) -> None:
    ctx = login_ctx.pop(uid, None)
    if ctx:
        with contextlib.suppress(Exception):
            await ctx.client.disconnect()
    user_states.pop(uid, None)


async def notify_super_for_approval(uid: int) -> None:
    info = await get_user_info(uid)
    name = info.get("name", "Noma'lum")
    username = f"@{info.get('username')}" if info.get("username") else "username yo'q"
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ ON (tasdiqlash)", callback_data=f"app:on:{uid}"),
                InlineKeyboardButton("⛔ OFF (rad etish)", callback_data=f"app:off:{uid}"),
            ]
        ]
    )
    text = (
        "🔔 Yangi foydalanuvchi tasdiq so'ramoqda\n\n"
        f"👤 Ism: {name}\n"
        f"📎 {username}\n"
        f"🆔 ID: {uid}\n\n"
        "ON bossangiz — foydalanuvchi botdan to'liq foydalana boshlaydi.\n"
        "OFF bossangiz — sessiyasi o'chiriladi va bot ishlatishni rad etadi."
    )
    with contextlib.suppress(Exception):
        await application.bot.send_message(SUPER_ADMIN, text, reply_markup=kb)


# ─────────────────────────────────────────────────────────────────────────
# POSTING WORKER (har foydalanuvchi uchun)
# ─────────────────────────────────────────────────────────────────────────
async def _resolve_chat(client: TelegramClient, chat: str):
    """Username yoki id (string) ni Telethon entity-ga aylantiradi."""
    s = chat.strip()
    if s.startswith("@"):
        return await client.get_entity(s)
    if s.lstrip("-").isdigit():
        return await client.get_entity(int(s))
    if s.startswith("https://t.me/") or s.startswith("t.me/"):
        return await client.get_entity(s)
    return await client.get_entity(s)


async def _send_post(client: TelegramClient, chat: str, post: dict) -> None:
    text = post.get("text", "")
    entities = dicts_to_telethon_entities(post.get("entities", []))
    target = await _resolve_chat(client, chat)
    await client.send_message(
        entity=target,
        message=text,
        formatting_entities=entities or None,
        link_preview=bool(post.get("link_preview", True)),
    )


async def _stop_worker(uid: int, *, persist: bool = True) -> None:
    w = workers.pop(uid, None)
    if w:
        w.stop_event.set()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(w.task, timeout=10)
    if persist:
        await set_running(uid, False)


async def _start_worker(uid: int) -> None:
    if uid in workers:
        return
    stop_event = asyncio.Event()
    task = asyncio.create_task(posting_loop(uid, stop_event), name=f"poster-{uid}")
    workers[uid] = Worker(uid=uid, task=task, stop_event=stop_event)
    await set_running(uid, True)


async def posting_loop(uid: int, stop: asyncio.Event) -> None:
    log(f"🟢 Worker:{uid} ishga tushdi")
    client: TelegramClient | None = None
    try:
        while not stop.is_set():
            sess = await get_session(uid)
            if not sess:
                log(f"❌ Worker:{uid} sessiya yo'q — to'xtaydi", "warning")
                break

            chats = await get_chats(uid)
            posts = await get_posts(uid)
            interval = await get_interval(uid)
            sched = await get_schedule(uid)

            if not chats or not posts:
                await _sleep_or_stop(stop, 30)
                continue

            # Vaqt oynasi tashqarisida bo'lsak — kutamiz
            now = now_local()
            wait_open = seconds_to_window_open(now, sched[0], sched[1])
            if wait_open > 0:
                log(f"⏳ Worker:{uid} oyna ochilguncha {wait_open}s kutadi")
                if await _sleep_or_stop(stop, wait_open):
                    break
                continue

            # Telethon klientni faol ushlab turamiz
            try:
                if client is None:
                    client = TelegramClient(StringSession(sess), API_ID, API_HASH)
                if not client.is_connected():
                    await asyncio.wait_for(client.connect(), timeout=20)
                if not await client.is_user_authorized():
                    raise AuthKeyUnregisteredError(request=None)
            except AuthKeyUnregisteredError:
                log(f"🚫 Worker:{uid} — sessiya bekor qilingan", "error")
                await del_session(uid)
                with contextlib.suppress(Exception):
                    await application.bot.send_message(
                        uid,
                        "🚫 Sessiyangiz Telegram tomonidan bekor qilindi.\n"
                        "Qaytadan 🔑 Login qiling.",
                    )
                break
            except (UserDeactivatedBanError,):
                log(f"🚫 Worker:{uid} — hisob bloklangan", "error")
                await del_session(uid)
                with contextlib.suppress(Exception):
                    await application.bot.send_message(
                        uid, "🚫 Hisobingiz Telegram tomonidan bloklangan."
                    )
                break
            except (asyncio.TimeoutError, OSError) as e:
                log(f"⚠️ Worker:{uid} ulanish xatosi: {e} — 30s kutadi", "warning")
                if await _sleep_or_stop(stop, 30):
                    break
                continue

            # Bitta tasodifiy postni barcha chatlarga yuboramiz
            post = random.choice(posts)
            ok, fail = 0, 0
            for chat in chats:
                if stop.is_set():
                    break
                try:
                    await asyncio.wait_for(_send_post(client, chat, post), timeout=20)
                    ok += 1
                    log(f"✅ {uid} → {chat}")
                except FloodWaitError as e:
                    wait_s = int(getattr(e, "seconds", 30)) + 5
                    log(f"⏳ {uid} → {chat} FloodWait {wait_s}s", "warning")
                    if await _sleep_or_stop(stop, wait_s):
                        break
                except (
                    ChatWriteForbiddenError,
                    ChannelPrivateError,
                    PeerIdInvalidError,
                    UsernameNotOccupiedError,
                    UsernameInvalidError,
                    ValueError,
                ) as e:
                    fail += 1
                    log(f"❌ {uid} → {chat}: {type(e).__name__}", "warning")
                except asyncio.TimeoutError:
                    fail += 1
                    log(f"⏱ {uid} → {chat} timeout", "warning")
                except Exception as e:
                    fail += 1
                    log(f"❌ {uid} → {chat}: {type(e).__name__}: {e}", "error")
                # Anti-spam: chatlar orasidagi pauza
                if not stop.is_set():
                    await _sleep_or_stop(stop, SEND_DELAY_S)

            log(f"📊 {uid} ✅{ok} ❌{fail} / {len(chats)}")

            # Keyingi turgacha kutish (jitter bilan)
            delay = interval * 60 + random.randint(-INTERVAL_JITTER_S, INTERVAL_JITTER_S)
            delay = max(MIN_INTERVAL_MIN * 60, delay)
            log(f"⏳ {uid} keyingi tur {delay}s ({interval} daq)")
            if await _sleep_or_stop(stop, delay):
                break
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log(f"💥 Worker:{uid} kutilmagan xato: {type(e).__name__}: {e}", "error")
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                SUPER_ADMIN, f"⚠️ Worker xato\nUID: {uid}\n{type(e).__name__}: {e}"
            )
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.disconnect()
        log(f"🔴 Worker:{uid} to'xtadi")


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> bool:
    """seconds davomida kutadi yoki stop signaliga javob beradi.
    True qaytarsa — to'xtatish kerak."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return False


# ─────────────────────────────────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id

    if await get_pending(uid) and not await is_approved(uid):
        await update.message.reply_text(
            "⏳ Sizning so'rovingiz ko'rib chiqilmoqda.\nAdmin tasdiqlashini kuting.",
            reply_markup=await menu_for(uid),
        )
        return

    if await is_approved(uid) and await get_session(uid):
        await update.message.reply_text(
            "🤖 AVTO BOT\n\nSiz tizimga kirgansiz!",
            reply_markup=await menu_for(uid),
        )
        return

    await update.message.reply_text(
        "🤖 AVTO BOT ga xush kelibsiz!\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "📋 BOSHLASH:\n\n"
        "1️⃣ '🔑 Login' tugmasini bosing\n"
        "2️⃣ Telefon raqamingizni kiriting (+998XXXXXXXXX)\n"
        "3️⃣ Telegramdan kelgan kodni kiriting\n"
        "4️⃣ 2FA bo'lsa — parolni kiriting\n"
        "5️⃣ Admin tasdiqlashini kuting (ON/OFF)\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "🛡 XAVFSIZLIK:\n\n"
        "✅ Kod va parol HECH QAYERDA saqlanmaydi\n"
        "✅ Faqat session token saqlanadi (siz Logout qilsangiz o'chadi)\n"
        "✅ Istalgan vaqt '🚪 Logout' orqali chiqishingiz mumkin\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ IMKONIYATLAR:\n\n"
        f"• Maksimal {MAX_CHATS} ta chat\n"
        f"• Maksimal {MAX_POSTS} ta post\n"
        f"• Interval: {MIN_INTERVAL_MIN}–{MAX_INTERVAL_MIN} daqiqa\n"
        "• Yuborish vaqt oynasini siz belgilaysiz (HH:MM–HH:MM)\n"
        "• Postingiz formatlash bilan birga jo'natiladi",
        reply_markup=await menu_for(uid),
    )


# ─────────────────────────────────────────────────────────────────────────
# CALLBACK
# ─────────────────────────────────────────────────────────────────────────
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data or ""

    # Yangi foydalanuvchi tasdiqlash: app:on:<id> | app:off:<id>
    if data.startswith("app:on:") or data.startswith("app:off:"):
        if not is_super(uid):
            return
        action = "on" if ":on:" in data else "off"
        target = int(data.split(":")[2])
        sess = await get_pending(target)
        if action == "on":
            if not sess:
                await q.edit_message_text(f"⚠️ {target} pending sessiyasi topilmadi.")
                return
            await set_session(target, sess)
            await del_pending(target)
            await add_admin(target)
            log(f"✅ Tasdiqlandi: {target}")
            await q.edit_message_text(f"✅ Tasdiqlandi: {target}")
            with contextlib.suppress(Exception):
                info = await get_user_info(target)
                name = info.get("name", "Foydalanuvchi")
                await application.bot.send_message(
                    target,
                    f"✅ {name}, hisobingiz tasdiqlandi!\n\n"
                    "Endi:\n"
                    f"1️⃣ ➕ Chat qo'shing (max {MAX_CHATS})\n"
                    f"2️⃣ 📝 Post qo'shing (max {MAX_POSTS})\n"
                    "3️⃣ ⏱ Interval va 🕒 vaqt oynasini sozlang\n"
                    "4️⃣ ▶️ Start bosing",
                    reply_markup=await menu_for(target),
                )
        else:  # off
            await del_pending(target)
            await del_session(target)
            log(f"❌ Rad etildi: {target}")
            await q.edit_message_text(f"⛔ Rad etildi: {target}")
            with contextlib.suppress(Exception):
                await application.bot.send_message(
                    target,
                    "❌ Sizning so'rovingiz rad etildi.\nQayta urinib ko'rishingiz mumkin.",
                    reply_markup=await menu_for(target),
                )
        return

    # Admin o'chirish (super admin)
    if data.startswith("rmadm:"):
        if not is_super(uid):
            return
        target = int(data.split(":")[1])
        await _stop_worker(target, persist=True)
        await remove_admin(target)
        await del_session(target)
        await del_pending(target)
        await del_chats(target)
        await del_posts(target)
        await del_interval(target)
        await del_schedule(target)
        await del_user_info(target)
        await del_running(target)
        log(f"🗑 Admin o'chirildi: {target}")
        await q.edit_message_text(f"🗑 O'chirildi: {target}")
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                target,
                "❌ Sizning huquqingiz bekor qilindi va ma'lumotlaringiz tozalandi.",
            )
        return

    if data == "rmadm:cancel":
        await q.edit_message_text("❌ Bekor qilindi.")
        return

    # Stop tasdiq
    if data == "stop:yes":
        await _stop_worker(uid, persist=True)
        await q.edit_message_text("⛔ Posting to'xtatildi.")
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                uid, "Holat yangilandi.", reply_markup=await menu_for(uid)
            )
        return
    if data == "stop:no":
        await q.edit_message_text("✅ Posting davom etmoqda.")
        return

    # Postlar tozalash
    if data == "clr:yes":
        await set_posts(uid, [])
        log(f"🧹 Postlar tozalandi: {uid}")
        await q.edit_message_text("🧹 Barcha postlar tozalandi.")
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                uid, "Holat yangilandi.", reply_markup=await menu_for(uid)
            )
        return
    if data == "clr:no":
        await q.edit_message_text("❌ Bekor qilindi.")
        return

    # Logout tasdiq
    if data == "out:yes":
        await _stop_worker(uid, persist=True)
        await del_session(uid)
        user_states.pop(uid, None)
        log(f"🚪 Logout: {uid}")
        await q.edit_message_text("🚪 Tizimdan chiqdingiz.")
        with contextlib.suppress(Exception):
            await application.bot.send_message(
                uid,
                "Qaytadan kirish uchun 🔑 Login bosing.",
                reply_markup=await menu_for(uid),
            )
        return
    if data == "out:no":
        await q.edit_message_text("❌ Bekor qilindi.")
        return

    # Bitta postni o'chirish
    if data.startswith("delp:"):
        try:
            i = int(data.split(":")[1])
        except Exception:
            return
        posts = await get_posts(uid)
        if 0 <= i < len(posts):
            removed = posts.pop(i)
            await set_posts(uid, posts)
            preview = (removed.get("text") or "")[:80]
            log(f"🗑 Post {i+1} o'chirildi: {uid}")
            await q.edit_message_text(f"🗑 O'chirildi:\n{preview}")
            with contextlib.suppress(Exception):
                await application.bot.send_message(
                    uid, "Holat yangilandi.", reply_markup=await menu_for(uid)
                )
        else:
            await q.edit_message_text("❌ Post topilmadi.")
        return
    if data == "delp:cancel":
        await q.edit_message_text("❌ Bekor qilindi.")
        return

    # Bitta chatni o'chirish
    if data.startswith("delc:"):
        try:
            i = int(data.split(":")[1])
        except Exception:
            return
        chats = await get_chats(uid)
        if 0 <= i < len(chats):
            removed = chats.pop(i)
            await set_chats(uid, chats)
            log(f"🗑 Chat {removed} o'chirildi: {uid}")
            await q.edit_message_text(f"🗑 O'chirildi: {removed}")
            with contextlib.suppress(Exception):
                await application.bot.send_message(
                    uid, "Holat yangilandi.", reply_markup=await menu_for(uid)
                )
        else:
            await q.edit_message_text("❌ Chat topilmadi.")
        return
    if data == "delc:cancel":
        await q.edit_message_text("❌ Bekor qilindi.")
        return

    # Adminlar paneli
    if data == "adm:list":
        if not is_super(uid):
            return
        await q.edit_message_text(await format_admin_list(), reply_markup=admin_panel_kb())
        return

    if data == "adm:remove":
        if not is_super(uid):
            return
        admins = await get_admins()
        if not admins:
            await q.edit_message_text("❌ O'chirish uchun admin yo'q.")
            return
        rows = []
        for a in admins:
            info = await get_user_info(a)
            name = info.get("name", str(a))
            rows.append([InlineKeyboardButton(f"🗑 {name} ({a})", callback_data=f"rmadm:{a}")])
        rows.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="rmadm:cancel")])
        await q.edit_message_text(
            "➖ O'chirish uchun adminni tanlang:", reply_markup=InlineKeyboardMarkup(rows)
        )
        return


def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Yangilash", callback_data="adm:list"),
                InlineKeyboardButton("➖ Admin o'chir", callback_data="adm:remove"),
            ]
        ]
    )


async def format_admin_list() -> str:
    admins = await get_admins()
    lines = [f"👥 ADMINLAR ({len(admins)} ta):", "", f"• 👑 Super admin ({SUPER_ADMIN})"]
    for a in admins:
        info = await get_user_info(a)
        name = info.get("name", "Noma'lum")
        username = f"@{info.get('username')}" if info.get("username") else "username yo'q"
        s = "✅" if await get_session(a) else "❌"
        ac = "🟢" if a in workers else "🔴"
        interval = await get_interval(a)
        sched = await get_schedule(a)
        chats_n = len(await get_chats(a))
        posts_n = len(await get_posts(a))
        lines.append("")
        lines.append(f"👤 {name}")
        lines.append(f"   {username} | {a}")
        lines.append(f"   Sessiya: {s} | Holat: {ac}")
        lines.append(
            f"   💬 {chats_n} | 📝 {posts_n} | ⏱ {interval} daq | "
            f"🕒 {sched[0].strftime('%H:%M')}–{sched[1].strftime('%H:%M')}"
        )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────
# MESSAGE HANDLER
# ─────────────────────────────────────────────────────────────────────────
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    msg = update.message
    text = (msg.text or "").strip()
    state = user_states.get(uid, {})
    step = state.get("step")

    # ── LOGIN BOSQICHLARI ────────────────────────────────────────────────
    if step in ("phone", "code", "password"):
        if time.time() - state.get("ts", 0) > LOGIN_TIMEOUT_S:
            await cleanup_login(uid)
            await msg.reply_text(
                "⏰ Vaqt tugadi (5 daqiqa). Qaytadan 🔑 Login bosing.",
                reply_markup=await menu_for(uid),
            )
            return

        if step == "phone":
            await _handle_phone(update, text)
            return
        if step == "code":
            await _handle_code(update, text)
            return
        if step == "password":
            await _handle_password(update, text)
            return

    # ── PENDING ──────────────────────────────────────────────────────────
    if not await is_approved(uid):
        if await get_pending(uid):
            await msg.reply_text(
                "⏳ So'rovingiz ko'rib chiqilmoqda. Admin tasdiqlashini kuting.",
                reply_markup=kb_pending(),
            )
            return
        # Tasdiqlanmagan, login boshlash
        if text == "🔑 Login":
            await _begin_login(update)
            return
        await msg.reply_text(
            "⚠️ Avval 🔑 Login qiling va admin tasdiqlashini kuting.",
            reply_markup=kb_login(),
        )
        return

    # ── FSM: input qabul qilish ─────────────────────────────────────────
    if step == "add_chat":
        await _handle_add_chat(update, text)
        return
    if step == "remove_chat_text":
        await _handle_remove_chat_text(update, text)
        return
    if step == "add_post":
        await _handle_add_post(update)
        return
    if step == "set_interval":
        await _handle_set_interval(update, text)
        return
    if step == "set_schedule":
        await _handle_set_schedule(update, text)
        return

    # ── MENYU TUGMALARI ──────────────────────────────────────────────────
    sess = await get_session(uid)
    if not sess:
        if text == "🔑 Login":
            await _begin_login(update)
            return
        await msg.reply_text(
            "⚠️ Avval 🔑 Login qiling.", reply_markup=kb_login()
        )
        return

    if text == "🔑 Login":
        await msg.reply_text("✅ Siz allaqachon kirgansiz.", reply_markup=await menu_for(uid))
        return

    if text == "🚪 Logout":
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Ha", callback_data="out:yes"),
                    InlineKeyboardButton("❌ Yo'q", callback_data="out:no"),
                ]
            ]
        )
        await msg.reply_text(
            "🚪 Tizimdan chiqasizmi?\n\nPosting to'xtaydi va sessiya o'chadi.",
            reply_markup=kb,
        )
        return

    if text == "▶️ Start":
        if uid in workers:
            await msg.reply_text("⚠️ Allaqachon ishlamoqda.", reply_markup=await menu_for(uid))
            return
        chats = await get_chats(uid)
        posts = await get_posts(uid)
        if not chats:
            await msg.reply_text("❌ Avval ➕ Chat qo'shing.", reply_markup=await menu_for(uid))
            return
        if not posts:
            await msg.reply_text("❌ Avval 📝 Post qo'shing.", reply_markup=await menu_for(uid))
            return
        await _start_worker(uid)
        interval = await get_interval(uid)
        sched = await get_schedule(uid)
        await msg.reply_text(
            f"✅ Posting boshlandi!\n"
            f"💬 {len(chats)} ta chat\n"
            f"📝 {len(posts)} ta post\n"
            f"⏱ Har {interval} daqiqada\n"
            f"🕒 Vaqt: {sched[0].strftime('%H:%M')}–{sched[1].strftime('%H:%M')}",
            reply_markup=await menu_for(uid),
        )
        return

    if text == "⛔ Stop":
        if uid not in workers:
            await msg.reply_text("⚠️ Hozir ishlamayapti.", reply_markup=await menu_for(uid))
            return
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Ha", callback_data="stop:yes"),
                    InlineKeyboardButton("❌ Yo'q", callback_data="stop:no"),
                ]
            ]
        )
        await msg.reply_text("⛔ Postingni to'xtatasizmi?", reply_markup=kb)
        return

    if text.startswith("📊 Status"):
        chats = await get_chats(uid)
        posts = await get_posts(uid)
        interval = await get_interval(uid)
        sched = await get_schedule(uid)
        active = uid in workers
        now = now_local()
        in_w = in_window(now, sched[0], sched[1])
        status = "🟢 ON" if active else "🔴 OFF"
        win = "🟢 oynada" if in_w else "🟡 oyna tashqarisida"
        await msg.reply_text(
            "📊 STATUS\n\n"
            f"Holat: {status}\n"
            f"Sessiya: ✅\n"
            f"Chatlar: {len(chats)}/{MAX_CHATS}\n"
            f"Postlar: {len(posts)}/{MAX_POSTS}\n"
            f"Interval: {interval} daqiqa\n"
            f"Vaqt: {sched[0].strftime('%H:%M')}–{sched[1].strftime('%H:%M')} ({win})\n"
            f"Hozir: {now.strftime('%H:%M')}",
            reply_markup=await menu_for(uid),
        )
        return

    if text == "💬 Chatlar":
        chats = await get_chats(uid)
        if not chats:
            await msg.reply_text("❌ Chatlar yo'q.", reply_markup=await menu_for(uid))
            return
        lines = [f"💬 CHATLAR ({len(chats)}/{MAX_CHATS}):", ""]
        lines += [f"{i}. {c}" for i, c in enumerate(chats, 1)]
        await msg.reply_text("\n".join(lines), reply_markup=await menu_for(uid))
        return

    if text == "➕ Chat qo'sh":
        chats = await get_chats(uid)
        if len(chats) >= MAX_CHATS:
            await msg.reply_text(
                f"❌ Maksimal {MAX_CHATS} ta chat. Avval birini o'chiring.",
                reply_markup=await menu_for(uid),
            )
            return
        user_states[uid] = {"step": "add_chat", "ts": time.time()}
        await msg.reply_text(
            "➕ Chat @username, https://t.me/... yoki ID yuboring.\n\n"
            f"Hozir: {len(chats)}/{MAX_CHATS}"
        )
        return

    if text == "➖ Chat o'chir":
        chats = await get_chats(uid)
        if not chats:
            await msg.reply_text("❌ Chatlar yo'q.", reply_markup=await menu_for(uid))
            return
        rows = [
            [InlineKeyboardButton(f"🗑 {i+1}. {c[:40]}", callback_data=f"delc:{i}")]
            for i, c in enumerate(chats)
        ]
        rows.append([InlineKeyboardButton("❌ Bekor", callback_data="delc:cancel")])
        await msg.reply_text(
            f"➖ O'chirish uchun chatni tanlang ({len(chats)} ta):",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if text == "📝 Post qo'sh":
        posts = await get_posts(uid)
        if len(posts) >= MAX_POSTS:
            await msg.reply_text(
                f"❌ Maksimal {MAX_POSTS} ta post.", reply_markup=await menu_for(uid)
            )
            return
        user_states[uid] = {"step": "add_post", "ts": time.time()}
        await msg.reply_text(
            "✍️ Reklama matnini formatlash bilan yuboring.\n\n"
            "Bold, italic, link va barcha formatlash saqlanadi.\n"
            f"📝 Hozir: {len(posts)}/{MAX_POSTS}"
        )
        return

    if text == "🗑 Post o'chir":
        posts = await get_posts(uid)
        if not posts:
            await msg.reply_text("❌ Postlar yo'q.", reply_markup=await menu_for(uid))
            return
        rows = []
        for i, p in enumerate(posts):
            preview = (p.get("text") or "")[:30]
            rows.append([InlineKeyboardButton(f"🗑 {i+1}. {preview}", callback_data=f"delp:{i}")])
        rows.append([InlineKeyboardButton("❌ Bekor", callback_data="delp:cancel")])
        await msg.reply_text(
            f"🗑 O'chirish uchun postni tanlang ({len(posts)} ta):",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if text == "📋 Postlar":
        posts = await get_posts(uid)
        if not posts:
            await msg.reply_text("❌ Postlar yo'q.", reply_markup=await menu_for(uid))
            return
        lines = [f"📋 POSTLAR ({len(posts)} ta):", ""]
        for i, p in enumerate(posts, 1):
            t = (p.get("text") or "")[:80]
            lines.append(f"{i}. {t}")
        await msg.reply_text("\n".join(lines), reply_markup=await menu_for(uid))
        return

    if text == "🧹 Tozalash":
        posts = await get_posts(uid)
        if not posts:
            await msg.reply_text("❌ Postlar yo'q.", reply_markup=await menu_for(uid))
            return
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Ha", callback_data="clr:yes"),
                    InlineKeyboardButton("❌ Yo'q", callback_data="clr:no"),
                ]
            ]
        )
        await msg.reply_text(f"🧹 Barcha {len(posts)} ta post o'chirilsinmi?", reply_markup=kb)
        return

    if text.startswith("⏱ Interval"):
        interval = await get_interval(uid)
        user_states[uid] = {"step": "set_interval", "ts": time.time()}
        await msg.reply_text(
            f"⏱ INTERVAL\n\n"
            f"Hozir: {interval} daqiqa\n"
            f"Yangi qiymatni kiriting ({MIN_INTERVAL_MIN}–{MAX_INTERVAL_MIN} daq):"
        )
        return

    if text.startswith("🕒 Vaqt"):
        sched = await get_schedule(uid)
        user_states[uid] = {"step": "set_schedule", "ts": time.time()}
        await msg.reply_text(
            f"🕒 VAQT OYNASI\n\n"
            f"Hozir: {sched[0].strftime('%H:%M')}–{sched[1].strftime('%H:%M')}\n\n"
            "Yangi oynani kiriting (HH:MM-HH:MM ko'rinishida).\n"
            "Masalan: 09:00-22:00\n"
            "Tunda o'tuvchi oyna ham mumkin: 22:00-06:00\n"
            "Butun kun: 00:00-23:59"
        )
        return

    if text == "👥 Adminlar" and is_super(uid):
        await msg.reply_text(await format_admin_list(), reply_markup=admin_panel_kb())
        return

    # Bilinmagan tugma
    await msg.reply_text("⚠️ Iltimos, menyudagi tugmalardan foydalaning.", reply_markup=await menu_for(uid))


# ─────────────────────────────────────────────────────────────────────────
# LOGIN BOSQICHLARI
# ─────────────────────────────────────────────────────────────────────────
async def _begin_login(update: Update) -> None:
    uid = update.effective_user.id
    user_states[uid] = {"step": "phone", "ts": time.time()}
    await update.message.reply_text(
        "📱 Telefon raqamingizni yuboring (+998XXXXXXXXX):"
    )


async def _handle_phone(update: Update, text: str) -> None:
    uid = update.effective_user.id
    phone = text.strip().replace(" ", "")
    if not phone.startswith("+") or not phone[1:].isdigit() or len(phone) < 7:
        await update.message.reply_text(
            "❌ Telefon + bilan, faqat raqamlardan iborat bo'lishi kerak.\nMasalan: +998901234567"
        )
        return
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        result = await client.send_code_request(phone)
        login_ctx[uid] = LoginCtx(
            client=client,
            phone=phone,
            phone_code_hash=result.phone_code_hash,
            started_at=time.time(),
        )
        user_states[uid] = {"step": "code", "ts": time.time()}
        await update.message.reply_text(
            "📩 Telegramdan kelgan kodni yuboring.\n\n"
            "⚠️ Kodni shu ko'rinishda yuboring: 1 2 3 4 5 (probel bilan) yoki 12345"
        )
    except PhoneNumberInvalidError:
        with contextlib.suppress(Exception):
            await client.disconnect()
        await cleanup_login(uid)
        await update.message.reply_text(
            "❌ Noto'g'ri raqam. Qaytadan 🔑 Login bosing.",
            reply_markup=await menu_for(uid),
        )
    except PhoneNumberBannedError:
        with contextlib.suppress(Exception):
            await client.disconnect()
        await cleanup_login(uid)
        await update.message.reply_text(
            "🚫 Bu raqam bloklangan.", reply_markup=await menu_for(uid)
        )
    except FloodWaitError as e:
        with contextlib.suppress(Exception):
            await client.disconnect()
        await cleanup_login(uid)
        await update.message.reply_text(
            f"⏳ Juda ko'p urinish. {e.seconds} soniya kuting.",
            reply_markup=await menu_for(uid),
        )
    except Exception as e:
        with contextlib.suppress(Exception):
            await client.disconnect()
        await cleanup_login(uid)
        log(f"❌ phone {uid}: {type(e).__name__}: {e}", "error")
        await update.message.reply_text(
            f"❌ Xatolik: {type(e).__name__}\nQaytadan 🔑 Login bosing.",
            reply_markup=await menu_for(uid),
        )


async def _handle_code(update: Update, text: str) -> None:
    uid = update.effective_user.id
    code = "".join(c for c in text if c.isdigit())
    if not code:
        await update.message.reply_text("❌ Kod faqat raqamlardan iborat bo'lishi kerak.")
        return
    ctx = login_ctx.get(uid)
    if not ctx:
        await cleanup_login(uid)
        await update.message.reply_text(
            "❌ Jarayon buzildi. Qaytadan 🔑 Login bosing.",
            reply_markup=await menu_for(uid),
        )
        return
    try:
        if not ctx.client.is_connected():
            await asyncio.wait_for(ctx.client.connect(), timeout=20)
        await ctx.client.sign_in(
            phone=ctx.phone, code=code, phone_code_hash=ctx.phone_code_hash
        )
        await _finalize_login(update, ctx)
    except SessionPasswordNeededError:
        user_states[uid] = {"step": "password", "ts": time.time()}
        await update.message.reply_text(
            "🔐 2FA parolingizni yuboring.\n\n✅ Parol DISK-ga saqlanmaydi."
        )
    except PhoneCodeInvalidError:
        await update.message.reply_text(
            "❌ Noto'g'ri kod. Telegramdagi ENG SO'NGGI kodni yuboring."
        )
    except PhoneCodeExpiredError:
        await cleanup_login(uid)
        await update.message.reply_text(
            "⏰ Kod muddati tugadi. Qaytadan 🔑 Login bosing.",
            reply_markup=await menu_for(uid),
        )
    except FloodWaitError as e:
        await cleanup_login(uid)
        await update.message.reply_text(
            f"⏳ {e.seconds} soniya kuting.", reply_markup=await menu_for(uid)
        )
    except Exception as e:
        await cleanup_login(uid)
        log(f"❌ code {uid}: {type(e).__name__}: {e}", "error")
        await update.message.reply_text(
            f"❌ Xatolik: {type(e).__name__}\nQaytadan 🔑 Login bosing.",
            reply_markup=await menu_for(uid),
        )


async def _handle_password(update: Update, text: str) -> None:
    uid = update.effective_user.id
    ctx = login_ctx.get(uid)
    if not ctx:
        await cleanup_login(uid)
        await update.message.reply_text(
            "❌ Jarayon buzildi. Qaytadan 🔑 Login bosing.",
            reply_markup=await menu_for(uid),
        )
        return
    try:
        if not ctx.client.is_connected():
            await asyncio.wait_for(ctx.client.connect(), timeout=20)
        await ctx.client.sign_in(password=text)
        await _finalize_login(update, ctx)
    except PasswordHashInvalidError:
        await update.message.reply_text("❌ Noto'g'ri parol. Qaytadan kiriting:")
    except FloodWaitError as e:
        await cleanup_login(uid)
        await update.message.reply_text(
            f"⏳ {e.seconds} soniya kuting.", reply_markup=await menu_for(uid)
        )
    except Exception as e:
        await cleanup_login(uid)
        log(f"❌ password {uid}: {type(e).__name__}: {e}", "error")
        await update.message.reply_text(
            f"❌ Xatolik: {type(e).__name__}\nQaytadan 🔑 Login bosing.",
            reply_markup=await menu_for(uid),
        )


async def _finalize_login(update: Update, ctx: LoginCtx) -> None:
    uid = update.effective_user.id
    sess_str = ctx.client.session.save()
    with contextlib.suppress(Exception):
        await ctx.client.disconnect()
    login_ctx.pop(uid, None)
    user_states.pop(uid, None)

    user = update.effective_user
    await set_user_info(
        uid,
        {
            "name": user.full_name or "Noma'lum",
            "username": user.username or "",
        },
    )

    # Super admin avtomatik tasdiqlanadi
    if uid == SUPER_ADMIN:
        await set_session(uid, sess_str)
        await del_pending(uid)
        log(f"✅ Super admin login: {uid}")
        await update.message.reply_text(
            "✅ Super admin sifatida tizimga kirdingiz!", reply_markup=await menu_for(uid)
        )
        return

    await set_pending(uid, sess_str)
    log(f"⏳ Tasdiq kutilmoqda: {uid}")
    await notify_super_for_approval(uid)
    await update.message.reply_text(
        "✅ Login qabul qilindi!\n\n"
        "⏳ Admin tasdiqlashini kuting (ON/OFF).\n"
        "Tasdiqlanganingizdan so'ng menyu ochiladi.",
        reply_markup=await menu_for(uid),
    )


# ─────────────────────────────────────────────────────────────────────────
# CHAT / POST / INTERVAL / SCHEDULE INPUT
# ─────────────────────────────────────────────────────────────────────────
async def _handle_add_chat(update: Update, text: str) -> None:
    uid = update.effective_user.id
    user_states.pop(uid, None)
    chat = text.strip()
    if not chat:
        await update.message.reply_text("❌ Bo'sh.", reply_markup=await menu_for(uid))
        return
    chats = await get_chats(uid)
    if len(chats) >= MAX_CHATS:
        await update.message.reply_text(
            f"❌ Maksimal {MAX_CHATS} ta.", reply_markup=await menu_for(uid)
        )
        return
    if chat in chats:
        await update.message.reply_text(
            "⚠️ Allaqachon mavjud.", reply_markup=await menu_for(uid)
        )
        return
    chats.append(chat)
    await set_chats(uid, chats)
    log(f"💬 Chat qo'shildi: {uid} → {chat}")
    await update.message.reply_text(
        f"✅ Qo'shildi: {chat}\n💬 Jami: {len(chats)}/{MAX_CHATS}",
        reply_markup=await menu_for(uid),
    )


async def _handle_remove_chat_text(update: Update, text: str) -> None:
    # Ehtiyot uchun qoldirilgan, lekin endi tugma orqali o'chiriladi
    uid = update.effective_user.id
    user_states.pop(uid, None)
    chats = await get_chats(uid)
    if text in chats:
        chats.remove(text)
        await set_chats(uid, chats)
        await update.message.reply_text(f"🗑 O'chirildi: {text}", reply_markup=await menu_for(uid))
    else:
        await update.message.reply_text("❌ Topilmadi.", reply_markup=await menu_for(uid))


async def _handle_add_post(update: Update) -> None:
    uid = update.effective_user.id
    user_states.pop(uid, None)
    msg = update.message
    text = msg.text or msg.caption or ""
    entities_src = list(msg.entities or []) + list(msg.caption_entities or [])
    if not text.strip():
        await update.message.reply_text(
            "❌ Bo'sh post qabul qilinmaydi.", reply_markup=await menu_for(uid)
        )
        return
    posts = await get_posts(uid)
    if len(posts) >= MAX_POSTS:
        await update.message.reply_text(
            f"❌ Maksimal {MAX_POSTS} ta.", reply_markup=await menu_for(uid)
        )
        return
    post = {
        "text": text,
        "entities": [entity_to_dict(e) for e in entities_src],
        "link_preview": True,
    }
    posts.append(post)
    await set_posts(uid, posts)
    log(f"📝 Post qo'shildi: {uid} (#{len(posts)})")
    await update.message.reply_text(
        f"✅ Saqlandi (#{len(posts)})\n\n{text[:100]}",
        reply_markup=await menu_for(uid),
    )


async def _handle_set_interval(update: Update, text: str) -> None:
    uid = update.effective_user.id
    try:
        m = int(text.strip())
    except Exception:
        await update.message.reply_text(
            f"❌ Faqat butun son ({MIN_INTERVAL_MIN}–{MAX_INTERVAL_MIN}). Qaytadan kiriting:"
        )
        return
    if m < MIN_INTERVAL_MIN or m > MAX_INTERVAL_MIN:
        await update.message.reply_text(
            f"❌ {MIN_INTERVAL_MIN}–{MAX_INTERVAL_MIN} oralig'ida bo'lishi kerak. Qaytadan:"
        )
        return
    user_states.pop(uid, None)
    await set_interval(uid, m)
    log(f"⏱ Interval: {uid} → {m}")
    await update.message.reply_text(
        f"✅ Interval: {m} daqiqa", reply_markup=await menu_for(uid)
    )


async def _handle_set_schedule(update: Update, text: str) -> None:
    uid = update.effective_user.id
    s = text.strip().replace(" ", "")
    try:
        a, b = s.split("-")
        sh, sm = map(int, a.split(":"))
        eh, em = map(int, b.split(":"))
        if not (0 <= sh < 24 and 0 <= eh < 24 and 0 <= sm < 60 and 0 <= em < 60):
            raise ValueError
        start = dtime(sh, sm)
        end = dtime(eh, em)
    except Exception:
        await update.message.reply_text(
            "❌ Format noto'g'ri. Masalan: 09:00-22:00\nQaytadan kiriting:"
        )
        return
    user_states.pop(uid, None)
    await set_schedule(uid, start, end)
    log(f"🕒 Schedule: {uid} → {start.strftime('%H:%M')}–{end.strftime('%H:%M')}")
    await update.message.reply_text(
        f"✅ Vaqt oynasi: {start.strftime('%H:%M')}–{end.strftime('%H:%M')}",
        reply_markup=await menu_for(uid),
    )


# ─────────────────────────────────────────────────────────────────────────
# RESTART-DAN KEYIN AVTO-TIKLASH
# ─────────────────────────────────────────────────────────────────────────
async def restore_running_workers() -> None:
    running = await jload(RUNNING_FILE, {})
    if not isinstance(running, dict):
        return
    for uid_str, val in running.items():
        if not val:
            continue
        try:
            uid = int(uid_str)
        except Exception:
            continue
        if not await is_approved(uid):
            await del_running(uid)
            continue
        if not await get_session(uid):
            await del_running(uid)
            continue
        chats = await get_chats(uid)
        posts = await get_posts(uid)
        if not chats or not posts:
            continue
        await _start_worker(uid)
        log(f"🔁 Tiklandi: {uid}")


# ─────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log(f"💥 Handler xato: {context.error}", "error")


async def main() -> None:
    global application
    log("🚀 AVTO BOT ishga tushmoqda")

    app = Application.builder().token(BOT_TOKEN).build()
    application = app

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_callback))
    # Foto/video bilan keluvchi caption-li xabarlar ham post sifatida saqlanishi uchun
    # filters.TEXT bilan birga caption-li xabarlarni ham tutamiz.
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND, on_message
        )
    )
    app.add_error_handler(on_error)

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    log("✅ Polling boshlandi")

    await restore_running_workers()

    try:
        # Cheksiz turish
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        log("🛑 To'xtatilmoqda...")
        for uid in list(workers.keys()):
            await _stop_worker(uid, persist=True)
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        log("👋 To'xtatildi")


if __name__ == "__main__":
    asyncio.run(main())
