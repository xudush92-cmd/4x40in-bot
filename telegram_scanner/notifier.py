"""Bildirishnoma yuborish va uni bezash (markaziy userbot YO'Q).

Bu modul faqat Telegram Bot API orqali xabar yuboradi va xabar matnini
tayyorlaydi. Skanerlash butunlay ``scanner_manager`` da: har bir
foydalanuvchi o'z sessiyasi bilan ishlaydi va topilgan xabar dastlab
faqat shu guruh egasiga boradi. Egasi ❌ Keraksiz desa, oddiy
bildirishnoma nusxasi ko'rib chiqish uchun adminga ham yuboriladi.

Eski "markaziy userbot" rejimi (bitta akkaunt, barcha oluvchilarga
tarqatish) ataylab olib tashlangan: u foydalanuvchilar ma'lumotini
aralashtirib yuborardi.

Fayl ``userbot.py`` deb nomlanmagan, chunki endi bu userbot emas.
"""
import asyncio
import html
import json
import logging
import re

import aiohttp

from config import ADMIN_ID, BOT_TOKEN

logger = logging.getLogger(__name__)

# --- Ishonchli yetkazish ---
# Bitta doimiy HTTP sessiya (har xabarda yangi TCP/TLS ulanish ochilmaydi).
# Tarmoq xatosi, 5xx yoki 429 bo'lsa qayta urinadi: 429 da Telegram
# aytgan ``retry_after`` kutiladi. Bir vaqtda yuborishlar soni cheklangan —
# qolganlari navbatda kutadi va Bot API limitini oshirib yubormaydi.
_SEND_ATTEMPTS = 6            # 1 + 5 qayta urinish (~31 s gacha)
_MAX_RETRY_AFTER = 60.0
_SEND_CONCURRENCY = 20
_API_TIMEOUT_SECONDS = 15
_session = None
_session_loop = None
_send_slots: asyncio.Semaphore | None = None


def _get_session():
    global _session, _session_loop, _send_slots
    loop = asyncio.get_running_loop()
    if (
        _session is None
        or _session_loop is not loop
        or getattr(_session, "closed", False)
    ):
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=_API_TIMEOUT_SECONDS)
        )
        _session_loop = loop
        _send_slots = asyncio.Semaphore(_SEND_CONCURRENCY)
    return _session


def _retry_after(body: str) -> float:
    """429 javobidagi ``parameters.retry_after`` (sekund)."""
    try:
        value = json.loads(body).get("parameters", {}).get("retry_after")
        return min(_MAX_RETRY_AFTER, max(1.0, float(value)))
    except (ValueError, TypeError, AttributeError):
        return 1.0


async def _post(session, url, payload) -> tuple[int | None, str]:
    """Bitta sendMessage; vaqtinchalik xatolarda qayta urinadi.

    Qaytaradi: (HTTP status yoki tarmoq xatosida None, javob matni).
    """
    status, body = None, ""
    for attempt in range(_SEND_ATTEMPTS):
        try:
            async with session.post(url, json=payload) as resp:
                status, body = resp.status, await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            status, body = None, type(exc).__name__
        if status == 429:
            delay = _retry_after(body)
        elif status is None or status >= 500:
            delay = min(16.0, 2.0 ** attempt)
        else:
            return status, body
        if attempt + 1 >= _SEND_ATTEMPTS:
            break
        logger.warning(
            "[NOTIFY] vaqtinchalik xato (%s), %.0f s dan keyin qayta urinish %s/%s",
            status or body, delay, attempt + 1, _SEND_ATTEMPTS - 1,
        )
        await asyncio.sleep(delay)
    return status, body


def _is_transient(status: int | None) -> bool:
    return status is None or status == 429 or status >= 500

# O'zbekiston telefon raqamini topish uchun regex
PHONE_REGEX = re.compile(
    r"(\+?998|8)?[\s\-]?\(?\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b"
)

def build_feedback_row(review_id: int) -> list[dict]:
    """Bildirishnoma uchun «foydali / keraksiz» tugmalari.

    ``review_id`` — ``database.save_lead_review()`` qaytargan id. Tugma
    bosilganda ovoz faqat statistikaga yoziladi; so'zlar vazni o'zgarmaydi.
    """
    return [
        {"text": "✅ Foydali", "callback_data": f"fb:{review_id}:1"},
        {"text": "❌ Keraksiz", "callback_data": f"fb:{review_id}:0"},
    ]


def _without_id_profile_links(text, reply_markup):
    """ID mention Telegram tomonidan rad etilsa, boshqa tugma/havolalarni saqlash."""
    clean_text = re.sub(r'<a href="tg://user\?id=[0-9]+">(.*?)</a>', r'\1', text, flags=re.DOTALL)
    if clean_text != text:
        clean_text += "\nℹ️ Profil havolasi mavjud emas — guruhdagi asl xabarni oching."
    clean_markup = None
    if reply_markup:
        rows = []
        for row in reply_markup.get("inline_keyboard", []):
            kept = [button for button in row
                    if not str(button.get("url", "")).startswith("tg://user?id=")]
            if kept:
                rows.append(kept)
        if rows:
            clean_markup = {**reply_markup, "inline_keyboard": rows}
    return clean_text, clean_markup


async def send_to_bot_api(text, reply_markup=None, chat_id=None) -> bool:
    """Xabarni boshqaruv boti orqali berilgan chatga yuborish.

    chat_id berilmasa — ADMIN_ID (tizim xabarlari faqat adminga).
    Asosiy yuborish xato bersa (tugma/HTML sababli), bildirishnoma
    yo'qolmasligi uchun oddiy matn bilan qayta yuboriladi. Tarmoq xatosi,
    5xx va 429 da esa o'sha xabar o'zi qayta yuboriladi (``_post``).
    """
    target = chat_id or ADMIN_ID
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": target,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        session = _get_session()
        async with _send_slots:
            status, body = await _post(session, url, payload)
            if status == 200:
                logger.info("[NOTIFY] Yuborildi (chat_id=%s)", target)
                return True
            logger.warning("[NOTIFY] Bot API xatosi (%s): %s", status, body)
            # Qayta urinishlardan keyin ham tarmoq/limit xatosi yoki bot
            # bloklangan (403) bo'lsa, matnni o'zgartirish yordam bermaydi.
            if _is_transient(status) or status == 403:
                logger.error(
                    "[NOTIFY] Yuborilmadi (chat_id=%s, status=%s)", target, status,
                )
                return False
            rejected_status = status
            # Telegram botga noma'lum user ID mention yoki URLni rad etishi
            # mumkin. Aniq 400 da faqat ID havolani olib, boshqa tugma va
            # asl xabar havolasini saqlab qayta yuboramiz.
            safe_text, safe_markup = _without_id_profile_links(text, reply_markup)
            if rejected_status == 400 and (safe_text != text or safe_markup != reply_markup):
                safe_payload = {
                    "chat_id": target, "text": safe_text, "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                }
                if safe_markup:
                    safe_payload["reply_markup"] = safe_markup
                safe_status, _ = await _post(session, url, safe_payload)
                if safe_status == 200:
                    logger.info("[NOTIFY] ID havolasiz zaxira yuborildi")
                    return True
                logger.warning("[NOTIFY] ID havolasiz zaxira xatosi (%s)", safe_status)
            # Avval inline tugmalarsiz, lekin HTML havolalarini saqlab yuboramiz.
            # Reply markupdagi bitta yaroqsiz URL butun klaviaturani yo'qotmasin.
            html_fallback = {
                "chat_id": target,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            status2, body2 = await _post(session, url, html_fallback)
            if status2 == 200:
                logger.info("[NOTIFY] HTML havolali zaxira xabar yuborildi")
                return True
            logger.warning("[NOTIFY] HTML zaxira xatosi (%s): %s", status2, body2)

            # Oxirgi zaxira: HTMLsiz oddiy matn.
            plain = re.sub(r"<[^>]+>", "", text)
            status3, body3 = await _post(
                session, url, {"chat_id": target, "text": plain}
            )
            if status3 == 200:
                logger.info("[NOTIFY] Oddiy matnli zaxira yuborildi")
                return True
            logger.error("[NOTIFY] Zaxira ham yuborilmadi (%s): %s", status3, body3)
    except Exception:
        logger.exception("[NOTIFY] Yuborishda tarmoq xatosi")
    return False


def build_profile_link(username: str | None) -> str | None:
    """Username mavjud bo'lsa, Telegram profilining HTTPS havolasi."""
    value = (username or "").strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", value):
        return None
    return f"https://t.me/{value}"


def build_protected_sender_link(
    username: str | None, user_id: int | str | None = None,
) -> str | None:
    """Protected lead egasi uchun public username yoki Telegram ID havolasi."""
    public_link = build_profile_link(username)
    if public_link:
        return public_link
    try:
        numeric_id = int(user_id)
    except (TypeError, ValueError):
        return None
    if numeric_id <= 0:
        return None
    return f"tg://user?id={numeric_id}"


def build_message_link(chat, chat_id, message_id) -> str | None:
    """Xabarning o'ziga olib boradigan havola.

    Ochiq guruhda (username bo'lsa): https://t.me/username/123
    Superguruhda (username bo'lmasa): https://t.me/c/123456/123
    Oddiy yopiq guruhda Telegram to'g'ridan havola bermaydi -> None.
    """
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"
    raw_id = str(chat_id)
    if raw_id.startswith("-100"):
        return f"https://t.me/c/{raw_id[4:]}/{message_id}"
    return None


# Faqat aniq belgilangan User ID: ... ko'rinishi; oddiy raqam yoki telefon emas.
_TEXT_USER_ID_RE = re.compile(r'(?<!\w)user\s+id\s*:\s*([0-9]{5,15})(?![\w\d])', re.IGNORECASE)


def _text_user_id_matches(raw_text: str):
    return list(_TEXT_USER_ID_RE.finditer(raw_text or ""))


def find_phone_text(raw_text: str, sender=None) -> str:
    """Telefonni xabar matnidan topadi; sender faqat oddiy alertlar uchun."""
    text = raw_text or ""
    id_spans = [match.span(1) for match in _text_user_id_matches(text)]
    for match in PHONE_REGEX.finditer(text):
        if not any(match.start() < end and match.end() > start for start, end in id_spans):
            return match.group(0)
    profile_phone = getattr(sender, "phone", None)
    if profile_phone:
        digits = re.sub(r"\D", "", str(profile_phone))
        if digits:
            return f"+{digits} (Profil raqami)"
    return "Matnda ko'rsatilmagan"


def build_protected_notification_markup(
    message_link: str | None,
    username: str | None = None,
    user_id: int | str | None = None,
):
    """Himoyalangan lead uchun profil/ID va asl xabar havolalari."""
    rows = []
    profile_link = build_protected_sender_link(username, user_id)
    if profile_link:
        rows.append([{
            "text": "👤 Yuboruvchi profilini ochish",
            "url": profile_link,
        }])
    if message_link:
        rows.append([{
            "text": "↗️ Guruhdagi asl xabarni ochish",
            "url": message_link,
        }])
    return {"inline_keyboard": rows} if rows else None


def build_protected_notification_text(
    *,
    group_title: str,
    message_link: str | None,
    protected: bool = True,
    include_details: bool = False,
    sender_name: str | None = None,
    username: str | None = None,
    user_id: int | str | None = None,
    phone: str | None = None,
    matched_words=None,
) -> str:
    """Xom matnsiz, faqat ruxsat etilgan ko'rinadigan ma'lumotli ogohlantirish.

    Himoya holati noma'lum bo'lsa ``include_details`` False qoladi va
    maxfiylik uchun umumiy ogohlantirish yuboriladi. Telefon faqat xabar
    matnida ochiq yozilgan bo'lsa chaqiruvchi tomonidan beriladi.
    """
    esc = html.escape
    include_details = bool(include_details and protected)
    heading = (
        "🔒 <b>HIMOYALANGAN GURUHDA MOS MATN TOPILDI</b>"
        if protected else "🔎 <b>GURUHDA MOS MATN TOPILDI</b>"
    )
    lines = [
        heading,
        "━━━━━━━━━━━━━━━",
        f"📍 <b>Guruh:</b> {esc(group_title or 'Nomaʼlum guruh')}",
        "",
    ]
    if include_details:
        safe_username = (username or "").strip()
        profile_link = build_protected_sender_link(safe_username, user_id)
        lines.append(
            f"👤 <b>Yuboruvchi:</b> {esc(sender_name or 'Nomaʼlum')}"
        )
        if user_id is not None:
            lines.append(f"🆔 <b>Telegram ID:</b> <code>{esc(str(user_id))}</code>")
        if profile_link and build_profile_link(safe_username):
            lines.append(
                f'🔗 <b>Ochiq username:</b> '
                f'<a href="{esc(profile_link, quote=True)}">'
                f"{esc('@' + safe_username.lstrip('@'))}</a>"
            )
        elif profile_link:
            lines.append(
                f'🔗 <a href="{esc(profile_link, quote=True)}">'
                "Yuboruvchi profilini ochish</a>"
            )
        else:
            lines.append("🔗 <b>Username:</b> ochiq emas")
        phone_text = phone or "Matnda ko'rsatilmagan"
        lines.extend(["", f"📞 <b>Telefon:</b> {esc(phone_text)}"])
        words = list(dict.fromkeys(str(word) for word in (matched_words or []) if word))
        lines.extend(["", f"🔑 {esc(', '.join(words)) if words else '—'}"])
        lines.extend(["", "🔒 Xabar matni himoya sabab ko'rsatilmaydi."])
    else:
        lines.append(
            "Xabar matni va yuboruvchi tafsilotlari maxfiylikni saqlash "
            "uchun ko'rsatilmaydi."
        )
    lines.append("")
    if message_link:
        lines.append(
            f'🔗 <a href="{esc(message_link, quote=True)}">'
            "Guruhdagi asl xabarni ochish</a>"
        )
    else:
        lines.append("Guruhni ochib, mos xabarni o'zingiz ko'ring.")
    return "\n".join(lines)


def build_notification_text(
    *,
    group_title: str,
    sender_name: str,
    username: str,
    user_id,
    phone: str,
    raw_text: str,
    matched_words,
    required_count: int,
    message_link: str | None,
    match_mode: str = "count",
    score: float | None = None,
    score_threshold: float | None = None,
    positive_weights: dict | None = None,
    negative_weights: dict | None = None,
    profile_user_id: int | None = None,
) -> str:
    """Bildirishnoma matni — rejimga mos ball/shart bilan.

    ID havolasi faqat chaqiruvchi uni Telegram foydalanuvchisi deb tasdiqlasa ishlatiladi.
    """
    sep = "━━━━━━━━━━━━━━━"
    esc = html.escape

    profile_link = build_protected_sender_link(username, profile_user_id)
    if profile_link:
        safe_profile_link = esc(profile_link, quote=True)
        sender_block = (
            f'👤 <b>Yuboruvchi:</b> '
            f'<a href="{safe_profile_link}">{esc(sender_name)}</a>'
        )
        if build_profile_link(username):
            sender_block += f"\n({esc(username)})"
        profile_line = (
            f'👉 <a href="{safe_profile_link}">'
            "Mijoz profiliga o'tish (Lichkasi)</a>"
        )
    else:
        sender_block = f"👤 <b>Yuboruvchi:</b> {esc(sender_name)}"
        if username and username != "Yo'q":
            sender_block += f"\n({esc(username)})"
        profile_line = "💡 (Profil havolasi yo'q — guruhdagi asl xabarni oching)"

    lines = [
        "🚕 <b>YANGI BUYURTMA / MIJOZ TOPILDI!</b>",
        sep,
        f"📍 <b>Guruh:</b> {esc(group_title or 'Nomaʼlum guruh')}",
        "",
        sender_block,
        f"🆔 <b>Telegram ID:</b> <code>{esc(str(user_id)) if user_id is not None else '—'}</code>",
        "",
        f"📞 <b>Telefon:</b> {esc(phone)}",
        "",
        "💬 <b>Xabar matni:</b>",
        esc(raw_text or ""),
        "",
        f"🔑 {esc(', '.join(matched_words)) if matched_words else '—'}",
    ]
    if match_mode == "weight":
        score_value = float(score or 0.0)
        threshold_value = float(score_threshold or 0.0)
        lines.append(
            f"⚖️ <b>Ball:</b> {score_value:g} / {threshold_value:g} — o'tdi"
        )
        details = []
        for word, weight in (positive_weights or {}).items():
            details.append(f"+{float(weight):g} {esc(str(word))}")
        for word, weight in (negative_weights or {}).items():
            details.append(f"{float(weight):g} {esc(str(word))}")
        if details:
            lines.append("🔎 <b>Mosgan vaznlar:</b> " + ", ".join(details))
    else:
        lines.append(
            f"🔔 <b>Shart:</b> kamida {int(required_count)} ta — bajarildi"
        )
    lines.extend([
        sep,
        profile_line,
    ])
    if message_link:
        lines.append(
            f'🔗 <a href="{esc(message_link, quote=True)}">'
            "Guruhdagi asl xabarni ochish</a>"
        )
    return "\n".join(lines)
