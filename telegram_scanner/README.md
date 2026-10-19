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

## Ish tartibi

1. `userbot.py` ishga tushgach, akkaunt a'zo bo'lgan guruhlar bazaga yoziladi.
2. Botda **📋 Guruhlar ro'yxati** dan kuzatiladigan guruhlarni yoqing.
3. **➕ Yangi ibora qo'shish** orqali qidiriladigan gaplarni qo'shing (kamida 2 so'z).
4. Mos xabar topilsa, bot adminga mijoz ismi, ID, telefoni va asl xabarga
   havola bilan xabar yuboradi.

Maxfiy fayllar (`.env`, `*.db`, `*.session`) `.gitignore` da — ularni
hech qachon gitga qo'shmang.
