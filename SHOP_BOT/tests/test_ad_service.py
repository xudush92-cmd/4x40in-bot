"""📢 E'lonlar servisi testlari (Phase 3).

Qamrov: qoralama yaratish, maydonlarni tahrirlash, rasm limiti (tarif/global),
yuborish (avto-tasdiq va moderatsiya), tasdiq/rad, pauza, o'chirish va limit
qaytarilishi, navbat pozitsiyalari, holat nomlari.
"""

from __future__ import annotations

import itertools
from decimal import Decimal

import pytest
from sqlalchemy import select, func

from app.constants import AdStatus, SellerStatus
from app.db.models import Ad, AdPhoto, Category, Group, ModerationLog, Seller
from app.services import ad_service, seller_service, subscription_service, tariff_service
from app.services.settings_service import settings_service


# ═══════════════════════════ Yordamchilar ═════════════════════════
async def _seller(session, *, user_id: int = 555000111, contact: str = "@dokon") -> Seller:
    seller, _ = await seller_service.get_or_create_seller(
        session, user_id, display_name="Do'kon", phone="+998901112233", contact=contact
    )
    await session.flush()
    return seller


_CHAT_ID_SEQ = itertools.count(1)


async def _category(session, *, name: str = "Telefonlar", moderation: bool = False) -> Category:
    """Yangi toifa. Guruh bazada bo'lsa qayta ishlatiladi (tg_chat_id unique)."""
    group = (await session.execute(select(Group).limit(1))).scalars().first()
    if group is None:
        group = Group(
            tg_chat_id=-1009990000000 - next(_CHAT_ID_SEQ),
            title="Telefonlar bozori",
            is_active=True,
        )
        session.add(group)
        await session.flush()
    category = Category(
        name=name, group_id=group.id, is_active=True, moderation_required=moderation, position=1000
    )
    session.add(category)
    await session.flush()
    return category


async def _seller_with_subscription(session, *, max_ads: int = 5, max_photos: int = 3):
    seller = await _seller(session)
    seller.status = SellerStatus.ACTIVE
    tariff = await tariff_service.create_tariff(
        session, name="Biznes", price="400000", duration_days=30, max_ads=max_ads, max_photos=max_photos
    )
    subscription = await subscription_service.grant(session, seller, tariff)
    await session.flush()
    return seller, tariff, subscription


async def _draft(session, seller: Seller, category: Category, *, title: str = "iPhone 15"):
    ad = await ad_service.create_draft(session, seller, category)
    await ad_service.set_title(session, ad, title)
    await ad_service.set_price(session, ad, 12500000)
    return ad


# ══════════════════════════ Qoralama ══════════════════════════════
async def test_create_draft_fills_defaults(session) -> None:
    seller = await _seller(session, contact="@dokon")
    category = await _category(session)

    ad = await ad_service.create_draft(session, seller, category)

    assert ad.id is not None
    assert ad.status == AdStatus.DRAFT
    assert ad.currency == "UZS"
    assert ad.contact_type == "username"
    assert ad.contact_value == "@dokon"
    assert ad.position == ad_service.POSITION_GAP


async def test_default_contact_from_phone_when_no_username(session) -> None:
    seller = await _seller(session, contact=None)
    assert ad_service.default_contact(seller) == ("phone", "+998901112233")


async def test_positions_increase_within_category(session) -> None:
    seller = await _seller(session)
    category = await _category(session)

    first = await ad_service.create_draft(session, seller, category)
    second = await ad_service.create_draft(session, seller, category)
    other = await ad_service.create_draft(session, seller, await _category(session, name="Noutbuk"))

    assert second.position == first.position + ad_service.POSITION_GAP
    assert other.position == ad_service.POSITION_GAP          # boshqa toifa — o'z navbati


async def test_set_title_validation(session) -> None:
    seller = await _seller(session)
    category = await _category(session)
    ad = await ad_service.create_draft(session, seller, category)

    assert await ad_service.set_title(session, ad, "ab") is False       # juda qisqa
    assert await ad_service.set_title(session, ad, "   ") is False      # bo'sh
    assert await ad_service.set_title(session, ad, "iPhone 15 Pro") is True
    assert ad.title == "iPhone 15 Pro"


async def test_set_price_and_caption(session) -> None:
    seller = await _seller(session)
    category = await _category(session)
    ad = await ad_service.create_draft(session, seller, category)
    await ad_service.set_title(session, ad, "iPhone 15 Pro")

    assert await ad_service.set_price(session, ad, 12500000) is True
    assert ad.price == Decimal("12500000.00")
    assert "12 500 000 so'm" in ad.caption

    assert await ad_service.set_price(session, ad, None) is True        # kelishiladi
    assert ad.price is None
    assert "Narx" not in ad.caption
    assert ad_service.format_ad_price(ad) == "Kelishiladi"

    assert await ad_service.set_price(session, ad, -5) is False
    assert await ad_service.set_price(session, ad, 10**15) is False


async def test_set_contact_and_category(session) -> None:
    seller = await _seller(session)
    first = await _category(session)
    second = await _category(session, name="Noutbuklar")
    ad = await ad_service.create_draft(session, seller, first)

    await ad_service.set_contact(session, ad, contact_type="phone", contact_value="+998901112233")
    assert ad.contact_type == "phone"
    assert ad.contact_value == "+998901112233"

    await ad_service.set_category(session, ad, second)
    assert ad.category_id == second.id
    assert ad.position == ad_service.POSITION_GAP        # yangi toifa navbatining oxiri


# ═══════════════════════════ Rasmlar ══════════════════════════════
async def test_add_and_remove_photos(session) -> None:
    seller = await _seller(session)
    category = await _category(session)
    ad = await ad_service.create_draft(session, seller, category)

    first = await ad_service.add_photo(session, ad, file_id="file-1", file_unique_id="uq-1")
    second = await ad_service.add_photo(session, ad, file_id="file-2", file_unique_id="uq-2")
    assert (first.position, second.position) == (0, 1)
    assert await ad_service.photo_count(session, ad.id) == 2

    assert await ad_service.remove_photo(session, ad, 0) is True
    assert await ad_service.photo_count(session, ad.id) == 1
    rows = (
        await session.execute(select(AdPhoto).where(AdPhoto.ad_id == ad.id))
    ).scalars().all()
    assert rows[0].position == 0                      # qayta raqamlandi
    assert await ad_service.remove_photo(session, ad, 5) is False


async def test_photo_limit_uses_tariff(session) -> None:
    seller, tariff, _ = await _seller_with_subscription(session, max_photos=2)

    assert await ad_service.photo_limit(session, seller) == 2


async def test_photo_limit_falls_back_to_settings(session) -> None:
    seller = await _seller(session)                     # obuna yo'q
    assert await ad_service.photo_limit(session, seller) == 3   # default_max_photos

    await settings_service.set(session, "default_max_photos", 5)
    assert await ad_service.photo_limit(session, seller) == 5

    await settings_service.set(session, "default_max_photos", 99)
    assert await ad_service.photo_limit(session, seller) == ad_service.MAX_PHOTOS_HARD  # 10


async def test_add_photo_respects_limit(session) -> None:
    seller = await _seller(session)
    category = await _category(session)
    ad = await ad_service.create_draft(session, seller, category)

    await ad_service.add_photo(session, ad, file_id="f1", limit=1)
    with pytest.raises(ValueError):
        await ad_service.add_photo(session, ad, file_id="f2", limit=1)


# ═══════════════════════ Yuborish (submit) ════════════════════════
async def test_validate_for_submit_requires_category_group_and_photo(session) -> None:
    seller = await _seller(session)
    category = await _category(session)
    ad = await ad_service.create_draft(session, seller, category)

    ok, reason = await ad_service.validate_for_submit(session, ad)
    assert ok is False and "qisqa" in reason           # sarlavha yo'q

    await ad_service.set_title(session, ad, "iPhone 15")
    ok, reason = await ad_service.validate_for_submit(session, ad)
    assert ok is False and "rasm" in reason.lower()     # rasm yo'q

    await ad_service.add_photo(session, ad, file_id="f1")
    ok, reason = await ad_service.validate_for_submit(session, ad)
    assert ok is True and reason == ""


async def test_validate_rejects_category_without_group(session) -> None:
    seller = await _seller(session)
    category = await _category(session)
    category.group_id = None
    ad = await _draft(session, seller, category)
    await ad_service.add_photo(session, ad, file_id="f1")

    ok, reason = await ad_service.validate_for_submit(session, ad)
    assert ok is False and "guruhga biriktirilmagan" in reason


async def test_submit_blocked_without_subscription(session) -> None:
    seller = await _seller(session)                     # status=pending, obuna yo'q
    category = await _category(session)
    ad = await _draft(session, seller, category)
    await ad_service.add_photo(session, ad, file_id="f1")

    ok, reason = await ad_service.submit(session, seller, ad)
    assert ok is False
    assert ad.status == AdStatus.DRAFT
    assert "tarif" in reason.lower()


async def test_submit_goes_active_without_moderation(session) -> None:
    seller, tariff, subscription = await _seller_with_subscription(session)
    category = await _category(session, moderation=False)
    ad = await _draft(session, seller, category)
    await ad_service.add_photo(session, ad, file_id="f1")

    ok, result = await ad_service.submit(session, seller, ad)

    assert ok is True and result == AdStatus.ACTIVE
    assert ad.status == AdStatus.ACTIVE
    assert ad.approved_at is not None
    assert subscription.ads_used == 1                    # limitdan hisoblandi


async def test_submit_goes_pending_with_moderation(session) -> None:
    seller, _, subscription = await _seller_with_subscription(session)
    category = await _category(session, moderation=True)
    ad = await _draft(session, seller, category)
    await ad_service.add_photo(session, ad, file_id="f1")

    ok, result = await ad_service.submit(session, seller, ad)

    assert ok is True and result == AdStatus.PENDING
    assert ad.status == AdStatus.PENDING
    assert ad.submitted_at is not None
    assert subscription.ads_used == 1


async def test_submit_stops_when_limit_exhausted(session) -> None:
    seller, _, subscription = await _seller_with_subscription(session, max_ads=1)
    category = await _category(session)
    ad = await _draft(session, seller, category)
    await ad_service.add_photo(session, ad, file_id="f1")
    await ad_service.submit(session, seller, ad)

    second = await _draft(session, seller, category, title="Ikkinchi")
    await ad_service.add_photo(session, second, file_id="f2")
    ok, reason = await ad_service.submit(session, seller, second)

    assert ok is False
    assert second.status == AdStatus.DRAFT
    assert "limit" in reason.lower()
    assert subscription.ads_used == 1


# ═══════════════════════ Moderatsiya (admin) ══════════════════════
async def test_approve_activates_and_logs(session) -> None:
    seller, _, subscription = await _seller_with_subscription(session)
    category = await _category(session, moderation=True)
    ad = await _draft(session, seller, category)
    await ad_service.add_photo(session, ad, file_id="f1")
    await ad_service.submit(session, seller, ad)

    assert await ad_service.approve(session, ad, admin_id=777) is True
    assert ad.status == AdStatus.ACTIVE
    assert ad.approved_by == 777

    history = await ad_service.moderation_history(session, ad.id)
    assert [row.decision for row in history] == ["approved"]

    # Takroriy tasdiq o'tmaydi
    assert await ad_service.approve(session, ad, admin_id=777) is False


async def test_reject_returns_slot_and_saves_reason(session) -> None:
    seller, _, subscription = await _seller_with_subscription(session)
    category = await _category(session, moderation=True)
    ad = await _draft(session, seller, category)
    await ad_service.add_photo(session, ad, file_id="f1")
    await ad_service.submit(session, seller, ad)
    assert subscription.ads_used == 1

    assert await ad_service.reject(session, seller, ad, 777, "🚫 Reklama/spam") is True
    assert ad.status == AdStatus.REJECTED
    assert ad.reject_reason == "🚫 Reklama/spam"
    assert subscription.ads_used == 0                    # limit qaytarildi

    history = await ad_service.moderation_history(session, ad.id)
    assert history[0].decision == "rejected"
    assert history[0].reason == "🚫 Reklama/spam"


async def test_admin_pause_logs_decision(session) -> None:
    seller, _, _ = await _seller_with_subscription(session)
    category = await _category(session)
    ad = await _draft(session, seller, category)
    await ad_service.add_photo(session, ad, file_id="f1")
    await ad_service.submit(session, seller, ad)

    assert await ad_service.admin_pause(session, ad, 777, "Shikoyat") is True
    assert ad.status == AdStatus.PAUSED

    rows = (
        await session.execute(select(ModerationLog).where(ModerationLog.ad_id == ad.id))
    ).scalars().all()
    assert [row.decision for row in rows] == ["paused"]


async def test_edited_resets_rejected_to_draft(session) -> None:
    seller, _, _ = await _seller_with_subscription(session)
    category = await _category(session, moderation=True)
    ad = await _draft(session, seller, category)
    await ad_service.add_photo(session, ad, file_id="f1")
    await ad_service.submit(session, seller, ad)
    await ad_service.reject(session, seller, ad, 777, "sabab")

    await ad_service.set_title(session, ad, "Yangi sarlavha")
    await ad_service.edited(session, ad)

    assert ad.status == AdStatus.DRAFT
    assert ad.reject_reason is None


async def test_edited_logs_revision_for_active_ad(session) -> None:
    seller, _, _ = await _seller_with_subscription(session)
    category = await _category(session)
    ad = await _draft(session, seller, category)
    await ad_service.add_photo(session, ad, file_id="f1")
    await ad_service.submit(session, seller, ad)
    assert ad.status == AdStatus.ACTIVE

    await ad_service.set_price(session, ad, 999)
    await ad_service.edited(session, ad)

    assert ad.status == AdStatus.ACTIVE                 # navbatdan chiqmaydi
    history = await ad_service.moderation_history(session, ad.id)
    assert [row.decision for row in history] == ["revised"]


# ═══════════════════ Pauza / o'chirish / navbat ═══════════════════
async def test_pause_resume_and_delete_flow(session) -> None:
    seller, _, subscription = await _seller_with_subscription(session)
    category = await _category(session)
    ad = await _draft(session, seller, category)
    await ad_service.add_photo(session, ad, file_id="f1")
    await ad_service.submit(session, seller, ad)

    assert await ad_service.pause(session, ad) is True
    assert ad.status == AdStatus.PAUSED
    assert await ad_service.pause(session, ad) is False        # ikkinchi marta emas
    assert await ad_service.resume(session, ad) is True
    assert ad.status == AdStatus.ACTIVE

    assert await ad_service.soft_delete(session, seller, ad) is True
    assert ad.status == AdStatus.DELETED
    assert subscription.ads_used == 0                          # limit qaytarildi
    assert await ad_service.soft_delete(session, seller, ad) is False


async def test_hard_delete_empty_draft(session) -> None:
    seller = await _seller(session)
    category = await _category(session)

    empty = await ad_service.create_draft(session, seller, category)
    assert await ad_service.hard_delete_empty_draft(session, empty) is True
    assert await ad_service.get_ad(session, empty.id) is None

    filled = await _draft(session, seller, category)
    assert await ad_service.hard_delete_empty_draft(session, filled) is False
    assert await ad_service.get_ad(session, filled.id) is not None


async def test_move_changes_order_and_renumbers(session) -> None:
    seller = await _seller(session)
    category = await _category(session)
    first = await _draft(session, seller, category, title="Birinchi")
    second = await _draft(session, seller, category, title="Ikkinchi")
    for ad in (first, second):
        ad.status = AdStatus.ACTIVE
    await session.flush()

    assert await ad_service.move(session, second, "up") is True
    assert second.position < first.position
    assert await ad_service.move(session, second, "up") is False       # allaqachon boshida
    assert await ad_service.move(session, second, "down") is True      # orqaga qaytdi
    assert first.position < second.position
    assert await ad_service.move(session, second, "down") is False     # allaqachon oxirida


async def test_renumber_category(session) -> None:
    seller = await _seller(session)
    category = await _category(session)
    ads = [await _draft(session, seller, category, title=f"E'lon {i}") for i in range(3)]
    ads[1].position = ads[0].position + 1                    # oraliq tugadi

    count = await ad_service.renumber_category(session, category.id)

    assert count == 3
    assert [ad.position for ad in ads] == [100, 200, 300]


# ═══════════════════ Ro'yxat, statistika, matnlar ═════════════════
async def test_seller_list_filters_and_stats(session) -> None:
    seller, _, _ = await _seller_with_subscription(session)
    category = await _category(session, moderation=True)

    active = await _draft(session, seller, category, title="Faol e'lon")
    await ad_service.add_photo(session, active, file_id="f1")
    await ad_service.submit(session, seller, active)
    await ad_service.approve(session, active, 777)

    draft = await _draft(session, seller, category, title="Qoralama")

    assert [ad.id for ad in await ad_service.list_seller_ads(session, seller.id, status="all")] == [
        draft.id,
        active.id,
    ] or [ad.id for ad in await ad_service.list_seller_ads(session, seller.id, status="all")] == [
        active.id,
        draft.id,
    ]
    assert await ad_service.count_seller_ads(session, seller.id, status="active") == 1
    assert await ad_service.count_seller_ads(session, seller.id) == 2

    stats = await ad_service.seller_ads_stats(session, seller.id)
    assert stats["active"] == 1
    assert stats["draft"] == 1
    assert stats["total"] == 2


async def test_admin_counts_and_pending_list(session) -> None:
    seller, _, _ = await _seller_with_subscription(session)
    category = await _category(session, moderation=True)
    ad = await _draft(session, seller, category)
    await ad_service.add_photo(session, ad, file_id="f1")
    await ad_service.submit(session, seller, ad)

    assert await ad_service.count_pending(session) == 1
    assert [row.id for row in await ad_service.pending_ads(session)] == [ad.id]

    stats = await ad_service.count_by_status(session)
    assert stats[AdStatus.PENDING] == 1
    assert stats["all"] == 1
    assert await ad_service.count_ads(session, status="pending", admin=True) == 1
    assert await ad_service.count_ads(session, status="active", admin=True) == 0

    by_category = await ad_service.list_ads(session, category_id=category.id, admin=True)
    assert [row.id for row in by_category] == [ad.id]


async def test_ad_stats_uses_post_log(session) -> None:
    from app.db.models import PostLog

    seller, _, _ = await _seller_with_subscription(session)
    category = await _category(session)
    ad = await _draft(session, seller, category)
    await ad_service.add_photo(session, ad, file_id="f1")

    session.add(
        PostLog(group_id=-1009990001111, ad_id=ad.id, seller_id=seller.id, status="ok", category_id=category.id)
    )
    session.add(
        PostLog(group_id=-1009990001111, ad_id=ad.id, seller_id=seller.id, status="error", category_id=category.id)
    )
    await session.flush()

    stats = await ad_service.ad_stats(session, ad)
    assert stats["logged_posts"] == 1                 # faqat muvaffaqiyatli
    assert stats["groups"] == 1
    assert stats["photos"] == 1


def test_status_titles_and_labels() -> None:
    assert "Faol" in ad_service.status_title(AdStatus.ACTIVE)
    assert ad_service.status_badge(AdStatus.PENDING) == "🕓"
    assert ad_service.filter_label("all") == "Hammasi"
    assert "Arxiv" in ad_service.filter_label("archived", admin=True)
    assert ad_service.pages(13, 6) == 3
    assert ad_service.pages(0, 6) == 1


async def test_moderation_required_prefers_category(session) -> None:
    category = await _category(session, moderation=False)
    assert await ad_service.moderation_required(session, category) is False

    await settings_service.set(session, "moderation_required_default", True)
    assert await ad_service.moderation_required(session, category) is False   # toifa ustun
    assert await ad_service.moderation_required(session, None) is True
