"""Shaxsiy chatdagi rollarga mos, qisqa foydalanish yo'riqnomalari.

Bu matnlar faqat ishlayotgan imkoniyatlarni tushuntiradi. Oddiy /start
ariza tasdig'ini talab qilmaydi; sotuvchi paneli talab qiladi.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import ApplicationStatus
from app.keyboards.callbacks import AdminCB, ApplicationCB, GuideCB, SellerPanelCB

# Kalit → (tugma, qisqa Telegram HTML matni). Mavjud amallar bilan mos saqlang.
GUIDES: dict[str, dict[str, tuple[str, str]]] = {
    "user": {
        "home": ("📖 Boshlash", (
            "📖 <b>Botdan foydalanish — foydalanuvchi</b>\n\n"
            "1️⃣ /start — bot bilan shaxsiy suhbatni ochadi.\n"
            "2️⃣ E'lonlarni bot ulangan guruhlarda toifalar bo'yicha ko'ring.\n"
            "3️⃣ Guruh N kishi yoki kanal a'zoligi shartini qo'ysa, "
            "/takliflarim orqali holat va shaxsiy havolani ko'ring.\n"
            "4️⃣ Sotuvchi bo'lish uchun «🛒 Sotuvchi bo'lish» arizasini shaxsiy chatda "
            "yuboring. Admin tasdiqlasa sotuvchi paneli ochiladi; tarif, chek va "
            "e'lonlar alohida tekshiriladi. Oddiy /start cheklanmagan.\n\n"
            "/help — buyruqlar · /id — Telegram ID · /xabarlar_stop — ommaviy DMni to'xtatish."
        )),
        "counter": ("🧮 Taklif va kanal", (
            "🧮 <b>Guruh shartlarini bajarish</b>\n\n"
            "/takliflarim → guruhni tanlang → N soni, qolgan takliflar, "
            "shaxsiy havola va kanal holatini tekshiring.\n"
            "Havoladan kelgan a'zo guruhda admin belgilagan muddat qolsa hisoblanadi. "
            "Guruh admini qo'lda qo'shishni ham ruxsat etishi mumkin.\n"
            "📣 Majburiy kanalga obuna N kishini taklif qilishdan <b>alohida shart</b>. "
            "Bot a'zolikni aniqlay olmasa, avtomatik jazo qo'llamaydi.\n\n"
            "A'zolik/to'lov savolida guruh administratoridan yordam so'rang."
        )),
    },
    "seller": {
        "home": ("📖 Boshlash", (
            "📖 <b>Botdan foydalanish — sotuvchi</b>\n\n"
            "/start → kabinet: tarif/muddat, e'lon limiti, e'lonlar va oxirgi chek "
            "holati hamda keyingi qadam. «📅 Mening tarifim»da rasm chegarasi ham bor.\n"
            "«📢 Mening e'lonlarim» tarifsiz ham eski e'lonlarni ko'rsatadi; yangi "
            "e'lon uchun faol tarif va bo'sh limit zarur. «👤 Aloqa ma'lumotlari» "
            "faqat o'zingizga ko'rinadi, tahrir uchun adminga yozing.\n"
            "Tarif yo'q yoki muddati o'tgan bo'lsa, «💳 Tariflarni ko'rish / olish»dan "
            "tarifni tanlang yoki «☎️ Yordam» orqali adminga yozing.\n"
            "Tarif tasdiqlanmaguncha yangi e'lonni yuborib bo'lmaydi.\n\n"
            "Batafsil yo'lni pastdagi tugmalardan tanlang."
        )),
        "ads": ("📢 E'lonlar", (
            "📢 <b>E'lon joylash va boshqarish</b>\n\n"
            "«➕ Yangi e'lon» → toifa → sarlavha → tavsif → narx → "
            "aloqa → rasmlar → ko'rib chiqish → yuborish.\n"
            "Tarifdagi e'lon/rasm chegaralari amal qiladi; bitta albomga "
            "ko'pi bilan 10 rasm. Toifada moderatsiya yoqilgan bo'lsa, "
            "e'lon admin qarorini kutadi.\n"
            "«📢 Mening e'lonlarim»da holatni ko'ring, tahrirlang, "
            "pauza/yoqish yoki tasdiq bilan o'chirish mumkin. "
            "Rad etilsa sababni o'qing, tuzating va qayta yuboring."
        )),
        "payments": ("💳 Tarif va to'lov", (
            "💳 <b>Tarif va chek</b>\n\n"
            "«💳 Tariflarni ko'rish / olish» → faol tarif → ko'rsatilgan "
            "rekvizitga pul o'tkazing → chek rasmini yuboring.\n"
            "«🧾 To'lovlarim»da natijani ko'ring: tekshiruvda, "
            "tasdiqlangan yoki rad etilgan (sababi bilan).\n"
            "<b>Chek obunani o'zi faollashtirmaydi:</b> bank kirimini admin "
            "tasdiqlagandan so'ng tarif beriladi.\n"
            "«🎁 Referal»dagi bonuslar guruh taklif sanoqchisidan alohida; "
            "faqat admin yoqqan shartlarga ko'ra ishlaydi."
        )),
    },
    "admin": {
        "home": ("📖 Boshlash", (
            "📖 <b>Botni boshqarish — admin</b>\n\n"
            "Botga shaxsiy /start yoki /admin yuboring. "
            "Avval test superguruhni ulang, bot huquqlarini tekshiring, "
            "toifa yarating, tarif va sotuvchini sozlang, so'ng test e'lonni tasdiqlang.\n"
            "Guruh qoidalarini <b>har bir guruhda alohida</b> sozlang. "
            "Global kalit faqat umumiy pauza: saqlangan guruh qoidalarini o'zgartirmaydi.\n\n"
            "Quyidagi bo'limlarda amaliy qadamlar bor. Katta amallarni test guruhida sinang."
        )),
        "groups": ("👥 Guruh va post", (
            "👥 <b>Guruh, toifa va joylash</b>\n\n"
            "«👥 Guruhlar» → superguruh → «🔄 Huquqlarni tekshirish»; "
            "botga o'chirish, cheklash va taklif huquqlari kerak. "
            "Telegram Privacy Mode o'chirilgan bo'lsin.\n"
            "«🧩 Funksiyalar»da joylashni yoqing; guruh sozlamalarida interval, "
            "kunlik limit, jitter va tinch soatlarni kiriting. "
            "«🗂 Toifalar»da shu guruhga toifa ulang; unga alohida interval berish mumkin.\n"
            "«📋 E'lonlar navbati»dan tekshiring. «🚀 Hoziroq» — haqiqiy xabar: "
            "faqat sinov guruhida ishlating."
        )),
        "safety": ("🛡 Qoidalar", (
            "🛡 <b>Posbon · tozalovchi · sanoqchi</b>\n\n"
            "Har birida kerakli <b>guruhni tanlang</b> va qoidalarini sozlang. "
            "Global switch, guruh switchi va 🧪 sinov rejimi uch xil daraja.\n"
            "Posbon: havola/so'z, ogohlantirish va jazo. "
            "Tozalovchi: xabar turini, eski e'lon va kechikishni belgilang.\n"
            "Sanoqchi: N kishi, hisob manbalari, minimal qolish va havola; "
            "majburiy kanal sharti alohida yoqiladi. Bot kanal admini bo'lsin.\n"
            "Avval 🧪 jurnalni ko'ring, keyin xavfsiz guruhda 🔴 JONLI tasdiqlang. "
            "Xatoda guruh yoki global switchni pauzalang; boshqa guruhlarga tegmang."
        )),
        "sales": ("🛒 Sotuvchi va chek", (
            "🛒 <b>Tarif · sotuvchi · moderatsiya · to'lov</b>\n\n"
            "«💳 Tariflar»da narx, muddat, e'lon va 10 tagacha rasmni belgilang. "
            "«🛒 Savdo → Arizalar»da ism/aloqani tekshirib, sotuvchilikka qaror bering. "
            "Qo'lda Telegram ID bilan qo'shish ham saqlangan; tarif alohida beriladi.\n"
            "«✅ Moderatsiya»da e'lonni tekshirib tasdiqlang yoki sabab bilan rad eting. "
            "«💰 To'lovlar»da chek va <b>haqiqiy bank kirimini</b> solishtirib tasdiqlang; "
            "chek kelishi o'zi tarif bermaydi.\n"
            "«📣 Broadcast»dan oldin sinov yuboring; ommaviy yuborish alohida tasdiq bilan. "
            "«⚙️ Sozlamalar»da global kalitlar va favqulodda pauzani ko'ring."
        )),
    },
    "moderator": {
        "home": ("📖 Boshlash", (
            "📖 <b>Botni boshqarish — moderator</b>\n\n"
            "Shaxsiy /start yoki /admin orqali panelni oching. "
            "Vazifangiz — «✅ Moderatsiya»da e'lonni ko'rib chiqish.\n"
            "Tarif, to'lov, global sozlama va guruh qoidalarini "
            "faqat admin/super-admin o'zgartiradi.\n"
            "Shubhali e'londa sababni yozing; bank chekini bu ekrandan tasdiqlamang."
        )),
        "moderation": ("✅ Moderatsiya", (
            "✅ <b>E'lonni tekshirish</b>\n\n"
            "«✅ Moderatsiya» → kutilayotgan e'lon → matn, narx, "
            "aloqa va rasmlarni ko'ring. Mos bo'lsa tasdiqlang, "
            "bo'lmasa tayyor yoki qo'lda sabab bilan rad eting.\n"
            "Rad etilganda sotuvchi e'lonni tahrirlab qayta yuborishi mumkin. "
            "Xato yoki yetishmayotgan huquqda admin bilan bog'laning."
        )),
    },
}


def user_start_kb(
    support: str, *, application_status: str | None = None, can_apply: bool = True,
) -> InlineKeyboardMarkup:
    """Oddiy /start va yo'riqnomadan qaytish bir xil, haqiqiy holatga mos."""
    rows: list[list[InlineKeyboardButton]] = []
    if can_apply and application_status in (None, ApplicationStatus.REJECTED):
        rows.append([InlineKeyboardButton(
            text="🛒 Qayta ariza" if application_status else "🛒 Sotuvchi bo'lish",
            callback_data=ApplicationCB(action="new").pack(),
        )])
    if application_status:
        rows.append([InlineKeyboardButton(
            text="📋 Arizam holati", callback_data=ApplicationCB(action="status").pack(),
        )])
    rows += [
        [InlineKeyboardButton(text="📖 Foydalanish yo'riqnomasi", callback_data=GuideCB().pack())],
        [InlineKeyboardButton(text="☎️ Yordam", url=f"https://t.me/{str(support).lstrip('@')}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def guide_kb(profile: str, page: str) -> InlineKeyboardMarkup:
    pages = GUIDES[profile]
    rows: list[list[InlineKeyboardButton]] = []
    if page == "home":
        rows.extend([
            [InlineKeyboardButton(text=title, callback_data=GuideCB(page=key).pack())]
            for key, (title, _) in pages.items() if key != "home"
        ])
    else:
        rows.append([InlineKeyboardButton(text="◀️ Yo'riqnoma bo'limlari", callback_data=GuideCB().pack())])

    if profile in {"admin", "moderator"}:
        back = AdminCB(action="menu").pack()
        label = "🏠 Boshqaruv paneli"
    elif profile == "seller":
        back = SellerPanelCB(action="menu").pack()
        label = "🏠 Sotuvchi paneli"
    else:
        back = GuideCB(page="back").pack()
        label = "🏠 Bosh sahifa"
    rows.append([InlineKeyboardButton(text=label, callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
