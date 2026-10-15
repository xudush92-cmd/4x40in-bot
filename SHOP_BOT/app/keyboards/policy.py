"""Phase 6: har guruhning posbon, tozalovchi va ruxsatlar paneli."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import PermissionKind
from app.db.models import CleanerSetting, Group, GroupMessageAction, GuardSetting, Permission
from app.keyboards.callbacks import AdminCB, GroupCB, PolicyCB
from app.keyboards.common import nav_row
from app.utils.text import truncate


def _button(text: str, action: str, group_id: int = 0, value: str = "-") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=PolicyCB(
        action=action, group_id=group_id, value=value,
    ).pack())


def choose_groups(groups: list[Group], *, source: str, page: int, pages: int) -> InlineKeyboardMarkup:
    rows = [[_button(f"{'🟢' if g.is_active else '⏸'} {truncate(g.display, 35)}",
                     "perm" if source == "permissions" else "home", g.id, source)]
            for g in groups]
    rows.append(nav_row(
        prev_data=PolicyCB(action="choose", value=f"{source}.{page - 1}").pack() if page else None,
        next_data=PolicyCB(action="choose", value=f"{source}.{page + 1}").pack() if page + 1 < pages else None,
        page=page, total_pages=pages,
        refresh_data=PolicyCB(action="choose", value=f"{source}.{page}").pack(),
    ))
    if source == "permissions":
        rows.append([_button("🌐 Global ruxsatlar", "perm")])
    rows.append([InlineKeyboardButton(text="◀️ Boshqaruv paneli", callback_data=AdminCB(action="menu").pack())])
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def guard_kb(group: Group, guard: GuardSetting, *, can_edit: bool) -> InlineKeyboardMarkup:
    gid = group.id
    rows: list[list[InlineKeyboardButton]] = []
    if can_edit:
        rows.extend([
            [_button(f"{'🟢' if guard.enabled and group.settings.guard_enabled else '🔴'} Posbonni yoqish/to'xtatish",
                     "gt", gid, "enabled")],
            [_button(f"{'🧪 Sinov' if guard.dry_run else '🔴 JONLI'} — rejimni almashtirish", "live", gid, "guard")],
            [_button(f"{'✅' if guard.link_filter else '⬜️'} Havolalar", "gt", gid, "link_filter"),
             _button(f"{'✅' if guard.forward_filter else '⬜️'} Forward", "gt", gid, "forward_filter")],
            [_button(f"{'✅' if guard.mention_filter else '⬜️'} @mention", "gt", gid, "mention_filter"),
             _button(f"{'✅' if guard.exemption_for_admins else '⬜️'} Guruh adminlari istisno", "gt", gid, "exemption_for_admins")],
            [_button("🌐 Oq ro'yxat domenlari", "ge", gid, "allowed_domains"),
             _button("🚫 Taqiqlangan so'zlar", "ge", gid, "banned_words")],
            [_button("📊 Jazo rejimi", "penalties", gid),
             _button("🎯 Ogohlantirish chegarasi", "ge", gid, "warn_limit")],
            [_button("⏱ Mute daqiqasi", "ge", gid, "mute_minutes"),
             _button("🕒 Hisob oynasi (soat)", "ge", gid, "warn_window_hours")],
        ])
    rows.extend([
        [_button("📋 Sabab-amallar jurnali", "log", gid), _button("🔑 Ruxsatlar", "perm", gid)],
        [_button("👤 Foydalanuvchini topish", "user_find", gid)],
        [_button("🛑 GURUHNI FAVQULODDA PAUZA", "pause_ask", gid)] if can_edit and group.is_active else [],
        [InlineKeyboardButton(text="◀️ Guruh kartasi", callback_data=GroupCB(action="card", group_id=gid).pack())],
    ])
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def cleaner_kb(group: Group, cleaner: CleanerSetting, *, can_edit: bool) -> InlineKeyboardMarkup:
    gid = group.id
    rows: list[list[InlineKeyboardButton]] = []
    if can_edit:
        rows.extend([
            [_button(f"{'🟢' if cleaner.enabled and group.settings.cleaner_enabled else '🔴'} Tozalovchini yoqish/to'xtatish",
                     "ct", gid, "enabled")],
            [_button(f"{'🧪 Sinov' if cleaner.dry_run else '🔴 JONLI'} — rejimni almashtirish", "live", gid, "cleaner")],
            [_button(f"{'✅' if cleaner.delete_join_leave else '⬜️'} Kirdi-chiqdi", "ct", gid, "delete_join_leave"),
             _button(f"{'✅' if cleaner.delete_service else '⬜️'} Xizmat", "ct", gid, "delete_service")],
            [_button(f"{'✅' if cleaner.delete_links else '⬜️'} Havolalar", "ct", gid, "delete_links"),
             _button(f"{'✅' if cleaner.delete_violations else '⬜️'} Qoidabuzar xabar", "ct", gid, "delete_violations")],
            [_button(f"{'✅' if cleaner.delete_old_ads else '⬜️'} Eski e'lonlar", "ct", gid, "delete_old_ads"),
             _button(f"{'✅' if cleaner.keep_pinned else '⬜️'} Mahkamlanganni saqla", "ct", gid, "keep_pinned")],
            [_button("🔢 E'londan nechta qolsin", "ce", gid, "keep_last_ads"),
             _button("⏱ Xabarni kechiktirish", "ce", gid, "delete_after_seconds")],
        ])
    rows.extend([
        [_button("📋 Tozalash jurnali", "log", gid), _button("🔑 Ruxsatlar", "perm", gid)],
        [_button("🛑 GURUHNI FAVQULODDA PAUZA", "pause_ask", gid)] if can_edit and group.is_active else [],
        [InlineKeyboardButton(text="◀️ Guruh kartasi", callback_data=GroupCB(action="card", group_id=gid).pack())],
    ])
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def pending_kb(group_id: int, entries: list[GroupMessageAction], *, can_edit: bool) -> InlineKeyboardMarkup:
    rows = ([[_button(f"❌ #{a.id} · xabar #{a.message_id} · {a.status}",
                      "action_cancel_ask", group_id, str(a.id))] for a in entries]
            if can_edit else [])
    rows.append([_button("🔄 Yangilash", "pending", group_id)])
    rows.append([_button("◀️ Sabab-amallar jurnali", "log", group_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def penalty_kb(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button("⚠️ Faqat ogohlantirish", "pen", group_id, "warn")],
        [_button("⏱ Chegaradan so'ng mute", "pen", group_id, "mute")],
        [_button("🚫 Chegaradan so'ng mute → ban", "pen", group_id, "ban")],
        [_button("◀️ Posbon", "home", group_id, "guard")],
    ])


def confirm_kb(action: str, group_id: int, value: str, back: str,
               *, cancel_action: str = "home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button("✅ HA, tasdiqlayman", action, group_id, value)],
        [_button("❌ Bekor qilish", cancel_action, group_id, back)],
    ])


def history_kb(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button("🔄 Yangilash", "log", group_id),
         _button("⏳ Kutilayotgan/noaniq amallar", "pending", group_id)],
        [_button("🛡 Posbon", "home", group_id, "guard"),
         _button("🧹 Tozalovchi", "home", group_id, "cleaner")],
    ])


PERMISSION_LABELS: dict[str, str] = {
    PermissionKind.FULL_EXEMPT: "🛡 Hammasidan ozod",
    PermissionKind.GUARD_EXEMPT: "Posbondan ozod",
    PermissionKind.CLEANER_EXEMPT: "Tozalovchidan ozod",
    PermissionKind.LINK_ALLOWED: "Havola yuborish",
    PermissionKind.COUNTER_EXEMPT: "Sanoqchidan ozod (Phase 7)",
}


def permission_kb(group_id: int, entries: list[Permission], *, can_edit: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_edit:
        rows.append([_button("➕ Ruxsat berish", "perm_add", group_id)])
        rows.extend([[_button(f"❌ #{p.id} · {p.user_id} · {truncate(PERMISSION_LABELS.get(p.kind, p.kind), 23)}",
                              "perm_revoke", p.group_id or 0, str(p.id))] for p in entries[:12]])
    rows.extend([
        [_button("🔄 Yangilash", "perm", group_id)],
        [_button("🌐 Global ruxsatlar" if group_id else "👥 Guruh tanlash", "perm" if group_id else "choose",
                 0, "-" if group_id else "permissions.0")],
        [InlineKeyboardButton(text="◀️ Guruh kartasi" if group_id else "◀️ Boshqaruv paneli",
                              callback_data=(GroupCB(action="card", group_id=group_id).pack()
                                             if group_id else AdminCB(action="menu").pack()))],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def permission_types_kb(group_id: int) -> InlineKeyboardMarkup:
    rows = [[_button(label, "perm_kind", group_id, kind)] for kind, label in PERMISSION_LABELS.items()
            if kind != PermissionKind.COUNTER_EXEMPT]  # Phase 7gacha faol emas
    rows.append([_button("❌ Bekor qilish", "perm", group_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


__all__ = [
    "PERMISSION_LABELS", "choose_groups", "cleaner_kb", "confirm_kb", "guard_kb", "history_kb",
    "penalty_kb", "pending_kb", "permission_kb", "permission_types_kb",
]
