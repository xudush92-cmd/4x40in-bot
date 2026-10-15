"""Phase 4: navbatni ko'rish, tartibni o'zgartirish va qo'lda joylash."""

from __future__ import annotations

from math import ceil

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole, AdStatus
from app.db.models import ActionLog, Ad
from app.filters import IsAdmin
from app.keyboards.callbacks import PostingCB
from app.keyboards.common import PER_PAGE_ADS
from app.keyboards.posting import category_queue_kb, group_queue_kb
from app.scheduler.poster import post_group
from app.services import ad_service, category_service, group_service
from app.utils.text import escape_html, truncate
from app.utils.tg import alert, render
from app.utils.time import fmt_dt

router = Router(name="admin:posting")
router.callback_query.filter(PostingCB.filter(), IsAdmin())


async def render_group_queue(callback: CallbackQuery, session: AsyncSession, group_id: int) -> None:
    group = await group_service.get_group(session, group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    categories = await category_service.list_categories_for_group(session, group_id)
    text = (
        f"📋 <b>{escape_html(group.display)} — e'lon navbati</b>\n"
        "Toifani bosing — e'lonlar tartibi va navbat kursori ko'rinadi.\n"
        "⬆️⬇️ bilan tartibni o'zgartirish, 🚀 bilan darhol joylash mumkin."
    )
    if not categories:
        text += "\n\n📭 Bu guruhga toifa biriktirilmagan."
    await render(callback, text, group_queue_kb(group_id, categories))


async def render_category_queue(
    callback: CallbackQuery, session: AsyncSession, category_id: int, page: int = 0
) -> None:
    category = await category_service.get_category(session, category_id)
    if category is None or category.group_id is None:
        await alert(callback, "⚠️ Biriktirilgan toifa topilmadi.", show=True)
        return
    where = (Ad.category_id == category.id, Ad.status.in_((AdStatus.ACTIVE, AdStatus.PAUSED)))
    count = int((await session.execute(select(func.count()).select_from(Ad).where(*where))).scalar_one())
    pages = max(1, ceil(count / PER_PAGE_ADS))
    page = max(0, min(page, pages - 1))
    ads = list((await session.execute(
        select(Ad).where(*where).order_by(Ad.position, Ad.id)
        .limit(PER_PAGE_ADS).offset(page * PER_PAGE_ADS)
    )).scalars())
    cursor = category.rotation.cursor_ad_id if category.rotation else None
    lines = [
        f"📋 <b>{escape_html(category.name)} — navbat</b>",
        f"📦 {count} ta e'lon · sahifa {page + 1}/{pages}",
        f"📍 Oxirgi joylangan: #{cursor}" if cursor else "📍 Hali e'lon joylanmagan",
        f"⏱ Keyingi vaqt: {fmt_dt(category.rotation.next_post_at)}" if category.rotation else "",
        "",
    ]
    if not ads:
        lines.append("📭 Navbat bo'sh. E'lonlar tasdiqlansa shu yerda paydo bo'ladi.")
    else:
        for ad in ads:
            lines.append(
                f"{'🟢' if ad.status == AdStatus.ACTIVE else '⏸'} "
                f"<b>{ad.position}.</b> #{ad.id} {escape_html(truncate(ad.title, 45))}"
                + ("  📍" if ad.id == cursor else "")
            )
    await render(callback, "\n".join(lines), category_queue_kb(category, ads, page=page, pages=pages))


@router.callback_query(PostingCB.filter(F.action == "group"), IsAdmin(AdminRole.ADMIN))
async def on_group(callback: CallbackQuery, callback_data: PostingCB, session: AsyncSession) -> None:
    await render_group_queue(callback, session, callback_data.target_id)
    await alert(callback, "")


@router.callback_query(PostingCB.filter(F.action == "queue"), IsAdmin(AdminRole.ADMIN))
async def on_queue(callback: CallbackQuery, callback_data: PostingCB, session: AsyncSession) -> None:
    try:
        page = max(0, int(callback_data.value))
    except ValueError:
        page = 0
    await render_category_queue(callback, session, callback_data.target_id, page)
    await alert(callback, "")


@router.callback_query(PostingCB.filter(F.action.in_({"up", "down"})), IsAdmin(AdminRole.ADMIN))
async def on_move(callback: CallbackQuery, callback_data: PostingCB, session: AsyncSession) -> None:
    try:
        category_id, page = map(int, callback_data.value.split("|", 1))
    except ValueError:
        await alert(callback, "⚠️ Navbat parametri noto'g'ri.", show=True)
        return
    ad = await ad_service.get_ad(session, callback_data.target_id)
    if ad is None or ad.category_id != category_id:
        await alert(callback, "⚠️ E'lon boshqa toifada yoki o'chirilgan.", show=True)
        return
    before = ad.position
    moved = await ad_service.move(session, ad, callback_data.action)
    if moved:
        session.add(ActionLog(
            actor_id=callback.from_user.id, action="queue_move", entity="ad", entity_id=ad.id,
            group_id=ad.category.group_id if ad.category else None,
            before={"position": before}, after={"position": ad.position},
        ))
    await render_category_queue(callback, session, category_id, max(0, page))
    await alert(callback, "✅ Tartib o'zgardi" if moved else "Chegaraga yetildi")


@router.callback_query(PostingCB.filter(F.action == "send"), IsAdmin(AdminRole.ADMIN))
async def on_send(
    callback: CallbackQuery, callback_data: PostingCB, session: AsyncSession, bot: Bot
) -> None:
    ad = await ad_service.get_ad(session, callback_data.target_id)
    if ad is None or ad.category is None or ad.category.group_id is None:
        await alert(callback, "⚠️ E'lon/guruh topilmadi.", show=True)
        return
    group_id, ad_id = ad.category.group_id, ad.id
    # Middleware sessiyasidagi o'qish tranzaksiyasini ochiq qoldirmaymiz:
    # post_group o'z tranzaksiyasida claim'ni Telegram'dan OLDIN commit qiladi.
    await session.commit()
    result = await post_group(bot, group_id, force_ad_id=ad_id)
    session.add(ActionLog(
        actor_id=callback.from_user.id, action="post_now", entity="ad", entity_id=ad_id,
        group_id=group_id, after={"status": result.status, "message_ids": list(result.message_ids)},
    ))
    if result.status == "sent":
        await alert(callback, f"✅ E'lon #{ad_id} guruhga joylandi.", show=True)
    else:
        await alert(callback, f"⚠️ Joylanmadi ({result.status}): {result.detail[:130]}", show=True)


@router.callback_query()
async def on_denied(callback: CallbackQuery) -> None:
    # Router darajasida PostingCB + IsAdmin filtri bor; moderatorga yozishga ruxsat yo'q.
    await alert(callback, "⛔️ Navbatni faqat admin boshqaradi.", show=True)
