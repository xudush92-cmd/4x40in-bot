"""👥 Guruhlar bo'limi (Phase 1).

Imkoniyatlar:
  * guruhlar ro'yxati va kartasi (holat, a'zolar, huquqlar)
  * qo'shish yo'riqnomasi (bot guruhga qo'shilganda avtomatik paydo bo'ladi)
  * ❚ pauza / yoqish, huquqlarni qo'lda tekshirish, o'chirish
  * funksiya tumbleri (e'lon joylash, sanoqchi, posbon, tozalovchi, salomlashuv)
  * interval, jitter, kunlik limit, tinch soatlar
  * 🎛 Matritsa — barcha guruhlar × funksiyalar bir ekranda
"""

from __future__ import annotations

from math import ceil

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    FEATURE_LABELS,
    FEATURE_PHASES,
    FEATURE_SHORT,
    MAX_DAILY_POST_LIMIT,
    MAX_INTERVAL_SEC,
    MAX_JITTER_PERCENT,
    MIN_INTERVAL_SEC,
    AdminRole,
    GroupFeature,
)
from app.db.models import ActionLog, CleanerSetting, Group
from app.filters import IsAdmin
from app.handlers.admin._roles import ReadOnlyForModerator
from app.keyboards.callbacks import FeatureCB, GroupCB
from app.keyboards.common import PER_PAGE_GROUPS, PER_PAGE_MATRIX
from app.keyboards.groups import (
    add_group_kb,
    cancel_kb,
    delete_confirm_kb,
    group_card_kb,
    group_diagnostic_kb,
    group_features_kb,
    group_settings_kb,
    groups_list_kb,
    matrix_kb,
)
from app.services import group_service
from app.services.group_service import (
    RightsCheck,
    apply_rights_check,
    check_group_rights,
    validate_daily_limit,
    validate_interval_minutes,
    validate_jitter,
)
from app.states import AdminGroupStates
from app.utils.text import (
    escape_html,
    fmt_interval,
    fmt_quiet_hours,
    human_int,
    parse_quiet_hours,
    truncate,
)
from app.utils.tg import alert, render
from app.utils.time import fmt_dt

router = Router(name="admin:groups")
router.message.filter(IsAdmin(AdminRole.ADMIN))
router.callback_query.filter(IsAdmin())
router.callback_query.middleware(ReadOnlyForModerator(
    {"list", "card", "add", "matrix", "feats", "settings", "cats", "diagnostic"},
))

PAUSED_REASONS = {
    "manual": "admin qo'lda to'xtatgan",
    "no_rights": "bot admin huquqini yo'qotgan",
    "chat_not_found": "guruh topilmadi / bot chiqarilgan",
    "bot_left": "bot guruhdan chiqarilgan",
    "error": "ketma-ket xatolar",
    "empty_queue": "navbatda e'lon yo'q",
}

# ═══════════════════════════ Ekranlar ═══════════════════════════════
def _list_text(groups: list[Group], total: int, active: int, paused: int) -> str:
    lines = [
        "👥 <b>Guruhlar</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Jami: <b>{total}</b>  ·  🟢 Faol: <b>{active}</b>  ·  ⏸ Pauza: <b>{paused}</b>",
        "",
    ]
    if not groups:
        lines += [
            "📭 Hozircha guruh yo'q.\n",
            "➕ <b>Guruh qo'shish</b> tugmasini bosing va ko'rsatmalarga amal qiling.",
        ]
    else:
        lines.append("Guruhni bosing — karta va sozlamalar ochiladi.")
    return "\n".join(lines)


def _card_text(group: Group, stats: dict[str, int]) -> str:
    s = group.settings
    warnings: list[str] = []

    if not group.is_supergroup:
        warnings.append("⚠️ Bu <b>oddiy guruh</b> — mute/ban ishlamaydi (supergroup kerak).")
    if not group.bot_is_admin:
        warnings.append("❌ Bot <b>admin emas</b> — funksiyalar ishlamaydi.")
    if group.last_error and group.bot_is_admin:
        warnings.append(f"⚠️ {escape_html(truncate(group.last_error, 120))}")

    lines = [
        f"👥 <b>{escape_html(group.display)}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🆔 <code>{group.tg_chat_id}</code>",
        f"👤 A'zolar: <b>{human_int(group.member_count) if group.member_count else '—'}</b>",
        f"📦 Turi: {'supergroup ✅' if group.is_supergroup else 'oddiy guruh ⚠️'}",
        f"🛠 Bot admin: {'✅' if group.bot_is_admin else '❌'}",
        f"📌 Holat: {'🟢 Faol' if group.is_active else '⏸ Pauza'}",
    ]

    if not group.is_active and group.paused_reason:
        lines.append(f"⏸ Sabab: {PAUSED_REASONS.get(group.paused_reason, group.paused_reason)}")

    if group.bot_rights:
        marks = [
            f"{'🗑' if group.bot_rights.get('can_delete_messages') else '🚫🗑'}",
            f"{'🚫' if group.bot_rights.get('can_restrict_members') else '🚫❌'}",
            f"{'🔗' if group.bot_rights.get('can_invite_users') else '🔗❌'}",
        ]
        lines.append("🔑 Huquqlar: " + " · ".join(marks))

    if s is not None:
        features = [FEATURE_SHORT.get(f, "") for f in FEATURE_LABELS if getattr(s, f"{f}_enabled", False)]
        lines += [
            "━━━━━━━━━━━━━━━━━━━━",
            f"🧩 Yoqilgan funksiyalar: {' '.join(features) if features else '— yo‘q'}",
            f"⏱ Interval: <b>{fmt_interval(s.interval_sec)}</b> (±{s.jitter_percent}%)",
            f"📆 Kunlik limit: <b>{s.daily_post_limit}</b>",
            f"🌙 Tinch soatlar: <b>{fmt_quiet_hours(s.quiet_start, s.quiet_end)}</b>",
        ]

    lines += [
        "━━━━━━━━━━━━━━━━━━━━",
        f"🗂 Toifalar: <b>{stats.get('categories', 0)}</b>  ·  📢 E'lonlar: <b>{stats.get('ads', 0)}</b>",
    ]

    if group.rotation is not None:
        lines.append(
            "🚀 Oxirgi joylash: "
            + (fmt_dt(group.rotation.last_post_at) if group.rotation.last_post_at else "—")
        )
        if group.rotation.next_post_at:
            lines.append(f"📅 Keyingi joylash: {fmt_dt(group.rotation.next_post_at)}")

    if warnings:
        lines += ["", "━━━━━━━━━━━━━━━━━━━━"] + warnings

    return "\n".join(lines)


def _features_text(group: Group) -> str:
    s = group.settings
    lines = [
        f"🧩 <b>{escape_html(group.display)}</b> — funksiyalar",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    for feature, label in FEATURE_LABELS.items():
        enabled = bool(getattr(s, f"{feature}_enabled", False)) if s else False
        phase = FEATURE_PHASES.get(feature, 9)
        note = (f"  <i>(Phase {phase} da ishga tushadi)</i>" if phase > 7 else "")
        lines.append(f"{'🟢' if enabled else '🔴'} {label}{note}")

    lines += [
        "━━━━━━━━━━━━━━━━━━━━",
        "🖼 <b>Kontentni himoya qilish</b> — joylangan e'lonlarni nusxalashni taqiqlaydi: "
        f"{'🟢 yoqilgan' if (s and s.protect_content) else '🔴 o‘chirilgan'}",
        "",
        "<i>Tugmani bosib yoqish/o'chirish mumkin. O'zgarish darhol saqlanadi.</i>",
    ]
    return "\n".join(lines)


def _settings_text(group: Group, *, old_ads_enabled: bool = False,
                   old_ads_dry_run: bool = False) -> str:
    s = group.settings
    if s is None:
        return "⚠️ Sozlamalar topilmadi."
    old_ads_text = ("🧪 sinovda (o‘chmaydi; tozalovchida jonli rejimni tasdiqlang)"
                    if old_ads_dry_run else "🟢 faqat eng oxirgisi qoladi"
                    if old_ads_enabled else "🔴 o‘chirilmaydi")
    return (
        f"⚙️ <b>{escape_html(group.display)}</b> — joylash sozlamalari\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ Interval: <b>{fmt_interval(s.interval_sec)}</b>\n"
        f"🔀 Jitter: <b>±{s.jitter_percent}%</b>\n"
        f"📆 Kunlik limit: <b>{s.daily_post_limit}</b> xabar\n"
        f"🌙 Tinch soatlar: <b>{fmt_quiet_hours(s.quiet_start, s.quiet_end)}</b>\n"
        f"🧹 Eski e'lon nusxalari: {old_ads_text}\n"
        f"👋 Salomlashuv: {'🟢' if s.welcome_enabled else '🔴'}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Minimal interval: {MIN_INTERVAL_SEC // 60} daqiqa "
        f"(Telegram limiti: guruhga 20 xabar/daqiqa)</i>\n"
        "Qiymatni o'zgartirish uchun tugmani bosing."
    )


def _matrix_text(groups: list[Group], page: int, total_pages: int, total: int) -> str:
    legend = "  ".join(f"{FEATURE_SHORT[f]} — {FEATURE_LABELS[f].split(' ', 1)[-1]}" for f in FEATURE_LABELS)
    return (
        "🎛 <b>Funksiyalar matritsasi</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{legend}\n\n"
        f"Jami guruh: <b>{total}</b> · sahifa <b>{page + 1}/{max(1, total_pages)}</b>\n\n"
        "<i>Guruh nomini bosing — kartasi ochiladi.\n"
        "✅ — yoqilgan, ⬜️ — o'chirilgan. Sanoqchi/posbon/tozalovchi "
        "faqat o'z siyosatida jonli rejim tasdiqlanganda amal qiladi.</i>"
    )


async def render_list(target, session: AsyncSession, page: int = 0) -> None:
    total = await group_service.count_groups(session)
    active, paused = await group_service.count_groups_by_status(session)
    total_pages = max(1, ceil(total / PER_PAGE_GROUPS))
    page = max(0, min(page, total_pages - 1))

    groups = await group_service.list_groups(session, offset=page * PER_PAGE_GROUPS, limit=PER_PAGE_GROUPS)
    await render(target, _list_text(groups, total, active, paused), groups_list_kb(groups, page, total_pages))


async def render_card(target, session: AsyncSession, group_id: int) -> bool:
    group = await group_service.get_group(session, group_id)
    if group is None:
        await render(target, "⚠️ Guruh topilmadi (o'chirilgan bo'lishi mumkin).")
        return False

    stats = await group_service.get_group_stats(session, group)
    await render(target, _card_text(group, stats), group_card_kb(group))
    return True


async def render_features(target, session: AsyncSession, group_id: int) -> None:
    group = await group_service.get_group(session, group_id)
    if group is None:
        await render(target, "⚠️ Guruh topilmadi.")
        return
    await render(target, _features_text(group), group_features_kb(group))


async def render_settings(target, session: AsyncSession, group_id: int) -> None:
    group = await group_service.get_group(session, group_id)
    if group is None:
        await render(target, "⚠️ Guruh topilmadi.")
        return
    policy = await session.get(CleanerSetting, group_id)
    old_ads = bool(policy and policy.enabled and policy.delete_old_ads
                   and group.settings and group.settings.cleaner_enabled)
    dry_run = bool(old_ads and policy.dry_run)
    await render(target, _settings_text(group, old_ads_enabled=old_ads, old_ads_dry_run=dry_run),
                 group_settings_kb(group, old_ads_enabled=old_ads, old_ads_dry_run=dry_run))


async def render_matrix(target, session: AsyncSession, page: int = 0) -> None:
    total = await group_service.count_groups(session)
    total_pages = max(1, ceil(total / PER_PAGE_MATRIX))
    page = max(0, min(page, total_pages - 1))

    groups = await group_service.list_groups(session, offset=page * PER_PAGE_MATRIX, limit=PER_PAGE_MATRIX)
    await render(target, _matrix_text(groups, page, total_pages, total), matrix_kb(groups, page, total_pages))


# ═══════════════════════════ Ro'yxat / karta ═══════════════════════
@router.callback_query(GroupCB.filter(F.action == "list"))
async def on_list(callback: CallbackQuery, callback_data: GroupCB, session: AsyncSession) -> None:
    await render_list(callback, session, _page(callback_data.value))
    await alert(callback, "")


@router.callback_query(GroupCB.filter(F.action == "card"))
async def on_card(callback: CallbackQuery, callback_data: GroupCB, session: AsyncSession) -> None:
    ok = await render_card(callback, session, callback_data.group_id)
    await alert(callback, "" if ok else "Guruh topilmadi")


@router.callback_query(GroupCB.filter(F.action == "diagnostic"))
async def on_diagnostic(callback: CallbackQuery, callback_data: GroupCB,
                        session: AsyncSession, role: str | None) -> None:
    from app.services.group_diagnostics import diagnostic_text

    group = await group_service.get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "Guruh topilmadi", show=True)
        return
    await render(callback, await diagnostic_text(session, group),
                 group_diagnostic_kb(group.id, can_refresh=role in {AdminRole.ADMIN, AdminRole.SUPER}))
    await alert(callback, "")


@router.callback_query(GroupCB.filter(F.action == "add"))
async def on_add(callback: CallbackQuery) -> None:
    text = (
        "➕ <b>Guruh qo'shish</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ Botni guruhga <b>qo'shing</b>\n"
        "2️⃣ Botni <b>admin</b> qiling va quyidagi huquqlarni bering:\n"
        "   • 🗑 Xabarlarni o'chirish\n"
        "   • 🚫 A'zolarni cheklash (mute/ban)\n"
        "   Ixtiyoriy: 🔗 Taklif havolalari yaratish (shaxsiy havola kerak bo'lsa)\n"
        "3️⃣ Guruh <b>supergroup</b> bo'lishi kerak (aks holda mute/ban ishlamaydi)\n"
        "4️⃣ @BotFather → /setprivacy → <b>Disable</b> (majburiy!)\n\n"
        "Guruh qo'shilgach ro'yxatda o'zi paydo bo'ladi va menga xabar keladi.\n"
        "Keyin shu yerdan sozlamalarni yoqasiz."
    )
    await render(callback, text, add_group_kb())
    await alert(callback, "")


@router.callback_query(GroupCB.filter(F.action == "matrix"))
async def on_matrix(callback: CallbackQuery, callback_data: GroupCB, session: AsyncSession) -> None:
    await render_matrix(callback, session, _page(callback_data.value))
    await alert(callback, "")


# ═══════════════════════════ Funksiyalar ═══════════════════════════
@router.callback_query(GroupCB.filter(F.action == "feats"))
async def on_features(callback: CallbackQuery, callback_data: GroupCB, session: AsyncSession) -> None:
    await render_features(callback, session, callback_data.group_id)
    await alert(callback, "")


@router.callback_query(FeatureCB.filter())
async def on_feature_toggle(
    callback: CallbackQuery, callback_data: FeatureCB, session: AsyncSession, role: str | None
) -> None:
    """Funksiya tumbleri (funksiyalar ekrani, 🎛 matritsa yoki sozlamalardan)."""
    group = await group_service.get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi", show=True)
        return

    feature = str(callback_data.feature)
    if feature not in FEATURE_LABELS:
        await alert(callback, "⚠️ Noma'lum funksiya", show=True)
        return
    if feature in (GroupFeature.GUARD, GroupFeature.CLEANER, GroupFeature.COUNTER) and role not in (
        AdminRole.ADMIN, AdminRole.SUPER
    ):
        await alert(callback, "⛔️ Sanoqchi/posbon/tozalovchini faqat admin boshqaradi.", show=True)
        return

    changed = await group_service.set_feature(
        session, group, feature, bool(callback_data.enabled), actor_id=callback.from_user.id,
    )
    label = FEATURE_LABELS[feature]
    phase = FEATURE_PHASES.get(feature, 9)

    if not changed:
        await alert(callback, "Qiymat o'zgarmadi")
    else:
        state = "🟢 yoqildi" if callback_data.enabled else "🔴 o'chirildi"
        if feature == GroupFeature.POSTING:
            extra = "" if group.is_active else "\n⚠️ Guruh pauzada — joylash boshlanmaydi."
            await alert(callback, f"{label}: {state}{extra}", show=True)
        elif feature in (GroupFeature.GUARD, GroupFeature.CLEANER, GroupFeature.COUNTER):
            await alert(callback, f"{label}: {state}\n🧪 Avval dry-run! Jonli rejimni guruh ekranida "
                        "alohida tasdiqlang.", show=True)
        else:
            await alert(
                callback,
                f"{label}: {state}\nℹ️ Bu funksiya Phase {phase} da jonli ishga tushadi.",
                show=True,
            )

    # Tugma bosilgan ekranni qayta chizamiz
    if callback_data.origin == "matrix":
        await render_matrix(callback, session, max(0, int(callback_data.page or 0)))
    elif callback_data.origin == "settings":
        await render_settings(callback, session, group.id)
    else:
        await render_features(callback, session, group.id)


@router.callback_query(GroupCB.filter(F.action == "toggle"))
async def on_setting_toggle(
    callback: CallbackQuery, callback_data: GroupCB, session: AsyncSession
) -> None:
    """Funksiyalar ekranidagi tumbler: kontent himoyasi."""
    group = await group_service.get_group(session, callback_data.group_id)
    if group is None or group.settings is None:
        await alert(callback, "⚠️ Guruh topilmadi", show=True)
        return

    if callback_data.value != "protect":
        await alert(callback, "⚠️ Noma'lum sozlama", show=True)
        return

    group.settings.protect_content = not group.settings.protect_content
    await session.flush()
    state = "yoqildi 🟢" if group.settings.protect_content else "o'chirildi 🔴"
    await alert(callback, f"🖼 Kontent himoyasi {state}")
    await render_features(callback, session, group.id)


# ═══════════════════════════ Sozlamalar ════════════════════════════
@router.callback_query(GroupCB.filter(F.action == "old_ads"), IsAdmin(AdminRole.ADMIN))
async def on_old_ads(callback: CallbackQuery, callback_data: GroupCB, session: AsyncSession) -> None:
    """Phase 4 tozalash: bitta e'londan guruhda oxirgi nusxa qolsin."""
    group = await group_service.get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    from app.services import group_policy_service as policies

    policy = await policies.ensure_cleaner(session, group.id)
    was_on = bool(policy.enabled and policy.delete_old_ads
                  and group.settings and group.settings.cleaner_enabled)
    actor_id = callback.from_user.id
    if was_on:
        await policies.edit_cleaner(session, group, "delete_old_ads", False, actor_id)
    else:
        # Qisqa tugma hech qachon dry-run'ni chetlab o'tmasin. Agar cleaner
        # oldindan jonli rejimda bo'lsa, uning shu tasdiqlangan rejimi saqlanadi.
        if not (policy.enabled and group.settings.cleaner_enabled):
            await policies.edit_cleaner(session, group, "enabled", True, actor_id)
        await policies.edit_cleaner(session, group, "delete_old_ads", True, actor_id)
    await render_settings(callback, session, group.id)
    mode = "sinovda sozlandi; jonli rejimni tozalovchi ekranida tasdiqlang" if policy.dry_run else "yoqildi"
    await alert(callback, "🧹 Eski nusxalar " + ("o'chirildi" if was_on else mode))


@router.callback_query(GroupCB.filter(F.action == "old_ads"))
async def on_old_ads_denied(callback: CallbackQuery) -> None:
    await alert(callback, "⛔️ Buni faqat admin sozlay oladi.", show=True)


@router.callback_query(GroupCB.filter(F.action == "settings"))
async def on_settings(callback: CallbackQuery, callback_data: GroupCB, session: AsyncSession) -> None:
    await render_settings(callback, session, callback_data.group_id)
    await alert(callback, "")


@router.callback_query(GroupCB.filter(F.action == "pause"))
async def on_pause(callback: CallbackQuery, callback_data: GroupCB, session: AsyncSession,
                   role: str | None) -> None:
    if role not in (AdminRole.ADMIN, AdminRole.SUPER):
        await alert(callback, "⛔️ Guruh pauzasini faqat admin boshqaradi.", show=True)
        return
    group = await group_service.get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi", show=True)
        return

    previous = group.is_active
    await group_service.set_active(session, group, not previous)
    session.add(ActionLog(actor_id=callback.from_user.id, action="group_set_active",
                          entity="group", entity_id=group.id, group_id=group.id,
                          before={"is_active": previous}, after={"is_active": group.is_active}))
    await render_card(callback, session, group.id)
    await alert(
        callback,
        "▶️ Guruh yoqildi" if group.is_active else "⏸ Guruh to'xtatildi (joylash o'chdi)",
        show=True,
    )


@router.callback_query(GroupCB.filter(F.action == "refresh"))
async def on_refresh(callback: CallbackQuery, callback_data: GroupCB, session: AsyncSession, bot) -> None:
    """Huquqlarni qo'lda tekshirish (Telegram'dan)."""
    group = await group_service.get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi", show=True)
        return

    await alert(callback, "🔍 Tekshirilmoqda…")
    result: RightsCheck = await check_group_rights(bot, group)
    was_active = group.is_active
    ok = await apply_rights_check(session, bot, group, result, notify=False)

    if ok and not was_active and group.paused_reason == "no_rights":
        logger.info("Huquqlar tiklandi: {}", group.display)

    await render_card(callback, session, group.id)
    await alert(callback, result.summary, show=not ok)


@router.callback_query(GroupCB.filter(F.action == "delete"))
async def on_delete(callback: CallbackQuery, callback_data: GroupCB, session: AsyncSession) -> None:
    group = await group_service.get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi", show=True)
        return

    stats = await group_service.get_group_stats(session, group)
    text = (
        f"🗑 <b>{escape_html(group.display)}</b> guruhini bazadan o'chirasizmi?\n\n"
        f"🗂 Toifalar: {stats['categories']} · 📢 E'lonlar: {stats['ads']}\n\n"
        "⚠️ Toifalar o'chmaydi, lekin guruhsiz qoladi. Bu amalni ortga qaytarib bo'lmaydi."
    )
    await render(callback, text, delete_confirm_kb(group.id))
    await alert(callback, "")


@router.callback_query(GroupCB.filter(F.action == "delete_confirm"))
async def on_delete_confirm(
    callback: CallbackQuery, callback_data: GroupCB, session: AsyncSession
) -> None:
    group = await group_service.get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi", show=True)
        return

    title = group.display
    await group_service.delete_group(session, group)
    await render_list(callback, session, 0)
    await alert(callback, f"🗑 «{title}» o'chirildi", show=True)


@router.callback_query(GroupCB.filter(F.action == "cats"))
async def on_group_categories(
    callback: CallbackQuery, callback_data: GroupCB, session: AsyncSession
) -> None:
    """Guruhga biriktirilgan toifalar (categories bo'limi orqali)."""
    from app.handlers.admin.categories import render_group_categories

    await render_group_categories(callback, session, callback_data.group_id)
    await alert(callback, "")


# ═══════════════════ FSM: qiymatlarni qo'lda kiritish ═══════════════
@router.callback_query(GroupCB.filter(F.action.in_({"interval", "jitter", "limit", "quiet"})))
async def start_edit(
    callback: CallbackQuery, callback_data: GroupCB, state: FSMContext, session: AsyncSession
) -> None:
    group = await group_service.get_group(session, callback_data.group_id)
    if group is None or group.settings is None:
        await alert(callback, "⚠️ Guruh topilmadi", show=True)
        return

    await state.update_data(group_id=group.id)
    s = group.settings

    prompts = {
        "interval": (
            AdminGroupStates.waiting_interval,
            f"⏱ <b>Joylash intervali</b>\nHozirgi: <b>{fmt_interval(s.interval_sec)}</b>\n\n"
            f"Yangi qiymatni <b>daqiqada</b> yuboring "
            f"({MIN_INTERVAL_SEC // 60}–{MAX_INTERVAL_SEC // 60}).\n"
            "Bekor qilish uchun /cancel",
        ),
        "jitter": (
            AdminGroupStates.waiting_jitter,
            f"🔀 <b>Jitter (tasodifiy siljish)</b>\nHozirgi: <b>±{s.jitter_percent}%</b>\n\n"
            f"0–{MAX_JITTER_PERCENT} orasida foiz yuboring (masalan 10).\n"
            "Jitter guruhlar bir sekundda post qilmasligi uchun kerak.\n"
            "Bekor qilish uchun /cancel",
        ),
        "limit": (
            AdminGroupStates.waiting_limit,
            f"📆 <b>Kunlik limit</b>\nHozirgi: <b>{s.daily_post_limit}</b> xabar\n\n"
            f"1–{MAX_DAILY_POST_LIMIT} orasida son yuboring.\n"
            "Bekor qilish uchun /cancel",
        ),
        "quiet": (
            AdminGroupStates.waiting_quiet,
            f"🌙 <b>Tinch soatlar</b>\nHozirgi: <b>{fmt_quiet_hours(s.quiet_start, s.quiet_end)}</b>\n\n"
            "Masalan: <code>23:00-08:00</code>\n"
            "O'chirish uchun: <code>off</code>\n"
            "Bekor qilish uchun /cancel",
        ),
    }

    # Tugma `action` yuboradi (eski variantlarda `value` ham bo'lishi mumkin)
    entry = prompts.get(callback_data.action) or prompts.get(callback_data.value)
    if entry is None:
        await alert(callback, "⚠️ Noma'lum sozlama", show=True)
        return

    next_state, text = entry
    await state.set_state(next_state)
    await render(callback, text, cancel_kb(group.id))
    await alert(callback, "")


@router.message(StateFilter(AdminGroupStates), Command("cancel"))
async def cancel_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    await state.clear()
    group_id = int(data.get("group_id") or 0)
    if group_id:
        await render_card(message, session, group_id)
    else:
        await render_list(message, session, 0)


async def _group_from_state(state: FSMContext, session: AsyncSession) -> Group | None:
    data = await state.get_data()
    group_id = int(data.get("group_id") or 0)
    if not group_id:
        return None
    return await group_service.get_group(session, group_id)


@router.message(StateFilter(AdminGroupStates.waiting_interval), F.text)
async def apply_interval(message: Message, state: FSMContext, session: AsyncSession) -> None:
    group = await _group_from_state(state, session)
    raw = (message.text or "").strip()

    if not raw.isdigit():
        await message.answer("⚠️ Faqat raqam yuboring (daqiqada). Bekor qilish: /cancel")
        return

    minutes = int(raw)
    if not (MIN_INTERVAL_SEC // 60) <= minutes <= (MAX_INTERVAL_SEC // 60):
        await message.answer(
            f"⚠️ Qiymat {MIN_INTERVAL_SEC // 60}–{MAX_INTERVAL_SEC // 60} daqiqa orasida bo'lishi kerak."
        )
        return

    if group is None or group.settings is None:
        await state.clear()
        await message.answer("⚠️ Guruh topilmadi. /start ni bosing.")
        return

    await group_service.set_setting(session, group, "interval_sec", validate_interval_minutes(minutes))
    await state.clear()
    await message.answer(f"✅ Interval saqlandi: <b>{minutes} daqiqa</b>")
    await render_card(message, session, group.id)


@router.message(StateFilter(AdminGroupStates.waiting_jitter), F.text)
async def apply_jitter(message: Message, state: FSMContext, session: AsyncSession) -> None:
    group = await _group_from_state(state, session)
    raw = (message.text or "").strip()

    if not raw.isdigit():
        await message.answer("⚠️ Faqat raqam yuboring (foizda). Bekor qilish: /cancel")
        return

    percent = int(raw)
    if not 0 <= percent <= MAX_JITTER_PERCENT:
        await message.answer(f"⚠️ Qiymat 0–{MAX_JITTER_PERCENT} orasida bo'lishi kerak.")
        return

    if group is None or group.settings is None:
        await state.clear()
        await message.answer("⚠️ Guruh topilmadi.")
        return

    await group_service.set_setting(session, group, "jitter_percent", validate_jitter(percent))
    await state.clear()
    await message.answer(f"✅ Jitter saqlandi: <b>±{percent}%</b>")
    await render_card(message, session, group.id)


@router.message(StateFilter(AdminGroupStates.waiting_limit), F.text)
async def apply_limit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    group = await _group_from_state(state, session)
    raw = (message.text or "").strip()

    if not raw.isdigit():
        await message.answer("⚠️ Faqat raqam yuboring. Bekor qilish: /cancel")
        return

    limit = int(raw)
    if not 1 <= limit <= MAX_DAILY_POST_LIMIT:
        await message.answer(f"⚠️ Qiymat 1–{MAX_DAILY_POST_LIMIT} orasida bo'lishi kerak.")
        return

    if group is None or group.settings is None:
        await state.clear()
        await message.answer("⚠️ Guruh topilmadi.")
        return

    await group_service.set_setting(session, group, "daily_post_limit", validate_daily_limit(limit))
    await state.clear()
    await message.answer(f"✅ Kunlik limit saqlandi: <b>{limit}</b>")
    await render_card(message, session, group.id)


@router.message(StateFilter(AdminGroupStates.waiting_quiet), F.text)
async def apply_quiet(message: Message, state: FSMContext, session: AsyncSession) -> None:
    group = await _group_from_state(state, session)
    raw = (message.text or "").strip()

    try:
        parsed = parse_quiet_hours(raw)
    except ValueError:
        await message.answer(
            "⚠️ Format noto'g'ri. Masalan: <code>23:00-08:00</code> yoki <code>off</code>"
        )
        return

    if group is None or group.settings is None:
        await state.clear()
        await message.answer("⚠️ Guruh topilmadi.")
        return

    if parsed is None:
        await group_service.set_setting(session, group, "quiet_start", None)
        await group_service.set_setting(session, group, "quiet_end", None)
        await message.answer("✅ Tinch soatlar o'chirildi.")
    else:
        start, end = parsed
        await group_service.set_setting(session, group, "quiet_start", start)
        await group_service.set_setting(session, group, "quiet_end", end)
        await message.answer(f"✅ Tinch soatlar saqlandi: <b>{start} – {end}</b>")

    await state.clear()
    await render_card(message, session, group.id)


def _page(value: str) -> int:
    """Callback'dagi sahifa raqamini xavfsiz o'qish."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


__all__ = [
    "render_card",
    "render_list",
    "render_matrix",
    "render_settings",
    "router",
]
