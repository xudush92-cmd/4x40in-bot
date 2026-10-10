# Haydovchilar boti

Telegram guruhlari uchun: haydovchilar yo'nalish, ism-familiya, telefon va bo'sh joy sonini
bitta guruh oynasida ko'rsatadi. Yo'lovchilar botdan foydalanmaydi — faqat oynani o'qiydi va
haydovchiga qo'ng'iroq qiladi.

## O'rnatish

1. Botni @BotFather orqali yarating va tokenini oling.
2. BotFather'da `/setprivacy` → **Disable** qiling (bot guruhdagi xabarlarni sanashi uchun).
3. `.env` faylini yarating (`.env.example` dan nusxa oling) va `BOT_TOKEN`, `ADMIN_ID` ni to'ldiring.
4. Ishga tushiring:

```bash
cd HAYDOVCHI_BOT
pip install -r requirements.txt
python bot.py
```

5. Testlar: `python -m pytest -q`

> Ma'lumotlar bazasi sxemasi o'zgargani uchun, eski `data/haydovchi.db` bo'lsa o'chiring.

## Guruhlarni boshqarish

Guruhlarni `.env` ga yozish shart emas. Faqat super admin (`ADMIN_ID`) botda
**🏘 Guruhlar** bo'limidan boshqaradi:

- **➕ Yangi guruh** — Telegram botlar guruh yarata olmaydi. Avval Telegram'da guruh oching,
  botni **admin** qiling (xabarlarni o'chirish huquqi bilan), so'ng botga guruhdan xabar
  **forward** qiling yoki guruh ID sini (`-100...`) yozing.
- Har guruh alohida: `1-guruh`, `2-guruh`... Tafsilotda: holat, oxirgi yangilanish,
  shundan beri kelgan xabarlar soni.
  - **🔄 Hozir yangilash** — oynani darhol pastga qayta yuboradi.
  - **⏸ To'xtatish / ▶️ Davom ettirish** — vaqtincha avtomatik yangilanishni to'xtatadi.
  - **🗑 Olib tashlash** (Ha/Yo'q tasdig'i bilan) — guruhni ro'yxatdan chiqaradi va oynasini o'chiradi.

Barcha belgilangan guruhlarda **bir xil** oyna chiqadi.
`GROUP_CHAT_IDS` (`.env`) ixtiyoriy: bot ishga tushganda shu guruhlar bazaga qo'shiladi.

## Oyna (guruh ichida)

- Har yo'nalish bo'yicha faol haydovchilar: ism-familiya, to'liq telefon, bo'sh joy soni.
  Boshqa ma'lumot yo'q. Pin banner yo'q.
- Oyna 40–50 dan ortiq haydovchida bir nechta xabarga bo'linadi (`(1/2-qism)` sarlavhasi).
- Oynaning pastida "🚗 Haydovchi bo'lish" tugmasi bor (botga o'tkazadi).

### Yangilash qoidasi

Skaner **har 30 soniyada** ishlaydi va quyidagilardan biri bo'lsa oynani yangilaydi:

1. Haydovchi ma'lumoti o'zgargan (e'lon, bo'sh joy, ism, telefon, yo'nalish, obuna) — o'zgarish bo'lsa darhol.
2. Guruhda **3 yoki undan ko'p** yangi xabar yozilgan (bu son sozlamada 3/5/10).

Hech qanday o'zgarish va yetarli yangi xabar bo'lmasa — yangilanmaydi.

- Oyna chatning **eng oxirgi** xabari bo'lsa — tahrirlanadi (joyi o'zgarmaydi).
- Boshqa xabarlar tushgan bo'lsa — **pastga qayta yuboriladi**, eski nusxa o'chiriladi
  (jim, ya'ni bildirishnomasiz).

## Rollar

### Boshqaruv paneli (faqat super admin)

- Boshqaruv faqat super admin (`ADMIN_ID`) uchun. Guruh adminlari botda boshqaruv huquqiga ega emas.
- Guruhda `/yangila` buyrug'i ham faqat super admin uchun ishlaydi.
- **🛣 Yo'nalishlar** — qo'shish (`Toshkent - Qibray`), ochish/yopish, o'chirish (Ha/Yo'q).
  Ajratuvchi sifatida `-`, `–`, `—`, `->`, `→`, `/`, `|` ishlaydi.
  Yo'nalish yopilsa, uning e'lonlari to'xtaydi.
- **👥 Haydovchilar** — yangi arizalar (bitta admin tasdig'i yetarli), faol/to'xtatilgan/bloklangan
  ro'yxati. Har haydovchi uchun:
  - **📅 Muddat berish** — admin muddatni faqat raqam bilan yozadi (masalan `30`).
    Yangi muddat eskisini bekor qiladi. Muddat tugasa haydovchi ishlay olmaydi.
  - **⏸ Vaqtincha to'xtatish / ▶️ Ishga tushirish** — qaytariladi.
  - **🚫 Bloklash / 🔓 Qayta tiklash** (Ha/Yo'q tasdig'i bilan).
  - Admin haydovchining ismi va telefonini o'zgartira olmaydi.
- **🏘 Guruhlar** — yuqoridagi "Guruhlarni boshqarish" bo'limi.
- **⚙️ Sozlamalar** — avtomatik to'xtash (1–4 soat, tavsiya 2) va oyna pastga tushish chegarasi (3/5/10 xabar).
  Tanlangach menyu yopiladi.
- **📊 Statistika** — haydovchilar, yo'nalishlar, faol e'lonlar, guruhlar soni.
- Har bir ko'p bosqichli kiritishda **❌ Bekor qilish** tugmasi bor.

### Haydovchi

- `/start` → ism, familiya, telefon (**📱 Raqamni yuborish** tugmasi yoki matn bilan).
- Admin tasdiqlagach menyu: **🟢 Ishni boshlash**, **🔴 To'xtatish**, **📋 Mening holatim**, **✏️ Ma'lumotlarim**.
- Bir vaqtda faqat **bitta faol yo'nalish** bo'ladi. Yangisini boshlasangiz, eskisi to'xtaydi.
- Bo'sh joy 0–8. **📋 Mening holatim** ichida ➖ / ➕ / 🔢 / 🔴 tugmalari bilan o'zgartiriladi.
- **✏️ Ma'lumotlarim** — ismni, familiyani va telefonni faqat haydovchining o'zi tahrirlaydi
  (telefon 📱 kontakt tugmasi orqali).
- Har ekranda **⬅️ Orqaga** bor; menyuda joriy holat matnda ko'rinadi.
- Muddat tugasa yoki admin to'xtatsa, e'lonlari oynadan olib tashlanadi va xabar yuboriladi.

## Avtomatik to'xtash va obuna tekshiruvi

- Haydovchi e'lonini belgilangan vaqt (1–4 soat, admin sozlaydi) davomida yangilamasa,
  e'lon to'xtatiladi va haydovchiga xabar yuboriladi.
- Obuna tugashiga 3 kun qolganda haydovchiga bir marta ogohlantirish yuboriladi.
- Har daqiqa tekshiriladi.

## Fayllar

| Fayl | Vazifa |
|---|---|
| `bot.py` | Ishga tushirish, 30 soniyalik skaner, daqiqalik tekshiruv (avto-to'xtash, obuna) |
| `handlers.py` | Buyruqlar, tugmalar, ro'yxatdan o'tish, boshqaruv paneli, guruh xabarlari |
| `board.py` | Guruh oynasi: tahrirlash yoki pastga qayta yuborish, eski nusxani o'chirish |
| `db.py` | SQLite (aiosqlite) ma'lumotlar bazasi |
| `utils.py` | Telefon, yo'nalish nomi, oyna matnini bo'lish (sof funksiyalar) |
| `config.py` | `.env` sozlamalari |
| `tests/` | Birlik testlari |
