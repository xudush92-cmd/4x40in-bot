# Haydovchilar boti

Telegram guruhlari uchun: haydovchilar yo'nalish, ism-familiya, telefon va bo'sh joy sonini
guruh oynasida ko'rsatadi. Yo'lovchi botdan foydalanmaydi — guruh oynasidagi
**🚕 Taksi chaqirish** tugmasini bosadi, so'rov taksi haydovchilarga boradi.

## Tuzilma: jamlanmalar

- **Jamlanma** — haydovchilar to'plami. Nomini super admin beradi, faqat admin yaratadi.
  Yo'nalishlar, haydovchilar, e'lonlar va sozlamalar jamlanma darajasida.
- **Telegram guruh** — jamlanmaga biriktiriladi. Jamlanmada bir nechta guruh bo'lishi mumkin;
  har guruhda o'z oynasi bor, ichida shu jamlanma ma'lumoti chiqadi.
- **Haydovchi** — bitta jamlanmaga biriktiriladi. Boshqa jamlanma haydovchilari ko'rinmaydi.
- Obuna umumiy (haydovchi uchun). Repost hisoblagichi har guruhda o'zinikidir.

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

Eski (har guruh alohida ishlaydigan) `data/haydovchi.db` bo'lsa, bot uni o'chirmasdan avtomatik
yangilaydi: **har bir eski Telegram guruh alohida jamlanmaga aylanadi** (nomi guruh nomi bo'ladi,
bo'sh bo'lsa `Jamlanma N`). Yo'nalish, haydovchi, e'lon, sozlama va taksi tarixi o'z guruhining
jamlanmasida qoladi. Migratsiya bir marta bajariladi; qayta ishga tushirilganda takrorlanmaydi.
Baribir zaxira nusxa olib qo'yish tavsiya etiladi.

## Super admin boshqaruvi (botda)

Guruhlar `.env` ga yozilmaydi — hammasi botdan boshqariladi.

### 🏘 Jamlanmalar

- **➕ Yangi jamlanma** — nomini matn bilan yozasiz. Keyin jamlanma menyusi ochiladi.
- Jamlanma menyusi:
  - **🛣 Yo'nalishlar** — ochish/yopish, o'chirish (Ha/Yo'q), yangi yo'nalish qo'shish
    (`Toshkent - Qibray`, bir nechta bo'lsa har qatorga bittasi).
  - **👥 Haydovchilar** — shu jamlanmaga biriktirilganlar.
  - **📢 E'lonlar** — shu jamlanmadagi hozirgi faol e'lonlar.
  - **🏘 Guruhlar** — Telegram guruhlari ro'yxati:
    - **➕ Guruh qo'shish** — guruhdan xabarni botga **forward** qiling yoki guruh ID sini
      (`-100...`) yozing. Bot o'sha guruhda **admin** bo'lishi shart (xabarlarni o'chirish huquqi bilan).
      Telegram botlar guruh yarata olmaydi — avval guruhni o'zingiz oching.
      Guruh boshqa jamlanmada bo'lsa, avval uni ko'chiring.
    - Guruh menyusi: **🔀 Boshqa jamlanmaga ko'chirish**, **🗑 Jamlanmadan olib tashlash** (Ha/Yo'q).
  - **⚙️ Sozlamalar** — avto-to'xtash (1–4 soat, standart 2), oyna pastga tushish chegarasi
    (3/5/10 yangi xabar, standart 3). Vaqt tanlangach menyu yopiladi.
  - **🚕 Taksi** — jamlanma guruhlaridagi taksi tugmasini yoqish/o'chirish.
  - **⏸ Avtomatikni to'xtatish / ▶️ Davom ettirish** — jamlanma oynalari yangilanishini pauza qilish.
  - **🔄 Oynalarni yangilash** — barcha guruh oynalarini darhol pastga qayta yuborish.
  - **🗑 Jamlanmani o'chirish** (Ha/Yo'q). Yo'nalish, e'lon va guruh oynalari o'chadi; guruhlar
    jamlanmadan ajraladi (Telegram guruhining o'zi qoladi); haydovchilar jamlanmasiz qoladi.

### 👥 Haydovchilar

- **Yangi arizalar** — bitta admin tasdig'i yetarli. Tasdiqlashda haydovchi jamlanmaga biriktiriladi.
- Har haydovchi uchun:
  - **🔀 Jamlanmani o'zgartirish** — boshqa jamlanmaga o'tkazish (eski e'loni to'xtaydi).
  - **📅 Muddat berish** — faqat raqam bilan (masalan `30`). Yangi muddat eskisini bekor qiladi.
  - **⏸ Vaqtincha to'xtatish / ▶️ Ishga tushirish**.
  - **🚫 Bloklash / 🔓 Qayta tiklash** (Ha/Yo'q tasdig'i bilan).
  - Admin haydovchining ismi va telefonini o'zgartira olmaydi.

### 📊 Statistika

Umumiy ko'rsatkichlar va har jamlanma kesimida: guruhlar, yo'nalishlar, faol e'lonlar, taksi so'rovlari.

Har ko'p bosqichli kiritishda **❌ Bekor qilish** tugmasi bor.

## Oyna (guruh ichida)

- Har yo'nalish bo'yicha faol haydovchilar: ism-familiya, **to'liq telefon**, bo'sh joy soni.
  Boshqa ma'lumot yo'q. Pin yo'q. Oyna guruhning pastki qismida turadi.
- 40–50 dan ortiq haydovchida oyna bir nechta xabarga bo'linadi (`(1/2-qism)` sarlavhasi).
- Oynaning tagida tugmalar: **🚕 Taksi chaqirish** (jamlanma sozlamasi yoqilgan bo'lsa) va
  **🚗 Haydovchi bo'lish**.

### Yangilash qoidasi

Skaner **har 30 soniyada** ishlaydi va quyidagilardan biri bo'lsa oynani yangilaydi:

1. Haydovchi ma'lumoti o'zgargan (e'lon, bo'sh joy, ism, telefon, yo'nalish, obuna). O'zgarish bo'lsa darhol.
2. Guruhda jamlanma sozlamasidagi miqdorda (standart 3) yangi xabar yozilgan.

Hech qanday o'zgarish va yetarli yangi xabar bo'lmasa — yangilanmaydi.

- Oyna guruhning **eng oxirgi** xabari bo'lsa — tahrirlanadi (joyi o'zgarmaydi).
- Boshqa xabarlar tushgan bo'lsa — **pastga qayta yuboriladi**, eski nusxa o'chiriladi
  (jim, ya'ni bildirishnomasiz).
- Jamlanma **⏸ to'xtatilgan** bo'lsa, avtomatik yangilanmaydi; qo'lda 🔄 orqali yangilash mumkin.

## Haydovchi

- `/start` → ism, familiya, telefon (**📱 Raqamni yuborish** tugmasi yoki matn bilan).
- Admin tasdiqlab jamlanmaga biriktirgach menyu: **🟢 Ishni boshlash**, **🔴 To'xtatish**,
  **📋 Mening holatim**, **✏️ Ma'lumotlarim**.
- Faqat o'z jamlanmasining yo'nalishlarida e'lon beradi. Bir vaqtda faqat **bitta faol yo'nalish** bo'ladi.
- Bo'sh joy 0–8. **📋 Mening holatim** ichida ➖ / ➕ / 🔢 / 🔴 tugmalari bilan o'zgartiriladi.
- **✏️ Ma'lumotlarim** — ism, familiya, telefon (faqat o'zi tahrirlaydi), taksi so'rovlarini yoqish/o'chirish.
- Har ekranda **⬅️ Orqaga** bor; menyuda joriy holat (jamlanma, muddat) matnda ko'rinadi.
- Muddat tugasa yoki admin to'xtatsa, e'lonlari oynadan olib tashlanadi va xabar yuboriladi.

## Yo'lovchi va taksi chaqirish

- Yo'lovchi botdan foydalanmaydi (botga yozish, telefon so'ralmaydi). Guruh oynasi ostidagi
  **🚕 Taksi chaqirish** tugmasini bosadi.
- So'rov yo'lovchi bosgan guruhning **jamlanmasidagi** faol e'loni bor va taksi yoqqan haydovchilarga boradi.
  Haydovchiga shaxsiy xabar: yo'lovchi ismi, @username, vaqt. Tugmalar: **👤 Bog'lanish** va
  **🔕 So'rovlarni to'xtatish**.
- Yo'lovchiga qisqa javob: "✅ So'rov taksi haydovchilariga yuborildi" yoki "Hozir faol taksi haydovchi yo'q".
- **🔕 So'rovlarni to'xtatish** bosilsa, haydovchiga taksi so'rovlari kelmaydi. Qayta yoqish:
  **✏️ Ma'lumotlarim → 🚕 Taksi so'rovlari**.
- Spamdan himoya: bir yo'lovchi jamlanmada 3 daqiqada bir marta so'rov yuboradi.

## Avtomatik to'xtash va obuna tekshiruvi

- Haydovchi e'lonini jamlanmaning avto-to'xtash vaqti (1–4 soat) davomida yangilamasa,
  e'lon to'xtatiladi va haydovchiga xabar yuboriladi.
- Obuna tugashiga 3 kun qolganda haydovchiga bir marta ogohlantirish yuboriladi.
- Har daqiqa tekshiriladi.

## Fayllar

| Fayl | Vazifa |
|---|---|
| `bot.py` | Ishga tushirish, 30 soniyalik skaner, daqiqalik tekshiruv (avto-to'xtash, obuna) |
| `handlers.py` | Buyruqlar, tugmalar, ro'yxatdan o'tish, boshqaruv paneli (jamlanmalar), guruh xabarlari |
| `board.py` | Guruh oynasi: tahrirlash yoki pastga qayta yuborish, eski nusxani o'chirish |
| `taxi.py` | Yo'lovchi taksi so'rovi, spam cheklovi, haydovchi to'xtatish tugmasi |
| `db.py` | SQLite (aiosqlite): jamlanmalar, guruhlar, haydovchilar; eski bazadan bir martalik migratsiya |
| `utils.py` | Telefon, yo'nalish nomi, oyna matnini bo'lish (sof funksiyalar) |
| `config.py` | `.env` sozlamalari |
| `tests/` | Birlik testlari |
