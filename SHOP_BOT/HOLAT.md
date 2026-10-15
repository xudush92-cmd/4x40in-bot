# 🔄 HOLAT VA DAVOM ETISH QO'LLANMASI

> **Bu fayl kim uchun?** — Shu loyihani **keyingi chatda** davom ettiradigan yordamchi uchun.
> Yangi chatda avval shu faylni, keyin `REJA.md` ni o'qing — kod aynan qolgan joyidan
> davom ettiriladi. Bu fayl doim **eng oxirgi holat** bo'yicha yangilanadi.

**Oxirgi yangilanish:** 2026-10-15 · **Holat:** Phase 0–3 ✅ tugadi (221 test yashil) · **Keyingisi: Phase 4** (ruxsat kutilmoqda)

---

## 0. Bir qarashda (TL;DR)

| Nima | Qiymat |
|---|---|
| Loyiha | **SHOP-BOT** — Telegram guruhlariga sotuvchi e'lonlarini navbat bilan avtomatik joylashtiruvchi bot |
| Papka | Repo ichida `SHOP_BOT/` (ildizdagi `AVTO_BOT/` — **boshqa loyiha, tegilmaydi**) |
| Repo | `https://github.com/xudush92-cmd/4x40in-bot` |
| Ish shoxobi | `arena/40593d24-4x40in-bot` (oxirgi commit `1ceac25`) |
| Texnologiya | Python 3.11+/3.12, aiogram 3.31, SQLAlchemy 2.1 (async), PostgreSQL 16, Redis 7, APScheduler, Docker Compose + Caddy + webhook |
| Testlar | **221 test, hammasi o'tadi** (`pytest`, tarmoqsiz SQLite) |
| Migratsiya | `f789aa7b756f` (Phase 0 dan beri o'zgarmagan — Phase 1–3 sxemaga tegilmadi) |
| Keyingi qadam | **Phase 4 — aylanma joylash dvigateli** (ruxsat kutilmoqda) |
| Ish qoidasi | ⚠️ **Foydalanuvchi ruxsatisiz kod yozilmaydi** — har bosqich oxirida hisobot + ruxsat so'rash |

---

## 1. Kod qayerga yozilgan (GitHub'dagi joyi)

**Repo:** https://github.com/xudush92-cmd/4x40in-bot
**Shoxobcha:** [`arena/40593d24-4x40in-bot`](https://github.com/xudush92-cmd/4x40in-bot/tree/arena/40593d24-4x40in-bot) — `main` **tegilmagan** (`ccbbe99` da turibdi).

| Commit | Nima qilingan | GitHub havolasi |
|---|---|---|
| `412b74d` | To'liq texnik reja (kod yo'q) | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/412b74d) |
| `147317a` | Tasdiqlangan qarorlar rejaga qo'shildi | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/147317a) |
| `f1c85ff` | **Phase 0** — poydevor (Docker, 41 jadval, Alembic, panel skeleti, seed, 58 test) | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/f1c85ff) |
| `50b77dc` | **Phase 1** — guruhlar va toifalar (104 test) | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/50b77dc) |
| `1fcdbf7` | **Phase 2** — sotuvchilar, tariflar, obunalar (164 test) | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/1fcdbf7) |
| `1ceac25` | **Phase 3** — e'lonlar va moderatsiya (221 test) | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/1ceac25) |

> ⚠️ **Muhim:** Arena'da har bir **yangi chat yangi shoxobcha** ochadi
> (`arena/<yangi-chat-id>-4x40in-bot`). Eski ishni yangi chatga olib o'tish:
>
> ```bash
> cd /home/user/4x40in-bot
> git fetch origin arena/40593d24-4x40in-bot
> git merge --ff-only FETCH_HEAD     # Phase 0–3 kodi keladi (main'dan to'g'ri shoxlangan)
> # ... shundan keyin YANGI chatning o'z shoxobchasida davom etiladi
> ```
>
> Merge ishlamasa: `git cherry-pick` yoki eng yomoni — eski shoxobchadagi fayllarni
> qo'lda ko'chirish (commitlar soni 6 ta, hammasi shu faylda sanab o'tilgan).

---

## 2. Yangi chatda birinchi qadamlar (ish muhitini tiklash)

`.venv/` papkasi sandbox snapshot'iga **kirmaydi** — har yangi chatda qayta yaratiladi
(2 daqiqa ish):

```bash
cd /home/user/4x40in-bot/SHOP_BOT
python3 -m venv .venv
.venv/bin/pip install -q -r requirements-dev.txt
.venv/bin/python -m pytest -q          # 221 test o'tishi kerak (~70 sekund)
```

Testlar **offline** ishlaydi: SQLite (vaqtinchalik fayl) + soxta Bot API sessiyasi,
Redis talab qilinmaydi (`tests/conftest.py` ni ko'ring).

Foydali tekshiruvlar:

```bash
.venv/bin/python -m compileall -q app scripts tests      # sintaksis
# Alembic sxema farqi bo'sh bo'lishi kerak:
TMP=$(mktemp -d); export DB_URL="sqlite+aiosqlite:///$TMP/al.db"
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m alembic revision --autogenerate -m "dif"   # op. bo'lmasligi kerak
# Seed sinovi (toza bazada): 0 admin / 25 sozlama / 30 matn / 3 tarif
```

---

## 3. Bot nima qiladi (qisqa, foydalanuvchi tilida)

Telegram guruhlari (supergroup) bozorlar uchun bot:

1. **Toifalar ↔ guruhlar**: har toifa bitta guruhga biriktiriladi (masalan «📱 Telefonlar» → «Telefonlar bozori» guruhi).
2. **Sotuvchilar** bot orqali e'lon qo'shadi (rasmlar bilan). Admin ularga **tarif** beradi (narx, muddat, e'lon limiti, rasm limiti).
3. **Moderatsiya**: admin e'lonni ko'rib, tasdiqlaydi yoki sabab bilan rad etadi.
4. **Aylanma joylash** (Phase 4): tasdiqlangan e'lonlar guruhlarga **navbat bilan, interval bilan** avtomatik joylanadi (albom + «Sotuvchi bilan bog'lanish» tugmasi).
5. Pul: sotuvchi **chek** yuboradi → admin tasdiqlaydi → obuna avtomatik uzayadi (Phase 5).
6. Qo'shimcha: posbon/tozalovchi (guruh nazorati), sanoqchi (odam qo'shish tizimi), referal, statistika, broadcast (Phase 6–8).

**To'liq funksiyalar ro'yxati va sabablari:** `REJA.md` (16 bo'lim).
**Foydalanuvchi bilan kelishilgan yagona haqiqat manbai:** `REJA.md` + shu fayl.

---

## 4. Bajarilgan bosqichlar

### ✅ Phase 0 — Poydevor
Docker Compose (bot + poster + PostgreSQL 16 + Redis 7 + Caddy), `.env` validatsiyasi,
41 jadvalli sxema + Alembic, loguru loglar, `error_log` + adminlarga xabar, middleware'lar
(DB sessiya, foydalanuvchi konteksti, anti-flood, texnik rejim), panel skeleti
(📊 Statistika, ⚙️ Sozlamalar), `/health` va `/stats`, scheduler (heartbeat, huquq tekshiruvi,
log tozalash, kunlik statistika), `scripts/seed.py`, `backup.sh`/`restore.sh`.

### ✅ Phase 1 — Guruhlar va toifalar
Guruhlar CRUD + huquq tekshiruvi, funksiyalar **matritsasi** (barcha guruhlar × 5 funksiya),
guruh sozlamalari (interval 1–1440 daq, jitter 0–50%, kunlik limit, tinch soatlar),
toifalar CRUD (emoji, guruhga biriktirish, alohida interval, moderatsiya rejimi, tartib),
panelda jonli hisoblagichlar. *Yo'l-yo'lakay 4 runtime xato tuzatilgan (filtr imzosi,
`PrivateChat`, aware datetime, FSM `action`).*

### ✅ Phase 2 — Sotuvchilar, tariflar, obunalar
Sotuvchi CRUD + qidiruv/filtr/sahifalash, bloklash (sabab bilan), blokdan chiqarish,
tasdiqlash, izoh, soft-delete; tarif CRUD (narx tahlili: `150 000`, `150,000`, `150.000`,
`150000 so'm`), faol/pauza, sinov, tartib, o'chirish (obunasi bor tarif → faqat to'xtatiladi);
obuna berish/uzaytirish/limit berish + tarix; **sotuvchi paneli** («Mening tarifim», katalog,
referal kod, yordam); joblar: eslatma (soatlik) + muddati tugaganlarni yopish (30 daqiqada, grace).

### ✅ Phase 3 — E'lonlar va moderatsiya
E'lon **ustasi** (toifa → sarlavha → tavsif → narx → aloqa → rasmlar → ko'rish → yuborish),
«Mening e'lonlarim» (ro'yxat + filtr + kartochka + statistika + tahrirlash + pauza + o'chirish),
rasmlar faqat `file_id` (disk tejash) va tarif limiti bilan, **moderatsiya** navbati
(rasmlar bilan kartochka, tasdiqlash, rad etish — 6 tayyor sabab yoki qo'lda yozish,
rad etilganda limit qaytariladi), **📢 E'lonlar** (admin, holat filtri, pauza/yoqish,
o'chirish, moderatsiya tarixi), xabarnomalar (yangi e'lon → adminlar, qaror → sotuvchi).

**Phase 3 da topilgan muhim xato:** e'lon router'i sotuvchi paneli router'i ichiga qo'shilgan
edi — aiogram'da router darajasidagi filtr **barcha ichki router'larga** qo'llanadi, shuning
uchun `ad:` callback'lari umuman ishlamasdi. Yechim: e'lon router'i root darajasida alohida
ulanadi (`app/handlers/__init__.py`, izohi bilan). **Buni qaytarib buzmaslik kerak.**

---

## 5. Test holati (221 test)

| Test fayli | Qamrov | Soni |
|---|---|---|
| `tests/test_ad_service.py` | E'lon servisi: qoralama, tekshiruvlar, rasm limiti, yuborish, tasdiq/rad, limit qaytarilishi, navbat | 30 |
| `tests/test_phase3_flows.py` | **E2E**: sotuvchi ustasi (rasm bilan), tahrir, moderatsiya, admin filtrlari | 27 |
| `tests/test_phase2_flows.py` | **E2E**: sotuvchi/tarif/obuna oqimlari | 24 |
| `tests/test_tariff_and_subscription.py` | Tarif + obuna servislari | 24 |
| `tests/test_category_service.py` | Toifa servisi | 16 |
| `tests/test_phase1_groups.py` | **E2E**: guruh/toifa oqimlari | 16 |
| `tests/test_admin_flows.py` | **E2E**: panel, sozlamalar, guruhlar | 14 |
| `tests/test_seller_service.py` | Sotuvchi servisi + telefon normalizatsiyasi | 12 |
| `tests/test_models.py` | Sxema, `Ad.caption`, relationship'lar | 12 |
| `tests/test_config.py` / `test_infra.py` | Konfiguratsiya / infratuzilma | 9 + 9 |
| `tests/test_text_service.py` | Matn shabloni + placeholder indeksi | 9 |
| `tests/test_seed_and_wiring.py` | Seed (subprocess) + router yig'ish | 7 |
| `tests/test_settings_service.py` / `test_group_service.py` | Sozlama keshi / guruh servisi | 6 + 6 |
| **JAMI** | | **221** |

**Test yozish qoidalari (buzilmasin):**
1. Har bir test fayli **alohida ham** o'tishi kerak (`pytest tests/x.py`).
2. Test sessiyasi handler sessiyasidan alohida → `session.expire_all()` dan keyin ORM
   atributiga murojaat qilish `MissingGreenlet` beradi. ID'lar `_pk(obj)` bilan
   (identity orqali) **feed'dan oldin** olinadi.
3. `clean_db` fixture jadvallarni **o'chirib qayta yaratadi** (tartibga bog'liqlik yo'q).
4. `tests/fake_telegram.py`: `make_dispatcher()`, `callback_update()`, `text_update()`,
   `photo_update()`, `reset_dispatcher_state()` — fixture boshida va oxirida chaqiriladi.

---

## 6. Kod xaritasi (davom ettirish uchun muhim fayllar)

```
SHOP_BOT/
├── REJA.md                     # to'liq reja (16 bo'lim) — funksiya talablari shu yerda
├── HOLAT.md                    # ⬅️ shu fayl (davom ettirish nuqtasi)
├── README.md                   # qisqa holat + ishga tushirish
├── app/
│   ├── main.py                 # RUN_MODE: bot | poster | all
│   ├── bot.py                  # Bot/Dispatcher, middleware, xato ushlagich
│   ├── config.py, constants.py, states.py, logging_setup.py, redis_client.py
│   ├── db/models.py            # 41 jadval (Phase 0 da yozilgan, o'zgarmagan)
│   ├── services/
│   │   ├── settings_service.py     # 25 global sozlama (restart kerak emas)
│   │   ├── text_service.py         # 30 matn + safe_format
│   │   ├── group_service.py, category_service.py
│   │   ├── seller_service.py, tariff_service.py, subscription_service.py
│   │   ├── ad_service.py           # ⬅️ Phase 3 (e'lon hayot sikli)
│   │   └── notify.py, stats_service.py
│   ├── handlers/
│   │   ├── __init__.py         # build_root_router() — router tartibi MUHIM
│   │   ├── common.py           # /start, fallback, sotuvchi holati
│   │   ├── admin/              # panel, settings, groups, categories, sellers, tariffs, mods
│   │   ├── seller/ads.py       # e'lon ustasi, «Mening e'lonlarim», tahrir
│   │   └── group/lifecycle.py
│   ├── keyboards/              # admin, common, groups, categories, sellers, tariffs, ads, mods, seller_panel
│   ├── scheduler/jobs.py       # posting_tick_job ⬅️ Phase 4 shu yerda to'ladi
│   ├── scheduler/runner.py     # job ro'yxati (posting_tick — har 10 sekund)
│   └── web/server.py           # /health, /stats, webhook
├── tests/                      # 221 test (+ conftest.py, fake_telegram.py)
├── alembic/versions/f789aa7b756f_boshlangich_sxema.py
└── scripts/seed.py, backup.sh, restore.sh
```

---

## 7. Muhim shartnomalar (davom ettirishda buzilmasin)

### Router tartibi (`app/handlers/__init__.py`)
```
admin_router → seller_ads_router → seller_router → group_router → common.router
```
E'lon router'i (`app/handlers/seller/ads.py`) **root darajasida** turadi (sabab: yuqoridagi
Phase 3 xatosi). Sotuvchi panelida esa `SellerPanelCB.filter()` router filtri bor —
**ichiga boshqa callback prefiksi qo'shilmaydi**.

### Callback prefikslari (64 bayt chegarasi tekshiriladi)
`adm:` admin panel · `grp:` guruhlar · `feat:` funksiya tumbleri · `cat:` toifalar ·
`slr:` sotuvchilar · `trf:` tariflar · `sp:` sotuvchi paneli · **`ad:` e'lonlar** ·
**`mod:` moderatsiya** · `nav:` navigatsiya.
Sahifa/filtr qiymatlari `"<sahifa>|<filtr>"` ko'rinishida (masalan `"0|active"`).

### Servis API (asosiy funksiyalar)
- `ad_service`: `create_draft(session, seller, category)`, `set_title/set_description/set_price/set_contact/set_category`,
  `add_photo(..., limit=)`, `remove_photo(session, ad, position)`, `photo_count(session, ad_id)` (int),
  `photo_limit(session, seller)`, `validate_for_submit`, `can_submit`, `submit(session, seller, ad) -> (bool, holat)`,
  `pause/resume`, `soft_delete` (limit qaytaradi), `hard_delete_empty_draft`, `approve/reject/admin_pause`,
  `edited` (tahrirdan keyingi holat), `renumber_category`, `move(session, ad, "up"|"down")`,
  `next_position`, `list_ads/count_ads` (admin filtr), `list_seller_ads/count_seller_ads`,
  `seller_ads_stats`, `pending_ads/count_pending`, `moderation_history`, `ad_stats`,
  `format_ad_price`, `status_title/status_badge/filter_label`, `pages`.
  Konstantalar: `POSITION_GAP=100`, `MAX_PHOTOS_HARD=10`, `STATUS_FILTERS`/`ADMIN_FILTERS`.
- `subscription_service`: `grant/extend/set_ads_limit/active_for/latest_for/days_left/can_publish/consume_slot/release_slot/reminders_due/expire_due/mark_reminded/...`
- `tariff_service`: `create_tariff/.../delete_tariff/move/list_all_active/get_stats/parse_price/format_price`
- `seller_service`: `get_or_create_seller/get_seller/set_status/soft_delete/normalize_phone/normalize_contact/seller_label/...`

### Klaviatura o'lchamlari (`app/keyboards/common.py`)
`PER_PAGE_GROUPS=6`, `PER_PAGE_CATEGORIES=8`, `PER_PAGE_MATRIX=5`, `PER_PAGE_SELLERS=6`,
`PER_PAGE_TARIFFS=8`, **`PER_PAGE_ADS=6`**, **`PER_PAGE_PHOTOS=8`**.

### Bazadagi muhim faktlar
- `ads.group_id` — denormalizatsiya (toifa guruhidan olinadi); `ad_photos` faqat `file_id` saqlaydi.
- `Ad.position` — navbat tartibi (100 qadam), `post_count`, `last_posted_at`, `next_eligible_at`.
- `category_rotation`: `cursor_ad_id` (oxirgi joylangan), `next_post_at`, `cycle_count`, `is_paused` — **Phase 4 shu kursordan foydalanadi**.
- `group_rotation`: `next_post_at` (indeksli), `today_count`, `today_date`, `error_streak`.
- `posted_messages`: `message_ids` (JSON) — eski postni o'chirish uchun; `post_log` — joylash tarixi.
- `group_settings`: `interval_sec` (default 1800), `jitter_percent` (10), `daily_post_limit` (50), `quiet_start/quiet_end`, `protect_content`, `posting_enabled`.
- Sessiya `expire_on_commit=False` (ishlab chiqarish kodida `MissingGreenlet` xavfi yo'q).

### Global sozlamalar (25 ta, `settings_service.DEFAULTS`)
`kill_switch`, `maintenance_mode`, `support_contact`, `timezone`, 5 ta funksiya kaliti,
`default_interval_sec`, `default_jitter_percent`, `default_daily_post_limit`, `min_interval_sec=60`,
`bot_username`, `subscription_reminder_days=3`, `subscription_grace_days=0`,
`moderation_required_default`, `default_max_photos=3`, `default_max_ads=5`, `receipt_required`,
`receipt_duplicate_check`, `referral_enabled`, `log_retention_days`, `broadcast_rate_per_sec`,
`warn_first_delay_sec`.

### Matnlar (30 ta, `text_service.DEFAULT_TEXTS`)
`common.*` (10), `start.*` (3), `group.*` (3), `seller.*` (6), `ad.*` (4: submitted/approved/rejected/paused),
`notify.*` (4). Placeholder nomlari **kod bilan aynan bir xil** bo'lishi shart —
`tests/test_text_service.py::test_all_default_texts_have_valid_placeholders` buni ushlaydi
(masalan `ad.submitted` → `{elon}`, `{toifa}`, `{sotuvchi}`).

### Panelda tayyor bo'limlar (`READY_SECTIONS`)
`stats, settings, groups, categories, sellers, tariffs, ads, moderation`
(qolganlari bosilganda "Phase N da qo'shiladi" xabari chiqadi — bu testda tekshiriladi).

---

## 8. Qolgan ishlar

### ⭐ Phase 4 — Aylanma joylash dvigateli (KEYINGI QADAM, ruxsat kutilmoqda)

**Maqsad:** tasdiqlangan e'lonlar guruhlarga interval bilan o'zi keta boshlaydi.

Tayyor turgan "kulisa": `posting_tick_job` (har 10 sekund, hozir faqat sanaydi), `group_rotation`
va `category_rotation` jadvallari, `post_log`, `posted_messages`, `GroupSettings` maydonlari,
`text_service."notify.group_paused"`, `ad_service.move()` (navbat tartibi).

Vazifalar ro'yxati:
1. **Nomzod tanlash**: `category_rotation.cursor_ad_id` dan keyingi `Ad` (`status=active`,
   `position` bo'yicha, oxiriga yetganda boshidan aylanadi) + filtrlash: sotuvchi obunasi faol,
   `ads_left > 0`, sotuvchi bloklanmagan, guruh/toifa faol, tarif cheklovi (bo'lsa), `next_eligible_at`.
2. **Interval va jitter**: manba — `category.interval_override` yoki `group_settings.interval_sec`;
   minimal 60 sekund; `next = now + interval * random(0.9..1.1)`.
3. **Atomar yangilash**: `UPDATE group_rotation SET next_post_at=:new WHERE group_id=:id AND next_post_at=:old`
   (`rowcount=0` → boshqa worker oldin oldi, o'tkazib yuboriladi). Ko'p poster uchun
   PostgreSQL `SELECT ... FOR UPDATE SKIP LOCKED`.
4. **Tinch soatlar** (`quiet_start..quiet_end`) va **kunlik limit** (`daily_post_limit`,
   `today_count`/`today_date` bilan) — buzilsa keyingi ruxsat etilgan vaqtga suriladi.
5. **Yuborish**: `sendMediaGroup` (1..10 rasm, `protect_content` sozlamasi bilan) + alohida
   xabar: `🔘 "Sotuvchi bilan bog'lanish"` (inline URL/`@username`/telefon). 10 dan ortiq rasm →
   bir necha albom. `posted_messages` ga `message_ids` yozish.
6. **Xato ishlovi**: `TelegramRetryAfter` → `retry_after` kutish (faqat shu guruh kechiktiriladi);
   `TelegramForbiddenError`/`BadRequest` → guruh pauza + adminga xabar + `error_log`
   (+ `error_streak`); muvaffaqiyatda `error_streak=0`.
7. **Eski postni o'chirish** (sozlama bo'lsa): botning o'z xabari o'zi uchun har doim o'chiriladi
   (`deleteMessage`). 48 soatdan oshganini faqat bot admin bo'lsa o'chira oladi.
8. **Kursorni yangilash + statistika**: `cursor_ad_id`, `last_post_at`, `post_count++`,
   `last_posted_at`, `post_log` yozuvi, `cycle_count`.
9. **«Hoziroq joylash»** tugmasi (guruh kartochkasida yoki e'lon kartochkasida) — navbatni
   buzmasdan darhol joylaydi va kursorni shu e'longa o'rnatadi.
10. **Navbatni ko'rish/o'zgartirish** (admin): toifa navbati ro'yxati + ⬆️⬇️ (servis `move()` tayyor).
11. **Kill switch / texnik rejim** hurmat qilinadi; global pauzada `next_post_at` "qarz" to'plamaydi.
12. **Testlar**: navbat mantiqi (unit) + E2E (soxta Bot API: `SendMediaGroup` allaqachon
    qo'llab-quvvatlanadi) + FloodWait/Forbidden stsenariylari (`fake.errors` bilan).

### Phase 5 — To'lovlar (MVP shu bilan yopiladi)
Rekvizitlar CRUD (bir necha karta, aylanma), sotuvchi tarif tanlab «To'lash» → karta ma'lumoti +
«nusxalash» → chek rasmi → `receipt_unique_hash` (takroriy chekni ushlash) → adminlarga
[Sotuvchi]/[Tarif]/[Summa]/[Chek] + ✅/❌ (sabab) → tasdiqlashda **obuna avtomatik** beriladi,
rad etilganda sabab bilan xabar; to'lovlar tarixi; `payment_methods`/`payments` jadvallari tayyor.

### Phase 6 — Posbon + tozalovchi + ruxsatlar
Havola/reklama filtri, majburiy obuna shartlari, jazo zinapoyasi (ogohlantirish → mute → ban),
dry-run, tozalash siyosati (nima/qachon), ruxsatlar/istisnolar (guruh yoki global), mute/ban.

### Phase 7 — Sanoqchi
Har guruhga alohida: `createChatInviteLink` (member_limit), `ChatMemberUpdated.invite_link` orqali
attributsiya, `/takliflarim`, admin qo'lda tuzatishi, majburiy kanal, «N odam» sharti.
**Foydalanuvchidan kerak:** majburiy kanal nomi.

### Phase 8 — Referal + statistika + matnlar + xatolar + broadcast
Referal bonusi sikli (`referral_enabled`), grafik/hisobot va eksport, bot matnlarini paneldan
tahrirlash, xato jurnali paneli, broadcast (25 msg/s limit bilan).

### Phase 9 — Sayqal
Yuklama testi, deploy skripti, backup/restore sinovi, README/video-qo'llanma, huquqiy eslatmalar
(REJA.md 11.2).

**Umumiy qolgan vaqt:** **66–88 soat** (~9–11 ish kuni). MVP (Phase 4+5): 18–24 soat.

---

## 9. Ochiq bandlar / kechiktirilganlar

| # | Nima | Qachon |
|---|---|---|
| 1 | Tarifda «qaysi guruh/toifalar uchun» cheklovi (`allowed_category_ids`/`allowed_group_ids`) UI | Phase 4 yoki 8 |
| 2 | Sotuvchi e'lonlarini **toifa bo'yicha guruhlash** (hozir ro'yxat + toifa ko'rsatkichi) | Phase 8 bilan |
| 3 | E'lon statistikasida kunlik grafik | Phase 8 |
| 4 | To'lov rekvizitlari (kodga yozilmaydi — paneldan kiritiladi) | Phase 5da kerak bo'ladi |
| 5 | Majburiy obuna kanali nomi | Phase 7da kerak bo'ladi |
| 6 | Telegram siyosati/huquqiy eslatmalar yakuniy tekshiruvi | Phase 9 |

---

## 10. Ish qoidalari (foydalanuvchi talablari — o'zgarmaydi)

1. ⚠️ **Foydalanuvchi aniq ruxsatisiz kod yozilmaydi.** Har bosqich oxirida: hisobot → ruxsat so'rash → keyingi bosqich.
   Kichik tuzatishlar ham **shu bosqich ichida** qilinadi, lekin yangi bosqichga o'tilmaydi.
2. **Minimal tuzatish** tamoyili: mavjud kodni qayta yozishdan ko'ra aniq tuzatish afzal.
3. **Yangi shoxobcha/PR ochilmaydi** — faqat chatning shoxobchasida ishlanadi va `git push` qilinadi.
4. **`AVTO_BOT/` tegilmaydi** (boshqa loyiha, alohida token/baza).
5. **Hujjatlar va hisobotlar o'zbek tilida.**
6. Har bosqich yakunida: to'liq `pytest`, `compileall`, Alembic diff, seed sinovi, so'ng commit + push.
7. Topilgan xatolar **halol** hisobot qilinadi (masalan: "bu xato mahsulot kodida emas, testda edi").

---

## 11. Yangi chat uchun nusxa ko'chiriladigan so'rov

> Quyidagini yangi chatga to'g'ridan-to'g'ri nusxalab yuborish mumkin:

```
Salom! SHOP-BOT loyihasini davom ettiramiz. Avval SHOP_BOT/HOLAT.md va SHOP_BOT/REJA.md
fayllarini o'qib chiqing — bu loyihaning to'liq holati va qolgan ishlar ro'yxati.
Keyin:
1) git fetch origin arena/40593d24-4x40in-bot && git merge --ff-only FETCH_HEAD
   (Phase 0–3 kodi shu shoxobchada; main'ga tegmaymiz);
2) .venv ni qayta yaratib, pytest ni ishga tushiring — 221 test o'tishi kerak
   (batafsil buyruqlar HOLAT.md 2-bo'limida);
3) holatni menga o'zbekcha qisqacha aytib bering va Phase 4 (aylanma joylash dvigateli)
   uchun ruxsat so'rang. Mendan ruxsat olmasdan kod yozmang.
```

---

## 12. Xulosa: "keyingi chat uchun yoriqnoma bormi?"

✅ **Bor.** Uch qatlamli:

1. **`SHOP_BOT/HOLAT.md`** (shu fayl) — holat, qolgan ishlar, shartnomalar, ish muhitini tiklash, yangi chat uchun tayyor so'rov.
2. **`SHOP_BOT/REJA.md`** — to'liq texnik reja (funksiya talablari, DB sxemasi, flow'lar, masshtablash, risklar, bosqichlar).
3. **Git tarixi** (`1ceac25` … `f1c85ff`) — kod va testlar GitHub'da, har bosqich alohida commit.

Yangi chatda yordamchi shu 3 ta manbani o'qisa, loyihani **aynan qolgan joyidan** davom ettira oladi:
`git fetch` → `merge` → `pytest` → ruxsat → Phase 4.
