# Haydovchilar boti

Telegram guruhlari uchun: haydovchilar yo'nalish, ism-familiya, telefon va bo'sh joy sonini
guruh oynasida ko'rsatadi. Yo'lovchi botdan foydalanmaydi — guruh oynasidagi
**🚕 Taksi chaqirish** tugmasini bosadi, so'rov taksi haydovchilarga boradi.

## O'rnatish

1. Botni @BotFather orqali yarating va tokenini oling.
2. BotFather'da `/setprivacy` → **Disable** qiling (bot guruhdagi xabarlarni sanashi uchun).
3. `.env` faylini yarating (`.env.example` dan nusxa oling). `BOT_TOKEN` va `ADMIN_ID` shart.
4. Ishga tushiring:

```bash
cd HAYDOVCHI_BOT
pip install -r requirements.txt
python bot.py
```

5. Testlar: `python -m pytest -q`

### Eski baza bilan ishlash

Eski (guruhsiz versiyadan) `data/haydovchi.db` bo'lsa, bot uni o'chirmasdan avtomatik yangilaydi:
eski yo'nalishlar, haydovchilar va sozlamalar birinchi guruhga ko'chiriladi. Baribir zaxira nusxa
olib qo'yish tavsiya etiladi.

## Guruhlar — har biri alohida

Guruhlarni `.env` ga yozish shart emas. Super admin botda **🏘 Guruhlar** bo'limidan boshqaradi.

- **➕ Yangi guruh** — Telegram botlar guruh yarata olmaydi. Avval Telegram'da guruh oching,
  botni **admin** qiling (xabarlarni o'chirish huquqi bilan), so'ng botga guruhdan xabar
  **forward** qiling yoki guruh ID sini (`-100...`) yozing.
- Har guruh (`1-guruh`, `2-guruh`...) menyusida:
  - **🛣 Yo'nalishlar** — shu guruhniki. Ochish/yopish, o'chirish.
  - **👥 Haydovchilar** — shu guruhga biriktirilganlar.
  - **📢 E'lonlar** — shu guruhdagi hozirgi faol e'lonlar.
  - **⚙️ Sozlamalar** — avto-to'xtash (1–4 soat, tavsiya 2), oyna pastga tushish chegarasi (3/5/10 xabar).
  - **🚕 Taksi** — guruh oynasida taksi tugmasini yoqish/o'chirish.
  - **🔄 Oynani yangilash**, **⏸ To'xtatish / ▶️ Davom ettirish**, **🗑 Olib tashlash** (Ha/Yo'q bilan).

`GROUP_CHAT_IDS` (`.env`) ixtiyoriy: bot ishga tushganda shu guruhlar bazaga qo'shiladi.

## Oyna (guruh ichida)

- Har yo'nalish bo'yicha faol haydovchilar: ism-familiya, to'liq telefon, bo'sh joy soni.
  Boshqa ma'lumot yo'q. Pin banner yo'q.
- 40–50 dan ortiq haydovchida oyna bir nechta xabarga bo'linadi (`(1/2-qism)` sarlavhasi).
- Oynaning tagida tugmalar: **🚕 Taksi chaqirish** (guruh sozlamasi yoqilgan bo'lsa) va
  **🚗 Haydovchi bo'lish**.

### Yangilash qoidasi

Skaner **har 30 soniyada** ishlaydi va quyidagilardan biri bo'lsa oynani yangilaydi:

1. Haydovchi ma'lumoti o'zgargan (e'lon, bo'sh joy, ism, telefon, yo'nalish, obuna). O'zgarish bo'lsa darhol.
2. Guruhda guruh sozlamasidagi miqdorda (standart 3) yangi xabar yozilgan.

Hech qanday o'zgarish va yetarli yangi xabar bo'lmasa — yangilanmaydi.

- Oyna guruhning **eng oxirgi** xabari bo'lsa — tahrirlanadi (joyi o'zgarmaydi).
- Boshqa xabarlar tushgan bo'lsa — **pastga qayta yuboriladi**, eski nusxa o'chiriladi
  (jim, ya'ni bildirishnomasiz).

## Rollar

### Super admin (`ADMIN_ID`)

- Yagona boshqaruvchi. Guruh adminlari botda boshqaruv huquqiga ega emas.
- **🏘 Guruhlar** — yuqoridagi "Guruhlar" bo'limi.
- **👥 Haydovchilar** — yangi arizalar (bitta admin tasdig'i yetarli). Tasdiqlashda haydovchi
  guruhga biriktiriladi. Har haydovchi uchun:
  - **🔀 Guruhni o'zgartirish** — boshqa guruhga o'tkazish (eski e'loni to'xtaydi).
  - **📅 Muddat berish** — admin muddatni faqat raqam bilan yozadi (masalan `30`).
    Yangi muddat eskisini bekor qiladi. Muddat tugasa haydovchi ishlay olmaydi.
  - **⏸ Vaqtincha to'xtatish / ▶️ Ishga tushirish** — qaytariladi.
  - **🚫 Bloklash / 🔓 Qayta tiklash** (Ha/Yo'q tasdig'i bilan).
  - Admin haydovchining ismi va telefonini o'zgartira olmaydi.
- **📊 Statistika** — umumiy va guruhlar kesimida.
- Har ko'p bosqichli kiritishda **❌ Bekor qilish** tugmasi bor.

### Haydovchi

- `/start` → ism, familiya, telefon (**📱 Raqamni yuborish** tugmasi yoki matn bilan).
- Admin tasdiqlab guruhga biriktirgach menyu: **🟢 Ishni boshlash**, **🔴 To'xtatish**,
  **📋 Mening holatim**, **✏️ Ma'lumotlarim**.
- Faqat o'z guruhining yo'nalishlarida e'lon beradi. Bir vaqtda faqat **bitta faol yo'nalish** bo'ladi.
- Bo'sh joy 0–8. **📋 Mening holatim** ichida ➖ / ➕ / 🔢 / 🔴 tugmalari bilan o'zgartiriladi.
- **✏️ Ma'lumotlarim** — ism, familiya, telefon (faqat o'zi tahrirlaydi), taksi so'rovlarini yoqish/o'chirish.
- Har ekranda **⬅️ Orqaga** bor; menyuda joriy holat matnda ko'rinadi.
- Muddat tugasa yoki admin to'xtatsa, e'lonlari oynadan olib tashlanadi va xabar yuboriladi.

### Yo'lovchi

- Botdan foydalanmaydi. Guruh oynasi ostidagi **🚕 Taksi chaqirish** tugmasini bosadi.

## Taksi chaqirish

1. Yo'lovchi tugmani bosadi (botga yozish shart emas, telefon so'ralmaydi).
2. Guruhda hozir **faol e'loni bor** va **taksi so'rovlarini olayotgan** haydovchilarga xabar boradi:
   yo'lovchining ismi, @username, guruh nomi, vaqt. Tugmalar: **👤 Bog'lanish** va
   **🔕 So'rovlarni to'xtatish**.
3. **🔕 So'rovlarni to'xtatish** bosilsa, haydovchiga taksi so'rovlari kelmaydi. Qayta yoqish:
   **✏️ Ma'lumotlarim → 🚕 Taksi so'rovlari**.
4. Spamdan himoya: bir yo'lovchi har guruhda 3 daqiqada bir marta so'rov yubora oladi.

## Avtomatik to'xtash va obuna tekshiruvi

- Haydovchi e'lonini guruhning avto-to'xtash vaqti (1–4 soat) davomida yangilamasa,
  e'lon to'xtatiladi va haydovchiga xabar yuboriladi.
- Obuna tugashiga 3 kun qolganda haydovchiga bir marta ogohlantirish yuboriladi.
- Har daqiqa tekshiriladi.

## Fayllar

| Fayl | Vazifa |
|---|---|
| `bot.py` | Ishga tushirish, 30 soniyalik skaner, daqiqalik tekshiruv (avto-to'xtash, obuna) |
| `handlers.py` | Buyruqlar, tugmalar, ro'yxatdan o'tish, boshqaruv paneli, guruh xabarlari |
| `board.py` | Guruh oynasi: tahrirlash yoki pastga qayta yuborish, eski nusxani o'chirish |
| `taxi.py` | Yo'lovchi taksi so'rovi, spam cheklovi, haydovchi to'xtatish tugmasi |
| `db.py` | SQLite (aiosqlite) ma'lumotlar bazasi, eski bazadan avtomatik migratsiya |
| `utils.py` | Telefon, yo'nalish nomi, oyna matnini bo'lish (sof funksiyalar) |
| `config.py` | `.env` sozlamalari |
| `tests/` | Birlik testlari |
