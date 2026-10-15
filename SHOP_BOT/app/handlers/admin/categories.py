"""🗂 Toifalar bo'limi (Phase 1).

Imkoniyatlar:
  * toifalar ro'yxati (guruh bo'yicha filtr bilan), kartasi
  * yaratish (nom/emoji + guruh tanlash), nomini o'zgartirish
  * guruhga biriktirish / biriktirilishini olib tashlash
  * faol/pauza, moderatsiya rejimi, alohida interval
  * tartibni o'zgartirish (⬆️/⬇️), o'chirish
"""

from __future__ import annotations

from math import ceil

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import MAX_INTERVAL_SEC, MIN_INTERVAL_SEC, AdminRole
from app.db.models import Category
from app.filters import IsAdmin
from app.handlers.admin._roles import ReadOnlyForModerator
from app.keyboards.callbacks import CategoryCB, GroupCB
from app.keyboards.categories import (
    cancel_create_kb,
    cancel_edit_kb,
    categories_list_kb,
    category_card_kb,
    delete_confirm_kb,
    group_categories_kb,
    group_choice_kb,
    order_kb,
)
from app.keyboards.common import PER_PAGE_CATEGORIES, PER_PAGE_GROUPS
from app.services import category_service, group_service
from app.states import AdminCategoryStates
from app.utils.text import escape_html, fmt_interval, human_int, truncate
from app.utils.tg import alert, render

router = Router(name="admin:categories")
router.message.filter(IsAdmin(AdminRole.ADMIN))
router.callback_query.filter(IsAdmin())
router.callback_query.middleware(ReadOnlyForModerator({"list", "card", "group", "order"}))

NAV_ACTIONS = {"list", "card", "create", "order", "group", "setgroup", "rename", "interval"}


# ═══════════════════════════ Ekranlar ═══════════════════════════════
def _list_text(categories: list[Category], stats: dict[str, int], titles: dict[int, str | None]) -> str:
    lines = [
        "🗂 <b>Toifalar</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Jami: <b>{stats['total']}</b>  ·  📎 Biriktirilgan: <b>{stats['attached']}</b>  ·  "
        f"⚠️ Bo'sh: <b>{stats['free']}</b>",
        "",
    ]
    if not categories:
        lines.append("📭 Hozircha toifa yo'q. «➕ Yangi toifa» tugmasini bosing.")
    else:
        for category in categories:
            title = titles.get(category.id) or "— biriktirilmagan"
            status = "" if category.is_active else " ⏸"
            lines.append(
                f"{category.emoji or '🗂'} <b>{escape_html(category.name)}</b>{status}\n"
                f"   └ 📎 {escape_html(truncate(title, 32))}"
            )
        lines.append("\n<i>Toifani bosib tahrirlash mumkin.</i>")
    return "\n".join(lines)


def _card_text(category: Category, group_title: str | None, stats: dict[str, int]) -> str:
    lines = [
        f"{category.emoji or '🗂'} <b>{escape_html(category.name)}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📎 Guruh: <b>{escape_html(group_title) if group_title else '— biriktirilmagan ⚠️'}</b>",
        f"📌 Holat: {'🟢 Faol' if category.is_active else '⏸ To‘xtatilgan'}",
        f"🧾 Moderatsiya: {'✅ talab qilinadi' if category.moderation_required else '⚪️ shart emas'}",
        f"⏱ Interval: <b>{fmt_interval(category.interval_override) if category.interval_override else 'guruh bilan bir xil'}</b>",
        f"🔢 Tartib: <b>#{category.position}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📢 E'lonlar: <b>{stats['total']}</b> "
        f"(faol {stats['active']}, moderatsiyada {stats['pending']})",
    ]

    if category.rotation is not None:
        lines.append(
            "🎯 Navbat kursori: <b>—</b>"
            if not category.rotation.cursor_ad_id
            else f"🎯 Navbat kursori: e'lon #{category.rotation.cursor_ad_id}"
        )
    else:
        lines.append("🎯 Navbat: guruh biriktirilmagan")

    if category.description:
        lines.append(f"\n📝 {escape_html(truncate(category.description, 200))}")

    if group_title is None:
        lines.append("\n⚠️ Guruh biriktirilmaguncha e'lonlar joylanmaydi.")

    return "\n".join(lines)


def _order_text(categories: list[Category]) -> str:
    return (
        "🔀 <b>Toifalar tartibi</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⬆️/⬇️ tugmalari bilan o'rnini almashtiring.\n"
        "Tartib navbatga ta'sir qiladi (Phase 4 da).\n\n"
        f"Jami: <b>{len(categories)}</b> toifa"
    )


# ═════════════════════════════ Render ══════════════════════════════
async def render_list(target, session: AsyncSession, page: int = 0) -> None:
    stats = await category_service.count_categories_stats(session)
    total_pages = max(1, ceil(stats["total"] / PER_PAGE_CATEGORIES))
    page = max(0, min(page, total_pages - 1))

    categories = await category_service.list_categories(
        session, offset=page * PER_PAGE_CATEGORIES, limit=PER_PAGE_CATEGORIES
    )
    titles = {c.id: await category_service.group_title(session, c.group_id) for c in categories}
    await render(
        target, _list_text(categories, stats, titles), categories_list_kb(categories, titles, page, total_pages)
    )


async def render_card(target, session: AsyncSession, category_id: int) -> bool:
    category = await category_service.get_category(session, category_id)
    if category is None:
        await render(target, "⚠️ Toifa topilmadi (o'chirilgan bo'lishi mumkin).")
        return False

    title = await category_service.group_title(session, category.group_id)
    stats = await category_service.get_category_stats(session, category_id)
    await render(target, _card_text(category, title, stats), category_card_kb(category))
    return True


async def render_group_categories(target, session: AsyncSession, group_id: int) -> None:
    group = await group_service.get_group(session, group_id)
    if group is None:
        await render(target, "⚠️ Guruh topilmadi.")
        return

    categories = await category_service.list_categories_for_group(session, group_id)
    text = (
        f"🗂 <b>{escape_html(group.display)}</b> — toifalar\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Biriktirilgan toifalar: <b>{len(categories)}</b>\n\n"
        + (
            "\n".join(
                f"{c.emoji or '🗂'} {escape_html(c.name)}{'' if c.is_active else ' ⏸'}"
                for c in categories
            )
            if categories
            else "📭 Bu guruhga hali toifa biriktirilmagan."
        )
    )
    await render(target, text, group_categories_kb(group_id, categories))


async def render_order(target, session: AsyncSession) -> None:
    categories = await category_service.list_categories(session, offset=0, limit=50)
    await render(target, _order_text(categories), order_kb(categories))


async def render_group_choice(
    target, session: AsyncSession, category_id: int = 0, page: int = 0
) -> None:
    total = await group_service.count_groups(session)
    total_pages = max(1, ceil(total / PER_PAGE_GROUPS))
    page = max(0, min(page, total_pages - 1))

    groups = await group_service.list_groups(session, offset=page * PER_PAGE_GROUPS, limit=PER_PAGE_GROUPS)
    text = (
        "📎 <b>Guruh tanlang</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "E'lonlar shu guruhga navbat bilan joylanadi.\n"
    )
    if not groups:
        text += "\n⚠️ Avval «👥 Guruhlar» bo'limida guruh qo'shing."

    await render(
        target,
        text,
        group_choice_kb(groups, category_id, page=page, total_pages=total_pages),
    )


# ═══════════════════════════ Callback'lar ══════════════════════════
@router.callback_query(CategoryCB.filter(F.action == "list"))
async def on_list(callback: CallbackQuery, callback_data: CategoryCB, session: AsyncSession) -> None:
    await render_list(callback, session, _page(callback_data.value))
    await alert(callback, "")


@router.callback_query(CategoryCB.filter(F.action == "card"))
async def on_card(callback: CallbackQuery, callback_data: CategoryCB, session: AsyncSession) -> None:
    ok = await render_card(callback, session, callback_data.category_id)
    await alert(callback, "" if ok else "Toifa topilmadi")


@router.callback_query(CategoryCB.filter(F.action == "create"))
async def start_create(
    callback: CallbackQuery, callback_data: CategoryCB, state: FSMContext
) -> None:
    """Yangi toifa: nom so'raymiz (guruh keyin tanlanadi)."""
    group_id = _page(callback_data.value)
    await state.clear()
    await state.update_data(create_group_id=group_id or None)

    hint = ""
    if group_id:
        hint = f"\n📎 Guruh: <b>ID {group_id}</b> ga biriktiriladi"

    await render(
        callback,
        "➕ <b>Yangi toifa</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Toifa nomini yuboring. Emoji ham qo'shsangiz bo'ladi:\n"
        "masalan: <code>📱 Telefonlar</code> yoki <code>Avtomobillar</code>\n"
        f"{hint}\n\nBekor qilish uchun /cancel",
        cancel_create_kb(),
    )
    await state.set_state(AdminCategoryStates.waiting_name)
    await alert(callback, "")


@router.callback_query(CategoryCB.filter(F.action == "rename"))
async def start_rename(
    callback: CallbackQuery, callback_data: CategoryCB, state: FSMContext, session: AsyncSession
) -> None:
    category = await category_service.get_category(session, callback_data.category_id)
    if category is None:
        await alert(callback, "⚠️ Toifa topilmadi", show=True)
        return

    await state.clear()
    await state.update_data(category_id=category.id)
    await state.set_state(AdminCategoryStates.waiting_rename)
    await render(
        callback,
        f"✏️ <b>Nomni o'zgartirish</b>\nHozirgi: <b>{escape_html(category_service.display_name(category))}</b>\n\n"
        "Yangi nomni yuboring (emoji bilan bo'lishi mumkin).\nBekor qilish uchun /cancel",
        cancel_edit_kb(category.id),
    )
    await alert(callback, "")


@router.callback_query(CategoryCB.filter(F.action == "interval"))
async def start_interval(
    callback: CallbackQuery, callback_data: CategoryCB, state: FSMContext, session: AsyncSession
) -> None:
    category = await category_service.get_category(session, callback_data.category_id)
    if category is None:
        await alert(callback, "⚠️ Toifa topilmadi", show=True)
        return

    await state.clear()
    await state.update_data(category_id=category.id)
    await state.set_state(AdminCategoryStates.waiting_interval)
    await render(
        callback,
        "⏱ <b>Toifa uchun alohida interval</b>\n"
        f"Hozirgi: <b>{fmt_interval(category.interval_override) if category.interval_override else 'guruh bilan bir xil'}</b>\n\n"
        f"Daqiqada yuboring ({MIN_INTERVAL_SEC // 60}–{MAX_INTERVAL_SEC // 60}).\n"
        "Guruh intervaliga qaytarish uchun: <code>0</code>\n"
        "Bekor qilish uchun /cancel",
        cancel_edit_kb(category.id),
    )
    await alert(callback, "")


@router.callback_query(CategoryCB.filter(F.action == "group"))
async def choose_group(callback: CallbackQuery, callback_data: CategoryCB, session: AsyncSession) -> None:
    await render_group_choice(callback, session, callback_data.category_id, page=0)
    await alert(callback, "")


@router.callback_query(CategoryCB.filter(F.action == "setgroup"))
async def set_group(callback: CallbackQuery, callback_data: CategoryCB, session: AsyncSession) -> None:
    kind, value = _parse_choice(callback_data.value)
    category_id = callback_data.category_id

    if kind == "page":
        await render_group_choice(callback, session, category_id, page=int(value))
        await alert(callback, "")
        return

    if category_id == 0:
        # Yaratish jarayonida guruh tanlanmoqda
        await alert(callback, "Bu qadam faqat mavjud toifa uchun", show=True)
        return

    category = await category_service.get_category(session, category_id)
    if category is None:
        await alert(callback, "⚠️ Toifa topilmadi", show=True)
        return

    if kind == "none":
        if category.group_id is None:
            await alert(callback, "Bu toifa allaqachon guruhsiz")
            return
        await category_service.attach_group(session, category, None)
        await alert(callback, "📎 Biriktirilish olib tashlandi", show=True)
    else:
        group = await group_service.get_group(session, int(value))
        if group is None or group.settings is None:
            await alert(callback, "⚠️ Guruh topilmadi", show=True)
            return
        await category_service.attach_group(session, category, group.id)
        if not group.settings.posting_enabled:
            await alert(
                callback,
                f"📎 «{group.display}» guruhiga biriktirildi.\n"
                "ℹ️ Joylash uchun guruhda e'lon joylashni yoqing.",
                show=True,
            )
        else:
            await alert(callback, f"📎 «{group.display}» guruhiga biriktirildi", show=True)

    await render_card(callback, session, category.id)


@router.callback_query(CategoryCB.filter(F.action == "active"))
async def toggle_active(callback: CallbackQuery, callback_data: CategoryCB, session: AsyncSession) -> None:
    category = await category_service.get_category(session, callback_data.category_id)
    if category is None:
        await alert(callback, "⚠️ Toifa topilmadi", show=True)
        return

    await category_service.set_active(session, category, not category.is_active)
    await render_card(callback, session, category.id)
    await alert(callback, "🟢 Yoqildi" if category.is_active else "⏸ To'xtatildi")


@router.callback_query(CategoryCB.filter(F.action == "moderation"))
async def toggle_moderation(
    callback: CallbackQuery, callback_data: CategoryCB, session: AsyncSession
) -> None:
    category = await category_service.get_category(session, callback_data.category_id)
    if category is None:
        await alert(callback, "⚠️ Toifa topilmadi", show=True)
        return

    await category_service.set_moderation(session, category, not category.moderation_required)
    await render_card(callback, session, category.id)
    await alert(
        callback,
        "🧾 Yangi e'lonlar admin tasdig'ini kutadi" if category.moderation_required else "✅ E'lonlar darhol navbatga tushadi",
        show=True,
    )


@router.callback_query(CategoryCB.filter(F.action == "order"))
async def on_order(callback: CallbackQuery, session: AsyncSession) -> None:
    await render_order(callback, session)
    await alert(callback, "")


@router.callback_query(CategoryCB.filter(F.action.in_({"order_up", "order_down", "up", "down"})))
async def move_category(callback: CallbackQuery, callback_data: CategoryCB, session: AsyncSession) -> None:
    category = await category_service.get_category(session, callback_data.category_id)
    if category is None:
        await alert(callback, "⚠️ Toifa topilmadi", show=True)
        return

    direction = "up" if callback_data.action.endswith("up") else "down"
    moved = await category_service.move(session, category, direction)

    if callback_data.action.startswith("order_"):
        await render_order(callback, session)
        await alert(callback, "✅ Tartib o'zgardi" if moved else "Chegaraga yetdi")
    else:
        await render_card(callback, session, category.id)
        await alert(callback, "✅ Tartib o'zgardi" if moved else "Chegaraga yetdi")


@router.callback_query(CategoryCB.filter(F.action == "delete"))
async def on_delete(callback: CallbackQuery, callback_data: CategoryCB, session: AsyncSession) -> None:
    category = await category_service.get_category(session, callback_data.category_id)
    if category is None:
        await alert(callback, "⚠️ Toifa topilmadi", show=True)
        return

    stats = await category_service.get_category_stats(session, category.id)
    text = (
        f"🗑 <b>{escape_html(category_service.display_name(category))}</b> toifasini o'chirasizmi?\n\n"
        f"📢 Bu toifadagi e'lonlar: <b>{stats['total']}</b> (faol {stats['active']})\n"
        "⚠️ E'lonlar ham o'chib ketadi. Ortga qaytarib bo'lmaydi."
    )
    await render(callback, text, delete_confirm_kb(category.id, ads=stats["total"]))
    await alert(callback, "")


@router.callback_query(CategoryCB.filter(F.action == "delete_confirm"))
async def on_delete_confirm(
    callback: CallbackQuery, callback_data: CategoryCB, session: AsyncSession
) -> None:
    category = await category_service.get_category(session, callback_data.category_id)
    if category is None:
        await alert(callback, "⚠️ Toifa topilmadi", show=True)
        return

    name = category_service.display_name(category)
    await category_service.delete_category(session, category)
    await render_list(callback, session, 0)
    await alert(callback, f"🗑 «{name}» o'chirildi", show=True)


# ═══════════════════ FSM: nom / interval kiritish ══════════════════
@router.message(StateFilter(AdminCategoryStates.waiting_name), F.text)
async def apply_create_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("⚠️ Nom juda qisqa. Kamida 2 belgi. Bekor qilish: /cancel")
        return

    data = await state.get_data()
    group_id = data.get("create_group_id")

    category = await category_service.create_category(
        session,
        name=name,
        group_id=int(group_id) if group_id else None,
        created_by=message.from_user.id,
    )
    if category is None:
        await message.answer("⚠️ Nomni qabul qilib bo'lmadi. Qaytadan yuboring.")
        return

    await state.clear()
    await message.answer(
        f"✅ Toifa yaratildi: <b>{escape_html(category_service.display_name(category))}</b>"
    )
    await render_card(message, session, category.id)


@router.message(StateFilter(AdminCategoryStates.waiting_rename), F.text)
async def apply_rename(message: Message, state: FSMContext, session: AsyncSession) -> None:
    name = (message.text or "").strip()
    data = await state.get_data()
    category_id = int(data.get("category_id") or 0)

    category = await category_service.get_category(session, category_id)
    if category is None:
        await state.clear()
        await message.answer("⚠️ Toifa topilmadi.")
        return

    updated = await category_service.rename_category(session, category, name)
    if updated is None:
        await message.answer("⚠️ Nom noto'g'ri. Qaytadan yuboring. Bekor qilish: /cancel")
        return

    await state.clear()
    await message.answer(f"✅ Yangi nom: <b>{escape_html(category_service.display_name(category))}</b>")
    await render_card(message, session, category.id)


@router.message(StateFilter(AdminCategoryStates.waiting_interval), F.text)
async def apply_interval(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip()
    data = await state.get_data()
    category_id = int(data.get("category_id") or 0)

    category = await category_service.get_category(session, category_id)
    if category is None:
        await state.clear()
        await message.answer("⚠️ Toifa topilmadi.")
        return

    if not raw.isdigit():
        await message.answer("⚠️ Raqam yuboring (daqiqada) yoki 0. Bekor qilish: /cancel")
        return

    minutes = int(raw)
    if minutes == 0:
        await category_service.set_interval_override(session, category, None)
        await message.answer("✅ Interval guruh sozlamasiga qaytarildi.")
    else:
        if not (MIN_INTERVAL_SEC // 60) <= minutes <= (MAX_INTERVAL_SEC // 60):
            await message.answer(
                f"⚠️ Qiymat {MIN_INTERVAL_SEC // 60}–{MAX_INTERVAL_SEC // 60} daqiqa orasida bo'lishi kerak."
            )
            return
        await category_service.set_interval_override(session, category, minutes * 60)
        await message.answer(f"✅ Alohida interval saqlandi: <b>{minutes} daqiqa</b>")

    await state.clear()
    await render_card(message, session, category.id)


@router.message(StateFilter(AdminCategoryStates), Command("cancel"))
async def cancel_category_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    await state.clear()
    category_id = int(data.get("category_id") or 0)

    if category_id:
        await render_card(message, session, category_id)
    else:
        await render_list(message, session, 0)


# ═══════════════════════════ Yordamchilar ══════════════════════════
def _page(value: str) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _parse_choice(value: str) -> tuple[str, int | str | None]:
    """`setgroup` callback qiymatini tahlil qilish: page:N | none | <group_id>."""
    if value == "none":
        return "none", None
    if value.startswith("page:"):
        try:
            return "page", int(value.split(":", 1)[1])
        except (IndexError, ValueError):
            return "page", 0
    try:
        return "group", int(value)
    except ValueError:
        return "none", None


__all__ = ["render_card", "render_group_categories", "render_list", "router"]
_ = (GroupCB, group_service, human_int, logger)
