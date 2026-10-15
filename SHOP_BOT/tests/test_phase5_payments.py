"""Phase 5: haqiqiy Dispatcher + soxta Telegram API bilan to'lovning boshidan oxirigacha."""

from __future__ import annotations

from decimal import Decimal

import pytest_asyncio
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage, SendPhoto
from sqlalchemy import select

from app.constants import AdminRole, PaymentStatus, SellerStatus
from app.db.models import ActionLog, Admin, Payment, PaymentMethod, Seller, Subscription, Tariff
from app.keyboards.callbacks import AdminCB, PaymentCB, SellerPanelCB
from app.services import payment_service, seller_service, tariff_service
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

SELLER_ID = 505050
MOD_ID = 707070
CARD_1 = "8600123456789012"  # faqat test uchun soxta raqam
CARD_2 = "9860123456789012"  # faqat test uchun soxta raqam


@pytest_asyncio.fixture
async def tg(session):
    session.add_all([
        Admin(user_id=ADMIN_ID, role=AdminRole.SUPER),
        Admin(user_id=MOD_ID, role=AdminRole.MODERATOR),
    ])
    seller, _ = await seller_service.get_or_create_seller(
        session, SELLER_ID, display_name="Ali <dokon>"
    )
    tariff = await tariff_service.create_tariff(
        session, name="Boshlang'ich", price="150000", duration_days=30, max_ads=3, max_photos=2
    )
    await session.commit()
    await reset_dispatcher_state()
    fake = FakeSession()
    bot = make_bot(fake)
    dp = make_dispatcher()
    yield fake, bot, dp, seller.id, tariff.id
    await bot.session.close()
    await reset_dispatcher_state()


async def feed(session, dp, bot, update):
    await dp.feed_update(bot, update)
    session.expire_all()


async def new_method(session, *, card=CARD_1):
    method = await payment_service.create_method(
        session, name="Uzcard", card_number=card, holder="Karta egasi", bank="Test bank",
    )
    await session.commit()
    return method.id


async def buy_and_send(session, dp, bot, tariff_id: int, *, unique: str, update_id: int) -> None:
    await feed(session, dp, bot, callback_update(
        SellerPanelCB(action="pay", value=str(tariff_id)).pack(),
        user_id=SELLER_ID, update_id=update_id,
    ))
    await feed(session, dp, bot, photo_update(
        file_id=f"receipt-{unique}", file_unique_id=unique,
        user_id=SELLER_ID, update_id=update_id + 1,
    ))


async def test_admin_creates_method_seller_pays_admin_approves_once(session, tg) -> None:
    fake, bot, dp, seller_id, tariff_id = tg
    await feed(session, dp, bot, callback_update(AdminCB(action="section", value="payments").pack(), update_id=1))
    assert "Faol kartalar: <b>0" in fake.edited_texts()[-1]
    await feed(session, dp, bot, callback_update(PaymentCB(action="method_new").pack(), update_id=2))
    for n, text in enumerate(("Uzcard", "8600 1234 5678 9012", "Sherzod <Admin>", "Bank", "-", "UZS"), start=3):
        await feed(session, dp, bot, text_update(text, update_id=n))
    method = (await session.execute(select(PaymentMethod))).scalar_one()
    assert method.card_number == CARD_1 and method.currency == "UZS"
    method_id = method.id
    assert "Sherzod &lt;Admin&gt;" in fake.sent_texts()[-1]

    await feed(session, dp, bot, callback_update(
        SellerPanelCB(action="tariffs").pack(), user_id=SELLER_ID, update_id=10,
    ))
    assert "Boshlang'ich" in fake.edited_texts()[-1]
    assert any(
        SellerPanelCB(action="pay", value=str(tariff_id)).pack() == button["callback_data"]
        for row in fake.called("EditMessageText")[-1]["reply_markup"]["inline_keyboard"] for button in row
    )
    await feed(session, dp, bot, callback_update(
        SellerPanelCB(action="pay", value=str(tariff_id)).pack(), user_id=SELLER_ID, update_id=11,
    ))
    pay_screen = fake.called("EditMessageText")[-1]
    assert "150 000 so'm" in pay_screen["text"]
    assert pay_screen["reply_markup"]["inline_keyboard"][0][0]["copy_text"]["text"] == CARD_1
    await feed(session, dp, bot, text_update("Pul o'tkazdim", user_id=SELLER_ID, update_id=12))
    assert "Chekni rasm" in fake.sent_texts()[-1]

    await feed(session, dp, bot, photo_update(
        file_id="receipt1", file_unique_id="uniq1", user_id=SELLER_ID, update_id=13,
    ))
    payment = (await session.execute(select(Payment))).scalar_one()
    assert payment.status == PaymentStatus.PENDING and payment.amount == Decimal("150000")
    assert payment.method_id == method_id and payment.receipt_unique_hash
    payment_id = payment.id
    assert (await session.execute(select(Subscription))).scalars().all() == []
    # Xabar faqat adminlarga (env'dagi super-adminlarga ham), moderatorga emas.
    receipts = [p for p in fake.called("SendPhoto") if p["photo"] == "receipt1"]
    assert {p["chat_id"] for p in receipts} == {ADMIN_ID, 222222}
    assert MOD_ID not in {p["chat_id"] for p in receipts}
    assert "Ali &lt;dokon&gt;" in receipts[0]["caption"]

    await feed(session, dp, bot, callback_update(PaymentCB(action="list", value="0|pending").pack(), update_id=14))
    assert "Kelgan cheklar" in fake.edited_texts()[-1]
    await feed(session, dp, bot, callback_update(PaymentCB(action="card", target_id=payment_id, value="0|pending").pack(), update_id=15))
    assert "150 000" in fake.edited_texts()[-1]
    await feed(session, dp, bot, callback_update(PaymentCB(action="approve", target_id=payment_id, value="0|pending").pack(), update_id=16))
    assert "bankingizdagi" in fake.edited_texts()[-1].lower()
    assert (await session.get(Payment, payment_id)).status == PaymentStatus.PENDING
    await feed(session, dp, bot, callback_update(PaymentCB(action="approve_confirm", target_id=payment_id, value="0|pending").pack(), update_id=17))
    approved = await session.get(Payment, payment_id)
    subscriptions = (await session.execute(select(Subscription))).scalars().all()
    assert approved.status == PaymentStatus.APPROVED and len(subscriptions) == 1
    assert approved.subscription_id == subscriptions[0].id and subscriptions[0].payment_id == approved.id
    assert (await session.get(Seller, seller_id)).status == SellerStatus.ACTIVE
    assert any(p["chat_id"] == SELLER_ID and "tasdiqlandi" in p["text"] for p in fake.called("SendMessage"))
    await feed(session, dp, bot, callback_update(PaymentCB(action="approve_confirm", target_id=payment_id, value="0|pending").pack(), update_id=18))
    assert len((await session.execute(select(Subscription))).scalars().all()) == 1

    await feed(session, dp, bot, callback_update(
        SellerPanelCB(action="payments").pack(), user_id=SELLER_ID, update_id=19,
    ))
    assert "To'lovlarim" in fake.edited_texts()[-1]
    await feed(session, dp, bot, callback_update(
        SellerPanelCB(action="payment_detail", value=str(payment_id)).pack(), user_id=SELLER_ID,
        update_id=20,
    ))
    assert "Tasdiqlandi" in fake.edited_texts()[-1]


async def test_duplicate_chek_is_flagged_blocked_and_rejected(session, tg) -> None:
    fake, bot, dp, _, tariff_id = tg
    await new_method(session)
    await buy_and_send(session, dp, bot, tariff_id, unique="same-receipt", update_id=30)
    await buy_and_send(session, dp, bot, tariff_id, unique="same-receipt", update_id=40)
    payments = (await session.execute(select(Payment).order_by(Payment.id))).scalars().all()
    assert len(payments) == 2 and payments[1].is_duplicate_receipt
    assert payments[0].receipt_unique_hash and payments[1].receipt_unique_hash is None
    duplicate_id = payments[1].id
    assert any("TAKRORIY CHEK" in p["caption"] for p in fake.called("SendPhoto"))
    await feed(session, dp, bot, callback_update(
        PaymentCB(action="approve_confirm", target_id=duplicate_id).pack(), update_id=42,
    ))
    assert "Takroriy chek" in fake.answers()[-1]
    assert (await session.get(Payment, duplicate_id)).status == PaymentStatus.PENDING
    await feed(session, dp, bot, callback_update(PaymentCB(action="reject", target_id=duplicate_id).pack(), update_id=43))
    await feed(session, dp, bot, callback_update(PaymentCB(action="reason", target_id=duplicate_id, value="duplicate").pack(), update_id=44))
    assert (await session.get(Payment, duplicate_id)).status == PaymentStatus.REJECTED
    assert (await session.execute(select(Subscription))).scalars().all() == []
    assert any(p["chat_id"] == SELLER_ID and "oldin ishlatilgan" in p["text"] for p in fake.called("SendMessage"))


async def test_custom_reject_role_and_privacy(session, tg) -> None:
    fake, bot, dp, _, tariff_id = tg
    await new_method(session)
    await buy_and_send(session, dp, bot, tariff_id, unique="new", update_id=50)
    payment = (await session.execute(select(Payment))).scalar_one()
    payment_id = payment.id
    await feed(session, dp, bot, callback_update(PaymentCB(action="approve_confirm", target_id=payment_id).pack(), user_id=MOD_ID, update_id=52))
    assert "faqat admin" in fake.answers()[-1]
    await feed(session, dp, bot, callback_update(AdminCB(action="section", value="payments").pack(), user_id=MOD_ID, update_id=53))
    assert "faqat admin" in fake.answers()[-1]
    await feed(session, dp, bot, callback_update(AdminCB(action="section", value="settings").pack(), user_id=MOD_ID, update_id=531))
    assert "receipt_duplicate_check" not in str(fake.called("EditMessageText")[-1]["reply_markup"])
    await feed(session, dp, bot, callback_update(AdminCB(action="toggle", value="receipt_duplicate_check").pack(), user_id=MOD_ID, update_id=532))
    assert "faqat admin" in fake.answers()[-1]
    await feed(session, dp, bot, callback_update(PaymentCB(action="reason", target_id=payment_id, value="custom").pack(), update_id=54))
    await feed(session, dp, bot, text_update("yo", update_id=55))
    assert "3–300" in fake.sent_texts()[-1]
    await feed(session, dp, bot, text_update("Bankda <b>summa</b> topilmadi", update_id=56))
    rejected = await session.get(Payment, payment_id)
    assert rejected.status == PaymentStatus.REJECTED and "<b>" in rejected.reason
    assert any("&lt;b&gt;" in p["text"] for p in fake.called("SendMessage") if p["chat_id"] == SELLER_ID)
    assert (await session.execute(select(Subscription))).scalars().all() == []
    session.add(Seller(user_id=707071, status=SellerStatus.PENDING, display_name="Begona"))
    await session.commit()
    before_edits = len(fake.edited_texts())
    await feed(session, dp, bot, callback_update(
        SellerPanelCB(action="payment_detail", value=str(payment_id)).pack(), user_id=707071,
        update_id=57,
    ))
    assert len(fake.edited_texts()) == before_edits
    assert "Chek topilmadi" in fake.answers()[-1]


async def test_receiptless_setting_and_stale_payment_wizard(session, tg) -> None:
    fake, bot, dp, _, tariff_id = tg
    await new_method(session)
    await feed(session, dp, bot, callback_update(AdminCB(action="toggle", value="receipt_required").pack(), update_id=61))
    await feed(session, dp, bot, callback_update(
        SellerPanelCB(action="pay", value=str(tariff_id)).pack(), user_id=SELLER_ID, update_id=62,
    ))
    assert "submit_no_receipt" in str(fake.called("EditMessageText")[-1]["reply_markup"])
    # Menyuga qaytish chek kutish holatini tozalaydi; begona rasm qabul qilinmaydi.
    await feed(session, dp, bot, callback_update(SellerPanelCB(action="menu").pack(), user_id=SELLER_ID, update_id=63))
    await feed(session, dp, bot, photo_update(user_id=SELLER_ID, update_id=64))
    assert (await session.execute(select(Payment))).scalars().all() == []

    await feed(session, dp, bot, callback_update(
        SellerPanelCB(action="pay", value=str(tariff_id)).pack(), user_id=SELLER_ID, update_id=65,
    ))
    await feed(session, dp, bot, callback_update(SellerPanelCB(action="submit_no_receipt").pack(), user_id=SELLER_ID, update_id=66))
    payment = (await session.execute(select(Payment))).scalar_one()
    assert payment.receipt_file_id is None and payment.status == PaymentStatus.PENDING
    payment_id = payment.id
    assert any("Chek rasmi yo'q" in p["text"] for p in fake.called("SendMessage") if p["chat_id"] == ADMIN_ID)
    await feed(session, dp, bot, callback_update(PaymentCB(action="approve_confirm", target_id=payment_id).pack(), update_id=67))
    assert (await session.get(Payment, payment_id)).status == PaymentStatus.APPROVED
    assert (await session.execute(select(Subscription))).scalars().first() is not None


async def test_card_edit_deactivate_and_reorder_with_audit(session, tg) -> None:
    fake, bot, dp, _, _ = tg
    first_id = await new_method(session)
    second = await payment_service.create_method(session, name="Humo", card_number=CARD_2)
    second_id = second.id
    await session.commit()
    await feed(session, dp, bot, callback_update(PaymentCB(action="methods").pack(), update_id=70))
    listing = fake.called("EditMessageText")[-1]
    assert CARD_1 not in str(listing)
    assert "9012" in str(listing["reply_markup"])
    await feed(session, dp, bot, callback_update(PaymentCB(action="method_card", target_id=first_id).pack(), update_id=71))
    assert CARD_1 in fake.edited_texts()[-1]
    await feed(session, dp, bot, callback_update(PaymentCB(action="method_edit", target_id=first_id, value="card_number").pack(), update_id=72))
    await feed(session, dp, bot, text_update("bad", update_id=73))
    assert "16–19" in fake.sent_texts()[-1]
    await feed(session, dp, bot, text_update("8600 0000 0000 5555", update_id=74))
    assert (await session.get(PaymentMethod, first_id)).card_number.endswith("5555")
    await feed(session, dp, bot, callback_update(PaymentCB(action="method_up", target_id=second_id).pack(), update_id=75))
    assert (await session.get(PaymentMethod, second_id)).position < (await session.get(PaymentMethod, first_id)).position
    await feed(session, dp, bot, callback_update(PaymentCB(action="method_delete_confirm", target_id=first_id).pack(), update_id=76))
    assert not (await session.get(PaymentMethod, first_id)).is_active
    assert (await session.get(PaymentMethod, first_id)).card_number.endswith("5555")
    audit = (await session.execute(select(ActionLog).where(ActionLog.entity == "payment_method"))).scalars().all()
    assert audit and all(CARD_1 not in str(row.after) for row in audit)



async def test_price_snapshot_and_card_rotation_via_dispatcher(session, tg) -> None:
    fake, bot, dp, _, tariff_id = tg
    first_id = await new_method(session)
    second_id = await new_method(session, card=CARD_2)
    await feed(session, dp, bot, callback_update(
        SellerPanelCB(action="pay", value=str(tariff_id)).pack(), user_id=SELLER_ID, update_id=80,
    ))
    assert CARD_1 in fake.edited_texts()[-1]
    tariff = await session.get(Tariff, tariff_id)
    tariff.price = Decimal("210000")
    await session.commit()
    await feed(session, dp, bot, photo_update(
        file_id="early", file_unique_id="early", user_id=SELLER_ID, update_id=81,
    ))
    first = (await session.execute(select(Payment))).scalar_one()
    assert first.method_id == first_id and first.amount == Decimal("150000")
    await feed(session, dp, bot, callback_update(
        SellerPanelCB(action="pay", value=str(tariff_id)).pack(), user_id=SELLER_ID, update_id=82,
    ))
    assert CARD_2 in fake.edited_texts()[-1] and "210 000" in fake.edited_texts()[-1]
    await feed(session, dp, bot, photo_update(
        file_id="late", file_unique_id="late", user_id=SELLER_ID, update_id=83,
    ))
    latest = (await session.execute(select(Payment).order_by(Payment.id.desc()))).scalars().first()
    assert latest.method_id == second_id and latest.amount == Decimal("210000")
    await feed(session, dp, bot, callback_update(
        SellerPanelCB(action="pay", value=str(tariff_id)).pack(), user_id=SELLER_ID, update_id=84,
    ))
    assert CARD_1 in fake.edited_texts()[-1]


async def test_photo_notification_failure_falls_back_to_admin_text(session, tg) -> None:
    fake, bot, dp, _, tariff_id = tg
    await new_method(session)
    fake.errors["SendPhoto"] = TelegramBadRequest(
        method=SendPhoto(chat_id=ADMIN_ID, photo="unavailable"), message="invalid file_id"
    )
    await buy_and_send(session, dp, bot, tariff_id, unique="unavailable", update_id=90)
    payment = (await session.execute(select(Payment))).scalar_one()
    assert payment.status == PaymentStatus.PENDING and payment.receipt_file_id
    assert (await session.execute(select(Subscription))).scalars().all() == []
    warnings = [p for p in fake.called("SendMessage") if "Rasmni yuborib bo'lmadi" in p["text"]]
    assert {p["chat_id"] for p in warnings} == {ADMIN_ID, 222222}
    assert warnings[0]["reply_markup"]["inline_keyboard"]



async def test_seller_ack_failure_does_not_hide_pending_receipt(session, tg) -> None:
    fake, bot, dp, _, tariff_id = tg
    await new_method(session)
    fake.errors["SendMessage"] = TelegramBadRequest(
        method=SendMessage(chat_id=SELLER_ID, text="Chek qabul qilindi"), message="blocked by user"
    )
    await buy_and_send(session, dp, bot, tariff_id, unique="seller-blocked", update_id=100)
    payment = (await session.execute(select(Payment))).scalar_one()
    assert payment.status == PaymentStatus.PENDING
    assert {p["chat_id"] for p in fake.called("SendPhoto") if p["photo"] == "receipt-seller-blocked"} == {
        ADMIN_ID, 222222,
    }


def test_payment_callback_lengths() -> None:
    for data in (
        PaymentCB(action="approve_confirm", target_id=999999999, value="9999|approved").pack(),
        PaymentCB(action="method_delete_confirm", target_id=999999999, value="9999").pack(),
        SellerPanelCB(action="payment_detail", value="999999999").pack(),
    ):
        assert len(data.encode()) <= 64
