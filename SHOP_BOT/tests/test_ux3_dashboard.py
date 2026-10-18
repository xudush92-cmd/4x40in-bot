"""UX-3: bitta kabinet /start va callback'da bir xil haqiqiy holatni beradi."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest_asyncio
from aiogram.types import Update

from app.constants import AdStatus, PaymentStatus, SellerStatus, SubscriptionStatus
from app.db.models import Ad, Category, Payment, Seller, Subscription
from app.keyboards.callbacks import SellerPanelCB
from app.services import seller_service, subscription_service, tariff_service
from app.states import SellerAdStates, SellerPaymentStates
from app.utils.time import utcnow
from tests.fake_telegram import (
    FakeSession,
    callback_update,
    group_chat,
    make_bot,
    make_dispatcher,
    reset_dispatcher_state,
    text_update,
)

SELLER_ID = 91929291


@pytest_asyncio.fixture
async def tg():
    await reset_dispatcher_state()
    fake = FakeSession()
    bot = make_bot(fake)
    dp = make_dispatcher()
    yield fake, bot, dp
    await bot.session.close()
    await reset_dispatcher_state()


async def feed(session, dp, bot, update) -> None:
    await dp.feed_update(bot, update)
    session.expire_all()


async def start(session, bot, dp, *, user_id: int = SELLER_ID, update_id: int = 1) -> None:
    await feed(session, dp, bot, text_update("/start", user_id=user_id, update_id=update_id))


async def click(session, bot, dp, action: str, *, user_id: int = SELLER_ID,
                update_id: int = 1) -> None:
    await feed(session, dp, bot, callback_update(
        SellerPanelCB(action=action).pack(), user_id=user_id, update_id=update_id,
    ))


def actions(payload) -> set[str]:
    return {button["callback_data"] for row in payload["reply_markup"]["inline_keyboard"]
            for button in row if button.get("callback_data") is not None}


async def seller_and_tariff(session, *, grant: bool = False, max_ads: int = 5):
    seller, _ = await seller_service.get_or_create_seller(
        session, SELLER_ID, display_name="<Do'kon & Co>",
        phone="+998901234567", contact="@shop_admin",
    )
    tariff = await tariff_service.create_tariff(session, name="<Sinov & Pro>",
                                                price="150000", duration_days=15,
                                                max_ads=max_ads)
    assert tariff is not None
    sub = await subscription_service.grant(session, seller, tariff) if grant else None
    await session.commit()
    return seller.id, tariff.id, sub.id if sub else None


async def cheque(session, seller_id: int, tariff_id: int, status: str,
                 reason: str | None = None) -> int:
    item = Payment(seller_id=seller_id, tariff_id=tariff_id, amount=Decimal("150000"),
                   status=status, reason=reason)
    session.add(item)
    await session.commit()
    return item.id


async def test_new_seller_has_dashboard_but_not_tariff_or_new_ad(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, _, _ = await seller_and_tariff(session)  # tarif mavjud, sotuvchiga hali berilmagan
    await start(session, bot, dp)
    text = fake.sent_texts()[-1]
    assert "Sotuvchi paneli ochiq" in text and "Tarif yo'q" in text
    assert "E'lon limiti: faol tarif yo'q" in text
    assert "0</b> faol" in text and "Oxirgi chek: yuborilmagan" in text
    assert "Katalogdan tarifni tanlang" in text
    keyboard = actions(fake.called("SendMessage")[-1])
    assert SellerPanelCB(action="ads").pack() in keyboard  # eski e'lonlar ham ko'rinadi
    assert SellerPanelCB(action="profile").pack() not in keyboard  # ortiqcha profil menyusi yo'q
    assert SellerPanelCB(action="payments").pack() in keyboard
    assert SellerPanelCB(action="tariffs").pack() in keyboard
    assert SellerPanelCB(action="new_ad").pack() not in keyboard
    assert (await session.get(Seller, seller_id)).status == SellerStatus.PENDING
    assert not (await session.get(Seller, seller_id)).is_verified  # panel ≠ verifikatsiya

    await click(session, bot, dp, "menu", update_id=2)
    assert "Mening kabinetim" in fake.edited_texts()[-1]
    assert "Oxirgi chek: yuborilmagan" in fake.edited_texts()[-1]
    await click(session, bot, dp, "profile", update_id=3)
    assert "&lt;Do'kon &amp; Co&gt;" in fake.edited_texts()[-1]
    assert "+998901234567" in fake.edited_texts()[-1]
    assert "@shop_admin" in fake.edited_texts()[-1]
    assert SellerPanelCB(action="support").pack() in actions(fake.called("EditMessageText")[-1])
    await click(session, bot, dp, "ads", update_id=4)
    assert "Mening e'lonlarim" in fake.edited_texts()[-1]
    assert "faol tarif va bo'sh limit kerak" in fake.edited_texts()[-1]
    markup = fake.called("EditMessageText")[-1]
    assert SellerPanelCB(action="menu").pack() in actions(markup)
    assert not any("Yangi e'lon" in button.get("text", "") for row in
                   markup["reply_markup"]["inline_keyboard"] for button in row)
    await click(session, bot, dp, "menu", update_id=5)  # ro'yxatdan kabinetga qaytish
    assert "Mening kabinetim" in fake.edited_texts()[-1]


async def test_payment_pending_and_rejection_do_not_activate_subscription(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, tariff_id, _ = await seller_and_tariff(session)
    await cheque(session, seller_id, tariff_id, PaymentStatus.PENDING)
    await start(session, bot, dp)
    assert "🧾 Oxirgi chek #1: <b>🕓 Tekshiruvda</b>" in fake.sent_texts()[-1]
    assert "Admin qarorini kuting" in fake.sent_texts()[-1]
    assert SellerPanelCB(action="new_ad").pack() not in actions(fake.called("SendMessage")[-1])

    await cheque(session, seller_id, tariff_id, PaymentStatus.REJECTED, "<i>Tekshir & qayta yubor</i>")
    await click(session, bot, dp, "menu", update_id=2)
    text = fake.edited_texts()[-1]
    assert "Oxirgi chek #2: <b>❌ Rad etilgan</b>" in text
    assert "&lt;i&gt;Tekshir &amp; qayta yubor&lt;/i&gt;" in text
    assert "<i>Tekshir" not in text
    assert "Rad sababini «To'lovlarim»da" in text
    assert (await session.get(Seller, seller_id)).status == SellerStatus.PENDING
    await click(session, bot, dp, "payments", update_id=3)
    assert "To'lovlarim" in fake.edited_texts()[-1]  # eski chek tarixi ishlaydi
    assert await subscription_service.active_for(session, seller_id) is None


async def test_active_dashboard_counts_and_quick_links_use_existing_flow(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, tariff_id, sub_id = await seller_and_tariff(session, grant=True)
    assert sub_id is not None
    category = Category(name="Sinov toifasi", is_active=True)
    session.add(category)
    await session.flush()
    for status in (AdStatus.ACTIVE, AdStatus.PENDING, AdStatus.REJECTED,
                   AdStatus.DRAFT, AdStatus.PAUSED, AdStatus.DELETED):
        session.add(Ad(seller_id=seller_id, category_id=category.id,
                       title="Sinov", status=status))
    sub = await session.get(Subscription, sub_id)
    sub.ads_used = 2  # agregat e'lonlar soni bilan teng emas: limit obunaga xos
    await session.commit()
    await cheque(session, seller_id, tariff_id, PaymentStatus.APPROVED)

    await start(session, bot, dp)
    text = fake.sent_texts()[-1]
    assert "&lt;Sinov &amp; Pro&gt;" in text and "2/5</b> ishlatilgan" in text
    assert "3</b> ta qolgan" in text
    assert "1</b> faol · <b>1</b> tekshiruvda · <b>1</b> rad · <b>1</b> qoralama" in text
    assert "1 pauzada" in text
    assert "Oxirgi chek #1: <b>✅ Tasdiqlangan</b>" in text
    assert "Rad etilgan e'lonni" in text
    assert SellerPanelCB(action="new_ad").pack() in actions(fake.called("SendMessage")[-1])
    await click(session, bot, dp, "menu", update_id=2)
    assert "2/5</b> ishlatilgan" in fake.edited_texts()[-1]
    assert "Mening e'lonlarim (1)" in str(fake.called("EditMessageText")[-1]["reply_markup"])
    await click(session, bot, dp, "tariff", update_id=3)
    assert "2/5" in fake.edited_texts()[-1]  # eski tarif ekrani bilan mos
    await click(session, bot, dp, "ads", update_id=4)
    assert "Mening e'lonlarim" in fake.edited_texts()[-1]
    await click(session, bot, dp, "tariffs", update_id=5)
    assert "Tariflar" in fake.edited_texts()[-1]


async def test_limit_exhausted_hides_creation_even_with_active_ads(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, _, sub_id = await seller_and_tariff(session, grant=True, max_ads=2)
    assert sub_id is not None
    (await session.get(Subscription, sub_id)).ads_used = 2
    await session.commit()
    await click(session, bot, dp, "menu")
    assert "2/2</b> ishlatilgan" in fake.edited_texts()[-1]
    assert "Limit tugadi" in fake.edited_texts()[-1]
    keyboard = actions(fake.called("EditMessageText")[-1])
    assert SellerPanelCB(action="new_ad").pack() not in keyboard
    assert SellerPanelCB(action="ads").pack() in keyboard
    await click(session, bot, dp, "new_ad", update_id=2)  # eski/qo'lda callback ham serverda rad
    assert any("E'lon limiti tugadi" in answer for answer in fake.answers())
    assert (await session.get(Subscription, sub_id)).ads_used == 2
    assert await subscription_service.active_for(session, seller_id) is not None


async def test_expired_or_cancelled_tariff_shows_distinct_reason(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, _, sub_id = await seller_and_tariff(session, grant=True)
    assert sub_id is not None
    sub = await session.get(Subscription, sub_id)
    sub.expires_at = utcnow() - timedelta(days=1)
    await session.commit()
    await click(session, bot, dp, "menu")
    assert "muddati tugagan" in fake.edited_texts()[-1]
    assert SellerPanelCB(action="new_ad").pack() not in actions(fake.called("EditMessageText")[-1])
    await click(session, bot, dp, "new_ad", update_id=2)
    assert any("muddati tugagan" in answer for answer in fake.answers())

    sub = await session.get(Subscription, sub_id)
    sub.status = SubscriptionStatus.CANCELLED
    sub.expires_at = utcnow() + timedelta(days=5)  # muddat bor, lekin bekor qilingan
    await session.commit()
    await click(session, bot, dp, "menu", update_id=3)
    assert "oldingi obuna bekor qilingan" in fake.edited_texts()[-1]
    assert "muddati tugagan" not in fake.edited_texts()[-1]
    assert await subscription_service.active_for(session, seller_id) is None


async def test_blocked_seller_and_stranger_cannot_open_dashboard_or_profile(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, _, _ = await seller_and_tariff(session, grant=True)
    await seller_service.set_status(session, await session.get(Seller, seller_id), SellerStatus.BLOCKED)
    await session.commit()
    await start(session, bot, dp)
    assert "Hisobingiz cheklangan" in fake.sent_texts()[-1]
    assert SellerPanelCB(action="profile").pack() not in actions(fake.called("SendMessage")[-1])
    await click(session, bot, dp, "profile", update_id=2)
    await click(session, bot, dp, "menu", update_id=3)
    await click(session, bot, dp, "menu", user_id=SELLER_ID + 1, update_id=4)
    assert not fake.edited_texts()


async def test_next_step_follows_ad_review_draft_and_expiring_tariff(session, tg) -> None:
    fake, bot, dp = tg
    seller_id, _, sub_id = await seller_and_tariff(session, grant=True)
    assert sub_id is not None
    category = Category(name="Aloqa", is_active=True)
    session.add(category)
    await session.flush()
    ad = Ad(seller_id=seller_id, category_id=category.id,
            title="Mening e'lonim", status=AdStatus.PENDING)
    session.add(ad)
    await session.flush()
    ad_id = ad.id
    await session.commit()
    await click(session, bot, dp, "menu")
    assert "E'lon admin tekshiruvida" in fake.edited_texts()[-1]

    ad = await session.get(Ad, ad_id)
    ad.status = AdStatus.DRAFT
    await session.commit()
    await click(session, bot, dp, "menu", update_id=2)
    assert "Qoralamani yakunlang" in fake.edited_texts()[-1]

    ad = await session.get(Ad, ad_id)
    ad.status = AdStatus.ACTIVE
    (await session.get(Subscription, sub_id)).expires_at = utcnow() + timedelta(days=1)
    await session.commit()
    await click(session, bot, dp, "menu", update_id=3)
    assert "Tarif tez tugaydi" in fake.edited_texts()[-1]
    assert SellerPanelCB(action="new_ad").pack() in actions(fake.called("EditMessageText")[-1])


async def test_dashboard_profile_is_private_only(session, tg) -> None:
    fake, bot, dp = tg
    await seller_and_tariff(session, grant=True)
    query = callback_update(SellerPanelCB(action="profile").pack(), user_id=SELLER_ID)
    assert query.callback_query is not None and query.callback_query.message is not None
    message = query.callback_query.message.model_copy(update={"chat": group_chat()})
    callback = query.callback_query.model_copy(update={"message": message})
    await feed(session, dp, bot, Update(update_id=1, callback_query=callback))
    assert not fake.edited_texts()
    assert "+998901234567" not in " ".join(fake.sent_texts())


async def test_start_returns_to_cabinet_from_ad_or_receipt_fsm(session, tg) -> None:
    fake, bot, dp = tg
    await seller_and_tariff(session, grant=True)
    state = dp.fsm.get_context(bot=bot, chat_id=SELLER_ID, user_id=SELLER_ID)
    await state.set_state(SellerAdStates.waiting_title)
    await state.update_data(ad_id=12345, flow="wizard", step="title")
    await start(session, bot, dp)
    assert await state.get_state() is None
    assert "E'lonlar" in fake.sent_texts()[-1] and "Sotuvchi paneli" in fake.sent_texts()[-1]
    assert await state.get_data() == {}

    await state.set_state(SellerPaymentStates.waiting_receipt)
    await state.update_data(tariff_id=999, amount=1)
    await start(session, bot, dp, update_id=2)
    assert await state.get_state() is None
    assert "Oxirgi chek: yuborilmagan" in fake.sent_texts()[-1]
    assert await state.get_data() == {}
    assert "To'lov jarayoni bekor qilindi" not in fake.sent_texts()[-1]

    await state.set_state(SellerAdStates.waiting_contact)
    await state.update_data(ad_id=12345)
    await feed(session, dp, bot, text_update("/start ref_invalid", user_id=SELLER_ID, update_id=3))
    assert await state.get_state() is None
    assert "Sotuvchi paneli" in fake.sent_texts()[-1]
