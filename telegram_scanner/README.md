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
3. **➕ Yangi ibora qo'shish** orqali kalit to'plamlarini qo'shing.
   Har bir so'z — alohida kalit, bitta to'plamda **2–10 ta so'z** bo'ladi,
   masalan: `toshkent samarqand odam mashina kerak yuk bugun`.
   Keyin bot so'raydi: nechta so'z uchrasa xabar beray — **2 ta** yoki **3 ta**.
4. Mos xabar topilsa, bot adminga mijoz ismi, ID, telefoni, topilgan
   so'zlar ro'yxati va asl xabarga havola bilan xabar yuboradi.

### Kalit qanday ishlaydi? (foizsiz — aniq son)

Har bir so'z alohida kalit. Xabarda to'plamdagi so'zlardan
foydalanuvchi belgilagan soni (2 yoki 3 ta) topilsa — xabar beriladi.
Foiz hisoblanmaydi.

| To'plam: `toshkent samarqand odam mashina kerak yuk bugun`, shart: 3 ta | Natija |
|---|---|
| "Toshkentdan odam bor, mashina kerak" (3 ta topildi) | ✅ xabar beradi |
| "Toshkentdan odam bor" (2 ta topildi) | ❌ bermaydi |
| "Samarqandga yuk kerak" (3 ta topildi) | ✅ xabar beradi |

Qo'shimcha: so'z tartibi va oradagi so'zlar ahamiyatsiz, katta-kichik
harf/tinish belgilari hisoblanmaydi, so'z shakllari ham taniladi
(`odam` ~ `odamlar`, `toshkentdan` ~ `toshkentga`). Bir nechta to'plam
mos kelsa — eng ko'p so'zi topilgani yuboriladi.

Maxfiy fayllar (`.env`, `*.db`, `*.session`) `.gitignore` da — ularni
hech qachon gitga qo'shmang.
