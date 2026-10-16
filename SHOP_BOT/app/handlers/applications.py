"""UX-2: shaxsiy chatdagi ariza ustasi va admin navbati (tarifdan mustaqil)."""

from __future__ import annotations

from math import ceil

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AdminRole, ApplicationStatus, SellerStatus
from app.db.models import SellerApplication
from app.filters import IsAdmin, PrivateChat
from app.keyboards.applications import (
    REASONS,
    card_kb,
    confirm_kb,
    custom_reason_kb,
    pending_kb,
    reject_kb,
    status_kb,
    wizard_kb,
)
from app.keyboards.callbacks import ApplicationCB
from app.keyboards.guide import user_start_kb
from app.keyboards.seller_panel import seller_menu_kb
from app.services import application_service, seller_service
from app.services.application_service import ApplicationError
from app.services.notify import notify_application_admins, notify_application_result
from app.services.settings_service import settings_service
from app.states import AdminApplicationStates, SellerApplicationStates
from app.utils.text import escape_html
from app.utils.tg import alert, render
from app.utils.time import ensure_aware, fmt_dt, utcnow

user_router = Router(name="user:applications")
user_router.message.filter(PrivateChat())
user_router.callback_query.filter(PrivateChat())

admin_router = Router(name="admin:applications")
admin_router.message.filter(IsAdmin(AdminRole.ADMIN))
admin_router.callback_query.filter(IsAdmin(AdminRole.ADMIN))

PER_PAGE = 6


def user_status_text(application: SellerApplication) -> str:
    """Faqat o'z arizasi uchun; admin HTMLi ham shu escape qoidalariga amal qiladi."""
    if application.status == ApplicationStatus.PENDING:
        return (f"📋 <b>Ariza #{application.id} ko'rib chiqilmoqda.</b>\n"
                f"🕒 Yuborilgan: {fmt_dt(application.created_at)}\n"
                "Admin qarorini kuting. Takror yuborish navbatni tezlatmaydi.")
    if application.status == ApplicationStatus.REJECTED:
        return (f"❌ <b>Ariza #{application.id} rad etildi.</b>\n"
                f"Sabab: {escape_html(application.reject_reason or 'Admin bilan bog‘laning.')}\n"
                "Sababni tuzatib 1 soatdan keyin qayta ariza bering (24 soatda ko'pi bilan 3 ta).")
    return (f"✅ <b>Ariza #{application.id} tasdiqlandi.</b>\n"
            "Sotuvchi paneli ochilgan bo'lishi kerak. Tarif/to'lov/e'lon alohida ko'rib chiqiladi.")


async def render_user_status(target: CallbackQuery | Message, session: AsyncSession, user_id: int) -> None:
    """Ma'lumot faqat event.from_user.id bo'yicha olinadi; callbackda ID yo'q."""
    seller = await seller_service.get_seller(session, user_id)
    if seller is not None:
        if seller.status in {SellerStatus.BLOCKED, SellerStatus.DELETED}:
            support = str(await settings_service.get("support_contact", "@admin", session))
            await render(target, "🚫 Sotuvchi hisobingiz cheklangan. Yangi ariza bu holatni bekor qilmaydi. "
                         "Sabab va tiklash uchun adminga murojaat qiling.",
                         user_start_kb(support, can_apply=False))
        else:
            await render(target, "✅ Siz sotuvchisiz. Tarif hali bo'lmasa, uni alohida tanlang.",
                         seller_menu_kb())
        return
    application = await application_service.latest_for(session, user_id)
    if application is None:
        support = str(await settings_service.get("support_contact", "@admin", session))
        await render(target, "📋 Sizda hali sotuvchilik arizasi yo'q. /start orqali ariza yuboring.",
                     user_start_kb(support))
        return
    can_retry = not (application.status == ApplicationStatus.REJECTED and application.decided_at
                     and ensure_aware(application.decided_at) + application_service.RETRY_AFTER > utcnow())
    await render(target, user_status_text(application), status_kb(application, can_retry=can_retry))


@user_router.callback_query(ApplicationCB.filter(F.action == "new"))
async def start_application(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    try:
        pending = await application_service.precheck(session, callback.from_user.id)
    except ApplicationError as exc:
        await render_user_status(callback, session, callback.from_user.id)
        await alert(callback, str(exc), show=True)
        return
    if pending is not None:
        await render_user_status(callback, session, callback.from_user.id)
        await alert(callback, f"Ariza #{pending.id} navbatda", show=True)
        return
    await state.clear()
    await state.set_state(SellerApplicationStates.waiting_name)
    await render(callback, "🛒 <b>Sotuvchi bo'lish uchun ariza</b>\n\n"
                 "1️⃣ Ism yoki do'kon nomini yuboring (2–64 belgi).\n"
                 "Oddiy /start hamma uchun ochiq; faqat sotuvchi paneli admin qaroridan keyin ochiladi.\n"
                 "Bekor qilish: /cancel", wizard_kb())
    await alert(callback, "")


@user_router.message(StateFilter(SellerApplicationStates.waiting_name), F.text & ~F.text.startswith("/"))
async def application_name(message: Message, state: FSMContext) -> None:
    try:
        name = application_service.validate_name(message.text)
    except ApplicationError as exc:
        await message.answer(f"⚠️ {escape_html(str(exc))} Qayta yuboring yoki /cancel.")
        return
    await state.update_data(name=name)
    await state.set_state(SellerApplicationStates.waiting_contact)
    await message.answer("2️⃣ @username (kamida 5 belgi) yoki telefon raqamini yuboring "
                         "(masalan +998901234567). Faqat shu ikkitasidan biri talab qilinadi.\n"
                         "Bekor qilish: /cancel", reply_markup=wizard_kb())


@user_router.message(StateFilter(SellerApplicationStates.waiting_contact), F.text & ~F.text.startswith("/"))
async def application_contact(message: Message, state: FSMContext) -> None:
    try:
        kind, contact = application_service.validate_contact(message.text)
    except ApplicationError as exc:
        await message.answer(f"⚠️ {escape_html(str(exc))} Qayta yuboring yoki /cancel.")
        return
    data = await state.get_data()
    name = data.get("name")
    if not name:
        await state.clear()
        await message.answer("⚠️ Ma'lumotlar eskirgan. /start orqali qayta boshlang.")
        return
    await state.update_data(contact=contact)
    await state.set_state(SellerApplicationStates.preview)
    await message.answer(
        "📝 <b>Arizani tekshiring</b>\n"
        f"👤 Ism/do'kon: <b>{escape_html(name)}</b>\n"
        f"☎️ {'Telegram' if kind == 'username' else 'Telefon'}: <code>{escape_html(contact)}</code>\n\n"
        "✅ Yuborsangiz, faqat admin ko'radi; tasdiq tarif/chek/e'lonni bermaydi.",
        reply_markup=wizard_kb(preview=True),
    )


@user_router.callback_query(ApplicationCB.filter(F.action == "edit"))
async def edit_application(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await start_application(callback, session, state)


@user_router.callback_query(ApplicationCB.filter(F.action == "submit"))
async def send_application(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot,
) -> None:
    data = await state.get_data()
    if await state.get_state() != SellerApplicationStates.preview.state or not data.get("name") or not data.get("contact"):
        await render_user_status(callback, session, callback.from_user.id)
        await alert(callback, "⚠️ Avval arizani to'ldiring.", show=True)
        return
    try:
        application, created = await application_service.submit(
            session, callback.from_user.id, data["name"], data["contact"],
        )
    except ApplicationError as exc:
        await render(callback, f"⚠️ {escape_html(str(exc))}\nArizani tahrirlang yoki /start dan holatni ko'ring.",
                     wizard_kb(preview=True))
        await alert(callback, "Ariza yuborilmadi", show=True)
        return
    # Avval DB, keyin Telegram. Bildirishnoma xatosi arizani yo'qotmaydi.
    await session.commit()
    await state.clear()
    await render(callback, user_status_text(application), status_kb(application))
    await alert(callback, "Ariza navbatga qo'shildi" if created else "Ariza avval yuborilgan")
    if created:
        try:
            await notify_application_admins(bot, application.id)
        except Exception:
            logger.exception("Ariza #{} xabarnomasi yuborilmadi (navbat DB'da)", application.id)


@user_router.callback_query(ApplicationCB.filter(F.action == "status"))
async def application_status(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if await state.get_state() in {s.state for s in SellerApplicationStates.__all_states__}:
        await state.clear()
    await render_user_status(callback, session, callback.from_user.id)
    await alert(callback, "")


@user_router.callback_query(ApplicationCB.filter(F.action == "cancel"))
async def cancel_application(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if await state.get_state() in {s.state for s in SellerApplicationStates.__all_states__}:
        await state.clear()
    await render_user_status(callback, session, callback.from_user.id)
    await alert(callback, "Ariza to'ldirish bekor qilindi")


@user_router.message(Command("cancel"), StateFilter(SellerApplicationStates))
async def cancel_application_text(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Ariza to'ldirish bekor qilindi. /start orqali qayta boshlang.")


def _admin_card_text(application: SellerApplication) -> str:
    status = {
        ApplicationStatus.PENDING: "🕓 Qaror kutmoqda",
        ApplicationStatus.APPROVED: "✅ Tasdiqlangan",
        ApplicationStatus.REJECTED: "❌ Rad etilgan",
    }.get(application.status, "Noma'lum")
    lines = [
        f"📋 <b>Sotuvchilik arizasi #{application.id}</b>",
        f"📌 Holat: {status}",
        f"🆔 Telegram ID: <code>{application.user_id}</code>",
        f"👤 Ism/do'kon: <b>{escape_html(application.display_name)}</b>",
        f"☎️ Aloqa: <code>{escape_html(application.contact_value)}</code>",
        f"🕒 Yuborildi: {fmt_dt(application.created_at)}",
    ]
    if application.decided_at:
        lines.append(f"🕒 Qaror: {fmt_dt(application.decided_at)} · admin <code>{application.decided_by}</code>")
    if application.reject_reason:
        lines.append(f"❌ Sabab: {escape_html(application.reject_reason)}")
    if application.seller_id:
        lines.append(f"🛒 Sotuvchi ID: <code>{application.seller_id}</code>")
    lines.append("\n<i>Tasdiq faqat sotuvchi panelini ochadi; tarif, chek va e'lon alohida.</i>")
    return "\n".join(lines)


async def render_admin_list(target: CallbackQuery | Message, session: AsyncSession, page: int = 0) -> None:
    count = await application_service.count_pending(session)
    pages = max(1, ceil(count / PER_PAGE))
    page = max(0, min(page, pages - 1))
    items = await application_service.list_pending(session, offset=page * PER_PAGE, limit=PER_PAGE)
    await render(target, f"📥 <b>Sotuvchilik arizalari</b> · qaror kutmoqda: {count}\n"
                 f"Sahifa {page + 1}/{pages}\n\n"
                 + ("Avval yuborilgan arizalarni ko'rib, so'ng qaror qiling." if items
                    else "📭 Hozir navbat bo'sh."), pending_kb(items, page, pages))


async def render_admin_card(
    target: CallbackQuery | Message, session: AsyncSession, application_id: int, page: int = 0,
) -> bool:
    application = await session.get(SellerApplication, application_id)
    if application is None:
        await render(target, "⚠️ Ariza topilmadi.")
        return False
    await render(target, _admin_card_text(application), card_kb(application, page))
    return True


@admin_router.callback_query(ApplicationCB.filter(F.action == "list"))
async def admin_list(callback: CallbackQuery, callback_data: ApplicationCB,
                     session: AsyncSession, state: FSMContext) -> None:
    if await state.get_state() == AdminApplicationStates.waiting_reason.state:
        await state.clear()
    await render_admin_list(callback, session, callback_data.page)
    await alert(callback, "")


@admin_router.callback_query(ApplicationCB.filter(F.action == "card"))
async def admin_card(callback: CallbackQuery, callback_data: ApplicationCB,
                     session: AsyncSession, state: FSMContext) -> None:
    if await state.get_state() == AdminApplicationStates.waiting_reason.state:
        await state.clear()
    ok = await render_admin_card(callback, session, callback_data.application_id, callback_data.page)
    await alert(callback, "" if ok else "Ariza topilmadi", show=not ok)


@admin_router.callback_query(ApplicationCB.filter(F.action == "approve"))
async def admin_approve_preview(
    callback: CallbackQuery, callback_data: ApplicationCB, session: AsyncSession,
) -> None:
    application = await session.get(SellerApplication, callback_data.application_id)
    if application is None or application.status != ApplicationStatus.PENDING:
        await render_admin_card(callback, session, callback_data.application_id, callback_data.page)
        await alert(callback, "Ariza navbatda emas", show=True)
        return
    await render(callback, _admin_card_text(application) + "\n\n"
                 "❗️Tasdiqlash faqat sotuvchi panelini ochadi. Tarif/chek/e'lon berilmaydi.",
                 confirm_kb(application.id, callback_data.page))
    await alert(callback, "")


async def _decide(
    target: CallbackQuery | Message, session: AsyncSession, bot: Bot,
    application_id: int, actor_id: int, *, approve: bool,
    reason: str | None = None, page: int = 0,
) -> bool:
    try:
        application, changed = await application_service.decide(
            session, application_id, actor_id, approve=approve, reason=reason,
        )
    except ApplicationError as exc:
        await render(target, f"⚠️ {escape_html(str(exc))}")
        if isinstance(target, CallbackQuery):
            await alert(target, "Qaror saqlanmadi", show=True)
        return False
    if not changed:
        await render_admin_card(target, session, application_id, page)
        if isinstance(target, CallbackQuery):
            await alert(target, "Ariza boshqa admin tomonidan ko'rilgan yoki topilmadi", show=True)
        return False
    assert application is not None
    # Qaror, seller (faqat tasdiqda) va audit atomar commit; DM alohida.
    await session.commit()
    await render_admin_card(target, session, application_id, page)
    if isinstance(target, CallbackQuery):
        await alert(target, "✅ Tasdiqlandi" if approve else "❌ Sabab bilan rad etildi", show=True)
    try:
        await notify_application_result(bot, application_id)
    except Exception:
        logger.exception("Ariza #{} qaror xabari yuborilmadi (qaror DB'da)", application_id)
    return True


@admin_router.callback_query(ApplicationCB.filter(F.action == "approve_confirm"))
async def admin_approve(
    callback: CallbackQuery, callback_data: ApplicationCB, session: AsyncSession, bot: Bot,
) -> None:
    await _decide(callback, session, bot, callback_data.application_id, callback.from_user.id,
                  approve=True, page=callback_data.page)


@admin_router.callback_query(ApplicationCB.filter(F.action == "reject"))
async def admin_reject_preview(
    callback: CallbackQuery, callback_data: ApplicationCB, session: AsyncSession,
) -> None:
    application = await session.get(SellerApplication, callback_data.application_id)
    if application is None or application.status != ApplicationStatus.PENDING:
        await render_admin_card(callback, session, callback_data.application_id, callback_data.page)
        await alert(callback, "Ariza navbatda emas", show=True)
        return
    await render(callback, f"❌ <b>Ariza #{application.id}</b> — rad sababini tanlang.\n"
                 "Sabab foydalanuvchiga yuboriladi va ariza tarixida saqlanadi.",
                 reject_kb(application.id, callback_data.page))
    await alert(callback, "")


@admin_router.callback_query(ApplicationCB.filter(F.action.startswith("reason_")))
async def admin_reject_reason(
    callback: CallbackQuery, callback_data: ApplicationCB, session: AsyncSession, bot: Bot,
) -> None:
    reason = REASONS.get(callback_data.action.removeprefix("reason_"))
    if reason is None:
        await alert(callback, "Noma'lum sabab", show=True)
        return
    await _decide(callback, session, bot, callback_data.application_id, callback.from_user.id,
                  approve=False, reason=reason, page=callback_data.page)


@admin_router.callback_query(ApplicationCB.filter(F.action == "custom"))
async def admin_reject_custom(
    callback: CallbackQuery, callback_data: ApplicationCB, session: AsyncSession, state: FSMContext,
) -> None:
    application = await session.get(SellerApplication, callback_data.application_id)
    if application is None or application.status != ApplicationStatus.PENDING:
        await render_admin_card(callback, session, callback_data.application_id, callback_data.page)
        await alert(callback, "Ariza navbatda emas", show=True)
        return
    await state.set_state(AdminApplicationStates.waiting_reason)
    await state.update_data(application_id=application.id, page=callback_data.page)
    await render(callback, f"❌ Ariza #{application.id} uchun tushunarli sababni yozing (3–500 belgi).\n"
                 "Bekor qilish: /cancel", custom_reason_kb(application.id, callback_data.page))
    await alert(callback, "")


@admin_router.message(StateFilter(AdminApplicationStates.waiting_reason), F.text & ~F.text.startswith("/"))
async def admin_reject_text(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot,
) -> None:
    try:
        reason = application_service.validate_reason(message.text)
    except ApplicationError as exc:
        await message.answer(f"⚠️ {escape_html(str(exc))} Qayta yuboring yoki /cancel.")
        return
    data = await state.get_data()
    application_id = int(data.get("application_id") or 0)
    page = int(data.get("page") or 0)
    if not application_id:
        await state.clear()
        await message.answer("⚠️ Ariza tanlanmagan; navbatga qayting.")
        return
    changed = await _decide(message, session, bot, application_id, message.from_user.id,
                            approve=False, reason=reason, page=page)
    if changed:
        await state.clear()
    else:
        # Admin eski navbat sahifasida qolmasin; qaror qayta ochilmaydi.
        application = await session.get(SellerApplication, application_id)
        if application is None or application.status != ApplicationStatus.PENDING:
            await state.clear()


@admin_router.message(Command("cancel"), StateFilter(AdminApplicationStates))
async def admin_cancel_reason(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await render_admin_list(message, session)
