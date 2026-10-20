# Telegram Scanner

Guruhlardagi xabarlarni berilgan iboralar bo'yicha kuzatib, mos kelgan
mijozlarni adminga yuboradigan tizim: **boshqaruv boti** (aiogram) +
**userbot** (Telethon).

## O'rnatish

```bash
cd telegram_scanner
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # ichini o'z ma'lumotlaringiz bilan to'ldiring
```

`.env` uchun kerak bo'ladi:
- `API_ID` / `API_HASH` — https://my.telegram.org → API development tools
- `BOT_TOKEN` — @BotFather dan
- `ADMIN_ID` — @userinfobot dan olingan shaxsiy ID

## Ishga tushirish (ikkita alohida terminalda)

```bash
.venv/bin/python bot.py      # boshqaruv boti
.venv/bin/python userbot.py  # skaner (1-marta telefon + kod so'raydi)
```

## Replitda ishga tushirish

1. Replitda **Import from GitHub** qiling (yoki shu papkadagi fayllarni yuklang).
2. Chap menyudagi **Secrets (🔒)** bo'limiga quyidagilarni qo'shing —
   kalitlarni kodga yozmang:

   | Secret nomi | Qiymati |
   |---|---|
   | `API_ID` | my.telegram.org dan (faqat raqam) |
   | `API_HASH` | my.telegram.org dan |
   | `BOT_TOKEN` | @BotFather dan |
   | `ADMIN_ID` | @userinfobot dan (faqat raqam) |

3. **Birinchi marta** Shell (terminal) da userbotni alohida ishga tushirib
   Telegramga kiring — telefon raqami, kod (va 2FA parol) so'raladi:

   ```bash
   cd telegram_scanner
   pip install -r requirements.txt
   python userbot.py
   ```

   Kirgach `Ctrl+C` bilan to'xtating — `userbot_session.session` fayli
   saqlanib qoladi, keyingi safar kod so'ralmaydi.
   ⚠️ Bu sessiya faylini hech kimga bermang — u akkauntingiz kaliti.

4. Keyin **Run** tugmasini bosing (`.replit` sozlangan) yoki:

   ```bash
   python main.py
   ```

   `main.py` bot va userbotni bir vaqtda ishlatadi.

Eslatma: Replit bepul tarifida loyiha "uxlab" qolishi mumkin — bot
to'xtab qolmasligi uchun Always On / Reserved VM kerak bo'lishi mumkin.

## Rollar: Admin va foydalanuvchilar (biznes)

- **Admin** (Secrets dagi `ADMIN_ID`, bitta odam): to'liq boshqaruv —
  kalit so'zlar, guruhlar, xabar sharti, tizim stop/start, skaner testi,
  📊 statistika va 👥 foydalanuvchilar paneli.
- **Foydalanuvchilar** (oylik tarif): /start bosib ro'yxatdan o'tadi.
  Ularda boshqaruv tugmalari **bo'lmaydi** — faqat 💳 Tarifim,
  🧾 Chek yuborish, ℹ️ Yordam. Kalitlarni faqat admin kiritadi.
- **Tarif**: foydalanuvchi chek rasmini yuboradi → adminga tugma bilan
  keladi → admin "✅ 30 kunga yoqish" ni bosadi → obuna faollashadi.
  Admin foydalanuvchini istalgan vaqt bloklashi/uzaytirishi mumkin.
- **Tarqatish**: topilgan xabar adminga va tarifi faol (bloklanmagan)
  barcha foydalanuvchilarga alohida-alohida yuboriladi.
- Yangi foydalanuvchi /start bossa, adminga "🆕 Yangi foydalanuvchi"
  xabari boradi.

## Ish tartibi

1. **➕ Guruh qo'shish** tugmasi orqali guruh manzili (`@username`,
   t.me havola) yoki raqamli ID (`-100...`) dan birini yuboring.
   Skaner faqat shu yerda qo'shilgan guruhlarni tekshiradi —
   akkauntdagi barcha guruhlar avtomatik tortib kelinmaydi.
   Userbot akkaunti guruhda a'zo bo'lishi shart: userbot 30 soniya
   ichida tekshirib, "✅ Guruh ulandi" yoki sababi bilan xato xabarini
   yuboradi. Xato bo'lsa 🔄 Qayta tekshirish tugmasi bor.
2. **📋 Guruhlarim** da har bir guruh yonida o'rnini almashtiradigan
   **⏸ To'xtatish / ▶️ Yoqish** tugmasi (skanerni yoqish/o'chirish) va
   **🗑 O'chirish** tugmasi (guruh butunlay o'chib ketadi) bor.
3. **➕ Kalit so'z qo'shish** orqali kalitlar qo'shing. Har bir so'z —
   alohida kalit, kalitlar soni **cheklanmagan**. Bitta xabarda bir
   nechta so'z yuborsangiz, har biri alohida kalit bo'lib saqlanadi.
4. **🔔 Xabar sharti** tugmasida admin bitta son belgilaydi: xabarda
   kalitlardan kamida nechtasi topilsa xabar berilishi. Sonni xohlagan
   vaqtda o'zgartirish mumkin — qayta ishga tushirish shart emas.
5. **🧪 Skaner testi** tugmasi diagnostika uchun: tizim/userbot/guruhlar
   holatini ko'rsatadi va namuna xabarni kalitlarga tekshirib beradi.
   Bildirishnomalar faqat Secrets dagi `ADMIN_ID` ga — shu bot bilan
   bo'lgan shaxsiy chatga keladi, boshqa joyga yuborilmaydi.
   Replit logida `[SCAN]` yozuvlari qaysi bosqichda to'xtaganini,
   `[NOTIFY]` yozuvlari yuborilganini ko'rsatadi.
6. Mos xabar topilsa, bot adminga mijoz ismi, ID, telefoni, topilgan
   kalitlar ro'yxati va asl xabarga havola bilan xabar yuboradi.

### Kalit qanday ishlaydi?

- Har bir so'z = bitta kalit, umumiy kalitlar sonining ahamiyati yo'q.
- Admin belgilagan son (standart: **3**) — xabarda kalitlardan istalgan
  shuncha tasi uchrasa, qaysi kalitlar ekanligidan qat'iy nazar,
  xabar beriladi. Foiz ham, to'plam ham yo'q.

| Kalitlar: `toshkent samarqand odam mashina kerak yuk bugun`, shart: 3 | Natija |
|---|---|
| "Toshkentdan odam bor, mashina kerak" (3+ ta topildi) | ✅ xabar beradi |
| "Toshkentdan odam bor" (2 ta topildi) | ❌ bermaydi |
| "Samarqandga yuk kerak" (3 ta topildi) | ✅ xabar beradi |

Qo'shimcha: so'z tartibi va oradagi so'zlar ahamiyatsiz, katta-kichik
harf/tinish belgilari hisoblanmaydi, so'z shakllari ham taniladi
(`odam` ~ `odamlar`, `toshkent` ~ `toshkentdan`).

Eski bazadagi ko'p so'zli yozuvlar avtomatik ravishda alohida
kalit so'zlarga bo'linadi — ma'lumot yo'qolmaydi.

Maxfiy fayllar (`.env`, `*.db`, `*.session`) `.gitignore` da — ularni
hech qachon gitga qo'shmang.
