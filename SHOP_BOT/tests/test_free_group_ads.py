"""2-bosqich: guruh tanlash → haqiqiy direct-add → admin → 30 kun → post.

Real Dispatcher/FSM + SQLite/Alembic model + FakeSession; internet ishlatilmaydi.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.constants import AdminRole, InviteSource
from app.db.base import session_scope
from app.db.models import (
    ActionLog,
    Admin,
    Category,
    CounterSetting,
    FreeAd,
    FreeEntitlement,
    FreeInviteUse,
    FreePostLog,
    Group,
    InviteEvent,
    PostLog,
)
from app.keyboards.callbacks import FreeCB, FreeModCB, GroupCB
from app.scheduler import free_poster, jobs
from app.services import free_ad_service as free_ads
from app.services import group_service
from app.services.settings_service import settings_service
from app.utils.time import ensure_aware, utcnow
from tests.fake_telegram import (
    ADMIN_ID,
    GROUP_CHAT_ID,
    FakeSession,
    callback_update,
    make_bot,
    make_dispatcher,
    photo_update,
    reset_dispatcher_state,
    text_update,
)
from tests.test_manual_group_add import enable_direct, finish_join
from tests.test_phase7_counter import INVITEE, INVITER, OTHER, membership, send, setup_group, subscribed


@pytest_asyncio.fixture
async def tg(session, monkeypatch):
    session.add(Admin(user_id=ADMIN_ID, role=AdminRole.SUPER))
    await session.commit()
    await reset_dispatcher_state()
    fake = FakeSession()
    subscribed(fake)
    bot = make_bot(fake)
    dp = make_dispatcher()

    async def fast(*args, **kwargs):
        return None
    monkeypatch.setattr(free_poster.posting_limiter, "acquire", fast)
    jobs._free_wait_cursor = 0
    yield fake, bot, dp
    await bot.session.close()
    await reset_dispatcher_state()


async def setup_free(session, *, n: int = 2, chat_id: int = GROUP_CHAT_ID) -> int:
    gid = await setup_group(session, chat_id=chat_id)
    await enable_direct(session, gid, n=n)
    group = await group_service.get_group(session, gid)
    group.settings.posting_enabled = True
    group.settings.free_ads_enabled = True
    session.add(Category(name="Telefonlar" if chat_id == GROUP_CHAT_ID else "Ustalar",
                         group_id=gid, is_active=True))
    await session.commit()
    return gid


async def credit(session, gid: int, uid: int, count: int, *, start: int = 70000,
                 source: str = InviteSource.ADDED_BY) -> None:
    for i in range(count):
        session.add(InviteEvent(group_id=gid, inviter_id=uid, invitee_id=start + i,
                                source=source, counted=True))
    await session.commit()


async def free_draft(session, gid: int, uid: int, *, caption: str = "Telefon sotiladi, @mijoz") -> FreeAd:
    ad = await free_ads.submit(session, uid, gid, "test-photo", caption)
    await session.commit()
    await free_ads.review(session, ad.id, ad.revision, ADMIN_ID, approve=True)
    await session.commit()
    return ad


async def test_user_flow_group_buttons_admin_gate_and_real_direct_members(session, tg):
    fake, bot, dp = tg
    gid = await setup_free(session, n=2)
    other = await setup_free(session, n=1, chat_id=OTHER)
    session.expire_all()

    await send(session, dp, bot, text_update("/start", user_id=INVITER, update_id=10))
    home = fake.called("SendMessage")[-1]
    buttons = [b["callback_data"] for row in home["reply_markup"]["inline_keyboard"]
               for b in row if "callback_data" in b]
    assert FreeCB(action="list").pack() in buttons
    assert "arizasi shart emas" in home["text"]
    await send(session, dp, bot, callback_update(FreeCB(action="list").pack(), user_id=INVITER, update_id=11))
    assert "guruhni tanlang" in fake.edited_texts()[-1]
    group_buttons = [b for row in fake.called("EditMessageText")[-1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("Telefonlar" in b["text"] for b in group_buttons)
    assert {FreeCB.unpack(b["callback_data"]).group_id for b in group_buttons} == {gid, other}

    await send(session, dp, bot, callback_update(FreeCB(action="group", group_id=gid).pack(),
                                                 user_id=INVITER, update_id=12))
    assert "2 ta haqiqiy" in fake.edited_texts()[-1] and "Pullik" in fake.edited_texts()[-1]
    await send(session, dp, bot, callback_update(FreeCB(action="paid", group_id=gid).pack(),
                                                 user_id=INVITER, update_id=13))
    assert "Hozircha faol tarif yo'q" in fake.edited_texts()[-1]
    assert (await session.execute(select(FreeAd))).scalars().all() == []

    await send(session, dp, bot, callback_update(FreeCB(action="photo", group_id=gid).pack(),
                                                 user_id=INVITER, update_id=14))
    await send(session, dp, bot, photo_update(caption="<b>Telefon</b> sotiladi, @mijoz",
                                              user_id=INVITER, update_id=15))
    preview = fake.called("SendPhoto")[-1]
    assert "parse_mode" not in preview and preview["caption"] == "<b>Telefon</b> sotiladi, @mijoz"
    await send(session, dp, bot, callback_update(FreeCB(action="submit", group_id=gid).pack(),
                                                 user_id=INVITER, update_id=16))
    ad = await free_ads.get_ad(session, INVITER, gid)
    assert ad.review_status == "pending" and not ad.approved_photo_id
    ad_id, revision = ad.id, ad.revision
    assert (await session.execute(select(FreeEntitlement))).scalars().all() == []
    await jobs.free_posting_tick_job(bot)
    assert not fake.called("SendPhoto")[-1]["chat_id"] == GROUP_CHAT_ID
    assert any(p.get("chat_id") == ADMIN_ID and "Bepul e'lon" in p.get("text", "")
               for p in fake.called("SendMessage"))

    await send(session, dp, bot, callback_update(FreeModCB(action="approve", ad_id=ad_id,
                                                            revision=revision).pack(), update_id=17))
    assert (await session.get(FreeAd, ad_id)).review_status == "approved"
    await jobs.free_posting_tick_job(bot)
    assert (await session.execute(select(FreeEntitlement))).scalars().all() == []

    # Haqiqiy guruh chat_member hodisalari va a'zolik cheki. N-1 yetmaydi.
    await send(session, dp, bot, membership(INVITEE, update_id=18))
    await finish_join(session, bot, group_id=gid, invitee_id=INVITEE)
    await jobs.free_posting_tick_job(bot)
    assert (await session.execute(select(FreeEntitlement))).scalars().all() == []
    await send(session, dp, bot, membership(INVITEE + 1, update_id=19))
    await finish_join(session, bot, group_id=gid, invitee_id=INVITEE + 1)
    await jobs.free_posting_tick_job(bot)
    access = (await session.execute(select(FreeEntitlement))).scalar_one()
    ad = await free_ads.get_ad(session, INVITER, gid)
    assert access.group_id == gid and access.period == 1
    assert timedelta(days=29, hours=23) < ensure_aware(access.expires_at) - ensure_aware(access.valid_from) <= timedelta(days=30)
    assert len((await session.execute(select(FreeInviteUse))).scalars().all()) == 2
    assert (ensure_aware(ad.next_post_at) - ensure_aware(access.valid_from)).total_seconds() >= 300
    assert not [p for p in fake.called("SendPhoto") if p["chat_id"] == GROUP_CHAT_ID]

    ad.next_post_at = utcnow() - timedelta(seconds=1)
    await session.commit()
    await jobs.free_posting_tick_job(bot)
    posts = [p for p in fake.called("SendPhoto") if p["chat_id"] == GROUP_CHAT_ID]
    assert len(posts) == 1 and posts[0]["caption"] == "<b>Telefon</b> sotiladi, @mijoz"
    assert "parse_mode" not in posts[0]
    log = (await session.execute(select(FreePostLog))).scalar_one()
    assert log.status == "sent" and log.message_id is not None
    assert (await session.execute(select(PostLog))).scalars().all() == []  # pullik Ad navbati ajratilgan
    assert (await session.execute(select(ActionLog).where(
        ActionLog.action == "free_ad_approve",
    ))).scalars().all()


async def test_30_days_renew_requires_new_verified_same_group_invites(session, tg):
    fake, bot, _ = tg
    gid = await setup_free(session, n=2)
    other = await setup_free(session, n=1, chat_id=OTHER)
    ad = await free_draft(session, gid, INVITER)
    await credit(session, gid, INVITER, 3, start=81000)
    await credit(session, gid, INVITER, 4, start=82000, source=InviteSource.LINK)
    await credit(session, other, INVITER, 2, start=83000)

    now = utcnow()
    assert await free_ads.maybe_activate(session, ad, now, member_ok=True)
    await session.commit()
    access = await free_ads.entitlement(session, INVITER, gid)
    assert access.period == 1 and len((await session.execute(select(FreeInviteUse))).scalars().all()) == 2
    assert await free_ads.unspent_count(session, gid, INVITER) == 1
    # Yangi surat tasdiqlansa huquq muddati qaytadan boshlanmasin.
    old_until = access.expires_at
    await free_ads.submit(session, INVITER, gid, "new-photo", "Yangi tasdiq uchun matn")
    ad = await free_ads.get_ad(session, INVITER, gid)
    await free_ads.review(session, ad.id, ad.revision, ADMIN_ID, approve=True)
    assert not await free_ads.maybe_activate(session, ad, utcnow(), member_ok=True)
    await session.commit()
    assert (await free_ads.entitlement(session, INVITER, gid)).expires_at == old_until

    access.expires_at = utcnow() - timedelta(seconds=1)
    await session.commit()
    assert not await free_ads.maybe_activate(session, ad, utcnow(), member_ok=True)
    assert ad.next_post_at is None
    # Ikkinchi guruh/havola va eski ikki eventni qayta sanamaydi.
    await credit(session, gid, INVITER, 1, start=84000)
    assert await free_ads.maybe_activate(session, ad, utcnow(), member_ok=True)
    await session.commit()
    access = await free_ads.entitlement(session, INVITER, gid)
    assert access.period == 2 and len((await session.execute(select(FreeInviteUse))).scalars().all()) == 4
    assert await free_ads.unspent_count(session, gid, INVITER) == 0
    assert not fake.called("CreateChatInviteLink")


async def test_edit_rejection_old_content_and_stale_admin_callback(session, tg):
    fake, bot, dp = tg
    gid = await setup_free(session, n=1)
    ad = await free_draft(session, gid, INVITER, caption="Eski tasdiqlangan matn")
    await credit(session, gid, INVITER, 1)
    await free_ads.maybe_activate(session, ad, utcnow(), member_ok=True)
    await session.commit()
    old_revision = ad.revision

    await send(session, dp, bot, callback_update(FreeCB(action="photo", group_id=gid).pack(),
                                                 user_id=INVITER, update_id=100))
    await send(session, dp, bot, photo_update(caption="Yangi MATN — tekshiruvda",
                                              user_id=INVITER, update_id=101))
    await send(session, dp, bot, callback_update(FreeCB(action="submit", group_id=gid).pack(),
                                                 user_id=INVITER, update_id=102))
    assert (await free_ads.get_ad(session, INVITER, gid)).review_status == "pending"
    assert (await free_ads.get_ad(session, INVITER, gid)).next_post_at is None
    await send(session, dp, bot, callback_update(FreeModCB(action="approve", ad_id=ad.id,
                                                            revision=old_revision).pack(), update_id=103))
    assert "eskirgan" in fake.answers()[-1]
    assert (await free_ads.get_ad(session, INVITER, gid)).review_status == "pending"
    new_revision = (await free_ads.get_ad(session, INVITER, gid)).revision
    await send(session, dp, bot, callback_update(FreeModCB(action="reject", ad_id=ad.id,
                                                            revision=new_revision).pack(), update_id=104))
    ad = await free_ads.get_ad(session, INVITER, gid)
    assert ad.review_status == "approved" and ad.approved_caption == "Eski tasdiqlangan matn"
    ad_id = ad.id
    await jobs.free_posting_tick_job(bot)
    session.expire_all()
    ad = await session.get(FreeAd, ad_id)
    assert ad.next_post_at is not None
    ad.next_post_at = utcnow() - timedelta(seconds=1)
    await session.commit()
    await free_poster.post_one(bot, ad.id)
    assert [p["caption"] for p in fake.called("SendPhoto") if p["chat_id"] == GROUP_CHAT_ID] == ["Eski tasdiqlangan matn"]


async def test_stop_start_owned_user_and_independent_timers(session, tg):
    fake, bot, dp = tg
    gid = await setup_free(session, n=1)
    a = await free_draft(session, gid, INVITER)
    b = await free_draft(session, gid, INVITER + 7, caption="Ikkinchi odamning e'loni")
    await credit(session, gid, INVITER, 1, start=71000)
    await credit(session, gid, INVITER + 7, 1, start=72000)
    for ad in (a, b):
        await free_ads.maybe_activate(session, ad, utcnow(), member_ok=True)
    await session.commit()
    b_due = b.next_post_at
    await send(session, dp, bot, callback_update(FreeCB(action="stop", group_id=gid).pack(),
                                                 user_id=INVITER, update_id=200))
    assert not (await free_ads.get_ad(session, INVITER, gid)).desired_running
    assert (await free_ads.get_ad(session, INVITER, gid)).next_post_at is None
    assert ensure_aware((await free_ads.get_ad(session, INVITER + 7, gid)).next_post_at) == ensure_aware(b_due)
    await send(session, dp, bot, callback_update(FreeCB(action="start", group_id=gid).pack(),
                                                 user_id=INVITER, update_id=201))
    a = await free_ads.get_ad(session, INVITER, gid)
    assert a.desired_running and a.next_post_at is not None
    assert ensure_aware(a.next_post_at) - utcnow() > timedelta(seconds=295)
    assert ensure_aware((await free_ads.get_ad(session, INVITER + 7, gid)).next_post_at) == ensure_aware(b_due)
    # /start bot menyusi Start/Stop tugmasi EMAS.
    await send(session, dp, bot, text_update("/start", user_id=INVITER, update_id=202))
    assert (await free_ads.get_ad(session, INVITER, gid)).next_post_at == a.next_post_at
    assert not fake.called("CreateChatInviteLink")


async def test_no_daily_quota_and_stale_sending_do_not_duplicate_posts(session, tg):
    fake, bot, _ = tg
    gid = await setup_free(session, n=1)
    group = await session.get(Group, gid)
    group.settings.daily_post_limit = 1  # tarixiy qiymat postga to'siq emas
    a = await free_draft(session, gid, INVITER)
    b = await free_draft(session, gid, INVITER + 7, caption="Boshqa odamning tasdiqlangan matni")
    await credit(session, gid, INVITER, 1, start=73000)
    await credit(session, gid, INVITER + 7, 1, start=74000)
    for ad in (a, b):
        await free_ads.maybe_activate(session, ad, utcnow(), member_ok=True)
        ad.next_post_at = utcnow() - timedelta(seconds=1)
    await session.commit()
    a_id, b_id = a.id, b.id
    assert await free_ads.due_one_per_group(session, utcnow()) == [a_id]
    await free_poster.post_one(bot, a_id)
    session.expire_all()
    assert (await session.get(Group, gid)).rotation.today_count == 1
    await free_poster.post_one(bot, b_id)
    b = await session.get(FreeAd, b_id)
    assert ensure_aware(b.next_post_at) > utcnow() + timedelta(minutes=5)
    assert len([p for p in fake.called("SendPhoto") if p["chat_id"] == GROUP_CHAT_ID]) == 2

    # Oldingi sending log noma'lum natija: restartda qayta yuborilmaydi.
    group = await session.get(Group, gid)
    b.next_post_at = utcnow() - timedelta(seconds=1)
    session.add(FreePostLog(free_ad_id=b.id, group_id=gid, user_id=b.user_id,
                            status="sending", created_at=utcnow() - timedelta(minutes=6)))
    await session.commit()
    assert await free_poster.recover_stale(bot) == 1
    session.expire_all()
    assert (await session.get(Group, gid)).paused_reason == "error"
    assert (await session.get(FreeAd, b_id)).desired_running is False
    await free_poster.post_one(bot, b_id)
    assert len([p for p in fake.called("SendPhoto") if p["chat_id"] == GROUP_CHAT_ID]) == 2
    assert (await session.execute(select(FreePostLog).where(
        FreePostLog.free_ad_id == b_id, FreePostLog.status == "uncertain",
    ))).scalar_one().status == "uncertain"


async def test_empty_paid_queue_does_not_pause_group_with_free_draft(session, tg):
    _, _, _ = tg
    gid = await setup_free(session, n=1)
    await free_ads.submit(session, INVITER, gid, "image", "Tasdiqni kutyapman")
    group = await session.get(Group, gid)
    group.rotation.next_post_at = utcnow() - timedelta(seconds=1)
    await session.commit()
    from app.services import posting_service
    async with session_scope() as other:
        claim, result = await posting_service.claim_post(other, gid, utcnow())
        assert claim is None and result.status == "empty" and not result.notify
    session.expire_all()
    group = await session.get(Group, gid)
    assert group.is_active and group.settings.posting_enabled
    assert group.rotation.next_post_at is None  # hech qanday pullik e'lon yo'q


async def test_free_unavailable_when_counter_is_dry_run_and_off(session, tg):
    fake, bot, dp = tg
    gid = await setup_free(session, n=1)
    setting = await session.get(CounterSetting, gid)
    setting.dry_run = True
    await session.commit()
    await send(session, dp, bot, callback_update(FreeCB(action="card", group_id=gid).pack(),
                                                 user_id=INVITER, update_id=300))
    assert "jonli sanoqchi yo'q" in fake.edited_texts()[-1]
    assert not await free_ads.terms(session, await session.get(Group, gid))
    with pytest.raises(ValueError):
        await free_ads.submit(session, INVITER, gid, "photo", "Salom, telefon sotiladi")
    assert (await session.execute(select(FreeAd))).scalars().all() == []
    assert not fake.called("CreateChatInviteLink")

async def test_group_free_opt_in_and_moderator_cannot_switch(session, tg):
    fake, bot, dp = tg
    gid = await setup_free(session, n=1)
    group = await session.get(Group, gid)
    group.settings.free_ads_enabled = False  # migratsiya default OFF
    session.add(Admin(user_id=333333, role=AdminRole.MODERATOR))
    await session.commit()
    await reset_dispatcher_state()  # yangi moderator rolini keshdan o'qisin
    try:
        await send(session, dp, bot, callback_update(GroupCB(action="free_ads", group_id=gid).pack(),
                                                     user_id=333333, update_id=400))
        assert not (await session.get(Group, gid)).settings.free_ads_enabled
        with pytest.raises(ValueError):
            await free_ads.submit(session, INVITER, gid, "photo", "Sotiladigan mahsulot")
        await send(session, dp, bot, callback_update(GroupCB(action="free_ads", group_id=gid).pack(),
                                                     user_id=ADMIN_ID, update_id=401))
        assert (await session.get(Group, gid)).settings.free_ads_enabled
        ad = await free_draft(session, gid, INVITER)
        await credit(session, gid, INVITER, 1, start=85000)
        await free_ads.maybe_activate(session, ad, utcnow(), member_ok=True)
        ad.next_post_at = utcnow() - timedelta(seconds=1)
        await session.commit()
        aid = ad.id
        await send(session, dp, bot, callback_update(GroupCB(action="free_ads", group_id=gid).pack(),
                                                     user_id=ADMIN_ID, update_id=402))
        assert not (await session.get(Group, gid)).settings.free_ads_enabled
        await free_poster.post_one(bot, aid)
        assert not [p for p in fake.called("SendPhoto") if p["chat_id"] == GROUP_CHAT_ID]
        await send(session, dp, bot, callback_update(GroupCB(action="free_ads", group_id=gid).pack(),
                                                     user_id=ADMIN_ID, update_id=403))
        ad = await session.get(FreeAd, aid)
        assert ensure_aware(ad.next_post_at) > utcnow() + timedelta(minutes=4)
        assert (await session.execute(select(ActionLog).where(
            ActionLog.action == "free_ads_switch", ActionLog.group_id == gid,
        ))).scalars().all()
    finally:
        await reset_dispatcher_state()


async def test_free_rule_interval_change_and_global_pause_rebase_free_due(session, tg):
    fake, bot, dp = tg
    gid = await setup_free(session, n=1)
    ad = await free_draft(session, gid, INVITER)
    await credit(session, gid, INVITER, 1, start=86000)
    await free_ads.maybe_activate(session, ad, utcnow(), member_ok=True)
    await session.commit()
    await send(session, dp, bot, callback_update(FreeModCB(action="rule_interval").pack(),
                                                 update_id=900))
    await send(session, dp, bot, text_update("10", update_id=901))
    ad = await free_ads.get_ad(session, INVITER, gid)
    assert ensure_aware(ad.next_post_at) > utcnow() + timedelta(minutes=9)

    ad_id = ad.id
    ad.next_post_at = utcnow() - timedelta(seconds=1)
    await session.commit()
    await settings_service.set(session, "posting_enabled_global", False)
    await session.commit()
    await jobs.free_posting_tick_job(bot)
    session.expire_all()
    ad = await session.get(FreeAd, ad_id)
    assert ensure_aware(ad.next_post_at) > utcnow() + timedelta(minutes=9)
    assert not [p for p in fake.called("SendPhoto") if p["chat_id"] == GROUP_CHAT_ID]


def test_free_caption_uses_telegram_utf16_limit_and_no_album() -> None:
    assert free_ads.valid_caption("Telefon yaxshi, @mijoz")
    assert not free_ads.valid_caption("📱" * 500)  # 1000 UTF-16 unit > 900
    assert not free_ads.valid_caption("salom")
    assert not free_ads.valid_caption("a" * 901)


async def test_album_rejected_and_unapproved_photo_never_posted(session, tg):
    fake, bot, dp = tg
    gid = await setup_free(session, n=1)
    await send(session, dp, bot, callback_update(FreeCB(action="photo", group_id=gid).pack(),
                                                 user_id=INVITER, update_id=510))
    raw = photo_update(caption="Telefon sotiladi @mijoz", user_id=INVITER, update_id=511)
    album = raw.model_copy(update={"message": raw.message.model_copy(update={"media_group_id": "album-1"})})
    await send(session, dp, bot, album)
    assert "albom emas" in fake.sent_texts()[-1]
    assert not fake.called("SendPhoto")
    assert not (await session.execute(select(FreeAd))).scalars().all()


async def test_admin_can_revoke_approved_ad_without_affecting_other_group(session, tg):
    fake, bot, dp = tg
    gid = await setup_free(session, n=1)
    group2 = await setup_free(session, n=1, chat_id=-1002003004001)
    for group_id, invited_id in ((gid, 8815001), (group2, 8815002)):
        await credit(session, group_id, INVITER, 1, start=invited_id)
        ad = await free_draft(session, group_id, INVITER)
        assert await free_ads.maybe_activate(session, ad, utcnow(), member_ok=True)
    await session.commit()
    first = await free_ads.get_ad(session, INVITER, gid)
    other = await free_ads.get_ad(session, INVITER, group2)
    assert first and first.next_post_at and other and other.next_post_at
    first_id = first.id
    with pytest.raises(ValueError, match="o'zgargan"):
        await free_ads.revoke(session, first_id, first.revision + 1, ADMIN_ID)
    assert first.review_status == "approved"
    in_flight = FreePostLog(free_ad_id=first_id, group_id=gid, user_id=INVITER,
                            status="sending")
    session.add(in_flight)
    await session.commit()
    with pytest.raises(ValueError, match="yuborilmoqda"):
        await free_ads.revoke(session, first_id, first.revision, ADMIN_ID)
    in_flight.status = "sent"
    await session.commit()
    await free_ads.revoke(session, first_id, first.revision, ADMIN_ID)
    await session.commit()
    assert first.review_status == "rejected" and first.next_post_at is None
    await free_ads.set_running(session, first, True)  # user Start tasdiqni aylanib o'tmaydi
    assert first.next_post_at is None
    assert other.review_status == "approved" and other.next_post_at
    assert first.approved_photo_id is None and first.approved_caption is None
    assert other.approved_photo_id == "test-photo"


async def test_admin_revoke_confirmation_stops_ad_and_notifies_user(session, tg):
    fake, bot, dp = tg
    gid = await setup_free(session, n=1)
    ad = await free_draft(session, gid, INVITER)
    ad_id, revision = ad.id, ad.revision
    await send(session, dp, bot, callback_update(
        FreeModCB(action="card", ad_id=ad_id).pack(), update_id=520))
    assert "✅" in fake.edited_texts()[-1]
    await send(session, dp, bot, callback_update(
        FreeModCB(action="revoke_confirm", ad_id=ad_id, revision=revision).pack(), update_id=521))
    assert "bekor qilasizmi" in fake.edited_texts()[-1]
    assert (await session.get(FreeAd, ad_id)).review_status == "approved"
    await send(session, dp, bot, callback_update(
        FreeModCB(action="revoke", ad_id=ad_id, revision=revision).pack(), update_id=522))
    assert (await session.get(FreeAd, ad_id)).review_status == "rejected"
    assert any(p.get("chat_id") == INVITER and "tasdig'ini bekor qildi" in p.get("text", "")
               for p in fake.called("SendMessage"))
    assert int((await session.execute(select(func.count(ActionLog.id)).where(
        ActionLog.action == "free_ad_revoke"))).scalar_one()) == 1


async def test_free_retention_removes_old_finished_but_keeps_unknown_posts(session, tg):
    gid = await setup_free(session, n=1)
    ad = await free_draft(session, gid, INVITER)
    old = utcnow() - timedelta(days=91)
    logs = [FreePostLog(free_ad_id=ad.id, group_id=gid, user_id=INVITER, status=status)
            for status in ("sent", "retry", "error", "skipped", "uncertain", "sending")]
    session.add_all(logs)
    await session.flush()
    for log in logs:
        log.created_at = old
    await session.commit()
    await jobs.retention_job()
    session.expire_all()
    remaining = (await session.execute(select(FreePostLog.status))).scalars().all()
    assert set(remaining) == {"uncertain", "sending"}
