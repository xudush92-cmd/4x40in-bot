"""Phase 7: a'zolik hodisalari, shaxsiy havola va xavfsiz sanoqchi cheki.

Join request hisobga olinmaydi. Faqat tasdiqlangan chat_member + min_stay
o'tganidan keyin scheduler getChatMember bilan tekshirib kredit beradi.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    ChatMemberUpdated,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.constants import CounterMode, InviteSource, PermissionKind
from app.db.base import session_scope
from app.db.models import (
    Admin,
    CleanupLog,
    CounterMessageCheck,
    CounterRestriction,
    CounterSetting,
    Group,
    GroupAdmin,
    GroupMessageAction,
    GroupSettings,
    InviteEvent,
    InviteLink,
    RequiredChannel,
    Restriction,
)
from app.filters import GroupChat, PrivateChat
from app.keyboards.callbacks import CounterCB
from app.services import counter_notice_service as notices
from app.services import counter_service as counters
from app.services import group_policy_service as policy
from app.services.group_service import get_group_by_chat_id, pause_group
from app.services.notify import notify_admins
from app.services.settings_service import settings_service
from app.utils.text import escape_html
from app.utils.time import utcnow

router = Router(name="group:counter")
# Ijobiy javoblargina keshlanadi; obuna bo'lgan odam 60s nohaq jazolanmaydi.
_membership_cache: dict[tuple[int, int], float] = {}


@dataclass(frozen=True)
class Need:
    issue: str  # counter_not_done | not_subscribed | unknown (Telegram tekshirilmayapti)
    count: int
    required: int
    channels: tuple[RequiredChannel, ...] = ()


def _member(status: object) -> bool:
    value = str(getattr(status, "status", ""))
    return value in {"member", "administrator", "creator"} or (
        value == "restricted" and bool(getattr(status, "is_member", False))
    )


async def _gate(session: AsyncSession, chat_id: int) -> tuple[Group, CounterSetting] | None:
    group = await get_group_by_chat_id(session, chat_id)
    if not (group and group.is_supergroup and group.is_active and group.bot_is_admin and group.settings
            and group.settings.counter_enabled):
        return None
    setting = await session.get(CounterSetting, group.id)
    return (group, setting) if setting and setting.enabled else None


async def _needed(bot: Bot, session: AsyncSession, group: Group, setting: CounterSetting,
                  user_id: int, *, fresh: bool = False) -> Need | None:
    """Bitta noaniq Telegram javobi jazoga SABAB bo'lmaydi (fail open)."""
    if user_id <= 0 or user_id in get_settings().admin_ids:
        return None
    kinds = await policy.permission_kinds(session, user_id, group.id)
    if PermissionKind.FULL_EXEMPT in kinds:
        return None
    admin = (await session.execute(select(Admin.id).where(
        Admin.user_id == user_id, Admin.is_active.is_(True),
    ))).scalar_one_or_none()
    local = (await session.execute(select(GroupAdmin.id).where(
        GroupAdmin.group_id == group.id, GroupAdmin.user_id == user_id,
    ))).scalar_one_or_none()
    if admin or local:
        return None
    try:
        member = await bot.get_chat_member(group.tg_chat_id, user_id)
    except TelegramAPIError as exc:
        logger.warning("Sanoqchi: guruh adminini tekshirib bo'lmadi: {}", exc)
        return Need("unknown", 0, setting.required_n)
    if str(member.status) in {"administrator", "creator"}:
        return None

    count = await counters.total_for(session, group.id, user_id)
    channels = await counters.applicable_channels(session, group.id) if setting.require_subscription else []
    if setting.require_subscription and not channels:
        return Need("unknown", count, setting.required_n)  # sozlanmagan kanal uchun jazo yo'q
    missing: list[RequiredChannel] = []
    for channel in channels:
        if not isinstance(channel.channel_tg_id, int):
            return Need("unknown", count, setting.required_n)
        if fresh:
            try:
                # Bot kanal adminligini yo'qotsa getChatMember(user) ishonchsiz:
                # oldin botning o'z a'zoligini tekshirib fail-open qilamiz.
                bot_member = await bot.get_chat_member(channel.channel_tg_id, (await bot.get_me()).id)
            except TelegramAPIError:
                return Need("unknown", count, setting.required_n)
            if str(bot_member.status) not in {"administrator", "creator"}:
                return Need("unknown", count, setting.required_n)
        key = (channel.channel_tg_id, user_id)
        if not fresh and _membership_cache.get(key, 0) > time.monotonic():
            continue
        try:
            member = await bot.get_chat_member(channel.channel_tg_id, user_id)
        except TelegramAPIError as exc:
            logger.warning("Kanal a'zoligi noaniq (kanal #{}): {}", channel.id, exc)
            return Need("unknown", count, setting.required_n)
        if not _member(member):
            missing.append(channel)
        else:
            if len(_membership_cache) >= 10_000:
                _membership_cache.clear()  # kesh cheksiz o'smasin
            _membership_cache[key] = time.monotonic() + 60
    if missing:
        return Need("not_subscribed", count, setting.required_n, tuple(missing))
    if setting.required_n > count and PermissionKind.COUNTER_EXEMPT not in kinds:
        return Need("counter_not_done", count, setting.required_n)
    return None


def _kb_missing(need: Need, group_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for channel in need.channels[:6]:
        if channel.invite_link:
            rows.append([InlineKeyboardButton(text=f"📣 {channel.title or channel.username or 'Kanal'}"[:60],
                                              url=channel.invite_link)])
    rows.append([InlineKeyboardButton(text="✅ Tekshirdim", callback_data=CounterCB(
        action="check", group_id=group_id,
    ).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _status_text(group: Group, need: Need | None, count: int, setting: CounterSetting) -> str:
    text = (f"🧮 <b>{escape_html(group.display)}</b>\n"
            f"Takliflar: <b>{count}</b> / <b>{setting.required_n}</b>\n"
            f"Qolgan: <b>{max(0, setting.required_n - count)}</b>\n")
    if setting.dry_run:
        text += "🧪 Sanoqchi sinov rejimida: xabar o'chirilmaydi va mute yo'q.\n"
    if need is None:
        return text + "✅ Shartlar bajarilgan (yoki siz uchun istisno mavjud)."
    if need.issue == "unknown":
        return text + "⚠️ Telegram/kanal holatini tekshirib bo'lmadi; hech qanday jazo yo'q."
    if need.issue == "not_subscribed":
        return text + "📣 Avval ko'rsatilgan kanal(lar)ga a'zo bo'ling, keyin «Tekshirdim»ni bosing."
    return text + "👥 Yana odam taklif qiling; a'zolar kamida belgilangan muddat qolishi kerak."


async def _user_group(bot: Bot, session: AsyncSession, group_id: int,
                      user_id: int) -> tuple[Group, CounterSetting] | None:
    group = await session.get(Group, group_id)
    setting = await session.get(CounterSetting, group_id)
    if not (group and group.is_active and group.is_supergroup and group.bot_is_admin and group.settings
            and group.settings.counter_enabled and setting and setting.enabled):
        return None
    try:
        status = await bot.get_chat_member(group.tg_chat_id, user_id)
        return (group, setting) if _member(status) else None
    except TelegramAPIError:
        return None


async def _personal_link(bot: Bot, group: Group, setting: CounterSetting,
                         user_id: int) -> str | None:
    if not await settings_service.is_feature_enabled_fresh("counter"):
        return None
    try:
        async with session_scope() as session:
            row, create, old_url = await counters.reserve_personal_link(
                session, group.id, user_id, user_id,
            )
            link_id, name = row.id, row.name
            if not create:
                return None if row.invite_link.startswith("pending:") else row.invite_link
    except ValueError as exc:
        logger.warning("Shaxsiy havola ruxsati yo'q: {}", exc)
        return None
    try:
        if not await settings_service.is_feature_enabled_fresh("counter"):
            async with session_scope() as session:
                await counters.finish_personal_link(session, link_id, None)
            return None
        response = await bot.create_chat_invite_link(
            group.tg_chat_id, name=name, member_limit=setting.link_member_limit,
        )
        url = response.invite_link
        async with session_scope() as session:
            fresh_group = await session.get(Group, group.id)
            fresh_setting = await session.get(CounterSetting, group.id)
            active = bool(fresh_group and fresh_group.is_active and fresh_group.settings
                          and fresh_group.settings.counter_enabled and fresh_setting
                          and fresh_setting.enabled)
            activated = (await counters.finish_personal_link(session, link_id, url)) if active else False
        if not activated or not await settings_service.is_feature_enabled_fresh("counter"):
            await bot.revoke_chat_invite_link(group.tg_chat_id, url)
            if activated:
                async with session_scope() as session:
                    current = await session.get(InviteLink, link_id)
                    await counters.cancel_personal_link(session, current, user_id)
            return None
        if old_url and old_url.startswith("https://t.me/"):
            try:
                await bot.revoke_chat_invite_link(group.tg_chat_id, old_url)
            except TelegramAPIError as exc:
                logger.warning("Eski invite linkni bekor qilib bo'lmadi: {}", exc)
        return url
    except TelegramAPIError as exc:
        logger.warning("Taklif havolasi yaratilishi noaniq/yaroqsiz: {}", exc)
        if isinstance(exc, (TelegramBadRequest, TelegramForbiddenError)):
            async with session_scope() as session:
                await counters.finish_personal_link(session, link_id, None)
        # Tarmoq/noaniq xatoda pending saqlanadi: bir xil odamga yana link
        # yaratilmaydi; admin uni audit bilan qo'lda bekor qilishi mumkin.
        return None


async def render_mine(target: CallbackQuery | Message, bot: Bot, session: AsyncSession,
                      group_id: int, user_id: int, *, fresh: bool = False) -> None:
    from app.utils.tg import render

    pair = await _user_group(bot, session, group_id, user_id)
    if pair is None:
        await render(target, "⚠️ Bu guruhda a'zoligingiz/sanoqchi holati tasdiqlanmadi.")
        return
    group, setting = pair
    count = await counters.total_for(session, group.id, user_id)
    need = await _needed(bot, session, group, setting, user_id, fresh=fresh)
    if fresh and need is None:
        await _unlock(bot, group.id, user_id)
    text = _status_text(group, need, count, setting)
    link = (await session.execute(select(InviteLink).where(
        InviteLink.group_id == group.id, InviteLink.user_id == user_id,
        InviteLink.is_active.is_(True),
    ))).scalar_one_or_none()
    if link and not link.invite_link.startswith("pending:") and link.join_count < setting.link_member_limit:
        text += f"\n🔗 Shaxsiy havola: <code>{escape_html(link.invite_link)}</code>"
    elif link:
        text += "\n⏳ Havola yaratilyapti yoki limiti to'ldi; yangisini so'rang."
    buttons: list[list[InlineKeyboardButton]] = []
    if need and need.issue == "not_subscribed":
        buttons.extend(_kb_missing(need, group.id).inline_keyboard)
    else:
        buttons.append([InlineKeyboardButton(text="✅ Qayta tekshirish", callback_data=CounterCB(
            action="check", group_id=group.id,
        ).pack())])
    buttons.append([InlineKeyboardButton(text="🔗 Havola olish/yangilash", callback_data=CounterCB(
        action="link", group_id=group.id,
    ).pack())])
    buttons.append([InlineKeyboardButton(text="◀️ Guruhlar", callback_data=CounterCB(action="list").pack())])
    await render(target, text, InlineKeyboardMarkup(inline_keyboard=buttons))


async def render_groups(target: CallbackQuery | Message, bot: Bot,
                        session: AsyncSession, user_id: int) -> None:
    from app.utils.tg import render

    rows = (await session.execute(select(Group.id).join(GroupSettings).join(CounterSetting).where(
        Group.is_active.is_(True), GroupSettings.counter_enabled.is_(True),
        CounterSetting.enabled.is_(True),
    ).order_by(Group.id).limit(50))).scalars().all()
    visible: list[Group] = []
    for group_id in rows:
        pair = await _user_group(bot, session, group_id, user_id)
        if pair:
            visible.append(pair[0])
    if not visible:
        await render(target, "🧮 Siz a'zo bo'lgan faol sanoqchi guruhlari topilmadi.")
        return
    buttons = [[InlineKeyboardButton(text=group.display[:55], callback_data=CounterCB(
        action="mine", group_id=group.id,
    ).pack())] for group in visible]
    await render(target, "🧮 <b>Guruhni tanlang</b>\nFaqat siz a'zo bo'lgan guruhlar ko'rsatiladi.",
                 InlineKeyboardMarkup(inline_keyboard=buttons))


@router.message(Command("takliflarim", "mening_holatim"), PrivateChat())
async def my_commands(message: Message, bot: Bot, session: AsyncSession) -> None:
    await render_groups(message, bot, session, message.from_user.id)


@router.message(Command("takliflarim", "mening_holatim"), GroupChat())
async def group_commands(message: Message) -> None:
    await message.answer("🔒 Hisobingiz va shaxsiy taklif havolangizni bot bilan shaxsiy chatda "
                         "/takliflarim orqali ko'ring.")


@router.callback_query(CounterCB.filter(F.action == "list"), PrivateChat())
async def mine_list(callback: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    await render_groups(callback, bot, session, callback.from_user.id)
    await callback.answer()


@router.callback_query(CounterCB.filter(F.action.in_({"mine", "check", "link"})), PrivateChat())
async def mine_callback(callback: CallbackQuery, callback_data: CounterCB, bot: Bot,
                        session: AsyncSession) -> None:
    group_id = callback_data.group_id
    if await _user_group(bot, session, group_id, callback.from_user.id) is None:
        await callback.answer("⚠️ Guruh a'zoligi tekshirilmadi.", show_alert=True)
        return
    if callback_data.action == "link":
        pair = await _user_group(bot, session, group_id, callback.from_user.id)
        url = await _personal_link(bot, *pair, callback.from_user.id)
        if url is None:
            await callback.answer("⚠️ Havola yaratilmayapti (huquq/pauza/noaniq).", show_alert=True)
            return
    await render_mine(callback, bot, session, group_id, callback.from_user.id,
                      fresh=callback_data.action == "check")
    await callback.answer()


@router.chat_join_request()
async def on_join_request(event: ChatJoinRequest, session: AsyncSession) -> None:
    if event.chat.type != "supergroup" or event.invite_link is None:
        return
    pair = await _gate(session, event.chat.id)
    if pair:
        await counters.record_request(session, group_id=pair[0].id, user_id=event.from_user.id,
                                      invite_link=event.invite_link.invite_link)


async def _joined(bot: Bot, session: AsyncSession, group: Group, user_id: int,
                  actor_id: int, invite_link: str | None, *, is_bot: bool = False,
                  message_id: int | None = None) -> None:
    setting = await session.get(CounterSetting, group.id)
    if not setting or not await settings_service.is_feature_enabled_fresh("counter"):
        return
    source = InviteSource.LINK if invite_link else InviteSource.ADDED_BY
    link = None
    if invite_link:
        link = (await session.execute(select(InviteLink).where(
            InviteLink.group_id == group.id, InviteLink.invite_link == invite_link,
        ))).scalar_one_or_none()
    inviter_id = link.user_id if link else actor_id if source == InviteSource.ADDED_BY else None
    if inviter_id is not None and inviter_id == (await bot.get_me()).id:
        inviter_id = None
    entry = await counters.reserve_join(
        session, group_id=group.id, inviter_id=inviter_id, invitee_id=user_id,
        source=source, invite_link=invite_link, message_id=message_id, is_bot=is_bot,
    )
    if entry is not None:
        await session.commit()  # oldin UNIQUE + min_stay navbati
    if (setting.mode == CounterMode.HARD and not setting.dry_run and not is_bot
            and (group.bot_rights or {}).get("can_restrict_members")):
        # Foydalanuvchi eski a'zo bo'lsa ham uning shartini tekshir; yangi
        # qo'shiluvchini darhol xato tekshiruvda jazolamaymiz (fail open).
        need = await _needed(bot, session, group, setting, user_id, fresh=True)
        if need and need.issue in {"not_subscribed", "counter_not_done"}:
            if await _restrict(bot, group.id, user_id, need.issue):
                await notices.send_notice(bot, group_id=group.id, user_id=user_id,
                                          issue=need.issue)


@router.chat_member()
async def member_event(event: ChatMemberUpdated, bot: Bot, session: AsyncSession) -> None:
    if event.chat.type != "supergroup":
        return
    old, new = event.old_chat_member, event.new_chat_member
    was = _member(old)
    now = _member(new)
    pair = await _gate(session, event.chat.id)
    if pair is None:
        return
    group, _ = pair
    user_id = new.user.id
    if was and not now:
        await counters.abandon_early(session, group_id=group.id, invitee_id=user_id)
        return
    if was or not now or new.user.is_bot:
        return
    link = event.invite_link.invite_link if event.invite_link else None
    link = link or await counters.request_link(session, group.id, user_id)
    await _joined(bot, session, group, user_id, event.from_user.id, link,
                  is_bot=new.user.is_bot)


async def service_join(message: Message, bot: Bot, session: AsyncSession) -> None:
    """Policy xabar marshrutidan chaqiriladi: Phase 6 join-cleaner'ni yutmasin."""
    pair = await _gate(session, message.chat.id)
    if pair is None or message.from_user is None:
        return
    for new_user in message.new_chat_members or []:
        if new_user.is_bot:
            continue
        await _joined(bot, session, pair[0], new_user.id, message.from_user.id,
                      None, message_id=message.message_id)


async def _restrict(bot: Bot, group_id: int, user_id: int, issue: str) -> bool:
    if not await settings_service.is_feature_enabled_fresh("counter"):
        return False
    async with session_scope() as session:
        group = await session.get(Group, group_id)
        setting = await session.get(CounterSetting, group_id)
        if not (group and group.is_active and group.bot_is_admin and group.settings
                and group.settings.counter_enabled and (group.bot_rights or {}).get("can_restrict_members")
                and setting and setting.enabled and not setting.dry_run and setting.mode == CounterMode.HARD):
            return False
        blockers = (await session.execute(select(Restriction.id).where(
            Restriction.group_id == group_id, Restriction.user_id == user_id,
            Restriction.is_active.is_(True),
            or_(Restriction.reason.is_(None), Restriction.reason != "counter_gate"),
            or_(Restriction.until_at.is_(None), Restriction.until_at > utcnow()),
        ))).first()
        if blockers:
            return False  # posbon/admin mute'ini cheksiz counter mute bilan almashtirmaymiz
        row = await session.get(CounterRestriction, (group_id, user_id))
        if row and row.status in {"running", "active", "uncertain"}:
            return False
        if row is None:
            row = CounterRestriction(group_id=group_id, user_id=user_id,
                                     issue=issue, status="running")
            session.add(row)
        else:
            row.status, row.issue, row.error = "running", issue, None
        await session.flush()
        chat_id = group.tg_chat_id
    # Tarmoq kutishidan so'ng faol qoidani yana tekshir (to'xtasa jazo yo'q).
    async with session_scope() as session:
        group = await session.get(Group, group_id)
        setting = await session.get(CounterSetting, group_id)
        if not (group and group.is_active and group.bot_is_admin and group.settings
                and group.settings.counter_enabled and (group.bot_rights or {}).get("can_restrict_members")
                and setting and setting.enabled and not setting.dry_run
                and setting.mode == CounterMode.HARD
                and await settings_service.is_feature_enabled_fresh("counter")):
            row = await session.get(CounterRestriction, (group_id, user_id))
            row.status = "released"
            return False
        need = await _needed(bot, session, group, setting, user_id, fresh=True)
        if need is None or need.issue != issue:
            row = await session.get(CounterRestriction, (group_id, user_id))
            row.status = "released"
            return False
    try:
        await bot.restrict_chat_member(chat_id, user_id,
                                       permissions=ChatPermissions(can_send_messages=False))
    except TelegramAPIError as exc:
        async with session_scope() as session:
            row = await session.get(CounterRestriction, (group_id, user_id))
            # API rad javobi aniq: mute yo'q. Faqat tarmoq noaniq xatosida
            # scheduler ehtimoliy mute'ni ehtiyotkorlik bilan ochadi.
            row.status = ("released" if isinstance(exc, (TelegramBadRequest, TelegramForbiddenError))
                          else "uncertain")
            row.error = str(exc)[:255]
        logger.warning("Counter mute #{}:{} noaniq: {}", group_id, user_id, exc)
        return False
    async with session_scope() as session:
        row = await session.get(CounterRestriction, (group_id, user_id))
        # API paytida boshqa ish release qilgan bo'lsa ham mute endi qo'yildi:
        # 'uncertain' holati schedulerga ochish uchun navbat qoldiradi.
        row.status = "active" if row.status == "running" else "uncertain"
        session.add(Restriction(group_id=group_id, user_id=user_id, kind="mute",
                                reason="counter_gate", is_active=True))
    return True


async def _unlock(bot: Bot, group_id: int, user_id: int) -> bool:
    async with session_scope() as session:
        row = await session.get(CounterRestriction, (group_id, user_id))
        if row is None or row.status not in {"active", "uncertain"}:
            return False
        group = await session.get(Group, group_id)
        if not group or not group.bot_is_admin or not (group.bot_rights or {}).get("can_restrict_members"):
            return False
        setting = await session.get(CounterSetting, group_id)
        live = bool(group.is_active and group.settings and group.settings.counter_enabled and setting
                    and setting.enabled and not setting.dry_run and setting.mode == CounterMode.HARD
                    and await settings_service.is_feature_enabled_fresh("counter"))
        if live:
            need = await _needed(bot, session, group, setting, user_id, fresh=True)
            if need is not None:
                return False  # API noaniqligi yoki shart bajarilmagan: mute saqlansin
        blockers = (await session.execute(select(Restriction.id).where(
            Restriction.group_id == group_id, Restriction.user_id == user_id,
            Restriction.is_active.is_(True),
            or_(Restriction.reason.is_(None), Restriction.reason != "counter_gate"),
            or_(Restriction.until_at.is_(None), Restriction.until_at > utcnow()),
        ))).first()
        if blockers:
            return False  # qo'lda/posbon bergan mute yoki ban'ni ochib yubormaymiz
        chat_id = group.tg_chat_id
    try:
        chat = await bot.get_chat(chat_id)
        defaults = getattr(chat, "permissions", None) or ChatPermissions(
            can_send_messages=True, can_send_audios=True, can_send_documents=True,
            can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
            can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
            can_add_web_page_previews=True,
        )
        await bot.restrict_chat_member(chat_id, user_id, permissions=defaults)
    except TelegramAPIError as exc:
        logger.warning("Counter mute'ni ochib bo'lmadi #{}:{}: {}", group_id, user_id, exc)
        return False
    async with session_scope() as session:
        row = await session.get(CounterRestriction, (group_id, user_id))
        if row is not None:
            row.status, row.error = "released", None
        restrictions = (await session.execute(select(Restriction).where(
            Restriction.group_id == group_id, Restriction.user_id == user_id,
            Restriction.reason == "counter_gate", Restriction.is_active.is_(True),
        ))).scalars().all()
        for item in restrictions:
            item.is_active, item.lifted_at = False, utcnow()
    return True


async def check_message(message: Message, session: AsyncSession, bot: Bot) -> bool:
    """True = xabar sanoqchida egallandi, boshqa delete/guard ishlamasin."""
    if (message.chat.type != "supergroup" or message.sender_chat is not None
            or message.from_user is None or message.from_user.is_bot
            or message.new_chat_members or message.left_chat_member):
        return False
    if not await settings_service.is_feature_enabled_fresh("counter"):
        return False
    pair = await _gate(session, message.chat.id)
    if pair is None:
        return False
    group, setting = pair
    need = await _needed(bot, session, group, setting, message.from_user.id)
    if need is None or need.issue == "unknown":
        return False
    try:
        async with session.begin_nested():
            check = CounterMessageCheck(group_id=group.id, message_id=message.message_id,
                                        user_id=message.from_user.id, issue=need.issue,
                                        status="dry_run" if setting.dry_run else "running")
            session.add(check)
            await session.flush()
    except IntegrityError:
        prior = (await session.execute(select(CounterMessageCheck.status).where(
            CounterMessageCheck.group_id == group.id,
            CounterMessageCheck.message_id == message.message_id,
        ))).scalar_one_or_none()
        return prior != "dry_run"  # sinov guard'dan xabarni yashirmaydi
    if setting.dry_run:
        await session.commit()
        return False
    action = await policy.reserve_action(session, group_id=group.id,
                                         message_id=message.message_id, user_id=message.from_user.id,
                                         match=policy.Match("counter", need.issue), dry_run=False)
    if action is None:
        check.status, check.error = "skipped", "Xabarni boshqa filtr band qilgan."
        await session.commit()
        return True
    action_id, check_id, group_id = action.id, check.id, group.id
    await session.commit()  # API oldidan idempotent rezervatsiyalar
    async with session_scope() as fresh_session:
        fresh_group = await fresh_session.get(Group, group_id)
        fresh_setting = await fresh_session.get(CounterSetting, group_id)
        fresh_need = (await _needed(bot, fresh_session, fresh_group, fresh_setting,
                                    message.from_user.id, fresh=True)
                      if fresh_group and fresh_setting else None)
        live = bool(fresh_group and fresh_group.is_active and fresh_group.bot_is_admin
                    and fresh_group.settings and fresh_group.settings.counter_enabled
                    and fresh_setting and fresh_setting.enabled and not fresh_setting.dry_run
                    and (fresh_group.bot_rights or {}).get("can_delete_messages")
                    and fresh_need and fresh_need.issue == need.issue
                    and await settings_service.is_feature_enabled_fresh("counter"))
        if not live:
            check = await fresh_session.get(CounterMessageCheck, check_id)
            action = await fresh_session.get(GroupMessageAction, action_id)
            check.status, action.status = "skipped", "skipped"
            check.error = action.error = "Siyosat/huquq/ruxsat o'zgardi yoki tekshirish noaniq."
            return True
    try:
        await bot.delete_message(group.tg_chat_id, message.message_id)
    except TelegramAPIError as exc:
        async with session_scope() as final_session:
            check = await final_session.get(CounterMessageCheck, check_id)
            action = await final_session.get(GroupMessageAction, action_id)
            check.status, action.status = "failed", "failed"
            check.error = action.error = str(exc)[:255]
            if isinstance(exc, TelegramForbiddenError):
                target = await final_session.get(Group, group_id)
                if target is not None and target.is_active:
                    await pause_group(final_session, target, reason="no_rights")
        if isinstance(exc, TelegramForbiddenError):
            try:
                await notify_admins(bot, f"⚠️ Sanoqchi: guruh #{group_id} pauzada; "
                                    "xabarni o'chirish huquqi yo'q.")
            except Exception as alert_exc:
                logger.warning("Sanoqchi xatosi adminlarga yuborilmadi: {}", alert_exc)
        return True
    async with session_scope() as final_session:
        check = await final_session.get(CounterMessageCheck, check_id)
        action = await final_session.get(GroupMessageAction, action_id)
        check.status, action.status = "deleted", "done"
        final_session.add(CleanupLog(group_id=group_id, kind="violation", deleted_count=1,
                                     details={"message_id": message.message_id,
                                              "counter_issue": need.issue}))
    if setting.mode == CounterMode.HARD:
        await _restrict(bot, group_id, message.from_user.id, need.issue)
    # DM botga /start bosilmagan bo'lsa yetmasligi mumkin; sabab guruhning
    # o'zida ham ko'rinsin. Navbat uni 15 sekunddan keyin o'chiradi.
    await notices.send_notice(bot, group_id=group_id, user_id=message.from_user.id,
                              issue=need.issue, deleted=True)
    try:
        bot_name = (await bot.get_me()).username or ""
        destination = f"https://t.me/{bot_name}" if bot_name else "botdagi /takliflarim"
        await bot.send_message(message.from_user.id,
                               f"🧮 {escape_html(group.display)}: xabaringiz shart sabab o'chirildi "
                               f"({escape_html(need.issue)}). {need.count}/{need.required}. "
                               f"Holat va kanalni ko'rish: {destination}")
    except TelegramAPIError:
        pass  # /start bosmagan a'zoga DM jo'natib bo'lmaydi
    return True


async def process_due(bot: Bot) -> int:
    if not await settings_service.is_feature_enabled_fresh("counter"):
        return 0
    ids = await counters.claim_due()
    for entry_id in ids:
        try:
            async with session_scope() as session:
                event = await session.get(InviteEvent, entry_id)
                group = await session.get(Group, event.group_id) if event else None
                if event is None or group is None or not group.is_active or not group.settings:
                    if event:
                        await counters.retry_check(session, event)
                    continue
                chat_id, invitee_id, inviter_id, gid = (
                    group.tg_chat_id, event.invitee_id, event.inviter_id, event.group_id,
                )
            if not await settings_service.is_feature_enabled_fresh("counter"):
                async with session_scope() as session:
                    entry = await session.get(InviteEvent, entry_id)
                    if entry:
                        await counters.retry_check(session, entry)
                break
            member = await bot.get_chat_member(chat_id, invitee_id)
            async with session_scope() as session:
                count = await counters.credit_join(session, entry_id, still_member=_member(member))
                setting = await session.get(CounterSetting, gid)
            if count and setting and setting.notify_inviter:
                try:
                    await bot.send_message(inviter_id, f"🧮 Taklifingiz hisoblandi: "
                                           f"{count}/{setting.required_n}. /takliflarim")
                except TelegramAPIError:
                    pass
            if count:
                await _unlock(bot, gid, inviter_id)
        except TelegramAPIError as exc:
            logger.warning("Taklif a'zoligini tekshirib bo'lmadi #{}: {}", entry_id, exc)
            async with session_scope() as session:
                entry = await session.get(InviteEvent, entry_id)
                if entry:
                    await counters.retry_check(session, entry)
        except Exception as exc:
            logger.exception("Sanoqchi job #{}: {}", entry_id, exc)
            async with session_scope() as session:
                entry = await session.get(InviteEvent, entry_id)
                if entry:
                    await counters.retry_check(session, entry)
    return len(ids)


async def process_restrictions(bot: Bot, *, limit: int = 100) -> int:
    """Hard mute'ni pauza/o'chirish/kvota o'tishi bilan yechishga urinish.

    Oldin tekshirilgan bloklangan foydalanuvchi navbatni egallab qolmasin:
    har ko'rilgan yozuv `updated_at` bo'yicha oxiriga suriladi.
    """
    from datetime import timedelta

    async with session_scope() as session:
        rows = (await session.execute(select(CounterRestriction).where(
            or_(CounterRestriction.status.in_({"active", "uncertain"}),
                (CounterRestriction.status == "running")
                & (CounterRestriction.updated_at < utcnow() - timedelta(minutes=5))),
        ).order_by(CounterRestriction.updated_at, CounterRestriction.group_id,
                   CounterRestriction.user_id).limit(limit))).scalars().all()
        candidates = [(row.group_id, row.user_id) for row in rows]
        for row in rows:
            if row.status == "running":
                row.status = "uncertain"  # worker API'dan keyin yiqilgan bo'lishi mumkin
            row.updated_at = utcnow()
    for group_id, user_id in candidates:
        try:
            await _unlock(bot, group_id, user_id)
        except Exception as exc:
            logger.exception("Sanoqchi mute tekshiruvi #{}:{}: {}", group_id, user_id, exc)
    return len(candidates)


__all__ = ["router", "check_message", "process_due", "process_restrictions", "render_mine", "_unlock"]
