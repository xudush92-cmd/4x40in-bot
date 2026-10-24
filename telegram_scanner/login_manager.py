"""Bot ichida Telegram akkaunt ulash (QR siz) — AVTOBOT2026 uslubida.

Oqim: telefon -> kod DARHOL so'raladi -> kod raqamli tugmalarda teriladi
-> 2FA (kerak bo'lsa) -> akkaunt UID/bot UID mosligi tekshiriladi ->
sessiya shifrlangan pending holatda saqlanadi -> admin tasdig'i.
"""
import asyncio
import logging
import time
from collections import defaultdict, deque

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberFloodError,
    PhoneNumberInvalidError,
    SendCodeUnavailableError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from config import API_HASH, API_ID

logger = logging.getLogger(__name__)

MAX_CODE_PER_PHONE_PER_HOUR = 3
MAX_WRONG_CODE = 5

_contexts: dict[int, dict] = {}
_phone_requests: dict[str, deque] = defaultdict(deque)


class LoginError(Exception):
    """Foydalanuvchiga ko'rsatiladigan xato matni bilan."""


def _phone_slot(phone: str) -> tuple[bool, int]:
    """Telefon limit: 3 ta/soat. (ruxsat, kutish daqiqasi)."""
    now = time.time()
    q = _phone_requests[phone]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= MAX_CODE_PER_PHONE_PER_HOUR:
        wait = max(1, int((3600 - (now - q[0])) // 60) + 1)
        return False, wait
    q.append(now)
    return True, 0


def _digits(text: str) -> str:
    return "".join(ch for ch in (text or "") if ch.isdigit())


def validate_phone(phone: str) -> str | None:
    """+998XXXXXXXXX bo'lsa tozalangan raqam, bo'lmasa None."""
    p = (phone or "").replace(" ", "").replace("-", "")
    if p.startswith("+998") and len(p) == 13 and _digits(p) == p[1:]:
        return p
    return None


def validate_full_name(name: str) -> bool:
    parts = " ".join((name or "").split()).split()
    return len(parts) >= 2 and all(len(p) >= 2 for p in parts)


async def cleanup(uid: int) -> None:
    ctx = _contexts.pop(uid, None)
    if ctx and ctx.get("client"):
        try:
            await ctx["client"].disconnect()
        except Exception:
            pass


async def request_code(uid: int, phone: str) -> int:
    """Kod so'raydi. Qaytaradi: kod uzunligi. Xatoda LoginError."""
    allowed, wait = _phone_slot(phone)
    if not allowed:
        raise LoginError(
            f"⏳ Bu raqamga kod so'rash limiti tugadi. {wait} daqiqadan keyin urining."
        )
    await cleanup(uid)
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        result = await asyncio.wait_for(client.send_code_request(phone), timeout=30)
    except PhoneNumberInvalidError:
        await _safe_disconnect(client)
        raise LoginError("❌ Telefon raqami noto'g'ri.")
    except PhoneNumberBannedError:
        await _safe_disconnect(client)
        raise LoginError("🚫 Bu raqam Telegram tomonidan bloklangan.")
    except FloodWaitError as e:
        await _safe_disconnect(client)
        raise LoginError(f"⏳ Telegram cheklovi: {max(1, e.seconds // 60)} daqiqa kuting.")
    except (PhoneNumberFloodError, SendCodeUnavailableError):
        await _safe_disconnect(client)
        raise LoginError("❌ Hozir kod yuborib bo'lmadi. Keyinroq urining.")
    except asyncio.TimeoutError:
        await _safe_disconnect(client)
        raise LoginError("❌ Telegramga ulanishda timeout. Qayta urining.")
    except Exception as e:
        await _safe_disconnect(client)
        logger.exception("request_code xato")
        raise LoginError("❌ Xatolik yuz berdi. Qayta urining.")

    phone_code_hash = getattr(result, "phone_code_hash", "") or ""
    if not phone_code_hash and await client.is_user_authorized():
        # Ba'zan Telegram kodsiz tasdiqlaydi
        _contexts[uid] = {"client": client, "phone": phone, "instant": True}
        return 0

    _contexts[uid] = {
        "client": client,
        "phone": phone,
        "phone_code_hash": phone_code_hash,
        "wrong": 0,
        "started": time.time(),
    }
    length = getattr(getattr(result, "type", None), "length", None) or 5
    return int(length)


async def _safe_disconnect(client) -> None:
    try:
        await client.disconnect()
    except Exception:
        pass


async def sign_in_code(uid: int, code: str):
    """(holat, client, me). holat: ok | password | wrong | expired | error."""
    ctx = _contexts.get(uid)
    if not ctx:
        return "error", None, None
    client = ctx["client"]
    if ctx.get("instant"):
        me = await client.get_me()
        return "ok", client, me
    try:
        await client.sign_in(
            phone=ctx["phone"], code=code, phone_code_hash=ctx["phone_code_hash"]
        )
        me = await client.get_me()
        return "ok", client, me
    except SessionPasswordNeededError:
        return "password", None, None
    except PhoneCodeInvalidError:
        ctx["wrong"] = ctx.get("wrong", 0) + 1
        if ctx["wrong"] >= MAX_WRONG_CODE:
            await cleanup(uid)
            return "error", None, None
        return "wrong", None, None
    except PhoneCodeExpiredError:
        return "expired", None, None
    except FloodWaitError as e:
        await cleanup(uid)
        return "error", None, None
    except Exception:
        logger.exception("sign_in xato")
        await cleanup(uid)
        return "error", None, None


async def sign_in_password(uid: int, password: str):
    ctx = _contexts.get(uid)
    if not ctx:
        return "error", None, None
    try:
        await ctx["client"].sign_in(password=password)
        me = await ctx["client"].get_me()
        return "ok", ctx["client"], me
    except Exception:
        logger.exception("2FA xato")
        return "error", None, None


def validate_account(uid: int, me, entered_phone: str) -> str | None:
    """Akkaunt bot foydalanuvchisiga tegishliligi. Xato matni yoki None."""
    if me is None or getattr(me, "id", None) != uid:
        return (
            "❌ Tasdiqlangan Telegram akkaunti sizning bot akkauntingizga mos "
            "emas. Sessiya saqlanmadi — o'z akkauntingiz bilan kiring."
        )
    me_phone = _digits(getattr(me, "phone", "") or "")
    if me_phone and _digits(entered_phone) and me_phone != _digits(entered_phone):
        return "❌ Akkaunt telefoni kiritilgan raqamga mos emas. Sessiya saqlanmadi."
    return None


def take_signed_client(uid: int):
    """Muvaffaqiyatli clientni kontekstdan oladi (chaqiruvchi saqlaydi)."""
    ctx = _contexts.pop(uid, None)
    return ctx["client"] if ctx else None


async def revoke_session(session_str: str) -> None:
    """Sessiyani Telegramda bekor qiladi (rad etish/o'chirishda)."""
    if not session_str:
        return
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        await client.log_out()
    except Exception:
        logger.warning("Sessiyani revoke qilishda xato", exc_info=True)
    finally:
        await _safe_disconnect(client)


async def check_session(session_str: str):
    """Sessiyani tekshiradi: (holat, me). holat: ok|mismatch|invalid|temporary."""
    if not session_str:
        return "invalid", None
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await client.is_user_authorized():
            return "invalid", None
        me = await client.get_me()
        return "ok", me
    except FloodWaitError:
        return "temporary", None
    except asyncio.TimeoutError:
        return "temporary", None
    except Exception:
        logger.warning("Sessiya tekshiruvida xato", exc_info=True)
        return "temporary", None
    finally:
        await _safe_disconnect(client)
