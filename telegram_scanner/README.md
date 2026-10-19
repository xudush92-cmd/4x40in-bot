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
   | `MATCH_THRESHOLD` | ixtiyoriy, masalan `0.70` |

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
3. **➕ Yangi ibora qo'shish** orqali qidiriladigan kalitlarni qo'shing.
   Kalit bitta so'z emas — **bir nechta so'zdan iborat ibora** bo'ladi,
   masalan: `toshkentdan odam bor`.
4. Mos xabar topilsa, bot adminga mijoz ismi, ID, telefoni va asl xabarga
   havola bilan xabar yuboradi.

### Kalit qanday ishlaydi? (70% qoidasi)

Kalit — bir nechta so'zdan iborat to'plam (7, 10 ta va h.k.). Kalitdagi
so'zlarning **kamida 70%** i bitta xabarda uchrasa, bot o'xshashlik
foizini ko'rsatib xabar yuboradi:

| Kalit hajmi | Xabar berilishi uchun kerak |
|---|---|
| 7 ta so'z | kamida **5** tasi (71%) |
| 10 ta so'z | kamida **7** tasi (70%) |
| 3 ta so'z | 3 tasi ham (2/3 = 66% < 70%) |
| 2 ta so'z | 2 tasi ham (1/2 = 50% < 70%) |

Chegarani `.env` da `MATCH_THRESHOLD` bilan o'zgartirish mumkin
(masalan `0.80` — qattiqroq, `0.70` — standart).

Qo'shimcha: so'z tartibi va oradagi so'zlar ahamiyatsiz, katta-kichik
harf/tinish belgilari hisoblanmaydi, so'z shakllari ham taniladi
(`odam` ~ `odamlar`, `toshkentdan` ~ `toshkentga`). Bir nechta kalit
mos kelsa — foizi eng yuqorisi yuboriladi.

| Kalit: `toshkentdan samarqandga odam bor mashina kerak ertaga` (7 so'z) | Natija |
|---|---|
| "Toshkentdan odam bor, mashina kerak" (5/7) | ✅ 71% — xabar beradi |
| "Toshkentdan odam bor, mashina bor" (4/7) | ❌ 57% — bermaydi |
| "Toshkentga odamlar bor" (kalitga 3 so'zli misolda) | ✅ so'z shakli taniladi |

Maxfiy fayllar (`.env`, `*.db`, `*.session`) `.gitignore` da — ularni
hech qachon gitga qo'shmang.
