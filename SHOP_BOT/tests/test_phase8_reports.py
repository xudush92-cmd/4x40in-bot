"""Kunlik mahalliy jamlanma, guruh taqsimoti, grafik va CSV."""

from __future__ import annotations

import csv
from datetime import UTC, datetime, time
from decimal import Decimal
from io import StringIO
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.constants import AdminRole, PaymentStatus
from app.db.models import (
    ActionLog,
    Ad,
    Admin,
    Category,
    CleanupLog,
    Group,
    GroupMessageAction,
    InviteEvent,
    Payment,
    PostLog,
    StatsDaily,
    Violation,
)
from app.keyboards.callbacks import AdminCB, StatsCB
from app.scheduler.jobs import daily_stats_job
from app.services import report_service, seller_service, tariff_service
from tests.fake_telegram import (
    ADMIN_ID,
    FakeSession,
    callback_update,
    make_bot,
    make_dispatcher,
    reset_dispatcher_state,
)


async def seed(session):
    d = await report_service.last_closed_day(session)
    midday = datetime.combine(d, time(13, 30), tzinfo=ZoneInfo("Asia/Tashkent")).astimezone(UTC)
    g1 = Group(tg_chat_id=-10011001, title="=Formula test")
    g2 = Group(tg_chat_id=-10011002, title="Ikkinchi guruh")
    session.add_all([g1, g2])
    await session.flush()
    seller, _ = await seller_service.get_or_create_seller(session, 1337, display_name="Sotuvchi")
    seller.created_at = midday
    tariff = await tariff_service.create_tariff(session, name="Sotuvchi tarifi", price="10000")
    c = Category(group_id=g1.id, name="Telefonlar")
    session.add(c)
    await session.flush()
    session.add(Ad(seller_id=seller.id, category_id=c.id, title="iPhone", status="active"))
    session.add_all([
        PostLog(group_id=g1.id, status="ok", created_at=midday),
        PostLog(group_id=g1.id, status="ok", created_at=midday),
        PostLog(group_id=g2.id, status="error", created_at=midday),
        InviteEvent(group_id=g1.id, invitee_id=503, counted=True, created_at=midday),
        Violation(group_id=g1.id, user_id=503, kind="test", created_at=midday),
        CleanupLog(group_id=g1.id, deleted_count=2, created_at=midday),
        GroupMessageAction(group_id=g1.id, message_id=919, source="guard", kind="filter",
                           planned_action="delete", status="done", updated_at=midday),
        Payment(seller_id=seller.id, tariff_id=tariff.id, amount=Decimal("10000"),
                status=PaymentStatus.APPROVED, decided_at=midday),
        Payment(seller_id=seller.id, tariff_id=tariff.id, amount=Decimal("55555"),
                status=PaymentStatus.REJECTED, decided_at=midday),
    ])
    await session.commit()
    return d, g1.id, g2.id


async def test_local_daily_group_rows_approved_only_idempotent_csv(session):
    d, gid, gid2 = await seed(session)
    assert await report_service.rollup_day(session, d, ZoneInfo("Asia/Tashkent")) == 3
    await session.commit()
    rows = (await session.execute(select(StatsDaily).where(StatsDaily.day == d))).scalars().all()
    assert len(rows) == 3
    by_group = {r.group_id: r for r in rows}
    assert by_group[gid].posts == 2 and by_group[gid2].posts == 0
    assert by_group[gid].joins == 1 and by_group[gid].violations == 1
    assert by_group[gid].deleted_msgs == 3 and by_group[gid].active_ads == 1
    assert by_group[gid].payments_amount == 0  # to'lov guruhga tegishli emas
    assert by_group[0].payments_amount == Decimal("10000")  # rad etilgan chek hisoblanmaydi
    assert by_group[0].new_sellers == 1
    await daily_stats_job()  # xuddi shu kunni qayta hisoblash PK dublikat bermaydi
    session.expire_all()
    assert len((await session.execute(select(StatsDaily))).scalars().all()) == 3
    series = await report_service.day_series(session, 7, gid)
    assert series[-1].posts == 2 and series[0] is None
    assert report_service.sparkline([0, 1, 4]) == "·▃█"
    data = await report_service.csv_export(session, 7)
    assert data.startswith(b"\xef\xbb\xbf")
    parsed = list(csv.DictReader(StringIO(data.decode("utf-8-sig"))))
    assert len(parsed) == 3
    assert any(row["guruh"] == "'=Formula test" for row in parsed)
    assert all(row["tasdiqlangan_bank_uzs"] == "0.00" for row in parsed if row["guruh_id"] != "0")


async def test_stats_admin_charts_export_and_moderator_restriction(session):
    _, gid, _ = await seed(session)
    await daily_stats_job()
    session.add(Admin(user_id=ADMIN_ID, role=AdminRole.SUPER))
    await session.commit()
    await reset_dispatcher_state()
    fake = FakeSession()
    bot, dp = make_bot(fake), make_dispatcher()
    await dp.feed_update(bot, callback_update(AdminCB(action="section", value="stats").pack(), update_id=1))
    assert "Statistika" in fake.edited_texts()[-1]
    await dp.feed_update(bot, callback_update(StatsCB(action="trend", group_id=gid, days=7).pack(), update_id=2))
    assert "Telefon" not in fake.edited_texts()[-1]
    assert "=Formula test" in fake.edited_texts()[-1]
    await dp.feed_update(bot, callback_update(StatsCB(action="csv", group_id=gid, days=7).pack(), update_id=3))
    assert len(fake.called("SendDocument")) == 1
    session.expire_all()
    row = (await session.execute(select(Admin).where(Admin.user_id == ADMIN_ID))).scalar_one()
    row.role = AdminRole.MODERATOR
    await session.commit()
    await reset_dispatcher_state()
    await dp.feed_update(bot, callback_update(StatsCB(action="csv", group_id=gid, days=7).pack(), update_id=4))
    assert len(fake.called("SendDocument")) == 1
    assert any("faqat admin" in answer for answer in fake.answers())
    assert not (await session.execute(select(ActionLog).where(ActionLog.action == "broadcast_confirm"))).scalars().all()
    await bot.session.close()
    await reset_dispatcher_state()
