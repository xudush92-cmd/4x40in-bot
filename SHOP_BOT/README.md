# 🛒 SHOP-BOT — Telegram onlayn do'kon uslubidagi e'lonlar boti

Guruhlarga bo'lingan toifalar bo'yicha sotuvchi e'lonlarini **avtomatik, navbat bilan**
joylashtiruvchi bot. Hamma boshqaruv — inline tugmalar orqali, kodga tegmasdan.

> To'liq loyiha rejasi: **[REJA.md](REJA.md)** (16 bo'lim: arxitektura, DB sxemasi,
> admin panel daraxti, jarayonlar, masshtablash, risklar, bosqichlar).
> Joriy holat va **davom ettirish qo'llanmasi** (yangi chat/sessiya uchun):
> **[HOLAT.md](HOLAT.md)** — nima bajarilgan, nima qolgan, muhim shartnomalar.
> Administrator uchun tugma-baqadam amaliy yo‘riqnoma:
> **[ADMIN_QOLLANMA.md](docs/ADMIN_QOLLANMA.md)**.

---

## 📌 Hozirgi holat: **Phase 0–9 kod va oflayn sinovlar ✅ · Jonli qabul sinovlari qolgan**

Phase 9da olingan ruxsat doirasida yuklama smoke, deploy/backup/restore
xavfsizligi va qo‘llanmalar qo‘shildi. **Bu ishlab chiqarishda sinovdan o‘tgan
degani emas:** real PostgreSQL/Redis, Telegram, TLS, bank va restore drill
uchun alohida test serveri kerak. [Deploy va tiklash](docs/DEPLOY.md) ·
[Video-qo‘llanma ssenariysi](docs/VIDEO_SENARIY.md) (**video hali yozilmagan**).

| Ish | Holat |
|---|---|
| Docker Compose (bot + poster + PostgreSQL 16 + Redis 7 + Caddy) | ✅ |
| 45 jadvalli baza sxemasi + Alembic (Phase 8: referal/chek/broadcast kengaytmalari) | ✅ |
| Konfiguratsiya (.env, pydantic-settings, validatsiya) | ✅ |
| Loglar (loguru, kunlik aylanish), xato jurnali (`error_log`) | ✅ |
| Middleware'lar (DB sessiya, foydalanuvchi konteksti, anti-flood, texnik rejim) | ✅ |
| Boshqaruv paneli skeleti: **📊 Statistika** va **⚙️ Sozlamalar** to'liq ishlaydi | ✅ |
| Bot guruhga qo'shilganda: baza'ga yozish, admin huquqlarini tekshirish, adminga xabar | ✅ |
| Rejalashtiruvchi: heartbeat, huquq tekshiruvi, log tozalash, kunlik statistika | ✅ |
| `/health` va `/stats` (HTTP), webhook va polling rejimi | ✅ |
| Seed, atomar backup/restore, preflight/deploy va oflayn regressiya testlari | ✅ (jonli tiklash kutilmoqda) |

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

### Phase 4 — aylanma joylash ✅

| Ish | Holat |
|---|---|
| ⏱ Tasdiqlangan e'lonlar avtomatik navbat bilan ketadi: guruh/toifa intervali, jitter, tinch soatlar, kunlik limit | ✅ |
| 🛡 Atomar DB band qilish (multi-worker), Redis tezlik cheklovi, noma'lum Telegram natijasida dublikatdan himoya | ✅ |
| 🖼 Surat albomi + «Sotuvchi bilan bog'lanish» tugmasi, post tarixi/statistika, eski nusxalarni ixtiyoriy o'chirish | ✅ |
| 🎛 Admin navbati, ⬆️⬇️ tartib, «Hoziroq joylash»; moderatorga cheklov | ✅ |
| 🧪 **258 ta offline test**: servis, soxta Telegram E2E, limiter va oldingi bosqichlar | ✅ |

### Phase 5 — to'lovlar ✅

| Ish | Holat |
|---|---|
| 💳 Admin rekvizitlari: bir nechta karta, tahrir, faollik, tartib va tarixni saqlovchi o'chirish (deaktivatsiya) | ✅ |
| 🛒 Sotuvchi katalogda «To'lash» → narx/karta va nusxalash → chek rasmini yuborish → «To'lovlarim» tarixi | ✅ |
| 🔴 Takroriy chek: Telegram `file_unique_id` xeshi bilan belgi; tasdiqlash bloklanadi; admin sababi bilan rad etadi | ✅ |
| ✅ Admin bank o'tkazmasini **qo'lda tekshirgach** ikki qadamda tasdiqlaydi → obuna beriladi/uzayadi; sotuvchiga javob | ✅ |
| 🔐 Moderator cheklar va moliyaviy sozlamalarga kira olmaydi; chek rasmisiz yuborish faqat `receipt_required=false` bo'lsa | ✅ |
| 🧪 Jami **274 offline test** (7 servis + 9 E2E test qo'shildi); SQLite'da `alembic check` toza | ✅ |

### Phase 6 — posbon, tozalovchi va ruxsatlar ✅

| Ish | Holat |
|---|---|
| 🛡 **Har guruh uchun posbon:** havola/forward/@mention/taqiqlangan so'zlar, domenlar oq ro'yxati, ogohlantirish oynasi/chegarasi, mute muddati va faqat alohida tasdiqdan keyingi ban rejimi | ✅ |
| 🧹 **Har guruh uchun tozalovchi:** kirdi-chiqdi, xizmat, havola va qoidabuzar xabarlar; kechiktirish (0–3600 s), pinlanganlarni saqlash, eski e'londan 1–20 nusxani qoldirish | ✅ |
| 🔑 **Istisnolar:** bitta guruh yoki global, turi/sababi, 1–365 kun yoki doimiy, ko'rish va qaytarib olish; takroriy aktiv ruxsatni DB darajasida to'sish | ✅ |
| 🔴 Jonli o'chirishdan avval har bir guruh uchun **dry-run → alohida tasdiq**; yangi siyosatda avtomatik ban yo'q. Global pauza guruh qoidasini o'zgartirmaydi | ✅ |
| 📋 Xabar/amallar tarixi, Telegram dublikatidan himoya, kutilayotgan amalni bekor qilish, favqulodda guruh pauzasi; post/tozalashga ham guruh + global switch | ✅ |
| 🧪 **302 offline test**; SQLite Alembic `upgrade/check/downgrade`, eski ruxsat dublikatini migratsiya qilish, seed 2 marta bir xil natija | ✅ |

**Boshlash:** admin paneli → «🛡 Posbon», «🧹 Tozalovchi» yoki «🔑 Ruxsatlar» →
guruhni tanlash → avval sinov jurnalini ko'rish → jonli rejimni alohida tasdiqlash.
«Guruhlar → guruh → Sozlamalar → Eski e'lon nusxalari» tugmasi ham yangi guruhni
**faqat sinov rejimida** sozlaydi; haqiqiy o'chirish uchun tozalovchi ekranida
jonli rejimni tasdiqlash kerak. Global switch va guruh pauzasi barcha tegishli
amallarni to'xtatadi, ammo guruh qoidalarini o'chirmaydi.

**Chegara:** real Telegram, bank va PostgreSQL/Redis deploy sinovlari o'tkazilmagan;
offline testlar ularning o'rnini bosmaydi. Phase 7 sanoqchi/kanal shartlari
Phase 6 siyosati bilan bitta xabar bo'yicha birlashtirilgan; guruhlar mustaqil.
Phase 9 uchun alohida ruxsat olingan, oflayn ishlar bajarilgan; jonli qabul
bandlari [yo‘riqnomada](docs/DEPLOY.md) ochiq qayd etilgan.

### Phase 7 — sanoqchi va majburiy kanal ✅

| Ish | Holat |
|---|---|
| 🧮 Guruhga xos N, qolish muddati, kunlik va havola limiti, havola/qo'lda qo'shish manbasi, SOFT/HARD rejimi | ✅ |
| 🔗 Shaxsiy `createChatInviteLink`; `chat_member.invite_link`dan inviter; xizmat xabari fallback; bir odam bir guruhda bir marta | ✅ |
| ⏳ Join request kredit EMAS; muddatdan so'ng scheduler `getChatMember` bilan a'zolikni tekshiradi | ✅ |
| 📣 Majburiy kanal — global yoki guruhga xos, bot kanal adminligini qayta tekshiradi; Telegram noaniq javobida jazo YO'Q | ✅ |
| 🧪 Guruh yoqilganda avval sinov; jonli SOFT o'chirish/HARD mute faqat **alohida tasdiq** bilan; guruh/global pauzalar va posbon/tozalovchi saqlanadi | ✅ |
| 👤 `/takliflarim`, shaxsiy havola va a'zolik holati; admin +/-/0, audit, cheklovni ochish | ✅ |
| 🧪 319 offline test; SQLite migratsiya/check/downgrade, seed ×2, PostgreSQL offline SQL (real server emas) | ✅ |

**Sozlash tartibi:** admin paneli → «🧮 Sanoqchi» → guruh → sanoqchini yoqish
(🧪 sinov) → N/limitlar/manbalarni sozlash → majburiy kanalni kiritish
(botingiz kanalda ADMIN) **yoki kanal shartini o'chirish** → «JONLI rejim»ni
guruhning o'zida tasdiqlash.
Kanal nomi/ID hali ko'rsatilmagan, hech qaysi kanal avtomatik belgilanmagan.
Kanalsiz kanal shartini jonli yoqib bo'lmaydi. SOFT sukut bo'yicha; HARD'ni
tanlash yana sinovga qaytaradi va jonli rejimni **qayta** tasdiqlash talab qiladi.
Guruh switch, global sanoqchi switch, favqulodda pauza hamda `kill_switch`
alohida; o'zgartirish bir guruhdan boshqasiga o'tmaydi.

**A'zo yo'li:** bot bilan shaxsiy chatda `/takliflarim` → guruhni tanlash →
«🔗 Havola olish/yangilash» → uni odamga yuborish. Havola shaxsiy chatdagina
ko'rsatiladi. Hard mute olgan a'zolar guruhda yozolmagani uchun botga /start
bosib, «✅ Tekshirdim» tugmasini shaxsiy chatda ishlatsin; imkon bo'lsa
guruh tavsifida bot manzilini yozib qo'ying. Telegram a'zoligi noma'lum bo'lsa
jazo berilmaydi. Kanal bot adminligi yo'qolsa jazo to'xtaydi.

**Chegara:** haqiqiy Telegram/supergroup/kanal, botning Privacy Mode'i va
PostgreSQL/Redis parallel worker sinovi deploydan oldin shart. Eski dublikat
shaxsiy linklar migratsiyada DB'da faolsizlantirilsa, ularni Telegramda
alohida revoke qilish kerak. Bot huquqini yo'qotsa avvalgi hard mute'ni ochish
uchun admin huquqlarini tiklash yoki qo'lda aralashish zarur bo'lishi mumkin.

---

### ✅ Phase 8 — Referal, hisobotlar va panellar

1. **Referal:** sotuvchi «🎁 Referal»dan kod/havola oladi. Yangi do'st
   `https://t.me/<bot_username>?start=ref_<kod>` bilan botga **birinchi marta
   shaxsiy** kiradi. Migratsiyadan KEYIN guruhda ko'ringan akkaunt ham
   shaxsiy `/start`gacha yangi hisoblanadi; migratsiyadan oldin ko'rilgan
   akkauntning shaxsiy tarixi noma'lum, u ehtiyotkorlik uchun bonusga yaroqsiz.
   Admin «🤝 Referal»da trigger (`signup` yoki **admin tasdiqlagan birinchi UZS
   to'lovi**), bonus turi (`days`, `balance`, `discount`), miqdor/kunlik limitni
   sozlab, yoqishni **alohida tasdiqlaydi**. Standart: **o'chiq**, birinchi chek,
   7 kun, kuniga 5 taklif, chek kamida 50 000 UZS. `days` uchun taklifchida
   faol obuna yo'q bo'lsa bonus keyinroq beriladi. Chegirma/balans bankka
   o'tkaziladigan summani kamaytiradi; 0 so'mlik chek ham admin tasdig'isiz
   obuna bermaydi. Bank cheki tasdig'ini aslo avtomatlashtirmang.
2. **Hisobotlar:** «📊 Statistika»dan kechagi kun, 7 va 30 kun, shuningdek
   har guruh bo'yicha grafikni ko'rish. Admin/super-admin CSV eksport qiladi.
   Job har kuni **00:10**da mahalliy (`timezone` sozlamasi) **kechagi** kunni
   jamlaydi; yangi deploydan oldingi kunlar avtomatik to'ldirilmaydi.
   Bank daromadi faqat **umumiy** satrda: chekda guruh identifikatori yo'q.
3. **Matn/xato/rollar:** «✍️ Bot matnlari»da shablonni ko'rish, preview,
   tahrirlash/reset; «⚠️ Xatolar jurnali»da filtr/tafsilot/hal qilingan
   belgisi; «🛠 Adminlar»da super-admin boshqa admin rolini/auditini
   boshqaradi. Moderator guruh/toifa/sozlamalarni o'zgartira olmaydi.
4. **Tarif va e'lonlar:** «💳 Tariflar» kartasida ruxsatli toifa/guruhlar
   alohida belgilanadi (`cheklovsiz` yoki aniq ro'yxat); sotuvchi e'lonlari
   toifa nomi ostida chiqadi, har e'londa 7/30 kunlik joylash grafigi bor.
5. **Broadcast:** «📣 Broadcast» → auditoriya (shaxsiy chatdagilar,
   sotuvchilar yoki adminlar) → matn/rasm → preview → faqat o'zingizga sinov →
   qabul qiluvchilarni **tasdiqlash**. Poster yuboradi (eng ko'pi **25/s**);
   faol jarayonni pauza/bekor qilish mumkin. Foydalanuvchi shaxsiy chatda
   `/xabarlar_stop` va `/xabarlar_on` bilan chiqadi/qaytadi. Botni bloklaganlar
   hamda **migratsiyadan avval shaxsiy `/start` qilgan, lekin bu haqda bazada
   ishonchli tarixiy belgi yo'q foydalanuvchilar** yangi `/start` qilmaguncha
   auditoriyaga kirmaydi (ammo referal bonusiga yaroqsiz bo'lib qoladi).
   Redis ishlab chiqarish muhitida majburiy: yo'qolsa broadcast xavfsizlik
   uchun to'xtaydi. Telegram noaniq javob bergan xabar
   qayta yuborilmaydi; admin tekshirib yopadi.

**Deploydan oldin:** `alembic upgrade head` (`8d93a17e623c`) va
`python -m scripts.seed` (26 sozlama, 30 matn, 3 namuna tarif) bajaring.
SQLite offline tekshiruvi PostgreSQL/Redis va haqiqiy Telegram/bank sinovini
almashtirmaydi. Phase 9ning deploy/restore amaliy qadamlari uchun
[operator qo‘llanmasi](docs/DEPLOY.md)ga qarang; jonli sinovlar o‘tmagan.

---

## 💰 To'lov oqimi (Phase 5)

1. `python -m scripts.seed`dan so'ng **admin/super-admin** bot panelida
   «💰 To'lovlar → 💳 Rekvizitlar → ➕ Yangi karta»ni ochadi va karta raqami,
   egasi, bank, izoh hamda valyutani kiritadi. 16–19 raqamli karta bir nechta bo'lsa
   har qabul qilingan chekdan so'ng navbatdagi faol karta tanlanadi.
2. Sotuvchi «💳 Tariflar»da pullik tarif yonidagi «To'lash»ni bosadi. Ko'rsatilgan
   summa/kartani tekshiradi, «📋 ... nusxalash»ni bosib pul o'tkazadi va chek
   **rasmini** yuboradi. «To'lovlarim»da holatini ko'radi.
3. Admin «📥 Kelgan cheklar»dagi sotuvchi, tarif, summa va chekni **bank hisobidagi
   haqiqiy o'tkazma bilan alohida solishtiradi**. «✅ Tasdiqlash» → «Ha, bankda
   tekshirdim» obunani beradi/uzaytiradi; «❌ Rad etish» tayyor yoki qo'lda
   yozilgan sababni sotuvchiga yuboradi. Takroriy chekni tasdiqlab bo'lmaydi.

«⚙️ Sozlamalar»da `receipt_required` (chek rasmi majburiyligi) va
`receipt_duplicate_check` (takroriy chekni aniqlash) admin tomonidan boshqariladi;
ikkalasi sukut bo'yicha **yoqilgan**. Tekshiruvni o'chirsangiz yangi cheklar xeshi
saqlanmaydi. Bank tushumini bot avtomatik tekshirmaydi, admin tasdig'i shart.

---

## 🚀 Tez boshlash (Docker Compose v2)

Bu buyruqlar **jonli serverda bu muhitda sinalmagan**; avval
[operator yo‘riqnomasini](docs/DEPLOY.md) o‘qing va test serverda sinang.

```bash
cd SHOP_BOT
cp .env.example .env && chmod 600 .env
# .env ni to‘ldiring: BOT_TOKEN, ADMIN_IDS, POSTGRES_PASSWORD va unga mos
# DB_URL, HEALTH_TOKEN; webhook bo‘lsa DOMAIN, WEBHOOK_BASE_URL, WEBHOOK_SECRET.
mkdir -p logs backups && sudo chown -R 1001:1001 logs
python3 -m scripts.preflight --env .env
./scripts/deploy.sh --check
./scripts/deploy.sh   # interaktiv DEPLOY; backup va migratsiya avtomatik
# Dastlabki super-admin, global sozlamalar, matnlar, namuna tariflar:
docker compose run --rm --no-deps migrate python -m scripts.seed
# Port 8080 hostga ochilmagan: tekshiruvni konteyner ICHIDAN qiling.
docker compose exec bot curl -fsS http://127.0.0.1:8080/health
docker compose logs -f bot poster
```

`USE_WEBHOOK=true` bo‘lsa Caddy/TLS uchun haqiqiy domen va ochiq 80/443
kerak; `false` bo‘lsa script Caddy’ni to‘xtatib, pollingni ishlatadi. Caddy
`/stats`ni tashqariga bermaydi; ichkarida `X-Token` headerini ishlating.
Yaroqsiz `.env.example` bilan productionni ishga tushirmang.

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
PYTHONPATH=. python -m pytest -q        # SQLite + soxta Telegram API, tarmoqsiz
python -m scripts.load_smoke             # 200 guruh/5000 e’lon/24h: oflayn SQLite
python -m pytest -v --tb=short          # batafsil
```

---

## ⚙️ Telegram tomonida bajarilishi SHART bo'lgan sozlamalar

Bot guruhlarda **to'liq** ishlashi uchun (REJA.md 1.2):

| # | Nima | Qayerda |
|---|---|---|
| 1 | **Privacy Mode'ni o'chirish** — aks holda bot guruhdagi oddiy xabarlarni ko'rmaydi (posbon/tozalovchi/sanoqchi ishlamaydi) | @BotFather → `/setprivacy` → **Disable** → botni guruhdan chiqarib, qayta qo'shish |
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
│   │   └── models.py        # 45 jadval (REJA.md 4-bo'lim + Phase 6–8)
│   ├── handlers/
│   │   ├── common.py        # /start, /help, /id, /ping, fallback + sotuvchi holati
│   │   ├── admin/           # panel + guruh siyosati, counter.py, to'lovlar
│   │   ├── seller/          # sotuvchi paneli + ads.py (e'lonlar) + payments.py (chek)
│   │   └── group/           # lifecycle.py + policy.py + counter.py
│   ├── keyboards/           # admin klaviaturalar + callback fabrikalari
│   ├── middlewares/         # db, user_context, throttling, maintenance
│   ├── filters/             # IsAdmin, IsSuperAdmin, IsSeller, HasPermission
│   ├── services/            # settings, text, group, category, seller, tariff,
│   │                        # subscription, ad, posting, posting_limiter, payment,
│   │                        # group_policy_service, counter_service, referral,
│   │                        # report, broadcast, error, admin, notify, stats
│   ├── scheduler/           # jobs.py (sanoqchi/referal/broadcast/stats), poster.py, runner.py
│   └── web/                 # server.py → /health, /stats, /webhook
├── alembic/                 # migratsiyalar
├── scripts/                 # seed.py, backup.sh, restore.sh, deploy.sh, preflight.py, load_smoke.py
├── docs/                    # DEPLOY.md, VIDEO_SENARIY.md (video fayli hali yo‘q)
├── tests/                   # 355 test (offline E2E + servis + infratuzilma smoke)
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
yangi qiymatni ko'radi. Xavfsizlikka oid global pauzalar esa Telegram amali
oldidan DB'dan qayta tekshiriladi. Botni qayta yoqish **shart emas**.

**Keshlangan matnlar.** Standart shablonlar `bot_texts` jadvalida; ularni admin
panelidan ko'rish, preview, tahrirlash va standartga qaytarish mumkin. Noma'lum
placeholder botni yiqitmaydi (matnda `{nom}` ko'rinishida qoladi va logga yoziladi).

**Xatoga chidamlilik.** Ba'zi eski oqimlar Redis bo'lmasa lokal rejimda ishlaydi;
**production broadcast esa Redis'siz xavfsizlik uchun to'xtaydi** (ko'p posterda
25 xabar/s limitini yo'qotmaslik uchun). Xatolar `error_log` jadvaliga tushadi va
adminlarga (daqiqada 1 martadan ko'p bo'lmagan holda) xabar ketadi.

**Guruh hayoti.** Bot guruhga qo'shilganda/guruhdan chiqarilganda: yozuv yangilanadi,
huquqlar tekshiriladi, muammolar (admin emas / oddiy guruh / huquq yetishmaydi)
haqida adminga aniq ko'rsatma bilan xabar beriladi.

---

## 🧪 Phase 9 — oflayn yuklama (jonli sinov emas)

`python -m scripts.load_smoke` alohida SQLite’da 200 guruh va 5000 e’lonni
joylab, 24 ta simulyatsiya soatida `claim_post → commit → finish_post → commit`
qildi: **4800 post, 133,88 s umumiy vaqt, p95 32,57 ms** (mahalliy sinov).
Telegram API, PostgreSQL, Redis, ko‘p worker, real rate-limit, TLS va bank
**tekshirilmagan**. To‘liq qabul tartibi va video ssenariysi yuqoridagi
qo‘llanmalarda.

---

## 🩺 Monitoring va zaxira nusxa

| Nima | Buyruq / yo'l |
|---|---|
| Konteyner holati | `docker compose ps` |
| Salomatlik | `docker compose exec bot curl -fsS http://127.0.0.1:8080/health` (hostda 8080 yopiq) |
| Statistika (JSON) | `docker compose exec bot sh -c 'curl -fsS -H "X-Token: $HEALTH_TOKEN" http://127.0.0.1:8080/stats'` (Caddy tashqariga bermaydi) |
| Bot loglari | `docker compose logs -f bot poster` / `logs/shopbot_YYYY-MM-DD.log` |
| Zaxira nusxa | `BACKUP_REQUIRE_DOCKER=true ./scripts/backup.sh` (productionda kunlik cron + offsite nusxa) |
| Tiklash | `./scripts/restore.sh backups/shopbot_....sql.gz` (**bot/poster to‘xtatilgan holda, avval test serverda**) |
| Migratsiya | `docker compose run --rm migrate` |
| Batafsil tartib | [Deploy / backup / restore / xavfsizlik](docs/DEPLOY.md) |

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
* `/stats` faqat `X-Token` bilan; query tokeni qabul qilinmaydi va Caddy uni
  tashqariga chiqarmaydi. `/health`dagi `degraded` uchun JSONni kuzating.
* Shaxsiy/chek ma’lumotlari, Telegram siyosati va bank bo‘yicha operatorning
  [huquqiy eslatma va qabul ro‘yxati](docs/DEPLOY.md)ga qarang.

---

## 📅 Bosqichlar (REJA.md 14-bo'lim)

| Bosqich | Mazmun | Holat |
|---|---|---|
| 0 | Poydevor: Docker, DB, kesh, loglar, health, panel skeleti | ✅ **Bajarildi** |
| 1 | Guruhlar va toifalar (CRUD, interval, pauza, biriktirish) | ✅ **Bajarildi** |
| 2 | Sotuvchilar, tariflar, obunalar, eslatmalar | ✅ **Bajarildi** |
| 3 | E'lonlar: usta, rasmlar/albom, moderatsiya | ✅ **Bajarildi** |
| 4 | **Aylanma joylash dvigateli** | ✅ **Bajarildi** |
| 5 | To'lovlar (chek → tasdiq → obuna) | ✅ **Bajarildi** |
| 6 | Posbon + tozalovchi + ruxsatlar | ✅ **Bajarildi** |
| 7 | Sanoqchi (invite linklar, majburiy obuna) | ✅ **Bajarildi** (offline) |
| 8 | Referal, statistika, matnlar, xato jurnali, broadcast | ✅ **Bajarildi** (oflayn) |
| 9 | Sayqal: yuklama, backup/restore, deploy va qo‘llanmalar | ✅ **Kod/oflayn bajarildi**; haqiqiy deploy/restore/video yozish qolgan |
