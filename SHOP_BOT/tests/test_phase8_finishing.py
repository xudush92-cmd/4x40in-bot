"""Phase 8 qoldiq UI: tarif cheklovi, toifalangan e'lon, admin rollari."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.constants import AdminRole
from app.db.models import ActionLog, Ad, Admin, Category, Group, PostLog, Tariff
from app.handlers.seller.ads import _active_categories
from app.keyboards.callbacks import AdCB, AdminCB, AdminOpsCB, TariffCB
from app.services import admin_service, seller_service, subscription_service, tariff_service
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


async def test_tariff_click_restrictions_immediately_filter_seller_wizard(session):
    group_a = Group(tg_chat_id=-1001001001, title="Guruh A")
    group_b = Group(tg_chat_id=-1001001002, title="Guruh B")
    session.add_all([group_a, group_b])
    await session.flush()
    ca = Category(group_id=group_a.id, name="Telefonlar")
    cb = Category(group_id=group_b.id, name="Kompyuterlar")
    session.add_all([ca, cb])
    seller, _ = await seller_service.get_or_create_seller(session, 8001, display_name="Sinov")
    tariff = await tariff_service.create_tariff(session, name="Tanlov", price=10000)
    await subscription_service.grant(session, seller, tariff)
    session.add(Admin(user_id=ADMIN_ID, role=AdminRole.SUPER))
    await session.commit()
    sid, tid, ca_id, cb_id, ga_id = seller.id, tariff.id, ca.id, cb.id, group_a.id
    await reset_dispatcher_state()
    fake = FakeSession()
    bot, dp = make_bot(fake), make_dispatcher()

    async def click(n: int, action: str, value: str):
        await dp.feed_update(bot, callback_update(
            TariffCB(action=action, tariff_id=tid, value=value).pack(), update_id=n))
        session.expire_all()

    await click(1, "restr", "c|0")
    assert "hammasi (cheklovsiz)" in fake.edited_texts()[-1]
    await click(2, "pick", f"c|{ca_id}|0")
    assert (await session.get(Tariff, tid)).allowed_category_ids == [ca_id]
    await click(3, "pick", f"g|{ga_id}|0")
    tariff = await session.get(Tariff, tid)
    assert tariff.allowed_group_ids == [ga_id]
    seller = await session.get(__import__("app.db.models", fromlist=["Seller"]).Seller, sid)
    assert [c.id for c in await _active_categories(session, seller)] == [ca_id]
    await dp.feed_update(bot, callback_update(AdCB(action="wiz_cat", value=str(cb_id)).pack(),
                                              user_id=seller.user_id, update_id=4))
    assert any("ruxsat bermaydi" in s for s in fake.answers())
    assert not (await session.execute(select(Ad))).scalars().all()
    await click(5, "unlimit", "c|0")
    await click(6, "unlimit", "g|0")
    tariff = await session.get(Tariff, tid)
    assert tariff.allowed_category_ids is None and tariff.allowed_group_ids is None
    assert len((await session.execute(select(ActionLog).where(
        ActionLog.action == "tariff_restriction"))).scalars().all()) == 4
    await bot.session.close()
    await reset_dispatcher_state()


async def test_seller_category_headings_and_daily_ad_chart(session):
    seller, _ = await seller_service.get_or_create_seller(session, 8811, display_name="Dokon")
    group = Group(tg_chat_id=-1008811, title="Dokon guruhi")
    session.add(group)
    await session.flush()
    c1 = Category(group_id=group.id, name="Telefonlar")
    c2 = Category(group_id=group.id, name="Noutbuklar")
    session.add_all([c1, c2])
    await session.flush()
    tariff = await tariff_service.create_tariff(session, name="Grafik", price=10000)
    await subscription_service.grant(session, seller, tariff)
    a = Ad(seller_id=seller.id, category_id=c1.id, title="iPhone", status="active")
    b = Ad(seller_id=seller.id, category_id=c2.id, title="MacBook", status="active")
    session.add_all([a, b])
    await session.flush()
    session.add_all([
        PostLog(group_id=group.id, ad_id=a.id, status="ok", created_at=utcnow()),
        PostLog(group_id=group.id, ad_id=a.id, status="ok", created_at=utcnow()),
        PostLog(group_id=group.id, ad_id=a.id, status="error", created_at=utcnow()),
        PostLog(group_id=group.id, ad_id=a.id, status="ok", created_at=utcnow() - timedelta(days=1)),
    ])
    await session.commit()
    aid = a.id
    await reset_dispatcher_state()
    fake = FakeSession()
    bot, dp = make_bot(fake), make_dispatcher()
    await dp.feed_update(bot, callback_update(AdCB(action="list").pack(), user_id=8811,
                                              update_id=1))
    listing = fake.edited_texts()[-1]
    assert "🗂 <b>Telefonlar</b>" in listing and "🗂 <b>Noutbuklar</b>" in listing
    await dp.feed_update(bot, callback_update(AdCB(action="stats", ad_id=aid).pack(),
                                              user_id=8811, update_id=2))
    assert "7 kunlik joylash grafigi" in fake.edited_texts()[-1]
    assert "Jami davrda: <b>3</b>" in fake.edited_texts()[-1]
    await dp.feed_update(bot, callback_update(AdCB(action="stats_30", ad_id=aid).pack(),
                                              user_id=8811, update_id=3))
    assert "30 kunlik joylash grafigi" in fake.edited_texts()[-1]
    await bot.session.close()
    await reset_dispatcher_state()


async def test_admin_role_ui_audit_and_protected_super(session):
    session.add(Admin(user_id=ADMIN_ID, role=AdminRole.SUPER))
    await session.commit()
    await reset_dispatcher_state()
    fake = FakeSession()
    bot, dp = make_bot(fake), make_dispatcher()

    async def click(n: int, action: str, admin_id: int = 0, value: str = "-"):
        await dp.feed_update(bot, callback_update(AdminOpsCB(action=action, admin_id=admin_id,
                                                              value=value).pack(), update_id=n))
        session.expire_all()

    await dp.feed_update(bot, callback_update(AdminCB(action="section", value="admins").pack(), update_id=1))
    assert "Adminlarni boshqarish" in fake.edited_texts()[-1]
    await click(2, "add")
    await dp.feed_update(bot, text_update("80088", update_id=3))
    await click(4, "add_role", value="moderator")
    await click(5, "add_confirm", 80088, "moderator")
    assert (await session.execute(select(Admin).where(Admin.user_id == 80088))).scalar_one().role == "moderator"
    await click(6, "role_ask", 80088, "admin")
    await click(7, "role_apply", 80088, "admin")
    assert (await session.execute(select(Admin).where(Admin.user_id == 80088))).scalar_one().role == "admin"
    await click(8, "stop_apply", 80088)
    assert not (await session.execute(select(Admin).where(Admin.user_id == 80088))).scalar_one().is_active
    assert len((await session.execute(select(ActionLog).where(
        ActionLog.entity == "admin", ActionLog.entity_id == 80088))).scalars().all()) == 3
    with pytest.raises(admin_service.AdminError):
        await admin_service.modify(session, ADMIN_ID, ADMIN_ID, role=AdminRole.MODERATOR)
    with pytest.raises(admin_service.AdminError):
        await admin_service.modify(session, ADMIN_ID, ADMIN_ID, deactivate=True)
    await bot.session.close()
    await reset_dispatcher_state()


async def test_moderator_cannot_change_legacy_group_category_or_global_settings(session):
    """Yangi rol qo'shilgach, Phase 1/6 tugmalari eski xabarda qolsa ham o'zgartirmaydi."""
    group = Group(tg_chat_id=-100900009, title="Rol sinovi")
    session.add(group)
    await session.flush()
    category = Category(group_id=group.id, name="Boshlang'ich")
    session.add_all([category, Admin(user_id=80088, role=AdminRole.MODERATOR)])
    await session.commit()
    gid, cid = group.id, category.id
    await reset_dispatcher_state()
    fake = FakeSession()
    bot, dp = make_bot(fake), make_dispatcher()
    from app.keyboards.callbacks import CategoryCB, FeatureCB, GroupCB
    from app.services.settings_service import settings_service

    payloads = [
        FeatureCB(group_id=gid, feature="posting", enabled=True).pack(),
        GroupCB(action="toggle", group_id=gid, value="protect").pack(),
        GroupCB(action="refresh", group_id=gid).pack(),
        GroupCB(action="delete_confirm", group_id=gid).pack(),
        CategoryCB(action="active", category_id=cid).pack(),
        CategoryCB(action="delete_confirm", category_id=cid).pack(),
        AdminCB(action="toggle", value="kill_switch").pack(),
        AdminCB(action="toggle", value="maintenance_mode").pack(),
    ]
    for n, payload in enumerate(payloads, start=1):
        await dp.feed_update(bot, callback_update(payload, user_id=80088, update_id=n))
    session.expire_all()
    assert await session.get(Group, gid) is not None
    assert (await session.get(Category, cid)).is_active
    assert not await settings_service.get("kill_switch", False, session)
    assert not await settings_service.get("maintenance_mode", False, session)
    assert all("faqat admin" in answer.lower() for answer in fake.answers()[-len(payloads):])
    # Ro'yxatni ko'rish va navigatsiya esa moderator uchun ochiq qoladi.
    await dp.feed_update(bot, callback_update(GroupCB(action="list").pack(),
                                              user_id=80088, update_id=20))
    await dp.feed_update(bot, callback_update(CategoryCB(action="list").pack(),
                                              user_id=80088, update_id=21))
    assert "Toifalar" in fake.edited_texts()[-1]
    await bot.session.close()
    await reset_dispatcher_state()
