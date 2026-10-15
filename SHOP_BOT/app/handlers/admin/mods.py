"""✅ Moderatsiya va 📢 E'lonlar bo'limi (admin) — Phase 3.

Imkoniyatlar:
  * 🕓 Tekshiruv kutayotgan e'lonlar navbati (rasmlari bilan)
  * ✅ Tasdiqlash — e'lon navbatga tushadi va sotuvchiga xabar boradi
  * ❌ Rad etish — sabab tanlanadi yoki qo'lda yoziladi, limit qaytariladi
  * 📢 Barcha e'lonlar — holat bo'yicha filtr, pauza/yoqish, o'chirish
  * 🕘 Moderatsiya tarixi — kim, qachon, nima qildi

Rasmlar `sendMediaGroup` (albom) bilan ko'rsatiladi — Telegram albomda
inline tugmaga ruxsat bermaydi, shuning uchun tugmalar alohida xabarda.
"""

from __future__ import annotations

from math import ceil

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole, AdStatus
from app.db.models import Ad, Seller
from app.filters import IsAdmin
from app.keyboards.callbacks import ModCB
from app.keyboards.common import PER_PAGE_ADS
from app.keyboards.mods import (
    REJECT_REASONS,
    ad_delete_confirm_kb,
    admin_ad_card_kb,
    admin_ads_list_kb,
    cancel_kb,
    moderation_card_kb,
    pending_list_kb,
    reject_reasons_kb,
    seller_label_kb,
)
from app.services import ad_service, seller_service
from app.services.text_service import text_service
from app.states import AdminModerationStates
from app.utils.text import escape_html, truncate
from app.utils.time import fmt_date, human_delta
from app.utils.tg import alert, render

router = Router(name="admin:moderation")
router.message.filter(IsAdmin(AdminRole.MODERATOR), StateFilter(AdminModerationStates))
router.callback_query.filter(ModCB.filter(), IsAdmin(AdminRole.MODERATOR))

MODERATION_ALBUM_LIMIT = 10


# ═══════════════════════════ Yordamchilar ═════════════════════════
def _parse_page_status(value: str | None, default_status: str = "all") -> tuple[int, str]:
    page, status = 0, default_status
    if value and "|" in value:
        raw_page, raw_status = value.split("|", 1)
        try:
            page = max(0, int(raw_page))
        except ValueError:
            page = 0
        if raw_status:
            status = raw_status
    return page, status


async def _seller_of(session: AsyncSession, ad: Ad) -> Seller | None:
    return await seller_service.get_seller_by_id(session, ad.seller_id)


async def _load_ad(callback: CallbackQuery, session: AsyncSession, ad_id: int) -> Ad | None:
    ad = await ad_service.get_ad(session, ad_id)
    if ad is None:
        await alert(callback, "⚠️ E'lon topilmadi.", show=True)
    return ad


async def _notify_seller(bot: Bot, seller: Seller | None, text: str) -> None:
    """Sotuvchiga shaxsiy xabar (bloklagan bo'lsa jim o'tiladi)."""
    if seller is None:
        return
    try:
        await bot.send_message(seller.user_id, text, disable_web_page_preview=True)
    except TelegramAPIError as exc:
        logger.debug("Sotuvchi {} ga xabar yuborilmadi: {}", seller.user_id, exc)


async def _send_ad_photos(message: Message, ad: Ad, caption: str) -> None:
    """Rasmlarni albom qilib ko'rsatish; tugmalar alohida xabarda chiqadi."""
    photos = [photo.file_id for photo in ad.photos][:MODERATION_ALBUM_LIMIT]
    if not photos:
        return
    try:
        if len(photos) == 1:
            await message.answer_photo(photos[0], caption=caption[:1024])
        else:
            media = [InputMediaPhoto(media=photos[0], caption=caption[:1024])]
            media += [InputMediaPhoto(media=file_id) for file_id in photos[1:]]
            await message.answer_media_group(media)
    except TelegramAPIError as exc:  # pragma: no cover — rasm eskirgan bo'lishi mumkin
        logger.warning("Rasmlarni ko'rsatib bo'lmadi (ad={}): {}", ad.id, exc)


async def _ad_card_text(session: AsyncSession, ad: Ad, *, for_moderation: bool) -> str:
    category = await ad_service.category_of(session, ad)
    seller = await _seller_of(session, ad)
    photos = await ad_service.photo_count(session, ad.id)
    stats = await ad_service.ad_stats(session, ad)

    lines = [
        f"{ad_service.status_badge(ad.status)} <b>#{ad.id} "
        f"{escape_html(truncate(ad.title or '(nomsiz)', 55))}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"👤 Sotuvchi: <b>{escape_html(seller_label_kb(seller) if seller else '—')}</b>"
        + (f"  <code>{seller.user_id}</code>" if seller else ""),
        f"🗂 Toifa: <b>{escape_html(category.name if category else '—')}</b>",
        f"💰 Narx: <b>{ad_service.format_ad_price(ad)}</b>",
        f"☎️ Aloqa: <code>{escape_html(ad.contact_value or '—')}</code> ({ad.contact_type})",
        f"🖼 Rasmlar: <b>{photos}</b> ta",
        f"📌 Holat: <b>{ad_service.status_title(ad.status)}</b>",
        f"👁 Joylangan: <b>{stats['post_count']}</b> marta",
    ]
    if ad.submitted_at:
        lines.append(f"🕘 Yuborilgan: {fmt_date(ad.submitted_at)} ({human_delta(ad.submitted_at)})")
    if ad.description:
        lines.append(f"\n📝 {escape_html(truncate(ad.description, 400))}")
    if ad.reject_reason:
        lines.append(f"\n❌ Rad etish sababi: {escape_html(ad.reject_reason)}")
    if for_moderation:
        lines.append("\n<i>Tasdiqlasangiz e'lon navbatga qo'shiladi.</i>")
    return "\n".join(lines)


# ═══════════════════ Moderatsiya navbati ══════════════════════════
async def render_pending(
    target: CallbackQuery | Message, session: AsyncSession, page: int = 0
) -> None:
    """🕓 Tekshiruv kutayotgan e'lonlar ro'yxati."""
    total = await ad_service.count_pending(session)
    total_pages = max(1, ceil(total / PER_PAGE_ADS))
    page = max(0, min(page, total_pages - 1))
    ads = await ad_service.pending_ads(session, limit=PER_PAGE_ADS, offset=page * PER_PAGE_ADS)
    all_stats = await ad_service.count_by_status(session)

    lines = [
        "✅ <b>Moderatsiya</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🕓 Kutilmoqda: <b>{total}</b>",
        f"🟢 Faol: <b>{all_stats.get(AdStatus.ACTIVE, 0)}</b>  ·  "
        f"⏸ To'xtatilgan: <b>{all_stats.get(AdStatus.PAUSED, 0)}</b>  ·  "
        f"❌ Rad etilgan: <b>{all_stats.get(AdStatus.REJECTED, 0)}</b>",
        "",
    ]
    if not ads:
        lines.append("🎉 <b>Navbat bo'sh</b> — barcha e'lonlar ko'rib chiqilgan.")
    else:
        for ad in ads:
            category = ad.category
            lines.append(
                f"🕓 <b>#{ad.id}</b> {escape_html(truncate(ad.title or '(nomsiz)', 45))}\n"
                f"   └ 🗂 {escape_html(category.name if category else '—')}  ·  "
                f"{ad_service.format_ad_price(ad)}  ·  🖼 {len(ad.photos)} ta"
            )
        if total_pages > 1:
            lines.append(f"\n<i>Sahifa {page + 1}/{total_pages}</i>")

    await render(target, "\n".join(lines), pending_list_kb(ads, page=page, total_pages=total_pages))


@router.callback_query(ModCB.filter(F.action == "list"))
async def on_pending(
    callback: CallbackQuery, callback_data: ModCB, session: AsyncSession
) -> None:
    page, _ = _parse_page_status(callback_data.value, "pending")
    await render_pending(callback, session, page)
    await alert(callback, "")


@router.callback_query(ModCB.filter(F.action == "card"))
async def on_moderation_card(
    callback: CallbackQuery, callback_data: ModCB, session: AsyncSession, state: FSMContext
) -> None:
    """🕓 Bitta e'lonni ko'rib chiqish (rasmlari bilan)."""
    ad = await _load_ad(callback, session, callback_data.ad_id)
    if ad is None:
        return

    await state.clear()
    page, _ = _parse_page_status(callback_data.value, "pending")
    text = await _ad_card_text(session, ad, for_moderation=True)

    message = callback.message
    if message is not None and ad.photos:
        await _send_ad_photos(message, ad, truncate(text, 1024))

    await render(callback, text, moderation_card_kb(ad, page=page))
    await alert(callback, "")


@router.callback_query(ModCB.filter(F.action == "approve"))
async def on_approve(
    callback: CallbackQuery, callback_data: ModCB, session: AsyncSession, bot: Bot, state: FSMContext
) -> None:
    """✅ Tasdiqlash."""
    ad = await _load_ad(callback, session, callback_data.ad_id)
    if ad is None:
        return

    seller = await _seller_of(session, ad)
    if not await ad_service.approve(session, ad, callback.from_user.id):
        await alert(callback, "⚠️ Bu e'lon tasdiqlash holatida emas.", show=True)
        return

    if seller is not None:
        text = await text_service.get(
            "ad.approved",
            elon=escape_html(truncate(ad.title or "", 60)),
        )
        await _notify_seller(bot, seller, text)

    page, _ = _parse_page_status(callback_data.value, "pending")
    await state.clear()
    await render_pending(callback, session, page)
    await alert(callback, "✅ Tasdiqlandi")


@router.callback_query(ModCB.filter(F.action == "reject"))
async def on_reject(
    callback: CallbackQuery, callback_data: ModCB, session: AsyncSession, state: FSMContext
) -> None:
    """❌ Rad etish — sabab tanlash ekrani."""
    ad = await _load_ad(callback, session, callback_data.ad_id)
    if ad is None:
        return

    page, _ = _parse_page_status(callback_data.value, "pending")
    await state.clear()
    await state.update_data(ad_id=ad.id, page=page)
    await state.set_state(AdminModerationStates.choosing_reason)

    await render(
        callback,
        f"❌ <b>Rad etish sababi</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 {escape_html(truncate(ad.title or '(nomsiz)', 50))}\n\n"
        "Sabab sotuvchiga yuboriladi — u e'lonni tahrirlab qayta yuborishi mumkin.",
        reject_reasons_kb(ad, page=page),
    )
    await alert(callback, "")


@router.callback_query(ModCB.filter(F.action == "reason"))
async def on_reason(
    callback: CallbackQuery, callback_data: ModCB, session: AsyncSession, bot: Bot, state: FSMContext
) -> None:
    """Tayyor sabab tanlandi (yoki qo'lda yozish)."""
    ad = await _load_ad(callback, session, callback_data.ad_id)
    if ad is None:
        return

    raw = callback_data.value or "other|0"
    key, _, raw_page = raw.partition("|")
    try:
        page = max(0, int(raw_page or 0))
    except ValueError:
        page = 0

    if key == "other":
        await state.update_data(ad_id=ad.id, page=page)
        await state.set_state(AdminModerationStates.waiting_reason)
        await render(
            callback,
            "✍️ <b>Sababni yozing</b>\nSotuvchi shu matnni ko'radi (5–300 belgi).",
            cancel_kb(ad.id, action="card", value=f"{page}|pending"),
        )
        await alert(callback, "")
        return

    reason = dict(REJECT_REASONS).get(key, "Sabab ko'rsatilmagan")
    await _do_reject(callback, session, bot, ad, reason, page, state)
    await alert(callback, "❌ Rad etildi")


@router.message(StateFilter(AdminModerationStates.waiting_reason), F.text)
async def on_custom_reason(
    message: Message, session: AsyncSession, bot: Bot, state: FSMContext
) -> None:
    """Qo'lda yozilgan sabab."""
    text = (message.text or "").strip()
    data = await state.get_data()
    ad_id = int(data.get("ad_id") or 0)
    page = int(data.get("page") or 0)

    if text in ("/cancel", "/bekor"):
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=cancel_kb(0, action="list", value="0|pending"))
        return

    if len(text) < 3:
        await message.answer("⚠️ Sabab juda qisqa. Kamida 3 belgi yozing.")
        return

    ad = await ad_service.get_ad(session, ad_id)
    if ad is None:
        await state.clear()
        await message.answer("⚠️ E'lon topilmadi.")
        return

    await _do_reject(None, session, bot, ad, text[:300], page, state, message=message)


async def _do_reject(
    callback: CallbackQuery | None,
    session: AsyncSession,
    bot: Bot,
    ad: Ad,
    reason: str,
    page: int,
    state: FSMContext,
    *,
    message: Message | None = None,
) -> None:
    """Rad etishni bajarish + sotuvchiga xabar + ro'yxatga qaytish."""
    seller = await _seller_of(session, ad)
    if seller is None:
        # Sotuvchi topilmasa ham e'lon holatini yopamiz (limit qaytarilmaydi)
        await state.clear()
        if callback is not None:
            await alert(callback, "⚠️ Sotuvchi topilmadi.", show=True)
        elif message is not None:
            await message.answer("⚠️ Sotuvchi topilmadi.")
        return

    admin_id = callback.from_user.id if callback is not None else (
        message.from_user.id if message is not None and message.from_user else None
    )

    if not await ad_service.reject(session, seller, ad, admin_id, reason):
        await state.clear()
        if callback is not None:
            await alert(callback, "⚠️ Bu e'lon rad etish holatida emas.", show=True)
        elif message is not None:
            await message.answer("⚠️ Bu e'lon rad etish holatida emas.")
        return

    text = await text_service.get(
        "ad.rejected",
        elon=escape_html(truncate(ad.title or "", 60)),
        sabab=escape_html(reason),
    )
    await _notify_seller(bot, seller, text)

    await state.clear()
    if callback is not None:
        await render_pending(callback, session, page)
    elif message is not None:
        await message.answer(
            "❌ Rad etildi va sotuvchiga xabar yuborildi.",
            reply_markup=cancel_kb(0, action="list", value="0|pending"),
        )


# ═════════════════════ 📢 Barcha e'lonlar (admin) ══════════════════
async def render_ads(
    target: CallbackQuery | Message,
    session: AsyncSession,
    page: int = 0,
    status: str = "all",
) -> None:
    """📢 Barcha e'lonlar ro'yxati (holat filtri bilan)."""
    total = await ad_service.count_ads(session, status=status, admin=True)
    total_pages = max(1, ceil(total / PER_PAGE_ADS))
    page = max(0, min(page, total_pages - 1))
    ads = await ad_service.list_ads(
        session, status=status, limit=PER_PAGE_ADS, offset=page * PER_PAGE_ADS, admin=True
    )
    stats = await ad_service.count_by_status(session)

    lines = [
        "📢 <b>E'lonlar</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Jami: <b>{stats.get('all', 0)}</b>  ·  🟢 Faol: <b>{stats.get(AdStatus.ACTIVE, 0)}</b>  ·  "
        f"🕓 Tekshiruvda: <b>{stats.get(AdStatus.PENDING, 0)}</b>",
        f"🔎 Filtr: <b>{ad_service.filter_label(status, admin=True)}</b>  ·  "
        f"ko'rsatilgan: <b>{total}</b>",
        "",
    ]
    if not ads:
        lines.append("📭 Bu filtrda e'lon yo'q.")
    else:
        for ad in ads:
            category = ad.category
            lines.append(
                f"{ad_service.status_badge(ad.status)} <b>#{ad.id}</b> "
                f"{escape_html(truncate(ad.title or '(nomsiz)', 40))}\n"
                f"   └ 🗂 {escape_html(category.name if category else '—')}  ·  "
                f"{ad_service.format_ad_price(ad)}  ·  👁 {ad.post_count}"
            )
        if total_pages > 1:
            lines.append(f"\n<i>Sahifa {page + 1}/{total_pages}</i>")

    await render(
        target, "\n".join(lines), admin_ads_list_kb(ads, page=page, total_pages=total_pages, status=status, current=status)
    )


@router.callback_query(ModCB.filter(F.action == "ads"))
async def on_admin_ads(
    callback: CallbackQuery, callback_data: ModCB, session: AsyncSession
) -> None:
    page, status = _parse_page_status(callback_data.value, "all")
    await render_ads(callback, session, page, status)
    await alert(callback, "")


async def _render_ad_card(
    callback: CallbackQuery,
    session: AsyncSession,
    ad: Ad,
    *,
    page: int = 0,
    status: str = "all",
) -> None:
    """Admin kartochkasini chizish (rasmlar bilan)."""
    text = await _ad_card_text(session, ad, for_moderation=ad.status == AdStatus.PENDING)
    message = callback.message
    if message is not None and ad.photos:
        await _send_ad_photos(message, ad, truncate(text, 1024))
    await render(callback, text, admin_ad_card_kb(ad, page=page, status=status))


@router.callback_query(ModCB.filter(F.action == "ads_card"))
async def on_admin_ad_card(
    callback: CallbackQuery, callback_data: ModCB, session: AsyncSession, state: FSMContext
) -> None:
    ad = await _load_ad(callback, session, callback_data.ad_id)
    if ad is None:
        return

    await state.clear()
    page, status = _parse_page_status(callback_data.value, "all")
    await _render_ad_card(callback, session, ad, page=page, status=status)
    await alert(callback, "")


@router.callback_query(ModCB.filter(F.action == "pause"))
async def on_admin_pause(
    callback: CallbackQuery, callback_data: ModCB, session: AsyncSession, bot: Bot
) -> None:
    ad = await _load_ad(callback, session, callback_data.ad_id)
    if ad is None:
        return

    if not await ad_service.admin_pause(session, ad, callback.from_user.id, "Admin to'xtatdi"):
        await alert(callback, "⚠️ Faqat faol e'lonni to'xtatish mumkin.", show=True)
        return

    seller = await _seller_of(session, ad)
    text = await text_service.get("ad.paused", elon=escape_html(truncate(ad.title or "", 60)))
    await _notify_seller(bot, seller, text)

    page, status = _parse_page_status(callback_data.value, "all")
    await _render_ad_card(callback, session, ad, page=page, status=status)
    await alert(callback, "⏸ To'xtatildi")


@router.callback_query(ModCB.filter(F.action == "resume"))
async def on_admin_resume(
    callback: CallbackQuery, callback_data: ModCB, session: AsyncSession
) -> None:
    ad = await _load_ad(callback, session, callback_data.ad_id)
    if ad is None:
        return

    if not await ad_service.resume(session, ad):
        await alert(callback, "⚠️ Bu e'lon pauzada emas.", show=True)
        return

    page, status = _parse_page_status(callback_data.value, "all")
    await render_ads(callback, session, page, status)
    await alert(callback, "▶️ Yoqildi")


@router.callback_query(ModCB.filter(F.action == "delete"))
async def on_admin_delete(
    callback: CallbackQuery, callback_data: ModCB, session: AsyncSession
) -> None:
    ad = await _load_ad(callback, session, callback_data.ad_id)
    if ad is None:
        return

    page, status = _parse_page_status(callback_data.value, "all")
    await render(
        callback,
        "🗑 <b>E'lon o'chirilsinmi?</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 {escape_html(truncate(ad.title or '(nomsiz)', 50))}\n\n"
        "<i>Sotuvchining obuna limitidan qaytariladi.</i>",
        ad_delete_confirm_kb(ad, page=page, status=status),
    )
    await alert(callback, "")


@router.callback_query(ModCB.filter(F.action == "delete_confirm"))
async def on_admin_delete_confirm(
    callback: CallbackQuery, callback_data: ModCB, session: AsyncSession, bot: Bot
) -> None:
    ad = await _load_ad(callback, session, callback_data.ad_id)
    if ad is None:
        return

    seller = await _seller_of(session, ad)
    page, status = _parse_page_status(callback_data.value, "all")
    removed = False
    if seller is not None:
        removed = await ad_service.soft_delete(session, seller, ad)

    await render_ads(callback, session, page, status)
    await alert(callback, "🗑 O'chirildi" if removed else "⚠️ Allaqachon o'chirilgan")


@router.callback_query(ModCB.filter(F.action == "history"))
async def on_history(
    callback: CallbackQuery, callback_data: ModCB, session: AsyncSession
) -> None:
    """🕘 Moderatsiya tarixi."""
    ad = await _load_ad(callback, session, callback_data.ad_id)
    if ad is None:
        return

    rows = await ad_service.moderation_history(session, ad.id)
    lines = [
        f"🕘 <b>Moderatsiya tarixi — #{ad.id}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if not rows:
        lines.append("📭 Yozuv yo'q (e'lon tasdiq talab qilmaydigan toifada bo'lgan).")
    else:
        titles = {"approved": "✅ Tasdiqlangan", "rejected": "❌ Rad etilgan", "revised": "✏️ Tahrirlangan"}
        for row in rows:
            lines.append(
                f"{titles.get(row.decision, row.decision)} — {fmt_date(row.created_at)}\n"
                f"   └ admin <code>{row.admin_id or '—'}</code>"
                + (f"\n   └ sabab: {escape_html(truncate(row.reason, 120))}" if row.reason else "")
            )

    page, status = _parse_page_status(callback_data.value, "all")
    await render(callback, "\n".join(lines), cancel_kb(ad.id, action="ads_card", value=f"{page}|{status}"))
    await alert(callback, "")


# ═════════════════ Tashqi foydalanish (panel dispatch) ═════════════
async def open_moderation(callback: CallbackQuery, session: AsyncSession) -> None:
    await render_pending(callback, session, 0)
    await alert(callback, "")


async def open_ads(callback: CallbackQuery, session: AsyncSession) -> None:
    await render_ads(callback, session, 0, "all")
    await alert(callback, "")


__all__ = ["open_ads", "open_moderation", "render_ads", "render_pending", "router"]
