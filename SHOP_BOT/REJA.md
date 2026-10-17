# SHOP-BOT — Onlayn do'kon uslubidagi e'lonlar boti
## To'liq texnik reja (v1.0) — kelishilgan bosqichlar va qamrov

> **Amaldagi holat (2026-10-15):** Phase 0–9 kod/oflayn ishlar bajarildi.
> Phase 9ga alohida ruxsat berilgan; jonli PostgreSQL/Redis/Telegram/bank va
> restore/video qabul ishlari qolgan. Bu fayl dastlabki reja; amalga oshirilgan
> ishlar va sinov cheklovlari uchun [HOLAT.md](HOLAT.md) ga qarang.
> **Ish qoidasi:** ruxsatsiz yangi bosqich boshlanmaydi, yangi branch/PR ochilmaydi.

---

## ✅ TASDIQLANGAN QARORLAR (2026-10-15)

| # | Savol | Sizning qaroringiz | Rejaga ta'siri |
|---|---|---|---|
| 1 | Baza | **PostgreSQL 16 + Redis 7** | 4-bo'limdagi sxema to'liq ishlatiladi; SQLite varianti rad etildi |
| 2 | Kod joyi | **Shu repo, `SHOP_BOT/` papkasi** | `AVTO_BOT/` ga umuman tegilmaydi; botlar mustaqil |
| 3 | Deploy | **Docker Compose + Caddy + webhook** | 13-bo'limdagi stack; domen va HTTPS kerak |
| 4 | Ish tartibi | **Avval MVP: Phase 0 → 5** | Guruh, toifa, sotuvchi, tarif, e'lon, aylanma joylash, to'lov. Keyin 6→9 (posbon, tozalovchi, sanoqchi, referal, statistika, sayqal) |

**MVP (0→5) yakunida ishlaydigan narsalar:** guruh va toifalarni boshqarish → sotuvchi va tariflar → e'lon qo'shish (al bomi bilan) → aylanma avto-joylash → yarim avtomatik to'lov va obuna. Ya'ni **pul ishlaydigan minimal tizim**.

**MVP'da ataylab keyinga qoldirilgan:** posbon, tozalovchi, sanoqchi, referal, statistika bo'limlari, broadcast, matn tahriri, xato jurnali paneli (Phase 6→9). Baza sxemasi (4-bo'lim) esa **boshidanoq to'liq** quriladi — keyin migratsiya bilan azoblanmaslik uchun.

---

## 0. QISQA JAVOB: "Qila olasanmi?"

**Ha.** Loyiha texnik jihatdan bajariladigan, lekin **"katta auditoriya uchun" degani arxitekturani boshqacha qurishni talab qiladi** (SQLite + bitta process yetmaydi).

Bir muhim ogohlantirish: rejangizda **5-8 ta joyda Texnologiya cheklovlari** bor, ular kod yozishdan oldin hal qilinishi kerak (1.2-bo'limga qarang) — aks holda keyinchalik qayta yozishga to'g'ri keladi. Masalan, **albomga (media group) inline tugma biriktirib bo'lmaydi** — bu Telegram Bot API'ning cheklovi, Aiogram'ning emas.

**Dastlabki auditda:** g'oya tahlil qilinib, arxitektura + DB sxemasi + bosqichma-bosqich reja yozilgan; o'sha paytda kod yozilmagan edi. Hozir Phase 0–8 kodi `SHOP_BOT/`da bor (joriy holat: `HOLAT.md`).

---

## Mundarija

1. [G'oyani ko'rib chiqish (audit)](#1-goyani-korib-chiqish-audit)
2. [Umumiy arxitektura](#2-umumiy-arxitektura)
3. [Texnologiyalar](#3-texnologiyalar)
4. [Ma'lumotlar bazasi sxemasi](#4-malumotlar-bazasi-sxemasi)
5. [Modul / fayl tuzilishi](#5-modul--fayl-tuzilishi)
6. [Admin panel (boshqaruv paneli)](#6-admin-panel-boshqaruv-paneli)
7. [Sotuvchi va foydalanuvchi panellari](#7-sotuvchi-va-foydalanuvchi-panellari)
8. [Asosiy avtomatik jarayonlar (flow)](#8-asosiy-avtomatik-jarayonlar-flow)
9. [Aylanma joylash dvigateli (yadro)](#9-aylanma-joylash-dvigateli-yadro)
10. [Katta auditoriya uchun masshtablash](#10-katta-auditoriya-uchun-masshtablash)
11. [Xavfsizlik, risklar, huquqiy eslatmalar](#11-xavfsizlik-risklar-huquqiy-eslatmalar)
12. [Test va QA rejasi](#12-test-va-qa-rejasi)
13. [Deploy, zaxira nusxa, monitoring](#13-deploy-zaxira-nusxa-monitoring)
14. [Bosqichlar (roadmap) va muddat](#14-bosqichlar-roadmap-va-muddat)
15. [Sizdan kerak bo'ladigan qarorlar](#15-sizdan-kerak-boladigan-qarorlar)
16. [Keyingi qadam](#16-keyingi-qadam)

---

## 1. G'OYANI KO'RIB CHIQISH (AUDIT)

### 1.1. Kuchli tomonlari

| # | Yaxshi jihat | Nega muhim |
|---|---|---|
| 1 | Hammasi admin paneldan boshqariladi, kodga tegmasdan | Loyihani boshqa odam ham yurita oladi, sotib olishga tayyor mahsulot bo'ladi |
| 2 | Har guruh uchun alohida sozlama | Bir bot bilan har xil talabli guruhlarni bir vaqtda xizmat qilish |
| 3 | Aylanma (round-robin) joylash | Guruh "katalog" bo'lib qoladi, sotuvchilar navbat kutadi — adolatli |
| 4 | Tarif tizimi + limitlar | Monetizatsiya modeli aniq: pul → limit |
| 5 | Posbon + tozalovchi + ruxsatlar | Guruhni toza saqlash — bu bozorda eng ko'p so'raladigan funksiya |
| 6 | Tasdiqlash rejimi (moderatsiya) | Spam va firibgar e'lonlardan himoya |

### 1.2. Zaif / muammoli / tuzatish kerak bo'lgan joylar (KRITIK)

Bular **kod yozishdan oldin** hal qilinishi shart.

| # | Muammo | Nega muhim | Taklif qilinayotgan yechim |
|---|---|---|---|
| 1 | **Albomga inline tugma qo'shib bo'lmaydi** | `sendMediaGroup` da `reply_markup` parametri yo'q (rasmiy hujjatda ham yo'q). Rejangizda "rasi al lbomi + Sotuvchi bilan bog'lanish tugmasi" bitta xabarda ko'zda tutilgan | Har e'lon = **2 xabar**: (1) albom (rasmlar + izoh), (2) albomga reply qilingan kichik xabar: `👤 Sotuvchi bilan bog'lanish` inline tugmasi bilan. Yoki: 1-rasm alohida + izoh + tugma, qolgan rasmlar albom. Ikkalasi ham test qilinadi, admin panelda tanlanadi |
| 2 | **Bot Privacy Mode O'CHIQ bo'lishi shart** | Aks holda bot guruhdagi oddiy xabarlarni **ko'rmaydi** → posbon (havola taqiqi) va tozalovchi **umuman ishlamaydi** | BotFather → `/setprivacy` → **Disable**. Bot ishga tushganda `/getMe + getChatMember` orqali huquqlarni tekshiradi va admin panelda ogohlantiradi |
| 3 | **Faqat supergroup'da ishlaydi** | Oddiy guruhda mute/ban/restrict amallari cheklangan, adminlik imkoniyatlari kam | Guruh qo'shilganda `is_supergroup` tekshiriladi; oddiy guruh bo'lsa admin panelda "Supergroup'ga aylantiring" degan aniq ko'rsatma chiqadi |
| 4 | **"Kim kimni qo'shdi" ni ishonchli aniqlash** | Bitta odam bir marta sanalishi kerak. Xizmat xabari ("X added Y") doim kelmaydi (join request, invite link holatlarida) | Asosiy usul: **shaxsiy invite link** (`createChatInviteLink`) + `chat_member.invite_link` / `chat_join_request.invite_link` orqali attributsiya. Zaxira usul: xizmat xabari. Uchinchi usul: admin qo'lda qo'shishi |
| 5 | **Invite linklar soni cheklangan bo'lishi mumkin** | Har foydalanuvchi uchun yangi link yaratilsa, yuz minglab link to'planadi | Link pool + qayta ishlatish + 30-90 kunda `revokeChatInviteLink`. Aniq limit Phase-0 testida o'lchanadi (100/1000) va kod shunga moslashadi |
| 6 | **Xabar o'chirish cheklovlari (48 soat / admin huquqi)** | "Oldingi e'lonlarni tozalash" rejasi xabar o'chirishga tayanadi | Ishonchli strategiya: **qayta joylashdan oldin o'zining eski xabarini o'chirish** (har doim ruxsat etiladi) + `posted_messages` jadvalida message_id saqlash. Xato (`MESSAGE_DELETE_FORBIDDEN`) bo'lsa — jurnalga yozish, to'xtamaslik |
| 7 | **Guruhda 20 xabar/daqiqa limiti** | Bitta guruhga bir necha toifa + tez interval = 429 xato | Global va guruh bo'yicha **rate limiter** (token bucket): 1 guruh = maks 1 xabar/2s, kunlik hisob; intervalga **jitter** (±10-20%); minimal interval 60s. Bir guruhga bir necha toifa biriktirilsa — jami limit hisobga olinadi |
| 8 | **To'lov firibgarligi (chek qayta ishlatish)** | Bitta chek rasmini 5 marta yuborish — klassik firibgarlik | `receipt.file_unique_id` hash'i saqlanadi, takroriy chek aniqlanadi va admin panelda 🔴 belgisi bilan ko'rsatiladi. Faqat admin tasdiqlaydi (avtomatik tasdiq yo'q) |
| 9 | **Tarif limitlarining bajarilishi** | "5 e'lon, har birida 3 rasm" — sotuvchi limitdan oshib ketmasligi shart | Har rasm yuklash va e'lon saqlashda **server tomonida** tekshiriladi (`ads_used / ads_limit`, `photos_count / max_photos`). Limit tugasa tugma o'chadi + sabab ko'rsatiladi |
| 10 | **Referal suiiste'moli** | O'zini o'zi taklif qilish, soxta akkauntlar, "bir kunda 100 bonus" | `referee_id` unikal, o'z-o'zini taklif taqiqlangan, kunlik/haftalik bonus limiti, ixtiyoriy: birinchi to'lovdan keyin bonus (bepul kunlardan ko'ra firibgarlikka chidamli) |
| 11 | **Bot huquqini yo'qotishi / guruh o'chirilishi** | Joylash to'xtaydi, xatolar to'planadi | `my_chat_member` update kuzatiladi: huquq olinsa → **guruh avtomatik pauza** + adminga darhol xabar. 3 marta ketma-ket xato → avtopauza + admin xabari (rejangizdagi talab) |
| 12 | **E'lon sifati va spam** | Tasdiqlash rejimi bo'lmasa guruh tez buziladi | Moderatsiya navbati + taqiqlangan so'zlar filtri + "Rad etish sababini yozish" + sotuvchiga qayta yuborish imkoni |
| 13 | **Ko'p admin / rollar** | "Adminlarni boshqarish" bor, lekin rollar aniqlanmagan | 3 rol: **Super admin** (hammasi), **Admin** (kontent), **Moderator** (faqat moderatsiya). Har amal `action_log`ga yoziladi (audit) |
| 14 | **Avariya to'xtatish (kill switch)** | Xato bo'lsa hammasi to'xtashi kerak | Global "🛑 HAMMASINI TO'XTATISH" tugmasi + har funksiya uchun guruh bo'yicha va global alohida o'chirish matritsasi |

### 1.3. Rejaga qo'shishni tavsiya qiladigan narsalar (sizning TZ'da yo'q)

| # | Qo'shimcha | Foyda |
|---|---|---|
| 1 | **Tinch soatlar** (masalan 23:00–08:00 joylanmaydi, yoki sekin rejim) | Kechasi guruhni uyg'otmaslik |
| 2 | **Jitter** (interval ±tasodifiy siljish) | Bir xil sekundda hamma guruhga post ketmasligi, spam belgisiga tushmaslik |
| 3 | **Kunlik post limiti** (guruh uchun) | Guruh suvga to'lib ketmasligi |
| 4 | **E'lon statistikasi** (necha marta joylandi, oxirgi marta qachon) | Sotuvchi o'z pulining natijasini ko'radi |
| 5 | **Sinov (dry-run) rejimi** — posbon/tozalovchi faqat log yozadi, jazo qo'llamaydi | Yangi guruhda qo'rqmasdan sozlash |
| 6 | **Moderatsiya: so'z/kanal blacklist** | Avtomatik filtr + admin tasdig'i |
| 7 | **Hisobot eksporti (CSV/XLSX)** | Hisob-kitob, soliq, investor hisoboti |
| 8 | **Broadcast (ommaviy xabar)** — eng ko'pi 25 msg/s limit bilan navbat orqali | Sotuvchilarga aksiya/xabar yuborish |
| 9 | **FSM holatini Redis'da saqlash** | Server qayta yonsa ham "e'lon qo'shish" jarayoni yo'qolmaydi |
| 10 | **Zaxira nusxa** (kunlik avtomatik `pg_dump`) | Ma'lumot yo'qolmasligi |
| 11 | **Bepul sinov / promo davri** (masalan 3 kun) | Yangi sotuvchilarni jalb qilish |
| 12 | **Ko'p tilli** (uz / ru) — matn tizimi shunga tayyor quriladi | Katta auditoriya uchun muhim |
| 13 | **Ma'lumot saqlash siyosati** (loglar 90 kun, keyin arxiv/o'chirish) | Baza sekinlashmasligi |

---

## 2. UMUMIY ARXITEKTURA

**Bitta bot, 4 xil rol** (admin / sotuvchi / guruh a'zosi / guruh ichidagi kuzatuvchi).

```
                        ┌──────────────────────────────┐
                        │      TELEGRAM SERVERLARI     │
                        └───────────────┬──────────────┘
                                        │  webhook (yoki long-polling)
                        ┌───────────────▼──────────────┐
                        │        NGINX / CADDY         │  TLS, domen
                        └───────────────┬──────────────┘
                                        │
        ┌───────────────────────────────▼────────────────────────────────┐
        │                     BOT PROCESS (Aiogram 3.x)                  │
        │                                                                │
        │  Middlewares:  DB sessiya │ User │ Sozlamalar keshi │ Throttling│
        │                │ Admin/Rol tekshiruvi │ Error handler           │
        │                                                                │
        │  Routerlar:                                                     │
        │   ├── admin/     (boshqaruv paneli — inline tugmalar)           │
        │   ├── seller/    (tarif, to'lov, e'lon qo'shish)                │
        │   ├── user/      (/start, /takliflarim, majburiy obuna)         │
        │   └── group/     (posbon, tozalovchi, chat_member, join_req)    │
        │                                                                │
        │  Services (biznes-logika, Telegram'siz):                        │
        │   posting │ tariff │ payment │ referral │ counter │ guard        │
        │   cleaner │ permission │ stats │ texts │ notification            │
        └───────┬───────────────────────────────────┬────────────────────┘
                │                                   │
      ┌─────────▼──────────┐              ┌─────────▼──────────┐
      │   POSTER WORKER     │              │      REDIS 7       │
      │  (APScheduler)      │              │  FSM, kesh, lock   │
      │  ├ aylanma joylash  │              └────────────────────┘
      │  ├ tarif eslatmalari│
      │  ├ referal/bonus    │              ┌────────────────────┐
      │  ├ tozalash (retention)             │  HEALTH SERVER     │
      │  └ kunlik statistika│              │  :8080 /health     │
      └─────────┬──────────┘              └────────────────────┘
                │
      ┌─────────▼──────────────────────────┐
      │   POSTGRESQL 16                    │
      │   (SQLAlchemy 2.0 async + Alembic) │
      │   ~30 jadval, kunlik zaxira nusxa  │
      └────────────────────────────────────┘
```

**Muhim tamoyillar:**
1. **Servislar Telegram'ga bog'lanmaydi** — sof biznes-logika, test qilish oson, keyin API/web panel qo'shish mumkin.
2. **Barcha holat bazada** — bot qayta yonsa hech narsa yo'qolmaydi (navbat, kursori, post vaqtlari, FSM).
3. **Sozlamalar keshi** — har xabar uchun DB'ga murojaat qilmaslik. Admin sozlamani o'zgartirsa → kesh darhol yangilanadi (bot qayta yoqilmaydi: bu sizning asosiy talabingiz).
4. **Idempotentlik** — bitta e'lon ikki marta joylanmasligi (DB'dagi atomar `UPDATE ... WHERE next_post_at = <eski qiymat>`), bir vaqtda ikki worker ishlasa ham.

---

## 3. TEXNOLOGIYALAR

| Qatlam | Tanlov | Sabab |
|---|---|---|
| Til | **Python 3.12** | Aiogram 3.x talabi, barqaror |
| Bot framework | **aiogram 3.x** (aniq versiya pin qilinadi, masalan 3.15+) | Async, pydantic v2, FSM, `CallbackData` fabrikalari, ajoyib middleware tizimi |
| DB | **PostgreSQL 16** + **SQLAlchemy 2.0 async** + **asyncpg** | Katta auditoriya uchun; bir vaqtda 100+ yozish; `SKIP LOCKED`, partial index |
| Migratsiya | **Alembic** | Sxema o'zgarishlari uchun (keyinchalik yangi funksiya qo'shganda) |
| Kesh / FSM | **Redis 7** (`redis.asyncio` + `RedisStorage`) | FSM restartdan omon qoladi, kesh, lock, rate-limit |
| Scheduler | **APScheduler** (`AsyncIOScheduler`) | Poster alohida process, DB'dan "vaqti kelgan" ishlarni oladi |
| HTTP | **aiohttp** (webhook + `/health`) | Aiogram bilan bir xil loop, yengil |
| Sozlamalar | **pydantic-settings** + `.env` | Tipizatsiya, validatsiya |
| Log | **loguru** yoki `structlog` (JSON) | Xatolarni jurnalga yozish, grep qilish oson |
| Test | **pytest**, **pytest-asyncio**, aiogram test utils, **testcontainers** (yoki SQLite test rejimi) | Servislar va handler'lar testi |
| Deploy | **Docker + docker-compose** (yoki systemd unit'lar) | Bir buyruq bilan ko'chirish |
| Proxy/TLS | **Caddy** (avtomatik TLS) yoki Nginx + certbot | Webhook uchun domen/HTTPS |
| Monitoring | `/health`, `/stats`, **Sentry** (ixtiyoriy) | Uptime robot uchun |

**Nima uchun SQLite emas:** mavjud `AVTO_BOT` loyihangiz SQLite'da — u yerda yuklama kichik. Bu yerda esa: ko'p guruh (100-1000), ko'p bir vaqtda yozuv (har xabar uchun statistika/violation), bir necha process (bot + poster). SQLite WAL bunday yuklamada `database is locked` beradi. **Agar siz baribir SQLite xohlasangiz** — SQLAlchemy tufayli kod bir xil qoladi, faqat havolani o'zgartirish kerak (lekin katta auditoriyada tavsiya etmayman).

---

## 4. MA'LUMOTLAR BAZASI SXEMASI

~30 jadval, 9 guruhga bo'lingan. Har jadval uchun asosiy ustunlar keltirilgan.

### 4.1. Yadro (yadro jadvallari)

| Jadval | Ustunlar | Izoh |
|---|---|---|
| `users` | `user_id PK, username, first_name, last_name, language, is_blocked, blocked_reason, created_at, last_seen_at` | Barcha foydalanuvchilar (admin, sotuvchi, a'zo) |
| `admins` | `id, user_id UNIQUE, role, title, added_by, added_at, is_active, last_seen_at` | `role`: `super` / `admin` / `moderator` |
| `settings` | `key PK, value JSONB, updated_by, updated_at` | Global sozlamalar (kill switch, vaqt zonasi, default interval, broadcast limiti) |
| `bot_texts` | `key PK, lang, text, is_custom, updated_by, updated_at` | Bot matnlari + `{placeholder}` validatsiyasi |
| `action_log` | `id, actor_id, action, entity, entity_id, group_id, before JSONB, after JSONB, created_at` | Auditi: kim nima o'zgartirgan |
| `error_log` | `id, level, source, group_id, user_id, message, traceback, context JSONB, created_at, resolved_at, resolved_by` | Xatolar jurnali (admin panelda ko'rinadi) |

### 4.2. Guruhlar va toifalar

| Jadval | Ustunlar | Izoh |
|---|---|---|
| `groups` | `id PK, tg_chat_id UNIQUE, title, username, type, is_supergroup, bot_is_admin, is_active, paused_reason, added_by, added_at, member_count, last_error, updated_at` | Guruhni pauza qilish sababi: `admin_left` / `no_rights` / `error` / `manual` |
| `group_settings` | `group_id PK FK, posting_enabled, counter_enabled, guard_enabled, cleaner_enabled, welcome_enabled, interval_sec, jitter_sec, quiet_start, quiet_end, tz, daily_post_limit, updated_at` | 1:1 `groups` bilan. Rejangizdagi "har funksiyani alohida yoqish/o'chirish" |
| `group_rotation` | `group_id PK, last_post_at, next_post_at, today_count, today_date, cycle_count` | Joylash vaqt holati (restartga chidamli) |
| `categories` | `id PK, group_id FK NULL, name, emoji, description, is_active, position, interval_override, moderation_required, created_by, created_at, updated_at` | `group_id` bo'sh bo'lsa — guruh biriktirilmagan |
| `group_admins` | `group_id, user_id, role, added_by, created_at` | Guruh darajasidagi adminlar (guruh ichidan) |
| `required_channels` | `id, scope` (`global`/`group`), `group_id, channel_tg_id, username, title, invite_link, is_active` | Majburiy obuna kanallari |
| `permissions` | `id, user_id, group_id NULL, kind, reason, granted_by, expires_at, is_active, created_at` | `kind`: `full_exempt` / `guard_exempt` / `cleaner_exempt` / `link_allowed` / `counter_exempt`. `group_id = NULL` → hamma guruhlarda; guruh/global aktiv ruxsatlar uchun alohida unique indekslar |

### 4.3. Sotuvchilar, tariflar, obunalar

| Jadval | Ustunlar | Izoh |
|---|---|---|
| `sellers` | `id PK, user_id UNIQUE FK, display_name, phone, contact, status, is_verified, referral_code UNIQUE, referred_by, balance, note, added_by, created_at, updated_at` | `status`: `pending`/`active`/`blocked`/`deleted` |
| `tariffs` | `id, name, description, price, currency, duration_days, max_ads, max_photos, allowed_category_ids JSONB NULL, allowed_group_ids JSONB NULL, is_active, position` | `NULL` = cheklovsiz (hammasi). Rejangizdagi "qaysi guruh/toifalar uchun" |
| `subscriptions` | `id, seller_id FK, tariff_id FK, status, starts_at, expires_at, ads_limit, ads_used, granted_by, payment_id, created_at, updated_at` | `status`: `active`/`expired`/`cancelled`/`grace`. Index: `(seller_id, status)`, `(expires_at)` |

### 4.4. E'lonlar va navbat

| Jadval | Ustunlar | Izoh |
|---|---|---|
| `ads` | `id, seller_id, category_id, group_id (denorm), title, description, price, currency, contact_type, contact_value, status, reject_reason, position, post_count, last_posted_at, next_eligible_at, approved_by, approved_at, created_at, updated_at` | `status`: `pending`/`active`/`paused`/`rejected`/`expired`/`deleted`. Tasdiqlash rejimi shu ustunda |
| `ad_photos` | `id, ad_id, file_id, file_unique_id, position, width, height` | **Fayl saqlanmaydi** — Telegram `file_id` yetarli (server disk tejaydi) |
| `category_rotation` | `category_id PK, cursor_ad_id, last_post_at, next_post_at, cycle_count` | Navbat kursori — aylanma joylashning yuragi |
| `posted_messages` | `id, ad_id, group_id, message_ids JSONB, sent_at, delete_after_at, is_deleted, delete_error` | Eski e'lonlarni o'chirish uchun message_id'lar |
| `moderation_log` | `id, ad_id, admin_id, decision, reason, created_at` | Kim tasdiqladi/rad etdi |
| `post_log` | `id, group_id, category_id, ad_id, seller_id, message_ids, status, error, created_at` | Joylash tarixi (statistika + xatolar) |

### 4.5. To'lovlar

| Jadval | Ustunlar | Izoh |
|---|---|---|
| `payment_methods` | `id, name, card_number, holder, bank, currency, note, is_active, position` | Rekvizitlar (bir nechta karta, aylanma) |
| `payments` | `id, seller_id, tariff_id, amount, currency, method_id, receipt_file_id, receipt_unique_hash UNIQUE, is_duplicate_receipt, status, admin_id, decided_at, reason, subscription_id, created_at` | `status`: `pending`/`approved`/`rejected`/`cancelled`. Xesh birinchi chekda, takroriy chekda `NULL` + alohida belgi |

### 4.6. Referal (sanoqchidan alohida)

| Jadval | Ustunlar | Izoh |
|---|---|---|
| `referral_settings` | `key PK, value JSONB` | `enabled`, `trigger` (`signup`/`first_payment`), `bonus_type` (`days`/`discount`/`balance`), `bonus_value`, `daily_limit`, `min_payment` |
| `referrals` | `id, referrer_id, referee_id UNIQUE, code, status, trigger_at, first_payment_id, bonus_type, bonus_value, applied_at, created_at` | `UNIQUE(referee_id)` → bir odam faqat bir marta |
| `referral_bonus_log` | `id, referral_id, seller_id, bonus_type, value, applied_at, admin_id NULL` | Bonus tarixi |

### 4.7. Sanoqchi (har guruhda alohida)

| Jadval | Ustunlar | Izoh |
|---|---|---|
| `counter_settings` | `group_id PK, enabled, dry_run, required_n, mode, link_member_limit, min_stay_minutes, max_per_day, count_sources JSONB, require_subscription, notify_inviter, updated_at` | `soft` xabarni o'chiradi; `hard` qo'shimcha mute; yangi guruh uchun o'chiq va dry-run |
| `invite_links` | `id, group_id, user_id, invite_link, join_count, created_at, revoked_at, is_active` | Har foydalanuvchining shaxsiy havolasi; faol `(group_id,user_id)` qisman unique |
| `invite_events` | `id, group_id, inviter_id, invitee_id, source, message_id, counted, reject_reason, created_at` | **`UNIQUE(group_id, invitee_id)`** → "bir odam bir marta sanaladi" |
| `counter_totals` | `(group_id, user_id) PK, counted, is_unlocked, unlocked_at, last_count_at, updated_at` | Guruhga xos jamlanma (`/takliflarim`) |
| `counter_audit` | `id, group_id, user_id, delta, admin_id, reason, created_at` | Admin qo'lda qo'shgani/ayirgani tarixi |
| `counter_join_requests`, `counter_message_checks`, `counter_restrictions` | Join request expiry, bir xabar uchun rezervatsiya, faqat bot qo'ygan mute | Phase 7 navbat/idempotentlik va xavfsiz unlock |

### 4.8. Posbon va tozalovchi

| Jadval | Ustunlar | Izoh |
|---|---|---|
| `guard_settings` | `group_id PK, enabled, dry_run, require_subscription, require_counter, link_filter, forward_filter, mention_filter, penalty, mute_minutes, warn_limit, escalate JSONB, allowed_domains JSONB, exemption_for_admins` | Jazo zinapoyasi: `warn → mute → ban` |
| `warnings` | `group_id, user_id, count, last_at` PK`(group_id,user_id)` | Ogohlantirish hisobi |
| `violations` | `id, group_id, user_id, kind, message_id, text_excerpt, action, penalty_until, created_at` | Qoidabuzarliklar tarixi |
| `restrictions` | `id, group_id, user_id, kind`(`mute`/`ban`/`kick`), `until_at, reason, created_at, lifted_at, lifted_by` | Foydalanuvchilar ro'yxati shu jadvaldan |
| `cleaner_settings` | `group_id PK, enabled, dry_run, delete_join_leave, delete_service, delete_links, delete_violations, delete_old_ads, keep_last_ads, delete_after_seconds, keep_pinned` | Har guruh uchun nima/qachon tozalanadi; yangi policy sukutda sinovda |
| `group_message_actions` | `id, group_id, message_id, user_id, source, kind, planned_action, status, due_at, is_dry_run, error` | `(group_id,message_id)` yagona; `pending/running` qayta bajarish xavfini nazorat qiladi |
| `cleanup_log` | `id, group_id, kind, deleted_count, details, created_at` | Tozalash statistikasi + sabab/qayd |

### 4.9. Statistika va broadcast

| Jadval | Ustunlar | Izoh |
|---|---|---|
| `stats_daily` | `date, group_id, posts, active_ads, joins, leaves, violations, deleted_msgs, payments_amount, new_sellers` PK`(date, group_id)` | Har kecha jamlanadi; grafiklar tez chiqadi |
| `broadcasts` | `id, admin_id, text, total, sent, failed, status, created_at, finished_at` | Ommaviy xabar navbati (25 msg/s limit; Phase 8 da kengaygan) |
| `broadcast_targets` | `id, broadcast_id, user_id, status, error, sent_at` | Har qabul qiluvchi holati |

**Kritik indekslar:** `ads(category_id, status, position)`, `ads(seller_id, status)`, `subscriptions(seller_id, status, expires_at)`, `invite_events(group_id, invitee_id)`, `payments(status, created_at)`, `posted_messages(group_id, sent_at)`, `violations(group_id, user_id, created_at)`.

---

## 5. MODUL / FAYL TUZILISHI

```
SHOP_BOT/
├── app/
│   ├── main.py                  # kirish nuqtasi: dispatcher, router, middleware
│   ├── config.py                # pydantic-settings (.env)
│   ├── bot.py                   # Bot/Dispatcher fabrikasi, webhook/polling
│   ├── db/
│   │   ├── base.py              # engine, session factory, transaction helper
│   │   ├── models.py            # SQLAlchemy 2.0 modellari (4-bo'limdagi jadvallar)
│   │   └── repo/                # groups.py, ads.py, subs.py, payments.py ...
│   ├── services/                # Telegram importi YO'Q — sof logika
│   │   ├── posting_service.py   # aylanma joylash dvigateli
│   │   ├── tariff_service.py    # limitlar, muddat, eslatmalar
│   │   ├── payment_service.py   # rekvizitlar, chek, tasdiq/rad
│   │   ├── referral_service.py  # havola, shart, bonus
│   │   ├── counter_service.py   # invite link, sanash, /takliflarim
│   │   ├── guard_service.py     # havola/obuna/sanoqchi shartlari, jazo
│   │   ├── cleaner_service.py   # tozalash siyosati
│   │   ├── permission_service.py# ruxsatlar + kesh
│   │   ├── stats_service.py     # statistika, eksport
│   │   ├── text_service.py      # matnlar + placeholder render
│   │   └── notify.py            # adminlarga xabar (xato, chek, kritik)
│   ├── handlers/
│   │   ├── admin/               # 16 ta modul (6-bo'limga qarang)
│   │   ├── seller/              # onboarding, tariff, ads, payment, referral
│   │   ├── user/                # start, takliflarim, obuna tekshirish
│   │   └── group/               # guard, cleaner, chat_member, join_request
│   ├── keyboards/               # inline / reply konstruktorlar
│   ├── middlewares/             # db_session, user_ctx, settings_cache,
│   │                            # throttling, admin_check, error_handler
│   ├── filters/                 # IsSuperAdmin, IsAdmin, IsSeller, HasPermission
│   ├── states/                  # FSM holatlari (e'lon ustasi, to'lov, sozlama)
│   ├── scheduler/
│   │   ├── poster.py            # aylanma joylash (asosiy job)
│   │   ├── reminders.py         # tarif eslatmalari, muddat tekshiruvi
│   │   ├── retention.py         # tozalash, log arxivlash
│   │   └── stats.py             # kunlik jamlanma
│   ├── locales/                 # uz.json, ru.json
│   └── utils/                   # rate_limiter, media(albom), time, validators, logger
├── tests/                       # unit + integration
├── scripts/                     # seed.py, backup.sh, deploy.sh
├── alembic/                     # migratsiyalar
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

---

## 6. ADMIN PANEL (BOSHQARUV PANELI)

`/start` → admin bo'lsa "🛠 Boshqaruv paneli" tugmasi. Har bo'lim inline tugmalar bilan, `◀️ Orqaga` har doim bor.

```
🛠 BOSHQARUV PANELI
├── 📊 Statistika              → kunlik/haftalik/oylik, guruh kesimida, eksport
├── 👥 Guruhlar                → ro'yxat │ +Qo'shish │ sozlash │ pauza │ o'chirish
│      └ Guruh kartasi: nomi, a'zolar, holat, interval, funksiya tumbleri,
│        toifalar, navbat, oxirgi postlar, xatolar, "hoziroq joylash"
├── 🗂 Toifalar                → +Yaratish │ tahrir │ o'chirish │ guruh biriktirish │ tartib
├── 🛒 Sotuvchilar             → +Qo'shish │ bloklash │ tarif berish/uzaytirish │ balans
├── 📢 E'lonlar                → filtr: guruh/toifa/sotuvchi/holat │ tahrir │ o'chirish │
│      │                          pauza │ navbat tartibini o'zgartirish │ hoziroq joylash
│      └ ✅ Moderatsiya navbati (tasdiqlash rejimi yoqilganda)
├── 💳 Tariflar                → +Yaratish │ tahrir │ o'chirish │ limitlar
├── 💰 To'lovlar               → rekvizitlar │ 📥 kelgan cheklar (✅/❌) │ tarix │ hisobot
│      └ Chek kartasi: sotuvchi, tarif, summa, rasm, ⚠️ takroriy chek belgisi
├── 🤝 Referal                 → yoqish/o'chirish │ shart │ bonus turi va miqdori │ statistika
├── 🧮 Sanoqchi                → guruh tanlash │ yoqish │ N soni │ majburiy kanal │
│      │                          foydalanuvchi bo'yicha son │ qo'lda +/- │ nolga tushirish
│      └ reyting: kim ko'p odam qo'shgan (top-20)
├── 🛡 Posbon                  → guruh tanlash │ shart (sanoqchi+obuna) │ havola taqiqi │
│      │                          jazo turi va zinapoyasi │ dry-run │ whitelist domenlar
├── 🧹 Tozalovchi              → guruh tanlash │ nima tozalanadi (5 ta tumbler) │
│      │                          qachon (sekund/kun) │ oxirgi tozalash jurnali
├── 🔑 Ruxsatlar               → +Berish (bitta guruh yoki hammasi) │ turini tanlash │
│                                 muddat │ qaytarib olish │ kimda nima bor
├── 👤 Foydalanuvchilar        → qidiruv │ mute/ban ro'yxati │ ban/unban │ jestoriya
├── ✍️ Bot matnlari            → ro'yxat │ tahrir │ ko'rish (preview) │ zavodga qaytarish
├── ⚠️ Xatolar jurnali         → oxirgi 50 │ filtr │ tafsilot │ "hal qilindi"
├── 🛠 Adminlar                → +Qo'shish │ rol berish │ o'chirish │ amallar tarixi
├── ⚙️ Global sozlamalar       → 🛑 HAMMASINI TO'XTATISH │ vaqt zonasi │ default interval │
│                                 broadcast limiti │ sinov (dry-run) rejimi
└── 📣 Broadcast               → matn/rasm → tasdiq → yuborish hisoboti
```

**Qulaylik uchun:** "🎛 Matritsa" ekrani — barcha guruhlar × funksiyalar (joylash/sanoqchi/posbon/tozalovchi) bir jadval ko'rinishida, ☑️/⬜️ tugmalar bilan. Bir tugma bilan 40 ta guruhda posbonni yoqish mumkin.

---

## 7. SOTUVCHI VA FOYDALANUVCHI PANELLARI

### 7.1. Sotuvchi (`/start` → "🛒 Sotuvchi bo'limi")

```
🛒 SOTUVCHI PANELI
├── 💳 Tarif va to'lov    → tariflar katalogi → "To'lash" → rekvizit → chek yuborish
├── 📢 Mening e'lonlarim  → toifalar bo'yicha guruhlangan ro'yxat
│      └ Har e'lon: tahrir │ o'chirish │ ⏸ pauza / ▶️ yoqish │ statistika (necha marta)
├── ➕ Yangi e'lon        → usta: toifa → nom → tavsif → narx → aloqa → rasmlar (1..N)
│                            → ko'rish (preview) → Yuborish (tasdiq rejimi bo'lsa navbatga)
├── 📅 Mening tarifim     → tarif nomi, tugash sanasi, qolgan kun, e'lon limiti (5/10),
│                            rasm limiti, ⏰ eslatma ko'rsatkichi
├── 🎁 Referal            → shaxsiy havola + nusxalash tugmasi │ takliflar soni │ bonuslar
└── ☎️ Yordam             → admin bilan bog'lanish
```

**E'lon ustasi (FSM, Redis'da saqlanadi):** har qadamda `⬅️ Orqaga`, `❌ Bekor qilish`, `👀 Ko'rish`. Rasm yuklash tugagach `✅ Tayyor`. Preview'da "guruhda qanday ko'rinadi" ko'rsatiladi — sotuvchi xatoni oldin ko'radi.

### 7.2. Foydalanuvchi (guruh a'zosi)

| Amal | Natija |
|---|---|
| `/start` | Bot bilan tanishish + majburiy obuna holati |
| `/takliflarim` | "Siz N ta odam qo'shdingiz, yana M ta qoldi" + shaxsiy havola + nusxalash |
| `/mening_holatim` | Guruhda yozish huquqi bor/yo'q, nima yetishmayapti |
| Guruhda yozish | Shart bajarilmagan bo'lsa: xabar o'chiriladi (soft) yoki mute (hard) + tushuntirish DM'da |
| Havola yuborish | O'chirish → ogohlantirish → (takrorlansa) mute → ban — **ruxsat berilganlarga tegmaydi** |
| Majburiy obuna | Inline `✅ Tekshirdim` tugmasi orqali darhol tekshiriladi (kesh bilan, 60s TTL) |

---

## 8. ASOSIY AVTOMATIK JARAYONLAR (FLOW)

### 8.1. Aylanma joylash (poster)

```
[Poster job, har 5-10 sekund]
   │
   ├─ SELECT groups WHERE posting_enabled AND next_post_at <= now()
   │
   ├─ Har guruh uchun: tinch soatmi? kunlik limit tugaganmi? → o'tkazib yuborish
   │
   ├─ Guruhning toifalari (navbati kelgan) bo'yicha:
   │     next_ad = aktiv e'lonlar ichida kursor'dan keyingi (position bo'yicha),
   │              sotuvchi obunasi aktiv, limiti tugamagan
   │     ├─ yo'q → guruh pauza + admin xabar "navbat bo'sh"
   │     └─ bor → xabar yuborish
   │
   ├─ Yuborish: [albom (1..10 rasm + izoh)] + [reply: tugma "Sotuvchi bilan bog'lanish"]
   │     ├─ FloodWait → retry_after kutish (bu guruhni kechiktirish, boshqasiga tegmaslik)
   │     ├─ Forbidden/BotNotAdmin/ChatNotFound → guruh pauza + admin xabar + error_log
   │     └─ OK → posted_messages'ga message_id yozish
   │
   ├─ Eski e'lonni o'chirish (cleaner.delete_old_ads bo'lsa) — o'z xabari, har doim mumkin
   ├─ Kursor yangilash, post_count++, last_posted_at = now
   └─ next_post_at = now + interval ± jitter  (atomar UPDATE, ikki marta postni oldini oladi)
```

### 8.2. To'lov (yarim avtomatik)

```
Sotuvchi tarif tanlaydi → "To'lash"
   ↓ bot rekvizitlarni beradi (karta raqami + nusxalash tugmasi + izoh talabi)
Sotuvchi chek RASMINI yuboradi
   ↓ bot: file_unique_id hash → takroriy chekmi? (⚠️ belgisi bilan adminga)
Adminga boradi: [Sotuvchi] [Tarif] [Summa] [Chek rasmi]
   [✅ Tasdiqlash]  [❌ Rad etish (sabab yoziladi)]
   ↓ Tasdiqlash
Subscription yaratiladi/uzaytiriladi → limitlar yoqiladi →
sotuvchiga xabar: "Tarifingiz faol: 10 ta e'lon, 3 ta rasm, 30 kun"
   ↓ Rad etish → sabab bilan sotuvchiga xabar → qayta yuborish imkoni
```
**Avtomatik tasdiq yo'q** (firibgarlikdan himoya): admin bankdagi o'tkazmani qo'lda
tekshiradi, keyin alohida tasdiqlash tugmasini bosadi. Phase 5da kartalar admin
panelidan kiritiladi, bir nechtasi navbat bilan ko'rsatiladi; takroriy chek
belgilanadi va tasdiqlash bloklanadi. `receipt_required=false` bo'lsa chek rasmi
shart emas, lekin admin tekshiruvi shart. Bot bank/API orqali pul tushganini
avtomatik tekshirmaydi. Haqiqiy Telegram/PostgreSQL/Redis sinovi hali kerak.
Avvalgi rejaning ixtiyoriy «1 klik» va Stars/Click g'oyalari **joriy MVPga kirmaydi**.

### 8.3. Referal — Phase 8 ✅

```
Yangi odam ?start=ref_<code> bilan kiradi → referrals(registratsiya)
   ↓ shart: settings.trigger = signup | first_payment
Shart bajarildi → bonus: kunlar (obunaga qo'shiladi) | chegirma (%) | balans
   ├─ Anti-firibgarlik: o'zini taklif qilish yo'q, referee UNIQUE, kunlik limit
   └─ Statistika: kim nechta taklif qildi, qancha bonus berildi
```

**Amalda (Phase 8):** faqat yangi **shaxsiy** `/start ref_<kod>`; migratsiyadan
keyin guruhda ko'rilgan foydalanuvchi birinchi shaxsiy startda yangi hisoblanadi.
Migratsiyadan oldingi userlarning shaxsiy tarixi noma'lum — ularga referal
bonusi berilmaydi (`referral_legacy=true`). Standart
`referral_enabled=false`, trigger `first_payment`, 7 kun, kunlik limit 5,
birinchi tasdiqlangan chek kamida 50 000 UZS. `signup` adminning alohida
ogohlantirilgan tanlovi. `days` faol tarif bo'lmasa keyinga qoladi;
`balance`/`discount` chek miqdorini kamaytiradi, rad etilsa rezerv qaytariladi.
Chekni baribir faqat admin bank bilan solishtirib tasdiqlaydi. Guruh sanoqchisining
shaxsiy invite linki va `/takliflarim` bu referaldan mutlaqo alohida. Batafsil
xavfsizlik cheklovlari va real muhit sinovlari `HOLAT.md` §4/9 da.

### 8.4. Sanoqchi (har guruhda alohida) — Phase 7 ✅

```
Foydalanuvchi guruhga kiradi (yoki uni kimdir qo'shadi)
   ├─ chat_join_request faqat linkni vaqtincha qayd etadi; o'zi kredit EMAS
   ├─ chat_member.invite_link → bot yaratgan shaxsiy link egasini topadi
   │     └─ xizmat xabari fallback ("X added Y"); haqiqiy link keyin kelsa ustun
   ├─ Tekshiruvlar: invitee yangimi (UNIQUE) │ o'zi o'zini emasmi │
   │                min_stay_minutes o'tdimi │ kunlik limit (guruh vaqt mintaqasi)
   └─ scheduler getChatMember bilan hali a'zoligini tekshiradi →
      counter_totals.inviter += 1  (bir odam bir guruhda BIR MARTA)
Chek: majburiy kanal obunasi (getChatMember, bot o'zi ham kanal admini) + counter N
   ├─ ikkisi ham OK → yozish huquqi ochiladi (hard rejimda bot qo'ygan mute olinadi)
   ├─ SOFT (standart): faqat xabar o'chiriladi; HARD: qo'shimcha mute
   └─ /takliflarim (shaxsiy chat) → "N qo'shildi, M qoldi" + shaxsiy havola
Admin panel: har guruh uchun N, qolish muddati, kunlik/havola limiti, manbalar,
kanal talabi (guruh/global kanal), sinov/jonli tasdiq, foydalanuvchi bo'yicha
qo'lda +/-/nol va counter_audit/action_log tarixi.
```

**Ishga tushirish:** yangi guruhda sanoqchi O'CHIQ; yoqilganda ham dry-run.
Haqiqiy o'chirish/mute alohida jonli tasdiq va Telegram huquqlari tekshiruvidan
keyin ishlaydi. Aniq kanal berilmagan: admin panelda kanal ID/@username va bot
adminligini tekshirib kiritiladi. API noma'lum bo'lsa fail-open (jazo yo'q).

### 8.5. Posbon (guard) va ruxsatlar — Phase 6 ✅

**Foydalanuvchi talabi:** posbon, tozalovchi va istisnolar **to'liq nazorat ostida,
har bitta guruh uchun alohida boshqariladigan** bo'lishi kerak. Har guruhdagi
siyosat/global switch/guruh pauzasi alohida qatlam: global o'zgarish guruh
qoidalarini o'zgartirmaydi. Boshqarish: admin paneli → guruh → posbon/tozalovchi;
sozlama va sabab-amal tarixi `action_log`/`group_message_actions`da ko'rinadi.

```
Guruhda xabar keldi
  ↓
[0] Faol superguruh + bot admin + guruh switch + global kill/maintenance tekshiruvi
  ↓
[1] Foydalanuvchining guruh/global ruxsati (faol, muddati o'tmagan) yoki admini?
    full_exempt / guard_exempt / cleaner_exempt / link_allowed → tegishli amal yo'q
  ↓
[2] Havola (matn va text_link entity), forward, @mention, taqiqlangan so'zlar;
    domen + subdomen oq ro'yxat. Har guruhda filterlar/istisnolar mustaqil.
  ↓
[3] (guruh_id, xabar_id) UNIQUE xabar amali + qoidabuzarlik sababi DB'da yoziladi
  ├─ yangi/tezkor yoqilgan policy: dry_run → FAQAT jurnal, Telegram amali yo'q
  └─ admin jonli rejimni alohida tasdiqlagan: bot huquqi/pin/ruxsat/pauza qayta
     tekshiriladi → deleteMessage → muvaffaqiyatdan keyin warnings oshiriladi
     warn (standart) → DM; mute (tanlansa) → muddatli cheklash;
     ban → FAQAT shu guruhda alohida BAN rejimi tasdiqlangandan keyin,
     warning chegarasining ikki barobarida. Qo'lda jazo ham admin tasdig'i bilan.
```

Guruhdagi ogohlantirishlar `warn_window_hours`, `warn_limit`, `mute_minutes` va
`penalty` bilan sozlanadi. Istisno: turi, foydalanuvchi ID, qamrov (guruh yoki
global), sabab, 1–365 kun/doimiy muddat; ko'rish, qaytarib olish va audit.
Aktiv ruxsatlar qisman unique indeks bilan takrorlanmaydi, muddati o'tgani
tarixda qoladi. **Phase 7:** obuna/N cheki `counter_settings`dagi guruhga xos
switchlar orqali posbonning yagona xabar-amali yo'liga xavfsiz ulangan;
`guard_settings.require_counter`/`require_subscription` eski zaxira maydonlari
alohida jazo yo'liga ulanmaydi (ikki marta o'chirish yoki yashirin yoqishni oldini oladi).

### 8.6. Tozalovchi — Phase 6 ✅

| Har guruh uchun mustaqil tur | Amal | Qachon |
|---|---|---|
| Kirdi-chiqdi / xizmat xabarlari | `deleteMessage` (yoki dry-run jurnal) | Kelganda yoki 0–3600 s kechiktirib |
| Havolalar | Guruh oq ro'yxatidagi domenlarni saqlab delete | Kelganda yoki kechiktirib |
| Qoidabuzar xabarlar | Posbon filtrini namunaga oladi, **o'zi jazo bermaydi** | Posbon o'chirilgan bo'lsa ham ixtiyoriy ishlaydi |
| **Eski e'lonlar** | `posted_messages`dan har e'londan `keep_last_ads` ta qoldirish, pinlanganlarni saqlash | **Yangi postdan keyin**; dry-run oldinroq xabarni o'chirmaydi |
| Eski loglar/statistika | Retention job | Belgilangan saqlash muddati tugaganda |

Bitta xabarga faqat bitta posbon/tozalovchi qarori; dry-run posbon xabarini
jonli cleaner chetdan o'chirmaydi. `pending` ishlarni scheduler CAS bilan oladi;
noaniq `running` qayta urinilmaydi. Admin kechiktirilgan ishni bekor qila oladi,
lekin Telegram'ga yuborilgan chaqiruvni ortga qaytara olmaydi. Huquq yo'qolsa
guruh pauza va admin xabardor; global switch/kutilmagan pauza API oldidan DB'dan
keshsiz qayta tekshiriladi. Yangi siyosatlar standartda o'chirilgan va dry-run;
eski Phase 4 tugmasi ham jonli rejimni tasdiqsiz yoqmaydi.

### 8.7. Xato bo'lganda (sizning talabingiz)

| Xato | Harakat |
|---|---|
| Bot guruhdan chiqarildi / huquq olindi | Guruh **pauza** + adminga darhol xabar + `error_log` |
| Guruh topilmadi (o'chirilgan) | Guruh **pauza** + admin panelda "🗑 O'chirilgan" belgisi |
| 3 marta ketma-ket post xatosi | Guruh **pauza** + sabab bilan admin xabari |
| FloodWait (429) | `retry_after` kutish, guruh kechiktiriladi, xato emas |
| DB xatosi | Retry (3 marta) → bo'lmasa `error_log` + super adminga |

---

## 9. AYLANMA JOYLASH DVIGATELI (YADRO) — batafsil

Bu loyihaning eng muhim qismi, shuning uchun alohida bo'lim.

**Navbat modeli:** `ads.position` + `category_rotation.cursor_ad_id`.
- Har toifada e'lonlar `position` bo'yicha tartiblangan (100, 200, 300... — orasiga qo'shish oson).
- Kursor "oxirgi qaysi e'lon joylandi" ni saqlaydi → keyingisi = `position > cursor` bo'lgan birinchi aktiv e'lon; oxiriga yetganda → eng kichik `position`ga **aylanadi** (boshidan).
- **Admin qo'lda tartibni o'zgartirsa** — faqat `position` almashadi, mantiq buzilmaydi (sizning "navbat tartibini o'zgartirish" talabi).
- Pozitsiya orasi tugasa (masalan orasiga 10 marta qo'shildi) — avtomatik qayta raqamlash.

**Navbatdan chiqariladigan e'lonlar (avtomatik o'tkazib yuboriladi):**
1. `status != active` (pauza, rad etilgan, o'chirilgan)
2. Sotuvchi obunasi muddati tugagan (`subscriptions.expires_at < now`)
3. Tarif kategoriyaga ruxsat bermaydi
4. Sotuvchi bloklangan
5. Guruh yoki toifa o'chirilgan

**Interval mantiqi:**
- Asosiy manba: `group_settings.interval_sec` (guruh uchun), `categories.interval_override` bo'lsa — u ustun.
- Minimal: **60 sekund** (Telegram limitlari), tavsiya: 15-60 daqiqa.
- **Jitter:** `next_post_at = now + interval * random(0.9, 1.1)` — hamma guruh bir vaqtda post qilmasligi uchun.
- **Kunlik limit:** `daily_post_limit` (masalan 50). Yetganda keyingi kunga o'tadi.
- **Tinch soatlar:** `quiet_start..quiet_end` oralig'ida joylanmaydi, keyingi ruxsat etilgan vaqtga suriladi.

**Ishonchlilik:**
- Atomar yangilash: `UPDATE group_rotation SET next_post_at = :new, last_post_at = :now WHERE group_id = :id AND next_post_at = :old` — `rowcount = 0` bo'lsa, boshqa worker oldin olgan → ikkinchi marta post qilinmaydi.
- Restart: barcha holat DB'da → hech narsa yo'qolmaydi, dublikat bo'lmaydi.
- Bir vaqtda bir necha poster process bo'lsa: PostgreSQL `SELECT ... FOR UPDATE SKIP LOCKED`.
- **Global pauza bo'lsa**, `next_post_at` o'tgan bo'lsa ham post qilinmaydi va qarz to'planmaydi (yoki admin tanlovi: pauzadan keyin to'planib qolgan postlarni bir yo'la yuborish/o'tkazib yuborish).

**"Hoziroq joylash" tugmasi:** navbatni buzmagan holda tanlangan e'lonni darhol joylaydi va kursorni shu e'longa o'rnatadi (keyingi post undan keyin davom etadi).

**Albom tuzilishi:**
```
1-xabar:  [rasm1..rasmN]  +  izoh (nom, tavsif, narx, aloqa matni, #toifa)
2-xabar:  🔘 "Sotuvchi bilan bog'lanish" (inline: URL yoki @username yoki telefon)
```
- Rasmlar soni tarif bilan cheklangan. **10 dan ortiq** rasm ruxsat etilsa — bir nechta albomga bo'linadi (Telegram bir albomda max 10 rasm).
- Har rasm `file_id` sifatida saqlanadi (qayta yuklash shart emas, trafik va disk tejaladi).
- `protect_content` (nusxalashni taqiqlash) — admin panelda ixtiyoriy tumbler.

---

## 10. KATTA AUDITORIYA UCHUN MASSHTABLASH

"Katta auditoriya" = ko'p guruh + ko'p foydalanuvchi + ko'p xabar. Quyidagilar hisobga olingan.

### 10.1. Telegram cheklovlari (rasmiy) va yechim

| Limit | Qiymat | Yechim |
|---|---|---|
| Bitta chatga | ~1 xabar/sekund | Guruhga min 1 xabar/2 sekund (limiter) |
| Bitta guruhga | **20 xabar/daqiqa** | Guruh bo'yicha token bucket + kunlik limit + bir guruhga bir necha toifa biriktirilsa jami hisob |
| Umumiy bulk | **25 xabar/sekund (loyiha limiti)** | Redis global limiter; broadcast navbat orqali (Docker/log) |
| 429 FloodWait | `retry_after` | Har doim hurmat qilinadi; guruhga xos kechiktirish (boshqa guruhlar ishlashda davom etadi) |
| Albom | 2-10 element | 10 dan ko'p rasm → bir necha albom |
| Xabar o'chirish | 48 soat / admin huquqi | Qayta post oldidan o'chirish + xatoga chidamli |
| Webhook | 443/80/8443 portlari | Caddy/Nginx TLS |

### 10.2. Kapasitet baholash

| Parametr | 200 guruh | 1000 guruh |
|---|---|---|
| Post intervali 30 daq | 400 post/soat | 2000 post/soat |
| API chaqiruv (2 xabar/post) | ~800/soat ≈ 0.2/sek | ~4000/soat ≈ 1.1/sek |
| Talab | juda qulay | qulay (lekin webhook tavsiya) |
| Server | 2 vCPU / 4 GB | 4 vCPU / 8 GB |
| Baza | PostgreSQL majburiy | PostgreSQL + Redis majburiy |

Xaridorlar soni (10 000+ sotuvchi) uchun ham shu arxitektura yetadi, chunki "og'ir" qism — xabar yuborish, u esa navbat + limiter bilan nazorat qilinadi.

### 10.3. Texnik yechimlar

1. **Webhook rejimi** (`.env` bilan yoqiladi) — long-polling'dan ko'proq yuklamaga chidaydi. Kichik bosqichda polling ham bo'ladi (kod ikkalasini qo'llaydi).
2. **`allowed_updates`** — faqat kerakli update turlari (`message`, `callback_query`, `chat_member`, `my_chat_member`, `chat_join_request`) → trafik kamayadi.
3. **Poster alohida process** — bot handler'lari sekinlashmaydi.
4. **Sozlamalar keshi (Redis + in-memory)** — har xabar uchun DB'dan o'qish yo'q. O'zgarishda `settings_version` oshadi → kesh avtomatik yangilanadi (**"botni qayta yoqmasdan darhol kuchga kiradi"** — sizning talabingiz shu tarzda bajariladi).
5. **Og'ir ishlar navbatga** — broadcast, eksport, rasm yuklash tekshiruvi kabi ishlar fon vazifasida.
6. **DB optimizatsiyasi** — indekslar, `stats_daily` jamlanmasi, eski loglarga retention.
7. **Loglar** — faylga aylanma (rotation) + `error_log` jadvaliga faqat muhimlari (DB shishib ketmasligi uchun).
8. **Kerak bo'lsa gorizontal o'sish** — bot processini bir necha nusxada (webhook) ishga tushirish; poster `SKIP LOCKED` bilan xavfsiz.

---

## 11. XAVFSIZLIK, RISKLAR, HUQUQIY ESLATMALAR

### 11.1. Texnik risklar

| Risk | Ehtimol | Ta'sir | Choralar |
|---|---|---|---|
| Bot huquqini yo'qotishi | Yuqori | Joylash to'xtaydi | `my_chat_member` kuzatuvi, avtopauza + admin xabari, kunlik "huquq tekshiruvi" job |
| FloodWait / bloklash | O'rta | Kechikish | Rate limiter, jitter, backoff, kunlik limit |
| DB shishib ketishi | O'rta | Sekinlashish | Retention (loglar 90 kun), `stats_daily` jamlanma, indekslar |
| Bir e'lon ikki marta post | O'rta | Sotuvchi shikoyati | Atomar UPDATE + lock + `post_log` tekshiruvi |
| To'lov cheki firibgarligi | Yuqori | Pul yo'qotish | `file_unique_id` hash, faqat admin tasdiq, chek tarixi |
| Sozlamalar keshining eskirishi | Past | Noto'g'ri ishlash | `settings_version` + har o'zgarishda invalidatsiya + 60s TTL zaxira |
| Server o'chishi | Past | To'xtash | Docker `restart: always` + systemd + health endpoint + zaxira nusxa |

### 11.2. Huquqiy / Telegram siyosati risklari (ochiq aytaman)

1. **"N ta odam qo'shish" majburiyati** — bu Telegram'ning "majburiy obuna / invite-spam" amaliyotiga kiradi. Texnik jihatdan ishlaydi, lekin:
   - foydalanuvchi shikoyatlari ko'paysa bot cheklanishi mumkin;
   - shuning uchun "**soft rejim**" (xabarni o'chirish) standart qilib olinadi, "hard" (mute) — admin tanlovi;
   - kunlik limit va "bir odam bir marta" qoidalari firibgarlikni kamaytiradi.
2. **Ommaviy avto-posting** — reklama botlari uchun odatiy, lekin guruh egalari ruxsati asosida ishlaydi (sizning modelingizda admin o'zi biriktiradi) — bu xavfsizroq.
3. **To'lovlar** — bot pulni ushlamaydi (faqat rekvizitni ko'rsatadi, chekni admin tasdiqlaydi). Bu huquqiy jihatdan eng xavfsiz variant. Agarda kelajakda **integratsiyalangan to'lov** (Click/Payme/Stars) qo'shilsa — bu alohida modul, alohida Yuridik shaxs/merchant talab qilinadi.
4. **Shaxsiy ma'lumotlar** — `users` jadvalida minimal ma'lumot saqlanadi. "O'chirish" so'rovi bo'lsa, `scripts/` da bir buyruq bilan o'chirish funksiyasi qo'shiladi.
5. **Sotuvchi kontenti** — bot javobgar emas, lekin **moderatsiya + blacklist** qo'yiladi (firibgar e'lonlar uchun).

---

## 12. TEST VA QA REJASI

| Bosqich | Nima test qilinadi |
|---|---|
| Unit (pytest) | Navbat aylanmasi, limitlar, referal shartlari, sanoqchi hisobi, havola filtri regexlari, vaqt/jitter hisobi, matn render |
| Integratsiya | To'liq to'lov sikli, e'lon qo'shish ustasi, posbon jazosi, tozalash |
| Telegram test muhiti | Test bot + test supergroup + test kanal: haqiqiy `chat_member`, `chat_join_request`, invite link attributsiyasi, mute/ban |
| Chek-list (go-live) | Bot adminmi? Privacy offmi? Supergroup'mi? Kanalga bot adminmi? Interval limitga mosmi? Zaxira nusxa ishlayaptimi? |
| Yuklama testi | Simulyatsiya: 200 guruh + 5000 e'lon, 24 soatlik "tezlashtirilgan" yugurish; 429 lar soni, o'rtacha kechikish, DB yuklamasi |
| Qayta yonish testi | Poster job o'rtasida `kill -9` → dublikat post yo'qligi tekshiriladi |

---

## 13. DEPLOY, ZAXIRA NUSXA, MONITORING

```
docker-compose:
  ├ bot         (webhook, restart: always)
  ├ poster      (scheduler worker)
  ├ postgres    (volume + kunlik pg_dump)
  ├ redis       (AOF)
  └ caddy       (TLS, domen → bot)
```

- **.env** (git'ga tushmaydi): `BOT_TOKEN, ADMIN_IDS, DB_URL, REDIS_URL, WEBHOOK_URL, SECRET_PATH, TZ, LOG_LEVEL, SENTRY_DSN(opt)`
- **Zaxira nusxa:** kunlik `pg_dump` → 14 kun saqlanadi; tiklash skripti `scripts/restore.sh` va sinovdan o'tkaziladi.
- **Monitoring:** `:8080/health` (Docker/uptime robot uchun), `/stats` (token bilan), Telegram'ga kritik xabarlar.
- **Yangilash:** `git pull → alembic upgrade head → docker compose up -d`
- **Mavjud loyihaga ta'sir:** yangi bot **butunlay alohida papkada** (`SHOP_BOT/`), `AVTO_BOT/` **teginilmaydi**. Umumiy hech narsa yo'q (token, baza, fayllar). Xohlasangiz keyin `health.py` va `rate_limiter.py` g'oyalaridan nusxa olish mumkin — lekin kod umumiy bo'lmaydi.
- **Papka nomi** — men `SHOP_BOT/` deb oldim; xohlagan nomingizga o'zgartirish bir buyruq (masalan `MARKET_BOT/`, `ELON_BOT/`).

---

## 14. BOSQICHLAR (ROADMAP) VA MUDDAT

Har bosqich oxirida **sizga ko'rsataman → tasdiqlaysiz → keyingisiga o'taman**. Kod bir bosqichda hammasi birdan yozilmaydi.

| # | Bosqich | Nima kiradi | Natija (test qilsa bo'ladi) | Taxminiy vaqt |
|---|---|---|---|---|
| **0** | Poydevor | Docker, `.env`, DB, Alembic, logger, kesh, health, xato ushlagich | Bot ishga tushadi, "Salom" deydi, DB ulangan | 6-8 soat |
| **1** | Guruh va toifa | Guruh qo'shish (bot admin tekshiruvi), pauza, interval, toifa CRUD, biriktirish, admin panel skeleti | Admin panelda guruh/toifa boshqarish ishlaydi | 10-14 soat |
| **2** | Sotuvchi, tarif, obuna | Sotuvchi CRUD, tarif CRUD, limitlar, obuna berish/uzaytirish, eslatmalar | Admin tarif beradi, sotuvchi "Mening tarifim" ko'radi | 10-12 soat |
| **3** | E'lon + moderatsiya | E'lon ustasi, rasmlar, albom, ko'rish, tasdiq rejimi, "Mening e'lonlarim" | E'lon qo'shiladi, admin tasdiqlaydi | 12-16 soat |
| **4** | **Aylanma joylash** | Navbat, kursor, interval, jitter, tinch soat, limiter, eski postni o'chirish, "hoziroq joylash", tartib o'zgartirish | Guruhga e'lonlar avtomatik keta boshlaydi ⭐ | 10-14 soat |
| **5** | To'lovlar | Rekvizitlar, chek qabul qilish, tasdiq/rad, avtomatik obuna, tarix | To'liq pul sikli ishlaydi 💰 | 8-10 soat |
| **6** ✅ | Posbon + tozalovchi + ruxsatlar | Har guruhda mustaqil filtr/jazo, dry-run, tozalash, muddatli ruxsatlar (obuna/sanoqchi sharti Phase 7da) | Guruh "o'zini tozalaydi" | 14-18 soat |
| **7** ✅ | Sanoqchi | Shaxsiy invite linklar, attributsiya, `/takliflarim`, admin qo'lda tuzatishi, majburiy kanal | "N odam qo'shish" tizimi ishlaydi (offline; deploy sinovi qolgan) | 12-16 soat |
| **8** ✅ | Referal + statistika + matnlar + xato jurnali | Referal sikli, grafik/hisobot, eksport, matn tahriri, xato paneli, broadcast | To'liq panel (341 offline test) | 12-16 soat |
| **9** | Sayqal | Testlar, yuklama smoke, deploy skripti, backup/restore, README, video ssenariyi | Kod/oflayn sinov ✅; jonli qabul va video yozish hali qolgan | 10-14 soat |

### ✅ Phase 0 — BAJARILDI (2026-10-15)

| Bajarilgan ish | Fayl / buyruq |
|---|---|
| Docker Compose: bot, poster, PostgreSQL 16, Redis 7, Caddy (HTTPS) | `docker-compose.yml`, `Dockerfile`, `Caddyfile` |
| 41 jadvalli baza sxemasi + boshlang'ich Alembic migratsiyasi | `app/db/models.py`, `alembic/versions/f789aa7b756f_*.py` |
| Konfiguratsiya va validatsiya (majburiy maydonlar, xavfsizlik tekshiruvi) | `app/config.py`, `.env.example` |
| Loglar (kunlik aylanish, 14 kun), xato jurnali + adminlarga xabar | `app/logging_setup.py`, `app/services/notify.py` |
| Middleware: DB sessiya, foydalanuvchi konteksti, anti-flood, texnik rejim/kill switch | `app/middlewares/` |
| Boshqaruv paneli: **📊 Statistika** va **⚙️ Sozlamalar** to'liq ishlaydi (kill switch, texnik rejim, interval, yordam kontakti) | `app/handlers/admin/panel.py`, `settings.py` |
| Guruh hayoti: bot qo'shildi/chiqarildi, huquqlar tekshiruvi, adminga ogohlantirish | `app/handlers/group/lifecycle.py`, `app/services/group_service.py` |
| Rejalashtiruvchi: heartbeat, huquq tekshiruvi (15 daq), log tozalash, kunlik statistika | `app/scheduler/` |
| HTTP: `/health`, `/stats` (token bilan), webhook va polling rejimi | `app/web/server.py` |
| Seed skript (adminlar, 22 sozlama, 20 matn, 3 namuna tarif) | `python -m scripts.seed` |
| Zaxira nusxa va tiklash skriptlari | `scripts/backup.sh`, `scripts/restore.sh` |
| **58 test** (sxema, servislar, filtrlar, seed, infratuzilma, simlar) — hammasi o'tadi | `pytest` |

**Tekshirilgan:** SQLite'da migratsiya (upgrade/downgrade), 41 jadval, DDL PostgreSQL uchun,
`/health` va `/stats` javoblari, seed natijasi, `app.main` importi.

**Keyingi qadam:** Phase 1 — Guruhlar va toifalar bo'limini to'liq yozish (CRUD, interval,
pauza/yoqish, toifa biriktirish, funksiya tumbleri).

### ✅ Phase 1 — BAJARILDI (2026-10-15)

| Bajarilgan ish | Fayl |
|---|---|
| Guruhlar bo'limi: ro'yxat, kartochka, huquqlar tekshiruvi, pauza/yoqish, o'chirish (tasdiq bilan) | `app/handlers/admin/groups.py`, `app/keyboards/groups.py` |
| Funksiyalar boshqaruvi: **matritsa** (barcha guruhlar × 5 funksiya), tumblerlar, ekran moslamasi (`origin`) | `app/keyboards/groups.py`, `app/keyboards/callbacks.py` |
| Guruh sozlamalari (FSM): interval (1–1440 daq), jitter (0–30%), kunlik limit, tinch soatlar (`23:00-08:00` / `off`) | `app/handlers/admin/groups.py`, `app/states.py`, `app/utils/text.py` |
| Toifalar bo'limi: yaratish (emoji bilan), nomini o'zgartirish, guruhga biriktirish/uzish, alohida interval, moderatsiya rejimi, tartibni o'zgartirish, o'chirish | `app/handlers/admin/categories.py`, `app/services/category_service.py`, `app/keyboards/categories.py` |
| Servis qatlami: huquq tekshiruvi (`RightsCheck`), guruh CRUD, toifa CRUD + navbat kursori (`category_rotation`) | `app/services/group_service.py`, `app/services/category_service.py` |
| Panel: bo'lim tugmalarida jonli hisoblagichlar (guruhlar, toifalar, to'lovlar, xatolar...) | `app/keyboards/admin.py`, `app/services/stats_service.py` |
| **Offline E2E testlar** (haqiqiy Dispatcher + fake Bot API sessiyasi, tarmoqsiz) | `tests/fake_telegram.py`, `tests/test_admin_flows.py` |
| **Jami 104 test — hammasi o'tadi** | `pytest` |

**Yo'l-yo'lakay topilgan va tuzatilgan 4 ta jiddiy xato (Phase 0 dan meros):**

| # | Xato | Oqibati | Yechim |
|---|---|---|---|
| 1 | Filtr imzosi `(event, data)` edi | `IsAdmin`/`IsSeller`/`HasPermission` **har chaqiruvda yiqilardi** — butun admin panel ishlamasdi | aiogram 3 talab qilgan `(event, **kwargs)` imzosiga o'tkazildi |
| 2 | `F.chat.type == "private"` callback'da `None` qaytaradi | Admin panelning **barcha inline tugmalari** javob bermasdi | `PrivateChat()` / `GroupChat()` filtrlari (`app/filters/chats.py`) |
| 3 | SQLite naive, PostgreSQL aware datetime qaytaradi | `TypeError: can't subtract offset-naive and offset-aware` (obuna muddati, `last_seen`) | `ensure_aware()` yordamchisi (`app/utils/time.py`) |
| 4 | FSM sozlamalari `value` maydonidan kalit izlardi | «⏱ Interval», «📈 Jitter», «📆 Limit», «🌙 Tinch soatlar» tugmalari `KeyError` berardi | `action` maydonidan o'qiladigan qilindi |

> Bu — aynan "offline E2E" testlarning foydasi: tarmoqqa chiqmasdan, tugmalarni
> haqiqiy bosib ko'ramiz. Har yangi bo'lim shu usulda tekshiriladi.

**Tekshirilgan:** 104 test (Phase 0 + Phase 1), `compileall`, `app.main`/`build_root_router` importi,
Alembic diff bo'sh (sxema o'zgarmagan), seed skripti ishlaydi.

**Keyingi qadam:** Phase 2 — Sotuvchilar, tariflar va obunalar (admin sotuvchi qo'shadi,
tarif CRUD, limitlar, obuna berish/uzaytirish, muddat eslatmalari, sotuvchi paneli).

### ✅ Phase 2 — BAJARILDI (2026-10-15)

| Bajarilgan ish | Fayl |
|---|---|
| Sotuvchilar bo'limi: ro'yxat (sahifalash, holat filtri), qidiruv, kartochka, qo'shish (FSM: ID → nom → telefon → kontakt), bloklash (sabab bilan) / blokdan chiqarish, tasdiqlash, izoh, profilni tahrirlash, soft-delete | `app/handlers/admin/sellers.py`, `app/keyboards/sellers.py` |
| Tariflar bo'limi: yaratish ustasi (nom → narx → muddat → e'lon limiti → rasm limiti), tahrirlash (nom, tavsif, narx, muddat, limitlar), faol/pauza, sinov belgisi, tartibni almashtirish (⬆/⬇), o'chirish (obuna bo'lsa — faqat to'xtatish) | `app/handlers/admin/tariffs.py`, `app/keyboards/tariffs.py` |
| Obunalar: tarif berish (sotuvchi kartochkasidan), uzaytirish, muddatni qo'lda o'zgartirish, e'lon limitini qo'lda berish, obunalar tarixi, sotuvchi blokdan chiqarilganda obuna hisobga olinadi | `app/services/subscription_service.py`, `app/handlers/admin/sellers.py` |
| **Sotuvchi paneli**: "Mening tarifim" (qolgan kun, limit, holat), tariflar katalogi (narx/limitlar), referal kodi (kerak bo'lsa avtomatik yaratiladi), yordam; sotuvchi `/start`ida holat ko'rsatiladi | `app/handlers/seller/__init__.py`, `app/keyboards/seller_panel.py`, `app/handlers/common.py` |
| Servis qatlami: sotuvchi CRUD + telefon normalizatsiyasi, tarif CRUD + narx tahlili (`150 000`, `150,000`, `150.000`, `150000 so'm`) | `app/services/seller_service.py`, `app/services/tariff_service.py` |
| Rejalashtiruvchi: **obuna eslatmalari** (har soatda, `subscription_reminder_days` kun qolganda, bir marta) va **muddati o'tganlarni yopish** (30 daqiqada, `subscription_grace_days` → `grace` → `expired`, e'lonlar `expired` bo'ladi, sotuvchi xabardor qilinadi) | `app/scheduler/jobs.py`, `app/scheduler/runner.py` |
| Yangi sozlamalar: `subscription_reminder_days=3`, `subscription_grace_days=0`, `bot_username`; matnlar 20 → **26** (`seller.*` — 6 ta yangi) | `app/services/settings_service.py`, `app/services/text_service.py` |
| **Jami 164 test — hammasi o'tadi** (13 ta alohida test fayli, tarmoqsiz va Redis'siz) | `pytest` |

**Testlar tarkibi (Phase 2 qo'shgani):**

| Test fayli | Nima tekshiradi | Soni |
|---|---|---|
| `tests/test_seller_service.py` | Sotuvchi CRUD, telefon normalizatsiyasi, holat o'tishlari, soft-delete, referal kod, qidiruv | 12 |
| `tests/test_tariff_and_subscription.py` | Narx tahlili/formatlash, tarif CRUD + tartib, obuna berish/uzaytirish/limitlar, `is_valid`, `ads_left`, eslatmalar, grace, statistika | 24 |
| `tests/test_phase2_flows.py` | **E2E**: admin tugmalarini bosib sotuvchi qo'shadi, tarif yaratadi, tarif beradi, uzaytiradi, bloklaydi; sotuvchi o'z panelini ko'radi; job'lar ishlaydi | 24 |

**Yo'l-yo'lakay topilgan va tuzatilgan xatolar (Phase 2):**

| # | Xato | Oqibati | Yechim |
|---|---|---|---|
| 1 | `fmt_amount` valyuta kodini xom chiqarardi | Tarif narxi **"150 000 UZS"** ko'rinishida edi (o'zbek foydalanuvchisi uchun tushunarsiz) | `CURRENCY_LABELS` (`UZS→so'm`, `USD→$`, `EUR→€`, `RUB→₽`) qo'shildi — `app/utils/text.py` |
| 2 | `parse_price("150,000")` vergulni kasr deb o'qirdi | Admin "150,000" kiritsa narx **150 so'm** bo'lib qolardi — pul yo'qolishi mumkin edi | `_normalize_separators`: ikkala `,` va `.` bo'lsa oxirgisi kasr, aks holda 3 xonali dum = minglik |
| 3 | `format_price` `currency` `None` bo'lganda "50 000 None" berardi (flush qilinmagan obyekt) | Panelda/bildirishnomada buzuq matn | Standart `UZS` qiymati ishlatiladi |
| 4 | `tariffs_label` flush qilinmagan tarifda ham "⏸" ko'rsatardi | Yangi tarif ro'yxatda darhol "pauza" bo'lib ko'rinardi | Belgisi faqat `is_active is False` bo'lganda |
| 5 | `normalize_phone` qavs/chiziqchalarni noto'g'ri qoldirardi | Bir xil raqam ikki xil ko'rinishda yozilishi mumkin edi | Faqat raqamlar + boshidagi `+`, uzunlik kesiladi: `"+998 (90) 111-22-33"` → `"+998901112233"` |

> **Eslatma (o'lchov uchun):** `tests/test_phase2_flows.py` yozilganda 6 test qizil edi — sabab
> **mahsulot kodida emas, testda** edi: test `commit()`dan keyin `expire_all()` chaqirib, ORM
> obyekt atributiga sinxron murojaat qilardi (`MissingGreenlet`). Yechim — ID'larni commit'dan
> **oldin** olib qo'yish (test shabloni shunga o'tkazildi). Ishlab chiqarish kodida bu xavf
> yo'q, chunki sessiya `expire_on_commit=False` bilan yaratilgan.

**Tekshirilgan:** 164 test o'tadi; har bir test fayli **alohida** ham o'tadi (tartibga bog'liqlik yo'q);
Alembic autogenerate diff **bo'sh** (Phase 2 sxemani o'zgartirmadi — Sotuvchi/Tarif/Obuna
jadvallari Phase 0 da qo'yilgan edi); `app.main` importi va routerni yig'ish ishlaydi;
seed toza bazada: **25 sozlama**, **26 matn**, 3 namuna tarif.

**Keyingi qadam:** Phase 3 — E'lonlar va moderatsiya (e'lon ustasi, albom bilan rasmlar,
"Tekshiruvda → Tasdiqlangan/Rad etilgan" rejimi, "Mening e'lonlarim", e'lon limitini
obunadan tekshirish).

### ✅ Phase 3 — BAJARILDI (2026-10-15)

| Bajarilgan ish | Fayl |
|---|---|
| **E'lon ustasi** (sotuvchi): toifa → sarlavha → tavsif → narx → aloqa → rasmlar → ko'rish (preview) → yuborish; har qadamda ⬅️ Orqaga / ⏭ O'tkazib yuborish / ❌ Bekor qilish | `app/handlers/seller/ads.py`, `app/keyboards/ads.py`, `app/states.py` |
| **«Mening e'lonlarim»**: ro'yxat (sahifalash + holat filtri), kartochka, statistika (necha marta joylandi, nechta guruh), tahrirlash (sarlavha/tavsif/narx/aloqa/toifa), pauza↔yoqish, o'chirish (tasdiq bilan) | `app/handlers/seller/ads.py` |
| **Rasmlar**: faqat `file_id` saqlanadi (disk tejash), tarifdagi `max_photos` bilan cheklanadi, qo'shish/o'chirish va qayta raqamlash, albom chegarasi (10) hisobga olingan | `app/services/ad_service.py` |
| **Moderatsiya**: "Tekshiruvda" navbati, e'lon kartochkasi **rasmlari bilan** (albom + alohida tugmalar xabari), ✅ Tasdiqlash, ❌ Rad etish (6 tayyor sabab yoki qo'lda yozish), rad etilganda **limit qaytariladi** | `app/handlers/admin/mods.py`, `app/keyboards/mods.py` |
| **📢 E'lonlar (admin)**: barcha e'lonlar holat bo'yicha filtr bilan, kartochka, pauza/yoqish, o'chirish, 🕘 moderatsiya tarixi (kim/qachon/sabab) | `app/handlers/admin/mods.py` |
| Servis qatlami: qoralama, maydon tekshiruvlari, navbat pozitsiyasi (100, 200, 300...), yuborish (limitdan hisoblash), tasdiq/rad, tahrir mantiqi (`draft`→qayta yuborish, `active`→jurnalga "revised") | `app/services/ad_service.py` |
| Sotuvchi e'lon yuborganda **adminlarga xabar**; tasdiq/rad/to'xtatishda **sotuvchiga xabar** (matnlar bazasidan) | `app/handlers/seller/ads.py`, `app/services/text_service.py` |
| Yangi matnlar: `ad.submitted`, `ad.approved`, `ad.rejected`, `ad.paused` (jami 26 → **30**) | `app/services/text_service.py` |
| Panel: «📢 E'lonlar» va «✅ Moderatsiya» bo'limlari ishga tushdi (tugmalarda hisoblagichlar allaqachon bor edi) | `app/keyboards/admin.py`, `app/handlers/admin/panel.py` |
| **Jami 221 test — hammasi o'tadi** | `pytest` |

**Testlar tarkibi (Phase 3 qo'shgani):**

| Test fayli | Nima tekshiradi | Soni |
|---|---|---|
| `tests/test_ad_service.py` | Qoralama, maydon tekshiruvlari, narx/caption, rasm limiti (tarif va global sozlama), yuborish (avto-tasdiq/moderatsiya), limit tugashi, tasdiq/rad + limit qaytarilishi, pauza, o'chirish, navbat tartibi (`move`/`renumber`), statistika | 30 |
| `tests/test_phase3_flows.py` | **E2E**: sotuvchi tugmalarni bosib e'lon yaratadi (rasm bilan), tahrirlab qayta yuboradi, rad etilganini tuzatadi; admin moderatsiyadan o'tkazadi (sabab bilan), filtrlarni bosadi; huquq cheklovlari | 27 |

**Yo'l-yo'lakay topilgan va tuzatilgan xatolar (Phase 3):**

| # | Xato | Oqibati | Yechim |
|---|---|---|---|
| 1 | E'lon izohida narx **"12 500 000 UZS"** ko'rinishida chiqardi | Guruhga chiqadigan postda o'zbek foydalanuvchisi uchun tushunarsiz valyuta kodi | `Ad.caption` endi `fmt_amount` ishlatadi → "12 500 000 so'm" |
| 2 | E'lon router'i sotuvchi paneli router'i **ichiga** qo'shilgan edi | aiogram'da router darajasidagi filtr (`SellerPanelCB.filter()`) **barcha ichki router'larga** qo'llanadi → `ad:` callback'lari umuman ishlamasdi (jimgina "unhandled") | E'lon router'i root darajasida alohida ulanadi (`app/handlers/__init__.py`) — sabab kodda izoh bilan yozilgan |
| 3 | `_do_reject()` da `await ... if seller else False` ko'rinishidagi ifoda | Rad etish yo'li mantiqiy xato bilan yozilgan edi (sotuvchi topilmasa jim o'tardi) | Aniq tekshiruvlarga bo'lindi (sotuvchi yo'q / holat mos emas) |
| 4 | `filterlar` qatori klaviaturaga **ro'yxat ichida ro'yxat** bo'lib qo'shilardi | Telegram `InlineKeyboardMarkup` xato berardi (ro'yxat ekrani ochilmasdi) | `rows.append(...)` → `rows.extend(...)` |
| 5 | `_category()` test yordamchisi bir xil `tg_chat_id` bilan guruh yaratardi | Ikkinchi toifa qo'shilganda unique constraint → test yiqilardi | Guruh qayta ishlatiladi (test yordamchisi) |
| 6 | `clean_text(reason, 300)` — ikkinchi argument pozitsion berilgan | `TypeError` (funksiya uni keyword-only kutadi) | `clean_text(reason, limit=300)` |

**Tekshirilgan:** 221 test o'tadi; har bir test fayli **alohida** ham o'tadi (tartibga bog'liqlik yo'q;
`clean_db` fixture endi jadvallarni to'liq tozalaydi); Alembic autogenerate diff **bo'sh**
(Phase 3 sxemani o'zgartirmadi); seed: 25 sozlama, **30 matn**, 3 namuna tarif;
`app.main` importi va router yig'ish ishlaydi.

**Keyingi qadam:** Phase 4 — **Aylanma joylash dvigateli** (navbat kursori, atomar
`next_post_at`, jitter, tinch soatlar, kunlik limit, "hoziroq joylash", navbat tartibini
o'zgartirish, eski postni o'chirish, FloodWait/Forbidden ishlovi).

**Jami: ~105-135 soat ish ≈ 14-18 ish kuni** (bitta kishi intensiv ishlasa; men bilan bosqichma-bosqich, real vaqtda tezroq — chunki testimiz parallel ketadi).

**Tez natija uchun MVP varianti (✅ tanlandi):** bosqich **0→5** ni birinchi qilib chiqamiz — shunda **guruh, toifa, sotuvchi, tarif, e'lon, aylanma joylash va to'lov** to'liq ishlaydi va pul ishlay boshlaydi. Keyin 6-9 (posbon, tozalovchi, sanoqchi, referal...) qo'shiladi. Shu tariqa loyihani ~5-6 ish kunida "ishlaydigan" holatga keltirish mumkin.

> **Muhim qoida:** har bosqichda sizning izohingizni olmasdan keyingisiga o'tmayman (`.kiro/steering/kiro-rules.md` talabi).

---

## 15. QARORLAR HOLATI

**Texnik tanlovlar — ✅ TASDIQLANDI** (yuqoridagi "TASDIQLANGAN QARORLAR" bo'limiga qarang):

| # | Savol | Holat |
|---|---|---|
| 1 | Baza | ✅ PostgreSQL 16 + Redis 7 |
| 2 | Kod joyi | ✅ `SHOP_BOT/` (shu repoda, `AVTO_BOT` tegilmaydi) |
| 3 | Deploy | ✅ Docker Compose + Caddy + webhook |
| 4 | Ish tartibi | ✅ MVP (Phase 0→5) birinchi |

**Menda allaqachon bor deb hisoblayman (bo'lmasa aytasiz):**
- Bot token, bot username
- Super admin Telegram ID(lar)
- Test uchun: 1 supergroup + 1 kanal + domen (webhook uchun)
- Tarif nomlari/narxlari/limitlari (keyin ham bo'ladi — panel orqali kiritiladi)

**Keyinroq kerak bo'ladi (kod yozishga xalaqit bermaydi):**
- To'lov kartalari/rekvizitlar (panel orqali kiritiladi, kodga yozilmaydi)
- Bot matnlari/branding (nomi, logotip, salomlashuv)

**Hali ochiq (MVP davomida hal qilamiz):**
- Sotuvchi e'lonlari orasida rasm limiti (tarif standartlari)
- Majburiy obuna kanali aniq nomi hali berilmagan; Phase 7 panelida admin tekshirib kiritadi

---

> 📌 **Joriy holat va davom ettirish qo'llanmasi:** [`HOLAT.md`](HOLAT.md) —
> qaysi bosqich bajarilgan, qolgan ishlar ro'yxati, servis shartnomalari va
> yangi chatda ishni qaytadan boshlash uchun aniq buyruqlar.

## YANGI OQIM (2026-10-17)

Oldingi Phase 0–9 rejasi tarixiy asos bo‘lib qoladi. Guruhda qo‘lda odam
qo‘shish, bot orqali bir oylik bepul/pullik e’lon va har foydalanuvchining
mustaqil Start/Stop taymeri bo‘yicha joriy talablar va ochiq qarorlar:
**[docs/YANGI_ELON_OQIMI.md](docs/YANGI_ELON_OQIMI.md)**. 1-bosqich
(guruhga qo‘lda a’zo qo‘shish) va 2-bosqich (soha guruhi + bir oylik
bepul e’lon) kodlangan; oddiy odamga pullik xarid hamda barcha pullik
kampaniyalarning mustaqil Start/Stop tizimiga alohida ruxsat kerak.

## 16. KEYINGI QADAM

1. ✅ Reja yozildi va ko'rib chiqish uchun taqdim etildi.
2. ✅ 4 ta texnik qaror tasdiqlandi (PostgreSQL+Redis, `SHOP_BOT/`, Docker+webhook, MVP 0→5).
3. ✅ **Phase 0** (poydevor) yozildi, tekshirildi va taqdim etildi — 58 test o'tdi.
4. ✅ **Phase 1** (guruhlar va toifalar) yozildi, tekshirildi — 104 test o'tdi.
5. ✅ **Phase 2** (sotuvchilar, tariflar, obunalar) yozildi, tekshirildi — 164 test o'tdi.
6. ✅ **Phase 3** (e'lonlar va moderatsiya) yozildi, tekshirildi — **221 test o'tdi**.
7. ✅ **Phase 4** (aylanma joylash dvigateli) yozildi, tekshirildi — **258 offline test o'tdi**. Tafsilot: `HOLAT.md`.
8. ✅ **Phase 5** (to'lovlar) — **274 offline test**; tafsilot `HOLAT.md`.
9. ✅ **Phase 6** (har guruhda posbon, tozalovchi, ruxsatlar) — **302 offline test**;
   SQLite Alembic diff, seed va regressiya tekshirildi. Tafsilot `HOLAT.md`.
10. ✅ **Phase 7** (har guruh sanoqchisi/majburiy kanal) — **319 offline test**;
    SQLite Alembic upgrade/check/downgrade, seed ×2 va PostgreSQL offline SQL tekshirildi.
11. ✅ **Phase 8** (referal/statistika/matn/xato/broadcast + tarif cheklovi,
    e'lon grafigi, admin rollari) foydalanuvchining alohida «ha» ruxsati bilan
    bajarildi — **341 offline test**. SQLite Alembic upgrade/check/downgrade,
    eski chek migratsiyasi, seed ×2 va PostgreSQL offline SQL tekshirildi.
12. ✅ **Phase 9** foydalanuvchining alohida «davom et» ruxsati bilan boshlandi:
    oflayn navbat yuklamasi, preflight/deploy, backup/restore himoyasi va
    o‘zbekcha qo‘llanmalar. Jonli deploy/restore/video yozish va huquqiy qabul
    sinovlari hali bajarilmadi: `HOLAT.md` §8–9.
