"""Phase 7: har bir guruh uchun sanoqchi, kanallar, hisob va audit paneli.

Jonli rejim faqat alohida tasdiq bilan, real Telegram huquqlari qayta
tekshirilgandan keyin yoqiladi. Kanal nomi oldindan taxmin qilinmaydi.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole, CounterMode
from app.db.models import (
    ActionLog,
    CounterAudit,
    CounterMessageCheck,
    CounterRestriction,
    CounterSetting,
    CounterTotal,
    Group,
    InviteEvent,
    InviteLink,
    RequiredChannel,
)
from app.filters import IsAdmin
from app.handlers.group.counter import _unlock
from app.keyboards.callbacks import CounterAdminCB
from app.keyboards.counter import channels_kb, choose_kb, confirm_kb, home_kb, user_kb
from app.services import counter_service as counters
from app.services.group_service import extract_rights, get_group, list_groups
from app.services.settings_service import settings_service
from app.states import AdminCounterStates
from app.utils.text import escape_html, truncate
from app.utils.tg import alert, render
from app.utils.time import fmt_dt

router = Router(name="admin:counter")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())
_EDITABLE = {AdminRole.ADMIN, AdminRole.SUPER}
_LABELS = {"required_n": "N odam sharti", "min_stay_minutes": "Minimal qolish (daqiqa)",
           "max_per_day": "Kunlik taklif limiti", "link_member_limit": "Shaxsiy havola limiti"}


def _edit(role: str | None) -> bool:
    return role in _EDITABLE


def _revision(row: CounterSetting) -> str:
    return row.updated_at.strftime("%Y%m%d%H%M%S%f") if row.updated_at else "-"


async def render_choose(target: Message | CallbackQuery, session: AsyncSession,
                        page: int = 0) -> None:
    from sqlalchemy import func

    count = (await session.execute(select(func.count()).select_from(Group))).scalar_one()
    pages = max(1, (count + 5) // 6)
    page = max(0, min(page, pages - 1))
    groups = await list_groups(session, offset=page * 6, limit=6)
    await render(target, "🧮 <b>Guruh sanoqchisini tanlang</b>\n"
                 "Har guruh uchun N, rejim, kanal, manba va audit alohida. "
                 "🌐 Global kanallar faqat kanal sharti yoqilgan guruhlarga ta'sir qiladi.",
                 choose_kb(groups, page, pages))


@router.callback_query(CounterAdminCB.filter(F.action == "choose"))
async def choose(callback: CallbackQuery, callback_data: CounterAdminCB,
                 session: AsyncSession) -> None:
    page = int(callback_data.value) if callback_data.value.isdigit() else 0
    await render_choose(callback, session, page)
    await alert(callback, "")


async def render_home(target: Message | CallbackQuery, session: AsyncSession,
                      group_id: int, role: str | None) -> None:
    group = await get_group(session, group_id)
    if group is None or group.settings is None:
        await render(target, "⚠️ Guruh topilmadi.")
        return
    row = await counters.ensure_counter(session, group.id)
    channels = await counters.applicable_channels(session, group.id)
    global_on = await settings_service.is_feature_enabled_fresh("counter")
    source = row.count_sources or {}
    text = (f"🧮 <b>{escape_html(group.display)} — sanoqchi</b>\n"
            f"Guruh: {'🟢' if group.is_active else '⏸'} · "
            f"Global: {'🟢' if global_on else '🛑'} · "
            f"Switch: {'🟢' if group.settings.counter_enabled and row.enabled else '🔴'}\n"
            f"Rejim: <b>{escape_html(row.mode or 'soft').upper()}</b> · "
            f"{'🧪 SINOV (jazo yo‘q)' if row.dry_run else '🔴 JONLI (xabar o‘chadi, hard: mute)'}\n"
            f"N: <b>{row.required_n}</b> · Minimal qolish: <b>{row.min_stay_minutes} min</b> · "
            f"Kunlik: <b>{row.max_per_day}</b> · Havola limiti: <b>{row.link_member_limit}</b>\n"
            f"Manbalar: havola {'✅' if source.get('link') else '—'} / "
            f"qo'lda {'✅' if source.get('added_by') else '—'}\n"
            f"Kanal sharti: {'✅' if row.require_subscription else '—'} "
            f"({len(channels)} ta, global kanallar ham kiritilgan) · "
            f"DM: {'✅' if row.notify_inviter else '—'}\n\n"
            "🔐 Kanal a'zoligi va N <b>ikkalasi</b> tekshiriladi. "
            "N noma'lum bo'lsa yoki Telegram tekshirilmasa jazo berilmaydi. "
            "SOFT: xabar o'chadi; HARD: shart bajarilmaguncha mute ham qo'yiladi.\n"
            "Yangi/yoqilgan guruh avval sinovda. Jonli rejimni alohida tasdiqlang. "
            "Privacy Mode'ni o'chiring.")
    if row.require_subscription and not channels:
        text += "\n⚠️ Kanal hali sozlanmagan: obuna uchun jazo ishlamaydi."
    await render(target, text, home_kb(group, row, can_edit=_edit(role)))


async def render_channels(target: Message | CallbackQuery, session: AsyncSession,
                          group_id: int, role: str | None) -> None:
    if group_id and not await get_group(session, group_id):
        await render(target, "⚠️ Guruh topilmadi.")
        return
    if group_id:
        channels = await counters.applicable_channels(session, group_id)
    else:
        channels = list((await session.execute(select(RequiredChannel).where(
            RequiredChannel.group_id.is_(None), RequiredChannel.is_active.is_(True),
        ).order_by(RequiredChannel.id))).scalars())
    title = "guruh kanallari" if group_id else "umumiy kanallar (barcha guruhlar)"
    items = [f"• <b>{escape_html(ch.title or ch.username or str(ch.channel_tg_id))}</b> "
             f"<code>{ch.channel_tg_id}</code> {'🌐 global' if ch.group_id is None else 'shu guruh'}"
             for ch in channels[:20]]
    text = (f"📣 <b>Majburiy obuna — {title}</b>\n"
            "Faqat sanoqchisida «Majburiy kanal» yoqilgan guruhlarga tatbiq etiladi.\n"
            "Bot kanalda ADMIN bo'lishi kerak; getChatMember ishlamasa jazo yo'q.\n\n"
            + ("\n".join(items) if items else "Hali kanal kiritilmagan.")
            + "\n\n❌ tugmasi kanalni bekor qilishni alohida tasdiqlaydi.")
    await render(target, text, channels_kb(group_id, channels, can_edit=_edit(role)))


async def render_user(target: Message | CallbackQuery, session: AsyncSession,
                      group_id: int, user_id: int, role: str | None) -> None:
    group = await get_group(session, group_id)
    if group is None or user_id <= 0:
        await render(target, "⚠️ Guruh yoki foydalanuvchi ID noto'g'ri.")
        return
    row = await counters.ensure_counter(session, group_id)
    count = await counters.total_for(session, group_id, user_id)
    pending = (await session.execute(select(InviteEvent).where(
        InviteEvent.group_id == group_id, InviteEvent.inviter_id == user_id,
    ).order_by(InviteEvent.id.desc()).limit(5))).scalars().all()
    changes = (await session.execute(select(CounterAudit).where(
        CounterAudit.group_id == group_id, CounterAudit.user_id == user_id,
    ).order_by(CounterAudit.id.desc()).limit(5))).scalars().all()
    restriction = await session.get(CounterRestriction, (group_id, user_id))
    link = (await session.execute(select(InviteLink).where(
        InviteLink.group_id == group_id, InviteLink.user_id == user_id,
        InviteLink.is_active.is_(True),
    ))).scalar_one_or_none()
    text = (f"👤 <b>{escape_html(group.display)} — <code>{user_id}</code></b>\n"
            f"Takliflar: <b>{count}/{row.required_n}</b> · qolgan: {max(0, row.required_n - count)}\n"
            f"Counter mute: {escape_html(restriction.status) if restriction else '—'}\n"
            f"Havola: {'⏳ noaniq/yasalmoqda' if link and link.invite_link.startswith('pending:') else '✅ faol' if link else '—'}\n\n"
            "<b>So'nggi kirishlar (taklif qilgan):</b>\n")
    text += "\n".join(
        f"• {event.invitee_id} · {escape_html(event.source)} · "
        f"{'✅' if event.counted else escape_html(event.reject_reason or 'kutmoqda')}"
        for event in pending
    ) or "—"
    text += "\n\n<b>Qo'lda tuzatishlar (audit):</b>\n"
    text += "\n".join(
        f"• {fmt_dt(change.created_at)} · {change.delta:+d} "
        f"· admin {change.admin_id or '—'} · {escape_html(truncate(change.reason or '', 50))}"
        for change in changes
    ) or "—"
    if link and link.invite_link.startswith("pending:") and _edit(role):
        text += "\n\n⚠️ Noaniq havolani bekor qilish uchun admin kerak; "
        "Telegram'da yaratilgan bo'lishi mumkin, loglarni tekshiring."
    await render(target, text, user_kb(group_id, user_id, can_edit=_edit(role),
                                       count=count, link_id=link.id if link else None))


@router.callback_query(CounterAdminCB.filter(F.action == "home"))
async def home(callback: CallbackQuery, callback_data: CounterAdminCB,
               session: AsyncSession, role: str | None) -> None:
    await render_home(callback, session, callback_data.group_id, role)
    await alert(callback, "")


@router.callback_query(CounterAdminCB.filter(F.action == "channels"))
async def channels(callback: CallbackQuery, callback_data: CounterAdminCB,
                   session: AsyncSession, role: str | None) -> None:
    await render_channels(callback, session, callback_data.group_id, role)
    await alert(callback, "")


@router.callback_query(CounterAdminCB.filter(F.action == "toggle"))
async def toggle(callback: CallbackQuery, callback_data: CounterAdminCB,
                 session: AsyncSession, role: str | None) -> None:
    if not _edit(role):
        await alert(callback, "⛔️ Sozlamani faqat admin o'zgartiradi.", show=True)
        return
    group = await get_group(session, callback_data.group_id)
    if group is None or group.settings is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    field = callback_data.value
    if field not in {"enabled", "require_subscription", "notify_inviter"}:
        await alert(callback, "⚠️ Noma'lum qoida.", show=True)
        return
    row = await counters.ensure_counter(session, group.id)
    current = bool(row.enabled and group.settings.counter_enabled) if field == "enabled" else bool(getattr(row, field))
    await counters.edit_counter(session, group, field, not current, callback.from_user.id)
    await render_home(callback, session, group.id, role)
    await alert(callback, "🧪 Yoqilganda sinovda. Mute'lar schedulerda ochiladi." if field == "enabled"
                else "✅ Saqlandi", show=True)


@router.callback_query(CounterAdminCB.filter(F.action.in_({"source", "mode"})))
async def select_mode(callback: CallbackQuery, callback_data: CounterAdminCB,
                      session: AsyncSession, role: str | None) -> None:
    if not _edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    group = await get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    try:
        await counters.edit_counter(session, group, callback_data.action,
                                    callback_data.value, callback.from_user.id)
    except ValueError as exc:
        await alert(callback, str(exc), show=True)
        return
    await render_home(callback, session, group.id, role)
    await alert(callback, "🧪 HARD uchun jonli rejim qayta tasdiqlanadi." if callback_data.value == "hard"
                else "✅ Saqlandi", show=True)


async def _validate_live(bot: Bot, session: AsyncSession, group: Group, row: CounterSetting) -> None:
    if not (group.is_active and group.is_supergroup and group.settings
            and group.settings.counter_enabled and row.enabled):
        raise ValueError("Avval faol superguruh va sanoqchini yoqing.")
    if not await settings_service.is_feature_enabled_fresh("counter"):
        raise ValueError("Global sanoqchi yoki tizim pauzada.")
    try:
        me = (await bot.get_me()).id
        member = await bot.get_chat_member(group.tg_chat_id, me)
        if str(member.status) not in {"administrator", "creator"}:
            raise ValueError("Bot guruhda admin emas.")
        rights = extract_rights(member)
        if not rights.get("can_delete_messages"):
            raise ValueError("Botda xabarni o'chirish huquqi yo'q.")
        if (row.count_sources or {}).get("link") and not rights.get("can_invite_users"):
            raise ValueError("Shaxsiy havola uchun invite huquqi yo'q.")
        if row.mode == CounterMode.HARD and not rights.get("can_restrict_members"):
            raise ValueError("HARD uchun a'zolarni cheklash huquqi yo'q.")
        if row.require_subscription:
            channels = await counters.applicable_channels(session, group.id)
            if not channels:
                raise ValueError("Kanal sharti yoqilgan, lekin kanal sozlanmagan.")
            for channel in channels:
                chat = await bot.get_chat(channel.channel_tg_id)
                admin = await bot.get_chat_member(channel.channel_tg_id, me)
                if chat.type != "channel" or str(admin.status) not in {"administrator", "creator"}:
                    raise ValueError(f"Kanal #{channel.id}: bot admin emas yoki bu kanal emas.")
        group.bot_is_admin, group.bot_rights = True, rights
    except TelegramAPIError as exc:
        raise ValueError(f"Telegram huquqlari tasdiqlanmadi: {exc}") from exc


@router.callback_query(CounterAdminCB.filter(F.action == "live"))
async def live(callback: CallbackQuery, callback_data: CounterAdminCB, session: AsyncSession,
               role: str | None) -> None:
    if not _edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    group = await get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    row = await counters.ensure_counter(session, group.id)
    if row.dry_run:
        await render(callback, f"🔴 <b>JONLI SANOQCHINI TASDIQLASH</b>\n\n"
                     f"Guruh: {escape_html(group.display)}\n"
                     f"Rejim: <b>{escape_html(row.mode)}</b> · N: {row.required_n}\n"
                     "SOFT: a'zoning xabari o'chadi; HARD: bunga qo'shimcha a'zo mute qilinadi. "
                     "Kanal bo'lsa bot u yerda ham admin bo'lishi kerak.\n\n"
                     "Bosilganda guruh va kanal huquqlari Telegram'da qayta tekshiriladi.",
                     confirm_kb("live_confirm", group.id, _revision(row)))
    else:
        await counters.edit_counter(session, group, "dry_run", True, callback.from_user.id)
        await render_home(callback, session, group.id, role)
    await alert(callback, "")


@router.callback_query(CounterAdminCB.filter(F.action == "live_confirm"))
async def confirm_live(callback: CallbackQuery, callback_data: CounterAdminCB,
                       session: AsyncSession, role: str | None, bot: Bot) -> None:
    if not _edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    group = await get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    row = await counters.ensure_counter(session, group.id)
    if not row.dry_run or callback_data.value != _revision(row):
        await alert(callback, "⚠️ Sozlama o'zgargan. Jonli tasdiq ekranini qayta oching.", show=True)
        return
    try:
        await _validate_live(bot, session, group, row)
    except ValueError as exc:
        await alert(callback, str(exc)[:190], show=True)
        return
    await counters.edit_counter(session, group, "dry_run", False, callback.from_user.id)
    await render_home(callback, session, group.id, role)
    await alert(callback, "🔴 Jonli rejim tasdiqlandi!", show=True)


@router.callback_query(CounterAdminCB.filter(F.action == "number"))
async def ask_number(callback: CallbackQuery, callback_data: CounterAdminCB, state: FSMContext,
                     session: AsyncSession, role: str | None) -> None:
    if not _edit(role) or callback_data.value not in _LABELS:
        await alert(callback, "⛔️ Ruxsat yoki maydon noto'g'ri.", show=True)
        return
    group = await get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    await state.set_state(AdminCounterStates.waiting_number)
    await state.update_data(counter_group_id=group.id, counter_field=callback_data.value)
    low, high = counters.NUMBERS[callback_data.value]
    await render(callback, f"✍️ {escape_html(group.display)} · <b>{_LABELS[callback_data.value]}</b>\n"
                 f"{low}–{high} oralig'ida raqam yuboring. /cancel — bekor qilish.")
    await alert(callback, "")


@router.message(StateFilter(AdminCounterStates.waiting_number), F.text)
async def save_number(message: Message, state: FSMContext, session: AsyncSession,
                      role: str | None) -> None:
    data = await state.get_data()
    if message.text.strip() == "/cancel":
        await state.clear()
        await render_home(message, session, int(data.get("counter_group_id") or 0), role)
        return
    if not _edit(role):
        await state.clear()
        return
    field = data.get("counter_field")
    group = await get_group(session, int(data.get("counter_group_id") or 0))
    if group is None or field not in _LABELS:
        await state.clear()
        await message.answer("⚠️ Guruh yoki maydon topilmadi.")
        return
    try:
        await counters.edit_counter(session, group, field, message.text, message.from_user.id)
    except ValueError as exc:
        await message.answer(f"⚠️ {escape_html(str(exc))} /cancel — bekor qilish.")
        return
    await state.clear()
    await render_home(message, session, group.id, role)


async def _validated_channel(bot: Bot, raw: str) -> tuple[int, str | None, str, str]:
    parts = raw.strip().split()
    if not 1 <= len(parts) <= 2:
        raise ValueError("@username yoki -100... [https://t.me/+...] ko'rinishida yuboring.")
    lookup = parts[0]
    if not (lookup.startswith("@") and len(lookup) >= 6 or lookup.startswith("-100") and lookup[1:].isdigit()):
        raise ValueError("Kanalni @username yoki -100... ID orqali ko'rsating.")
    if len(parts) == 2 and not (parts[1].startswith("https://t.me/+") and len(parts[1]) <= 255):
        raise ValueError("Xususiy kanal linki https://t.me/+... bo'lishi kerak.")
    try:
        chat = await bot.get_chat(int(lookup) if lookup.startswith("-100") else lookup)
        if chat.type != "channel" or chat.id >= 0:
            raise ValueError("Bu kanal emas.")
        member = await bot.get_chat_member(chat.id, (await bot.get_me()).id)
        if str(member.status) not in {"administrator", "creator"}:
            raise ValueError("Bot kanalga admin qilib qo'shilishi kerak.")
    except TelegramAPIError as exc:
        raise ValueError(f"Kanal yoki bot adminligini tekshirib bo'lmadi: {exc}") from exc
    username = getattr(chat, "username", None)
    link = (f"https://t.me/{username}" if username else getattr(chat, "invite_link", None)
            or (parts[1] if len(parts) == 2 else None))
    if not link or not link.startswith("https://t.me/"):
        raise ValueError("Xususiy kanal havolasi topilmadi; ID bilan https://t.me/+... yuboring.")
    return chat.id, username, chat.title or username or str(chat.id), link


@router.callback_query(CounterAdminCB.filter(F.action == "channel_add"))
async def ask_channel(callback: CallbackQuery, callback_data: CounterAdminCB, state: FSMContext,
                      session: AsyncSession, role: str | None) -> None:
    if not _edit(role) or callback_data.group_id and not await get_group(session, callback_data.group_id):
        await alert(callback, "⛔️ Ruxsat yoki guruh topilmadi.", show=True)
        return
    await state.set_state(AdminCounterStates.waiting_channel)
    await state.update_data(counter_group_id=callback_data.group_id)
    await render(callback, "📣 Bot kanalda <b>admin</b> bo'lsin. Kanalning "
                 "<code>@username</code> yoki <code>-100...</code> ID sini yuboring.\n"
                 "Xususiy kanal uchun: <code>-100... https://t.me/+link</code> "
                 "(linkning IDga mosligini Telegram tekshira olmaydi; admin mas'ul).\n"
                 "/cancel — bekor qilish.")
    await alert(callback, "")


@router.message(StateFilter(AdminCounterStates.waiting_channel), F.text)
async def save_channel(message: Message, state: FSMContext, bot: Bot,
                       session: AsyncSession, role: str | None) -> None:
    data = await state.get_data()
    gid = int(data.get("counter_group_id") or 0)
    if message.text.strip() == "/cancel":
        await state.clear()
        await render_channels(message, session, gid, role)
        return
    if not _edit(role) or gid and not await get_group(session, gid):
        await state.clear()
        return
    try:
        cid, username, title, link = await _validated_channel(bot, message.text)
        await counters.add_channel(session, group_id=gid or None, channel_id=cid,
                                   username=username, title=title, invite_link=link,
                                   actor_id=message.from_user.id)
    except ValueError as exc:
        await message.answer(f"⚠️ {escape_html(str(exc))}\n/cancel — bekor qilish.")
        return
    await state.clear()
    await render_channels(message, session, gid, role)


@router.callback_query(CounterAdminCB.filter(F.action == "channel_ask"))
async def ask_remove_channel(callback: CallbackQuery, callback_data: CounterAdminCB,
                             session: AsyncSession, role: str | None) -> None:
    if not _edit(role) or not callback_data.value.isdigit():
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    row = await session.get(RequiredChannel, int(callback_data.value))
    if row is None or not row.is_active or (row.group_id or 0) != callback_data.group_id:
        await alert(callback, "⚠️ Bu qamrovda kanal yo'q.", show=True)
        return
    await render(callback, f"❌ <b>Kanalni talabdan olib tashlash?</b>\n"
                 f"{escape_html(row.title or str(row.channel_tg_id))} · "
                 f"{'global' if row.group_id is None else 'shu guruh'}\n"
                 "Telegram kanalining o'zi o'chirilmaydi.",
                 confirm_kb("channel_remove", callback_data.group_id, callback_data.value))
    await alert(callback, "")


@router.callback_query(CounterAdminCB.filter(F.action == "channel_remove"))
async def remove_channel(callback: CallbackQuery, callback_data: CounterAdminCB,
                         session: AsyncSession, role: str | None) -> None:
    if not _edit(role) or not callback_data.value.isdigit():
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    row = await session.get(RequiredChannel, int(callback_data.value))
    if row is None or (row.group_id or 0) != callback_data.group_id:
        await alert(callback, "⚠️ Bu qamrovda kanal yo'q.", show=True)
        return
    await counters.remove_channel(session, row, callback.from_user.id)
    await render_channels(callback, session, callback_data.group_id, role)
    await alert(callback, "✅ Talabdan olib tashlandi.")


@router.callback_query(CounterAdminCB.filter(F.action == "user"))
async def ask_user(callback: CallbackQuery, callback_data: CounterAdminCB, state: FSMContext,
                   session: AsyncSession) -> None:
    group = await get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    await state.set_state(AdminCounterStates.waiting_user)
    await state.update_data(counter_group_id=group.id)
    await render(callback, "👤 Hisobini ko'rish uchun Telegram foydalanuvchi ID sini "
                 "(musbat raqam) yuboring. /cancel — bekor qilish.")
    await alert(callback, "")


@router.message(StateFilter(AdminCounterStates.waiting_user), F.text)
async def save_user(message: Message, state: FSMContext, session: AsyncSession,
                    role: str | None) -> None:
    data = await state.get_data()
    gid = int(data.get("counter_group_id") or 0)
    if message.text.strip() == "/cancel":
        await state.clear()
        await render_home(message, session, gid, role)
        return
    raw = message.text.strip()
    if not raw.isascii() or not raw.isdigit() or len(raw) > 19 or not 0 < int(raw) < 2**63:
        await message.answer("⚠️ Musbat Telegram ID yuboring. /cancel — bekor qilish.")
        return
    if await get_group(session, gid) is None:
        await state.clear()
        return
    await state.clear()
    await render_user(message, session, gid, int(raw), role)


@router.callback_query(CounterAdminCB.filter(F.action == "status"))
async def status(callback: CallbackQuery, callback_data: CounterAdminCB, session: AsyncSession,
                 role: str | None) -> None:
    if not callback_data.value.isdigit():
        await alert(callback, "⚠️ Foydalanuvchi ID noto'g'ri.", show=True)
        return
    await render_user(callback, session, callback_data.group_id, int(callback_data.value), role)
    await alert(callback, "")


@router.callback_query(CounterAdminCB.filter(F.action == "adjust"))
async def ask_adjust(callback: CallbackQuery, callback_data: CounterAdminCB, state: FSMContext,
                     session: AsyncSession, role: str | None) -> None:
    raw = callback_data.value
    if not _edit(role) or len(raw) < 2 or raw[0] not in "pm" or not raw[1:].isdigit():
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    if not await get_group(session, callback_data.group_id):
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    user_id = int(raw[1:])
    if user_id <= 0:
        return
    await state.set_state(AdminCounterStates.waiting_adjust)
    await state.update_data(counter_group_id=callback_data.group_id, counter_user_id=user_id,
                            counter_sign=1 if raw[0] == "p" else -1)
    await render(callback, f"👤 <code>{user_id}</code>: "
                 f"<b>{'qo‘shish' if raw[0] == 'p' else 'kamaytirish'}</b>\n"
                 "<code>2 sababi</code> ko'rinishida miqdor (1–1000) va "
                 "3–255 belgili sabab yuboring. /cancel — bekor qilish.")
    await alert(callback, "")


@router.message(StateFilter(AdminCounterStates.waiting_adjust), F.text)
async def save_adjust(message: Message, state: FSMContext, session: AsyncSession,
                      role: str | None, bot: Bot) -> None:
    data = await state.get_data()
    gid, uid = int(data.get("counter_group_id") or 0), int(data.get("counter_user_id") or 0)
    if message.text.strip() == "/cancel":
        await state.clear()
        await render_user(message, session, gid, uid, role)
        return
    if not _edit(role):
        await state.clear()
        return
    pieces = message.text.strip().split(maxsplit=1)
    if len(pieces) != 2 or not pieces[0].isascii() or not pieces[0].isdigit():
        await message.answer("⚠️ Masalan: <code>2 hisob xatosi</code>. /cancel — bekor qilish.")
        return
    try:
        count = await counters.adjust(session, group_id=gid, user_id=uid,
                                      delta=int(data.get("counter_sign") or 1) * int(pieces[0]),
                                      reason=pieces[1], actor_id=message.from_user.id)
    except ValueError as exc:
        await message.answer(f"⚠️ {escape_html(str(exc))} /cancel — bekor qilish.")
        return
    await session.commit()  # mute ochish Telegram API'sidan oldin audit saqlansin
    if count:
        await _unlock(bot, gid, uid)
    await state.clear()
    await render_user(message, session, gid, uid, role)


@router.callback_query(CounterAdminCB.filter(F.action == "zero_ask"))
async def ask_zero(callback: CallbackQuery, callback_data: CounterAdminCB,
                   session: AsyncSession, role: str | None) -> None:
    if not _edit(role) or not callback_data.value.isdigit():
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    uid = int(callback_data.value)
    group = await get_group(session, callback_data.group_id)
    if group is None or uid <= 0:
        await alert(callback, "⚠️ Guruh/ID topilmadi.", show=True)
        return
    count = await counters.total_for(session, group.id, uid)
    await render(callback, f"0️⃣ <b>{escape_html(group.display)}: {uid}</b>\n"
                 f"{count} ta hisobni nolga tushirishni tasdiqlaysizmi? "
                 "Auditda admin va sabab saqlanadi.",
                 confirm_kb("zero_confirm", group.id, str(uid)))
    await alert(callback, "")


@router.callback_query(CounterAdminCB.filter(F.action == "zero_confirm"))
async def confirm_zero(callback: CallbackQuery, callback_data: CounterAdminCB,
                       session: AsyncSession, role: str | None) -> None:
    if not _edit(role) or not callback_data.value.isdigit():
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    uid = int(callback_data.value)
    count = await counters.total_for(session, callback_data.group_id, uid)
    if count:
        await counters.reset_count(session, group_id=callback_data.group_id, user_id=uid,
                                   actor_id=callback.from_user.id)
    await render_user(callback, session, callback_data.group_id, uid, role)
    await alert(callback, "✅ Nolga tushirildi" if count else "Hisob allaqachon nol")


@router.callback_query(CounterAdminCB.filter(F.action == "link_cancel_ask"))
async def ask_link_cancel(callback: CallbackQuery, callback_data: CounterAdminCB,
                          session: AsyncSession, role: str | None) -> None:
    if not _edit(role) or not callback_data.value.isdigit():
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    row = await session.get(InviteLink, int(callback_data.value))
    if row is None or not row.is_active or row.group_id != callback_data.group_id:
        await alert(callback, "⚠️ Faol havola topilmadi.", show=True)
        return
    pending = row.invite_link.startswith("pending:")
    await render(callback, f"🔗 <b>Havolani bekor qilish?</b>\n"
                 f"Guruh #{row.group_id}, foydalanuvchi <code>{row.user_id}</code>.\n"
                 + ("⚠️ API holati noma'lum: Telegram'da yaratilgan bo'lishi mumkin. "
                    "Havolalar ro'yxatini qo'lda tekshiring." if pending
                    else "Telegram'dagi havola ham revoke qilinadi."),
                 confirm_kb("link_cancel", row.group_id, str(row.id)))
    await alert(callback, "")


@router.callback_query(CounterAdminCB.filter(F.action == "link_cancel"))
async def cancel_link(callback: CallbackQuery, callback_data: CounterAdminCB,
                      session: AsyncSession, role: str | None, bot: Bot) -> None:
    if not _edit(role) or not callback_data.value.isdigit():
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    row = await session.get(InviteLink, int(callback_data.value))
    if row is None or not row.is_active or row.group_id != callback_data.group_id:
        await alert(callback, "⚠️ Faol havola topilmadi.", show=True)
        return
    uid = row.user_id
    if not row.invite_link.startswith("pending:"):
        group = await get_group(session, row.group_id)
        if group is None:
            return
        try:
            await bot.revoke_chat_invite_link(group.tg_chat_id, row.invite_link)
        except TelegramAPIError as exc:
            await alert(callback, f"Telegram bekor qilgani noma'lum: {exc}"[:180], show=True)
            return  # API noaniq: DB'da bekor qilmaymiz
    await counters.cancel_personal_link(session, row, callback.from_user.id)
    await render_user(callback, session, row.group_id, uid, role)
    await alert(callback, "✅ Havola bekor qilindi.")


@router.callback_query(CounterAdminCB.filter(F.action == "log"))
async def log(callback: CallbackQuery, callback_data: CounterAdminCB,
              session: AsyncSession) -> None:
    gid = callback_data.group_id
    group = await get_group(session, gid)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    checks = (await session.execute(select(CounterMessageCheck).where(
        CounterMessageCheck.group_id == gid,
    ).order_by(CounterMessageCheck.id.desc()).limit(8))).scalars().all()
    changes = (await session.execute(select(ActionLog).where(
        ActionLog.group_id == gid,
        ActionLog.action.in_({"counter_setting", "counter_switch", "counter_adjust",
                              "channel_add", "channel_remove", "invite_cancel"}),
    ).order_by(ActionLog.id.desc()).limit(8))).scalars().all()
    total = (await session.execute(select(CounterTotal).where(
        CounterTotal.group_id == gid,
    ).order_by(CounterTotal.counted.desc()).limit(5))).scalars().all()
    text = f"📋 <b>{escape_html(group.display)} — sanoqchi tarixi</b>\n"
    text += "Eng faol: " + (", ".join(f"{row.user_id}: {row.counted}" for row in total) or "—")
    text += "\n\n<b>Xabar tekshiruvlari:</b>\n" + ("\n".join(
        f"• #{row.message_id} · {row.user_id} · {escape_html(row.issue)} · {escape_html(row.status)}"
        for row in checks
    ) or "—")
    text += "\n\n<b>O'zgarishlar:</b>\n" + ("\n".join(
        f"• {fmt_dt(row.created_at)} · {escape_html(row.action)} · "
        f"admin {row.actor_id or '—'} · {escape_html(truncate(str(row.after or {}), 100))}"
        for row in changes
    ) or "—")
    await render(callback, text, InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Sanoqchi", callback_data=CounterAdminCB(
            action="home", group_id=gid,
        ).pack()),
    ]]))
    await alert(callback, "")
