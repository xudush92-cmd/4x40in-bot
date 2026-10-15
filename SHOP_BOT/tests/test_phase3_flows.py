"""Phase 3: e'lon ustasi, «Mening e'lonlarim» va moderatsiya (E2E).

Haqiqiy `Dispatcher` + soxta Bot API. Sotuvchi tugmalarni bosib e'lon
yaratadi, rasm yuboradi, admin uni moderatsiyadan o'tkazadi.

Eslatma: handler sessiyasi test sessiyasidan alohida — shuning uchun
tekshirishdan oldin `session.expire_all()` qilib, yangi SELECT ishlatamiz.
"""

from __future__ import annotations

import itertools
from datetime import timedelta

import pytest_asyncio
from sqlalchemy import func, select

from app.constants import AdminRole, AdStatus, SellerStatus
from app.db.models import Ad, AdPhoto, Admin, Category, Group, ModerationLog, PostLog, Seller, Subscription
from app.keyboards.callbacks import AdCB, AdminCB, ModCB, SellerPanelCB
from app.services import ad_service, seller_service, subscription_service, tariff_service
from tests.fake_telegram import (
    ADMIN_ID,
    FakeSession,
    callback_update,
    make_bot,
    make_dispatcher,
    photo_update,
    reset_dispatcher_state,
    text_update,
)

SELLER_ID = 808080808
GROUP_CHAT_ID = -1007770001111

CB_SELLERS = SellerPanelCB(action="ads").pack()
CB_NEW_AD = SellerPanelCB(action="new_ad").pack()


@pytest_asyncio.fixture
async def tg(session):
    session.add(Admin(user_id=ADMIN_ID, role=AdminRole.SUPER))
    await session.commit()

    await reset_dispatcher_state()
    fake = FakeSession()
    bot = make_bot(fake)
    dp = make_dispatcher()
    yield fake, bot, dp
    await bot.session.close()
    await reset_dispatcher_state()


# ══════════════════════════ Tayyorgarlik ══════════════════════════
def _pk(obj) -> int:
    """Primary key'ni ORM yuklamasisiz olish.

    `session.expire_all()` dan keyin `obj.id` ga murojaat qilish sinxron
    lazy-load chaqiradi (`MissingGreenlet`) — shuning uchun testlarda ID
    shu yordamchi bilan olinadi.
    """
    from sqlalchemy import inspect as sa_inspect

    identity = sa_inspect(obj).identity
    assert identity is not None, "obyekt bazaga yozilmagan"
    return int(identity[0])


async def _feed(session, dp, bot, update_id: int, update) -> None:
    await dp.feed_update(bot, update)
    session.expire_all()


async def _cb(
    session,
    dp,
    bot,
    update_id: int,
    data: str,
    *,
    user_id: int = SELLER_ID,
) -> None:
    await _feed(session, dp, bot, update_id, callback_update(data, user_id=user_id))


async def _msg(session, dp, bot, update_id: int, text: str, *, user_id: int = SELLER_ID) -> None:
    await _feed(session, dp, bot, update_id, text_update(text, user_id=user_id))


async def _photo(
    session, dp, bot, update_id: int, file_id: str, *, user_id: int = SELLER_ID
) -> None:
    await _feed(session, dp, bot, update_id, photo_update(file_id=file_id, user_id=user_id))


async def _group(session, *, chat_id: int = GROUP_CHAT_ID) -> Group:
    group = (await session.execute(select(Group).where(Group.tg_chat_id == chat_id))).scalars().first()
    if group is None:
        group = Group(tg_chat_id=chat_id, title="Telefonlar bozori", is_active=True)
        session.add(group)
        await session.flush()
    return group


async def _category(
    session, *, name: str = "Telefonlar", moderation: bool = False, with_group: bool = True
) -> Category:
    group = await _group(session) if with_group else None
    category = Category(
        name=name,
        group_id=group.id if group else None,
        is_active=True,
        moderation_required=moderation,
        position=1000,
    )
    session.add(category)
    await session.flush()
    return category


async def _seller_with_tariff(
    session,
    *,
    user_id: int = SELLER_ID,
    max_ads: int = 5,
    max_photos: int = 3,
    name: str = "Do'kon",
) -> tuple[Seller, Subscription | None]:
    seller, _ = await seller_service.get_or_create_seller(
        session, user_id, display_name=name, phone="+998901112233", contact="@dokon"
    )
    tariff = await tariff_service.create_tariff(
        session, name=f"Tarif {max_photos}", price="400000", duration_days=30,
        max_ads=max_ads, max_photos=max_photos,
    )
    assert tariff is not None
    subscription = await subscription_service.grant(session, seller, tariff)
    seller.status = SellerStatus.ACTIVE
    await session.commit()
    return seller, subscription


async def _seller_record(session, user_id: int = SELLER_ID) -> Seller:
    return (
        await session.execute(select(Seller).where(Seller.user_id == user_id))
    ).scalar_one()


async def _ads(session) -> list[Ad]:
    return list(
        (await session.execute(select(Ad).order_by(Ad.id))).scalars().all()
    )


async def _only_ad(session) -> Ad:
    ads = await _ads(session)
    assert len(ads) == 1, f"bitta e'lon kutilgan edi, {len(ads)} ta topildi"
    return ads[0]


async def _subscription(session) -> Subscription:
    return (await session.execute(select(Subscription))).scalars().first()


async def _run_wizard(
    session,
    dp,
    bot,
    *,
    category_id: int,
    title: str = "iPhone 15 Pro Max 256GB",
    description: str = "Yangi, kafolat bilan",
    price: str = "12500000",
    photos: int = 1,
    start: int = 1,
    entry: str = CB_NEW_AD,
) -> int:
    """Usta oxirigacha bosib chiqiladi. Keyingi `update_id` qaytaradi."""
    n = start
    await _cb(session, dp, bot, n, entry)
    n += 1
    await _cb(session, dp, bot, n, AdCB(action="wiz_cat", value=str(category_id)).pack())
    n += 1
    await _msg(session, dp, bot, n, title)
    n += 1
    await _msg(session, dp, bot, n, description)
    n += 1
    await _msg(session, dp, bot, n, price)
    n += 1
    await _cb(session, dp, bot, n, AdCB(action="c_type", ad_id=1, value="username").pack())
    n += 1
    await _msg(session, dp, bot, n, "@dokon_admin")
    n += 1
    for index in range(photos):
        await _photo(session, dp, bot, n, file_id=f"photo-{index}")
        n += 1
    ad = await _only_ad(session)
    await _cb(session, dp, bot, n, AdCB(action="wiz_done", ad_id=_pk(ad)).pack())
    n += 1
    return n


# ═══════════════ 1. Usta: e'lon yaratish (avto-tasdiq) ═════════════
async def test_seller_creates_ad_and_it_goes_active(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    category = await _category(session, moderation=False)
    await session.commit()

    n = await _run_wizard(session, dp, bot, category_id=_pk(category))

    ad = await _only_ad(session)
    assert ad.status == AdStatus.DRAFT              # hali yuborilmagan
    assert ad.title == "iPhone 15 Pro Max 256GB"
    assert ad.description == "Yangi, kafolat bilan"
    assert str(ad.price) == "12500000.00"
    assert ad.contact_value == "@dokon_admin"
    assert await ad_service.photo_count(session, ad.id) == 1
    assert "E'lon ko'rinishi" in fake.edited_texts()[-1]

    # 📤 Yuborish
    await _cb(session, dp, bot, n, AdCB(action="wiz_send", ad_id=_pk(ad)).pack())

    ad = await _only_ad(session)
    assert ad.status == AdStatus.ACTIVE
    assert ad.approved_at is not None
    assert (await _subscription(session)).ads_used == 1
    assert any("faollashtirildi" in text for text in fake.edited_texts())


async def test_seller_edits_and_resubmits_rejected_ad(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session, max_photos=2)
    category = await _category(session, moderation=True)
    await session.commit()

    n = await _run_wizard(session, dp, bot, category_id=_pk(category))
    ad = await _only_ad(session)
    await _cb(session, dp, bot, n, AdCB(action="wiz_send", ad_id=_pk(ad)).pack())
    n += 1

    # Moderatsiya talab qilingani uchun — 🕓 kutish holatida
    ad = await _only_ad(session)
    assert ad.status == AdStatus.PENDING
    assert "tekshiruvga yuborildi" in fake.edited_texts()[-1]

    # Sayt egasi rad etadi (boshqa testda to'liq; bu yerda servis orqali)
    seller = await _seller_record(session)
    await ad_service.reject(session, seller, ad, ADMIN_ID, "Rasm sifatsiz")
    await session.commit()

    # Sotuvchi tahrirlaydi → qoralama bo'ladi
    await _cb(session, dp, bot, n, AdCB(action="card", ad_id=_pk(ad), value="0|all").pack())
    n += 1
    assert "Rad etish sababi" in fake.edited_texts()[-1]

    await _cb(session, dp, bot, n, AdCB(action="edit", ad_id=_pk(ad), value="0|all").pack())
    n += 1
    await _cb(session, dp, bot, n, AdCB(action="e_title", ad_id=_pk(ad), value="0|all").pack())
    n += 1
    await _msg(session, dp, bot, n, "iPhone 15 Pro Max (yangilangan)")
    n += 1

    ad = await _only_ad(session)
    assert ad.status == AdStatus.DRAFT
    assert ad.reject_reason is None
    assert "Sarlavha yangilandi" in fake.sent_texts()[-1]

    # Qayta yuborish → yana 🕓
    await _cb(session, dp, bot, n, AdCB(action="send", ad_id=_pk(ad)).pack())
    session.expire_all()
    assert (await _only_ad(session)).status == AdStatus.PENDING


async def test_seller_wizard_requires_photo(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    category = await _category(session)
    await session.commit()

    await _cb(session, dp, bot, 1, CB_NEW_AD)
    await _cb(session, dp, bot, 2, AdCB(action="wiz_cat", value=str(_pk(category))).pack())
    await _msg(session, dp, bot, 3, "Sarlavha")
    await _msg(session, dp, bot, 4, "-")
    await _msg(session, dp, bot, 5, "1000")

    ad = await _only_ad(session)
    await _cb(session, dp, bot, 6, AdCB(action="wiz_done", ad_id=_pk(ad)).pack())

    assert any("Kamida bitta rasm" in answer for answer in fake.answers())
    assert (await _only_ad(session)).status == AdStatus.DRAFT


async def test_seller_wizard_skips_optional_steps(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    category = await _category(session)
    await session.commit()

    await _cb(session, dp, bot, 1, CB_NEW_AD)
    await _cb(session, dp, bot, 2, AdCB(action="wiz_cat", value=str(_pk(category))).pack())
    await _msg(session, dp, bot, 3, "Noutbuk")
    ad = await _only_ad(session)

    # ⏭ Tavsifni o'tkazib yuborish
    await _cb(session, dp, bot, 4, AdCB(action="wiz_skip", ad_id=_pk(ad)).pack())
    await _msg(session, dp, bot, 5, "5000000")

    # ⏭ Aloqani o'tkazib yuborish → profildagi @dokon ishlatiladi
    await _cb(session, dp, bot, 6, AdCB(action="wiz_skip", ad_id=_pk(ad)).pack())

    ad = await _only_ad(session)
    assert ad.description is None
    assert ad.contact_type == "username"
    assert ad.contact_value == "@dokon"

    await _photo(session, dp, bot, 7, "p1")
    await _cb(session, dp, bot, 8, AdCB(action="wiz_done", ad_id=_pk(ad)).pack())
    await _cb(session, dp, bot, 9, AdCB(action="wiz_send", ad_id=_pk(ad)).pack())

    session.expire_all()
    assert (await _only_ad(session)).status == AdStatus.ACTIVE


async def test_seller_backs_up_a_step(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    category = await _category(session)
    await session.commit()

    await _cb(session, dp, bot, 1, CB_NEW_AD)
    await _cb(session, dp, bot, 2, AdCB(action="wiz_cat", value=str(_pk(category))).pack())
    await _msg(session, dp, bot, 3, "Birinchi sarlavha")
    ad = await _only_ad(session)

    # ⬅️ Orqaga → yana sarlavha so'raladi
    await _cb(session, dp, bot, 4, AdCB(action="wiz_back", ad_id=_pk(ad), value="title").pack())
    assert "sarlavhasi" in fake.edited_texts()[-1].lower()

    await _msg(session, dp, bot, 5, "Ikkinchi sarlavha")
    assert (await _only_ad(session)).title == "Ikkinchi sarlavha"


async def test_wizard_cancel_keeps_draft_and_removes_empty(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    category = await _category(session)
    await session.commit()

    # 1) Toifa tanlandi, hali hech narsa yozilmadi → qoralama o'chiriladi
    await _cb(session, dp, bot, 1, CB_NEW_AD)
    await _cb(session, dp, bot, 2, AdCB(action="wiz_cat", value=str(_pk(category))).pack())
    ad = await _only_ad(session)
    await _cb(session, dp, bot, 3, AdCB(action="wiz_cancel", ad_id=_pk(ad)).pack())
    assert await _ads(session) == []

    # 2) Sarlavha yozildi → qoralama saqlanadi
    await _cb(session, dp, bot, 4, CB_NEW_AD)
    await _cb(session, dp, bot, 5, AdCB(action="wiz_cat", value=str(_pk(category))).pack())
    await _msg(session, dp, bot, 6, "Saqlanadigan e'lon")
    ad = await _only_ad(session)
    await _cb(session, dp, bot, 7, AdCB(action="wiz_cancel", ad_id=_pk(ad)).pack())

    ads = await _ads(session)
    assert len(ads) == 1 and ads[0].status == AdStatus.DRAFT
    assert "qoralama" in fake.edited_texts()[-1].lower()


async def test_wizard_hidden_without_subscription(session, tg) -> None:
    fake, bot, dp = tg
    seller, _ = await seller_service.get_or_create_seller(session, SELLER_ID, display_name="Do'kon")
    seller.status = SellerStatus.ACTIVE              # tarif yo'q
    category = await _category(session)
    await session.commit()

    await _cb(session, dp, bot, 1, CB_NEW_AD)

    assert await _ads(session) == []
    assert any("tarif" in answer.lower() for answer in fake.answers())


async def test_wizard_without_ready_category(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    await _category(session, with_group=False)       # guruhga biriktirilmagan
    await session.commit()

    await _cb(session, dp, bot, 1, CB_NEW_AD)

    assert await _ads(session) == []
    assert any("faol toifa yo'q" in answer for answer in fake.answers())


async def test_photo_limit_stops_extra_photos(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session, max_photos=1)
    category = await _category(session)
    await session.commit()

    await _cb(session, dp, bot, 1, CB_NEW_AD)
    await _cb(session, dp, bot, 2, AdCB(action="wiz_cat", value=str(_pk(category))).pack())
    await _msg(session, dp, bot, 3, "Bir rasmli e'lon")
    await _msg(session, dp, bot, 4, "-")
    await _msg(session, dp, bot, 5, "1000")
    await _cb(session, dp, bot, 6, AdCB(action="wiz_skip", ad_id=1).pack())

    ad_id = _pk(await _only_ad(session))
    await _photo(session, dp, bot, 7, "p1")
    await _photo(session, dp, bot, 8, "p2")          # limitdan oshiq

    assert await ad_service.photo_count(session, ad_id) == 1
    assert any("Rasm limiti tugadi" in text for text in fake.sent_texts())


# ═══════════════ 2. «Mening e'lonlarim» (kartochka) ════════════════
async def _make_active_ad(session, *, title: str = "Faol e'lon") -> Ad:
    seller = await _seller_record(session)
    category = (await session.execute(select(Category))).scalars().first()
    assert category is not None
    ad = await ad_service.create_draft(session, seller, category)
    await ad_service.set_title(session, ad, title)
    await ad_service.set_price(session, ad, 1000)
    await ad_service.add_photo(session, ad, file_id="seed-photo")
    await ad_service.submit(session, seller, ad)
    await session.commit()
    return ad


async def test_panel_opens_ads_list(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    await _category(session)
    await _make_active_ad(session, title="IPhone 14")

    await _cb(session, dp, bot, 1, CB_SELLERS)

    text = fake.edited_texts()[-1]
    assert "Mening e'lonlarim" in text
    assert "IPhone 14" in text
    assert "🟢 Faol: <b>1</b>" in text

    # Kartochka
    ad = await _only_ad(session)
    await _cb(session, dp, bot, 2, AdCB(action="card", ad_id=_pk(ad), value="0|all").pack())
    card = fake.edited_texts()[-1]
    assert "Telefonlar" in card
    assert "1 000 so'm" in card
    assert "@dokon" in card


async def test_ads_list_filters(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    await _category(session)
    await _make_active_ad(session)

    await _cb(session, dp, bot, 1, AdCB(action="filter", value="draft").pack())
    assert "Bu filtrda e'lon yo'q" in fake.edited_texts()[-1]
    assert "✏️ Qoralama" in fake.edited_texts()[-1]

    await _cb(session, dp, bot, 2, AdCB(action="filter", value="active").pack())
    assert "Faol e'lon" in fake.edited_texts()[-1]


async def test_pause_resume_and_delete_ad(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    await _category(session)
    ad = await _make_active_ad(session)
    ad_id = _pk(ad)

    await _cb(session, dp, bot, 1, AdCB(action="pause", ad_id=ad_id, value="0|all").pack())
    session.expire_all()
    assert (await session.get(Ad, ad_id)).status == AdStatus.PAUSED
    assert "To'xtatilgan" in fake.edited_texts()[-1]

    await _cb(session, dp, bot, 2, AdCB(action="resume", ad_id=ad_id, value="0|all").pack())
    session.expire_all()
    assert (await session.get(Ad, ad_id)).status == AdStatus.ACTIVE

    # O'chirish: tasdiq ekrani → tasdiq
    await _cb(session, dp, bot, 3, AdCB(action="delete", ad_id=ad_id, value="0|all").pack())
    assert "o'chirilsinmi" in fake.edited_texts()[-1]

    await _cb(session, dp, bot, 4, AdCB(action="delete_confirm", ad_id=ad_id, value="0|all").pack())
    session.expire_all()
    assert (await session.get(Ad, ad_id)).status == AdStatus.DELETED
    assert (await _subscription(session)).ads_used == 0      # limit qaytarildi


async def test_photo_edit_add_and_remove(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session, max_photos=3)
    await _category(session)
    ad = await _make_active_ad(session)
    ad_id = _pk(ad)

    await _cb(session, dp, bot, 1, AdCB(action="photos", ad_id=ad_id, value="0|all").pack())
    assert "1/3" in fake.edited_texts()[-1]

    await _photo(session, dp, bot, 2, "p2")
    await _photo(session, dp, bot, 3, "p3")
    assert await ad_service.photo_count(session, ad_id) == 3

    await _cb(session, dp, bot, 4, AdCB(action="photo_del", ad_id=ad_id, value="2").pack())
    assert await ad_service.photo_count(session, ad_id) == 2
    assert "o'chirildi" in fake.edited_texts()[-1]


async def test_ad_stats_screen(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    await _category(session)
    ad = await _make_active_ad(session)
    session.add(
        PostLog(group_id=GROUP_CHAT_ID, ad_id=_pk(ad), status="ok", category_id=ad.category_id)
    )
    await session.commit()

    await _cb(session, dp, bot, 1, AdCB(action="stats", ad_id=_pk(ad), value="0|all").pack())

    text = fake.edited_texts()[-1]
    assert "Joylashlar soni" in text
    assert "Qamrab olingan guruhlar: <b>1</b>" in text


async def test_stranger_cannot_open_seller_ad(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    await _category(session)
    ad = await _make_active_ad(session)
    session.add(Admin(user_id=999999, role=AdminRole.MODERATOR))
    await session.commit()

    # Boshqa foydalanuvchi (sotuvchi emas) — router uni o'tkazib yuboradi
    await _cb(session, dp, bot, 1, AdCB(action="card", ad_id=_pk(ad)).pack(), user_id=999999)
    assert fake.edited_texts() == []


# ═══════════════════ 3. Moderatsiya (admin) ════════════════════════
async def _submit_pending_ad(session, *, title: str = "Tekshiriladigan e'lon") -> Ad:
    """Moderatsiya talab qiladigan toifada e'lon yuboradi (🕓 holatda qoladi)."""
    seller = await _seller_record(session)
    category = (
        await session.execute(select(Category).where(Category.moderation_required.is_(True)))
    ).scalars().first()
    assert category is not None, "moderatsiyali toifa yo'q"
    ad = await ad_service.create_draft(session, seller, category)
    await ad_service.set_title(session, ad, title)
    await ad_service.set_price(session, ad, 5000000)
    await ad_service.add_photo(session, ad, file_id="mod-photo", file_unique_id="mod-uq")
    ok, state = await ad_service.submit(session, seller, ad)
    assert ok and state == AdStatus.PENDING
    await session.commit()
    return ad


async def test_admin_panel_opens_ads_and_moderation(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    await _category(session, moderation=True)
    await _submit_pending_ad(session)

    await _cb(session, dp, bot, 1, AdminCB(action="section", value="moderation").pack(), user_id=ADMIN_ID)
    text = fake.edited_texts()[-1]
    assert "Moderatsiya" in text
    assert "Kutilmoqda: <b>1</b>" in text
    assert "Tekshiriladigan e'lon" in text

    await _cb(session, dp, bot, 2, AdminCB(action="section", value="ads").pack(), user_id=ADMIN_ID)
    assert "📢 <b>E'lonlar</b>" in fake.edited_texts()[-1]

    # Bu bo'limlar endi tayyor — "Phase" ogohlantirishi chiqmasin
    assert not any("Phase" in answer for answer in fake.answers())


async def test_admin_approves_ad(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    await _category(session, moderation=True)
    ad = await _submit_pending_ad(session)
    ad_id = _pk(ad)

    await _cb(session, dp, bot, 1, ModCB(action="list", value="0|pending").pack(), user_id=ADMIN_ID)
    assert "Tekshiriladigan e'lon" in fake.edited_texts()[-1]

    await _cb(session, dp, bot, 2, ModCB(action="card", ad_id=ad_id, value="0|pending").pack(), user_id=ADMIN_ID)
    card = fake.edited_texts()[-1]
    assert "Do'kon" in card                       # sotuvchi nomi
    assert "5 000 000 so'm" in card
    assert fake.called("SendPhoto") or fake.called("SendMediaGroup")

    await _cb(session, dp, bot, 3, ModCB(action="approve", ad_id=ad_id, value="0|pending").pack(), user_id=ADMIN_ID)

    session.expire_all()
    approved = await session.get(Ad, ad_id)
    assert approved.status == AdStatus.ACTIVE
    assert approved.approved_by == ADMIN_ID
    assert await ad_service.count_pending(session) == 0
    assert any("tasdiqlandi" in text for text in fake.sent_texts())     # sotuvchiga xabar
    assert "Kutilmoqda: <b>0</b>" in fake.edited_texts()[-1]

    history = (
        await session.execute(select(ModerationLog).where(ModerationLog.ad_id == ad_id))
    ).scalars().all()
    assert [row.decision for row in history] == ["approved"]


async def test_admin_rejects_ad_with_preset_reason(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    await _category(session, moderation=True)
    ad = await _submit_pending_ad(session)
    ad_id = _pk(ad)

    await _cb(session, dp, bot, 1, ModCB(action="reject", ad_id=ad_id, value="0|pending").pack(), user_id=ADMIN_ID)
    assert "Rad etish sababi" in fake.edited_texts()[-1]

    await _cb(
        session, dp, bot, 2,
        ModCB(action="reason", ad_id=ad_id, value="spam|0").pack(),
        user_id=ADMIN_ID,
    )

    session.expire_all()
    rejected = await session.get(Ad, ad_id)
    assert rejected.status == AdStatus.REJECTED
    assert "spam" in (rejected.reject_reason or "")
    assert (await _subscription(session)).ads_used == 0        # limit qaytarildi
    assert any("rad etildi" in text.lower() for text in fake.sent_texts())


async def test_admin_rejects_ad_with_custom_reason(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    await _category(session, moderation=True)
    ad = await _submit_pending_ad(session)
    ad_id = _pk(ad)

    await _cb(session, dp, bot, 1, ModCB(action="reject", ad_id=ad_id, value="0|pending").pack(), user_id=ADMIN_ID)
    await _cb(session, dp, bot, 2, ModCB(action="reason", ad_id=ad_id, value="other|0").pack(), user_id=ADMIN_ID)
    await _msg(session, dp, bot, 3, "Rasm sifati past, qayta yuklang", user_id=ADMIN_ID)

    session.expire_all()
    rejected = await session.get(Ad, ad_id)
    assert rejected.status == AdStatus.REJECTED
    assert "Rasm sifati past" in (rejected.reject_reason or "")
    assert await ad_service.count_pending(session) == 0


async def test_admin_ads_section_filters_and_pauses(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    await _category(session, moderation=False)
    await _make_active_ad(session, title="Bozordagi e'lon")

    await _cb(session, dp, bot, 1, ModCB(action="ads", value="0|active").pack(), user_id=ADMIN_ID)
    text = fake.edited_texts()[-1]
    assert "Bozordagi e'lon" in text
    assert "ko'rsatilgan: <b>1</b>" in text

    ad_id = _pk(await _only_ad(session))
    await _cb(
        session, dp, bot, 2,
        ModCB(action="ads_card", ad_id=ad_id, value="0|active").pack(),
        user_id=ADMIN_ID,
    )
    assert "Bozordagi e'lon" in fake.edited_texts()[-1]

    await _cb(session, dp, bot, 3, ModCB(action="pause", ad_id=ad_id, value="0|active").pack(), user_id=ADMIN_ID)
    session.expire_all()
    assert (await session.get(Ad, ad_id)).status == AdStatus.PAUSED
    assert any("to'xtatildi" in text for text in fake.sent_texts())

    await _cb(session, dp, bot, 4, ModCB(action="resume", ad_id=ad_id, value="0|paused").pack(), user_id=ADMIN_ID)
    session.expire_all()
    assert (await session.get(Ad, ad_id)).status == AdStatus.ACTIVE


async def test_admin_deletes_ad_and_returns_slot(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    await _category(session)
    ad = await _make_active_ad(session)
    ad_id = _pk(ad)

    await _cb(session, dp, bot, 1, ModCB(action="delete", ad_id=ad_id, value="0|active").pack(), user_id=ADMIN_ID)
    assert "o'chirilsinmi" in fake.edited_texts()[-1]

    await _cb(
        session, dp, bot, 2, ModCB(action="delete_confirm", ad_id=ad_id, value="0|active").pack(),
        user_id=ADMIN_ID,
    )
    session.expire_all()
    assert (await session.get(Ad, ad_id)).status == AdStatus.DELETED
    assert (await _subscription(session)).ads_used == 0


async def test_admin_moderation_history(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    await _category(session, moderation=True)
    ad = await _submit_pending_ad(session)
    ad_id = _pk(ad)

    await _cb(session, dp, bot, 1, ModCB(action="approve", ad_id=ad_id, value="0|pending").pack(), user_id=ADMIN_ID)
    await _cb(session, dp, bot, 2, ModCB(action="history", ad_id=ad_id, value="0|active").pack(), user_id=ADMIN_ID)

    text = fake.edited_texts()[-1]
    assert "Moderatsiya tarixi" in text
    assert "Tasdiqlangan" in text


async def test_other_seller_cannot_touch_foreign_ad(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    await _seller_with_tariff(session, user_id=SELLER_ID + 1, name="Boshqa do'kon")
    await _category(session)
    ad = await _make_active_ad(session)
    ad_id = _pk(ad)

    await _cb(session, dp, bot, 1, AdCB(action="delete", ad_id=ad_id).pack(), user_id=SELLER_ID + 1)
    assert any("E'lon topilmadi" in answer for answer in fake.answers())
    assert (await session.get(Ad, ad_id)).status == AdStatus.ACTIVE


# ═══════════════ 4. Panel va callback chegaralari ══════════════════
async def test_seller_menu_shows_ads_counter(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    await _category(session)
    await _make_active_ad(session)

    await _cb(session, dp, bot, 1, SellerPanelCB(action="menu").pack())

    markup = fake.called("EditMessageText")[-1]["reply_markup"]
    labels = [button["text"] for row in markup["inline_keyboard"] for button in row]
    assert any(label.startswith("📢 Mening e'lonlarim (1)") for label in labels)
    assert any("Yangi e'lon" in label for label in labels)


async def test_expired_subscription_blocks_new_ad(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session)
    await _category(session)
    subscription = await _subscription(session)
    subscription.expires_at = subscription.starts_at - timedelta(days=1)
    await session.commit()

    await _cb(session, dp, bot, 1, CB_NEW_AD)

    assert await _ads(session) == []
    assert any("muddati" in answer.lower() for answer in fake.answers())


def test_ad_callbacks_fit_telegram_limit() -> None:
    payloads = [
        AdCB(action="wiz_cat", ad_id=123456, value="7890").pack(),
        AdCB(action="delete_confirm", ad_id=123456, value="12|rejected").pack(),
        AdCB(action="e_contact", ad_id=123456, value="3|paused").pack(),
        ModCB(action="reason", ad_id=123456, value="complaints|12").pack(),
        ModCB(action="delete_confirm", ad_id=123456, value="3|archived").pack(),
    ]
    for payload in payloads:
        assert len(payload.encode()) <= 64, payload


async def test_photo_counter_in_list_matches_db(session, tg) -> None:
    fake, bot, dp = tg
    await _seller_with_tariff(session, max_photos=3)
    await _category(session)
    ad = await _make_active_ad(session)

    await ad_service.add_photo(session, ad, file_id="second")
    await session.commit()

    await _cb(session, dp, bot, 1, AdCB(action="list", value="0|all").pack())
    assert "🖼 2 ta" in fake.edited_texts()[-1]

    total_photos = (await session.execute(select(func.count()).select_from(AdPhoto))).scalar_one()
    assert total_photos == 2
