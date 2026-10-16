"""Bot matnlari servisi.

Matnlar `bot_texts` jadvalida saqlanadi va admin panelda tahrirlanadi.
DB'dagi qiymat bo'lmasa — bu yerdagi standart matn ishlatiladi.

Placeholder'lar: {ism}, {kun}, {guruh} kabi. Noma'lum placeholder xato
bermaydi (matnda ko'rinib qoladi) — bot hech qachon "yiqilmaydi".
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from html.parser import HTMLParser
from string import Formatter
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import session_scope
from app.db.models import ActionLog, BotText
from app.redis_client import redis_manager

DEFAULT_LANG = "uz"

# ── Standart matnlar (o'zbekcha) ──────────────────────────────
DEFAULT_TEXTS: dict[str, str] = {
    # Umumiy
    "common.back": "◀️ Orqaga",
    "common.cancel": "❌ Bekor qilish",
    "common.confirm": "✅ Tasdiqlash",
    "common.yes": "✅ Ha",
    "common.no": "❌ Yo'q",
    "common.close": "✖️ Yopish",
    "common.error": (
        "⚠️ Xatolik yuz berdi. Administratorlarga xabar berildi.\n"
        "Iltimos, birozdan so'ng qayta urinib ko'ring."
    ),
    "common.not_admin": "⛔️ Bu amal faqat administratorlar uchun.",
    "common.save": "💾 Saqlash",
    "common.unknown_command": "🤖 Bu buyruqni tanimadim.",
    # /start (foydalanuvchi)
    "start.user": (
        "👋 Assalomu alaykum, <b>{ism}</b>!\n\n"
        "Bu bot — guruhlar uchun onlayn do'kon uslubidagi e'lonlar tizimi.\n\n"
        "📌 Guruhlarda toifa bo'yicha e'lonlarni ko'rishingiz mumkin.\n"
        "📌 Sotuvchi bo'lish uchun pastdagi arizani yuboring; admin ko'rib chiqadi.\n\n"
        "☎️ Yordam: {yordam}"
    ),
    # /start (admin)
    "start.admin": (
        "👋 Assalomu alaykum, <b>{ism}</b>!\n\n"
        "🛠 <b>Boshqaruv paneli</b>ga xush kelibsiz.\n"
        "Kerakli bo'limni tanlang:"
    ),
    # /start (sotuvchi)
    "start.seller": (
        "👋 Assalomu alaykum, <b>{ism}</b>!\n\n"
        "🛒 <b>Sotuvchi paneli</b>:\n"
        "{tarif_holati}\n"
        "Kerakli bo'limni tanlang:"
    ),
    # Guruhga qo'shilganda
    "group.added": (
        "✅ Rahmat! Men <b>{guruh}</b> guruhiga qo'shildim.\n\n"
        "Boshlash uchun administrator panelga kirib:\n"
        "1️⃣ Guruhni tasdiqlasin (admin huquqlari tekshiriladi),\n"
        "2️⃣ Kerakli funksiyalarni (e'lon joylash, posbon, sanoqchi) yoqsin,\n"
        "3️⃣ Toifa biriktirsin.\n\n"
        "⚠️ Bot to'liq ishlashi uchun <b>supergroup</b> bo'lishi va "
        "<b>Privacy Mode o'chirilgan</b> bo'lishi kerak."
    ),
    "group.rights_missing": (
        "⚠️ <b>{guruh}</b> guruhida menga quyidagi huquqlar yetishmayapti: {huquqlar}\n"
        "Iltimos, administrator huquqlarini bering."
    ),
    "group.left": "👋 <b>{guruh}</b> guruhidan chiqdim. E'lon joylash to'xtatildi.",
    # Xatolar / kritik
    "seller.tariff_granted": (
        "🎉 <b>Tarifingiz faollashtirildi!</b>\n\n"
        "💳 Tarif: <b>{tarif}</b>\n"
        "📅 Muddat: <b>{kun} kun</b> ({sana} gacha)\n"
        "📢 E'lon limiti: <b>{elon}</b> ta\n"
        "🖼 Har e'londa rasm: <b>{rasm}</b> tagacha"
    ),
    "seller.subscription_reminder": (
        "⏰ <b>Tarifingiz {kun} kundan keyin tugaydi</b>\n\n"
        "📅 Tugash sanasi: <b>{sana}</b>\n"
        "📢 Qolgan e'lon limiti: <b>{qoldi}</b>\n\n"
        "Uzaytirish uchun admin bilan bog'laning: <b>{yordam}</b>"
    ),
    "seller.subscription_expired": (
        "🔴 <b>Tarifingiz muddati tugadi</b>\n\n"
        "E'lon joylash to'xtatildi. Yangilash uchun admin bilan bog'laning: <b>{yordam}</b>"
    ),
    "seller.blocked": (
        "🚫 <b>Hisobingiz bloklandi</b>\n\nSabab: {sabab}"
    ),
    "seller.unblocked": "✅ Hisobingiz blokdan chiqarildi. Tarif holatini /start orqali ko'rishingiz mumkin.",
    "seller.extended": (
        "✅ Tarifingiz {kun} kunga uzaytirildi.\n📅 Yangi muddat: <b>{sana}</b>"
    ),
    # ── E'lonlar (Phase 3) ──
    "ad.submitted": (
        "🕓 <b>Yangi e'lon tekshiruvga tushdi</b>\n\n"
        "📢 {elon}\n"
        "🗂 Toifa: {toifa}\n"
        "👤 Sotuvchi: {sotuvchi}\n\n"
        "<i>«✅ Moderatsiya» bo'limida ko'rib chiqing.</i>"
    ),
    "ad.approved": (
        "✅ <b>E'loningiz tasdiqlandi!</b>\n\n"
        "📢 {elon}\n\n"
        "E'lon navbatga qo'shildi — navbati kelganda guruhlarga joylanadi."
    ),
    "ad.rejected": (
        "❌ <b>E'loningiz rad etildi</b>\n\n"
        "📢 {elon}\n"
        "📝 Sabab: {sabab}\n\n"
        "<i>E'lonni tahrirlab, qaytadan yuborishingiz mumkin.</i>"
    ),
    "ad.paused": (
        "⏸ <b>E'loningiz to'xtatildi</b>\n\n"
        "📢 {elon}\n\n"
        "<i>Savol bo'lsa admin bilan bog'laning.</i>"
    ),
    "notify.payment_received": "📥 <b>Yangi to'lov cheki</b>\n\nSotuvchi: {sotuvchi}\nTarif: {tarif}\nSumma: {summa}",
    "notify.group_paused": "⏸ <b>{guruh}</b> guruhi to'xtatildi.\nSabab: {sabab}",
    "notify.error": "⚠️ <b>Xatolik</b>\nManba: {manba}\nTafsilot: {xato}",
    "notify.bot_kicked": "🚫 Bot <b>{guruh}</b> guruhidan chiqarildi (yoki huquqi olindi).",
}


_TEXT_VERSION = "shopbot:texts:version"
_TEXT_TTL = 15.0
_ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre"}
_FIELD_RE = re.compile(r"[a-z_]+\Z")


class _SafeHTML(HTMLParser):
    """Telegram qo'llaydigan oddiy HTML; noto'g'ri tag bilan botni yiqitmaslik."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _ALLOWED_TAGS or attrs:
            raise ValueError("Faqat b/i/u/s/code/pre teglariga ruxsat; atributlar mumkin emas.")
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack.pop() != tag:
            raise ValueError("HTML yopilish tegi mos emas.")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        raise ValueError("Yakka HTML teg ishlatmang.")

    def handle_comment(self, data: str) -> None:
        raise ValueError("HTML kommentariy mumkin emas.")

    def handle_decl(self, decl: str) -> None:
        raise ValueError("HTML deklaratsiyasi mumkin emas.")


def validate_template(key: str, value: str) -> str:
    """Faqat mavjud shablonlar, ularning xavfsiz placeholder'lari va HTML'i."""
    if key not in DEFAULT_TEXTS:
        raise ValueError("Bunday bot matni mavjud emas.")
    text = value.strip() if isinstance(value, str) else ""
    if not 1 <= len(text) <= 2800:
        raise ValueError("Matn 1–2800 belgidan iborat bo'lsin.")
    try:
        allowed = {name for _, name, _, _ in Formatter().parse(DEFAULT_TEXTS[key]) if name}
        for _, name, fmt, conversion in Formatter().parse(text):
            if name is not None and (not _FIELD_RE.fullmatch(name) or name not in allowed or fmt or conversion):
                raise ValueError("Faqat shu matnga tegishli oddiy {placeholder} mumkin.")
    except ValueError as exc:
        if "placeholder" in str(exc):
            raise
        raise ValueError("Qavslar yoki placeholder shakli noto'g'ri.") from exc
    html = _SafeHTML()
    html.feed(text)
    html.close()
    if html.stack:
        raise ValueError("HTML teglari yopilmagan.")
    # HTMLParser noto'g'ri '<' belgilarini ham oddiy matn deb olishi mumkin.
    # Telegramda xato bermasligi uchun literal < ni faqat &lt; deb yozing.
    if "<" in re.sub(r"</?(?:" + "|".join(_ALLOWED_TAGS) + r")>", "", text):
        raise ValueError("HTML xatosi: '<' uchun &lt; yozing.")
    if re.search(r"&(?!amp;|lt;|gt;|quot;)", text):
        raise ValueError("HTML xatosi: '&' uchun &amp; yozing.")
    return text


async def update_template(session: AsyncSession, key: str, value: str | None,
                          actor_id: int) -> BotText:
    """Saqlash yoki standartga qaytarish; dastlabki xato shu yerda to'siladi."""
    text = DEFAULT_TEXTS[key] if value is None and key in DEFAULT_TEXTS else validate_template(key, value or "")
    row = (await session.execute(select(BotText).where(
        BotText.key == key, BotText.lang == DEFAULT_LANG,
    ))).scalar_one_or_none()
    previous = row.text if row else DEFAULT_TEXTS[key]
    if row is None:
        row = BotText(key=key, lang=DEFAULT_LANG, text=text, is_custom=value is not None,
                      updated_by=actor_id)
        session.add(row)
    else:
        row.text, row.is_custom, row.updated_by = text, value is not None, actor_id
    await session.flush()
    if previous != text:
        session.add(ActionLog(actor_id=actor_id, action="bot_text_change", entity="bot_text",
                              entity_id=row.id, before={"key": key, "text": previous[:500]},
                              after={"key": key, "text": text[:500]}))
        await session.flush()
    return row


class TextService:
    """Keshlangan matnlar + xavfsiz render."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], str] = {}
        self._loaded = False
        self._last_check = 0.0
        self._version: int | None = None

    async def load(self, session: AsyncSession | None = None) -> None:
        rows: list[BotText]
        if session is not None:
            rows = (await session.execute(select(BotText))).scalars().all()
        else:
            async with session_scope() as own_session:
                rows = (await own_session.execute(select(BotText))).scalars().all()
        self._cache = {(row.key, row.lang): row.text for row in rows}
        self._loaded = True
        self._last_check = time.monotonic()
        self._version = await redis_manager.get_int(_TEXT_VERSION)
        logger.debug("Bot matnlari yuklandi: {} ta yozuv", len(self._cache))

    async def ensure_loaded(self, session: AsyncSession | None = None) -> None:
        if not self._loaded or time.monotonic() - self._last_check >= _TEXT_TTL:
            version = await redis_manager.get_int(_TEXT_VERSION)
            if not self._loaded or version is None or version != self._version:
                await self.load(session)
            else:
                self._last_check = time.monotonic()

    def raw(self, key: str, lang: str = DEFAULT_LANG) -> str:
        """Matnni placeholder'larsiz olish."""
        if (key, lang) in self._cache:
            return self._cache[(key, lang)]
        if key in DEFAULT_TEXTS:
            return DEFAULT_TEXTS[key]
        logger.warning("Bot matni topilmadi: key={} lang={}", key, lang)
        return f"[{key}]"

    async def get(self, key: str, lang: str = DEFAULT_LANG, **kwargs: Any) -> str:
        """Tayyor (render qilingan) matn."""
        await self.ensure_loaded()
        return safe_format(self.raw(key, lang), **kwargs)

    async def all_defaults(self) -> dict[str, str]:
        return dict(DEFAULT_TEXTS)

    def invalidate(self) -> None:
        self._loaded = False
        self._cache.clear()
        self._last_check = 0.0

    async def publish(self) -> None:
        """Faqat DB commitidan KEYIN: boshqa processlarning keshini yangilatadi."""
        self.invalidate()
        await redis_manager.incr(_TEXT_VERSION)


def safe_format(template: str, **kwargs: Any) -> str:
    """`str.format` ning xatoga chidamli varianti.

    Noma'lum placeholder uchun xato bermaydi — matnda `{nom}` ko'rinishida
    qoladi (xatoni topish oson) va logga ogohlantirish yoziladi.
    """
    if not template or "{" not in template:
        return template

    prepared = {k: ("" if v is None else str(v)) for k, v in kwargs.items()}

    missing: list[str] = []

    class _KeepMissing(defaultdict):  # noma'lum kalitni {kalit} ko'rinishida qoldiradi
        def __init__(self, initial: dict[str, str]) -> None:
            super().__init__(str)
            self.update(initial)

        def __missing__(self, key: str) -> str:
            missing.append(key)
            return "{" + key + "}"

    mapping = _KeepMissing(prepared)

    try:
        result = template.format_map(_KeepMissing(mapping))
    except (IndexError, ValueError) as exc:  # buzuq shablon
        logger.warning("Matn shabloni buzuq ({}): {}", exc, template[:80])
        return template

    if missing:
        logger.warning("Matnda noma'lum placeholder(lar): {}", ", ".join(sorted(set(missing))))
    return result


# Global nusxa
text_service = TextService()
