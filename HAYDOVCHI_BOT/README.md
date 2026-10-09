# Haydovchilar boti

Telegram guruhi uchun: haydovchilar yo'nalish, bo'sh joy va telefon raqamini
bitta guruh oynasida ko'rsatadi. Yo'lovchilar faqat oynani o'qiydi va qo'ng'iroq qiladi.

## O'rnatish

1. Botni @BotFather orqali yarating va tokenini oling.
2. Botni guruhga **admin** qiling. Huquqlar: *xabarlarni o'chirish*, *xabarlarni tahrirlash*.
3. BotFather'da `/setprivacy` → **Disable** qiling (bot guruhdagi barcha xabarlarni ko'rishi uchun).
4. `.env` faylini yarating (`.env.example` dan nusxa oling) va to'ldiring.
5. Ishga tushiring:

```bash
cd HAYDOVCHI_BOT
pip install -r requirements.txt
python bot.py
```

6. Testlar: `python -m pytest -q`

## Bir nechta guruh

`.env` da `GROUP_CHAT_IDS` ga guruh ID larini vergul bilan yozing. Har bir guruhda o'z ma'lumot
oynasi bo'ladi. Yo'nalishlar va haydovchilar hamma guruhlar uchun umumiy. Guruh adminlari
o'zi admin bo'lgan guruhlar bo'yicha boshqaruv paneliga kiradi.

> Eski versiyadagi `GROUP_CHAT_ID` ham ishlaydi. Ma'lumotlar bazasi sxemasi o'zgargani uchun
> sinov paytida eski `data/haydovchi.db` faylini o'chiring.

## Obuna (oylik tarif)

- Admin har bir haydovchi uchun obuna muddatini qo'lda belgilaydi: `+30 kun`, `+90 kun` yoki
  aniq sana (YYYY-MM-DD).
- Obuna tugagan haydovchi e'lon bera olmaydi, uning faol e'loni to'xtatiladi.
- Tugashiga 3 kun qolganda haydovchiga ogohlantirish yuboriladi (bir marta).
- Yangi muddat hozirgi tugashidan keyin qo'shiladi.

## Qoidalar

- Haydovchida bir vaqtda faqat **bitta faol yo'nalish** bo'ladi. Yangi yo'nalish boshlansa,
  eskisi avtomatik to'xtaydi.
- Admin yo'nalishni `Toshkent - Qibray` ko'rinishida yozadi. Ajratuvchi sifatida `-`, `–`, `—`,
  `->`, `→`, `/`, `|` ishlaydi. Bir nechta yo'nalishni har birini yangi qatordan yozib, bir
  vaqtda qo'shish mumkin.

## Rollar

- **Super admin** (`ADMIN_ID`) va **guruh adminlari** (Telegram'dagi admin/creator) — boshqaruv paneli:
  yo'nalishlar, haydovchi arizalari, bloklash, sozlamalar, statistika.
  Guruh admini avtomatik aniqlanadi — ro'yxat qo'lda yuritilmaydi.
- **Haydovchi** — botga `/start`, ism, familiya, telefon yuboradi; admin tasdiqlagach
  🟢 Ishni boshlash / 🔴 To'xtatish / bo'sh joy tugmalarini ishlatadi.

## Guruh oynasi qoidalari

- Oyna guruh ichida, pin banner yo'q. Har yo'nalish bo'yicha faol haydovchilar ko'rinadi.
- O'zgarish bo'lsa 30 soniya kutiladi (bir necha o'zgarish bitta yangilanishga yig'iladi).
- Oyna chatning eng oxirgi xabari bo'lsa — **tahrirlanadi** (joyi o'zgarmaydi).
- Oynadan keyin boshqa xabarlar yozilgan bo'lsa — **pastga qayta yuboriladi**, eski nusxa o'chiriladi (jim yuboriladi).
- Ikki qayta yuborish orasi kamida 2 daqiqa. Vaqt bo'yicha tekshiruv sozlamada (10/15/20/30 daqiqa).
- Oyna 40–50 tadan ko'p haydovchida bir nechta xabarga bo'linadi.
- Guruhda `/yangila` (admin) — oynani darhol pastga qayta yuboradi.

## Avtomatik to'xtash

Haydovchi e'lonini belgilangan vaqt (1–4 soat, admin sozlaydi) davomida yangilamasa,
e'lon oynadan olib tashlanadi va haydovchiga xabar yuboriladi.

## Fayllar

| Fayl | Vazifa |
|---|---|
| `bot.py` | Ishga tushirish, fon jarayonlari (avto-to'xtash, davriy tekshiruv) |
| `handlers.py` | Buyruqlar, tugmalar, ro'yxatdan o'tish, admin paneli |
| `board.py` | Guruh oynasini tahrirlash / pastga qayta yuborish mantig'i |
| `db.py` | SQLite (aiosqlite) ma'lumotlar bazasi |
| `utils.py` | Telefon, yo'nalish nomi, oyna matnini bo'lish (sof funksiyalar) |
| `config.py` | `.env` sozlamalari |
| `tests/` | Birlik testlari |
