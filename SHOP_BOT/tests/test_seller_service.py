"""Sotuvchilar servisi testlari (Phase 2)."""

from __future__ import annotations

from app.constants import SellerStatus
from app.services import seller_service

USER_ID = 555000111


async def test_create_seller_with_referral_code(session) -> None:
    seller, created = await seller_service.get_or_create_seller(
        session, USER_ID, display_name="📱 Telefon do'koni", added_by=111111
    )

    assert created is True
    assert seller.user_id == USER_ID
    assert seller.status == SellerStatus.PENDING
    assert seller.referral_code is not None
    assert len(seller.referral_code) == seller_service.CODE_LENGTH
    assert all(ch in seller_service.CODE_ALPHABET for ch in seller.referral_code)
    assert seller.added_by == 111111
    assert seller.balance == 0


async def test_referral_codes_are_unique(session) -> None:
    codes = set()
    for index in range(15):
        seller, _ = await seller_service.get_or_create_seller(session, USER_ID + index)
        codes.add(seller.referral_code)

    assert len(codes) == 15
    assert all(code is not None for code in codes)


async def test_create_twice_updates_existing(session) -> None:
    seller, created = await seller_service.get_or_create_seller(session, USER_ID, display_name="Birinchi")
    assert created is True
    code = seller.referral_code

    again, created_again = await seller_service.get_or_create_seller(
        session, USER_ID, display_name="Ikkinchi", phone="+998 90 123 45 67"
    )

    assert created_again is False
    assert again.id == seller.id
    assert again.display_name == "Ikkinchi"
    assert again.phone == "+998901234567"  # normalizatsiya
    assert again.referral_code == code  # kod o'zgarmaydi


async def test_normalizers() -> None:
    assert seller_service.normalize_phone("+998 (90) 123-45-67") == "+998901234567"
    assert seller_service.normalize_phone("90 123 45 67") == "901234567"
    assert seller_service.normalize_phone("-") is None
    assert seller_service.normalize_phone("o'tkazib yuborish") is None
    assert seller_service.normalize_phone(None) is None

    assert seller_service.normalize_contact("@dokon") == "@dokon"
    assert seller_service.normalize_contact("https://t.me/dokon") == "@dokon"
    assert seller_service.normalize_contact("yo'q") is None

    assert seller_service.normalize_name("  Do'kon  ") == "Do'kon"
    assert seller_service.normalize_name("   ") is None


async def test_status_changes_and_reason(session) -> None:
    seller, _ = await seller_service.get_or_create_seller(session, USER_ID)

    assert await seller_service.set_status(session, seller, SellerStatus.BLOCKED, reason="Firibgarlik")
    assert seller.status == SellerStatus.BLOCKED
    assert seller.blocked_reason == "Firibgarlik"

    # Bir xil holatga qayta o'tkazish — o'zgarish yo'q
    assert await seller_service.set_status(session, seller, SellerStatus.BLOCKED) is False

    assert await seller_service.set_status(session, seller, SellerStatus.ACTIVE)
    assert seller.blocked_reason is None

    assert await seller_service.set_status(session, seller, "notogri_holat") is False


async def test_is_active_seller(session) -> None:
    seller, _ = await seller_service.get_or_create_seller(session, USER_ID)

    assert await seller_service.is_active_seller(session, USER_ID) is True   # pending — panel ochiq
    await seller_service.set_status(session, seller, SellerStatus.BLOCKED)
    assert await seller_service.is_active_seller(session, USER_ID) is False
    assert await seller_service.is_active_seller(session, 999999) is False


async def test_filter_and_search(session) -> None:
    one, _ = await seller_service.get_or_create_seller(session, USER_ID, display_name="Alfa do'kon")
    two, _ = await seller_service.get_or_create_seller(session, USER_ID + 1, display_name="Beta bozor")
    await seller_service.set_status(session, two, SellerStatus.ACTIVE)
    three, _ = await seller_service.get_or_create_seller(session, USER_ID + 2, display_name="Gamma")
    await seller_service.set_status(session, three, SellerStatus.BLOCKED)

    assert await seller_service.count_sellers(session) == 3
    assert await seller_service.count_sellers(session, status=SellerStatus.ACTIVE) == 1
    assert await seller_service.count_sellers(session, status=SellerStatus.BLOCKED) == 1

    by_name = await seller_service.list_sellers(session, query="alfa")
    assert [s.display_name for s in by_name] == ["Alfa do'kon"]

    by_id = await seller_service.list_sellers(session, query=str(USER_ID + 1))
    assert [s.user_id for s in by_id] == [USER_ID + 1]

    counts = await seller_service.count_sellers_by_status(session)
    assert counts["total"] == 3
    assert counts["active"] == 1
    assert counts["blocked"] == 1

    _ = one


async def test_soft_delete_hides_from_list(session) -> None:
    seller, _ = await seller_service.get_or_create_seller(session, USER_ID)
    await seller_service.soft_delete(session, seller)

    assert seller.status == SellerStatus.DELETED
    assert seller.referral_code is None
    assert await seller_service.count_sellers(session) == 0
    assert await seller_service.is_active_seller(session, USER_ID) is False

    # Qayta qo'shilsa — pending holatda tiklanadi
    seller_again, created = await seller_service.get_or_create_seller(session, USER_ID)
    assert created is False
    assert seller_again.status == SellerStatus.PENDING


async def test_update_profile(session) -> None:
    seller, _ = await seller_service.get_or_create_seller(session, USER_ID, display_name="Eski nom")

    assert await seller_service.update_profile(session, seller, display_name="Yangi nom", phone="+998901112233")
    assert seller.display_name == "Yangi nom"
    assert seller.phone == "+998901112233"

    # `None` — o'zgartirmaslik
    assert await seller_service.update_profile(session, seller, phone=None) is False

    # Tozalash
    assert await seller_service.update_profile(session, seller, phone="-") is True
    assert seller.phone is None


async def test_status_badges(session) -> None:
    seller, _ = await seller_service.get_or_create_seller(session, USER_ID, display_name="Do'kon")
    assert "Tarif yo'q" in seller_service.status_badge(seller)

    await seller_service.set_status(session, seller, SellerStatus.ACTIVE)
    assert "Faol" in seller_service.status_badge(seller)

    assert seller_service.seller_label(seller) == "Do'kon"
    assert seller_service.status_filter_label(None) == "Hammasi"
    assert seller_service.status_filter_label(SellerStatus.BLOCKED).endswith("Bloklangan")


async def test_get_by_referral_code(session) -> None:
    seller, _ = await seller_service.get_or_create_seller(session, USER_ID)
    code = await seller_service.ensure_referral_code(session, seller)

    found = await seller_service.get_seller_by_referral_code(session, code.lower())
    assert found is not None and found.id == seller.id
    assert await seller_service.get_seller_by_referral_code(session, "YOQKOD") is None


async def test_seller_stats(session) -> None:
    seller, _ = await seller_service.get_or_create_seller(session, USER_ID)
    stats = await seller_service.get_seller_stats(session, seller)

    assert stats == {"ads_total": 0, "ads_active": 0, "payments": 0, "subscriptions": 0}
