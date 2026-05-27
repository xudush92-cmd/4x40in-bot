# ENGINEBOT — Loyiha konteksti va holati

## 📌 Loyiha haqida
Telegram kanal/guruh egalari uchun universal e'lon boshqaruv tizimi.
- **Repo:** `xudush92-cmd/4x40in-bot`, papka `ENGINEBOT/`
- **Texnologiyalar:** Python 3.11+, aiogram 3.x, aiosqlite (WAL mode)
- **Arxitektura:** 4 darajali (SUPER_ADMIN > TENANT > MODERATOR > USER)
- **Model:** PULSIZ (og'zaki kelishuv asosida tarif/muddat belgilanadi)

## 🔀 Branch'lar va PR'lar holati (2025-05-27)

| PR | Branch | Maqsad | Holat |
|----|--------|--------|-------|
| #6 | `feature/enginebot-v1-redesign` | V1 to'liq redesign | Ochiq |
| #7 | `fix/enginebot-cleanup-pulsiz` | Pulsiz model + kritik fixlar | Ochiq |
| #8 | `fix/enginebot-dead-handlers-and-bugs` | Dead button handlerlar + buglar | Ochiq ✅ |

**Tavsiya:** #6 → #7 → #8 tartibida main'ga merge qilish.

## ✅ Oxirgi sessiyada bajarilgan ishlar (PR #8)

### Kritik buglar tuzatildi:
1. `publisher.py` — `refresh_post_in_channel` endi `is_edit=True` bilan chaqiriladi (rotation_count oshirilmaydi, "Aylandi" badge ko'rsatilmaydi)
2. `scheduler.py` — `is_first` mantiqi: `PostStatus.DRAFT` emas, `message_id=NULL` bilan tekshirish
3. `_handle_publish_error` — FloodWait retry'da `is_edit` uzatiladi

### Dead button handlerlar yozildi (~30 ta):
- **Super admin:** `super:tenant:stats/users/payments/audit/message/reject/delete`, `super:tenants:filter:*`, `super:system:backup/cleanup_logs/restart_services`, `Btn.PAYMENTS`, `super:menu`
- **Tenant:** `tenant:post:view/warn_owner`, `tenant:channel:toggle/remove`, `tenant:users:filter:*`, `tenant:user:posts/audit`, `tenant:profile:edit:*`, `tenant:deeplink:copy`, `tenant:cat_toggle/cat_save`, `Btn.STATS/DEEP_LINK/CATEGORY_RESTRICTION`, orqaga tugmalari

### Xavfsizlik — confirmation qo'shildi:
- `tenant:post:delete` → tasdiqlash + kanaldan o'chirish
- `poster:post:delete` → tasdiqlash
- `super:tenant:approve_trial` → tasdiqlash
- `super:tenant:pause` → tasdiqlash
- `super:tenant:unblock` → tasdiqlash
- `super:tenant:delete` → DOUBLE confirmation + CASCADE warning
- `tenant:user:unblock` → tasdiqlash

### Notification/Throttle:
- `notify_tenant_payment_reminder` — IDEMPOTENT (bir kunda 1 ta, DB tekshirish)
- `broadcast` — `asyncio.Semaphore(25)` (FloodWait oldini olish)
- `super:awaiting_message_to_tenant` state qo'shildi (shaxsiy xabar yuborish)

### Dead code tozalandi:
- `tenant_manager.receive_payment()` — 60 qator (chaqirilmas edi)
- `audit_log.log_payment_event()` — chaqirilmas edi
- `formatters.format_uzs()` — chaqirilmas edi
- `validators.validate_amount_uzs()` — chaqirilmas edi
- `confirm_logout` import (poster/customer) — ishlatilmas edi
- `parse_confirmation` import (super_admin) — ishlatilmas edi

## ⚠️ HALI QOLGAN MUAMMOLAR (keyingi sessiya uchun)

### 🟡 O'rtacha muhimlik:
1. **`max_users` tarif limit** — DB'da bor, lekin hech qaerda tekshirilmaydi (yangi user registratsiyada)
2. **`max_posts_per_day` tarif limit** — tekshirilmaydi
3. **Moderator panel** — `panels/moderator/handlers.py` deyarli bo'sh (v1.5 uchun)
4. **`tenant_detailed_stats`** — DB funksiyasi mavjudligini tekshirish kerak (PR #8 da ishlatilgan, lekin database.py'da bu funksiya PR #6 da yozilgan)
5. **`db.list_audit(actor_id=...)`** — DB funksiyasi parametri tekshirish kerak
6. **`db.get_allowed_categories`** / `db.set_allowed_categories` — DB funksiyasi mavjudligini tekshirish
7. **`db.tenant_detailed_stats`** — DB funksiyasi mavjudligini tekshirish

### 🟢 Past muhimlik:
- `Btn.MODERATORS` / `Btn.EDIT_PROFILE` class'da bor lekin hech qaerda ishlatilmaydi
- `tenant:post:pause/resume` — confirmation yo'q (lekin tez qaytariladigan amal)
- `format_uzs` funksiya olib tashlandi — agar kelajakda pul model kerak bo'lsa qayta yozish kerak

## 🚨 KEYINGI SESSIYADA BIRINCHI NAVBAT:

1. **SINOV** — Bot'ni ishga tushirib PR #8 handlerlarini haqiqiy test qilish
2. **DB funksiyalar tekshiruvi** — `tenant_detailed_stats`, `list_audit(actor_id=)`, `get_allowed_categories`, `set_allowed_categories`, `search_announcements`, `get_recent_announcements`, `list_bookmarks`, `is_bookmarked`, `add_bookmark`, `remove_bookmark` — hammasi `database.py` da bormi?
3. **3 ta PR ni merge qilish** (yoki birlashtirib 1 taga aylantirish)
4. **Deploy** — Replit/VPS'ga chiqarish

## 📂 Asosiy fayl tuzilishi (52 fayl)

```
ENGINEBOT/
├── main.py                    — entry point, router registration
├── config.py                  — env, constants, tariff limits
├── core/
│   ├── database.py            — SQLite CRUD (1780 qator)
│   ├── permissions.py         — 4-darajali RBAC
│   ├── tenant_manager.py      — tenant lifecycle
│   ├── notifier.py            — notification queue
│   ├── audit_log.py           — audit logging
│   ├── middleware.py          — global error handler
│   ├── error_handler.py       — safe_loop, ErrorBoundary
│   ├── categories.py          — soha kodlari
│   ├── event_bus.py           — async events
│   └── rate_limiter.py        — anti-flood
├── panels/
│   ├── start.py               — /start, /cancel, /help
│   ├── common_handlers.py     — Btn.MY_PROFILE, Btn.LOGOUT (umumiy)
│   ├── super_admin/handlers.py — 30+ callback handler (PR #8)
│   ├── tenant/handlers.py     — 40+ handler (kanal, users, posts, profile, stats)
│   ├── poster/handlers.py     — registration + CRUD + rotation
│   ├── customer/handlers.py   — registration + search + feed
│   ├── moderator/handlers.py  — stub (v1.5)
│   └── user/handlers.py       — legacy stub
├── keyboards/
│   ├── common_kb.py           — Btn class, inline_grid, make_reply
│   ├── super_admin_kb.py      — SA menyulari
│   ├── tenant_kb.py           — tenant menyulari
│   ├── user_kb.py             — poster/customer menyulari
│   └── routes.py              — REGIONS list
├── services/
│   ├── publisher.py           — kanalga publish + refresh
│   ├── scheduler.py           — per-poster rotation loop
│   ├── cleaner.py             — expired post cleanup
│   ├── billing_checker.py     — muddat tekshiruv
│   └── notifier_service.py    — notification yuborish
└── utils/
    ├── session_state.py       — per-user conversation state
    ├── confirmation.py        — build_confirmation + confirm_logout
    ├── formatters.py          — HTML escape, wrap_announcement
    ├── validators.py          — phone, name, channel, interval
    └── logger.py              — logging setup
```

## 🛑 QOIDALAR (har sessiyada amal qilish)

1. **KODGA TEGISHDAN OLDIN RUXSAT OLISH** — har sessiyada
2. **MAVJUD KODNI QAYTA YOZMASLIK** — faqat str_replace, nuqtaviy edit
3. **AVTO_BOT papkasiga TEGMASLIK** — alohida loyiha
4. **Har muhim amalda CONFIRMATION** — bot egasining qat'iy talabi
5. **Audit log MAJBURIY** — har handler'da
6. **Bildirishnoma MAJBURIY** — block, warn, approve, delete
