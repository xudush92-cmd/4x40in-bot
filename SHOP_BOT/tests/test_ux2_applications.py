"""UX-2: ariza DB cheklovlari, admin ruxsati va haqiqiy routerdagi private oqim."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.constants import AdminRole, ApplicationStatus, SellerStatus
from app.db.base import get_session_factory
from app.db.models import (
    ActionLog,
    Ad,
    Admin,
    Payment,
    Referral,
    Seller,
    SellerApplication,
    Subscription,
    User,
)
from app.keyboards.callbacks import AdminCB, ApplicationCB, GuideCB, SellerCB, SellerPanelCB
from app.services import application_service as applications
from app.services import seller_service
from app.services.application_service import ApplicationError
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

APPLICANT_ID = 54545455
MOD_ID = 88998899
OTHER_ADMIN = 222222


def cb(action: str, app_id: int = 0, page: int = 0) -> str:
    return ApplicationCB(action=action, application_id=app_id, page=page).pack()


@pytest.mark.parametrize("value", ["", "a", "x" * 65, "<b>" * 22])
def test_name_does_not_silently_truncate(value) -> None:
    with pytest.raises(ApplicationError):
        applications.validate_name(value)
    assert applications.validate_name("  Do'kon \n nomi  ") == "Do'kon nomi"
    assert applications.validate_name("a" * 64) == "a" * 64


@pytest.mark.parametrize("value", ["@ab", "@" + "a" * 33, "@b;bad", "++998901234567", "123-abc", "x" * 65])
def test_contact_rejects_bad_values(value) -> None:
    with pytest.raises(ApplicationError):
        applications.validate_contact(value)
    assert applications.validate_contact("@market_uz") == ("username", "@market_uz")
    assert applications.validate_contact("+998 (90) 111-22-33") == ("phone", "+998901112233")
    assert applications.validate_contact("123456789") == ("phone", "123456789")


async def test_unique_pending_rejection_retry_limit_and_audit(session) -> None:
    now = utcnow()
    first, created = await applications.submit(session, APPLICANT_ID, "Do'kon", "@market_uz", now=now)
    first_id = first.id
    assert created and first.status == ApplicationStatus.PENDING
    duplicate, created = await applications.submit(session, APPLICANT_ID, "Boshqa ism", "+998901234567", now=now)
    assert not created and duplicate.id == first_id and first.display_name == "Do'kon"
    assert await applications.count_pending(session) == 1
    assert [row.id for row in await applications.list_pending(session)] == [first_id]

    # Boshqa DB sessiyasidan kelsa ham partial UNIQUE bazaning o'zida kuchda.
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(SellerApplication(user_id=APPLICANT_ID, display_name="Dubl", contact_type="phone",
                                          contact_value="+998901234567", status=ApplicationStatus.PENDING))
            await session.flush()
    assert await applications.count_pending(session) == 1
    await session.commit()
    session.add(Admin(user_id=ADMIN_ID, role=AdminRole.SUPER))
    await session.commit()
    rejected, changed = await applications.decide(session, first_id, ADMIN_ID, approve=False, reason="Aloqa yo'q")
    assert changed and rejected.status == ApplicationStatus.REJECTED and rejected.reject_reason == "Aloqa yo'q"
    assert rejected.decided_by == ADMIN_ID and rejected.decided_at
    await session.commit()
    with pytest.raises(ApplicationError, match="1 soat"):
        await applications.submit(session, APPLICANT_ID, "Do'kon", "@market_uz", now=utcnow())

    # Vaqtni sun'iy o'tkazish: yangi ariza boshqa ID; 24 soatda ko'pi bilan 3 ta.
    rejected.decided_at = now - timedelta(hours=2)
    await session.commit()
    second, created = await applications.submit(session, APPLICANT_ID, "Ikkinchi", "+998901234567", now=now)
    assert created and second.id != first_id
    second_id = second.id
    await applications.decide(session, second_id, ADMIN_ID, approve=False, reason="Nomni aniqlang")
    second.decided_at = now - timedelta(hours=2)
    await session.commit()
    third, created = await applications.submit(session, APPLICANT_ID, "Uchinchi", "@market_uz", now=now)
    assert created and third.id not in (first_id, second_id)
    await applications.decide(session, third.id, ADMIN_ID, approve=False, reason="Ko'proq ma'lumot")
    third.decided_at = now - timedelta(hours=2)
    await session.commit()
    with pytest.raises(ApplicationError, match="3 ta ariza"):
        await applications.submit(session, APPLICANT_ID, "To'rtinchi", "@market_uz", now=now)
    assert (await session.execute(select(func.count()).select_from(SellerApplication))).scalar_one() == 3
    assert (await session.execute(select(func.count()).select_from(ActionLog))).scalar_one() == 6


async def test_decision_guards_idempotence_rollback_and_legacy_sellers(session) -> None:
    session.add_all([Admin(user_id=ADMIN_ID, role=AdminRole.SUPER),
                     Admin(user_id=MOD_ID, role=AdminRole.MODERATOR),
                     Admin(user_id=OTHER_ADMIN, role=AdminRole.ADMIN)])
    legacy, _ = await seller_service.get_or_create_seller(session, 909909, display_name="Eski sotuvchi")
    await session.commit()
    assert await applications.latest_for(session, legacy.user_id) is None
    with pytest.raises(ApplicationError, match="allaqachon sotuvchi"):
        await applications.submit(session, legacy.user_id, "Yangisi", "@market_uz")
    app, _ = await applications.submit(session, APPLICANT_ID, "Sotuvchi", "@market_uz")
    app_id = app.id
    await session.commit()
    with pytest.raises(ApplicationError, match="faqat admin"):
        await applications.decide(session, app_id, MOD_ID, approve=True)
    with pytest.raises(ApplicationError, match="faqat admin"):
        await applications.decide(session, app_id, 123000, approve=False, reason="Sinov")
    with pytest.raises(ApplicationError, match="3–500"):
        await applications.decide(session, app_id, ADMIN_ID, approve=False, reason="no")
    assert (await applications.pending_for(session, APPLICANT_ID)).id == app_id

    approved, changed = await applications.decide(session, app_id, ADMIN_ID, approve=True)
    assert changed and approved.seller_id and approved.decided_by == ADMIN_ID
    await session.commit()
    seller = await seller_service.get_seller(session, APPLICANT_ID)
    assert seller.status == SellerStatus.PENDING and seller.added_by == ADMIN_ID
    assert seller.display_name == "Sotuvchi" and seller.contact == "@market_uz"
    assert seller.phone is None and not seller.is_verified
    assert (await session.execute(select(func.count()).select_from(Subscription))).scalar_one() == 0
    assert (await session.execute(select(func.count()).select_from(Payment))).scalar_one() == 0
    assert (await session.execute(select(func.count()).select_from(Ad))).scalar_one() == 0
    count_logs = (await session.execute(select(func.count()).select_from(ActionLog))).scalar_one()
    # Ikkinchi admin mustaqil DB sessiyasida eskirgan callbackni yuboradi.
    async with get_session_factory()() as other:
        row, changed = await applications.decide(other, app_id, OTHER_ADMIN, approve=False, reason="Kechikdi")
        assert not changed and row.status == ApplicationStatus.APPROVED
        await other.commit()
    assert (await session.execute(select(func.count()).select_from(ActionLog))).scalar_one() == count_logs
    assert (await session.execute(select(func.count()).select_from(Seller).where(
        Seller.user_id == APPLICANT_ID))).scalar_one() == 1

    # Bloklangan sotuvchi ochiq arizani tasdiqlash orqali tiklanmaydi: CAS rollback.
    app2, _ = await applications.submit(session, APPLICANT_ID + 1, "Blok", "+998901234567")
    sid2 = app2.id
    blocked, _ = await seller_service.get_or_create_seller(session, APPLICANT_ID + 1, display_name="Blok")
    blocked.status = SellerStatus.BLOCKED
    await session.commit()
    with pytest.raises(ApplicationError, match="bloklangan"):
        await applications.decide(session, sid2, ADMIN_ID, approve=True)
    session.expire_all()
    assert (await session.get(SellerApplication, sid2)).status == ApplicationStatus.PENDING
    assert (await seller_service.get_seller(session, APPLICANT_ID + 1)).status == SellerStatus.BLOCKED
    with pytest.raises(ApplicationError, match="allaqachon sotuvchi"):
        await applications.submit(session, APPLICANT_ID + 1, "Yangi", "@market_uz")


async def test_manual_add_reconciles_pending_without_granting_tariff(session) -> None:
    session.add(Admin(user_id=ADMIN_ID, role=AdminRole.ADMIN))
    app, _ = await applications.submit(session, APPLICANT_ID, "Arizachi", "+998901234567")
    app_id = app.id
    await session.commit()
    seller, created = await seller_service.get_or_create_seller(session, APPLICANT_ID,
                                                                display_name="Qo'lda", added_by=ADMIN_ID)
    assert created
    row = await applications.approve_manually(session, seller, ADMIN_ID)
    assert row.id == app_id
    await session.commit()
    assert (await session.get(SellerApplication, app_id)).status == ApplicationStatus.APPROVED
    assert (await session.get(SellerApplication, app_id)).seller_id == seller.id
    assert await applications.count_pending(session) == 0
    assert await applications.approve_manually(session, seller, ADMIN_ID) is None
    assert (await applications.decide(session, app_id, ADMIN_ID, approve=True))[1] is False
    assert (await session.execute(select(func.count()).select_from(Subscription))).scalar_one() == 0


@pytest.fixture
async def tg(session):
    session.add_all([Admin(user_id=ADMIN_ID, role=AdminRole.SUPER),
                     Admin(user_id=OTHER_ADMIN, role=AdminRole.ADMIN),
                     Admin(user_id=MOD_ID, role=AdminRole.MODERATOR)])
    await session.commit()
    await reset_dispatcher_state()
    fake = FakeSession()
    bot = make_bot(fake)
    dp = make_dispatcher()
    yield fake, bot, dp
    await bot.session.close()
    await reset_dispatcher_state()


async def feed(dp, bot, session, update) -> None:
    await dp.feed_update(bot, update)
    session.expire_all()


async def test_private_flow_admin_queue_approval_and_blocked_start(session, tg) -> None:
    fake, bot, dp = tg
    await feed(dp, bot, session, text_update("/start", user_id=APPLICANT_ID, update_id=1))
    assert "Sotuvchi bo'lish" not in str(fake.called("SendMessage")[-1]["reply_markup"])
    assert "E'lon joylash" in str(fake.called("SendMessage")[-1]["reply_markup"])
    assert await seller_service.get_seller(session, APPLICANT_ID) is None
    user = await session.get(User, APPLICANT_ID)
    assert user.private_started_at is not None  # oddiy /start yopilmagan
    await feed(dp, bot, session, callback_update(SellerPanelCB().pack(), user_id=APPLICANT_ID, update_id=2))
    assert not fake.edited_texts()  # tasdiqsiz seller paneli ochilmaydi
    await feed(dp, bot, session, callback_update(cb("new"), user_id=APPLICANT_ID, update_id=3))
    assert "Ism yoki do'kon" in fake.edited_texts()[-1]
    await feed(dp, bot, session, text_update("a", user_id=APPLICANT_ID, update_id=4))
    assert "2–64" in fake.sent_texts()[-1]
    await feed(dp, bot, session, text_update("<Market & Co>", user_id=APPLICANT_ID, update_id=5))
    await feed(dp, bot, session, text_update("@x", user_id=APPLICANT_ID, update_id=6))
    assert "@username" in fake.sent_texts()[-1]
    await feed(dp, bot, session, text_update("+998 (90) 111-22-33", user_id=APPLICANT_ID, update_id=7))
    assert "&lt;Market &amp; Co&gt;" in fake.sent_texts()[-1]
    assert "+998901112233" in fake.sent_texts()[-1]
    await feed(dp, bot, session, callback_update(cb("submit"), user_id=APPLICANT_ID, update_id=8))
    app = await applications.pending_for(session, APPLICANT_ID)
    assert app and app.display_name == "<Market & Co>" and app.contact_value == "+998901112233"
    app_id = app.id
    assert await seller_service.get_seller(session, APPLICANT_ID) is None
    assert any(payload["chat_id"] == ADMIN_ID and "Yangi sotuvchilik arizasi" in payload["text"]
               for payload in fake.called("SendMessage"))
    assert any(payload["chat_id"] == OTHER_ADMIN and "Yangi sotuvchilik arizasi" in payload["text"]
               for payload in fake.called("SendMessage"))
    assert not any(payload["chat_id"] == MOD_ID for payload in fake.called("SendMessage"))
    await feed(dp, bot, session, callback_update(cb("submit"), user_id=APPLICANT_ID, update_id=9))
    assert await applications.count_pending(session) == 1
    await feed(dp, bot, session, text_update("/start", user_id=APPLICANT_ID, update_id=10))
    assert "arizasi shart emas" in fake.sent_texts()[-1]
    assert "Qayta ariza" not in str(fake.called("SendMessage")[-1]["reply_markup"])
    await feed(dp, bot, session, callback_update(GuideCB(page="back").pack(), user_id=APPLICANT_ID,
                                                  update_id=11))
    assert "arizasi shart emas" in fake.edited_texts()[-1]

    # Moderator uchun menyuda tugma yo'q, eski/soxta callback ham qaror qilmaydi.
    await feed(dp, bot, session, callback_update(AdminCB(action="menu").pack(), user_id=MOD_ID, update_id=12))
    assert "Arizalar" not in str(fake.called("EditMessageText")[-1]["reply_markup"])
    await feed(dp, bot, session, callback_update(AdminCB(action="section", value="applications").pack(),
                                                  user_id=MOD_ID, update_id=13))
    assert "faqat admin" in fake.answers()[-1]
    await feed(dp, bot, session, callback_update(cb("approve_confirm", app_id), user_id=MOD_ID, update_id=14))
    assert (await applications.pending_for(session, APPLICANT_ID)).id == app_id
    await feed(dp, bot, session, callback_update(AdminCB(action="section", value="sellers").pack(),
                                                  user_id=MOD_ID, update_id=140))
    assert "faqat admin" in fake.answers()[-1]
    assert not any("+998901112233" in text for text in fake.edited_texts())
    await feed(dp, bot, session, callback_update(AdminCB(action="menu").pack(), update_id=15))
    assert "Arizalar: <b>1</b>" in fake.edited_texts()[-1]
    assert "Arizalar · 1" in str(fake.called("EditMessageText")[-1]["reply_markup"])
    await feed(dp, bot, session, callback_update(AdminCB(action="hub", value="sales").pack(), update_id=16))
    assert "Arizalar · 1" in str(fake.called("EditMessageText")[-1]["reply_markup"])
    await feed(dp, bot, session, callback_update(AdminCB(action="section", value="applications").pack(),
                                                  update_id=17))
    assert "qaror kutmoqda: 1" in fake.edited_texts()[-1]
    await feed(dp, bot, session, callback_update(cb("card", app_id), update_id=18))
    assert "&lt;Market &amp; Co&gt;" in fake.edited_texts()[-1]
    await feed(dp, bot, session, callback_update(cb("approve", app_id), update_id=19))
    assert "faqat sotuvchi panelini ochadi" in fake.edited_texts()[-1]
    await feed(dp, bot, session, callback_update(cb("approve_confirm", app_id), update_id=20))
    assert (await session.get(SellerApplication, app_id)).status == ApplicationStatus.APPROVED
    seller = await seller_service.get_seller(session, APPLICANT_ID)
    assert seller.status == SellerStatus.PENDING and seller.phone == "+998901112233"
    assert (await session.execute(select(func.count()).select_from(Subscription))).scalar_one() == 0
    assert (await session.execute(select(func.count()).select_from(Payment))).scalar_one() == 0
    assert (await session.execute(select(func.count()).select_from(Ad))).scalar_one() == 0
    assert any(payload["chat_id"] == APPLICANT_ID and "Sotuvchilik arizangiz" in payload["text"]
               for payload in fake.called("SendMessage"))
    fake.reset()
    await feed(dp, bot, session, callback_update(cb("approve_confirm", app_id), user_id=OTHER_ADMIN, update_id=21))
    assert "boshqa admin" in fake.answers()[-1]
    assert not any(payload["chat_id"] == APPLICANT_ID for payload in fake.called("SendMessage"))
    await feed(dp, bot, session, text_update("/start", user_id=APPLICANT_ID, update_id=22))
    assert "Tarif yo'q" in fake.sent_texts()[-1]
    seller.status = SellerStatus.BLOCKED
    seller.blocked_reason = "Sinov sabab"
    await session.commit()
    await feed(dp, bot, session, text_update("/start", user_id=APPLICANT_ID, update_id=23))
    assert "Hisobingiz cheklangan" in fake.sent_texts()[-1]
    assert "Sotuvchi bo'lish" not in str(fake.called("SendMessage")[-1]["reply_markup"])
    await feed(dp, bot, session, callback_update(cb("new"), user_id=APPLICANT_ID, update_id=24))
    assert "cheklangan" in fake.edited_texts()[-1]
    assert not await applications.pending_for(session, APPLICANT_ID)


async def test_reject_reason_dm_failure_and_retry_new_id(session, tg, monkeypatch) -> None:
    fake, bot, dp = tg
    await feed(dp, bot, session, text_update("/start", user_id=APPLICANT_ID, update_id=1))
    await feed(dp, bot, session, callback_update(cb("new"), user_id=APPLICANT_ID, update_id=2))
    await feed(dp, bot, session, text_update("Do'kon", user_id=APPLICANT_ID, update_id=3))
    await feed(dp, bot, session, text_update("@market_uz", user_id=APPLICANT_ID, update_id=4))
    await feed(dp, bot, session, callback_update(cb("submit"), user_id=APPLICANT_ID, update_id=5))
    app = await applications.pending_for(session, APPLICANT_ID)
    app_id = app.id
    await feed(dp, bot, session, callback_update(cb("reject", app_id), update_id=6))
    await feed(dp, bot, session, callback_update(cb("custom", app_id), update_id=7))
    await feed(dp, bot, session, text_update("x", update_id=8))
    assert "3–500" in fake.sent_texts()[-1]
    # Natija DM xatosi qarorni rollback qilmasin. Bildirishnoma commitdan keyin
    # yuborilganini boshqa DB sessiyasidan o'qib tekshiramiz.
    seen = []
    async def failed_after_commit(bot, application_id):
        async with get_session_factory()() as check:
            row = await check.get(SellerApplication, application_id)
            seen.append((row.status, row.reject_reason))
        raise RuntimeError("Telegram vaqtincha uzilgan")
    monkeypatch.setattr("app.handlers.applications.notify_application_result", failed_after_commit)
    await feed(dp, bot, session, text_update("<Yaroqsiz & aloqa>", update_id=9))
    assert seen == [(ApplicationStatus.REJECTED, "<Yaroqsiz & aloqa>")]
    assert (await session.get(SellerApplication, app_id)).status == ApplicationStatus.REJECTED
    assert "&lt;Yaroqsiz &amp; aloqa&gt;" in fake.sent_texts()[-1]
    assert await seller_service.get_seller(session, APPLICANT_ID) is None
    fake.reset()
    await feed(dp, bot, session, text_update("/start", user_id=APPLICANT_ID, update_id=10))
    assert "arizasi shart emas" in fake.sent_texts()[-1]
    await feed(dp, bot, session, callback_update(cb("new"), user_id=APPLICANT_ID, update_id=11))
    assert "1 soat" in fake.answers()[-1]
    assert await applications.count_pending(session) == 0
    app = await session.get(SellerApplication, app_id)
    app.decided_at = utcnow() - timedelta(hours=2)
    await session.commit()
    await feed(dp, bot, session, callback_update(cb("new"), user_id=APPLICANT_ID, update_id=12))
    assert "Ism yoki do'kon" in fake.edited_texts()[-1]
    await feed(dp, bot, session, text_update("Tuzatilgan", user_id=APPLICANT_ID, update_id=13))
    await feed(dp, bot, session, text_update("+998901234567", user_id=APPLICANT_ID, update_id=14))
    await feed(dp, bot, session, callback_update(cb("submit"), user_id=APPLICANT_ID, update_id=15))
    new = await applications.pending_for(session, APPLICANT_ID)
    assert new.id != app_id and new.display_name == "Tuzatilgan"


async def test_manual_admin_path_closes_pending_and_notifies_after_commit(session, tg) -> None:
    fake, bot, dp = tg
    await feed(dp, bot, session, text_update("/start", user_id=APPLICANT_ID, update_id=1))
    await feed(dp, bot, session, callback_update(cb("new"), user_id=APPLICANT_ID, update_id=2))
    await feed(dp, bot, session, text_update("Arizachi", user_id=APPLICANT_ID, update_id=3))
    await feed(dp, bot, session, text_update("@market_uz", user_id=APPLICANT_ID, update_id=4))
    await feed(dp, bot, session, callback_update(cb("submit"), user_id=APPLICANT_ID, update_id=5))
    app_id = (await applications.pending_for(session, APPLICANT_ID)).id
    await feed(dp, bot, session, callback_update(SellerCB(action="add").pack(), update_id=6))
    await feed(dp, bot, session, text_update(str(APPLICANT_ID), update_id=7))
    await feed(dp, bot, session, text_update("Qo'lda qo'shildi", update_id=8))
    await feed(dp, bot, session, text_update("-", update_id=9))
    await feed(dp, bot, session, text_update("@market_uz", update_id=10))
    assert (await session.get(SellerApplication, app_id)).status == ApplicationStatus.APPROVED
    assert (await seller_service.get_seller(session, APPLICANT_ID)).display_name == "Qo'lda qo'shildi"
    assert any(payload["chat_id"] == APPLICANT_ID and "Sotuvchilik arizangiz" in payload["text"]
               for payload in fake.called("SendMessage"))
    assert await applications.count_pending(session) == 0
    assert (await session.execute(select(func.count()).select_from(Subscription))).scalar_one() == 0


async def test_admin_notification_only_after_commit_and_private_only(session, tg, monkeypatch) -> None:
    fake, bot, dp = tg
    from app.filters import PrivateChat
    from tests.fake_telegram import group_chat

    private_event = callback_update(cb("new"), user_id=APPLICANT_ID).callback_query
    assert await PrivateChat()(private_event)
    group_event = private_event.model_copy(update={
        "message": private_event.message.model_copy(update={"chat": group_chat()}),
    })
    assert not await PrivateChat()(group_event)

    seen = []
    async def check_committed(bot, application_id):
        async with get_session_factory()() as check:
            row = await check.get(SellerApplication, application_id)
            seen.append((row.status, row.contact_value))
        raise RuntimeError("Admin botni bloklagan")
    monkeypatch.setattr("app.handlers.applications.notify_application_admins", check_committed)
    await feed(dp, bot, session, text_update("/start", user_id=APPLICANT_ID, update_id=1))
    await feed(dp, bot, session, callback_update(cb("new"), user_id=APPLICANT_ID, update_id=2))
    await feed(dp, bot, session, text_update("Do'kon", user_id=APPLICANT_ID, update_id=3))
    await feed(dp, bot, session, text_update("@market_uz", user_id=APPLICANT_ID, update_id=4))
    await feed(dp, bot, session, callback_update(cb("submit"), user_id=APPLICANT_ID, update_id=5))
    assert seen == [(ApplicationStatus.PENDING, "@market_uz")]
    assert await applications.count_pending(session) == 1
    await feed(dp, bot, session, callback_update(cb("submit"), user_id=APPLICANT_ID, update_id=6))
    assert len(seen) == 1  # qayta bosishda adminga takroriy DM yo'q
    await feed(dp, bot, session, text_update("/start", user_id=APPLICANT_ID, update_id=7))
    assert "arizasi shart emas" in fake.sent_texts()[-1]


async def test_application_does_not_retrigger_referral_bonus(session, tg) -> None:
    fake, bot, dp = tg
    referrer, _ = await seller_service.get_or_create_seller(session, 333555, display_name="Taklifchi")
    referrer_id = referrer.user_id
    code = referrer.referral_code
    await settings_service.set(session, "referral_enabled", True, updated_by=ADMIN_ID)
    await session.commit()
    await feed(dp, bot, session, text_update(f"/start ref_{code}", user_id=APPLICANT_ID, update_id=1))
    assert (await session.execute(select(func.count()).select_from(Referral).where(
        Referral.referee_id == APPLICANT_ID))).scalar_one() == 1
    await feed(dp, bot, session, callback_update(cb("new"), user_id=APPLICANT_ID, update_id=2))
    await feed(dp, bot, session, text_update("Do'kon", user_id=APPLICANT_ID, update_id=3))
    await feed(dp, bot, session, text_update("@market_uz", user_id=APPLICANT_ID, update_id=4))
    await feed(dp, bot, session, callback_update(cb("submit"), user_id=APPLICANT_ID, update_id=5))
    app_id = (await applications.pending_for(session, APPLICANT_ID)).id
    await feed(dp, bot, session, callback_update(cb("approve_confirm", app_id), update_id=6))
    await feed(dp, bot, session, text_update(f"/start ref_{code}", user_id=APPLICANT_ID, update_id=7))
    assert (await session.execute(select(func.count()).select_from(Referral).where(
        Referral.referee_id == APPLICANT_ID))).scalar_one() == 1
    assert (await seller_service.get_seller(session, APPLICANT_ID)).referred_by == referrer_id
