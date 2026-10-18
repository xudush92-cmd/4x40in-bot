"""Phase 6: har bir guruhning posbon/tozalovchi qoidalari va amallar jurnali."""

from __future__ import annotations

from math import ceil

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole, Penalty
from app.db.models import ActionLog, CleanupLog, GroupMessageAction, Violation
from app.filters import IsAdmin
from app.keyboards.callbacks import PolicyCB
from app.keyboards.policy import (
    choose_groups,
    cleaner_kb,
    confirm_kb,
    guard_kb,
    history_kb,
    penalty_kb,
    pending_kb,
)
from app.services import group_policy_service as policies
from app.services import group_service
from app.services.settings_service import settings_service
from app.states import AdminPolicyStates
from app.utils.text import escape_html, truncate
from app.utils.tg import alert, render
from app.utils.time import fmt_dt

router = Router(name="admin:policy")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

_EDITABLE = {AdminRole.ADMIN, AdminRole.SUPER}
_PROMPTS = {
    "allowed_domains": f"Ko'pi bilan {policies.MAX_POLICY_LIST_ITEMS} domen, masalan: <code>t.me, example.uz</code> (bo'shatish: <code>-</code>).",
    "banned_words": f"Ko'pi bilan {policies.MAX_POLICY_LIST_ITEMS} so'z/ibora, vergul yoki yangi qatordan ajrating (bo'shatish: <code>-</code>).",
    "warn_limit": f"1–{policies.MAX_WARN_LIMIT} oralig'ida chegara kiriting. Bosqich: limitgacha DM, undan keyin mute.",
    "mute_minutes": f"1–{policies.MAX_MUTE_MINUTES} daqiqa kiriting (maksimal 70 kun).",
    "warn_window_hours": f"1–{policies.MAX_WARN_WINDOW_HOURS} soat kiriting: shu muddatdan eski warninglar noldan boshlanadi.",
    "keep_last_ads": f"Har bir e'londan 1–{policies.MAX_KEEP_LAST_ADS} ta oxirgi nusxa saqlansin (0 ta ruxsat etilmaydi).",
    "delete_after_seconds": f"0–{policies.MAX_DELETE_AFTER_SECONDS} sekund: 0 darhol, >0 xabar shu vaqtdan keyin o'chadi.",
}


def _can_edit(role: str | None) -> bool:
    return role in _EDITABLE


async def render_choose(
    target: CallbackQuery | Message, session: AsyncSession, source: str, page: int = 0,
) -> None:
    if source not in {"guard", "cleaner", "permissions"}:
        return
    total = await group_service.count_groups(session)
    pages = max(1, ceil(total / 6))
    page = min(max(0, page), pages - 1)
    groups = await group_service.list_groups(session, offset=page * 6, limit=6)
    title = {"guard": "🛡 Posbon", "cleaner": "🧹 Tozalovchi", "permissions": "🔑 Ruxsatlar"}[source]
    await render(target, f"{title} — <b>guruhni tanlang</b>\n\n"
                 "Har guruhning qoidalari, rejimi va istisnolari alohida.\n"
                 "⚠️ Global switch guruh qoidasini o'zgartirmaydi.",
                 choose_groups(groups, source=source, page=page, pages=pages))


async def render_policy(
    target: CallbackQuery | Message, session: AsyncSession, group_id: int,
    source: str, role: str | None,
) -> None:
    group = await group_service.get_group(session, group_id)
    if group is None or group.settings is None:
        await render(target, "⚠️ Guruh topilmadi.")
        return
    global_on = await settings_service.is_feature_enabled(source)
    if await settings_service.get("maintenance_mode", False):
        global_on = False
    gate = "🟢 Faol" if group.is_active else "🛑 Guruh PAUZADA"
    global_text = "🟢 yoqilgan" if global_on else "🔴 to'xtagan"
    rights = (group.bot_rights or {}).get("can_delete_messages")
    rights_text = "✅" if group.bot_is_admin and rights else "❌ — avval admin huquqini bering"
    if source == "guard":
        row = await policies.ensure_guard(session, group_id)
        text = (
            f"🛡 <b>Posbon: {escape_html(group.display)}</b>\n"
            f"{gate} · Global: {global_text} · Delete huquqi: {rights_text}\n"
            f"Guruh switch: {'🟢' if group.settings.guard_enabled else '🔴'} · "
            f"Posbon: {'🟢' if row.enabled else '🔴'} · "
            f"Rejim: <b>{'🧪 sinov (FAQAT jurnal)' if row.dry_run else '🔴 JONLI (xabar o‘chadi)'}</b>\n\n"
            f"🔗 Havola: {'✅' if row.link_filter else '—'} · Forward: {'✅' if row.forward_filter else '—'} "
            f"· @mention: {'✅' if row.mention_filter else '—'}\n"
            f"🌐 Domenlar: {escape_html(truncate(', '.join(row.allowed_domains or []), 120))}\n"
            f"🚫 So'zlar: {escape_html(truncate(', '.join(row.banned_words or []), 120))}\n"
            f"⚖️ Jazo: <b>{row.penalty}</b> · chegara: <b>{row.warn_limit}</b> "
            f"· mute: <b>{row.mute_minutes} min</b>\n"
            f"🕒 Hisob oynasi: <b>{(row.escalate or {}).get('warn_window_hours', 24)} soat</b> "
            f"· Adminlar istisno: {'ha' if row.exemption_for_admins else 'yo‘q'}\n\n"
            "ℹ️ Sanoqchi/N alohida shart; posbonning ogohlantirish soniga qo‘shilmaydi. "
            "Bot Privacy Mode o‘chirilgan bo‘lishi kerak."
        )
        kb = guard_kb(group, row, can_edit=_can_edit(role))
    elif source == "cleaner":
        row = await policies.ensure_cleaner(session, group_id)
        text = (
            f"🧹 <b>Tozalovchi: {escape_html(group.display)}</b>\n"
            f"{gate} · Global: {global_text} · Delete huquqi: {rights_text}\n"
            f"Guruh switch: {'🟢' if group.settings.cleaner_enabled else '🔴'} · "
            f"Tozalovchi: {'🟢' if row.enabled else '🔴'} · "
            f"Rejim: <b>{'🧪 sinov (FAQAT jurnal)' if row.dry_run else '🔴 JONLI (xabar o‘chadi)'}</b>\n\n"
            f"🚪 Kirdi-chiqdi {'✅' if row.delete_join_leave else '—'} · "
            f"🔔 Xizmat {'✅' if row.delete_service else '—'} · "
            f"🔗 Havola {'✅' if row.delete_links else '—'}\n"
            f"🛡 Qoidabuzarlik {'✅' if row.delete_violations else '—'} · "
            f"📢 Eski e'lon {'✅' if row.delete_old_ads else '—'}\n"
            f"📌 Pinni saqlash: {'ha' if row.keep_pinned else 'yo‘q'} · "
            f"E'londan oxirgi <b>{row.keep_last_ads}</b> ta qoladi\n"
            f"⏱ Xabar kechikishi: <b>{row.delete_after_seconds or 0} sekund</b> "
            "(eski e'lon yangi postdan keyin).\n\n"
            "ℹ️ Telegram boshqa odamning xabarini tahrirlashga ruxsat bermaydi: "
            "jonli tozalash faqat o‘chirish orqali bajariladi."
        )
        kb = cleaner_kb(group, row, can_edit=_can_edit(role))
    else:
        return
    await render(target, text, kb)


@router.callback_query(PolicyCB.filter(F.action == "choose"))
async def choose(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession) -> None:
    try:
        source, raw_page = callback_data.value.split(".", 1)
        page = int(raw_page)
    except (ValueError, AttributeError):
        await alert(callback, "⚠️ Noto'g'ri sahifa", show=True)
        return
    await render_choose(callback, session, source, page)
    await alert(callback, "")


@router.callback_query(PolicyCB.filter(F.action == "home"))
async def home(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
               role: str | None) -> None:
    await render_policy(callback, session, callback_data.group_id, callback_data.value, role)
    await alert(callback, "")


@router.callback_query(PolicyCB.filter(F.action.in_({"gt", "ct"})))
async def toggle_rule(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
                      role: str | None) -> None:
    if not _can_edit(role):
        await alert(callback, "⛔️ Qoidalarni faqat admin sozlaydi.", show=True)
        return
    source = "guard" if callback_data.action == "gt" else "cleaner"
    group = await group_service.get_group(session, callback_data.group_id)
    if group is None or group.settings is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    field = callback_data.value
    row = await (policies.ensure_guard(session, group.id) if source == "guard"
                 else policies.ensure_cleaner(session, group.id))
    if field not in (policies.GUARD_BOOLEANS if source == "guard" else policies.CLEANER_BOOLEANS) or field == "dry_run":
        await alert(callback, "⚠️ Noma'lum qoida.", show=True)
        return
    active = (row.enabled and getattr(group.settings, f"{source}_enabled")) if field == "enabled" else bool(getattr(row, field))
    try:
        await (policies.edit_guard(session, group, field, not active, callback.from_user.id) if source == "guard"
               else policies.edit_cleaner(session, group, field, not active, callback.from_user.id))
    except ValueError as exc:
        await alert(callback, str(exc), show=True)
        return
    await render_policy(callback, session, group.id, source, role)
    await alert(callback, "🧪 Yoqilganda avval dry-run ishlaydi." if field == "enabled" and not active else "✅ Saqlandi")


@router.callback_query(PolicyCB.filter(F.action == "live"))
async def ask_live(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
                   role: str | None) -> None:
    if not _can_edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    source = callback_data.value
    if source not in {"guard", "cleaner"}:
        return
    group = await group_service.get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    row = await (policies.ensure_guard(session, group.id) if source == "guard"
                 else policies.ensure_cleaner(session, group.id))
    if row.dry_run:
        await render(callback, f"🔴 <b>JONLI REJIMNI TASDIQLASH</b>\n\n"
                     f"{escape_html(group.display)} guruhi uchun {source} endi xabarlarni "
                     "haqiqatan o‘chirishi, posbon esa mute/ban qilishi mumkin.\n\n"
                     "Avval qoidalarni va huquqlarni sinov rejimida tekshiring!",
                     confirm_kb("live_confirm", group.id, source, source))
    else:
        await (policies.edit_guard(session, group, "dry_run", True, callback.from_user.id) if source == "guard"
               else policies.edit_cleaner(session, group, "dry_run", True, callback.from_user.id))
        await render_policy(callback, session, group.id, source, role)
    await alert(callback, "")


@router.callback_query(PolicyCB.filter(F.action == "live_confirm"))
async def confirm_live(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
                       role: str | None) -> None:
    if not _can_edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    group = await group_service.get_group(session, callback_data.group_id)
    source = callback_data.value
    if group is None or source not in {"guard", "cleaner"}:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    await (policies.edit_guard(session, group, "dry_run", False, callback.from_user.id) if source == "guard"
           else policies.edit_cleaner(session, group, "dry_run", False, callback.from_user.id))
    await render_policy(callback, session, group.id, source, role)
    await alert(callback, "🔴 Jonli rejim tasdiqlandi.", show=True)


@router.callback_query(PolicyCB.filter(F.action == "penalties"))
async def penalties(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession) -> None:
    if await group_service.get_group(session, callback_data.group_id) is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    row = await policies.ensure_guard(session, callback_data.group_id)
    await render(callback, "⚖️ <b>Jazo zinapoyasi</b>\n\n"
                 f"Joriy: <b>{row.penalty}</b>, chegara <b>{row.warn_limit}</b> ta.\n"
                 "Ogohlantirishlar guruh bo‘yicha va hisob oynasi ichida sanaladi.\n"
                 "• warn: o‘chirish + DM, mute/ban YO‘Q\n"
                 "• mute: chegarada vaqtincha cheklash\n"
                 "• ban: chegarada mute, ikki baravar chegarada ban\n\n"
                 "🧪 Dry-run rejimida hech qanday Telegram amali yo‘q.",
                 penalty_kb(callback_data.group_id))
    await alert(callback, "")


@router.callback_query(PolicyCB.filter(F.action == "pen"))
async def set_penalty(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
                      role: str | None) -> None:
    if not _can_edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    group = await group_service.get_group(session, callback_data.group_id)
    if group is None or callback_data.value not in {Penalty.WARN, Penalty.MUTE, Penalty.BAN}:
        await alert(callback, "⚠️ Noto'g'ri jazo.", show=True)
        return
    if callback_data.value == Penalty.BAN:
        await render(callback, f"🚫 <b>BAN rejimini tasdiqlang</b>\n\n"
                     f"Faqat {escape_html(group.display)} uchun: "
                     "chegaraning ikki barobarida doimiy ban berilishi mumkin. "
                     "Huquqlarni, dry-run jurnalini va chegarani tekshiring.",
                     confirm_kb("ban_confirm", group.id, "ban", "guard"))
        await alert(callback, "")
        return
    await policies.edit_guard(session, group, "penalty", callback_data.value, callback.from_user.id)
    await render_policy(callback, session, group.id, "guard", role)
    await alert(callback, "⚖️ Jazo turi saqlandi.")


@router.callback_query(PolicyCB.filter(F.action == "ban_confirm"))
async def confirm_ban(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
                      role: str | None) -> None:
    if not _can_edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    group = await group_service.get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    await policies.edit_guard(session, group, "penalty", Penalty.BAN, callback.from_user.id)
    await render_policy(callback, session, group.id, "guard", role)
    await alert(callback, "🚫 BAN qoidasi yozildi (dry-run bo'lsa faol jazo yo'q).", show=True)


@router.callback_query(PolicyCB.filter(F.action.in_({"ge", "ce"})))
async def edit_value(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
                     state: FSMContext, role: str | None) -> None:
    if not _can_edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    source = "guard" if callback_data.action == "ge" else "cleaner"
    field = callback_data.value
    if field not in (_PROMPTS if source == "guard" else {k: v for k, v in _PROMPTS.items()
                                                       if k in {"keep_last_ads", "delete_after_seconds"}}):
        await alert(callback, "⚠️ Noma'lum qiymat.", show=True)
        return
    group = await group_service.get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    row = await (policies.ensure_guard(session, group.id) if source == "guard"
                 else policies.ensure_cleaner(session, group.id))
    current = (row.escalate or {}).get("warn_window_hours", 24) if field == "warn_window_hours" else getattr(row, field)
    await state.set_state(AdminPolicyStates.waiting_value)
    await state.update_data(policy_group_id=group.id, policy_source=source, policy_field=field)
    await render(callback, f"✍️ <b>{source} · {field}</b>\n"
                 f"Guruh: {escape_html(group.display)}\n"
                 f"Hozirgi: <code>{escape_html(str(current or '—'))[:120]}</code>\n\n"
                 + _PROMPTS[field] + "\nBekor qilish: /cancel")
    await alert(callback, "")


@router.message(StateFilter(AdminPolicyStates.waiting_value), F.text)
async def save_value(message: Message, state: FSMContext, session: AsyncSession,
                     role: str | None) -> None:
    if message.text and message.text.startswith("/cancel"):
        await cancel_value(message, state, session, role)
        return
    if not _can_edit(role):
        await state.clear()
        return
    data = await state.get_data()
    source = data.get("policy_source")
    field = data.get("policy_field")
    group = await group_service.get_group(session, int(data.get("policy_group_id") or 0))
    if group is None or source not in {"guard", "cleaner"} or field not in _PROMPTS:
        await state.clear()
        await message.answer("⚠️ Guruh yoki sozlama topilmadi.")
        return
    raw = (message.text or "").strip()
    value: str = "" if raw == "-" and field in {"allowed_domains", "banned_words"} else raw
    try:
        if source == "guard":
            await policies.edit_guard(session, group, field, value, message.from_user.id)
        elif field in {"keep_last_ads", "delete_after_seconds"}:
            await policies.edit_cleaner(session, group, field, value, message.from_user.id)
        else:
            raise ValueError("Noma'lum sozlama.")
    except ValueError as exc:
        await message.answer(f"⚠️ {escape_html(str(exc))}\nBekor qilish: /cancel")
        return
    await state.clear()
    await message.answer("✅ Guruh qoidasi saqlandi.")
    await render_policy(message, session, group.id, source, role)


@router.message(StateFilter(AdminPolicyStates.waiting_value), Command("cancel"))
async def cancel_value(message: Message, state: FSMContext, session: AsyncSession,
                       role: str | None) -> None:
    data = await state.get_data()
    await state.clear()
    if data.get("policy_source") in {"guard", "cleaner"}:
        await render_policy(message, session, int(data.get("policy_group_id") or 0), data["policy_source"], role)


@router.callback_query(PolicyCB.filter(F.action == "pause_ask"))
async def pause_ask(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
                    role: str | None) -> None:
    if not _can_edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    group = await group_service.get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    await render(callback, f"🛑 <b>FAVQULODDA GURUH PAUZASI</b>\n\n"
                 f"{escape_html(group.display)}: posbon, tozalovchi va joylash birga to‘xtaydi. "
                 "Avvalgi qoidalar o‘chmaydi. Huquqlar yangilanganda ham "
                 "bu qo‘lda berilgan pauza saqlanadi. Qayta yoqish: guruh kartasidagi ▶️ tugma.",
                 confirm_kb("pause_confirm", group.id, "-", "guard"))
    await alert(callback, "")


@router.callback_query(PolicyCB.filter(F.action == "pause_confirm"))
async def pause_confirm(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
                        role: str | None) -> None:
    if not _can_edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    group = await group_service.get_group(session, callback_data.group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    if group.is_active:
        await group_service.set_active(session, group, False)
        session.add(ActionLog(
            actor_id=callback.from_user.id, action="group_emergency_pause", entity="group",
            entity_id=group.id, group_id=group.id, before={"is_active": True}, after={"is_active": False},
        ))
    await render_policy(callback, session, group.id, "guard", role)
    await alert(callback, "🛑 Guruh pauzada: barcha amallar to'xtadi.", show=True)


def _old_log_line(log: CleanupLog) -> str:
    details = log.details or {}
    suffix = " 🧪" if details.get("dry_run") else ""
    if details.get("error"):
        suffix += " — " + escape_html(truncate(details["error"], 80))
    if details.get("skipped"):
        suffix += " — " + escape_html(truncate(details["skipped"], 30))
    return f"• {fmt_dt(log.created_at)} · o‘chgan: {log.deleted_count}{suffix}"


@router.callback_query(PolicyCB.filter(F.action == "log"))
async def view_log(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession) -> None:
    group_id = callback_data.group_id
    group = await group_service.get_group(session, group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    actions = await policies.recent_actions(session, group_id, limit=10)
    violations = (await session.execute(select(Violation).where(
        Violation.group_id == group_id,
        Violation.message_id.in_([a.message_id for a in actions] or [-1]),
    ))).scalars().all()
    excerpts = {v.message_id: v.text_excerpt for v in violations}
    totals = await policies.action_totals(session, group_id)
    logs = (await session.execute(select(CleanupLog).where(
        CleanupLog.group_id == group_id, CleanupLog.kind == "old_ad",
    ).order_by(CleanupLog.id.desc()).limit(4))).scalars().all()
    changes = (await session.execute(select(ActionLog).where(
        ActionLog.group_id == group_id,
        ActionLog.action.in_({"guard_setting", "cleaner_setting", "group_policy_switch",
                              "group_emergency_pause", "group_set_active", "warning_reset",
                              "restriction_lift", "manual_restrict", "permission_grant", "permission_revoke"}),
    ).order_by(ActionLog.id.desc()).limit(5))).scalars().all()
    text = (f"📋 <b>{escape_html(group.display)} — xabar siyosati jurnali</b>\n"
            f"Jami holatlar: {', '.join(f'{k}:{v}' for k, v in totals.items()) or '—'}\n\n")
    text += "<b>Xabarlar:</b>\n" + ("\n".join(
        f"• {fmt_dt(a.created_at)} · #{a.message_id} · {a.source}/{a.kind} "
        f"· {a.status}/{a.planned_action}{' 🧪' if a.is_dry_run else ''}"
        f"{f' ({escape_html(truncate(a.error, 80))})' if a.error else ''}"
        f"{f' — {escape_html(truncate(excerpts[a.message_id], 65))}' if excerpts.get(a.message_id) else ''}"
        for a in actions
    ) or "—")
    text += "\n\n<b>Eski e'lonlar:</b>\n" + ("\n".join(_old_log_line(log) for log in logs) or "—")
    text += "\n\n<b>Sozlamalar tarixi:</b>\n" + ("\n".join(
        f"• {fmt_dt(a.created_at)} · admin {a.actor_id or '—'} · {a.action}: "
        f"{escape_html(truncate(str(a.after), 95))}" for a in changes
    ) or "—")
    await render(callback, text[:4000], history_kb(group_id))
    await alert(callback, "")


async def render_pending(callback: CallbackQuery, group_id: int, session: AsyncSession,
                         role: str | None) -> None:
    group = await group_service.get_group(session, group_id)
    if group is None:
        await alert(callback, "⚠️ Guruh topilmadi.", show=True)
        return
    entries = (await session.execute(select(GroupMessageAction).where(
        GroupMessageAction.group_id == group.id,
        GroupMessageAction.status.in_({"pending", "running"}),
    ).order_by(GroupMessageAction.id.desc()).limit(20))).scalars().all()
    text = (f"⏳ <b>{escape_html(group.display)} — kutilayotgan/noaniq amallar</b>\n\n"
            "`pending`: belgilangan vaqtda o'chadi. `running`: Telegram natijasi "
            "noaniq; avtomatik qayta urinish YO'Q.\n\n"
            "⚠️ Jarayondagi API chaqiruvi allaqachon yuborilgan bo'lsa, "
            "bekor qilish o'sha chaqiruvni ortga qaytara olmaydi.\n\n")
    text += "\n".join(
        f"• #{a.id}: xabar #{a.message_id} · {a.source}/{a.kind} · {a.status}"
        f"{f' · {fmt_dt(a.due_at)}' if a.due_at else ''}"
        for a in entries
    ) or "—"
    await render(callback, text, pending_kb(group.id, entries, can_edit=_can_edit(role)))


@router.callback_query(PolicyCB.filter(F.action == "pending"))
async def view_pending(callback: CallbackQuery, callback_data: PolicyCB,
                       session: AsyncSession, role: str | None) -> None:
    await render_pending(callback, callback_data.group_id, session, role)
    await alert(callback, "")


@router.callback_query(PolicyCB.filter(F.action == "action_cancel_ask"))
async def cancel_action_ask(callback: CallbackQuery, callback_data: PolicyCB, session: AsyncSession,
                            role: str | None) -> None:
    if not _can_edit(role) or not callback_data.value.isdigit():
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    action = await session.get(GroupMessageAction, int(callback_data.value))
    if action is None or action.group_id != callback_data.group_id or action.status not in {"pending", "running"}:
        await alert(callback, "⚠️ Bu amal endi kutilmayapti.", show=True)
        return
    await render(callback, f"❌ <b>Xabar amalini bekor qilish</b>\n\n"
                 f"Guruh #{action.group_id} · xabar #{action.message_id} · {action.status}\n"
                 "Telegram'ga yuborilgan amalni ortga qaytarib bo'lmaydi. "
                 "Bekor qilingan amal avtomatik qayta bajarilmaydi.",
                 confirm_kb("action_cancel_confirm", action.group_id, str(action.id),
                            "guard", cancel_action="pending"))
    await alert(callback, "")


@router.callback_query(PolicyCB.filter(F.action == "action_cancel_confirm"))
async def cancel_action_confirm(callback: CallbackQuery, callback_data: PolicyCB,
                                session: AsyncSession, role: str | None) -> None:
    if not _can_edit(role) or not callback_data.value.isdigit():
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    action = await session.get(GroupMessageAction, int(callback_data.value))
    if action is None or action.group_id != callback_data.group_id:
        await alert(callback, "⚠️ Xabar topilmadi.", show=True)
        return
    was = action.status
    changed = await session.execute(update(GroupMessageAction).where(
        GroupMessageAction.id == action.id, GroupMessageAction.group_id == callback_data.group_id,
        GroupMessageAction.status.in_({"pending", "running"}),
    ).values(status="skipped", error="Admin qo'lda bekor qildi.").returning(GroupMessageAction.id))
    if changed.scalar_one_or_none() is None:
        await alert(callback, "⚠️ Amal allaqachon yakunlangan.", show=True)
        return
    session.add(ActionLog(actor_id=callback.from_user.id, action="policy_action_cancel",
                          entity="group_message_actions", entity_id=action.id, group_id=action.group_id,
                          before={"status": was, "message_id": action.message_id},
                          after={"status": "skipped"}))
    await session.flush()
    await render_pending(callback, callback_data.group_id, session, role)
    await alert(callback, "✅ Amal bekor qilindi.", show=True)


__all__ = ["router", "render_choose", "render_policy"]
