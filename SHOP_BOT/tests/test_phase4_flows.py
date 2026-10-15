"""Phase 4: admin tugmalari → navbat → tartib → qo'lda joylash (offline E2E)."""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select

from app.constants import AdminRole
from app.db.base import session_scope
from app.db.models import Ad, Admin, CleanerSetting
from app.keyboards.callbacks import GroupCB, ModCB, PostingCB
from app.scheduler import poster
from tests.fake_telegram import (
    ADMIN_ID,
    FakeSession,
    callback_update,
    make_bot,
    make_dispatcher,
    reset_dispatcher_state,
)
from tests.test_posting_service import setup

MOD_ID = 787878


@pytest_asyncio.fixture
async def tg(clean_db, monkeypatch):
    await reset_dispatcher_state()
    async def fast(*args, **kwargs):
        pass
    monkeypatch.setattr(poster.posting_limiter, "acquire", fast)
    fake = FakeSession()
    bot = make_bot(fake)
    dp = make_dispatcher()
    async with session_scope() as session:
        session.add(Admin(user_id=ADMIN_ID, role=AdminRole.SUPER))
        session.add(Admin(user_id=MOD_ID, role=AdminRole.MODERATOR))
        group, category, ads, _, _, _ = await setup(session, count=2)
        ids = (group.id, category.id, ads[0].id, ads[1].id)
    yield fake, bot, dp, ids
    await bot.session.close()
    await reset_dispatcher_state()


async def test_queue_reorder_and_send_button(tg) -> None:
    fake, bot, dp, (group_id, cat_id, first, second) = tg
    await dp.feed_update(bot, callback_update(GroupCB(action="card", group_id=group_id).pack(), update_id=1))
    card = fake.called("EditMessageText")[-1]
    card_callbacks = [b["callback_data"] for row in card["reply_markup"]["inline_keyboard"] for b in row]
    assert PostingCB(action="group", target_id=group_id).pack() in card_callbacks

    await dp.feed_update(bot, callback_update(PostingCB(action="group", target_id=group_id).pack(), update_id=2))
    assert "Telefonlar — e'lon navbati" in fake.edited_texts()[-1]
    await dp.feed_update(bot, callback_update(PostingCB(action="queue", target_id=cat_id).pack(), update_id=3))
    assert "Hali e'lon joylanmagan" in fake.edited_texts()[-1]
    await dp.feed_update(bot, callback_update(
        PostingCB(action="up", target_id=second, value=f"{cat_id}|0").pack(), update_id=4,
    ))
    async with session_scope() as session:
        ordered = (await session.execute(select(Ad).order_by(Ad.position, Ad.id))).scalars().all()
        assert [ad.id for ad in ordered] == [second, first]

    await dp.feed_update(bot, callback_update(PostingCB(action="send", target_id=second).pack(), update_id=5))
    assert any("joylandi" in text for text in fake.answers())
    async with session_scope() as session:
        assert (await session.get(Ad, second)).post_count == 1
    assert fake.called("SendMessage")  # guruhga aloqa reply xabari (rasm yo'q: text fallback)


def test_callback_length() -> None:
    cb = PostingCB(action="down", target_id=999999999, value="999999999|99999").pack()
    assert len(cb.encode("utf-8")) <= 64


async def test_moderator_cannot_send_or_reorder(tg) -> None:
    fake, bot, dp, (group_id, cat_id, first, second) = tg
    for n, data in enumerate((
        PostingCB(action="send", target_id=first).pack(),
        PostingCB(action="up", target_id=second, value=f"{cat_id}|0").pack(),
    ), start=1):
        await dp.feed_update(bot, callback_update(data, user_id=MOD_ID, update_id=80 + n))
    assert all("faqat admin" in answer for answer in fake.answers())
    assert not fake.called("SendMediaGroup")
    async with session_scope() as session:
        assert (await session.get(Ad, first)).post_count == 0
        assert (await session.get(Ad, second)).position > (await session.get(Ad, first)).position


async def test_group_old_ads_toggle(tg) -> None:
    fake, bot, dp, (group_id, cat_id, first, second) = tg
    cb = GroupCB(action="old_ads", group_id=group_id).pack()
    await dp.feed_update(bot, callback_update(cb, update_id=10))
    assert "eng oxirgisi qoladi" in fake.edited_texts()[-1]
    async with session_scope() as session:
        policy = await session.get(CleanerSetting, group_id)
        assert policy and policy.enabled and policy.delete_old_ads and policy.keep_last_ads == 1
    await dp.feed_update(bot, callback_update(cb, update_id=11))
    async with session_scope() as session:
        assert (await session.get(CleanerSetting, group_id)).delete_old_ads is False


async def test_manual_button_on_admin_ad_card(tg) -> None:
    fake, bot, dp, (group_id, cat_id, first, second) = tg
    await dp.feed_update(bot, callback_update(ModCB(action="ads_card", ad_id=first, value="0|all").pack(), update_id=33))
    buttons = [b["callback_data"] for row in fake.called("EditMessageText")[-1]["reply_markup"]["inline_keyboard"] for b in row]
    assert PostingCB(action="send", target_id=first, value="0|all").pack() in buttons
