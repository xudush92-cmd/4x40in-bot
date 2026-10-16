"""Phase 8: referal yoqish, xavfsiz konfiguratsiya va hisobot."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole, BonusType, ReferralTrigger
from app.db.models import ActionLog, Referral, ReferralBonusLog
from app.filters import IsAdmin
from app.keyboards.callbacks import AdminCB, ReferralAdminCB
from app.services import referral_service
from app.services.settings_service import settings_service
from app.states import AdminReferralStates
from app.utils.text import escape_html
from app.utils.tg import alert, render

router = Router(name="admin:referral")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


def _edit(role: str | None) -> bool:
    return role in (AdminRole.ADMIN, AdminRole.SUPER)


def _btn(text: str, action: str, value: str = "-") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=ReferralAdminCB(action=action, value=value).pack())


async def render_home(target: Message | CallbackQuery, session: AsyncSession,
                      role: str | None) -> None:
    conf = await referral_service.config(session)
    enabled = bool(await settings_service.get("referral_enabled", False, session))
    stats = (await session.execute(select(Referral.status, func.count(Referral.id))
                                   .group_by(Referral.status))).all()
    data = {status: int(n) for status, n in stats}
    spent = (await session.execute(select(func.count(ReferralBonusLog.id)))).scalar_one()
    text = ("🤝 <b>Referal (guruh sanoqchisidan alohida)</b>\n"
            f"Holat: {'🟢 YOQILGAN' if enabled else '⏸ PAUZA (standart)'}\n"
            f"Shart: {escape_html(str(conf['trigger']))} · tur: {escape_html(str(conf['bonus_type']))}\n"
            f"Bonus: {escape_html(str(conf['bonus_value']))} · kunlik taklif limiti: {conf['daily_limit']}\n"
            f"Birinchi chek min.: {conf['min_payment']} UZS\n"
            f"👥 Keldi: {sum(data.values())} · 🎉 Bonus: {data.get('applied', 0)} "
            f"· ⏳ Kutmoqda: {data.get('pending', 0)} · ❌ Rad: {data.get('rejected', 0)}\n"
            f"📋 Bonus jurnali: {spent}\n\n"
            "Faqat yangi /start ref_<kod> qabul qilinadi. Kod egasi sotuvchi bo'lishi kerak. "
            "Bir odam uchun bir marta, kunlik limit. Birinchi to'lovni faqat admin tasdiqlaydi. "
            "Faol tarifi yo'q sotuvchining 'kun' bonusi navbatda saqlanadi.")
    rows = []
    if _edit(role):
        rows += [
            [_btn("⏸ O'chirish" if enabled else "🟢 Yoqish (tasdiq)", "toggle_ask")],
            [_btn("📋 Shart: ro'yxatdan o'tish", "trigger_ask", ReferralTrigger.SIGNUP),
             _btn("💳 Birinchi chek", "trigger", ReferralTrigger.FIRST_PAYMENT)],
            [_btn("📆 Kun", "type", BonusType.DAYS),
             _btn("💰 Balans", "type", BonusType.BALANCE),
             _btn("% Chegirma", "type", BonusType.DISCOUNT)],
            [_btn("🎁 Bonus miqdori", "number", "bonus_value"),
             _btn("📆 Kunlik limit", "number", "daily_limit")],
            [_btn("💳 Minimal chek (UZS)", "number", "min_payment")],
        ]
    rows += [[_btn("🏆 Top-10", "top")],
             [InlineKeyboardButton(text="◀️ Panel", callback_data=AdminCB(action="menu").pack())]]
    await render(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(ReferralAdminCB.filter(F.action == "home"))
async def home(callback: CallbackQuery, session: AsyncSession, role: str | None) -> None:
    await render_home(callback, session, role)
    await alert(callback, "")


@router.callback_query(ReferralAdminCB.filter(F.action == "toggle_ask"))
async def toggle_ask(callback: CallbackQuery, role: str | None, session: AsyncSession) -> None:
    if not _edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    current = bool(await settings_service.get("referral_enabled", False, session))
    text = ("🟢 <b>JONLI referalni yoqish</b>\n"
            "Yangi ro'yxatga olish va pul/kun/kupon bonuslari kuchga kiradi. "
            "Avval shart va miqdorni tekshiring; ikki bosqichda tasdiqlang." if not current
            else "⏸ Referalni to'xtatish? Saqlangan yozuvlar o'chmaydi.")
    await render(callback, text, InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✅ Tasdiqlayman", "toggle", "off" if current else "on")],
        [_btn("◀️ Bekor", "home")],
    ]))
    await alert(callback, "")


@router.callback_query(ReferralAdminCB.filter(F.action == "toggle"))
async def toggle(callback: CallbackQuery, callback_data: ReferralAdminCB,
                 session: AsyncSession, role: str | None) -> None:
    if not _edit(role) or callback_data.value not in {"on", "off"}:
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    new = callback_data.value == "on"
    current = bool(await settings_service.get("referral_enabled", False, session))
    if current != new:
        await settings_service.set(session, "referral_enabled", new, updated_by=callback.from_user.id)
        session.add(ActionLog(actor_id=callback.from_user.id, action="referral_switch",
                              entity="setting", before={"enabled": current}, after={"enabled": new}))
    await render_home(callback, session, role)
    await alert(callback, "✅ Saqlandi", show=True)


@router.callback_query(ReferralAdminCB.filter(F.action == "trigger_ask"))
async def signup_ask(callback: CallbackQuery, role: str | None) -> None:
    if not _edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    await render(callback, "⚠️ <b>Signup bonusini tasdiqlash</b>\n"
                 "Har bir yangi akkaunt (to'lovsiz ham) bonusga olib keladi! "
                 "Firibgarlik xavfi bor. Kunlik limit va miqdorni tekshiring.",
                 InlineKeyboardMarkup(inline_keyboard=[
                     [_btn("✅ Signup'ni tasdiqlayman", "trigger", ReferralTrigger.SIGNUP)],
                     [_btn("◀️ Bekor", "home")],
                 ]))
    await alert(callback, "")


@router.callback_query(ReferralAdminCB.filter(F.action.in_({"trigger", "type"})))
async def select_config(callback: CallbackQuery, callback_data: ReferralAdminCB,
                        session: AsyncSession, role: str | None) -> None:
    if not _edit(role):
        await alert(callback, "⛔️ Faqat admin.", show=True)
        return
    key = "trigger" if callback_data.action == "trigger" else "bonus_type"
    try:
        await referral_service.set_config(session, key, callback_data.value, callback.from_user.id)
    except ValueError as exc:
        await alert(callback, str(exc), show=True)
        return
    await render_home(callback, session, role)
    await alert(callback, "✅ Sozlandi. Bonus turi o'zgarganda miqdor standartga qaytadi.")


@router.callback_query(ReferralAdminCB.filter(F.action == "number"))
async def ask_number(callback: CallbackQuery, callback_data: ReferralAdminCB,
                     state: FSMContext, role: str | None) -> None:
    if not _edit(role) or callback_data.value not in {"bonus_value", "daily_limit", "min_payment"}:
        await alert(callback, "⛔️ Ruxsat yoki sozlama noto'g'ri.", show=True)
        return
    await state.set_state(AdminReferralStates.waiting_value)
    await state.update_data(ref_field=callback_data.value)
    await render(callback, f"✍️ <b>{escape_html(callback_data.value)}</b> uchun raqam yuboring.\n"
                 f"Kun: 1–{referral_service.MAX_BONUS_DAYS:.0f}, "
                 f"balans UZS: 1000–{referral_service.MAX_BONUS_BALANCE:.0f}, "
                 f"chegirma: 1–{referral_service.MAX_DISCOUNT_PERCENT:.0f}% (xavfsizlik chegarasi), "
                 f"kunlik limit: 1–{referral_service.MAX_DAILY_REFERRALS}, "
                 f"minimal chek: 0–{referral_service.MAX_MIN_PAYMENT:.0f} UZS.\n"
                 "/cancel — bekor qilish.")
    await alert(callback, "")


@router.message(Command("cancel"), StateFilter(AdminReferralStates.waiting_value))
async def cancel_number(message: Message, state: FSMContext, session: AsyncSession,
                        role: str | None) -> None:
    await state.clear()
    await render_home(message, session, role)


@router.message(StateFilter(AdminReferralStates.waiting_value), F.text)
async def save_number(message: Message, state: FSMContext, session: AsyncSession,
                      role: str | None) -> None:
    if not _edit(role):
        await state.clear()
        return
    key = (await state.get_data()).get("ref_field", "-")
    if key not in {"bonus_value", "daily_limit", "min_payment"} or len(message.text) > 20:
        await message.answer("⚠️ Qiymat noto'g'ri. /cancel — bekor qilish.")
        return
    try:
        await referral_service.set_config(session, key, message.text, message.from_user.id)
    except ValueError as exc:
        await message.answer(f"⚠️ {escape_html(str(exc))} /cancel — bekor qilish.")
        return
    await state.clear()
    await render_home(message, session, role)


@router.callback_query(ReferralAdminCB.filter(F.action == "top"))
async def top(callback: CallbackQuery, session: AsyncSession) -> None:
    rows = (await session.execute(select(Referral.referrer_id,
                                        func.count(Referral.id),
                                        func.count(Referral.id).filter(Referral.status == "applied"))
                                  .group_by(Referral.referrer_id)
                                  .order_by(func.count(Referral.id).desc())
                                  .limit(10))).all()
    lines = ["🏆 <b>Referal reytingi</b> (taklif/bonus)"]
    lines += [f"{i}. <code>{user_id}</code> · {invited} / {int(rewarded or 0)}"
              for i, (user_id, invited, rewarded) in enumerate(rows, 1)]
    if not rows:
        lines.append("Hali hech kim taklif qilmagan.")
    await render(callback, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[[_btn("◀️ Referal", "home")]]))
    await alert(callback, "")
