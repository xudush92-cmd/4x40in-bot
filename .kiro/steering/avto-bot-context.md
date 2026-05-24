# AVTO BOT — Loyiha konteksti

## Repo va branch
- Repo: xudush92-cmd/4x40in-bot
- Branch: feat/avto-bot
- Fayl: AVTO_BOT/avto_bot.py (yagona fayl)

## Bot nima qiladi
Telegram avto-poster bot. Foydalanuvchilar o'z Telegram hisoblari orqali tanlangan chatlarga avtomatik reklama joylashtiradi.

## Asosiy texnologiyalar
- python-telegram-bot (PTB) — bot interface
- Telethon — foydalanuvchi hisobi orqali post yuborish
- JSON fayllar — data saqlash (atomik yozish)
- StringSession — sessiya saqlash

## Muhim o'zgarishlar (bajarilgan)
1. Inline Numpad — kod kiritish (Telegram anti-fraud bypass)
2. Login timeout: 5 daqiqa
3. Noto'g'ri kod: 5 marta urinish
4. PhoneCodeExpired → avtomatik yangi kod
5. Bot reklamasi: har post oxiriga "🤖 AVTO_BOT — @avtoelon_el_uzbot"
6. /start oynasi: to'liq ma'lumot (kimlar uchun, nimalar uchun)
7. Admin kontakt: +998938670592

## Konstantalar
- MAX_CHATS = 10
- MAX_POSTS = 20
- MIN_INTERVAL_MIN = 4
- BOT_USERNAME = @avtoelon_el_uzbot
- ADMIN_CONTACT_PHONE = +998938670592

## Deploy
- AWS yoki Replit
- .env kerak: API_ID, API_HASH, BOT_TOKEN, ADMIN_ID
