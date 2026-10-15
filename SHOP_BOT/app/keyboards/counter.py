"""Phase 7: guruhga xos sanoqchi va kanal boshqaruvi tugmalari."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import CounterMode, InviteSource
from app.db.models import CounterSetting, Group, RequiredChannel
from app.keyboards.callbacks import AdminCB, CounterAdminCB, GroupCB, PolicyCB


def _button(label: str, action: str, group_id: int, value: str = "-") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=label, callback_data=CounterAdminCB(
        action=action, group_id=group_id, value=value,
    ).pack())


def choose_kb(groups: list[Group], page: int, pages: int) -> InlineKeyboardMarkup:
    rows = [[_button(f"{'🟢' if group.is_active else '⏸'} {group.display}"[:60],
                     "home", group.id)] for group in groups]
    nav: list[InlineKeyboardButton] = []
    if page:
        nav.append(_button("◀️", "choose", 0, str(page - 1)))
    nav.append(_button(f"{page + 1}/{pages} 🔄", "choose", 0, str(page)))
    if page + 1 < pages:
        nav.append(_button("▶️", "choose", 0, str(page + 1)))
    rows += [nav, [_button("🌐 Umumiy kanallar", "channels", 0)],
             [InlineKeyboardButton(text="◀️ Boshqaruv paneli", callback_data=AdminCB(
                 action="menu",
             ).pack())]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def home_kb(group: Group, row: CounterSetting, *, can_edit: bool) -> InlineKeyboardMarkup:
    gid = group.id
    rows: list[list[InlineKeyboardButton]] = []
    if can_edit:
        rows += [
            [_button(f"{'🟢' if row.enabled and group.settings.counter_enabled else '🔴'} Sanoqchini yoqish/o'chirish",
                     "toggle", gid, "enabled"),
             _button(f"{'🔴 JONLI' if not row.dry_run else '🧪 SINOV'} rejim", "live", gid)],
            [_button(f"{'🔴 HARD (mute)' if row.mode == CounterMode.HARD else '🟢 SOFT (delete)'}",
                     "mode", gid, CounterMode.SOFT if row.mode == CounterMode.HARD else CounterMode.HARD)],
            [_button(f"👥 N = {row.required_n}", "number", gid, "required_n"),
             _button(f"⏳ Qolish: {row.min_stay_minutes} min", "number", gid, "min_stay_minutes")],
            [_button(f"📆 Kunlik: {row.max_per_day}", "number", gid, "max_per_day"),
             _button(f"🔗 Havola limiti: {row.link_member_limit}", "number", gid, "link_member_limit")],
            [_button(f"{'✅' if (row.count_sources or {}).get(InviteSource.LINK) else '⬜️'} Havola orqali",
                     "source", gid, InviteSource.LINK),
             _button(f"{'✅' if (row.count_sources or {}).get(InviteSource.ADDED_BY) else '⬜️'} Qo'lda qo'shish",
                     "source", gid, InviteSource.ADDED_BY)],
            [_button(f"{'✅' if row.require_subscription else '⬜️'} Majburiy kanal", "toggle", gid,
                     "require_subscription"),
             _button(f"{'✅' if row.notify_inviter else '⬜️'} DM xabar", "toggle", gid,
                     "notify_inviter")],
        ]
    rows += [
        [_button("📣 Shu guruh kanallari", "channels", gid),
         _button("🌐 Umumiy kanallar", "channels", 0)],
        [_button("👤 A'zo hisobi (+/−/0)", "user", gid),
         _button("📋 Hisob va sozlama tarixi", "log", gid)],
        [InlineKeyboardButton(text="🔑 Istisnolar", callback_data=PolicyCB(
            action="perm", group_id=gid,
        ).pack())],
        [InlineKeyboardButton(text="◀️ Guruh kartasi", callback_data=GroupCB(
            action="card", group_id=gid,
        ).pack())],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def channels_kb(group_id: int, channels: list[RequiredChannel], *, can_edit: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_edit:
        for channel in channels[:20]:
            if (channel.group_id or 0) == group_id:
                rows.append([_button(f"❌ {channel.title or channel.username or channel.channel_tg_id}"[:55],
                                     "channel_ask", group_id, str(channel.id))])
        rows.append([_button("➕ Kanal qo'shish", "channel_add", group_id)])
    if group_id:
        rows.append([_button("🌐 Umumiy kanallar", "channels", 0)])
        rows.append([_button("◀️ Sanoqchi", "home", group_id)])
    else:
        rows.append([_button("◀️ Sanoqchi guruhlari", "choose", 0, "0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_kb(action: str, group_id: int, value: str = "-") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button("🔴 Tasdiqlayman", action, group_id, value)],
        [_button("◀️ Bekor qilish", "channels" if action == "channel_remove" else "home", group_id)],
    ])


def user_kb(group_id: int, user_id: int, *, can_edit: bool, count: int,
            link_id: int | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_edit:
        rows += [
            [_button("➕ Qo'shish", "adjust", group_id, f"p{user_id}"),
             _button("➖ Kamaytirish", "adjust", group_id, f"m{user_id}")],
            [_button("0️⃣ Nolga tushirish", "zero_ask", group_id, str(user_id))] if count else [],
            [_button("🔗 Havolani bekor qilish", "link_cancel_ask", group_id, str(link_id))]
            if link_id else [],
        ]
    rows += [
        [_button("🔄 Yangilash", "status", group_id, str(user_id))],
        [_button("◀️ Sanoqchi", "home", group_id)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])
