"""
core/notifier.py — bildirishnoma va ogohlantirish tizimi.

MAQSAD:
───────
Foydalanuvchilarga muhim hodisalar haqida xabar berish:
- ✅ "Sizning eʼloningiz tasdiqlandi"
- ⚠️ "Sizga ogohlantirish berildi (sabab: ...)"
- 🚫 "Sizning hisobingiz bloklandi"
- 💰 "Toʻlov muddatingiz tugayapti (3 kun qoldi)"
- 🔔 "Yangi eʼlon kelib tushdi" (kuzatuvchilarga)

PRINSIPLAR:
───────────
1. ASYNCHRONOUS: bildirishnoma yuborish — alohida task. Asosiy
   handler kutib turmaydi (fire-and-forget).

2. PERSISTENT: bildirishnoma DB'da yoziladi (notifications jadval).
   Telegram yuborish muvaffaqiyatsiz boʻlsa — keyinchalik qayta urinish
   mumkin (notifier service tomonidan).

3. PRIORITET: ogohlantirish va bloklash xabarlari — birinchi.
   Reklama xarakteridagi notification — keyin.

4. TEMPLATES: hamma xabar bir xil shablon va emoji bilan keladi
   (foydalanuvchi tezda taniydi).

DARAJALAR:
──────────
- info     — odatiy bilim
- success  — muvaffaqiyat
- warning  — diqqat
- error    — xato
- critical — favqulodda (block, sessiya yoʻq va h.k.)
"""

from __future__ import annotations

import logging
from typing import Any

from core import database as db

logger = logging.getLogger("enginebot.notifier")


# ─────────────────────────────────────────────────────────────────────
# Notification turi (UI ko'rinishi uchun)
# ─────────────────────────────────────────────────────────────────────
class NotifyType:
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


_TYPE_EMOJI: dict[str, str] = {
    NotifyType.INFO: "ℹ️",
    NotifyType.SUCCESS: "✅",
    NotifyType.WARNING: "⚠️",
    NotifyType.ERROR: "❌",
    NotifyType.CRITICAL: "🚨",
}


# ─────────────────────────────────────────────────────────────────────
# Asosiy funksiya — yangi bildirishnoma yaratish
# ─────────────────────────────────────────────────────────────────────
async def notify(
    user_id: int,
    message: str,
    *,
    title: str = "",
    type_: str = NotifyType.INFO,
    tenant_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    """
    Yangi bildirishnoma yaratish (DB'ga yozadi).

    Telegram'ga yuborish — alohida service (notifier_service.py)
    tomonidan qabul qilinadi va yuboriladi.

    Returns: notification ID
    """
    if not title:
        title = _default_title(type_)

    nid = await db.add_notification(
        user_id=user_id,
        message=message,
        title=title,
        type_=type_,
        tenant_id=tenant_id,
        payload=payload or {},
    )
    logger.info(
        f"notification queued: id={nid} user={user_id} type={type_} "
        f"tenant={tenant_id} title={title!r}"
    )
    return nid


# ─────────────────────────────────────────────────────────────────────
# Tezkor yordamchilar (turlar boʻyicha)
# ─────────────────────────────────────────────────────────────────────
async def notify_info(user_id: int, message: str, *, tenant_id: int | None = None, **kw) -> int:
    return await notify(user_id, message, type_=NotifyType.INFO, tenant_id=tenant_id, **kw)


async def notify_success(user_id: int, message: str, *, tenant_id: int | None = None, **kw) -> int:
    return await notify(user_id, message, type_=NotifyType.SUCCESS, tenant_id=tenant_id, **kw)


async def notify_warning(user_id: int, message: str, *, tenant_id: int | None = None, **kw) -> int:
    return await notify(user_id, message, type_=NotifyType.WARNING, tenant_id=tenant_id, **kw)


async def notify_error(user_id: int, message: str, *, tenant_id: int | None = None, **kw) -> int:
    return await notify(user_id, message, type_=NotifyType.ERROR, tenant_id=tenant_id, **kw)


async def notify_critical(user_id: int, message: str, *, tenant_id: int | None = None, **kw) -> int:
    return await notify(user_id, message, type_=NotifyType.CRITICAL, tenant_id=tenant_id, **kw)


# ─────────────────────────────────────────────────────────────────────
# Standart shablonlar (eng tez-tez ishlatiladigan)
# ─────────────────────────────────────────────────────────────────────
async def notify_user_approved(user_id: int, tenant_id: int, tenant_name: str = "") -> int:
    """User'ga tasdiqlanganini bildirish.

    tenant_name berilmagan bo'lsa, DB'dan avtomatik olamiz.
    """
    if not tenant_name:
        from core import database as _db
        tenant = await _db.get_tenant(tenant_id)
        if tenant:
            tenant_name = tenant.get("name", "") or ""

    return await notify_success(
        user_id=user_id,
        tenant_id=tenant_id,
        title="Hisobingiz tasdiqlandi",
        message=(
            f"✅ Sizning hisobingiz tasdiqlandi"
            + (f" ({tenant_name} tomonidan)" if tenant_name else "")
            + ".\n\nEndi eʼlon yozishingiz mumkin."
        ),
    )


async def notify_user_blocked(
    user_id: int, tenant_id: int, reason: str = ""
) -> int:
    return await notify_critical(
        user_id=user_id,
        tenant_id=tenant_id,
        title="Hisobingiz bloklandi",
        message=(
            f"🚫 Sizning hisobingiz bloklandi.\n\n"
            f"Sabab: {reason or 'sabab koʻrsatilmagan'}\n\n"
            "Bahslashish uchun guruh egasiga murojaat qiling."
        ),
    )


async def notify_user_warned(
    user_id: int,
    tenant_id: int,
    reason: str,
    warnings_count: int,
    max_warnings: int,
) -> int:
    return await notify_warning(
        user_id=user_id,
        tenant_id=tenant_id,
        title="Ogohlantirish",
        message=(
            f"⚠️ Sizga ogohlantirish berildi.\n\n"
            f"📌 Sabab: {reason}\n"
            f"📊 Holat: {warnings_count}/{max_warnings} ogohlantirish\n\n"
            "Diqqatli boʻling — yana ogohlantirish olsangiz "
            "hisobingiz avtomatik bloklanishi mumkin."
        ),
    )


async def notify_post_published(user_id: int, tenant_id: int, post_id: int) -> int:
    return await notify_success(
        user_id=user_id,
        tenant_id=tenant_id,
        title="Eʼloningiz joylashdi",
        message=(
            f"✅ Sizning eʼloningiz kanalga muvaffaqiyatli joylashdi.\n\n"
            f"📋 Eʼlon ID: #{post_id}\n\n"
            "Eʼlonni 'Mening eʼlonlarim' boʻlimida boshqarishingiz mumkin."
        ),
        payload={"post_id": post_id},
    )


async def notify_post_expired(user_id: int, tenant_id: int, post_id: int) -> int:
    return await notify_info(
        user_id=user_id,
        tenant_id=tenant_id,
        title="Eʼlon vaqti tugadi",
        message=(
            f"ℹ️ Sizning eʼloningiz vaqti tugadi va kanaldan oʻchirildi.\n\n"
            f"📋 Eʼlon ID: #{post_id}\n\n"
            "Yangi eʼlon yozishingiz mumkin."
        ),
        payload={"post_id": post_id},
    )


async def notify_tenant_payment_reminder(
    tenant_id: int, days_left: int, paid_until: str
) -> int:
    """Tenant'ga muddati yaqinlashayotganini eslatish (PULSIZ model).

    IDEMPOTENT: bir kunda bir martadan ko'p yuborilmaydi (DB tekshirish).
    """
    # Idempotency: bugun shu tenantga "muddat yaqin" yuborilganmi?
    from core.database import _conn
    async with _conn() as conn:
        cur = await conn.execute(
            """SELECT id FROM notifications
               WHERE user_id = ? AND tenant_id = ?
                 AND title LIKE 'Muddat yaqin%'
                 AND date(created_at) = date('now')
               LIMIT 1""",
            (tenant_id, tenant_id),
        )
        row = await cur.fetchone()
        await cur.close()
    if row is not None:
        logger.debug(
            f"payment_reminder skipped (already sent today): tenant={tenant_id}"
        )
        return int(row[0])

    return await notify_warning(
        user_id=tenant_id,
        tenant_id=tenant_id,
        title="Muddat yaqin",
        message=(
            f"⚠️ Sizning tarif muddatingiz {days_left} kundan keyin tugaydi.\n\n"
            f"📅 Tugash sanasi: {paid_until}\n\n"
            "Muddat tugagach bot vaqtincha to'xtaydi.\n"
            "Iltimos, kanal egasi (super admin) bilan bog'lanib muddatni uzaytiring."
        ),
    )


async def notify_tenant_paused(tenant_id: int, reason: str = "Muddat tugadi") -> int:
    return await notify_critical(
        user_id=tenant_id,
        tenant_id=tenant_id,
        title="Bot vaqtincha toʻxtatildi",
        message=(
            f"🚨 Sizning bot xizmatingiz vaqtincha toʻxtatildi.\n\n"
            f"📌 Sabab: {reason}\n\n"
            "Mavjud eʼlonlar saqlandi, lekin yangilari qabul qilinmaydi.\n"
            "Iltimos, super admin bilan bog'lanib muddatni uzaytiring."
        ),
    )


async def notify_tenant_approved(tenant_id: int, tariff: str, paid_until: str) -> int:
    return await notify_success(
        user_id=tenant_id,
        tenant_id=tenant_id,
        title="Hisobingiz aktivlashdi",
        message=(
            f"✅ Sizning hisobingiz aktivlashdi!\n\n"
            f"📦 Tarif: {tariff.upper()}\n"
            f"📅 Amal qilish muddati: {paid_until}\n\n"
            "Endi botdan foydalana olasiz. /start bosing va kanalingizni ulang."
        ),
    )


# ─────────────────────────────────────────────────────────────────────
# Bulk notification — koʻplab foydalanuvchilarga
# ─────────────────────────────────────────────────────────────────────
async def notify_bulk(
    user_ids: list[int],
    message: str,
    *,
    title: str = "",
    type_: str = NotifyType.INFO,
    tenant_id: int | None = None,
) -> int:
    """
    Bir nechta foydalanuvchiga bir xil xabar yuborish.

    Returns: yaratilgan notification soni.
    """
    count = 0
    for uid in user_ids:
        try:
            await notify(uid, message, title=title, type_=type_, tenant_id=tenant_id)
            count += 1
        except Exception as e:
            logger.error(f"bulk notify failed for {uid}: {type(e).__name__}: {e}")
    logger.info(f"bulk notify: {count}/{len(user_ids)} queued")
    return count


# ─────────────────────────────────────────────────────────────────────
# Yordamchi
# ─────────────────────────────────────────────────────────────────────
def _default_title(type_: str) -> str:
    """Type'ga qarab default sarlavha."""
    return {
        NotifyType.INFO: "Bilim",
        NotifyType.SUCCESS: "Muvaffaqiyat",
        NotifyType.WARNING: "Ogohlantirish",
        NotifyType.ERROR: "Xato",
        NotifyType.CRITICAL: "Diqqat",
    }.get(type_, "Bildirishnoma")


def render_notification(notif: dict) -> str:
    """
    DB'dagi notification yozuvini Telegram uchun matnga aylantirish.

    Format:
        ℹ️ Sarlavha
        ━━━━━━━━━━━━
        Xabar matni
    """
    emoji = _TYPE_EMOJI.get(notif.get("type", NotifyType.INFO), "ℹ️")
    title = notif.get("title", "")
    message = notif.get("message", "")
    if title:
        return f"{emoji} <b>{title}</b>\n━━━━━━━━━━━━━━━━━━\n{message}"
    return f"{emoji} {message}"



# ─────────────────────────────────────────────────────────────────────
# V1.1 yangi bildirishnomalar
# ─────────────────────────────────────────────────────────────────────
async def notify_post_action(
    user_id: int,
    tenant_id: int,
    post_id: int,
    action: str,
    reason: str = "",
) -> int:
    """
    Poster'ga e'loni ustida amal bajarilgani haqida xabar.

    action: "paused", "deleted", "resumed"
    """
    action_labels = {
        "paused": "⏸ pauzaga olindi",
        "deleted": "🗑 o'chirildi",
        "resumed": "▶️ davom ettirildi",
    }
    label = action_labels.get(action, action)
    msg = (
        f"📋 Sizning eʼloningiz #{post_id} {label}.\n"
    )
    if reason:
        msg += f"\n📌 Sabab: {reason}"

    return await notify_warning(
        user_id=user_id,
        tenant_id=tenant_id,
        title=f"E'lon {label}",
        message=msg,
        payload={"post_id": post_id, "action": action},
    )


async def notify_tenant_poster_warnings(
    tenant_id: int,
    poster_id: int,
    poster_name: str,
    warnings_count: int,
) -> int:
    """
    Tenant'ga xabar: poster ko'p ogohlantirish oldi (kuzatuv uchun).

    Bu — tenant'ga keladi, poster'ga emas.
    """
    return await notify_info(
        user_id=tenant_id,
        tenant_id=tenant_id,
        title="Poster ko'p ogohlantirish oldi",
        message=(
            f"⚠️ <b>{poster_name}</b> (#{poster_id}) — "
            f"{warnings_count} ogohlantirish oldi.\n\n"
            "Iltimos, foydalanuvchilar bo'limida tekshiring.\n"
            "3 ogohlantirish = avtomatik blok."
        ),
        payload={"poster_id": poster_id, "warnings_count": warnings_count},
    )


async def notify_new_user_registered(
    tenant_id: int,
    user_id: int,
    user_name: str,
    user_role: str,
) -> int:
    """
    Tenant'ga yangi foydalanuvchi ro'yxatdan o'tgani haqida xabar.

    Auto-approve'da ham keladi — monitoring uchun.
    """
    role_emoji = {"poster": "📝", "customer": "🔍", "both": "🔄"}.get(user_role, "👤")
    return await notify_info(
        user_id=tenant_id,
        tenant_id=tenant_id,
        title="Yangi foydalanuvchi",
        message=(
            f"🔔 Yangi foydalanuvchi ro'yxatdan o'tdi:\n\n"
            f"{role_emoji} <b>{user_name}</b> (#{user_id})\n"
            f"📌 Rol: {user_role}"
        ),
        payload={"new_user_id": user_id, "user_role": user_role},
    )
