"""Phase 8 admin matn va xato panellari: haqiqiy dispatcher, offline Telegram."""

from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.constants import AdminRole
from app.db.models import ActionLog, Admin, BotText, ErrorLog
from app.keyboards.callbacks import AdminCB, ErrorCB, TextCB
from app.scheduler.jobs import retention_job
from app.services import error_service
from app.services.text_service import text_service, update_template, validate_template
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


async def click(session, bot, dp, data: str, n: int):
    await dp.feed_update(bot, callback_update(data, update_id=n))
    session.expire_all()


async def test_template_validation_and_cache_commit(session):
    key = "start.user"
    for value in ("", "<script>bad</script>", "<b>unclosed", "{__class__}", "{ism.upper}",
                  "{nope}", "say < 3", "you & me", "{", "x" * 2801):
        with pytest.raises(ValueError):
            validate_template(key, value)
    with pytest.raises(ValueError):
        validate_template("unknown.key", "salom")
    row = await update_template(session, key, "<b>Salom {ism}</b>!", ADMIN_ID)
    assert row.is_custom and row.updated_by == ADMIN_ID
    await session.commit()
    await text_service.publish()
    assert await text_service.get(key, ism="Ali") == "<b>Salom Ali</b>!"
    assert (await session.execute(select(ActionLog).where(
        ActionLog.action == "bot_text_change",
    ))).scalar_one().entity_id == row.id
    await update_template(session, key, None, ADMIN_ID)
    await session.commit()
    await text_service.publish()
    assert "Assalomu" in await text_service.get(key, ism="Ali", yordam="@admin")


async def test_text_admin_editor_and_moderator_read_only(session, tg):
    fake, bot, dp = tg
    await click(session, bot, dp, AdminCB(action="section", value="texts").pack(), 1)
    assert "Bot matnlari" in fake.edited_texts()[-1]
    await click(session, bot, dp, TextCB(action="card", key="start.user").pack(), 2)
    await click(session, bot, dp, TextCB(action="edit", key="start.user").pack(), 3)
    await dp.feed_update(bot, text_update("<b>Salom {ism}</b>", update_id=4))
    session.expire_all()
    row = (await session.execute(select(BotText).where(BotText.key == "start.user"))).scalar_one()
    assert row.is_custom and row.text == "<b>Salom {ism}</b>"
    row_id = row.id
    await click(session, bot, dp, TextCB(action="preview", key="start.user").pack(), 5)
    assert "<b>Salom Namuna</b>" in fake.edited_texts()[-1]
    await click(session, bot, dp, TextCB(action="reset", key="start.user").pack(), 6)
    session.expire_all()
    assert not (await session.get(BotText, row_id)).is_custom

    admin = (await session.execute(select(Admin).where(Admin.user_id == ADMIN_ID))).scalar_one()
    admin.role = AdminRole.MODERATOR
    await session.commit()
    await reset_dispatcher_state()
    await click(session, bot, dp, TextCB(action="edit", key="start.user").pack(), 7)
    assert any("ruxsat" in answer.lower() for answer in fake.answers())
    await click(session, bot, dp, TextCB(action="reset", key="start.user").pack(), 8)
    assert not (await session.get(BotText, row_id)).is_custom


async def test_error_filters_details_resolve_audit_and_retention(session, tg):
    fake, bot, dp = tg
    old = ErrorLog(source="poster", message="Xato <500>", is_critical=True,
                   traceback="Trace & details", context={"msg": "<broken>"})
    session.add(old)
    await session.flush()
    eid = old.id
    old.created_at = utcnow() - timedelta(days=400)
    session.add(ErrorLog(source="handler", message="Past xato", resolved_at=utcnow(),
                         resolved_by=ADMIN_ID))
    await session.commit()
    await click(session, bot, dp, AdminCB(action="section", value="errors").pack(), 1)
    assert "Xatolar jurnali" in fake.edited_texts()[-1]
    await click(session, bot, dp, ErrorCB(action="card", error_id=eid).pack(), 2)
    assert "Xato &lt;500&gt;" in fake.edited_texts()[-1]
    await click(session, bot, dp, ErrorCB(action="resolve", error_id=eid).pack(), 3)
    assert (await session.get(ErrorLog, eid)).resolved_by == ADMIN_ID
    assert not await error_service.resolve(session, eid, ADMIN_ID)  # dublikat audit yo'q
    assert len((await session.execute(select(ActionLog).where(
        ActionLog.action == "error_resolved",
    ))).scalars().all()) == 1
    await session.commit()
    await retention_job()
    session.expire_all()
    assert await session.get(ErrorLog, eid) is None

    pending = ErrorLog(source="handler", message="Hal qilinmagan")
    session.add(pending)
    await session.flush()
    pending.created_at = utcnow() - timedelta(days=400)
    pending_id = pending.id
    await session.commit()
    await retention_job()
    session.expire_all()
    assert await session.get(ErrorLog, pending_id) is not None  # ochiq xato o'chmaydi
