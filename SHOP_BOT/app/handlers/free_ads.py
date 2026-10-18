"""Oddiy /start → soha guruhi → bepul/pullik → suratli bepul e'lon.

FreeCB faqat shaxsiy chatda ishlaydi; user_id hech qachon callback/FSMdan
olinmaydi. Sotuvchilik arizasi va pullik obuna bu yo'lda majburiy emas.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group
from app.filters import PrivateChat
from app.keyboards.callbacks import FreeCB
from app.keyboards.free_ads import choice_kb, free_card_kb, group_list_kb, preview_kb
from app.services import free_ad_service as free_ads
from app.services.notify import get_admin_ids
from app.services.settings_service import settings_service
from app.states import FreeAdStates
from app.utils.text import escape_html
from app.utils.tg import alert, render
from app.utils.time import ensure_aware, fmt_dt, utcnow

router = Router(name="user:free_ads")


async def _groups(target: CallbackQuery | Message, session: AsyncSession) -> None:
    available = await free_ads.groups(session)
    text = ("📢 <b>E'lon chiqadigan guruhni tanlang</b>\n"
            "Har bir soha guruhining e'loni va taklif hisobi alohida.")
    if not available:
        text += "\n\nHozir bot admin bo'lgan faol soha guruhi mavjud emas."
    await render(target, text, group_list_kb(available))


async def _choice(target: CallbackQuery, session: AsyncSession, group: Group) -> None:
    policy = await free_ads.terms(session, group)
    n = policy.required_n if policy else None
    wait = policy.min_stay_minutes if policy else None
    text = (
        f"📢 <b>{escape_html(group.display)}</b>\n\n"
        "🎁 <b>Bepul:</b> shu guruhning o'ziga Telegramdagi «A'zo qo'shish» orqali "
        + (f"<b>{n} ta haqiqiy a'zo</b> qo'shing. " if n else "tasdiqlangan takliflar kerak. ")
        + (f"Ular kamida {wait} daqiqa a'zo bo'lishi kerak. " if wait else "")
        + "Bitta surat va e'lon matnini admin tekshiradi. Tasdiq va taklifdan keyin "
        "30 kunlik huquq; shu muddatda e'lonni almashtirish mumkin. "
        "Keyingi 30 kun uchun yangi takliflar kerak.\n\n"
        "💳 <b>Pullik:</b> taklif talabi yo'q; tarif, suratlar va joylash oralig'i "
        "narxga bog'liq. «Pullik imkoniyat» orqali tarifni tanlab to'lash mumkin."
    )
    if group.settings and not group.settings.free_ads_enabled:
        text += "\n\n⚠️ Admin bu guruhda bepul e'lonni hali yoqmagan."
    elif not policy:
        text += "\n\n⚠️ Bu guruhning qo'lda a'zo qo'shish sanoqchisi hali jonli emas."
    if not group.is_active or not group.settings or not group.settings.posting_enabled:
        text += "\n⚠️ Joylash hozir pauzada; bo'sh navbat pauzasi faqat e'lon yuborilganda tiklanadi."
    await render(target, text, choice_kb(group.id))


async def _card(target: CallbackQuery | Message, session: AsyncSession,
                bot: Bot, group: Group, user_id: int) -> None:
    ad = await free_ads.get_ad(session, user_id, group.id)
    policy = await free_ads.terms(session, group)
    access = await free_ads.entitlement(session, user_id, group.id)
    now = utcnow()
    if ad and ad.review_status == "approved" and ad.desired_running:
        member_ok = await free_ads.is_member(bot, group.tg_chat_id, user_id)
        await free_ads.maybe_activate(session, ad, now, member_ok=member_ok,
                                      allow_new=await settings_service.is_feature_enabled_fresh("counter"))
        await session.flush()
        access = await free_ads.entitlement(session, user_id, group.id)
    count = await free_ads.unspent_count(session, group.id, user_id)
    n = policy.required_n if policy else 0
    lines = [f"🎁 <b>{escape_html(group.display)} — bepul e'lon</b>",
             "Sotuvchilik arizasi shart emas · bitta surat · har tahrir admin tasdig'i.", ""]
    if policy:
        lines.append(f"👥 Bu davr uchun takliflar: <b>{count} / {n}</b> tasdiqlangan. "
                     "Do'stlarni guruhdagi «A'zo qo'shish» orqali qo'shing.")
    elif group.settings and not group.settings.free_ads_enabled:
        lines.append("⚠️ Admin bu guruhda bepul e'lonni yoqmagan.")
    else:
        lines.append("⚠️ Guruhda jonli sanoqchi yo'q; yangi davr hozir ochilmaydi.")
    if access and ensure_aware(access.expires_at) > now:
        lines.append(f"📅 Bepul muddat: <b>{fmt_dt(access.expires_at)} gacha</b> "
                     f"({access.period}-davr). Yangi surat muddatni uzaytirmaydi.")
    elif access:
        lines.append("⏳ 30 kun tugagan. Yangi davr uchun yangi N ta tasdiqlangan do'st kerak.")
    else:
        lines.append("⏳ 30 kunlik muddat faqat admin tasdig'i, N taklif va a'zolikdan so'ng boshlanadi.")
    if not ad:
        lines.append("\n📷 Matni bilan bitta surat yuboring; admin ko'rib chiqadi.")
    else:
        status = {"pending": "🕓 Admin ko'rib chiqmoqda", "approved": "✅ Mazmun tasdiqlangan",
                  "rejected": "❌ Mazmun rad etilgan"}.get(ad.review_status, ad.review_status)
        lines.append(f"\n📢 E'lon #{ad.id}: {status}.")
        if ad.rejected_reason:
            lines.append(escape_html(ad.rejected_reason))
        lines.append("⏹ Siz to'xtatgansiz; muddat yurishda davom etadi." if not ad.desired_running else
                     "▶️ Avtomatik joylash so'ralgan.")
        if ad.admin_paused:
            lines.append("⏸ Admin shu e'lonni pauzalagan; Start buni bekor qilmaydi.")
        if ad.next_post_at and ad.review_status == "approved" and access and ensure_aware(access.expires_at) > now:
            lines.append(f"⏱ Navbatdagi shaxsiy vaqt: {fmt_dt(ad.next_post_at)} "
                         "(Telegram texnik navbatida biroz kechikishi mumkin).")
        lines.append(f"📊 Joylangan: {ad.post_count} marta.")
    can_submit = bool(policy and (free_ads.ready_group(group) or group.paused_reason == "empty_queue"))
    await render(target, "\n".join(lines), free_card_kb(group.id, ad, can_submit=can_submit))


async def _notify_admins(bot: Bot, session: AsyncSession, ad_id: int) -> None:
    from app.db.models import FreeAd
    from app.keyboards.free_ads import free_review_kb

    ad = await session.get(FreeAd, ad_id)
    group = await session.get(Group, ad.group_id) if ad else None
    if not ad or not group or not ad.pending_photo_id:
        return
    text = (f"🕓 <b>Bepul e'lon #{ad.id} (tahrir {ad.revision})</b>\n"
            f"👥 {escape_html(group.display)} · 👤 <code>{ad.user_id}</code>\n\n"
            f"{escape_html(ad.pending_caption or '')}\n\n"
            "Faqat shu rasm/matnni tasdiqlang; taklif va muddat alohida tekshiriladi.")
    for admin_id in await get_admin_ids(session):
        admin_text = text
        try:
            await bot.send_photo(admin_id, ad.pending_photo_id,
                                 caption=f"Bepul e'lon #{ad.id} · {group.display}"[:180],
                                 parse_mode=None)
        except TelegramAPIError as exc:
            logger.warning("Bepul e'lon #{} rasmi adminga yetmadi: {}", ad.id, exc)
            admin_text += "\n⚠️ Rasmni yuborib bo'lmadi; navbatdan qayta ko'ring."
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=free_review_kb(ad))
        except TelegramAPIError as exc:
            logger.warning("Bepul e'lon #{} admin {} xabari: {}", ad.id, admin_id, exc)


@router.message(Command("elon"), PrivateChat())
async def cmd_elon(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if await state.get_state() in {step.state for step in FreeAdStates.__all_states__}:
        await state.clear()
    await _groups(message, session)


@router.callback_query(FreeCB.filter(), PrivateChat())
async def on_free_callback(callback: CallbackQuery, callback_data: FreeCB,
                           session: AsyncSession, bot: Bot, state: FSMContext) -> None:
    action, group_id = callback_data.action, callback_data.group_id
    user_id = callback.from_user.id
    if action == "list":
        await _groups(callback, session)
    else:
        group = await free_ads.group_for(session, group_id)
        if group is None:
            await alert(callback, "Guruh topilmadi yoki bot admin emas.", show=True)
            return
        if action == "group":
            await _choice(callback, session, group)
        elif action == "paid":
            from sqlalchemy import select

            from app.db.models import Category
            from app.handlers.seller import _catalog_text
            from app.keyboards.seller_panel import tariffs_catalog_kb
            from app.services import seller_service, tariff_service

            if await free_ads.is_blocked(session, user_id):
                await alert(callback, "Hisob cheklangan; admin bilan bog'laning.", show=True)
                return
            # Sotuvchilik arizasi kerak emas: odam tarifni ko'rishi/to'lashi
            # uchun oddiy kabinet avtomatik ochiladi. E'lon faqat admin tasdig'idan keyin.
            await seller_service.get_or_create_seller(
                session, user_id, display_name=callback.from_user.full_name,
            )
            tariffs = await tariff_service.list_all_active(session)
            category_ids = set((await session.execute(select(Category.id).where(
                Category.group_id == group.id, Category.is_active.is_(True),
            ))).scalars())
            allowed = [t for t in tariffs
                       if (t.allowed_group_ids is None or group.id in t.allowed_group_ids)
                       and (t.allowed_category_ids is None
                            or bool(category_ids.intersection(t.allowed_category_ids)))]
            await render(callback,
                         f"💳 <b>{escape_html(group.display)}</b> — pullik tariflar\n"
                         "Do'st qo'shish shart emas. Xarid uchun chek yuboring; "
                         "admin tasdiqlagach e'lon yuborish mumkin.\n\n"
                         + await _catalog_text(session, allowed),
                         tariffs_catalog_kb(allowed))
        elif action == "card":
            await _card(callback, session, bot, group, user_id)
        elif action == "photo":
            if not await free_ads.terms(session, group):
                await alert(callback, "Bu guruhning qo'lda qo'shish sanoqchisi jonli emas.", show=True)
                return
            if not (free_ads.ready_group(group) or group.paused_reason == "empty_queue"):
                await alert(callback, "Bu guruhda joylash hozir o'chirilgan.", show=True)
                return
            await state.set_state(FreeAdStates.waiting_photo)
            await state.set_data({"free_group_id": group.id})
            await render(callback,
                f"📷 <b>{escape_html(group.display)}</b> uchun bitta surat yuboring.\n"
                "E'lon matni va aloqani suratning <b>izohi</b>ga yozing "
                "(kamida 10 belgi, eng ko'pi 900 birlik; emoji 2 birlik). "
                "Albom emas, bitta surat. Yuborishdan oldin preview ko'rsatiladi.")
        elif action == "cancel":
            await state.clear()
            await _card(callback, session, bot, group, user_id)
        elif action == "submit":
            data = await state.get_data()
            if (await state.get_state() != FreeAdStates.preview.state
                    or data.get("free_group_id") != group.id or not data.get("free_photo_id")):
                await alert(callback, "Preview eskirgan; suratni qayta yuboring.", show=True)
                return
            if not await free_ads.is_member(bot, group.tg_chat_id, user_id):
                await alert(callback, "Avval e'lon chiqadigan guruhga a'zo bo'ling.", show=True)
                return
            try:
                ad = await free_ads.submit(session, user_id, group.id,
                                           data["free_photo_id"], data["free_caption"])
            except ValueError as exc:
                await alert(callback, str(exc), show=True)
                return
            await session.commit()  # moderation xabari faqat DB'dagi draft saqlangach
            await state.clear()
            await _notify_admins(bot, session, ad.id)
            await _card(callback, session, bot, group, user_id)
        elif action in {"start", "stop"}:
            ad = await free_ads.get_ad(session, user_id, group.id)
            if not ad:
                await alert(callback, "Avval e'lon yuboring.", show=True)
                return
            if action == "start" and not await free_ads.is_member(bot, group.tg_chat_id, user_id):
                await alert(callback, "Avval shu guruhga a'zo bo'ling.", show=True)
                return
            await free_ads.set_running(session, ad, action == "start")
            await _card(callback, session, bot, group, user_id)
        else:
            await alert(callback, "Eski tugma; /elon ni qayta yuboring.")
            return
    await alert(callback, "")


@router.message(StateFilter(FreeAdStates.waiting_photo), PrivateChat(),
                ~F.text.startswith("/start"))
async def on_free_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not message.photo or message.media_group_id:
        await message.answer("Iltimos, matni izohida yozilgan bitta surat yuboring (albom emas).")
        return
    caption = (message.caption or "").strip()
    if not free_ads.valid_caption(caption):
        await message.answer("Surat izohiga kamida 10 belgili, ko'pi bilan 900 birlikli "
                             "e'lon va aloqa matnini yozing (emoji 2 birlik).")
        return
    await state.update_data(free_photo_id=message.photo[-1].file_id, free_caption=caption)
    await state.set_state(FreeAdStates.preview)
    await message.answer_photo(message.photo[-1].file_id, caption=caption,
                               parse_mode=None, reply_markup=preview_kb(data["free_group_id"]))


@router.message(StateFilter(FreeAdStates.preview), PrivateChat(),
                ~F.text.startswith("/start"))
async def on_free_preview_text(message: Message) -> None:
    await message.answer("Surat ostidagi «Adminga yuborish» tugmasini bosing yoki boshqa surat tanlang.")
