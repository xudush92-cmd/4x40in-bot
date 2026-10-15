"""Admin broadcast paneli: preview → aniq tasdiq → 25/s navbat/audit."""

from __future__ import annotations

from html import unescape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole
from app.db.models import Broadcast, BroadcastTarget
from app.filters import IsAdmin
from app.keyboards.callbacks import AdminCB, BroadcastCB
from app.services import broadcast_service
from app.services.settings_service import settings_service
from app.states import AdminBroadcastStates
from app.utils.text import escape_html, truncate
from app.utils.tg import alert, render
from app.utils.time import fmt_dt

router = Router(name="admin:broadcast")
router.message.filter(IsAdmin(AdminRole.ADMIN))
router.callback_query.filter(IsAdmin(AdminRole.ADMIN))

_TARGET_LABEL = {"all": "Barcha shaxsiy foydalanuvchilar", "sellers": "Sotuvchilar",
                 "admins": "Adminlar"}
_STATUS = {"draft": "✏️ Qoralama", "queued": "📥 Navbat", "sending": "📣 Yuborilmoqda",
           "paused": "⏸ Pauza", "cancelled": "🚫 Bekor", "finished": "✅ Tugadi",
           "needs_review": "⚠️ Qo'lda tekshirish"}


def _btn(label: str, action: str, broadcast_id: int = 0,
         target: str = "all") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=label, callback_data=BroadcastCB(
        action=action, broadcast_id=broadcast_id, target=target,
    ).pack())


async def render_home(target: Message | CallbackQuery, session: AsyncSession) -> None:
    rows = (await session.execute(select(Broadcast).order_by(Broadcast.id.desc()).limit(10))).scalars().all()
    rate = min(25, max(1, int(await settings_service.get("broadcast_rate_per_sec", 25, session) or 25)))
    enabled = await settings_service.is_feature_enabled_fresh("broadcast")
    text = ("📣 <b>Broadcast</b> — shaxsiy /start qilganlar\n"
            f"Global holat: {'🟢 ishlayapti' if enabled else '⏸ pauza'} · tezlik: <b>{rate}/s</b>\n"
            "Rasm yoki matn yuboring; avval preview/sinov, keyin alohida tasdiq. "
            "Guruhdagi a'zolarga avtomatik xabar yuborilmaydi.\n\n"
            "Oxirgi tarqatishlar:")
    buttons = [[_btn(f"➕ {_TARGET_LABEL[key]}", "new", target=key)]
               for key in ("all", "sellers", "admins")]
    buttons.append([_btn("⚙️ Tezlikni sozlash (1–25/s)", "rate")])
    buttons += [[_btn(f"#{row.id} {_STATUS.get(row.status, row.status)} "
                      f"{row.sent}/{row.total} · {truncate(unescape(row.text or '🖼 rasm'), 17)}",
                      "card", row.id)] for row in rows]
    buttons.append([InlineKeyboardButton(text="◀️ Panel", callback_data=AdminCB(action="menu").pack())])
    await render(target, text, InlineKeyboardMarkup(inline_keyboard=buttons))


async def render_card(target: CallbackQuery | Message, session: AsyncSession, broadcast_id: int,
                      *, owner_id: int | None = None) -> None:
    row = await session.get(Broadcast, broadcast_id)
    if row is None:
        if isinstance(target, CallbackQuery):
            await alert(target, "Tarqatish topilmadi.", show=True)
        return
    counts = (await session.execute(select(BroadcastTarget.status, func.count(BroadcastTarget.id))
                                    .where(BroadcastTarget.broadcast_id == row.id)
                                    .group_by(BroadcastTarget.status))).all()
    stats = dict(counts)
    text = (f"📣 <b>Broadcast #{row.id}</b> — {_STATUS.get(row.status, row.status)}\n"
            f"Kimga: {_TARGET_LABEL.get(row.target, row.target)} · admin <code>{row.admin_id}</code>\n"
            f"Yaratildi: {fmt_dt(row.created_at)}\n"
            f"Jami: {row.total} · yuborildi: {row.sent} · aniq xato: {row.failed}\n"
            f"Navbat: {stats.get('pending', 0)} · noaniq: {stats.get('uncertain', 0)}\n"
            f"Rasm: {'bor' if row.photo_file_id else 'yo‘q'}\n\n"
            f"<b>Xabar ko'rinishi:</b>\n{escape_html(truncate(unescape(row.text or ''), 1700)) or '🖼 Rasm (matnsiz)'}")
    if row.status == "draft":
        text += ("\n\n<i>Bu hali hech kimga yuborilmadi. Sinov faqat sizga yuboriladi; "
                 "qabul qiluvchilar tasdiq vaqtida muzlatiladi.</i>")
    if row.status == "needs_review":
        uncertain = (await session.execute(select(BroadcastTarget).where(
            BroadcastTarget.broadcast_id == row.id, BroadcastTarget.status == "uncertain",
        ).limit(3))).scalars().all()
        text += ("\n\n⚠️ Tarmoq uzilgach bu qabul qiluvchilarga xabar borgan-bormagani "
                 "noma'lum. Avtomatik qayta yuborilmaydi.")
        text += "".join(f"\n<code>{item.user_id}</code> · {escape_html(truncate(item.error, 60))}"
                        for item in uncertain)
    buttons = []
    if row.status == "draft" and owner_id == row.admin_id:
        buttons += [[_btn("👀 Faqat menga sinov yuborish", "test", row.id)],
                    [_btn("✅ Tarqatishni tasdiqlash", "ask", row.id)]]
    elif row.status in {"queued", "sending"}:
        buttons += [[_btn("⏸ Pauza", "pause", row.id)],
                    [_btn("🚫 Bekor qilish", "ask_cancel", row.id)]]
    elif row.status == "paused":
        buttons += [[_btn("▶️ Davom ettirish", "resume", row.id)],
                    [_btn("🚫 Bekor qilish", "ask_cancel", row.id)]]
    elif row.status == "needs_review":
        buttons.append([_btn("✅ Tekshirildi, qayta yubormay yopish", "ask_resolve", row.id)])
    buttons += [[_btn("🔄 Yangilash", "card", row.id)], [_btn("◀️ Tarqatishlar", "home")]]
    await render(target, text, InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(BroadcastCB.filter(F.action == "home"))
async def home(callback: CallbackQuery, session: AsyncSession) -> None:
    await render_home(callback, session)
    await alert(callback, "")


@router.callback_query(BroadcastCB.filter(F.action == "new"))
async def start_new(callback: CallbackQuery, callback_data: BroadcastCB,
                    state: FSMContext) -> None:
    if callback_data.target not in _TARGET_LABEL:
        await alert(callback, "Noma'lum auditoriya.", show=True)
        return
    await state.set_state(AdminBroadcastStates.waiting_payload)
    await state.update_data(target=callback_data.target)
    await render(callback, f"📣 <b>{_TARGET_LABEL[callback_data.target]}</b> uchun xabar.\n\n"
                 "Bir dona <b>matn</b> yoki <b>rasm</b> (ixtiyoriy caption) yuboring. "
                 "Teglar literal matn hisoblanadi, xavfsiz ko'rsatiladi.\n"
                 "Rasm caption'i 1024, oddiy matn 4096 belgidan oshmasin.\n"
                 "/cancel — bekor qilish.")
    await alert(callback, "")


@router.message(StateFilter(AdminBroadcastStates.waiting_payload), Command("cancel"))
@router.message(StateFilter(AdminBroadcastStates.waiting_rate), Command("cancel"))
async def cancel(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await render_home(message, session)


@router.message(StateFilter(AdminBroadcastStates.waiting_payload))
async def save_payload(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    if data.get("target") not in _TARGET_LABEL:
        await state.clear()
        await message.answer("Jarayon eskirgan; yangidan boshlang.")
        return
    photo = message.photo[-1].file_id if message.photo else None
    raw = message.text or message.caption
    try:
        row = await broadcast_service.create_draft(session, message.from_user.id,
                                                   data["target"], raw, photo)
    except broadcast_service.BroadcastError as exc:
        await message.answer(f"⚠️ {escape_html(str(exc))} /cancel — bekor qilish.")
        return
    await state.clear()
    await render_card(message, session, row.id, owner_id=message.from_user.id)


@router.callback_query(BroadcastCB.filter(F.action == "card"))
async def card(callback: CallbackQuery, callback_data: BroadcastCB, session: AsyncSession) -> None:
    await render_card(callback, session, callback_data.broadcast_id, owner_id=callback.from_user.id)
    await alert(callback, "")


@router.callback_query(BroadcastCB.filter(F.action == "test"))
async def test_to_me(callback: CallbackQuery, callback_data: BroadcastCB, session: AsyncSession,
                     bot: Bot) -> None:
    row = await session.get(Broadcast, callback_data.broadcast_id)
    if row is None or row.admin_id != callback.from_user.id or row.status != "draft":
        await alert(callback, "Bu qoralama sinov uchun yaroqsiz.", show=True)
        return
    try:
        if row.photo_file_id:
            await bot.send_photo(callback.from_user.id, row.photo_file_id, caption=row.text, parse_mode="HTML")
        else:
            await bot.send_message(callback.from_user.id, row.text or "", parse_mode="HTML")
    except TelegramAPIError as exc:
        await alert(callback, f"Sinov xatosi: {truncate(str(exc), 120)}", show=True)
        return
    await alert(callback, "👀 Sinov faqat sizga yuborildi; boshqalarga tarqatilmadi.", show=True)


@router.callback_query(BroadcastCB.filter(F.action == "ask"))
async def ask_confirm(callback: CallbackQuery, callback_data: BroadcastCB,
                      session: AsyncSession) -> None:
    row = await session.get(Broadcast, callback_data.broadcast_id)
    if row is None or row.admin_id != callback.from_user.id or row.status != "draft":
        await alert(callback, "Qoralama eskirgan.", show=True)
        return
    count = await broadcast_service.eligible_count(session, row.target)
    await render(callback, f"⚠️ <b>Tarqatishni TASDIQLAYSIZMI?</b>\n\n"
                 f"#{row.id} · {_TARGET_LABEL[row.target]} · hozirda <b>{count}</b> qabul qiluvchi.\n"
                 "Tasdiqda ro'yxat qayta hisoblanadi, muzlatiladi va fon navbatida "
                 "yuborish boshlanadi. Orqaga qaytarsangiz hali hech kimga bormagan bo'ladi.",
                 InlineKeyboardMarkup(inline_keyboard=[
                     [_btn("✅ Ha, hammaga yuborish", "confirm", row.id)],
                     [_btn("❌ Yo'q, preview", "card", row.id)],
                 ]))
    await alert(callback, "")


@router.callback_query(BroadcastCB.filter(F.action == "confirm"))
async def confirm(callback: CallbackQuery, callback_data: BroadcastCB,
                  session: AsyncSession) -> None:
    try:
        row = await broadcast_service.confirm(session, callback_data.broadcast_id,
                                              callback.from_user.id)
    except broadcast_service.BroadcastError as exc:
        await alert(callback, str(exc), show=True)
        return
    await render_card(callback, session, row.id, owner_id=callback.from_user.id)
    await alert(callback, f"✅ {row.total} qabul qiluvchi navbatga qo'yildi.", show=True)


@router.callback_query(BroadcastCB.filter(F.action.in_({"pause", "resume"})))
async def toggle_pause(callback: CallbackQuery, callback_data: BroadcastCB,
                       session: AsyncSession) -> None:
    try:
        row = await broadcast_service.change_status(session, callback_data.broadcast_id,
                                                    callback.from_user.id, callback_data.action)
    except broadcast_service.BroadcastError as exc:
        await alert(callback, str(exc), show=True)
        return
    await render_card(callback, session, row.id, owner_id=callback.from_user.id)
    await alert(callback, "Holat yangilandi; allaqachon ketayotgan 1 xabar tugashi mumkin.")


@router.callback_query(BroadcastCB.filter(F.action.in_({"ask_cancel", "ask_resolve"})))
async def ask_action(callback: CallbackQuery, callback_data: BroadcastCB) -> None:
    action = "cancel" if callback_data.action == "ask_cancel" else "resolve"
    warning = ("Qolgan manzillarga xabar bormaydi; allaqachon yuborilganlar qaytarilmaydi."
               if action == "cancel" else
               "Noaniq natijalar 'xato' deb yopiladi; ayrimlari aslida yetib borgan bo'lishi "
               "mumkin. Hech qaysi biriga qayta yuborilmaydi.")
    await render(callback, f"⚠️ <b>#{callback_data.broadcast_id} — amalni tasdiqlang</b>\n{warning}",
                 InlineKeyboardMarkup(inline_keyboard=[
                     [_btn("✅ Ha, tasdiqlayman", action, callback_data.broadcast_id)],
                     [_btn("❌ Yo'q", "card", callback_data.broadcast_id)],
                 ]))
    await alert(callback, "")


@router.callback_query(BroadcastCB.filter(F.action.in_({"cancel", "resolve"})))
async def finish_action(callback: CallbackQuery, callback_data: BroadcastCB,
                        session: AsyncSession) -> None:
    try:
        row = await broadcast_service.change_status(session, callback_data.broadcast_id,
                                                    callback.from_user.id, callback_data.action)
    except broadcast_service.BroadcastError as exc:
        await alert(callback, str(exc), show=True)
        return
    await render_card(callback, session, row.id, owner_id=callback.from_user.id)
    await alert(callback, "Holat saqlandi.")


@router.callback_query(BroadcastCB.filter(F.action == "rate"))
async def start_rate(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminBroadcastStates.waiting_rate)
    await render(callback, "📣 1 dan 25 gacha yangi xabar/sekund limitini yuboring. "
                 "Barcha poster processlar Redis orqali bir xil limitga amal qiladi.\n"
                 "/cancel — bekor qilish.")
    await alert(callback, "")


@router.message(StateFilter(AdminBroadcastStates.waiting_rate))
async def save_rate(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 25:
        await message.answer("⚠️ Faqat 1–25 oralig'idagi sonni yuboring. /cancel — bekor qilish.")
        return
    await settings_service.set(session, "broadcast_rate_per_sec", int(raw),
                               updated_by=message.from_user.id)
    await state.clear()
    await render_home(message, session)
