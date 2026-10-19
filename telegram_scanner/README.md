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

## Ish tartibi

1. `userbot.py` ishga tushgach, akkaunt a'zo bo'lgan guruhlar bazaga yoziladi.
2. Botda **📋 Guruhlar ro'yxati** dan kuzatiladigan guruhlarni yoqing.
3. **➕ Kalit so'z qo'shish** orqali kalitlar qo'shing. Har bir so'z —
   alohida kalit, kalitlar soni **cheklanmagan**. Bitta xabarda bir
   nechta so'z yuborsangiz, har biri alohida kalit bo'lib saqlanadi.
4. **🔔 Xabar sharti** tugmasida admin bitta son belgilaydi: xabarda
   kalitlardan kamida nechtasi topilsa xabar berilishi. Sonni xohlagan
   vaqtda o'zgartirish mumkin — qayta ishga tushirish shart emas.
5. Mos xabar topilsa, bot adminga mijoz ismi, ID, telefoni, topilgan
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
