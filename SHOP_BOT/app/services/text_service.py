"""Bot matnlari servisi.

Matnlar `bot_texts` jadvalida saqlanadi va admin panelda tahrirlanadi.
DB'dagi qiymat bo'lmasa — bu yerdagi standart matn ishlatiladi.

Placeholder'lar: {ism}, {kun}, {guruh} kabi. Noma'lum placeholder xato
bermaydi (matnda ko'rinib qoladi) — bot hech qachon "yiqilmaydi".
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import session_scope
from app.db.models import BotText

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
        "📌 Sotuvchi bo'lish uchun administrator bilan bog'laning.\n\n"
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
    "notify.payment_received": "📥 <b>Yangi to'lov cheki</b>\n\nSotuvchi: {sotuvchi}\nTarif: {tarif}\nSumma: {summa}",
    "notify.group_paused": "⏸ <b>{guruh}</b> guruhi to'xtatildi.\nSabab: {sabab}",
    "notify.error": "⚠️ <b>Xatolik</b>\nManba: {manba}\nTafsilot: {xato}",
    "notify.bot_kicked": "🚫 Bot <b>{guruh}</b> guruhidan chiqarildi (yoki huquqi olindi).",
}


class TextService:
    """Keshlangan matnlar + xavfsiz render."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], str] = {}
        self._loaded = False

    async def load(self, session: AsyncSession | None = None) -> None:
        rows: list[BotText]
        if session is not None:
            rows = (await session.execute(select(BotText))).scalars().all()
        else:
            async with session_scope() as own_session:
                rows = (await own_session.execute(select(BotText))).scalars().all()
        self._cache = {(row.key, row.lang): row.text for row in rows}
        self._loaded = True
        logger.debug("Bot matnlari yuklandi: {} ta yozuv", len(self._cache))

    async def ensure_loaded(self, session: AsyncSession | None = None) -> None:
        if not self._loaded:
            await self.load(session)

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
