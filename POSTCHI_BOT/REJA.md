# 📮 POSTCHI_BOT — Loyiha rejasi (spetsifikatsiya)

> Bu hujjat — loyiha rejasi. Hali kod yozilmagan. Kelajakda loyihani
> boshlaganda shu hujjatdan foydalaniladi.

---

## 1. Umumiy g'oya

POSTCHI_BOT — viloyatlar bo'yicha e'lon tarqatuvchi Telegram bot.

```
Bot begona guruhlarga ADMIN qilinadi
        ↓
Guruhlar viloyatlar bo'yicha guruhlanadi
        ↓
Foydalanuvchi: viloyat tanlaydi + e'lon yozadi + boshlaydi
        ↓
Bot O'SHA viloyat guruhlariga e'lonni interval bilan yuboradi
```

**Eng katta texnik yutuq:** foydalanuvchi hisobi (Telethon) ISHLATILMAYDI.
Faqat **Bot API**. Demak login, kod, 2FA, sessiya — hech qaysisi yo'q.
E'lonni **botning o'zi** yuboradi.

---

## 2. Rollar (3 xil)

| Rol | Kim | Nima qiladi |
|-----|-----|-------------|
| 👑 Super admin | Loyiha egasi | Hamma narsani boshqaradi |
| 🏢 Guruh egasi | Botni o'z guruhiga admin qilgan odam | O'z guruhi statistikasi + vaqtincha to'xtatish |
| 👤 Foydalanuvchi | E'lon beruvchi | Viloyat tanlaydi, e'lon beradi |

Bir odam bir vaqtning o'zida **uchala rolda** ham bo'lishi mumkin —
bot rolga qarab mos panelni ko'rsatadi.

---

## 3. 👑 SUPER ADMIN paneli

### 3.1. 🗺 Viloyatlar
- ➕ Viloyat qo'shish (nom so'raydi → bazaga qo'shadi)
- 📋 Viloyatlar ro'yxati (har birida nechta guruh borligi)
- ✏️ Viloyat nomini o'zgartirish
- 🗑 Viloyatni o'chirish

### 3.2. 👥 Guruhlar
- 📋 Barcha guruhlar (nom, viloyat, holat, interval)
- 🔄 Biriktirilmaganlar (bot admin bo'lgan, lekin viloyatsiz)
- 🏷 Viloyatga biriktirish + interval belgilash
- 🔀 Viloyatni o'zgartirish
- ⏱ Intervalni o'zgartirish (sozlanadi)
- 🗑 Guruhni o'chirish
- 📊 Guruh holati (bot admin mi, oxirgi yuborish)

**Avtomatik:** bot guruhga admin qilinsa → `my_chat_member` hodisasi
orqali bot sezadi → super adminga so'rov keladi:
```
🔔 Yangi guruhga admin qilindim!
📛 Nomi: [guruh nomi]
👥 A'zolar: [son]
🆔 ID: [id]
Qaysi viloyatga biriktiramiz?
[Toshkent] [Samarqand] [Farg'ona] ...
        ↓
Viloyat tanlanadi → interval so'raladi → guruh qo'shiladi
```

### 3.3. 👤 Foydalanuvchilar
- 📋 Ro'yxat (ism, telefon, holat)
- ⏳ Tasdiq kutayotganlar
- ✅ Tasdiqlash
- 🚫 Bloklash
- 🗑 O'chirish

### 3.4. 📊 Statistika
- Jami guruhlar (viloyat bo'yicha)
- Faol e'lonlar soni
- Bugun/jami yuborilgan e'lonlar
- Faol foydalanuvchilar soni

### 3.5. ⚙️ Sozlamalar
- Yuborish tezligi (guruhlar orasidagi kutish, flood himoya)
- Standart interval = **10 daqiqa** (admin guruhga interval bermasa)

---

## 4. 🏢 GURUH EGASI paneli

Guruh egasi = botni o'z guruhiga admin qilgan odam.
Bot `my_chat_member` orqali kim qilganini eslab qoladi.

- 📋 Mening guruhlarim (ro'yxat)
- 📊 Faqat **O'Z GURUHI** statistikasi:
  - Bugun/jami yuborilgan e'lonlar
  - Nechta foydalanuvchi shu guruhga e'lon beryapti
  - Viloyati, interval
- ⏸ Guruhni vaqtincha TO'XTATISH (e'lon yuborish pauza)
- ▶️ Qayta yoqish

> Guruh egasi faqat o'z guruhini ko'radi va to'xtatadi.
> Boshqa guruhlar yoki butun viloyat statistikasini KO'RMAYDI.

---

## 5. 👤 FOYDALANUVCHI paneli

### 5.1. Ro'yxatdan o'tish (login YO'Q!)
```
1. /start
2. Bot: "Ismingizni kiriting"
3. Ism yoziladi
4. Bot: "Telefon raqamingizni yuboring" [📱 tugma]
5. Telefon yuboriladi (MAJBURIY — admin bog'lanishi uchun)
6. Super adminga tasdiq so'rovi keladi
7. Admin tasdiqlaydi → menyu ochiladi
```
> Kod yo'q, 2FA yo'q, sessiya yo'q. Faqat ism + telefon + tasdiq.

### 5.2. Menyu
- 📢 E'lonlarim (5 tagacha saqlanadi)
  - ➕ E'lon qo'shish (matn yoki rasm+matn)
  - ✏️ E'lonni o'zgartirish
  - 🗑 E'lonni o'chirish
  - ✅ Faol e'lonni tanlash (5 tadan bittasi)
- 🗺 Viloyat tanlash (BITTA viloyat)
- ▶️ Boshlash (faol e'lon → tanlangan viloyatga ketadi)
- ⛔ To'xtatish
- 📊 Holat (qaysi e'lon, qaysi viloyat, ishlayaptimi)
- 📈 Statistika (e'lon qaysi guruhlarga yetib bordi)
- 👥 Referal
- 🚪 Chiqish

### 5.3. Oqim
```
E'lon yozadi (5 tagacha saqlanadi)
        ↓
Bog'lanish kontaktini kiritadi (@username yoki +998...)
        ↓
Bittasini FAOL qiladi
        ↓
Viloyat tanlaydi
        ↓
▶️ Boshlash
        ↓
Bot faol e'lonni o'sha viloyat guruhlariga
har guruh O'Z intervali bilan yuboradi
```
Keyin foydalanuvchi boshqa e'lon + boshqa viloyat tanlashi mumkin.
Bir vaqtda BITTA e'lon + BITTA viloyat faol.

### 5.4. E'lon ostidagi tugmalar (avtomatik)

Bot guruhlarga e'lonni yuborganda, ostiga AVTOMATIK 2 ta inline
tugma qo'shiladi:

```
┌─────────────────────────────────────┐
│   [E'lon matni / rasmi]              │
├─────────────────────────────────────┤
│  [📞 Bog'lanish]  [📢 E'lon berish]  │
└─────────────────────────────────────┘
```

| Tugma | Vazifasi |
|-------|----------|
| 📞 Bog'lanish | E'lon beruvchi e'lon berishda KIRITGAN kontaktiga olib boradi (@username yoki tel raqam). Har e'londa alohida kontakt. |
| 📢 E'lon berish | Botga olib kiradi REFERAL havola bilan: `https://t.me/POSTCHI_BOT?start=ref_<uid>`. Kim shu tugma orqali kirib ro'yxatdan o'tsa — e'lon beruvchining referali bo'ladi. |

> MUHIM texnik nuqta: POSTCHI_BOT e'lonni BOTNING O'ZI yuboradi (Bot API),
> shuning uchun inline tugmalar TO'LIQ ishlaydi. (AVTO_BOT da user account
> orqali tugma yuborib bo'lmasdi — bu yerda bunday cheklov yo'q.)

- Bog'lanish kontakti har e'lon uchun alohida saqlanadi (elonlar jadvalida)
- Tugmalar har doim avtomatik qo'shiladi (foydalanuvchi alohida sozlamaydi)

---

## 6. Asosiy qoidalar

| Qoida | Qiymat |
|-------|--------|
| Interval | Admin HAR GURUHGA alohida belgilaydi (sozlanadi) |
| Standart interval | 10 daqiqa |
| Foydalanuvchi interval | Belgilamaydi (admin ishi) |
| Saqlanadigan e'lon | 5 ta (1 tasi faol) |
| Viloyat tanlash | Bitta |
| Telefon | Majburiy |
| Moderatsiya | Yo'q — e'lon to'g'ridan-to'g'ri ketadi |
| Yuborish | Interval bilan qayta-qayta |
| Flood himoya | Guruhlar orasida kutish (3-5s) |

---

## 7. Baza tuzilishi (taxminiy)

```
viloyatlar
  - id
  - nom

guruhlar
  - id
  - guruh_id (Telegram chat id)
  - nom
  - viloyat_id
  - interval_min (default 10)
  - egasi_uid (kim admin qilgan)
  - faolmi (bot hali admin mi)
  - pauza (guruh egasi to'xtatganmi)

userlar
  - uid
  - ism
  - telefon
  - rol (foydalanuvchi/guruh_egasi)
  - tasdiqlangan
  - bloklangan
  - tanlangan_viloyat_id
  - faol_elon_id

elonlar
  - id
  - uid
  - matn
  - rasm
  - kontakt (bog'lanish — @username yoki +998...)
  - tartib (1-5)

yuborish_log (statistika uchun)
  - id
  - elon_id
  - guruh_id
  - vaqt
  - holat (ok/xato)
```

---

## 8. Texnik arxitektura (modullar)

```
bot.py            — asosiy bot, handlerlar, menyu
database.py       — SQLite storage
group_tracker.py  — my_chat_member hodisasi (admin bo'lish/chiqarilish)
sender.py         — e'lonni guruhlarga yuborish (flood himoya)
worker.py         — interval bilan qayta yuborish (har guruh o'z intervali)
rate_limiter.py   — anti-spam (AVTO_BOT dan olinadi)
health.py         — monitoring (ixtiyoriy)
```

**Texnologiyalar:**
- python-telegram-bot (faqat Bot API)
- aiosqlite (SQLite WAL)
- Telethon KERAK EMAS

---

## 9. Muhim himoya mexanizmlari

1. **Flood himoya** — guruhlar orasida 3-5s kutish (Telegram limiti)
2. **Guruh sog'ligi** — bot chiqarilsa → avtomatik nofaol
3. **Admin huquqi olib tashlansa** — sezadi → super adminga xabar
4. **Xato bardoshlilik** — bitta guruh xato bersa, qolganlarga yuboradi
5. **Restart tiklanish** — bot qayta ishga tushsa, faol e'lonlar tiklanadi
6. **Bir guruh ikki marta qo'shilmaydi** — bazada borligi tekshiriladi

---

## 10. Aniqlangan qarorlar (yakuniy)

| # | Jihat | Qaror |
|---|-------|-------|
| 1 | Guruhlar | Begona |
| 2 | Bot roli | Admin bo'ladi |
| 3 | Hudud | Barcha viloyatlar |
| 4 | Loyiha | Yangi (POSTCHI_BOT) |
| 5 | Guruh qo'shish | Avtomatik aniqlash + admin viloyat tanlaydi |
| 6 | Moderatsiya | Yo'q |
| 7 | Viloyat tanlash | Bitta |
| 8 | Yuborish | Interval bilan qayta-qayta |
| 9 | Tarif | KERAK EMAS (hamma teng) |
| 10 | Interval | Admin har guruhga alohida + sozlanadi (default 10 daq) |
| 11 | E'lonlar | 5 ta saqlanadi, 1 tasi faol |
| 12 | Telefon | Majburiy |
| 13 | Login/2FA | YO'Q (faqat Bot API) |
| 14 | Guruh egasi paneli | Faqat o'z guruhi statistikasi + vaqtincha to'xtatish |
| 15 | E'lon ostidagi tugmalar | Avtomatik: 📞 Bog'lanish (kontakt) + 📢 E'lon berish (referal) |
| 16 | Bog'lanish kontakti | Foydalanuvchi e'lon berishda kiritadi (har e'longa alohida) |
