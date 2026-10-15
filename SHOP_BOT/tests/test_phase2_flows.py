"""Phase 2: sotuvchi/tarif/obuna oqimlarining E2E sinovi.

Haqiqiy `Dispatcher` + soxta Bot API: admin sotuvchi qo'shadi, tarif yaratadi,
tarif beradi, sotuvchi o'z panelida holatni ko'radi, bloklangan sotuvchi
kira olmaydi, eslatma va muddat job'lari ishlaydi.

Eslatma: test o'z session'ida yozadi, handler esa alohida session'da — shuning
uchun `commit()`dan keyin **ID'larni oldindan olib qo'yamiz** (expire bo'lgan
obyektga murojaat `MissingGreenlet` beradi) va o'qishni yangi SELECT bilan
qilamiz.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest_asyncio
from sqlalchemy import select

from app.constants import AdminRole, SellerStatus, SubscriptionStatus
from app.db.models import Ad, Admin, Category, Seller, Subscription, Tariff
from app.keyboards.callbacks import AdminCB, SellerCB, SellerPanelCB, TariffCB
from app.scheduler.jobs import expire_subscriptions_job, subscription_reminders_job
from app.services import seller_service, subscription_service, tariff_service
from app.services.settings_service import settings_service
from app.utils.time import utcnow
from tests.fake_telegram import (
    ADMIN_ID,
    FakeSession,
    callback_update,
    make_bot,
    make_dispatcher,
    reset_dispatcher_state,
    text_update,
)

SELLER_ID = 909090909
CB_SELLERS = SellerCB(action="list", value="0|all").pack()
CB_TARIFFS = TariffCB(action="list", value="0").pack()


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


async def _feed(session, dp, bot, update_id: int, update) -> None:
    await dp.feed_update(bot, update)
    session.expire_all()


async def _seller(session) -> Seller:
    return (await session.execute(select(Seller).where(Seller.user_id == SELLER_ID))).scalar_one()


async def _tariff(session, name: str) -> Tariff:
    return (await session.execute(select(Tariff).where(Tariff.name == name))).scalar_one()


async def _subscription(session) -> Subscription:
    return (await session.execute(select(Subscription))).scalars().first()


async def _prepare(
    session,
    *,
    name: str = "Do'kon",
    user_id: int = SELLER_ID,
    tariff_kwargs: dict[str, Any] | None = None,
    grant: bool = False,
) -> tuple[int, int | None, int | None]:
    """Sotuvchi (+ tarif, + obuna) tayyorlab, ularning ID'larini qaytaradi."""
    seller, _ = await seller_service.get_or_create_seller(session, user_id, display_name=name)
    await session.flush()
    seller_id = seller.id

    tariff_id = subscription_id = None
    if tariff_kwargs is not None:
        tariff = await tariff_service.create_tariff(session, **tariff_kwargs)
        assert tariff is not None
        await session.flush()
        tariff_id = tariff.id
        if grant:
            subscription = await subscription_service.grant(session, seller, tariff)
            subscription_id = subscription.id

    await session.commit()
    return seller_id, tariff_id, subscription_id


# ═══════════════ 1. Admin: sotuvchini qo'shish (FSM) ═══════════════
async def test_admin_adds_seller_via_fsm(session, tg) -> None:
    fake, bot, dp = tg

    await _feed(session, dp, bot, 1, callback_update(CB_SELLERS))
    assert "Sotuvchilar" in fake.edited_texts()[-1]
    assert "Hech narsa topilmadi" in fake.edited_texts()[-1]

    # ➕ Sotuvchi qo'shish
    await _feed(session, dp, bot, 2, callback_update(SellerCB(action="add").pack()))
    assert "Telegram ID" in fake.edited_texts()[-1]

    # Noto'g'ri ID
    await _feed(session, dp, bot, 3, text_update("salom"))
    assert "Faqat raqam" in fake.sent_texts()[-1]

    # To'g'ri ID → ism → telefon → kontakt
    await _feed(session, dp, bot, 4, text_update(str(SELLER_ID)))
    await _feed(session, dp, bot, 5, text_update("📱 Telefon do'koni"))
    await _feed(session, dp, bot, 6, text_update("+998 (90) 111-22-33"))
    await _feed(session, dp, bot, 7, text_update("@telefon_dokoni"))

    seller = await _seller(session)
    assert seller.display_name == "📱 Telefon do'koni"
    assert seller.phone == "+998901112233"
    assert seller.contact == "@telefon_dokoni"
    assert seller.status == SellerStatus.PENDING
    assert seller.added_by == ADMIN_ID
    assert seller.referral_code
    assert any("qo'shildi" in text for text in fake.sent_texts())


async def test_admin_cannot_add_same_seller_twice(session, tg) -> None:
    fake, bot, dp = tg
    await _feed(session, dp, bot, 1, callback_update(SellerCB(action="add").pack()))
    await _feed(session, dp, bot, 2, text_update(str(SELLER_ID)))
    await _feed(session, dp, bot, 3, text_update("Do'kon"))
    await _feed(session, dp, bot, 4, text_update("-"))
    await _feed(session, dp, bot, 5, text_update("-"))

    await _feed(session, dp, bot, 6, callback_update(SellerCB(action="add").pack()))
    await _feed(session, dp, bot, 7, text_update(str(SELLER_ID)))

    assert any("allaqachon sotuvchi" in text for text in fake.sent_texts())


# ═══════════ 2. Admin: tarif yaratish va tahrirlash ═══════════════
async def test_admin_creates_tariff(session, tg) -> None:
    fake, bot, dp = tg

    await _feed(session, dp, bot, 1, callback_update(CB_TARIFFS))
    assert "Tarif yo'q" in fake.edited_texts()[-1]

    await _feed(session, dp, bot, 2, callback_update(TariffCB(action="create").pack()))
    assert "tarif nomini" in fake.edited_texts()[-1].lower()

    await _feed(session, dp, bot, 3, text_update("🟢 Boshlang'ich"))
    await _feed(session, dp, bot, 4, text_update("150 000 so'm"))
    await _feed(session, dp, bot, 5, text_update("30"))
    await _feed(session, dp, bot, 6, text_update("3"))
    await _feed(session, dp, bot, 7, text_update("2"))

    tariff = await _tariff(session, "🟢 Boshlang'ich")
    assert tariff.price == Decimal("150000.00")
    assert tariff.duration_days == 30
    assert tariff.max_ads == 3
    assert tariff.max_photos == 2
    assert any("yaratildi" in text for text in fake.sent_texts())


async def test_admin_tariff_validation_and_edit(session, tg) -> None:
    fake, bot, dp = tg
    await _feed(session, dp, bot, 1, callback_update(TariffCB(action="create").pack()))
    await _feed(session, dp, bot, 2, text_update("Test tarif"))
    await _feed(session, dp, bot, 3, text_update("100000"))
    await _feed(session, dp, bot, 4, text_update("99999"))   # muddat chegaradan tashqari
    assert "1–3650" in fake.sent_texts()[-1]

    await _feed(session, dp, bot, 5, text_update("30"))
    await _feed(session, dp, bot, 6, text_update("5"))
    await _feed(session, dp, bot, 7, text_update("99"))       # rasm chegaradan tashqari
    assert "1–10" in fake.sent_texts()[-1]

    await _feed(session, dp, bot, 8, text_update("3"))
    tariff = await _tariff(session, "Test tarif")
    tariff_id = tariff.id

    # Narxni tahrirlash
    await _feed(session, dp, bot, 9, callback_update(TariffCB(action="price", tariff_id=tariff_id).pack()))
    await _feed(session, dp, bot, 10, text_update("250 000"))
    session.expire_all()
    assert (await _tariff(session, "Test tarif")).price == Decimal("250000.00")

    # Nomni tahrirlash
    await _feed(session, dp, bot, 11, callback_update(TariffCB(action="rename", tariff_id=tariff_id).pack()))
    await _feed(session, dp, bot, 12, text_update("Premium tarif"))
    assert (await _tariff(session, "Premium tarif")).id == tariff_id

    # Limitni tahrirlash
    await _feed(session, dp, bot, 13, callback_update(TariffCB(action="ads", tariff_id=tariff_id).pack()))
    await _feed(session, dp, bot, 14, text_update("25"))
    session.expire_all()
    assert (await _tariff(session, "Premium tarif")).max_ads == 25

    # Faol/pauza
    await _feed(session, dp, bot, 15, callback_update(TariffCB(action="active", tariff_id=tariff_id).pack()))
    session.expire_all()
    assert (await _tariff(session, "Premium tarif")).is_active is False

    # Sinov belgisi
    await _feed(session, dp, bot, 16, callback_update(TariffCB(action="trial", tariff_id=tariff_id).pack()))
    session.expire_all()
    assert (await _tariff(session, "Premium tarif")).is_trial is True

    # Bekor qilish (/cancel) — kartochkaga qaytadi
    await _feed(session, dp, bot, 17, callback_update(TariffCB(action="desc", tariff_id=tariff_id).pack()))
    await _feed(session, dp, bot, 18, text_update("/cancel"))
    assert "Premium tarif" in fake.sent_texts()[-1]


async def test_admin_tariff_delete_with_subscription_only_deactivates(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, tariff_id, _ = await _prepare(
        session, tariff_kwargs={"name": "Band tarif", "max_ads": 5}, grant=True
    )
    assert tariff_id is not None and seller_id

    await _feed(session, dp, bot, 1, callback_update(TariffCB(action="delete", tariff_id=tariff_id).pack()))
    assert "to'xtatiladi" in fake.edited_texts()[-1]

    await _feed(
        session, dp, bot, 2, callback_update(TariffCB(action="delete_confirm", tariff_id=tariff_id).pack())
    )
    session.expire_all()
    tariff = await session.get(Tariff, tariff_id)
    assert tariff is not None            # yozuv saqlandi
    assert tariff.is_active is False


# ═══════════ 3. Admin: tarif berish, uzaytirish, bloklash ═════════
async def test_admin_grants_tariff_and_seller_is_notified(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, tariff_id, _ = await _prepare(
        session,
        tariff_kwargs={
            "name": "Biznes",
            "price": "400000",
            "duration_days": 30,
            "max_ads": 10,
            "max_photos": 5,
        },
    )
    assert tariff_id is not None

    # «Tarif berish» → tarif tanlash → berish
    await _feed(session, dp, bot, 1, callback_update(SellerCB(action="grant", seller_id=seller_id).pack()))
    assert "tarif tanlang" in fake.edited_texts()[-1]

    await _feed(
        session,
        dp,
        bot,
        2,
        callback_update(SellerCB(action="grant_tariff", seller_id=seller_id, value=str(tariff_id)).pack()),
    )

    session.expire_all()
    assert (await _seller(session)).status == SellerStatus.ACTIVE
    subscription = await _subscription(session)
    assert subscription is not None
    assert subscription.ads_limit == 10
    assert subscription.granted_by == ADMIN_ID

    # Sotuvchi shaxsiy xabar oldi
    assert any("Tarifingiz faollashtirildi" in text for text in fake.sent_texts())
    # Kartochkada obuna holati
    assert "Faol" in fake.edited_texts()[-1]


async def test_admin_extends_and_sets_limits(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, tariff_id, _ = await _prepare(
        session, tariff_kwargs={"name": "Biznes", "duration_days": 30, "max_ads": 10}, grant=True
    )
    before = (await _subscription(session)).expires_at

    # ➕ +30 kun
    await _feed(
        session, dp, bot, 1, callback_update(SellerCB(action="extend", seller_id=seller_id, value="30").pack())
    )
    session.expire_all()
    assert (await _subscription(session)).expires_at > before

    # Limitni qo'lda
    await _feed(session, dp, bot, 2, callback_update(SellerCB(action="limit", seller_id=seller_id).pack()))
    await _feed(session, dp, bot, 3, text_update("40"))
    session.expire_all()
    assert (await _subscription(session)).ads_limit == 40

    # Muddatni qo'lda
    await _feed(session, dp, bot, 4, callback_update(SellerCB(action="days", seller_id=seller_id).pack()))
    await _feed(session, dp, bot, 5, text_update("15"))
    assert any("Yangi muddat" in text for text in fake.sent_texts())


async def test_admin_blocks_and_unblocks(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, _, _ = await _prepare(session, tariff_kwargs={"name": "Biznes", "max_ads": 10}, grant=True)

    await _feed(session, dp, bot, 1, callback_update(SellerCB(action="block", seller_id=seller_id).pack()))
    assert "bloklash sababini" in fake.edited_texts()[-1]

    await _feed(
        session,
        dp,
        bot,
        2,
        callback_update(SellerCB(action="block_confirm", seller_id=seller_id, value="no_pay").pack()),
    )
    session.expire_all()
    seller = await _seller(session)
    assert seller.status == SellerStatus.BLOCKED
    assert "To'lov" in (seller.blocked_reason or "")
    assert any("bloklandi" in text for text in fake.sent_texts())

    # Blokdan chiqarish — obuna bor, shuning uchun ACTIVE bo'ladi
    await _feed(session, dp, bot, 3, callback_update(SellerCB(action="unblock", seller_id=seller_id).pack()))
    session.expire_all()
    assert (await _seller(session)).status == SellerStatus.ACTIVE


async def test_admin_verifies_seller_and_edits_profile(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, _, _ = await _prepare(session, name="Eski nom")

    await _feed(session, dp, bot, 1, callback_update(SellerCB(action="verify", seller_id=seller_id).pack()))
    session.expire_all()
    assert (await _seller(session)).is_verified is True

    await _feed(session, dp, bot, 2, callback_update(SellerCB(action="profile", seller_id=seller_id).pack()))
    assert "Profil" in fake.edited_texts()[-1]

    await _feed(session, dp, bot, 3, callback_update(SellerCB(action="edit_name", seller_id=seller_id).pack()))
    await _feed(session, dp, bot, 4, text_update("Yangi nom"))
    session.expire_all()
    assert (await _seller(session)).display_name == "Yangi nom"

    # Izoh qo'shish
    await _feed(session, dp, bot, 5, callback_update(SellerCB(action="note", seller_id=seller_id).pack()))
    await _feed(session, dp, bot, 6, text_update("Ishonchli sotuvchi"))
    session.expire_all()
    assert (await _seller(session)).note == "Ishonchli sotuvchi"


async def test_admin_soft_deletes_seller(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, _, _ = await _prepare(session)

    await _feed(session, dp, bot, 1, callback_update(SellerCB(action="delete", seller_id=seller_id).pack()))
    assert "o'chirilsinmi" in fake.edited_texts()[-1]

    await _feed(
        session, dp, bot, 2, callback_update(SellerCB(action="delete_confirm", seller_id=seller_id).pack())
    )
    session.expire_all()
    assert (await _seller(session)).status == SellerStatus.DELETED
    assert "Sotuvchilar" in fake.edited_texts()[-1]


async def test_admin_searches_and_filters_sellers(session, tg) -> None:
    fake, bot, dp = tg
    await _prepare(session, name="Alfa do'kon")
    await _prepare(session, name="Beta bozor", user_id=SELLER_ID + 1)

    await _feed(session, dp, bot, 1, callback_update(SellerCB(action="search").pack()))
    await _feed(session, dp, bot, 2, text_update("alfa"))
    found = fake.sent_texts()[-1]
    assert "🔍 Qidiruv: <b>alfa</b>" in found
    assert "Ko'rsatilgan: 1 ta" in found

    # Holat bo'yicha filtr (hammasi — tarifsiz)
    await _feed(session, dp, bot, 3, callback_update(SellerCB(action="filter", value="pending").pack()))
    assert "🕓 Tarifsiz" in fake.edited_texts()[-1]


async def test_admin_opens_subscription_history(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, _, _ = await _prepare(
        session, tariff_kwargs={"name": "Biznes", "duration_days": 30, "max_ads": 10}, grant=True
    )

    await _feed(session, dp, bot, 1, callback_update(SellerCB(action="subs", seller_id=seller_id).pack()))
    history = fake.edited_texts()[-1]
    assert "Obunalar tarixi" in history
    assert "Biznes" in history
    assert "0/10" in history


# ══════════════════ 4. Sotuvchi paneli (E2E) ══════════════════════
async def test_seller_without_tariff_sees_no_tariff(session, tg) -> None:
    fake, bot, dp = tg
    await _prepare(session)

    await _feed(
        session, dp, bot, 1, callback_update(SellerPanelCB(action="menu").pack(), user_id=SELLER_ID)
    )
    assert "Tarifingiz hali berilmagan" in fake.edited_texts()[-1]

    await _feed(
        session, dp, bot, 2, callback_update(SellerPanelCB(action="tariff").pack(), user_id=SELLER_ID)
    )
    text = fake.edited_texts()[-1]
    assert "Mening tarifim" in text
    assert "tarifingiz yo'q" in text.lower()


async def test_seller_sees_active_tariff(session, tg) -> None:
    fake, bot, dp = tg
    await _prepare(
        session,
        tariff_kwargs={
            "name": "Biznes",
            "price": "400000",
            "duration_days": 30,
            "max_ads": 10,
            "max_photos": 5,
        },
        grant=True,
    )

    await _feed(
        session, dp, bot, 1, callback_update(SellerPanelCB(action="tariff").pack(), user_id=SELLER_ID)
    )
    text = fake.edited_texts()[-1]
    assert "Biznes" in text
    assert "Qolgan muddat" in text
    assert "0/10" in text
    assert "Faol" in text

    await _feed(
        session, dp, bot, 2, callback_update(SellerPanelCB(action="menu").pack(), user_id=SELLER_ID)
    )
    menu = fake.edited_texts()[-1]
    assert "Biznes" in menu and "0/10" in menu

    # Faol obuna bo'lsa — "Yangi e'lon" tugmasi ko'rinadi (Phase 3 da ishga tushdi)
    markup = fake.called("EditMessageText")[-1]["reply_markup"]
    labels = [button["text"] for row in markup["inline_keyboard"] for button in row]
    assert any("Yangi e'lon" in label for label in labels)

    # 📢 Mening e'lonlarim (Phase 3) — bo'sh ro'yxat
    await _feed(
        session, dp, bot, 3, callback_update(SellerPanelCB(action="ads").pack(), user_id=SELLER_ID)
    )
    assert "Mening e'lonlarim" in fake.edited_texts()[-1]

    # ➕ Yangi e'lon (Phase 3): faol toifa yo'q → ogohlantirish
    await _feed(
        session, dp, bot, 4, callback_update(SellerPanelCB(action="new_ad").pack(), user_id=SELLER_ID)
    )
    assert any("toifa" in answer.lower() for answer in fake.answers())


async def test_seller_catalog_and_support(session, tg) -> None:
    fake, bot, dp = tg
    await _prepare(session)
    await tariff_service.create_tariff(
        session, name="Boshlang'ich", price="150000", max_ads=3, max_photos=2
    )
    await session.commit()

    await _feed(
        session, dp, bot, 1, callback_update(SellerPanelCB(action="tariffs").pack(), user_id=SELLER_ID)
    )
    catalog = fake.edited_texts()[-1]
    assert "Boshlang'ich" in catalog
    assert "150 000 so'm" in catalog
    assert "Tarif olish uchun" in catalog

    await _feed(
        session, dp, bot, 2, callback_update(SellerPanelCB(action="support").pack(), user_id=SELLER_ID)
    )
    assert "Yordam" in fake.edited_texts()[-1]


async def test_seller_referral_code_created_on_demand(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, _, _ = await _prepare(session)
    seller = await session.get(Seller, seller_id)
    seller.referral_code = None
    await session.commit()

    await _feed(
        session, dp, bot, 1, callback_update(SellerPanelCB(action="referral").pack(), user_id=SELLER_ID)
    )
    session.expire_all()
    assert (await _seller(session)).referral_code is not None
    assert "Referal" in fake.edited_texts()[-1]


async def test_blocked_seller_cannot_open_panel(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, _, _ = await _prepare(session)
    seller = await session.get(Seller, seller_id)
    await seller_service.set_status(session, seller, SellerStatus.BLOCKED)
    await session.commit()

    await _feed(
        session, dp, bot, 1, callback_update(SellerPanelCB(action="menu").pack(), user_id=SELLER_ID)
    )
    assert fake.edited_texts() == []


async def test_stranger_cannot_open_seller_panel(session, tg) -> None:
    fake, bot, dp = tg
    await _feed(
        session, dp, bot, 1, callback_update(SellerPanelCB(action="menu").pack(), user_id=123321)
    )
    assert fake.edited_texts() == []


# ═══════════════ 5. Eslatma va muddat job'lari ════════════════════
async def test_reminder_job_notifies_seller_once(session, tg) -> None:
    fake, bot, dp = tg
    _, _, subscription_id = await _prepare(
        session, tariff_kwargs={"name": "Biznes", "duration_days": 30, "max_ads": 10}, grant=True
    )

    # Muddatni 2 kunga tushiramiz
    subscription = await session.get(Subscription, subscription_id)
    subscription.expires_at = utcnow() + timedelta(days=2)
    await session.commit()

    await subscription_reminders_job(bot)
    assert any("kundan keyin tugaydi" in text for text in fake.sent_texts())

    session.expire_all()
    assert (await _subscription(session)).reminder_sent_at is not None

    # Ikkinchi marta — takrorlanmaydi
    fake.reset()
    await subscription_reminders_job(bot)
    assert fake.sent_texts() == []


async def test_expire_job_deactivates_ads_and_notifies(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, tariff_id, subscription_id = await _prepare(
        session, tariff_kwargs={"name": "Biznes", "duration_days": 30, "max_ads": 10}, grant=True
    )

    subscription = await session.get(Subscription, subscription_id)
    subscription.expires_at = utcnow() - timedelta(minutes=5)

    category = Category(name="Telefonlar", position=1000)
    session.add(category)
    await session.flush()
    session.add(Ad(seller_id=seller_id, category_id=category.id, title="E'lon", status="active"))
    await session.commit()

    await expire_subscriptions_job(bot)

    session.expire_all()
    assert (await _subscription(session)).status == SubscriptionStatus.EXPIRED
    assert (await session.execute(select(Ad))).scalar_one().status == "expired"

    # Muddati o'tgani haqida xabar (bir marta)
    await subscription_reminders_job(bot)
    assert any("muddati tugadi" in text for text in fake.sent_texts())

    fake.reset()
    await subscription_reminders_job(bot)
    assert fake.sent_texts() == []


async def test_grace_period_keeps_subscription_in_grace(session, tg) -> None:
    """`subscription_grace_days > 0` bo'lsa — avval grace holatiga o'tadi."""
    fake, bot, dp = tg

    _, _, subscription_id = await _prepare(
        session, tariff_kwargs={"name": "Biznes", "duration_days": 30, "max_ads": 10}, grant=True
    )
    subscription = await session.get(Subscription, subscription_id)
    subscription.expires_at = utcnow() - timedelta(minutes=5)
    await session.commit()

    await settings_service.set(session, "subscription_grace_days", 3)
    await session.commit()
    try:
        await expire_subscriptions_job(bot)
        session.expire_all()
        assert (await _subscription(session)).status == SubscriptionStatus.GRACE
    finally:
        await settings_service.set(session, "subscription_grace_days", 0)
        await session.commit()


# ═══════════════ 6. Panel bo'limlari va klaviaturalar ═════════════
async def test_admin_panel_opens_sellers_and_tariffs(session, tg) -> None:
    fake, bot, dp = tg

    await _feed(
        session, dp, bot, 1, callback_update(AdminCB(action="section", value="sellers").pack())
    )
    assert "Sotuvchilar" in fake.edited_texts()[-1]

    await _feed(
        session, dp, bot, 2, callback_update(AdminCB(action="section", value="tariffs").pack())
    )
    assert "Tariflar" in fake.edited_texts()[-1]

    # Endi bu bo'limlar tayyor — "Phase N" xabari chiqmasligi kerak
    assert not any("Phase" in answer for answer in fake.answers())


async def test_admin_menu_shows_seller_counter(session, tg) -> None:
    fake, bot, dp = tg
    await _prepare(session, name="Alfa")

    await _feed(session, dp, bot, 1, callback_update(AdminCB(action="menu").pack()))
    markup = fake.called("EditMessageText")[-1]["reply_markup"]
    labels = [button["text"] for row in markup["inline_keyboard"] for button in row]
    assert any(label.startswith("🛒 Sotuvchilar · 1") for label in labels)


def test_seller_and_tariff_callbacks_fit_telegram_limit() -> None:
    payloads = [
        SellerCB(action="grant_tariff", seller_id=123456, value="987654").pack(),
        SellerCB(action="block_confirm", seller_id=123456, value="complaints").pack(),
        SellerCB(action="list", value="3|blocked").pack(),
        TariffCB(action="delete_confirm", tariff_id=987654).pack(),
        SellerPanelCB(action="tariffs").pack(),
    ]
    for payload in payloads:
        assert len(payload.encode()) <= 64, payload
