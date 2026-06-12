# AVTO BOT — Loyiha konteksti

## Repo va branch
- Repo: xudush92-cmd/4x40in-bot
- Branch: main
- Asosiy papka: AVTO_BOT/

## Bot nima qiladi
Telegram avto-poster bot. Foydalanuvchilar o'z Telegram hisoblari orqali tanlangan chatlarga avtomatik reklama joylashtiradi.

## Arxitektura (modullar)

| Fayl | Vazifa |
|------|--------|
| avto_bot.py | Asosiy bot — Telegram handlers, login flow, numpad, posting worker |
| database.py | SQLite storage (users, chats, posts) — JSON o'rniga |
| client_pool.py | Telethon client pool (max 50 client, idle 5daq→disconnect) |
| worker_manager.py | Workerlar boshqaruvi (max 35, graceful shutdown) |
| health.py | HTTP /health endpoint (port 8080) — monitoring |
| rate_limiter.py | Anti-spam (login: 3/5daq, command: 30/min) |
| requirements.txt | python-telegram-bot, telethon, aiosqlite, aiohttp |

## Texnologiyalar
- python-telegram-bot (PTB) — bot interface
- Telethon — foydalanuvchi hisobi orqali post yuborish
- aiosqlite — async SQLite storage (WAL mode)
- aiohttp — health check HTTP server
- StringSession — sessiya saqlash

## Asosiy xususiyatlar
1. **Numpad login** — kod kiritish uchun inline tugmalar (Telegram anti-fraud bypass)
2. **Login timeout: 5 daqiqa**, noto'g'ri kod: 5 marta urinish
3. **PhoneCodeExpired → avtomatik yangi kod** + numpad qayta
4. **Tarif tizimi** — 4 ta tarif, har biri o'z chat/post limiti bilan
5. **Restart-dan keyin avtomatik tiklash** — running=1 bo'lgan userlar
6. **Graceful shutdown** — SIGTERM/SIGINT da barcha komponentlar xavfsiz yopiladi
7. **Super admin** uchun '🖥 Tizim' tugmasi — RAM, workers, pool monitoring
8. **Referal tizimi** — foydalanuvchilar boshqalarni taklif qilishi mumkin
9. **Tarif muddati nazorati** — muddati tugaganlarga ogohlantirish + avto-to'xtatish

## Tariflar

| Tarif | Nomi | Max chatlar | Max postlar |
|-------|------|-------------|-------------|
| 1 | 🟢 Start | 5 | 10 |
| 2 | 🔵 Biznes | 10 | 25 |
| 3 | 🟡 Pro | 20 | 50 |
| 4 | 🔴 Premium | 50 | 100 |

- Tarif muddati: 30 kun (admin tomonidan beriladi)
- Muddat tugashidan 3 kun oldin ogohlantirish yuboriladi
- Super admin tarifi: 3 (Pro), muddatsiz

## Konstantalar
- MIN_INTERVAL_MIN = 5 daqiqa
- MAX_INTERVAL_MIN = 1440 daqiqa (24 soat)
- MAX_CONCURRENT_WORKERS = 35
- LOGIN_TIMEOUT_S = 300 (5 daq)
- SEND_DELAY_S = 5 (chatlar orasidagi kutish)
- MAX_CHAT_FAILS = 3 (ketma-ket xato → chat avto-o'chiriladi)
- BOT_USERNAME = @avtoelon_el_uzbot
- ADMIN_CONTACT_PHONE = +998938670592

## Yuklanish (capacity)
- 8 GB RAM serverda: 200-250 faol foydalanuvchi
- 1 GB RAM (AWS free tier): 20-30 faol foydalanuvchi
- SQLite 1000+ foydalanuvchi uchun mos

## Deploy
- .env kerak: API_ID, API_HASH, BOT_TOKEN, ADMIN_ID
- Qo'shimcha: HEALTH_PORT (default 8080), BOT_USERNAME
- Ishga tushirish: `pip install -r requirements.txt && python avto_bot.py`
- Health check: `curl http://server:8080/health`
