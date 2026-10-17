"""Bepul e'lonlar uchun majburiy moderator tasdig'i (pullik modlardan mustaqil)."""

from __future__ import annotations

from math import ceil

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole
from app.db.models import ActionLog, FreeAd, Group
from app.filters import IsAdmin
from app.keyboards.callbacks import FreeCB, FreeModCB
from app.keyboards.free_ads import free_pending_kb, free_review_kb, free_revoke_kb
from app.services import free_ad_service as free_ads
from app.utils.text import escape_html
from app.utils.tg import alert, render

router = Router(name="admin:free_ads")
router.callback_query.filter(FreeModCB.filter(), IsAdmin(AdminRole.MODERATOR))
PER_PAGE = 12


async def render_pending(target: CallbackQuery, session: AsyncSession,
                         page: int = 0) -> None:
    pending = int((await session.execute(select(func.count(FreeAd.id)).where(
        FreeAd.review_status == "pending",
    ))).scalar_one())
    approved = int((await session.execute(select(func.count(FreeAd.id)).where(
        FreeAd.review_status == "approved",
    ))).scalar_one())
    total = pending + approved
    pages = max(1, ceil(total / PER_PAGE))
    page = max(0, min(page, pages - 1))
    ads = list((await session.execute(select(FreeAd).where(
        FreeAd.review_status.in_(("pending", "approved")),
    ).order_by(case((FreeAd.review_status == "pending", 0), else_=1),
               FreeAd.id.desc()).offset(page * PER_PAGE).limit(PER_PAGE))).scalars())
    text = (f"🎁 <b>Bepul e'lonlar</b> · 🕓 kutilmoqda {pending} · ✅ tasdiqlangan {approved}\n"
            "Yangi/tahrirlangan rasm-matnni ko'rib qaror qiling. "
            "Tasdiqlangan e'lonni ham kerak bo'lsa bekor qilish mumkin. "
            "Taklif va muddat alohida tekshiriladi.")
    if not ads:
        text += "\n\nHozir e'lon yo'q."
    else:
        text += f"\n\nSahifa {page + 1}/{pages}."
    await render(target, text, free_pending_kb(ads, page, pages))


@router.callback_query(FreeModCB.filter(F.action == "list"))
async def on_list(callback: CallbackQuery, callback_data: FreeModCB,
                  session: AsyncSession) -> None:
    await render_pending(callback, session, callback_data.page)
    await alert(callback, "")


@router.callback_query(FreeModCB.filter(F.action == "card"))
async def on_card(callback: CallbackQuery, callback_data: FreeModCB,
                  session: AsyncSession) -> None:
    ad = await session.get(FreeAd, callback_data.ad_id)
    if not ad or ad.review_status not in {"pending", "approved"}:
        await alert(callback, "E'lon bu ro'yxatda yo'q; yangilang.", show=True)
        return
    pending = ad.review_status == "pending"
    photo = ad.pending_photo_id if pending else ad.approved_photo_id
    caption = ad.pending_caption if pending else ad.approved_caption
    if not photo:
        await alert(callback, "E'lonning rasmi yo'q; adminga xabar bering.", show=True)
        return
    group = await session.get(Group, ad.group_id)
    group_name = group.display if group else "Guruh o'chirilgan"
    if callback.message:
        try:
            await callback.message.answer_photo(photo,
                                                caption=f"Bepul e'lon #{ad.id} · tahrir {ad.revision}",
                                                parse_mode=None)
        except TelegramAPIError as exc:
            logger.warning("Bepul e'lon #{} rasmi: {}", ad.id, exc)
    await render(callback,
                 f"{'🕓' if pending else '✅'} <b>Bepul e'lon #{ad.id}</b> · tahrir {ad.revision}\n"
                 f"👥 {escape_html(group_name)}\n"
                 f"👤 <code>{ad.user_id}</code>\n\n"
                 f"{escape_html(caption or '')}\n\n"
                 "Admin tasdiq faqat mazmunga; taklif/oy alohida tekshiriladi.",
                 free_review_kb(ad) if pending else free_revoke_kb(ad))
    await alert(callback, "")


@router.callback_query(FreeModCB.filter(F.action.in_({"approve", "reject"})))
async def on_review(callback: CallbackQuery, callback_data: FreeModCB,
                    session: AsyncSession, bot: Bot) -> None:
    approve = callback_data.action == "approve"
    try:
        ad = await free_ads.review(session, callback_data.ad_id, callback_data.revision,
                                   callback.from_user.id, approve=approve)
    except ValueError as exc:
        await alert(callback, str(exc), show=True)
        return
    session.add(ActionLog(actor_id=callback.from_user.id,
                          action="free_ad_approve" if approve else "free_ad_reject",
                          entity="free_ad", entity_id=ad.id, group_id=ad.group_id,
                          before={"revision": ad.revision, "status": "pending"},
                          after={"status": ad.review_status}))
    user_id, group_id = ad.user_id, ad.group_id
    await session.commit()  # boshqa admin eski revision'ni qayta tasdiqlay olmaydi
    try:
        await bot.send_message(user_id,
            ("✅ E'lon mazmuni tasdiqlandi. Guruhga kerakli do'stlar qo'shilgach "
             "bot avtomatik joylashni boshlaydi." if approve else
             "❌ E'lon mazmuni rad etildi. Surat/matnni tuzatib qayta yuboring. "
             "Avvalgi tasdiqlangan e'lon bo'lsa, faqat o'sha mazmun saqlanadi."),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🎁 E'lonimni ko'rish", callback_data=FreeCB(
                    action="card", group_id=group_id,
                ).pack())
            ]]),
        )
    except TelegramAPIError:
        logger.debug("Bepul e'lon #{} foydalanuvchiga DM yuborilmadi", callback_data.ad_id)
    await render_pending(callback, session)
    await alert(callback, "✅ Tasdiqlandi" if approve else "❌ Rad etildi")


@router.callback_query(FreeModCB.filter(F.action == "revoke_confirm"))
async def on_revoke_confirm(callback: CallbackQuery, callback_data: FreeModCB,
                            session: AsyncSession) -> None:
    ad = await session.get(FreeAd, callback_data.ad_id)
    if ad is None or ad.review_status != "approved" or ad.revision != callback_data.revision:
        await alert(callback, "Tasdiq o'zgargan; kartani yangilang.", show=True)
        return
    await render(callback,
                 f"⚠️ <b>Bepul e'lon #{ad.id} tasdig'ini bekor qilasizmi?</b>\n"
                 "Keyingi postlar to'xtaydi, foydalanuvchi yangi rasm/matnni "
                 "adminga qayta yuborishi kerak. Boshqa guruh va e'lonlarga tegmaydi.",
                 free_revoke_kb(ad, confirm=True))
    await alert(callback, "")


@router.callback_query(FreeModCB.filter(F.action == "revoke"))
async def on_revoke(callback: CallbackQuery, callback_data: FreeModCB,
                    session: AsyncSession, bot: Bot) -> None:
    try:
        ad = await free_ads.revoke(session, callback_data.ad_id,
                                   callback_data.revision, callback.from_user.id)
    except ValueError as exc:
        await alert(callback, str(exc), show=True)
        return
    session.add(ActionLog(actor_id=callback.from_user.id, action="free_ad_revoke",
                          entity="free_ad", entity_id=ad.id, group_id=ad.group_id,
                          before={"status": "approved", "revision": ad.revision},
                          after={"status": "rejected"}))
    uid, gid = ad.user_id, ad.group_id
    await session.commit()
    try:
        await bot.send_message(uid,
            "🚫 Admin bepul e'lon tasdig'ini bekor qildi. Joylash to'xtatildi; "
            "yangi surat/matnni qayta tekshiruvga yuboring.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🎁 E'lonimni ko'rish", callback_data=FreeCB(
                    action="card", group_id=gid,
                ).pack())
            ]]),
        )
    except TelegramAPIError:
        logger.debug("Bepul e'lon #{} bekor qilingani DM'ga yetmadi", ad.id)
    await render_pending(callback, session)
    await alert(callback, "🚫 Tasdiq bekor qilindi")
