# ENGINEBOT loyihasi — kontekst va qoidalar

> Bu fayl `.kiro/steering/` ichida joylashgan va har bir chat sessiyasida
> avtomatik yuklanadi. Yangi suhbatda Kiro shu kontekstni biladi.

## 🎯 Loyiha haqida

**ENGINEBOT** — Telegram kanal va guruh egalari uchun universal e'lon
boshqaruv tizimi. Loyiha `4x40in-bot` repo'sida `ENGINEBOT/` papkasida
joylashgan.

**Brend:** ENGINE + BOT (foydalanuvchi tomonidan tanlangan)
**Tagline:** "E'lonlar mexanizmi"
**Owner:** @xudush92-cmd
**Version:** 1.0.0-mvp

## 📋 Asosiy g'oyalar va biznes-model

- Telegram kanal/guruh egalari (tenants) uchun **pulli xizmat**
- Tenantlar bot orqali e'lon qabul qiladi va kanaliga avtomatik joylashtiradi
- E'lonlar belgilangan intervalda (min 10 daqiqa) **aylanib** turadi
- Universal: faqat taxi emas, har qanday soha uchun (taxi, mulk, ish, bozor)
- To'lov: og'zaki kelishuv asosida, super admin (loyiha egasi) tasdiqlaydi
- Tariflar: Trial (bepul), Bronze 50K, Silver 150K, Gold 300K so'm/oy

## 🏗 Arxitektura

### 4 darajali boshqaruv:
1. **SUPER_ADMIN** (siz, @xudush92-cmd) — global nazorat
2. **TENANT** (kanal egasi) — o'z guruhi
3. **MODERATOR** (tenant yordamchisi) — cheklangan huquq
4. **USER** (taksist/sotuvchi) — faqat o'zi

### Papka tuzilishi (ENGINEBOT/ ichida):
```
core/        - 8 modul (database, permissions, tenant_manager, event_bus,
               audit_log, rate_limiter, notifier, error_handler)
panels/      - 4 panel (super_admin, tenant, moderator, user) + start.py
plugins/     - kengaytirish (taxi MVP)
services/    - publisher, scheduler, cleaner, billing_checker
keyboards/   - common, routes (14 viloyat), 4 panel KB
utils/       - session_state, confirmation, validators, formatters, logger
data/        - SQLite baza (gitignore)
logs/        - rotation logs (gitignore)
```

### DB jadvallar (10 ta):
tenants, tenant_settings, channels, users, announcements, moderators,
audit_log, notifications, payments, warnings

## 🔐 QAT'IY QOIDALAR (foydalanuvchi tomonidan o'rnatilgan)

1. **AVTO_BOT'ga tegmaslik!** — `4x40in-bot/AVTO_BOT/` papkasi alohida
   loyiha, ishlab turibdi. Hech qachon tegmaslik kerak.
   `polish/login-janitor-and-rollback` PR #3 — AVTO_BOT'niki.

2. **Kodga o'zgartirish kiritishdan oldin foydalanuvchi ruxsati shart!**
   Avval muammoni tahlil qilish, yechimni taklif qilish, va FAQAT
   foydalanuvchi "ha" yoki "ruxsat beraman" degandan keyin kod yozish.

3. **Izolyatsiya** — har bir tenant alohida, DB darajasida `tenant_id`
   filtri orqali. Cross-tenant access PermissionDenied'ga olib keladi.

4. **Tasdiqlash** — har bir muhim amalda foydalanuvchidan tasdiq olish
   (utils/confirmation.py orqali).

5. **Aylanish** — default OFF, min 10 daqiqa, faqat tenant yoqsa ishlaydi.

6. **Bildirishnoma va ogohlantirish** — har muhim amalda yuboriladi
   (core/notifier.py).

7. **Crash isolation** — bittasi crash bo'lsa boshqasi davom etadi
   (safe_loop, ErrorBoundary).

## 🎨 Til va uslub

- **Asosiy til:** O'zbekcha (latin yozuvi)
- **Kod sharhlari:** O'zbekcha (kelajakda RU/EN qo'shilishi mumkin)
- **Tugma matnlari:** O'zbekcha + emoji
- **Foydalanuvchi xabarlari:** Hurmatli, do'stona uslubda

## 🛠 Texnik stack

- **Python 3.11+** (lekin kod 3.9 bilan ham mos qilingan)
- **aiogram 3.x** — bot framework
- **aiosqlite** — async SQLite (WAL mode)
- **aiohttp** — HTTP server (health endpoint, kelajakda)
- **python-dotenv** — env management

## 📍 Hozirgi holat (May 2026)

- ✅ MVP yaratildi: 39 ta Python fayl, hammasi compile o'tdi
- ✅ PR #5 ochildi: https://github.com/xudush92-cmd/4x40in-bot/pull/5
- ✅ Branch: `feature/enginebot-init`
- ⏳ Test/deploy: foydalanuvchi tomonidan ko'rib chiqilmoqda

## 🚀 Keyingi rivojlanish bosqichlari

### v1.5 (kelajak)
- @username orqali kanal ulash (bot.get_chat)
- Yo'lovchi izlash funksiyasi (search)
- Real estate, jobs, marketplace pluginlari
- Reyting tizimi
- Eksport (Excel, PDF)

### v2.0 (Pro)
- Click/Payme avto-to'lov integratsiyasi
- VIP e'lonlar
- Push notification
- Web admin panel (FastAPI/Flask)
- Telegram WebApp

### v3.0 (Ekosistema)
- REST API
- Mobile app (iOS, Android)
- Multi-language (UZ/RU/EN)
- AI yordamchi
- Public plugin marketplace

## 💬 Foydalanuvchi haqida

- @xudush92-cmd — loyiha egasi
- O'zbekistondan
- Telegram bot ishlab chiqaradi
- Hozirda AVTO_BOT'i bor (alohida loyiha)
- ENGINEBOT'ni biznes sifatida qurmoqchi (pulli xizmat)
- Texnik tushunchaga ega, lekin kod yozishni Kiro'ga ishonib topshiradi
- Har qadamda tasdiqlash so'raydi — ehtiyotkor ishlaydi

## 📞 Hisobot va davom etish

Yangi suhbat boshlanganda foydalanuvchi:
- "ENGINEBOT haqida" deb so'rasa → bu kontekst yordam beradi
- "Loyihani davom ettiraylik" desa → PR #5 holatini tekshirish kerak
- "Yangi funksiya qo'shing" desa → arxitektura va plugin tizimini eslash kerak
- AVTO_BOT haqida so'rasa → ENGINEBOT'dan butunlay alohida ekanligini eslash
