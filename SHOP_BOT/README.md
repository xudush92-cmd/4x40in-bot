# 🛒 SHOP-BOT — Telegram onlayn do'kon uslubidagi e'lonlar boti

Guruhlarga bo'lingan toifalar bo'yicha sotuvchi e'lonlarini **avtomatik, navbat bilan**
joylashtiruvchi bot. Hamma boshqaruv — inline tugmalar orqali, kodga tegmasdan.

> To'liq loyiha rejasi: **[REJA.md](REJA.md)** (16 bo'lim: arxitektura, DB sxemasi,
> admin panel daraxti, jarayonlar, masshtablash, risklar, bosqichlar).
> Joriy holat va **davom ettirish qo'llanmasi** (yangi chat/sessiya uchun):
> **[HOLAT.md](HOLAT.md)** — nima bajarilgan, nima qolgan, muhim shartnomalar.

---

## 📌 Hozirgi holat: **Phase 0 ✅ · Phase 1 ✅ · Phase 2 ✅ · Phase 3 (e'lonlar va moderatsiya) ✅**

| Ish | Holat |
|---|---|
| Docker Compose (bot + poster + PostgreSQL 16 + Redis 7 + Caddy) | ✅ |
| 41 jadvalli baza sxemasi + Alembic migratsiya | ✅ |
| Konfiguratsiya (.env, pydantic-settings, validatsiya) | ✅ |
| Loglar (loguru, kunlik aylanish), xato jurnali (`error_log`) | ✅ |
| Middleware'lar (DB sessiya, foydalanuvchi konteksti, anti-flood, texnik rejim) | ✅ |
| Boshqaruv paneli skeleti: **📊 Statistika** va **⚙️ Sozlamalar** to'liq ishlaydi | ✅ |
| Bot guruhga qo'shilganda: baza'ga yozish, admin huquqlarini tekshirish, adminga xabar | ✅ |
| Rejalashtiruvchi: heartbeat, huquq tekshiruvi, log tozalash, kunlik statistika | ✅ |
| `/health` va `/stats` (HTTP), webhook va polling rejimi | ✅ |
| Seed skript, backup/restore skriptlar, 58 test | ✅ |

### Phase 1 — guruhlar va toifalar ✅

| Ish | Holat |
|---|---|
| 👥 Guruhlar: ro'yxat, kartochka, admin huquqlari tekshiruvi, pauza/yoqish, o'chirish (tasdiq bilan) | ✅ |
| 🎛 Funksiyalar matritsasi — barcha guruhlar × 5 funksiya bir ekranda yoqiladi/o'chiriladi | ✅ |
| ⚙️ Guruh sozlamalari: interval (1–1440 daq), jitter, kunlik limit, tinch soatlar — panel orqali, **restart kerak emas** | ✅ |
| 🗂 Toifalar: yaratish (emoji bilan), qayta nomlash, guruhga biriktirish, alohida interval, moderatsiya, tartib, o'chirish | ✅ |
| 🔢 Panel tugmalarida jonli hisoblagichlar (guruhlar, toifalar, to'lovlar, xatolar) | ✅ |
| 🧪 Offline E2E testlar: haqiqiy Dispatcher + soxta Bot API (tarmoq/Redis talab qilmaydi) — **jami 104 test** | ✅ |

### Phase 2 — sotuvchilar, tariflar, obunalar ✅

| Ish | Holat |
|---|---|
| 🛒 Sotuvchilar: ro'yxat (sahifa + holat filtri), qidiruv, kartochka, qo'shish (ID → nom → telefon → kontakt), bloklash (sabab bilan), blokdan chiqarish, tasdiqlash, izoh, profil tahriri, soft-delete | ✅ |
| 💳 Tariflar: yaratish ustasi, narx/muddat/limitlarni tahrirlash, faol↔pauza, sinov belgisi, tartib (⬆/⬇), o'chirish (obunasi bor tarif faqat to'xtatiladi) | ✅ |
| 🎫 Obunalar: tarif berish, uzaytirish, muddatni qo'lda o'zgartirish, e'lon limitini berish, obunalar tarixi, sotuvchi blokdan chiqarilganda obuna hisobga olinadi | ✅ |
| 👤 **Sotuvchi paneli**: "Mening tarifim" (qolgan kun, limit, holat), tariflar katalogi, referal kodi, yordam — `/start` da ham holat ko'rinadi | ✅ |
| ⏰ Avtomatika: obuna eslatmasi (har soatda, 3 kun qolganda, bir marta) va muddati o'tganlarni yopish (30 daqiqada, `grace` → `expired`, e'lonlar o'chiriladi, sotuvchi xabardor) | ✅ |
| 💰 Narx kiritish "odam tilida": `150 000`, `150,000`, `150.000`, `150000 so'm` — hammasi to'g'ri o'qiladi, panelda "150 000 so'm" chiqadi | ✅ |
| 🧪 Testlar: **jami 164 o'tadi** (12 sotuvchi + 24 tarif/obuna + 24 E2E oqim + Phase 0/1 testlari) | ✅ |

### Phase 3 — e'lonlar va moderatsiya ✅

| Ish | Holat |
|---|---|
| ➕ **E'lon ustasi**: toifa → sarlavha → tavsif → narx → aloqa → rasmlar → ko'rish → yuborish (har qadamda ⬅️ orqaga / ⏭ o'tkazib yuborish / ❌ bekor) | ✅ |
| 📢 **Mening e'lonlarim**: ro'yxat (sahifa + holat filtri), kartochka, statistika, tahrirlash, ⏸ pauza / ▶️ yoqish, 🗑 o'chirish (tasdiq bilan) | ✅ |
| 🖼 **Rasmlar**: Telegram `file_id` (disk tejash), tarifdagi rasm limiti, qo'shish/o'chirish | ✅ |
| ✅ **Moderatsiya**: «🕓 Tekshiruvda» navbati, rasmlar bilan kartochka, tasdiqlash, ❌ rad etish (6 tayyor sabab yoki qo'lda) — rad etilganda limit qaytariladi | ✅ |
| 📢 **E'lonlar (admin)**: barcha e'lonlar holat bo'yicha filtr bilan, pauza/yoqish, o'chirish, 🕘 moderatsiya tarixi | ✅ |
| 🔔 Xabarnomalar: yangi e'lon → adminlarga; tasdiq/rad/to'xtatish → sotuvchiga | ✅ |
| 🧪 Testlar: **jami 221 o'tadi** (30 e'lon servisi + 27 E2E oqim + oldingi bosqichlar) | ✅ |

**Keyingi bosqich (Phase 4):** aylanma joylash dvigateli — e'lonlar guruhlarga avtomatik
navbat bilan ketadi (interval, jitter, tinch soatlar, kunlik limit, «hoziroq joylash»).

---

## 🚀 Tez boshlash (Docker)

```bash
cd SHOP_BOT

# 1) Sozlamalar
cp .env.example .env
nano .env          # BOT_TOKEN, ADMIN_IDS, DOMAIN, POSTGRES_PASSWORD, WEBHOOK_SECRET

# 2) Ishga tushirish
docker compose up -d --build

# 3) Loglarni kuzatish
docker compose logs -f bot

# 4) Boshlang'ich ma'lumotlar (adminlar, sozlamalar, matnlar, namuna tariflar)
docker compose exec bot python -m scripts.seed
```

Tekshirish: `curl http://127.0.0.1:8080/health` → `{"status":"ok", ...}`

### Domen va webhook

`.env` da:

```env
USE_WEBHOOK=true
WEBHOOK_BASE_URL=https://bot.sizning-domen.uz
WEBHOOK_SECRET=<uzun-tasodifiy-satr>
DOMAIN=bot.sizning-domen.uz
```

Caddy sertifikatni o'zi oladi. Webhook'siz ishlash uchun `USE_WEBHOOK=false`
qoldiring (polling ishlaydi) va `caddy` servisini o'chiring:

```bash
docker compose up -d bot poster postgres redis
```

---

## 💻 Lokal ishlab chiqish (Docker'siz)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
# SQLite bilan tez sinash uchun .env ichida:
#   DB_URL=sqlite+aiosqlite:///./data/shopbot.db
#   RUN_MODE=all

alembic upgrade head          # jadvallarni yaratish
python -m scripts.seed        # boshlang'ich ma'lumotlar
python -m app.main            # ishga tushirish
```

Testlar:

```bash
pytest                        # 58 test (SQLite'da, tarmoqsiz ishlaydi)
pytest -v --tb=short          # batafsil
```

---

## ⚙️ Telegram tomonida bajarilishi SHART bo'lgan sozlamalar

Bot guruhlarda **to'liq** ishlashi uchun (REJA.md 1.2):

| # | Nima | Qayerda |
|---|---|---|
| 1 | **Privacy Mode'ni o'chirish** — aks holda bot guruhdagi oddiy xabarlarni ko'rmaydi (posbon/tozalovchi ishlamaydi) | @BotFather → `/setprivacy` → **Disable** → botni guruhdan chiqarib, qayta qo'shish |
| 2 | Bot **admin** bo'lishi | Guruh → Administratorlar → botga: ✏️ Xabarlarni o'chirish, 🚫 A'zolarni cheklash, 🔗 Taklif havolalari |
| 3 | Guruh **supergroup** bo'lishi | Oddiy guruhda mute/ban ishlamaydi: Sozlamalar → Chat history → Convert to supergroup |
| 4 | Majburiy kanalda bot **admin** bo'lishi | Kanal → Administratorlar → bot qo'shish |
| 5 | Bot qo'shilganda adminlarga xabar keladi | Xabardagi ro'yxat bo'yicha tekshiring |

---

## 📁 Loyiha tuzilishi

```
SHOP_BOT/
├── app/
│   ├── main.py              # kirish nuqtasi (RUN_MODE: bot | poster | all)
│   ├── bot.py               # Bot/Dispatcher, middleware, xato ushlagich
│   ├── config.py            # .env sozlamalari (pydantic-settings)
│   ├── constants.py         # statuslar, rollar, Redis kalitlari, limitlar
│   ├── states.py            # FSM holatlari
│   ├── logging_setup.py     # loguru konfiguratsiyasi
│   ├── redis_client.py      # Redis + FSM storage (ixtiyoriy komponent)
│   ├── db/
│   │   ├── base.py          # engine, sessiya, JSONB varianti
│   │   └── models.py        # 41 jadval (REJA.md 4-bo'lim)
│   ├── handlers/
│   │   ├── common.py        # /start, /help, /id, /ping, fallback + sotuvchi holati
│   │   ├── admin/           # panel, settings, groups, categories, sellers, tariffs, mods
│   │   ├── seller/          # sotuvchi paneli + ads.py (e'lon ustasi, ro'yxat)
│   │   └── group/           # lifecycle.py (bot qo'shildi/chiqarildi)
│   ├── keyboards/           # admin klaviaturalar + callback fabrikalari
│   ├── middlewares/         # db, user_context, throttling, maintenance
│   ├── filters/             # IsAdmin, IsSuperAdmin, IsSeller, HasPermission
│   ├── services/            # settings, text, group, category, seller, tariff,
│   │                        # subscription, ad, notify, stats
│   ├── scheduler/           # jobs.py (vazifalar), runner.py (APScheduler)
│   └── web/                 # server.py → /health, /stats, /webhook
├── alembic/                 # migratsiyalar
├── scripts/                 # seed.py, backup.sh, restore.sh
├── tests/                   # 221 test (offline E2E + servis testlari)
├── docker-compose.yml       # postgres, redis, migrate, bot, poster, caddy
├── Dockerfile
├── Caddyfile
├── requirements.txt / requirements-dev.txt
└── .env.example
```

---

## 🧩 Muhim xususiyatlar

**Sozlamalar darhol kuchga kiradi.** Admin panelda o'zgargan sozlama
`settings_version` ni oshiradi → bot va poster 15 sekund ichida (odatda darhol)
yangi qiymatni ko'radi. Botni qayta yoqish **shart emas**.

**Keshlangan matnlar.** Barcha matnlar `bot_texts` jadvalida; admin panelda
tahrirlanadi. Noma'lum placeholder botni yiqitmaydi (matnda `{nom}` ko'rinishida
qoladi va logga yoziladi).

**Xatoga chidamlilik.** Redis bo'lmasa bot xotira rejimida ishlaydi;
xatolar `error_log` jadvaliga tushadi va adminlarga (daqiqada 1 martadan ko'p
bo'lmagan holda) xabar ketadi.

**Guruh hayoti.** Bot guruhga qo'shilganda/guruhdan chiqarilganda: yozuv yangilanadi,
huquqlar tekshiriladi, muammolar (admin emas / oddiy guruh / huquq yetishmaydi)
haqida adminga aniq ko'rsatma bilan xabar beriladi.

---

## 🩺 Monitoring va zaxira nusxa

| Nima | Buyruq / yo'l |
|---|---|
| Konteyner holati | `docker compose ps` |
| Salomatlik | `curl localhost:8080/health` |
| Statistika (JSON) | `curl -H "X-Token: $HEALTH_TOKEN" localhost:8080/stats` |
| Bot loglari | `docker compose logs -f bot poster` / `logs/shopbot_YYYY-MM-DD.log` |
| Zaxira nusxa | `./scripts/backup.sh` (kunlik cron tavsiya etiladi) |
| Tiklash | `./scripts/restore.sh backups/shopbot_....sql.gz` |
| Migratsiya | `docker compose run --rm migrate` |

---

## 🛠 Tez-tez uchraydigan muammolar

| Muammo | Sabab va yechim |
|---|---|
| Tugma bosilganda javob yo'q | Bo'lim tugmasi eskirgan bo'lishi mumkin — `/start` ni qayta bosing (xabar yangilanadi) |
| `Konfiguratsiya xatosi: BOT_TOKEN bo'sh` | `.env` to'ldirilmagan (`cp .env.example .env`) |
| `Baza ishlayaptimi? ... (alembic upgrade head)` | Migratsiya bajarilmagan: `docker compose run --rm migrate` |
| `/health` → `degraded` | Redis ishlamayapti (bot ishlaydi, lekin FSM restartda yo'qoladi) — `docker compose up -d redis` |
| Bot guruhdagi xabarlarni ko'rmayapti | @BotFather → `/setprivacy` → **Disable**, so'ng botni guruhdan chiqarib qayta qo'shing |
| Mute/ban ishlamayapti | Guruh **supergroup** emas, yoki botda "A'zolarni cheklash" huquqi yo'q |
| `Telegram'ga ulanib bo'lmadi` | Token xato yoki serverda internet yo'q |
| Webhook ishlamayapti | `WEBHOOK_BASE_URL` domenga mos emas / HTTPS yo'q / `WEBHOOK_SECRET` bo'sh |

---

## 🔐 Xavfsizlik

* `.env` **hech qachon** git'ga tushmaydi (`.gitignore` da).
* Maxfiy ma'lumotlar logga yozilmaydi (`diagnose=False`, Redis manzilidagi parol niqoblanadi).
* Docker konteyneri root bo'lmagan `shopbot` foydalanuvchisida ishlaydi.
* To'lovlar faqat **admin tasdig'i** bilan yoqiladi (avtomatik tasdiq yo'q).

---

## 📅 Bosqichlar (REJA.md 14-bo'lim)

| Bosqich | Mazmun | Holat |
|---|---|---|
| 0 | Poydevor: Docker, DB, kesh, loglar, health, panel skeleti | ✅ **Bajarildi** |
| 1 | Guruhlar va toifalar (CRUD, interval, pauza, biriktirish) | ✅ **Bajarildi** |
| 2 | Sotuvchilar, tariflar, obunalar, eslatmalar | ✅ **Bajarildi** |
| 3 | E'lonlar: usta, rasmlar/albom, moderatsiya | ✅ **Bajarildi** |
| 4 | **Aylanma joylash dvigateli** | ⏳ Keyingi |
| 5 | To'lovlar (chek → tasdiq → obuna) | ⏸ |
| 6 | Posbon + tozalovchi + ruxsatlar | ⏸ |
| 7 | Sanoqchi (invite linklar, majburiy obuna) | ⏸ |
| 8 | Referal, statistika, matnlar, xato jurnali, broadcast | ⏸ |
| 9 | Sayqal: yuklama testi, deploy, hujjat | ⏸ |
