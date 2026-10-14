"""Phase 1: admin panel oqimlarining to'liq (E2E) sinovi.

Haqiqiy `Dispatcher`, middleware'lar, filterlar, FSM va handler'lar ishlaydi;
faqat Bot API chaqiruvlari `FakeSession` orqali ushlanadi (tarmoq kerak emas).

Bu testlar Phase 0 dagi uchta jiddiy runtime xatosini ham qamrab oladi:
  * `F.chat.type` callback_query uchun ishlamaydi → `PrivateChat()` filtri;
  * filtr imzosi aiogram 3 da `(event, **kwargs)` bo'lishi shart;
  * FSM sozlamalar tugmalari `value` o'rniga `action` yuboradi.
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select

from app.constants import AdminRole
from app.db.models import Admin, Category, CategoryRotation, Group, GroupSettings
from app.keyboards.callbacks import AdminCB, CategoryCB, FeatureCB, GroupCB
from tests.fake_telegram import (
    ADMIN_ID,
    GROUP_CHAT_ID,
    FakeSession,
    bot_added_update,
    bot_removed_update,
    callback_update,
    make_bot,
    make_dispatcher,
    reset_dispatcher_state,
    text_update,
)

CB_GROUPS = GroupCB(action="list").pack()
CB_CATEGORIES = CategoryCB(action="list").pack()
CB_MENU = AdminCB(action="menu").pack()


@pytest_asyncio.fixture
async def tg(session):
    """Admin + bot + dispatcher: real oqim uchun tayyor muhit."""
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
    """Update'ni dispatcher'ga uzatish va test sessiyasi keshini yangilash.

    Muhim: handler'lar o'z sessiyasida yozadi, shuning uchun keyin har doim
    yangi SELECT bilan o'qish kerak (`_group`, `_settings`, ...).
    """
    await dp.feed_update(bot, update)
    session.expire_all()


async def _group(session) -> Group:
    return (await session.execute(select(Group).where(Group.tg_chat_id == GROUP_CHAT_ID))).scalar_one()


async def _settings(session, group_id: int) -> GroupSettings:
    return (
        await session.execute(select(GroupSettings).where(GroupSettings.group_id == group_id))
    ).scalar_one()


async def _categories(session) -> list[Category]:
    return list((await session.execute(select(Category).order_by(Category.position))).scalars().all())


async def _category(session, category_id: int) -> Category:
    return (await session.execute(select(Category).where(Category.id == category_id))).scalar_one()


async def _rotation(session, category_id: int) -> CategoryRotation:
    return (
        await session.execute(
            select(CategoryRotation).where(CategoryRotation.category_id == category_id)
        )
    ).scalar_one()


# ═══════════ 1. Bot guruhga qo'shilishi va guruh yaratilishi ═══════
async def test_bot_added_creates_group_and_notifies_admin(session, tg) -> None:
    fake, bot, dp = tg

    await _feed(session, dp, bot, 1, bot_added_update(is_admin=True))

    group = await _group(session)
    assert group.title == "📱 Telefonlar bozori"
    assert group.is_supergroup is True
    assert group.bot_is_admin is True

    settings = await _settings(session, group.id)
    assert settings.posting_enabled is False       # yangi guruh — hammasi o'chiq
    assert settings.interval_sec == 1800           # standart 30 daqiqa
    assert settings.jitter_percent == 10

    # Adminga guruh haqida xabar ketdi
    assert any("Guruh" in text for text in fake.sent_texts())


async def test_bot_removed_pauses_group(session, tg) -> None:
    fake, bot, dp = tg
    await _feed(session, dp, bot, 1, bot_added_update())
    await _feed(session, dp, bot, 2, bot_removed_update())

    group = await _group(session)
    assert group.is_active is False
    assert group.paused_reason == "bot_left"


# ═══════════════════════ 2. Guruhlar bo'limi ═══════════════════════
async def test_groups_list_and_card(session, tg) -> None:
    fake, bot, dp = tg
    await _feed(session, dp, bot, 1, bot_added_update())

    # Ro'yxat
    await _feed(session, dp, bot, 2, callback_update(CB_GROUPS))
    listing = fake.edited_texts()[-1]
    assert "Guruhlar" in listing
    assert "Jami: <b>1</b>" in listing

    # Kartochka
    group = await _group(session)
    await _feed(session, dp, bot, 3, callback_update(GroupCB(action="card", group_id=group.id).pack()))
    card = fake.edited_texts()[-1]
    assert "📱 Telefonlar bozori" in card
    assert "🆔 <code>-1002003004000</code>" in card
    assert "supergroup ✅" in card
    assert "30 daqiqa" in card
    assert "Toifalar: <b>0</b>" in card


async def test_feature_toggle_rerenders_correct_screen(session, tg) -> None:
    fake, bot, dp = tg
    await _feed(session, dp, bot, 1, bot_added_update())
    group_id = (await _group(session)).id

    # Sozlamalar ekranidan «joylash»ni yoqish
    await _feed(
        session,
        dp,
        bot,
        2,
        callback_update(
            FeatureCB(group_id=group_id, feature="posting", enabled=True, origin="settings").pack()
        ),
    )
    assert (await _settings(session, group_id)).posting_enabled is True
    assert any("E'lon joylash" in text for text in fake.answers())

    # Matritsadan o'chirish → matritsa ekrani qayta chiziladi
    await _feed(
        session,
        dp,
        bot,
        3,
        callback_update(
            FeatureCB(group_id=group_id, feature="posting", enabled=False, origin="matrix").pack()
        ),
    )
    assert (await _settings(session, group_id)).posting_enabled is False
    assert "Funksiyalar matritsasi" in fake.edited_texts()[-1]


async def test_interval_fsm(session, tg) -> None:
    fake, bot, dp = tg
    await _feed(session, dp, bot, 1, bot_added_update())
    group_id = (await _group(session)).id

    # «⏱ Interval» → FSM holat
    await _feed(session, dp, bot, 2, callback_update(GroupCB(action="interval", group_id=group_id).pack()))
    assert "intervali" in fake.edited_texts()[-1].lower()

    # To'g'ri qiymat (daqiqada)
    await _feed(session, dp, bot, 3, text_update("45"))
    assert (await _settings(session, group_id)).interval_sec == 45 * 60
    assert any("45 daqiqa" in text for text in fake.sent_texts())

    # Noto'g'ri qiymat (0) → saqlanmaydi
    await _feed(session, dp, bot, 4, callback_update(GroupCB(action="interval", group_id=group_id).pack()))
    await _feed(session, dp, bot, 5, text_update("0"))
    assert (await _settings(session, group_id)).interval_sec == 45 * 60

    # Son bo'lmagan matn
    await _feed(session, dp, bot, 6, text_update("salom"))
    assert (await _settings(session, group_id)).interval_sec == 45 * 60


async def test_jitter_limit_quiet_fsm(session, tg) -> None:
    fake, bot, dp = tg
    await _feed(session, dp, bot, 1, bot_added_update())
    group_id = (await _group(session)).id

    # Jitter
    await _feed(session, dp, bot, 2, callback_update(GroupCB(action="jitter", group_id=group_id).pack()))
    await _feed(session, dp, bot, 3, text_update("25"))
    assert (await _settings(session, group_id)).jitter_percent == 25

    # Kunlik limit
    await _feed(session, dp, bot, 4, callback_update(GroupCB(action="limit", group_id=group_id).pack()))
    await _feed(session, dp, bot, 5, text_update("20"))
    assert (await _settings(session, group_id)).daily_post_limit == 20

    # Tinch soatlar
    await _feed(session, dp, bot, 6, callback_update(GroupCB(action="quiet", group_id=group_id).pack()))
    await _feed(session, dp, bot, 7, text_update("23:00-08:00"))
    settings = await _settings(session, group_id)
    assert (settings.quiet_start, settings.quiet_end) == ("23:00", "08:00")

    # Noto'g'ri format — o'zgarmaydi
    await _feed(session, dp, bot, 8, callback_update(GroupCB(action="quiet", group_id=group_id).pack()))
    await _feed(session, dp, bot, 9, text_update("25:00-99:00"))
    settings = await _settings(session, group_id)
    assert (settings.quiet_start, settings.quiet_end) == ("23:00", "08:00")

    # O'chirish
    await _feed(session, dp, bot, 10, callback_update(GroupCB(action="quiet", group_id=group_id).pack()))
    await _feed(session, dp, bot, 11, text_update("off"))
    settings = await _settings(session, group_id)
    assert settings.quiet_start is None and settings.quiet_end is None


async def test_pause_resume_and_delete(session, tg) -> None:
    fake, bot, dp = tg
    await _feed(session, dp, bot, 1, bot_added_update())
    group_id = (await _group(session)).id

    # Pauza
    await _feed(session, dp, bot, 2, callback_update(GroupCB(action="pause", group_id=group_id).pack()))
    group = await _group(session)
    assert group.is_active is False
    assert group.paused_reason == "manual"

    # Qayta yoqish
    await _feed(session, dp, bot, 3, callback_update(GroupCB(action="pause", group_id=group_id).pack()))
    group = await _group(session)
    assert group.is_active is True
    assert group.paused_reason is None

    # O'chirish — tasdiq talab qilinadi
    await _feed(session, dp, bot, 4, callback_update(GroupCB(action="delete", group_id=group_id).pack()))
    assert "o'chir" in fake.edited_texts()[-1].lower()
    assert len((await session.execute(select(Group))).scalars().all()) == 1

    await _feed(
        session, dp, bot, 5, callback_update(GroupCB(action="delete_confirm", group_id=group_id).pack())
    )
    assert (await session.execute(select(Group))).scalars().all() == []


async def test_group_card_opens_categories_screen(session, tg) -> None:
    """«🗂 Toifalar» tugmasi guruh kartasidan ishlaydi."""
    fake, bot, dp = tg
    await _feed(session, dp, bot, 1, bot_added_update())
    group_id = (await _group(session)).id

    await _feed(session, dp, bot, 2, callback_update(GroupCB(action="cats", group_id=group_id).pack()))
    text = fake.edited_texts()[-1]
    assert "toifalar" in text
    assert "Biriktirilgan toifalar: <b>0</b>" in text


# ═══════════════════════ 3. Toifalar bo'limi ═══════════════════════
async def test_category_create_attach_detach(session, tg) -> None:
    fake, bot, dp = tg
    await _feed(session, dp, bot, 1, bot_added_update())
    group_id = (await _group(session)).id

    # Bo'sh ro'yxat
    await _feed(session, dp, bot, 2, callback_update(CB_CATEGORIES))
    assert "Hozircha toifa yo'q" in fake.edited_texts()[-1]

    # Yaratish → nom yuborish
    await _feed(session, dp, bot, 3, callback_update(CategoryCB(action="create", category_id=0, value="0").pack()))
    assert "Yangi toifa" in fake.edited_texts()[-1]
    await _feed(session, dp, bot, 4, text_update("📱 Telefonlar"))

    category = (await _categories(session))[0]
    category_id = category.id
    assert (category.emoji, category.name) == ("📱", "Telefonlar")
    assert category.group_id is None
    assert any("yaratildi" in text for text in fake.sent_texts())
    assert any("biriktirilmagan" in text for text in fake.sent_texts())

    # Guruh tanlash ekrani
    await _feed(session, dp, bot, 5, callback_update(CategoryCB(action="group", category_id=category_id).pack()))
    assert "Guruh tanlang" in fake.edited_texts()[-1]

    # Biriktirish
    await _feed(
        session,
        dp,
        bot,
        6,
        callback_update(CategoryCB(action="setgroup", category_id=category_id, value=str(group_id)).pack()),
    )
    assert (await _category(session, category_id)).group_id == group_id
    assert (await _rotation(session, category_id)).is_paused is False
    assert "biriktirildi" in " ".join(fake.answers())

    # Ro'yxatda ko'rinadi
    await _feed(session, dp, bot, 7, callback_update(CB_CATEGORIES))
    listing = fake.edited_texts()[-1]
    assert "Jami: <b>1</b>" in listing
    assert "Biriktirilgan: <b>1</b>" in listing

    # Biriktirilishini olib tashlash
    await _feed(
        session,
        dp,
        bot,
        8,
        callback_update(CategoryCB(action="setgroup", category_id=category_id, value="none").pack()),
    )
    assert (await _category(session, category_id)).group_id is None
    assert (await _rotation(session, category_id)).is_paused is True


async def test_category_rename_interval_and_toggles(session, tg) -> None:
    fake, bot, dp = tg
    await _feed(session, dp, bot, 1, bot_added_update())
    await _feed(session, dp, bot, 2, callback_update(CategoryCB(action="create", category_id=0, value="0").pack()))
    await _feed(session, dp, bot, 3, text_update("Avtomobillar"))
    category_id = (await _categories(session))[0].id

    # Nomni o'zgartirish
    await _feed(session, dp, bot, 4, callback_update(CategoryCB(action="rename", category_id=category_id).pack()))
    await _feed(session, dp, bot, 5, text_update("🚗 Avto bozori"))
    category = await _category(session, category_id)
    assert (category.emoji, category.name) == ("🚗", "Avto bozori")

    # Alohida interval
    await _feed(session, dp, bot, 6, callback_update(CategoryCB(action="interval", category_id=category_id).pack()))
    await _feed(session, dp, bot, 7, text_update("120"))
    assert (await _category(session, category_id)).interval_override == 120 * 60

    # Guruh intervaliga qaytarish
    await _feed(session, dp, bot, 8, callback_update(CategoryCB(action="interval", category_id=category_id).pack()))
    await _feed(session, dp, bot, 9, text_update("0"))
    assert (await _category(session, category_id)).interval_override is None

    # Faol/pauza
    await _feed(session, dp, bot, 10, callback_update(CategoryCB(action="active", category_id=category_id).pack()))
    assert (await _category(session, category_id)).is_active is False

    # Moderatsiya rejimi
    await _feed(session, dp, bot, 11, callback_update(CategoryCB(action="moderation", category_id=category_id).pack()))
    assert (await _category(session, category_id)).moderation_required is True


async def test_category_order_and_delete(session, tg) -> None:
    fake, bot, dp = tg
    await _feed(session, dp, bot, 1, bot_added_update())

    for index, name in enumerate(("Birinchi", "Ikkinchi"), start=1):
        await _feed(session, dp, bot, 10 + index, callback_update(CategoryCB(action="create", category_id=0, value="0").pack()))
        await _feed(session, dp, bot, 20 + index, text_update(name))

    categories = await _categories(session)
    assert [c.name for c in categories] == ["Birinchi", "Ikkinchi"]
    second_id = categories[1].id

    # Tartib ekrani
    await _feed(session, dp, bot, 30, callback_update(CategoryCB(action="order").pack()))
    assert "tartibi" in fake.edited_texts()[-1]

    # Pastdagi toifani yuqoriga ko'chirish
    await _feed(session, dp, bot, 31, callback_update(CategoryCB(action="order_up", category_id=second_id).pack()))
    assert [c.name for c in await _categories(session)] == ["Ikkinchi", "Birinchi"]

    # O'chirish: tasdiq ekrani → o'chirish
    await _feed(session, dp, bot, 32, callback_update(CategoryCB(action="delete", category_id=second_id).pack()))
    assert "o'chirasizmi" in fake.edited_texts()[-1]
    assert len(await _categories(session)) == 2

    await _feed(session, dp, bot, 33, callback_update(CategoryCB(action="delete_confirm", category_id=second_id).pack()))
    assert [c.name for c in await _categories(session)] == ["Birinchi"]


async def test_cancel_fsm_returns_to_card(session, tg) -> None:
    fake, bot, dp = tg
    await _feed(session, dp, bot, 1, bot_added_update())
    group_id = (await _group(session)).id

    await _feed(session, dp, bot, 2, callback_update(GroupCB(action="limit", group_id=group_id).pack()))
    await _feed(session, dp, bot, 3, text_update("/cancel"))
    assert "📱 Telefonlar bozori" in fake.sent_texts()[-1]


# ═══════════════════════ 4. Asosiy panel ═══════════════════════════
async def test_panel_menu_and_sections(session, tg) -> None:
    fake, bot, dp = tg

    await _feed(session, dp, bot, 1, callback_update(CB_MENU))
    assert "Boshqaruv paneli" in fake.edited_texts()[-1]

    # Statistika
    await _feed(session, dp, bot, 2, callback_update(AdminCB(action="section", value="stats").pack()))
    assert "statistika" in fake.edited_texts()[-1].lower()

    # Guruhlar bo'limi panel orqali ham ochiladi
    await _feed(session, dp, bot, 3, callback_update(AdminCB(action="section", value="groups").pack()))
    assert "Guruhlar" in fake.edited_texts()[-1]

    # Toifalar bo'limi
    await _feed(session, dp, bot, 4, callback_update(AdminCB(action="section", value="categories").pack()))
    assert "Toifalar" in fake.edited_texts()[-1]

    # Tayyor bo'lmagan bo'lim → Phase haqida ogohlantirish
    await _feed(session, dp, bot, 5, callback_update(AdminCB(action="section", value="sellers").pack()))
    assert any("Phase" in answer for answer in fake.answers())


async def test_admin_only_access_for_foreign_user(session, tg) -> None:
    """Begona foydalanuvchi panelga kira olmaydi."""
    fake, bot, dp = tg
    await _feed(session, dp, bot, 1, bot_added_update())
    fake.reset()

    await _feed(session, dp, bot, 2, callback_update(CB_GROUPS, user_id=777777, update_id=900))
    assert fake.edited_texts() == []          # hech narsa ko'rsatilmadi
    assert fake.answers() == []
