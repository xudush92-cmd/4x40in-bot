"""📢 Sotuvchi e'lonlari: usta (FSM), «Mening e'lonlarim», tahrirlash (Phase 3).

Oqim:

    ➕ Yangi e'lon → 🗂 toifa → ✏️ sarlavha → 📝 tavsif → 💰 narx → ☎️ aloqa
                    → 🖼 rasmlar (1..tarif limiti) → 👀 ko'rish → 📤 yuborish

Yuborilgach:
  * toifa moderatsiya talab qilsa → 🕓 admin tasdig'iga tushadi;
  * aks holda → darhol 🟢 navbatga qo'shiladi (Phase 4 joylaydi).

Diqqat: bitta FSM holati ham usta, ham tahrirlash uchun ishlatiladi —
ajratish `data["flow"]` (`wizard` | `edit`) va `data["step"]` orqali.
"""

from __future__ import annotations

from math import ceil

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdStatus
from app.db.models import Ad, Seller
from app.filters import IsSeller, PrivateChat
from app.keyboards.ads import (
    ad_card_kb,
    ad_delete_confirm_kb,
    ads_list_kb,
    back_to_ads_kb,
    categories_kb,
    contact_kb,
    contact_type_label,
    edit_kb,
    photos_kb,
    preview_kb,
    status_filter_title,
    wizard_step_kb,
)
from app.keyboards.callbacks import AdCB
from app.keyboards.common import PER_PAGE_ADS
from app.services import ad_service, category_service, notify, seller_service, subscription_service
from app.services.tariff_service import parse_price
from app.services.text_service import text_service
from app.states import SellerAdStates
from app.utils.text import escape_html, truncate
from app.utils.time import fmt_date
from app.utils.tg import alert, render

router = Router(name="seller:ads")
router.callback_query.filter(AdCB.filter(), PrivateChat(), IsSeller())
router.message.filter(StateFilter(SellerAdStates), PrivateChat(), IsSeller())

FLOW_WIZARD = "wizard"
FLOW_EDIT = "edit"

TITLE_PROMPT = (
    "✏️ <b>E'lon sarlavhasi</b>\n"
    "Qisqa va aniq yozing (3–120 belgi).\n"
    "Masalan: <i>iPhone 15 Pro Max 256GB</i>"
)
DESC_PROMPT = (
    "📝 <b>Tavsif</b>\n"
    "Holati, kafolati, yetkazib berish shartlari...\n"
    "O'tkazib yuborish uchun <code>-</code> yuboring."
)
PRICE_PROMPT = (
    "💰 <b>Narx</b> (so'm)\n"
    "Masalan: <code>12500000</code> yoki <code>12500000 so'm</code>\n"
    "Kelishilgan narx uchun <code>kelishiladi</code> yozing."
)
CONTACT_PROMPT = (
    "☎️ <b>Aloqa</b>\n"
    "Avval turini tanlang, keyin qiymatini yozing.\n"
    "Masalan: <code>@dokon_admin</code>, <code>+998901234567</code> yoki "
    "<code>https://t.me/dokon</code>"
)
PHOTOS_PROMPT = (
    "🖼 <b>Rasmlar</b>\n"
    "Rasmlarni birma-bir yuboring (albom ham bo'ladi).\n"
    "Tugagach <b>✅ Tayyor</b> tugmasini bosing."
)

# Usta qadami → FSM holati
STEP_STATES = {
    "title": SellerAdStates.waiting_title,
    "desc": SellerAdStates.waiting_description,
    "price": SellerAdStates.waiting_price,
    "contact": SellerAdStates.waiting_contact,
    "photos": SellerAdStates.waiting_photos,
    "preview": SellerAdStates.preview,
    "edit_title": SellerAdStates.waiting_title,
    "edit_desc": SellerAdStates.waiting_description,
    "edit_price": SellerAdStates.waiting_price,
    "edit_contact": SellerAdStates.waiting_contact,
}

STEP_PROMPTS = {
    "title": TITLE_PROMPT,
    "desc": DESC_PROMPT,
    "price": PRICE_PROMPT,
    "contact": CONTACT_PROMPT,
    "photos": PHOTOS_PROMPT,
}

# Orqaga tugmasi qaysi qadamga qaytaradi
BACK_STEPS = {"desc": "title", "price": "desc", "contact": "price", "photos": "contact"}

# Tahrirlash menyusidagi tugma → (savol, qadam, qaytariladigan holat matni)
EDIT_FIELDS: dict[str, tuple[str, str]] = {
    "e_title": ("✏️ <b>Yangi sarlavha</b>\n3–120 belgi. Masalan: <i>iPhone 15 Pro Max 256GB</i>", "edit_title"),
    "e_desc": ("📝 <b>Yangi tavsif</b>\nTozalash uchun <code>-</code> yuboring.", "edit_desc"),
    "e_price": (
        "💰 <b>Yangi narx</b> (so'm)\nMasalan: <code>12500000</code> · "
        "kelishilgan narx uchun <code>kelishiladi</code>",
        "edit_price",
    ),
    "e_contact": (
        "☎️ <b>Yangi aloqa qiymati</b>\nMasalan: <code>@dokon_admin</code> yoki <code>+998901234567</code>",
        "edit_contact",
    ),
}


# ═══════════════════════════ Yordamchilar ═════════════════════════
async def _seller(callback: CallbackQuery, session: AsyncSession) -> Seller | None:
    seller = await seller_service.get_seller(session, callback.from_user.id)
    if seller is None:
        await alert(callback, "⚠️ Siz sotuvchi sifatida ro'yxatdan o'tmagansiz.", show=True)
        return None
    return seller


async def _own_ad(
    callback: CallbackQuery, session: AsyncSession, seller: Seller, ad_id: int
) -> Ad | None:
    """E'lonni egalik bilan olish (begona e'lon ochilmasligi uchun)."""
    ad = await ad_service.get_ad(session, ad_id, seller_id=seller.id)
    if ad is None:
        await alert(callback, "⚠️ E'lon topilmadi.", show=True)
        return None
    return ad


async def _active_categories(session: AsyncSession):
    """Usta uchun toifalar: faol + guruhga biriktirilgan."""
    categories = await category_service.list_categories(session, limit=100)
    return [c for c in categories if c.is_active and c.group_id is not None]


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


def _limit_of(data: dict) -> int:
    return int(data.get("photo_limit") or 3)


async def _show_step(
    target: CallbackQuery | Message,
    state: FSMContext,
    step: str,
    *,
    ad_id: int,
    count: int | None = None,
) -> None:
    """Usta qadamini ko'rsatish (holat + matn + navigatsiya)."""
    data = await state.get_data()
    flow = str(data.get("flow") or FLOW_WIZARD)
    await state.set_state(STEP_STATES[step])
    await state.update_data(step=step)

    if step == "photos":
        limit = _limit_of(data)
        photos = count if count is not None else int(data.get("photo_count") or 0)
        await render(
            target,
            f"{PHOTOS_PROMPT}\n\n{ad_service.photos_line(photos, limit)}",
            photos_kb(ad_id=ad_id, count=photos, limit=limit, from_edit=flow == FLOW_EDIT),
        )
        return

    if step == "contact":
        await render(target, CONTACT_PROMPT, contact_kb(ad_id=ad_id))
        return

    await render(
        target,
        STEP_PROMPTS[step],
        wizard_step_kb(ad_id=ad_id, back=BACK_STEPS.get(step), skip=(step == "desc")),
    )


async def _show_edit_menu(
    target: CallbackQuery | Message,
    session: AsyncSession,
    ad: Ad,
    *,
    page: int = 0,
    status: str = "all",
    note: str = "",
) -> None:
    """Tahrirlash menyusi va qayta yuborish yo'li."""
    lines = [
        "✏️ <b>Tahrirlash</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📢 {escape_html(truncate(ad.title or '(nomsiz)', 50))}",
        f"📌 Holat: <b>{ad_service.status_title(ad.status)}</b>",
        "",
    ]
    if note:
        lines.append(note)
        lines.append("")
    lines.append("Qaysi maydonni o'zgartirasiz?")

    await render(target, "\n".join(lines), edit_kb(ad, page=page, status=status))


async def _show_preview(
    target: CallbackQuery | Message,
    session: AsyncSession,
    ad: Ad,
    *,
    from_edit: bool = False,
) -> None:
    """«Guruhda qanday ko'rinadi» — caption ko'rinishida."""
    category = await ad_service.category_of(session, ad)
    photos = await ad_service.photo_count(session, ad.id)
    lines = [
        "👀 <b>E'lon ko'rinishi</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🗂 Toifa: <b>{escape_html(category.name if category else '—')}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        ad.caption,
        "━━━━━━━━━━━━━━━━━━━━",
        f"🖼 Rasmlar: <b>{photos}</b> ta  ·  📌 {ad_service.status_title(ad.status)}",
        "<i>Guruhda: rasmlar albom bo'lib, yuqoridagi matn izoh sifatida chiqadi.</i>",
    ]
    await render(target, "\n".join(lines)[:4000], preview_kb(ad_id=ad.id, from_edit=from_edit))


async def _finish_wizard(
    callback: CallbackQuery,
    session: AsyncSession,
    seller: Seller,
    ad: Ad,
    state: FSMContext,
    bot: Bot | None = None,
) -> None:
    """📤 Yuborish: limitdan hisoblash + moderatsiya holati."""
    ok, result = await ad_service.submit(session, seller, ad)
    if not ok:
        await alert(callback, result, show=True)
        return

    photos = await ad_service.photo_count(session, ad.id)
    subscription = await subscription_service.active_for(session, seller.id)
    limit_line = ""
    if subscription is not None:
        limit_line = (
            f"\n📢 Limit: <b>{subscription.ads_used}/{subscription.ads_limit}</b> "
            f"(qoldi {subscription.ads_left})"
        )

    if result == AdStatus.PENDING:
        text = (
            "🕓 <b>E'lon tekshiruvga yuborildi</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📢 <b>{escape_html(truncate(ad.title, 60))}</b>\n"
            f"🖼 Rasmlar: <b>{photos}</b> ta\n\n"
            "Admin tasdiqlagach e'lon navbatga qo'shiladi va sizga xabar beraman."
            f"{limit_line}"
        )
    else:
        text = (
            "🎉 <b>E'lon faollashtirildi!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📢 <b>{escape_html(truncate(ad.title, 60))}</b>\n"
            f"🖼 Rasmlar: <b>{photos}</b> ta\n\n"
            "E'lon navbatga qo'shildi — navbati kelganda guruhlarga joylanadi."
            f"{limit_line}"
        )

    if result == AdStatus.PENDING and bot is not None:
        await _notify_admins_new_ad(bot, session, ad)

    await state.clear()
    await render(callback, text, back_to_ads_kb())


async def _notify_admins_new_ad(bot: Bot, session: AsyncSession, ad: Ad) -> None:
    """🕓 Yangi e'lon moderatsiyaga tushganda adminlarga xabar (REJA.md 8.1)."""
    category = await ad_service.category_of(session, ad)
    seller = await seller_service.get_seller_by_id(session, ad.seller_id)
    text = await text_service.get(
        "ad.submitted",
        elon=escape_html(truncate(ad.title or "", 60)),
        toifa=escape_html(category.name if category else "—"),
        sotuvchi=escape_html(seller_service.seller_label(seller) if seller else "—"),
    )
    await notify.notify_admins(bot, text)


async def _start_wizard(
    callback: CallbackQuery, session: AsyncSession, seller: Seller, state: FSMContext
) -> None:
    """➕ Yangi e'lon: avval obuna/limit, keyin toifa tanlash."""
    ok, reason = await subscription_service.can_publish(session, seller)
    if not ok:
        await alert(callback, reason, show=True)
        return

    categories = await _active_categories(session)
    if not categories:
        await alert(
            callback,
            "🗂 Hozircha faol toifa yo'q. Admin toifa qo'shib, guruhga "
            "biriktirishini kuting.",
            show=True,
        )
        return

    await state.clear()
    await state.set_state(SellerAdStates.waiting_category)
    await state.update_data(flow=FLOW_WIZARD, ad_id=0)
    await render(
        callback,
        "➕ <b>Yangi e'lon</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🗂 <b>1-qadam: toifa tanlang</b>\n"
        "<i>E'lon shu toifa guruhiga joylanadi.</i>",
        categories_kb(categories),
    )


async def render_ads_list(
    target: CallbackQuery | Message,
    session: AsyncSession,
    seller: Seller,
    page: int = 0,
    status: str = "all",
) -> None:
    """Ro'yxat ekrani (panel va callback uchun umumiy)."""
    total = await ad_service.count_seller_ads(session, seller.id, status=status)
    total_pages = max(1, ceil(total / PER_PAGE_ADS))
    page = max(0, min(page, total_pages - 1))
    ads = await ad_service.list_seller_ads(
        session, seller.id, status=status, limit=PER_PAGE_ADS, offset=page * PER_PAGE_ADS
    )
    stats = await ad_service.seller_ads_stats(session, seller.id)
    subscription = await subscription_service.active_for(session, seller.id)

    lines = [
        "📢 <b>Mening e'lonlarim</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Jami: <b>{stats['total']}</b>  ·  🟢 Faol: <b>{stats['active']}</b>  ·  "
        f"🕓 Tekshiruvda: <b>{stats['pending']}</b>  ·  ✏️ Qoralama: <b>{stats['draft']}</b>",
        status_filter_title(status),
    ]
    if subscription is not None:
        lines.append(
            f"📢 Limit: <b>{subscription.ads_used}/{subscription.ads_limit}</b> "
            f"(qoldi {subscription.ads_left})"
        )
    lines.append("")

    if not ads:
        lines.append("📭 Bu filtrda e'lon yo'q. «➕ Yangi e'lon» tugmasini bosing.")
    else:
        for ad in ads:
            category = ad.category
            lines.append(
                f"{ad_service.status_badge(ad.status)} "
                f"<b>{escape_html(truncate(ad.title or '(nomsiz)', 45))}</b>\n"
                f"   ├ 🗂 {escape_html(category.name if category else '—')}"
                f"  ·  💰 {ad_service.format_ad_price(ad)}\n"
                f"   ├ 📌 {ad_service.status_title(ad.status)}  ·  🖼 {len(ad.photos)} ta\n"
                f"   └ 👁 {ad.post_count} marta joylangan"
            )
        if total_pages > 1:
            lines.append(f"\n<i>Sahifa {page + 1}/{total_pages} · jami {total} ta</i>")

    await render(
        target, "\n".join(lines), ads_list_kb(ads, page=page, total_pages=total_pages, status=status)
    )


# ═══════════════════════ Ro'yxat va kartochka ══════════════════════
@router.callback_query(AdCB.filter(F.action == "list"))
async def on_list(callback: CallbackQuery, callback_data: AdCB, session: AsyncSession) -> None:
    seller = await _seller(callback, session)
    if seller is None:
        return
    page, status = _parse_page_status(callback_data.value)
    await render_ads_list(callback, session, seller, page, status)
    await alert(callback, "")


@router.callback_query(AdCB.filter(F.action == "filter"))
async def on_filter(callback: CallbackQuery, callback_data: AdCB, session: AsyncSession) -> None:
    seller = await _seller(callback, session)
    if seller is None:
        return
    status = callback_data.value if callback_data.value in ad_service.STATUS_FILTERS else "all"
    await render_ads_list(callback, session, seller, 0, status)
    await alert(callback, ad_service.filter_label(status))


@router.callback_query(AdCB.filter(F.action == "card"))
async def on_card(callback: CallbackQuery, callback_data: AdCB, session: AsyncSession) -> None:
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return

    page, status = _parse_page_status(callback_data.value)
    category = await ad_service.category_of(session, ad)
    photos = await ad_service.photo_count(session, ad.id)
    stats = await ad_service.ad_stats(session, ad)

    lines = [
        f"{ad_service.status_badge(ad.status)} "
        f"<b>{escape_html(truncate(ad.title or '(nomsiz)', 60))}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📌 Holat: <b>{ad_service.status_title(ad.status)}</b>",
        f"🗂 Toifa: <b>{escape_html(category.name if category else '—')}</b>",
        f"💰 Narx: <b>{ad_service.format_ad_price(ad)}</b>",
        f"☎️ Aloqa: {contact_type_label(ad.contact_type)} "
        f"<code>{escape_html(ad.contact_value or '—')}</code>",
        f"🖼 Rasmlar: <b>{photos}</b> ta",
        f"👁 Joylangan: <b>{stats['post_count']}</b> marta",
    ]
    if stats["last_posted_at"]:
        lines.append(f"🕘 Oxirgi joylash: {fmt_date(stats['last_posted_at'])}")
    if ad.description:
        lines.append(f"\n📝 {escape_html(truncate(ad.description, 300))}")
    if ad.status == AdStatus.REJECTED and ad.reject_reason:
        lines.append(f"\n❌ <b>Rad etish sababi:</b> {escape_html(ad.reject_reason)}")
        lines.append("<i>Tahrirlab, qaytadan yuborishingiz mumkin.</i>")
    if ad.status == AdStatus.EXPIRED:
        lines.append(
            "\n⌛️ <i>Obuna muddati tugagach e'lon navbatdan chiqarildi. Tarif yangilangach "
            "admin uni qayta yoqadi.</i>"
        )

    await render(callback, "\n".join(lines), ad_card_kb(ad, page=page, status=status))
    await alert(callback, "")


@router.callback_query(AdCB.filter(F.action == "stats"))
async def on_stats(callback: CallbackQuery, callback_data: AdCB, session: AsyncSession) -> None:
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return

    page, status = _parse_page_status(callback_data.value)
    stats = await ad_service.ad_stats(session, ad)
    lines = [
        f"📊 <b>{escape_html(truncate(ad.title or '(nomsiz)', 50))}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"👁 Joylashlar soni: <b>{stats['post_count']}</b>",
        f"👥 Qamrab olingan guruhlar: <b>{stats['groups']}</b>",
        f"🖼 Rasmlar: <b>{stats['photos']}</b> ta",
    ]
    if stats["last_posted_at"]:
        lines.append(f"🕘 Oxirgi joylash: {fmt_date(stats['last_posted_at'])}")
    else:
        lines.append("🕘 Hali joylanmagan — navbati kelganda guruhlarga chiqadi.")
    lines.append("\n<i>Batafsil statistika (kunlik grafik) Phase 8 da qo'shiladi.</i>")

    await render(callback, "\n".join(lines), ad_card_kb(ad, page=page, status=status))
    await alert(callback, "")


# ═══════════════════════════ Usta ══════════════════════════════════
@router.callback_query(AdCB.filter(F.action == "new"))
async def on_new(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    seller = await _seller(callback, session)
    if seller is None:
        return
    await _start_wizard(callback, session, seller, state)
    await alert(callback, "")


@router.callback_query(AdCB.filter(F.action == "wiz_cat"))
async def on_wizard_category(
    callback: CallbackQuery, callback_data: AdCB, session: AsyncSession, state: FSMContext
) -> None:
    """Toifa tanlandi → (kerak bo'lsa) qoralama yaratiladi va sarlavha so'raladi."""
    seller = await _seller(callback, session)
    if seller is None:
        return

    try:
        category_id = int(callback_data.value)
    except (TypeError, ValueError):
        await alert(callback, "⚠️ Toifa tanlanmadi.", show=True)
        return

    category = await category_service.get_category(session, category_id)
    if category is None or not category.is_active or category.group_id is None:
        await alert(callback, "⚠️ Bu toifa faol emas yoki guruhga biriktirilmagan.", show=True)
        return

    data = await state.get_data()
    flow = str(data.get("flow") or FLOW_WIZARD)
    ad_id = int(data.get("ad_id") or 0)

    if ad_id:
        ad = await ad_service.get_ad(session, ad_id, seller_id=seller.id)
        if ad is None:
            await alert(callback, "⚠️ E'lon topilmadi.", show=True)
            return
        await ad_service.set_category(session, ad, category)
        await ad_service.edited(session, ad)
    else:
        ad = await ad_service.create_draft(session, seller, category)
        ad_id = ad.id

    limit = await ad_service.photo_limit(session, seller)
    count = await ad_service.photo_count(session, ad.id)
    await state.update_data(
        ad_id=ad_id, category_id=category.id, photo_limit=limit, photo_count=count
    )

    if flow == FLOW_EDIT:
        await state.set_state(SellerAdStates.preview)
        await _show_edit_menu(
            callback,
            session,
            ad,
            note=f"✅ Toifa almashtirildi: <b>{escape_html(category.name)}</b>",
        )
        await alert(callback, "")
        return

    await _show_step(callback, state, "title", ad_id=ad_id)
    await alert(callback, "")


@router.callback_query(AdCB.filter(F.action.in_({"wiz_back", "wiz_skip"})))
async def on_wizard_nav(
    callback: CallbackQuery, callback_data: AdCB, session: AsyncSession, state: FSMContext
) -> None:
    """⬅️ Orqaga / ⏭ O'tkazib yuborish."""
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return

    data = await state.get_data()
    step = str(data.get("step") or "title")

    if callback_data.action == "wiz_skip":
        if step == "desc":
            await ad_service.set_description(session, ad, "")
            await _show_step(callback, state, "price", ad_id=ad.id)
            await alert(callback, "⏭ O'tkazib yuborildi")
            return
        if step == "contact":
            contact_type, contact_value = ad_service.default_contact(seller)
            await ad_service.set_contact(
                session, ad, contact_type=contact_type, contact_value=contact_value
            )
            count = await ad_service.photo_count(session, ad.id)
            await state.update_data(photo_count=count)
            await _show_step(callback, state, "photos", ad_id=ad.id, count=count)
            await alert(callback, "⏭ Profildagi aloqa ishlatiladi")
            return
        await alert(callback, "⏭ O'tkazib yuborildi")
        return

    target = callback_data.value if callback_data.value in STEP_STATES else None
    if target is not None:
        await _show_step(callback, state, target, ad_id=ad.id)
    await alert(callback, "")


@router.callback_query(AdCB.filter(F.action == "c_type"))
async def on_contact_type(
    callback: CallbackQuery, callback_data: AdCB, session: AsyncSession, state: FSMContext
) -> None:
    """☎️ Aloqa turi tanlandi → qiymat so'raladi."""
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return

    contact_type = callback_data.value if callback_data.value in ("username", "phone", "url") else "username"
    await state.set_state(SellerAdStates.waiting_contact)
    await state.update_data(step="contact", contact_type=contact_type)

    hint = {
        "username": "Masalan: <code>@dokon_admin</code>",
        "phone": "Masalan: <code>+998901234567</code>",
        "url": "Masalan: <code>https://t.me/dokon</code>",
    }[contact_type]

    await render(
        callback,
        f"{CONTACT_PROMPT}\n\n{contact_type_label(contact_type)} tanlandi.\n{hint}",
        wizard_step_kb(ad_id=ad.id, back="contact"),
    )
    await alert(callback, "")


@router.callback_query(AdCB.filter(F.action == "wiz_done"))
async def on_wizard_done(
    callback: CallbackQuery, callback_data: AdCB, session: AsyncSession, state: FSMContext
) -> None:
    """✅ Tayyor → ko'rish (preview)."""
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return

    data = await state.get_data()
    photos = await ad_service.photo_count(session, ad.id)
    if photos == 0:
        limit = _limit_of(data)
        await alert(callback, "🖼 Kamida bitta rasm qo'shing.", show=True)
        await render(
            callback,
            f"{PHOTOS_PROMPT}\n\n{ad_service.photos_line(0, limit)}",
            photos_kb(ad_id=ad.id, count=0, limit=limit),
        )
        return

    await state.set_state(SellerAdStates.preview)
    await state.update_data(step="preview", photo_count=photos)
    await _show_preview(callback, session, ad, from_edit=str(data.get("flow")) == FLOW_EDIT)
    await alert(callback, "")


@router.callback_query(AdCB.filter(F.action == "preview"))
async def on_preview(
    callback: CallbackQuery, callback_data: AdCB, session: AsyncSession, state: FSMContext
) -> None:
    """👀 Ko'rish ekrani (kartochka/tahrirlashdan)."""
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return
    await state.update_data(flow=FLOW_EDIT, ad_id=ad.id, step="preview")
    await state.set_state(SellerAdStates.preview)
    await _show_preview(callback, session, ad, from_edit=True)
    await alert(callback, "")


@router.callback_query(AdCB.filter(F.action == "wiz_send"))
async def on_wizard_send(
    callback: CallbackQuery, callback_data: AdCB, session: AsyncSession, state: FSMContext, bot: Bot
) -> None:
    """📤 Yuborish (usta yakuni)."""
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return
    await _finish_wizard(callback, session, seller, ad, state, bot)
    await alert(callback, "")


@router.callback_query(AdCB.filter(F.action == "send"))
async def on_send(
    callback: CallbackQuery, callback_data: AdCB, session: AsyncSession, state: FSMContext, bot: Bot
) -> None:
    """✅ Qoralamani kartochkadan yuborish."""
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return
    await _finish_wizard(callback, session, seller, ad, state, bot)
    await alert(callback, "")


@router.callback_query(AdCB.filter(F.action == "wiz_cancel"))
async def on_wizard_cancel(
    callback: CallbackQuery, callback_data: AdCB, session: AsyncSession, state: FSMContext
) -> None:
    """❌ Bekor qilish: bo'sh qoralama o'chiriladi, to'ldirilgani saqlanadi."""
    seller = await _seller(callback, session)
    if seller is None:
        return

    data = await state.get_data()
    ad_id = int(data.get("ad_id") or callback_data.ad_id or 0)
    await state.clear()

    kept = False
    if ad_id:
        ad = await ad_service.get_ad(session, ad_id, seller_id=seller.id)
        if ad is not None:
            kept = not await ad_service.hard_delete_empty_draft(session, ad)

    if kept:
        text = (
            "❌ <b>Bekor qilindi</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "To'ldirilgan e'lon <b>✏️ qoralama</b> sifatida saqlandi — "
            "«📢 Mening e'lonlarim» bo'limidan davom ettirishingiz mumkin."
        )
    else:
        text = "❌ <b>Bekor qilindi.</b>"

    await render(callback, text, back_to_ads_kb())
    await alert(callback, "")


# ═══════════════════ Usta: matn va rasm qadamlari ═════════════════
@router.message(StateFilter(SellerAdStates), F.photo)
async def on_photo(message: Message, session: AsyncSession, state: FSMContext) -> None:
    """🖼 Rasm qabul qilish (usta va rasmlarni tahrirlash)."""
    data = await state.get_data()
    ad_id = int(data.get("ad_id") or 0)
    flow = str(data.get("flow") or FLOW_WIZARD)

    seller = await seller_service.get_seller(session, message.from_user.id if message.from_user else 0)
    if seller is None:
        return

    if not ad_id:
        await message.answer("⚠️ Avval e'lonni boshlang: «➕ Yangi e'lon».")
        return

    ad = await ad_service.get_ad(session, ad_id, seller_id=seller.id)
    if ad is None:
        await message.answer("⚠️ E'lon topilmadi.")
        return

    photo = message.photo[-1] if message.photo else None
    if photo is None:
        return

    limit = _limit_of(data)
    try:
        await ad_service.add_photo(
            session,
            ad,
            file_id=photo.file_id,
            file_unique_id=photo.file_unique_id,
            width=photo.width,
            height=photo.height,
            limit=limit,
        )
    except ValueError:
        count = await ad_service.photo_count(session, ad.id)
        await message.answer(
            f"⚠️ Rasm limiti tugadi (<b>{limit}</b> ta).\n"
            "Davom etish uchun «✅ Tayyor» tugmasini bosing.",
            reply_markup=photos_kb(
                ad_id=ad.id, count=count, limit=limit, from_edit=flow == FLOW_EDIT
            ),
        )
        return

    count = await ad_service.photo_count(session, ad.id)
    await state.set_state(SellerAdStates.waiting_photos)
    await state.update_data(step="photos", photo_count=count, photo_limit=limit)

    await message.answer(
        f"🖼 Rasm qo'shildi.\n\n{ad_service.photos_line(count, limit)}",
        reply_markup=photos_kb(ad_id=ad.id, count=count, limit=limit, from_edit=flow == FLOW_EDIT),
    )


@router.message(StateFilter(SellerAdStates), F.text)
async def on_text_step(message: Message, session: AsyncSession, state: FSMContext) -> None:
    """Usta va tahrirlash matn qadamlari."""
    text = (message.text or "").strip()
    data = await state.get_data()
    ad_id = int(data.get("ad_id") or 0)
    step = str(data.get("step") or "title")
    flow = str(data.get("flow") or FLOW_WIZARD)
    page = int(data.get("page") or 0)
    status = str(data.get("status") or "all")

    if text in ("/cancel", "/bekor", "❌ Bekor qilish"):
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=back_to_ads_kb())
        return

    seller = await seller_service.get_seller(session, message.from_user.id if message.from_user else 0)
    if seller is None:
        return
    if not ad_id:
        await message.answer("⚠️ Avval e'lonni boshlang: «➕ Yangi e'lon».")
        return

    ad = await ad_service.get_ad(session, ad_id, seller_id=seller.id)
    if ad is None:
        await state.clear()
        await message.answer("⚠️ E'lon topilmadi.")
        return

    # ═══════════ Tahrirlash qadamlari ═══════════
    if step == "edit_title":
        if not await ad_service.set_title(session, ad, text):
            await message.answer("⚠️ Sarlavha juda qisqa. Kamida 3 belgi yozing.")
            return
        await ad_service.edited(session, ad)
        await _show_edit_menu(
            message, session, ad, page=page, status=status, note="✅ Sarlavha yangilandi."
        )
        return

    if step == "edit_desc":
        await ad_service.set_description(session, ad, "" if text == "-" else text)
        await ad_service.edited(session, ad)
        await _show_edit_menu(
            message, session, ad, page=page, status=status, note="✅ Tavsif yangilandi."
        )
        return

    if step == "edit_price":
        if text.lower() in ("kelishiladi", "kelishilgan", "narxsiz", "-"):
            await ad_service.set_price(session, ad, None)
        else:
            value = parse_price(text)
            if value is None:
                await message.answer(
                    "⚠️ Narxni tushunmadim. Faqat raqam yozing, masalan "
                    "<code>12500000</code>."
                )
                return
            if not await ad_service.set_price(session, ad, value):
                await message.answer("⚠️ Narx juda katta. Qaytadan kiriting.")
                return
        await ad_service.edited(session, ad)
        await _show_edit_menu(
            message, session, ad, page=page, status=status,
            note=f"✅ Narx: <b>{ad_service.format_ad_price(ad)}</b>",
        )
        return

    if step == "edit_contact":
        contact_type = str(data.get("contact_type") or ad.contact_type or "username")
        value = _contact_value(text, contact_type)
        if value is None:
            await message.answer(
                "⚠️ Qiymatni tushunmadim.\nMasalan: <code>@dokon_admin</code> yoki "
                "<code>+998901234567</code>"
            )
            return
        await ad_service.set_contact(session, ad, contact_type=contact_type, contact_value=value)
        await ad_service.edited(session, ad)
        await _show_edit_menu(
            message, session, ad, page=page, status=status, note="✅ Aloqa yangilandi."
        )
        return

    # ═══════════ Usta qadamlari ═══════════
    if step == "title":
        if not await ad_service.set_title(session, ad, text):
            await message.answer("⚠️ Sarlavha juda qisqa yoki bo'sh. Kamida 3 belgi yozing.")
            return
        await _show_step(message, state, "desc", ad_id=ad.id)
        return

    if step == "desc":
        await ad_service.set_description(session, ad, "" if text == "-" else text)
        await _show_step(message, state, "price", ad_id=ad.id)
        return

    if step == "price":
        if text.lower() in ("kelishiladi", "kelishilgan", "narxsiz", "-"):
            await ad_service.set_price(session, ad, None)
        else:
            value = parse_price(text)
            if value is None:
                await message.answer(
                    "⚠️ Narxni tushunmadim. Faqat raqam yozing, masalan "
                    "<code>12500000</code> yoki <code>kelishiladi</code>."
                )
                return
            if not await ad_service.set_price(session, ad, value):
                await message.answer("⚠️ Narx juda katta. Qaytadan kiriting.")
                return
        await _show_step(message, state, "contact", ad_id=ad.id)
        return

    if step == "contact":
        contact_type = str(data.get("contact_type") or "username")
        value = _contact_value(text, contact_type)
        if value is None:
            await message.answer(
                "⚠️ Telefon raqamni tushunmadim. Masalan: <code>+998901234567</code>"
            )
            return
        await ad_service.set_contact(session, ad, contact_type=contact_type, contact_value=value)
        count = await ad_service.photo_count(session, ad.id)
        await state.update_data(photo_count=count)
        await _show_step(message, state, "photos", ad_id=ad.id, count=count)
        return

    if step in ("photos", "preview"):
        limit = _limit_of(data)
        count = await ad_service.photo_count(session, ad.id)
        await message.answer(
            "🖼 Iltimos, rasm yuboring yoki «✅ Tayyor» tugmasini bosing.\n\n"
            f"{ad_service.photos_line(count, limit)}",
            reply_markup=photos_kb(
                ad_id=ad.id, count=count, limit=limit, from_edit=flow == FLOW_EDIT
            ),
        )
        return

    # Noma'lum qadam — boshidan davom ettiramiz
    await _show_step(message, state, "title", ad_id=ad.id)


# ═══════════════════════ Tahrirlash menyusi ════════════════════════
def _contact_value(text: str, contact_type: str) -> str | None:
    """Aloqa qiymatini turiga qarab normallashtirish."""
    if contact_type == "phone":
        return seller_service.normalize_phone(text)
    value = seller_service.normalize_contact(text) or text[:255]
    return value or None


@router.callback_query(AdCB.filter(F.action == "edit"))
async def on_edit(
    callback: CallbackQuery, callback_data: AdCB, session: AsyncSession, state: FSMContext
) -> None:
    """✏️ Tahrirlash menyusi."""
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return

    page, status = _parse_page_status(callback_data.value)
    await state.clear()
    await state.update_data(
        flow=FLOW_EDIT,
        ad_id=ad.id,
        step="edit",
        page=page,
        status=status,
        category_id=ad.category_id,
        contact_type=ad.contact_type,
        photo_limit=await ad_service.photo_limit(session, seller),
        photo_count=await ad_service.photo_count(session, ad.id),
    )
    await _show_edit_menu(callback, session, ad, page=page, status=status)
    await alert(callback, "")


@router.callback_query(AdCB.filter(F.action.in_(set(EDIT_FIELDS))))
async def on_edit_field(
    callback: CallbackQuery, callback_data: AdCB, session: AsyncSession, state: FSMContext
) -> None:
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return

    prompt, step = EDIT_FIELDS[callback_data.action]
    data = await state.get_data()
    await state.update_data(
        flow=FLOW_EDIT, ad_id=ad.id, step=step, contact_type=ad.contact_type, **{
            "page": data.get("page", 0), "status": data.get("status", "all")
        }
    )
    await state.set_state(STEP_STATES[step])
    await render(callback, prompt, wizard_step_kb(ad_id=ad.id, back=None))
    await alert(callback, "")


@router.callback_query(AdCB.filter(F.action == "e_cat"))
async def on_edit_category(
    callback: CallbackQuery, callback_data: AdCB, session: AsyncSession, state: FSMContext
) -> None:
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return

    categories = await _active_categories(session)
    if not categories:
        await alert(callback, "🗂 Faol toifa yo'q.", show=True)
        return

    data = await state.get_data()
    await state.update_data(
        flow=FLOW_EDIT,
        ad_id=ad.id,
        step="category",
        page=data.get("page", 0),
        status=data.get("status", "all"),
    )
    await state.set_state(SellerAdStates.waiting_category)
    await render(
        callback,
        "🗂 <b>Yangi toifa</b>\nE'lon shu toifa guruhiga joylanadi.",
        categories_kb(categories, ad_id=ad.id),
    )
    await alert(callback, "")


# ═══════════════════════════ Rasmlar ══════════════════════════════
@router.callback_query(AdCB.filter(F.action == "photos"))
async def on_photos(
    callback: CallbackQuery, callback_data: AdCB, session: AsyncSession, state: FSMContext
) -> None:
    """🖼 Rasmlarni tahrirlash: qo'shish / olib tashlash."""
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return

    limit = await ad_service.photo_limit(session, seller)
    count = await ad_service.photo_count(session, ad.id)
    page, status = _parse_page_status(callback_data.value)
    await state.update_data(
        flow=FLOW_EDIT,
        ad_id=ad.id,
        step="photos",
        page=page,
        status=status,
        photo_limit=limit,
        photo_count=count,
    )
    await state.set_state(SellerAdStates.waiting_photos)

    lines = [PHOTOS_PROMPT, "", ad_service.photos_line(count, limit)]
    if count:
        lines.append("<i>Ortiqcha rasmni «🗑 Oxirgisini o'chirish» bilan olib tashlang.</i>")

    await render(
        callback, "\n".join(lines), photos_kb(ad_id=ad.id, count=count, limit=limit, from_edit=True)
    )
    await alert(callback, "")


@router.callback_query(AdCB.filter(F.action == "photo_del"))
async def on_photo_delete(
    callback: CallbackQuery, callback_data: AdCB, session: AsyncSession, state: FSMContext
) -> None:
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return

    try:
        position = int(callback_data.value)
    except (TypeError, ValueError):
        position = 0

    removed = await ad_service.remove_photo(session, ad, position)
    data = await state.get_data()
    limit = _limit_of(data)
    count = await ad_service.photo_count(session, ad.id)
    await state.update_data(photo_count=count)

    head = "🗑 Rasm o'chirildi." if removed else "⚠️ Rasm topilmadi."
    await render(
        callback,
        f"{head}\n\n{ad_service.photos_line(count, limit)}",
        photos_kb(ad_id=ad.id, count=count, limit=limit, from_edit=True),
    )
    await alert(callback, "")


# ═══════════════════ Holat: pauza / yoqish / o'chirish ═════════════
@router.callback_query(AdCB.filter(F.action == "pause"))
async def on_pause(callback: CallbackQuery, callback_data: AdCB, session: AsyncSession) -> None:
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return

    if not await ad_service.pause(session, ad):
        await alert(callback, "⚠️ Faqat faol e'lonni to'xtatish mumkin.", show=True)
        return

    page, status = _parse_page_status(callback_data.value)
    await on_card(callback, AdCB(action="card", ad_id=ad.id, value=f"{page}|{status}"), session)
    await alert(callback, "⏸ To'xtatildi")


@router.callback_query(AdCB.filter(F.action == "resume"))
async def on_resume(callback: CallbackQuery, callback_data: AdCB, session: AsyncSession) -> None:
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return

    ok, reason = await subscription_service.can_publish(session, seller)
    if not ok:
        await alert(callback, reason, show=True)
        return

    if not await ad_service.resume(session, ad):
        await alert(callback, "⚠️ Bu e'lon pauzada emas.", show=True)
        return

    page, status = _parse_page_status(callback_data.value)
    await on_card(callback, AdCB(action="card", ad_id=ad.id, value=f"{page}|{status}"), session)
    await alert(callback, "▶️ Yana navbatda")


@router.callback_query(AdCB.filter(F.action == "delete"))
async def on_delete(callback: CallbackQuery, callback_data: AdCB, session: AsyncSession) -> None:
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return

    page, status = _parse_page_status(callback_data.value)
    await render(
        callback,
        "🗑 <b>E'lon o'chirilsinmi?</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 {escape_html(truncate(ad.title or '(nomsiz)', 50))}\n\n"
        "<i>E'lon navbatdan chiqariladi va obuna limitidan qaytariladi.</i>",
        ad_delete_confirm_kb(ad, page=page, status=status),
    )
    await alert(callback, "")


@router.callback_query(AdCB.filter(F.action == "delete_confirm"))
async def on_delete_confirm(
    callback: CallbackQuery, callback_data: AdCB, session: AsyncSession, state: FSMContext
) -> None:
    seller = await _seller(callback, session)
    if seller is None:
        return
    ad = await _own_ad(callback, session, seller, callback_data.ad_id)
    if ad is None:
        return

    page, status = _parse_page_status(callback_data.value)
    removed = await ad_service.soft_delete(session, seller, ad)
    await state.clear()
    await render_ads_list(callback, session, seller, page, status)
    await alert(callback, "🗑 O'chirildi" if removed else "⚠️ Allaqachon o'chirilgan")


# ═══════════ Sotuvchi panelidan chaqiriladigan funksiyalar ═════════
async def open_ads_list(callback: CallbackQuery, session: AsyncSession) -> None:
    """🛒 Panel → «📢 Mening e'lonlarim»."""
    seller = await _seller(callback, session)
    if seller is None:
        return
    await render_ads_list(callback, session, seller, 0, "all")
    await alert(callback, "")


async def start_ad_wizard(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    """🛒 Panel → «➕ Yangi e'lon»."""
    seller = await _seller(callback, session)
    if seller is None:
        return
    await _start_wizard(callback, session, seller, state)
    await alert(callback, "")


__all__ = ["open_ads_list", "render_ads_list", "router", "start_ad_wizard"]
