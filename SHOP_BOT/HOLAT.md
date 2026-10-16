# 🔄 HOLAT VA DAVOM ETISH QO'LLANMASI

> **Bu fayl kim uchun?** — Shu loyihani **keyingi chatda** davom ettiradigan yordamchi uchun.
> Yangi chatda avval shu faylni, keyin `REJA.md` ni o'qing — kod aynan qolgan joyidan
> davom ettiriladi. Bu fayl doim **eng oxirgi holat** bo'yicha yangilanadi.

**Oxirgi yangilanish:** 2026-10-16 · **Holat:** Phase 0–9 + limit/yo‘riqnoma + UX-1/2 oflayn ✅ (384 test); UX-3 kabineti navbatdagi ish. **Jonli deploy/restore, Telegram/bank qabul sinovi va video hali bajarilmagan.**

---

## 0. Bir qarashda (TL;DR)

| Nima | Qiymat |
|---|---|
| Loyiha | **SHOP-BOT** — Telegram guruhlariga sotuvchi e'lonlarini navbat bilan avtomatik joylashtiruvchi bot |
| Papka | Repo ichida `SHOP_BOT/` (ildizdagi `AVTO_BOT/` — **boshqa loyiha, tegilmaydi**) |
| Repo | `https://github.com/xudush92-cmd/4x40in-bot` |
| Ish shoxobi | `arena/18e1094b-4x40in-bot` (shu chatning shoxobchasi; `main`ga tegilmaydi) |
| Texnologiya | Python 3.11+/3.12, aiogram 3.31, SQLAlchemy 2.1 (async), PostgreSQL 16, Redis 7, APScheduler, Docker Compose + Caddy + webhook |
| Testlar | **384 test, hammasi o'tdi** (`PYTHONPATH=. .venv/bin/python -m pytest -q`, tarmoqsiz SQLite + soxta Telegram API) |
| Migratsiya | `f789aa7b756f` → `c8a21b6d0f42` → `4f30ae7c912b` → `8d93a17e623c` → **`b6c8e4d0192a`** (46 jadval; SQLite `alembic check` toza) |
| Keyingi qadam | UX-2 tugadi; shu suhbatdagi umumiy ruxsat doirasida UX-3 sotuvchi kabinetini yakunlash. Replitni foydalanuvchi o‘zi yangilatadi; real Telegram/bank/PostgreSQL/Redis qabul sinovi alohida qoladi |
| Ish qoidasi | ⚠️ **Foydalanuvchi ruxsatisiz kod yozilmaydi** — har bosqich oxirida hisobot + ruxsat so'rash |

---

## 1. Kod qayerga yozilgan (GitHub'dagi joyi)

**Repo:** https://github.com/xudush92-cmd/4x40in-bot
**Shoxobcha:** [`arena/18e1094b-4x40in-bot`](https://github.com/xudush92-cmd/4x40in-bot/tree/arena/18e1094b-4x40in-bot) — shu sessiyaning shoxobchasi; `main` **tegilmagan** (`ccbbe99`).

| Commit | Nima qilingan | GitHub havolasi |
|---|---|---|
| `412b74d` | To'liq texnik reja (kod yo'q) | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/412b74d) |
| `147317a` | Tasdiqlangan qarorlar rejaga qo'shildi | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/147317a) |
| `f1c85ff` | **Phase 0** — poydevor (Docker, 41 jadval, Alembic, panel skeleti, seed, 58 test) | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/f1c85ff) |
| `50b77dc` | **Phase 1** — guruhlar va toifalar (104 test) | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/50b77dc) |
| `1fcdbf7` | **Phase 2** — sotuvchilar, tariflar, obunalar (164 test) | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/1fcdbf7) |
| `1ceac25` | **Phase 3** — e'lonlar va moderatsiya (221 test) | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/1ceac25) |
| `0ba9389` | **Phase 4** — aylanma joylash dvigateli (258 test) | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/0ba9389) |
| `ceea3ec` | **Phase 5** — to'lovlar (274 test) | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/ceea3ec) |
| `7ac64b2` | **Phase 6** — guruh siyosati, ruxsatlar va amallar (302 test) | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/7ac64b2) |
| `90da91c` | **Phase 8** — referal, panellar, broadcast (341 test) | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/90da91c) |
| `e17e690`, `51561cf` | **Phase 9** — oflayn yuklama, deploy/backup/restore, amaliy qo‘llanma (355 test) | [branch](https://github.com/xudush92-cmd/4x40in-bot/tree/arena/18e1094b-4x40in-bot) |
| `ad1d1ef` | **UX-0** — panel/ariza sxemasi, kod emas | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/ad1d1ef) |
| `f2306ad` | Alohida so‘ralgan **limitlar ×10 / bot yo‘riqnomasi** bosqichi (363 test) | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/f2306ad) |
| `3c51a90` | **UX-1** — admin navigatsiyasi va guruh diagnostikasi (365 test) | [link](https://github.com/xudush92-cmd/4x40in-bot/commit/3c51a90) |
| Joriy shoxobchaning so‘nggi commiti (`git log -1 --oneline`) | **UX-2** — sotuvchilik arizasi va admin qarori (384 test) | [branch](https://github.com/xudush92-cmd/4x40in-bot/tree/arena/18e1094b-4x40in-bot) |

> ⚠️ **Muhim:** ishni faqat chatning **joriy** shoxobchasida olib boring —
> `main`ga tegmang, qo'shimcha branch/PR ochmang. Keyingi sessiyada shu kodni
> topish uchun yuqoridagi shoxobcha va commit tarixidan foydalaning; chatga
> biriktirilgan shoxobchani almashtirmang.

---

## 2. Yangi chatda birinchi qadamlar (ish muhitini tiklash)

`.venv/` papkasi sandbox snapshot'iga **kirmaydi** — har yangi chatda qayta yaratiladi
(2 daqiqa ish):

```bash
cd /home/user/4x40in-bot/SHOP_BOT
python3 -m venv .venv
.venv/bin/pip install -q -r requirements-dev.txt
PYTHONPATH=. .venv/bin/python -m pytest -q  # 384 test (offline, ~140 sekund)
```

Testlar **offline** ishlaydi: SQLite (vaqtinchalik fayl) + soxta Bot API sessiyasi,
Redis talab qilinmaydi (`tests/conftest.py` ni ko'ring).

Foydali tekshiruvlar:

```bash
.venv/bin/python -m compileall -q app alembic scripts tests      # sintaksis
# Alembic sxema farqi bo'sh bo'lishi kerak (fayl yaratmaydi):
TMP=$(mktemp -d); export DB_URL="sqlite+aiosqlite:///$TMP/al.db"
.venv/bin/alembic upgrade head
.venv/bin/alembic check          # "No new upgrade operations detected."
.venv/bin/python -m scripts.seed
# Seed natijasi: ADMIN_IDS sonicha admin / 26 sozlama / 30 matn / 3 tarif
# Seed'ni ikkinchi marta chaqirish mavjud ma'lumotlarni ko'paytirmaydi.
rm -rf "$TMP"                    # faqat o'zingiz yaratgan vaqtinchalik papka
```

---

## 3. Bot nima qiladi (qisqa, foydalanuvchi tilida)

Telegram guruhlari (supergroup) bozorlar uchun bot:

1. **Toifalar ↔ guruhlar**: har toifa bitta guruhga biriktiriladi (masalan «📱 Telefonlar» → «Telefonlar bozori» guruhi).
2. **Sotuvchilar** bot orqali e'lon qo'shadi (rasmlar bilan). Admin ularga **tarif** beradi (narx, muddat, e'lon limiti, rasm limiti).
3. **Moderatsiya**: admin e'lonni ko'rib, tasdiqlaydi yoki sabab bilan rad etadi.
4. **Aylanma joylash** (Phase 4 bajarildi): tasdiqlangan e'lonlar guruhlarga **navbat bilan, interval bilan** avtomatik joylanadi (albom + «Sotuvchi bilan bog'lanish» tugmasi).
5. Pul (Phase 5 bajarildi): sotuvchi tarifni tanlaydi → kartaga o'tkazadi → **chek** yuboradi → admin bank o'tkazmasini tekshirib tasdiqlaydi → obuna avtomatik yaratiladi/uzayadi. Bot pulni o'zi olmaydi.
6. **Guruh nazorati** (Phase 6 bajarildi): alohida posbon/tozalovchi, istisnolar, dry-run, sabab-amallar tarixi.
7. **Sanoqchi/kanallar** (Phase 7 bajarildi): har guruhda shaxsiy havola, yagona taklif hisobi, majburiy kanal/N, xavfsiz dry-run va admin tasdig'i.
8. **Referal/hisobot/panellar** (Phase 8 bajarildi): shaxsiy havola, tasdiqlangan chek bonusi, 1/7/30 kunlik grafik/CSV, matn/xato/admin paneli va 25/s broadcast.
9. **Limitlar / yo‘riqnoma (alohida ruxsat, 2026-10-16):** admin belgilaydigan maksimal chegaralar ×10, lekin defaultlar/mavjud DB qiymatlari ko‘chirilmagan; albom 10 rasm, 25/s, jitter 30%, chegirma 50% o‘zgarishsiz. `/start`, admin va sotuvchi menyusida rolli qisqa yo‘riqnoma. **O‘sha bosqichda sotuvchilik arizasi hali yo‘q edi**, oddiy `/start` ochiq. UX-1/2/3 rejalari `docs/PANELLAR_VA_ARIZA_REJASI.md`da; keyin foydalanuvchi qolgan uchtasiga birgalikda ruxsat berdi.

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
guruh sozlamalari (interval hozir 1–14400 daq, jitter 0–30%, kunlik limit 1–5000, tinch soatlar),
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

### ✅ Phase 4 — Aylanma joylash
`posting_tick_job` har 10 sekundda due guruhlardan nomzod tanlaydi. Navbat toifa
`position`i va har toifadagi e'lon `position`iga asoslanadi; kursorlar `group_rotation`
va `category_rotation`da saqlanadi. Faol obuna, sotuvchi/guruh/toifa holati,
`ads_left`, tarifning guruh/toifa cheklovi va keyingi ruxsat vaqti tekshiriladi.
Guruh yoki toifa intervali, jitter, tinch soatlar, Tashkent vaqti bilan kunlik
limit va global kill switch/texnik rejim hisobga olinadi.

`app/services/posting_service.py` DB da `sending` yozib, guruh vaqtini CAS bilan
band qiladi; PostgreSQL'da `FOR UPDATE SKIP LOCKED`. `app/services/posting_limiter.py`
Redis Lua rezervatsiyasidan (Redis bo'lmasa lokal zaxiradan) foydalanadi: bir
guruhdagi API jo'natmalari orasida kamida 2s, bir guruhga 20 xabar/daq va jami 25 xabar/s. `app/scheduler/poster.py` surat albomi va
alohida aloqa tugmasini yuboradi; natija `post_log`/`posted_messages`da, hisoblar
va kursorlar bazada saqlanadi. FloodWait kechiktiriladi, Forbidden/BadRequest
guruhni to'xtatadi; navbat bo'shab qolsa ham guruh pauza qilinadi (yangi
e'lon paydo bo'lganda admin qo'lda qayta yoqadi). Noma'lum tarmoq natijasi yoki muddati o'tgan `sending`
**qayta yuborilmaydi**, qo'lda tekshirilishi uchun pauza va admin xabari beriladi.
Sozlama yoqilib tozalovchi jonli rejimi tasdiqlansa, eski postlardan oxirgi
`keep_last_ads` tasi saqlanadi; muvaffaqiyatsiz o'chirishlar `cleanup_log`ga tushadi.

Admin uchun guruh kartochkasida **Navbat**, toifa navbatida **⬆️/⬇️**,
e'lon kartochkasida **Hoziroq joylash**, guruh sozlamalarida **Eski nusxalarni
o'chirish** qo'shildi. Moderator joylash tugmalaridan foydalana olmaydi; admin
amallari `action_log`da qayd qilinadi. Toifa guruhini o'zgartirish mavjud e'lonlarni
sinxronlaydi; interval o'zgarsa navbat vaqti qayta hisoblanadi.

**Cheklovlar:** Telegram real supergroup/deploy sinovi hali o'tkazilmadi;
PostgreSQL `SKIP LOCKED` va Redis Lua haqiqiy serverlarda sinovdan o'tmagan;
SQLite CAS va soxta `Redis.eval` chaqiruvi testlari mavjud. Tarif cheklovlari
Phase 8 da panel orqali sozlanadi (pastdagi Phase 8 bo'limiga qarang).

### ✅ Phase 5 — To'lovlar (yarim avtomatik, MVP)
Admin «💰 To'lovlar → Rekvizitlar»da kartalarni qo'shadi/tahrirlaydi, faol/pauza qiladi,
tartibini o'zgartiradi; «o'chirish» tarixni saqlash uchun deaktivatsiya qiladi. Bir
valyutadagi faol kartalar qabul qilingan cheklarga qarab aylanadi. Sotuvchi katalogdan
pullik tarifni «To'lash» bilan tanlaydi → karta raqamini nusxalaydi → chek rasmini
jo'natadi; `receipt_required=false` bo'lsa cheksiz ariza ham mumkin. Tanlangan
narx/valyuta chek yozilganda saqlanadi. Tasdiq yoki radni faqat admin/super-admin
beradi: bankdagi o'tkazmani tekshirish uchun **alohida tasdiqlash bosqichi** bor.

Chek `file_unique_id`ning SHA-256 xeshi bilan tekshiriladi: takroriy chek belgilab
saqlanadi, adminning tasdiqlashi servisda ham bloklanadi (rad etish mumkin).
`receipt_duplicate_check=false` bo'lsa xesh saqlanmaydi va tekshiruv bo'lmaydi;
ikkala chek sozlamasini moderator o'zgartira olmaydi. Chek + audit avval DB'ga
commit qilinadi, so'ng adminlarga rasm/tugmali xabar boradi; rasm yetkazilmasa
matnli xabar zaxirasi bor. Qaror + obuna bitta tranzaksiyada saqlanadi, sotuvchiga
javob undan keyin yuboriladi. Sotuvchi o'zining to'lovlar tarixini ko'radi,
begona sotuvchining chekiga kira olmaydi.

**Sinov chegarasi:** haqiqiy bank o'tkazmasini bot tekshirmaydi; admin bank ilovasida
qo'lda solishtirishi kerak. Telegram/haqiqiy PostgreSQL/Redis deploy va bir vaqtda
bir nechta worker bilan poyga sinovlari hali o'tkazilmagan. `alembic check` faqat
SQLite bilan qilingan, sxemaga o'zgartirish kiritilmadi.

### ✅ Phase 6 — Posbon + tozalovchi + ruxsatlar (guruhlar bo'yicha alohida)
Admin paneli → «🛡 Posbon» / «🧹 Tozalovchi» / «🔑 Ruxsatlar» → guruhni tanlash.
Har guruhning `guard_settings`, `cleaner_settings`, `group_settings` qiymatlari
mustaqil. Posbon: havola/forward/@mention/taqiqlangan so'zlar, domenlar oq
ro'yxati, jazo darajasi (warn/mute/ban), ogohlantirish oynasi/chegarasi va mute
muddati. Avtomatik ban standartda yo'q; uni admin aynan shu guruhda **alohida
tasdiqlaydi**. Cleaner: kirdi-chiqdi, xizmat, havola, qoidabuzar xabar, hozir 0–36000 s
kechikish, mahkamlanganlarni saqlash, e'londan 1–200 nusxani qoldirish. Posbon
faol bo'lmasa ham cleaner uning filtrlaridan o'zicha foydalana oladi; jazo bermaydi.
Phase 7dagi sanoqchi/majburiy kanal tekshiruvi endi xuddi shu xabar-amali
rezervatsiyasini ishlatadi; posbon/tozalovchining mustaqil qoidalari buzilmagan.

Yangi siyosat **o'chiq va dry-run**: qoidani yoqish faqat jurnalga yozadi, jonli
rejim alohida tasdiqlanadi. Eski Phase 4 e'lon nusxalari tugmasi ham yangi guruhda
faqat sinovda sozlaydi; jonli rejim tozalovchi ekranida tasdiqlanadi. Global
`guard_enabled_global`/`cleaner_enabled_global`, `kill_switch` va `maintenance_mode`
Telegram amali oldidan DB'dan keshsiz qayta tekshiriladi; global pauza guruh
qoidasini o'zgartirmaydi. Favqulodda guruh pauzasi posbon, tozalovchi va joylashni
to'xtatadi; huquq yangilanishi qo'lda berilgan pauzani olib tashlamaydi.

`group_message_actions`da `(group_id, message_id)` unique: dublikat Telegram
update yoki ikki worker ayni xabarni qayta o'chirmaydi. `pending` CAS orqali
scheduler oladi; noma'lum `running` amal qayta bajarilmaydi. Admin «kutilayotgan
amallar»dan uni tasdiqlab bekor qila oladi; **allachon Telegram'ga yuborilgan
API chaqiruvi ortga qaytmaydi**. Huquq yo'qolsa guruh pauza + admin xabari,
`violation`, `cleanup_log`, `restriction`, `action_log`da sabab/amallar saqlanadi.
Ruxsatlar guruhga yoki global: turi, sababi, hozir 1–3650 kun yoki doimiy; qaytarib
olish auditi bor. Qisman unique indekslar NULL global scope va guruh scopeda
faqat bitta aktiv ruxsatni ta'minlaydi; expired yozuv qayta berilganda tarixda
qoladi. Qo'lda mute/ban/ochish va warning reset faqat admin tasdig'i bilan.

**Migratsiya:** `c8a21b6d0f42` yangi jadval/indeks va cleaner `dry_run` maydoni.
Eski faol cleaner oldingi sozlamasini saqlaydi (`dry_run=false`), yangi guruh
`dry_run=true`; eski ruxsat dublikatlaridan faqat so'nggisi aktiv qoladi.
**Tekshiruv chegarasi:** 28 yangi offline test va SQLite upgrade/check/downgrade,
dublikat migratsiya/seed o'tgan; haqiqiy PostgreSQL/Redis, Telegram, ko'p process
race va Privacy Mode'ni ishlab turgan guruhda sinash deploy oldidan qoladi.

### ✅ Phase 7 — Sanoqchi + majburiy kanal (guruh bo'yicha to'liq sozlanadi)
Admin paneli → «🧮 Sanoqchi» → guruh: yoqish/o'chirish, hozir N (0–1000),
qolish muddati (0–100800 min), kunlik limit (1–1000), shaxsiy havola limiti
(1–1000), havola yoki qo'lda qo'shish manbasi, kanal sharti va DM alohida.
«🌐 Umumiy kanallar» barcha guruhlarga faqat **o'zida kanal sharti yoqilgan** bo'lsa
qo'llanadi; guruh kanallari ham alohida qo'shiladi. Admin kanalni @username
(yoki `-100...` ID + private link) bilan yuboradi; botning kanalda adminligi
Telegram orqali tekshiriladi. **Aniq kanal hali berilmagan; birortasi avtomatik
tanlanmaydi.** Guruh supergroup, bot admin va Privacy Mode o'chirilgan bo'lishi kerak.

Yangi guruh sanoqchisi o'chiq, yoqilganda ham **dry-run** (jazo yo'q). SOFT
(standart) jonli rejimda shartni bajarmagan xabarni o'chiradi, HARD qo'shimcha
mute qiladi. Jonli rejim har bir guruhda alohida, joriy sozlamaga bog'langan
tasdiq va bot huquqlarini qayta tekshirish bilan yoqiladi. Global counter switch,
kill switch, texnik rejim va guruh pauzasi bot API amalidan OLDIN qayta ko'riladi.
Telegram huquqi yoki kanal javobi noma'lum bo'lsa **fail-open**; bitta xabarni
Phase 6 posboni/tozalovchisi bilan ikki marta o'chirmaslik uchun
`group_message_actions`dagi unique `(group_id,message_id)` ishlatiladi.

`createChatInviteLink` shaxsiy havolasi API'dan oldin `pending:` yozuv bilan
band qilinadi, noaniq tarmoq natijasida dublikat link yaratilmaydi; admin noaniq
linkni qo'lda bekor qila oladi. `chat_join_request` o'zi sanalmaydi;
`chat_member.invite_link` asosiy manba, xizmat xabari fallback (Phase 6 tozalash
bilan birga ishlaydi). Bir odam bir guruhda bir marta (`invite_events` unique),
o'z-o'zini taklif qilish rad, kamida belgilangan muddatdan so'ng scheduler
**haqiqiy a'zolikni getChatMember bilan qayta tasdiqlaydi**, keyin kunlik limitni
hisobga olib kredit beradi. `counter_totals`da guruhga xos jamlanma, foydalanuvchi
uchun `/takliflarim` (shaxsiy chatda holat, kanal tugmasi, havola), admin uchun
foydalanuvchi bo'yicha +/-/0 va `counter_audit`/`action_log`. Counter qo'ygan
mute shart bajarilganda yoki funksiya o'chirilganda, boshqa faol posbon/admin
cheklovi bo'lmasa, schedulerda yechiladi; bot huquqi yo'qolsa qo'lda aralashuv
kerak bo'lishi mumkin.

**Migratsiya:** `4f30ae7c912b`: `counter_settings`ga `dry_run` va havola limiti,
3 yangi jadval, faol havola uchun qisman unique indeks. Oldindan ikki faol
shaxsiy link bo'lsa faqat so'nggisi DB'da faol qoladi; Telegramdagi eski havolalar
alohida tekshirilishi kerak. SQLite upgrade/check/downgrade/upgrade, 3 dublikat
linkni ko'chirish, seed ×2 va PostgreSQL uchun **offline SQL** tekshirildi;
PostgreSQL serveri, Redis, real Telegram kanali/supergroupi va ko'p worker race
sinovdan o'tmagan — deploydan avval tekshiring. 17 yangi offline test.

### ✅ Phase 8 — Referal, hisobot, matn/xato panellari va broadcast

- **🤝 Referal (guruh sanoqchisidan mustaqil):** sotuvchining kodi bilan yangi
  shaxsiy `/start ref_<kod>`; bot akkauntni migratsiyadan keyin avval guruhda
  ko'rgan bo'lsa ham birinchi shaxsiy start hisoblanadi. Migratsiyadan oldin
  ko'rilgan eski akkauntlar bonusga yaroqsiz (shaxsiy tarix noma'lum).
  O'zini taklif qilish, ikkinchi kod, takror bonus va
  kunlik limitdan oshish rad etiladi. `signup` yoki **faqat admin tasdiqlagan
  birinchi UZS cheki** (`min_payment` bilan) tanlanadi. Bonus `days` (faol tarif
  bo'lmasa navbatda qoladi), `balance` (chekda sarflanadi), `discount` (bir marta)
  ko'rinishida; rad etilgan chekdagi bandlov qaytariladi. Statistikasi sotuvchi
  va admin panelida. Standartda **O'CHIQ** (`referral_enabled=false`), shart
  `first_payment`, 7 kun, kuniga 5, minimal 50 000 UZS. Admin «🤝 Referal»da
  sozlaydi va yoqishni alohida tasdiqlaydi; global sozlamadagi eski bir bosqichli
  toggle orqali yoqib bo'lmaydi.
- **📊 Hisobot:** mahalliy vaqt zonasidagi yopilgan kechagi kun `00:10`da
  `stats_daily`ga UPSERT; 1/7/30 kunlik umumiy/guruh grafigi va 1/7/30 kunlik CSV.
  Guruhning alohida daromadi soxta ko'rsatilmaydi: bank cheki guruhga bog'lanmagan;
  tushum faqat umumiy satrda. Faol e'lonlar — kun oxiridagi snapshot, yig'indi
  emas. Birinchi deployda hali jamlanmagan kunlar 0/bo'sh ko'rinadi.
- **✍️ Matnlar va ⚠️ xatolar:** `bot_texts` ro'yxati, tahrir, HTML xavfsiz preview,
  placeholder validatsiyasi, standartga qaytarish; `error_log` filtri, tafsilot,
  hal qilingan deb belgilash. Moderator matnlarni faqat ko'radi; xatolarni
  admin/super-admin ko'radi.
- **📣 Broadcast:** matn/rasmli qoralama → preview → adminning o'ziga sinov →
  auditoriyani tasdiqlab snapshot qilish → poster navbati. Faqat shaxsiy `/start`
  bosgan, bloklanmagan va `/xabarlar_stop` bilan chiqmagan odamlar. `all`,
  `sellers`, `admins` auditoriyasi. Redis va poster bilan **ko'pi 25 xabar/s**,
  umumiy posting limiter ham qo'llanadi; prod'da Redis ishlamasa yuborish
  xavfsizlik uchun to'xtaydi. 429 kechiktiriladi, noaniq tarmoq natijasi
  **qayta yuborilmaydi** (admin qo'lda yopadi); pauza/bekor qilish mavjud.
- **Qo'shimchalar:** tarifning ruxsat etilgan toifa/guruhlarini panelda boshqarish
  (`None` — cheklovsiz, `[]` — hech narsa), sotuvchi ro'yxatida toifa sarlavhalari,
  e'lonning 7/30 kunlik post grafigi; admin rollari qo'shish/rol/o'chirish,
  audit, super-admin himoyasi. Eski guruh/toifa callback'lari va global sozlamalarni
  moderator o'zgartira olmaydi; Phase 6 guruhga xos qoidalar o'zgarishsiz qoldi.

**Migratsiya:** `8d93a17e623c` — faqat mavjud jadvalga ustun/unique/FK;
eski cheklar uchun `base_amount=amount`; eski userlarning `referral_legacy=true`
bo'ladi — tarixiy shaxsiy/guruh tashrifini ajratib bo'lmagani uchun ular
**keyinchalik yangi referal bonusini ola olmaydi**. `private_started_at` bo'sh:
aniq shaxsiy `/start` Telegram'dan kelgachgina kiritiladi, undan oldin
broadcast yuborilmaydi. SQLite eski chek bilan upgrade/check, yangi bazada
downgrade/upgrade/check, seed ×2 (2 test admin / 26 sozlama / 30 matn,
avvalgi tarif + 3 namuna tarif), PostgreSQL **offline SQL** tekshirildi.
Haqiqiy PostgreSQL/Redis/Telegram, bank bilan tekshiruv, yuklama va ko'p worker
sinovi Phase 8 vaqtida qoldirilgan edi. Phase 9 oflayn navbat yuklamasi pastda;
jonli qabul sinovlari hanuz bajarilmagan. `AVTO_BOT/`ga va `main`ga tegilmagan.

### ✅ Phase 9 — oflayn sayqal; ishlab chiqarish qabuli hali yo‘q

Foydalanuvchi Phase 8 hisobotidan so‘ng **«davom et»** deb Phase 9ga alohida
ruxsat berdi. Shu bosqichda quyidagilar amalga oshirildi:

- `scripts/load_smoke.py`: vaqtinchalik **SQLite** bazasida 200 guruh / 5000
  sintetik e’lon / 24 simulyatsiya soati; har soatda `due_group_ids`, har guruhda
  `claim_post → commit → finish_post → commit`. **4800 post**, 133,88 s jami;
  claim+finish p50 **26,98 ms**, p95 **32,57 ms**, p99 **38,94 ms** (faqat shu
  mashina/SQLite). Telegram yuborish, rate-limit, real APScheduler, ikki worker,
  PostgreSQL va Redis **sinovga kirmagan**. Kichik parametrli CI smoke ham bor.
- `scripts/backup.sh`: dump xatosida qisman fayl o‘chadi, gzip tekshiriladi,
  atomar nomlanadi (`0600`), saqlash kunlari tekshiriladi; deployda faqat
  Docker konteyneridan backupga ruxsat. `restore.sh`: buzilgan arxiv rad
  etiladi, konteyner/ishlayotgan bot/poster/TTY/ikki tasdiq, `psql`da
  `ON_ERROR_STOP=1` va
  yagona tranzaksiya. **Faqat soxta Docker/psql bilan test qilindi; real tiklash
  sinovi emas.**
- `scripts/preflight.py`, `scripts/deploy.sh --check`: `.env` shablon va zaif
  parollar, DB URL mosligi, webhook domeni/sekreti tekshiriladi; Compose config
  tekshiruvi. Operator tasdiqlaydigan deploy: DB/Redis → build → bot/poster stop
  → backup → migratsiya → restart, pollingda Caddy to‘xtaydi. Docker bu
  sandboxda yo‘q: deploy **haqiqatda bajarilmadi**.
- `app/web/server.py`: `/stats` query-token qabul qilmaydi, `X-Token`ni solishtiradi;
  webhook faqat faol bot rejimida ro‘yxatdan o‘tadi, noto‘g‘ri update 400,
  dispatcher tashqi xatosi 503. `Caddyfile` tashqi `/stats`ni yopadi. Ichki
  aiogram handler xatolari hozircha aiogram `on_error` tomonidan yutiladi:
  webhookda ayrim handler xatolari 200 sifatida qaytishi mumkin; real
  at-least-once/idempotentlik qabul sinovisiz kafolatlanmaydi.
- [Operator deploy/tiklash qo‘llanmasi](docs/DEPLOY.md), [video ssenariysi](docs/VIDEO_SENARIY.md)
  va huquqiy/Telegram siyosati eslatmalari o‘zbekcha. **Video fayli yozilmagan**:
  test superguruh, server va yozish vositasi talab etiladi.

**Tekshiruv:** 355 offline pytest; `compileall`, o‘zgargan Python fayllarida Ruff,
`bash -n`, `git diff --check`; SQLite Alembic upgrade/check/downgrade/upgrade/check
(ikkalasida diff bo‘sh), seed 2 marta (2 admin / 26 sozlama / 30 matn / 3 tarif),
PostgreSQL 915 qatorli **offline SQL**. Jonli Docker/PostgreSQL/Redis/Telegram/
bank, TLS, video va restore drill **o‘tmagan**. Phase 6ning har guruh uchun
alohida qoida/tumblerlari o‘zgarmadi; `AVTO_BOT/`, `main` tegilmagan.

### ✅ UX-0 hujjat + alohida limit/yo‘riqnoma bosqichi (2026-10-16)

`docs/PANELLAR_VA_ARIZA_REJASI.md`: kelajak admin navigatsiyasi/sotuvchilik arizasi
**faqat reja**; ariza, admin navbati va kabinetni qayta tuzish **bajarilmadi**.
Foydalanuvchining keyingi so‘rovi doirasida admin belgilaydigan **faqat maksimal
chegaralar ×10**: guruh/toifa intervali 1–14400 daqiqa, kunlik post 1–5000,
posbon warn 200/mute 100800 daqiqa/oyna 7200 soat/ro‘yxat 300,
tozalovchi 200 nusxa/36000 soniya, sanoqchi N 1000/qolish 100800 daqiqa/
kunlik-havola 1000/qo‘lda ±10000, istisno 3650 kun. Tarif 36500 kun/
10000 e’lon/narx 9 999 999 990 so‘m, obuna qo‘lda 1000000 e’lon; referal
kunlik 500, kun bonusi 3650, balans bonusi 10 mln va minimal chek narx bilan
mos. **Mavjud va default qiymatlar o‘zgarmadi; migratsiya yo‘q.** Chegirma
50%, albom 10 rasm, jitter 30% va broadcast 25/s xavfsizlik chegaralari
oshirilmadi. Aniq jadval va xavf eslatmalari rejaning 3-bo‘limida.

`/start` va admin/sotuvchi paneli yangi **📖 Foydalanish yo‘riqnomasi** tugmasini
ko‘rsatadi; moderatorga faqat moderatsiya, sotuvchiga e’lon/tarif/chek,
oddiy odamga `/takliflarim` va kanal bo‘yicha qisqa sahifalar chiqadi.
`guide:` callbackning rolini server DBdan tekshiradi; shaxsiy chat bilan
cheklangan. O‘chirilgan sotuvchiga eski `/start` paneli ko‘rsatilmaydi;
orqaga qaytish referal `/start`ni qayta ishlamaydi. Avvalgi
sana bilan qotirilgan bitta testning `setup(now=...)`si barqarorlashtirildi;
Phase 6/7 eski «chegaradan tashqarida» testlari yangi chegara + 1 ga moslandi.

**Oflayn tekshiruv:** 363/363 pytest; `compileall`; vaqtinchalik SQLite Alembic
`upgrade head` + `check` («No new upgrade operations detected.»), seed ×2:
2 admin / 26 sozlama / 30 matn / 3 tarif. Yangi sinovlar rol/forged callback,
guruh izolyatsiyasi, chegaraning o‘zi va undan +1, katta tarif/chek va
xavfsizlik istisnolarini qamraydi. Haqiqiy Telegram/PostgreSQL/Redis/bankda
sinov qilinmagan, bu **jonli qabul emas**.

### ✅ UX-1 — admin navigatsiyasi va har guruh diagnostikasi (2026-10-16)

Asosiy `/start`/`/admin` panelida faqat **qaror kutayotgan moderatsiya/chek** navbati
va beshta yo‘nalish: 👥 Guruhlar, 🛒 Savdo, 📢 Kontent, 📊 Nazorat,
⚙️ Tizim. «Barcha bo‘limlar» va eski `adm:section` tugmalari ishlaydi,
admin rol tekshiruvi serverda saqlanadi. Guruh kartasida «🧮 N kishi» va
«📣 Kanal a’zoligi» alohida; «🔍 Nega ishlamayapti?» global → guruh →
qoida → sinov/jonli → bot huquqlarini **faqat o‘qish** bilan tushuntiradi,
sozlamalarni/matritsani o‘zgartirmaydi. Telegram holati oxirgi tekshiruvga
asoslangan va qayta tekshirish tugmasi alohida. Adminlar uchun nazorat
bo‘limida so‘nggi 15 amal ko‘rsatiladi. `tests/test_ux1_navigation.py`:
2 yangi E2E/servis testi; eski bosh menyu testi yangi navigatsiyaga moslandi.
O‘sha bosqichda ariza hali yo‘q edi; keyingi UX-2da joriy qilindi.

### ✅ UX-2 — sotuvchilik arizasi va admin qarori (2026-10-16)

`app/db/models.py` va `alembic/versions/b6c8e4d0192a_ux2_seller_applications.py`:
46-jadval `seller_applications` qo‘shildi; tarix saqlanadi, qisman UNIQUE
indeks bir foydalanuvchida bitta ochiq arizani ta’minlaydi. `SellerStatus.PENDING`
hamon **tarifsiz sotuvchi**, ariza esa mustaqil `ApplicationStatus.PENDING`.
Shaxsiy `/start` ochiq: ism/do‘kon (2–64 belgi), `@username` yoki telefon,
preview/tahrir/bekor qilish/holat. Admin/super-admin uchun asosiy navbatda va
«🛒 Savdo → 📥 Arizalar»da qaror, sabab bilan rad, audit va commitdan keyin DM;
moderatorga server/servisda rad (shu jumladan eski `adm:section`dan sotuvchi/tarif kabi maxfiy bo‘limlarga kirish). Takror bosish bitta ID/qaror bo‘lib qoladi;
rad qaroridan so‘ng 1 soat kutish va 24 soatda 3 ta ariza cheklovi bor.
Admin qo‘lda ID bilan qo‘shsa ochiq ariza shu tranzaksiyada yopiladi; eski
sotuvchilar ko‘chirilmaydi, bloklangan/o‘chirilgan hisob ariza bilan tiklanmaydi.
Tasdiq **faqat sotuvchi panelini ochadi**, avtomatik tarif, chek, e’lon yoki
`is_verified` belgisini bermaydi. `ref_<kod>` birinchi tashrif bonusi saqlanadi,
ariza/tasdiq uni takrorlamaydi. Admin yoki foydalanuvchiga DM yuborilmasa DB
qarori/navbati qoladi, `/start`dan holatni ko‘rish mumkin.

Oflayn `tests/test_ux2_applications.py` (18 test) va
`tests/test_ux2_migration.py` (1 test): HTML/uzunlik, spam chegarasi, UNIQUE,
rol/idempotent qaror, qo‘lda qo‘shish, commitdan keyingi xabar, referal,
oldingi sotuvchini saqlagan migratsiya/downgrade. **Haqiqiy PostgreSQL parallel
worker, Redis FSM, Telegram DM va jonli Replit sinovi bu natijadan kelib
chiqmaydi.** UX-3 hali joriy qilinmagan; Replitni bu yerdan yangilamaymiz.

---

## 5. Test holati (384 test)

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
| `tests/test_posting_service.py` | Nomzod, kursor, CAS, interval, limit, pauza, xatolar | 14 |
| `tests/test_phase4_poster.py` | Albom/aloqa, FloodWait, Forbidden, dublikatning oldi, eski post, statistika | 15 |
| `tests/test_phase4_flows.py` | Admin navbati, tartib, qo'lda jo'natish, moderator cheklovi, cleaner tugmasi | 5 |
| `tests/test_posting_limiter.py` | Guruh/global tezlik va Redis Lua band qilish | 3 |
| `tests/test_payment_service.py` | Karta CRUD/aylanma, chek dublikati, tasdiq/rad, obuna uzayishi, tarix | 7 |
| `tests/test_phase5_payments.py` | **E2E**: karta FSM → chek → admin qarori, moderator, cheksiz to'lov, narx, xabar zaxirasi | 9 |
| `tests/test_phase6_policy.py` | **E2E + servis**: dry-run, dublikat, izolyatsiya, jazo, cleaner, kechiktirish, istisno | 17 |
| `tests/test_phase6_admin.py` | **E2E**: har guruh paneli, tasdiqlar, global switch, favqulodda pauza, qo'lda jazo | 9 |
| `tests/test_phase6_posting.py` | Eski e'lonlar, pin, global/guruh to'xtashi | 2 |
| `tests/test_phase7_counter.py` | **E2E + servis**: shaxsiy link, join, vaqt/limit, kanal, SOFT/HARD, mute, admin FSM/audit, pauza | 17 |
| **Phase 7 gacha** | | **319** |
| `tests/test_phase8_referral.py` | `/start` E2E, kunlik limit, bonus/chek/balans, eski user va global switch | 8 |
| `tests/test_phase8_broadcast.py` | Manzil snapshot'i, opt-out, rate/Redis, noaniq natija | 4 |
| `tests/test_phase8_migration.py` | Eski user/chek backfill, yangi user default, downgrade/upgrade | 1 |
| `tests/test_phase8_reports.py` | Lokal kun, guruh statistikasi, CSV va admin grafik/rol | 2 |
| `tests/test_phase8_panel.py` | Matn shabloni, xato paneli, moderator roli | 3 |
| `tests/test_phase8_finishing.py` | Tarif cheklovi E2E, e'lon grafigi, adminlar/audit, eski callback roli | 4 |
| `tests/test_phase9_infra.py` | Preflight, backup atomarligi, restore tasdig‘i, Docker mock, deploy `--check` va operator ketma-ketligi | 10 |
| `tests/test_phase9_web.py` | `/stats` header, webhook marshruti/validatsiya/dispatch xatosi | 3 |
| `tests/test_phase9_load.py` | Mustaqil guruhlarning oflayn tezlashtirilgan navbati (kichik smoke) | 1 |
| `tests/test_limits_and_guides.py` | ×10 chegaralar, eski hard cheklovlar, guruh izolyatsiyasi, yuqori narx/chek, rollarga mos in-bot yo‘riqnoma (E2E) | 8 |
| `tests/test_ux1_navigation.py` | UX-1: menyu, moderator, har guruhning diagnostikasi va read-onlyligi | 2 |
| `tests/test_ux2_applications.py` | UX-2: ariza FSM, rol, dublikat/UNIQUE, kutish/limit, qaror/audit/DM, referal va qo‘lda qo‘shish | 18 |
| `tests/test_ux2_migration.py` | UX-2: eski sotuvchi saqlanadi, yangi pending UNIQUE, downgrade/upgrade/check | 1 |
| **JAMI** | | **384** |

**Phase 7 tekshiruvi (tarix):** 319 offline test o'tdi; `compileall` va Phase 7 o'zgartirilgan
fayllarda Ruff toza (`models.py`da avvaldan mavjud UP037/UP045 qoidalari
alohida saqlanadi); vaqtinchalik SQLite'da `alembic upgrade/check/downgrade/upgrade`:
«No new upgrade operations detected.»; 3 ta eski faol havola dublikatini migratsiya
qilish tekshirildi. Seed ikki marta: 1 super-admin / 25 sozlama / 30 matn / 3 tarif;
PostgreSQL **offline SQL** kompilyatsiyasi o'tdi (haqiqiy server sinovi emas).
**Phase 8 tekshiruvi:** 341 offline test; `compileall`; eski to'lovni
saqlagan SQLite bazadan migratsiya/check, bo'sh bazada downgrade/upgrade/check,
seed ×2 (26 sozlama, 30 matn, 3 namuna tarif) va PostgreSQL offline SQL.
Phase 8 o'zgargan Python fayllari Ruff'dan o'tadi (`models.py`ning eski
UP045/UP037 annotatsiya qoidalari istisno). To'liq repodagi **203 ta avvalgi
Ruff xatosi** (`models.py` va eski Alembic/testlar) ommaviy avtomatik
tuzatilmagan: Phase 8 vazifasidan tashqari, regressiya xavfi bor.
Haqiqiy PostgreSQL/Redis/Telegram, bank va parallel worker tekshiruvi
Phase 9ning oflayn sayqalidan keyin ham deploy qabuli uchun alohida qoladi;
yuqoridagi Phase 9 bo‘limi va [operator qo‘llanmasi](docs/DEPLOY.md)ga qarang.

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
│   ├── db/models.py            # 46 jadval (Phase 8 + UX-2 ariza)
│   ├── services/
│   │   ├── settings_service.py     # 26 global sozlama (restart kerak emas)
│   │   ├── group_service.py, category_service.py
│   │   ├── seller_service.py, tariff_service.py, subscription_service.py, application_service.py
│   │   ├── ad_service.py           # ⬅️ Phase 3 (e'lon hayot sikli)
│   │   ├── posting_service.py, posting_limiter.py  # Phase 4 DB navbat va limiter
│   │   ├── payment_service.py   # Phase 5 karta/chek/qaror/obuna
│   │   ├── group_policy_service.py  # Phase 6 guruh filtr/jazo/ruxsat qoidalari
│   │   ├── counter_service.py  # Phase 7 sanoqchi/kanal/join/kredit/audit
│   │   ├── referral_service.py, report_service.py, broadcast_service.py  # Phase 8
│   │   └── text_service.py, error_service.py, admin_service.py, notify.py, stats_service.py
│   ├── handlers/
│   │   ├── __init__.py         # build_root_router() — router tartibi MUHIM
│   │   ├── common.py           # /start, fallback, sotuvchi holati
│   │   ├── applications.py     # UX-2 user arizasi + admin navbati
│   │   ├── admin/              # panel, settings, groups, policy, counter.py va boshqalar
│   │   ├── seller/ads.py, seller/payments.py  # e'lon ustasi va chek FSM
│   │   └── group/              # lifecycle, policy, counter.py (invite + xabar)
│   ├── keyboards/              # admin, groups, policy, counter.py va boshqalar
│   ├── scheduler/jobs.py       # posting_tick_job + counter_job + cleanup
│   ├── scheduler/poster.py     # Telegram albomi, aloqa, xatolar, jo'natish
│   ├── scheduler/runner.py     # job ro'yxati (posting_tick — har 10 sekund)
│   └── web/server.py           # /health, /stats, webhook
├── tests/                      # 384 test (+ conftest.py, fake_telegram.py)
├── alembic/versions/f789aa7b756f_boshlangich_sxema.py
├── alembic/versions/c8a21b6d0f42_phase6_xabar_siyosati.py
├── alembic/versions/4f30ae7c912b_phase7_sanoqchi.py
├── alembic/versions/8d93a17e623c_phase8_referral_panels_broadcast.py
├── alembic/versions/b6c8e4d0192a_ux2_seller_applications.py
├── scripts/seed.py, backup.sh, restore.sh, deploy.sh, preflight.py, load_smoke.py
└── docs/DEPLOY.md, VIDEO_SENARIY.md  # operator yo‘riqnomasi; video fayli yo‘q
```

---

## 7. Muhim shartnomalar (davom ettirishda buzilmasin)

### Router tartibi (`app/handlers/__init__.py`)
```
admin_router → seller_payments_router → seller_ads_router → seller_router → application_user_router → group_router → common.router
```
E'lon va to'lov router'lari (`app/handlers/seller/{ads,payments}.py`) **root darajasida**
turadi (sabab: yuqoridagi Phase 3 xatosi). Sotuvchi panelida `SellerPanelCB.filter()`
router filtri bor; to'lov router'ida esa `SellerPaymentStates` bilan kelgan rasmlar
ushlanadi. Ariza (`ApplicationCB`, user FSM/admin FSM) sotuvchi routeridan
**alohida** ulangan, admin qarorida DB roli servisda ham tekshiriladi.
**Boshqa prefiksdagi router'ni seller_router ichiga qo'shmang**.
`group_router`: lifecycle → counter (chat_member/join request va /takliflarim) →
policy (oddiy xabarlar). Phase 6 policy handleri join xizmat xabarida Phase 7
`service_join`ni chaqirib, o'sha xabarni cleanerda ham ishlashiga ruxsat beradi;
jonli counter xabari `group_message_actions`ni band qilsa guard/cleaner qayta
o'chirmaydi, dry-run bo'lsa Phase 6 qoidalari odatdagidek davom etadi.

### Callback prefikslari (64 bayt chegarasi tekshiriladi)
`adm:` admin panel · `grp:` guruhlar · `feat:` funksiya tumbleri · `cat:` toifalar ·
`slr:` sotuvchilar · `trf:` tariflar · `sp:` sotuvchi paneli · **`ad:` e'lonlar** ·
**`mod:` moderatsiya** · **`pst:` joylash/navbat** · **`pay:` to'lovlar** ·
**`pol:` guruh siyosati/istisnolar** · **`mine:` foydalanuvchi sanoqchisi** ·
**`acnt:` admin sanoqchisi** · `ref:` referal sozlamalari · `st8:` hisobot ·
`txt:` matnlar · `err:` xatolar · `bcast:` broadcast · `aops:` adminlar · `nav:` navigatsiya ·
`guide:` shaxsiy chatdagi rolli yo‘riqnoma (rol serverdan olinadi) ·
`appx:` sotuvchilik arizasi/user-admin navbati (ID va sahifa; user statusida ID callbackda berilmaydi).
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
- `application_service`: `precheck/submit/pending_for/list_pending/count_pending/decide/approve_manually`; pending UNIQUE, AdminRole.ADMIN+, CAS va eski sotuvchi holati tekshiruvi. `notify_application_admins/result` **faqat commitdan keyin**; `SellerStatus.PENDING` ariza holati emas.
- `payment_service`: `create_method/update_method/move_method/choose_method`,
  `submit_receipt` (hash + dublikat belgisi), `list_payments/count_payments`,
  `decide` (admin qarori + obuna; oldin Seller, keyin Payment qatorini bloklaydi).
  To'lovni yuborish va admin qaroridan keyingi Telegram xabarlari **commitdan keyin**.
- `group_policy_service`: `safe_guard/safe_cleaner`, `edit_guard/edit_cleaner`,
  `classify`, `reserve_action`, `increment_warning`, `grant_permission`,
  `revoke_permission`, `permission_kinds`. `group/policy.py`: `perform_action`,
  `claim_due_actions`, `process_due_cleanup` (scheduler). Dry-run va aktiv jazo
  alohida; API oldidan guruh + global holat qayta tekshiriladi; `running`
  noaniq amal avtomatik takrorlanmaydi.
- `counter_service`: `ensure_counter/edit_counter`, `applicable_channels/add_channel/remove_channel`,
  `reserve_personal_link/finish_personal_link/cancel_personal_link`, `reserve_join/claim_due/credit_join`,
  `adjust/reset_count`. `group/counter.py`: `check_message`, `process_due`, `process_restrictions`.
  Link oldin `pending:` DB'ga yoziladi; join request **kredit emas**, taklif
  bir guruhda bir marta. Hard mute boshqa faol guard/admin cheklovini ochmaydi.

### Klaviatura o'lchamlari (`app/keyboards/common.py`)
`PER_PAGE_GROUPS=6`, `PER_PAGE_CATEGORIES=8`, `PER_PAGE_MATRIX=5`, `PER_PAGE_SELLERS=6`,
`PER_PAGE_TARIFFS=8`, **`PER_PAGE_ADS=6`**, **`PER_PAGE_PHOTOS=8`**.

### Bazadagi muhim faktlar
- `ads.group_id` — denormalizatsiya (toifa guruhidan olinadi); `ad_photos` faqat `file_id` saqlaydi.
- `Ad.position` — navbat tartibi (100 qadam), `post_count`, `last_posted_at`, qo'lda belgilangan `next_eligible_at`.
- `category_rotation`: `cursor_ad_id` (oxirgi joylangan), `next_post_at` (toifa qaytish vaqti), `cycle_count`, `is_paused`.
- `group_rotation`: `next_post_at` (guruh intervali/bandligi), `today_count`, `today_date`, `error_streak`; noma'lum yuborishda pauza.
- `posted_messages`: `message_ids` (JSON) — eski postni o'chirish uchun; `post_log` — `sending`/`ok`/`error`/`skipped`/`uncertain` tarixi.
- `group_settings`: `interval_sec` (default 1800), `jitter_percent` (10), `daily_post_limit` (50), `quiet_start/quiet_end`, `protect_content`, `posting_enabled`, `counter_enabled`, `guard_enabled`, `cleaner_enabled`.
- `group_message_actions`: `(group_id,message_id)` yagona; `pending/running/done/skipped/failed` — noaniq `running` qayta yuborilmaydi. `permissions`dagi guruh/global **aktiv** scope uchun unique indekslar; expired yozuv tarixda qoladi.
- `cleaner_settings.dry_run`: eski yozuvga migratsiyada `false` (avvalgi niyat saqlanadi), yangi policy `true`; eski e'lon tugmasi `dry_run`ni tasdiqsiz o'chirmaydi.
- `counter_settings.dry_run`: eski/yoqilgan yozuvlarda migratsiyadan keyin `true`; `invite_links` faol `(group_id,user_id)` unique; `invite_events`ning `(group_id,invitee_id)` unique yozuvi o'chirilmaydi (abadiy bir-marta sanash). `counter_message_checks` faqat yakunlanganda retentionga kiradi, admin +/- alohida `counter_audit`ga tushadi.
- Sessiya `expire_on_commit=False`, ammo **yangi yaratilgan ORM relationship**ni async rejimda lazy-load qilmang: `session.get()` yoki eager `selectin` bilan oling.

### Global sozlamalar (26 ta, `settings_service.DEFAULTS`)
`kill_switch`, `maintenance_mode`, `support_contact`, `timezone`, 5 ta funksiya kaliti,
`default_interval_sec`, `default_jitter_percent`, `default_daily_post_limit`, `min_interval_sec=60`,
`bot_username`, `subscription_reminder_days=3`, `subscription_grace_days=0`,
`moderation_required_default`, `default_max_photos=3`, `default_max_ads=5`, `receipt_required`,
`receipt_duplicate_check`, `referral_enabled`, `broadcast_enabled_global`, `log_retention_days`, `broadcast_rate_per_sec`,
`warn_first_delay_sec`.

### Matnlar (30 ta, `text_service.DEFAULT_TEXTS`)
`common.*` (10), `start.*` (3), `group.*` (3), `seller.*` (6), `ad.*` (4: submitted/approved/rejected/paused),
`notify.*` (4). Placeholder nomlari **kod bilan aynan bir xil** bo'lishi shart —
`tests/test_text_service.py::test_all_default_texts_have_valid_placeholders` buni ushlaydi
(masalan `ad.submitted` → `{elon}`, `{toifa}`, `{sotuvchi}`).

### Panelda tayyor bo'limlar (`READY_SECTIONS`)
`stats, settings, groups, categories, sellers, tariffs, ads, moderation, payments,
guard, cleaner, counter, permissions, users, referral, texts, errors, broadcast, admins`.
Referal sozlamalari va global switchlar faqat admin/super-admin tomonidan yoqiladi;
adminlarni faqat super-admin boshqaradi. Moderator guruh/toifa va matnlarni ko'ra
oladi, lekin o'zgartira olmaydi; e'lonlarni moderatsiya qila oladi.

---

## 8. Qolgan ishlar

### Phase 0–9, limit/yo‘riqnoma va UX-1/2 kod/oflayn ✅ — bajarildi

Phase 8/9ga alohida ruxsat berilgan; limit/yo‘riqnomadan keyin foydalanuvchi
UX-1/2/3ning barchasiga birgalikda ruxsat berdi. UX-1/2 bajarildi; UX-3
kabineti navbatda. Jonli sinov/deploy bu ruxsat doirasida emas. Testlar yuqoridagi §4–5da. Majburiy kanal
nomi hali berilmagan: admin Phase 7 panelida kiritadi, hech qaysi kanal
avtomatik tanlanmagan.

### Qolgan: Phase 9ning jonli qabul bandlari (hali bajarilmagan)

Haqiqiy PostgreSQL/Redis/Telegram va bank bilan deploy/qabul, ikki worker
poygasi, TLS, real backup/restore drill, rasmiy siyosat/yuridik ko‘rib chiqish
va haqiqiy video yozuvi. Bu sandboxda Docker, `pg_dump`, Redis, Telegram/bank
credentiallari hamda `ffmpeg` yo‘q. [Batafsil ro‘yxat](docs/DEPLOY.md)ni
operator test muhitida bajarsin; bajarildi deb qayd qilmang. **Har yangi
bosqichdan oldin alohida ruxsat** qoidasi o‘z kuchida.

---

## 9. Ochiq bandlar / kechiktirilganlar

| # | Nima | Qachon |
|---|---|---|
| 1 | Haqiqiy bank, Telegram va PostgreSQL/Redis muhitida to'lov/referal/broadcastni amalda sinash; bank o'tkazmasini admin qo'lda tekshiradi | Deploydan oldin |
| 2 | Majburiy obuna kanali nomi/ID hali berilmagan — admin Phase 7 panelida qo'shadi; kanal adminligini real Telegramda tekshirish | Deploy oldidan |
| 3 | Huquqiy/Telegram siyosati eslatmalari yozildi (`docs/DEPLOY.md`); amaldagi rasmiy qoidalar va mahalliy huquqiy talablar mutaxassis tomonidan hali tasdiqlanmagan | Ishga tushirishdan oldin |
| 4 | Phase 6–8 posbon/tozalovchi/sanoqchi, Redis limiter va ko'p workerli broadcastni haqiqiy PostgreSQL + Redis + superguruhda (Privacy Mode o'chirilgan) yuklama bilan sinash | Deploydan oldin |
| 5 | Eski dublikat invite linklar DB'da deaktiv qilinsa ham Telegramda hali ochiq bo'lishi mumkin — deployda qo'lda revoke qilish | Migratsiyadan so'ng |
| 6 | Avvalgi shaxsiy `/start` haqida tarix yo'q: eski user bonusga yaroqsiz va broadcastga avtomatik kirmaydi; broadcast uchun yana shaxsiy `/start` kerak | Deploydan keyin |
| 7 | `stats_daily` migratsiyadan oldingi davrni avtomatik to'ldirmaydi; yangi jamlanma ertasi kuni 00:10da paydo bo'ladi | Deploydan keyin |
| 8 | Real PostgreSQLga backup/restore, interaktiv deploy, Caddy/TLS va video yozuvi test muhitida bajarilmagan | Production qabulidan oldin |

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
Salom! SHOP-BOT loyihasini davom ettiramiz. Avval SHOP_BOT/HOLAT.md, REJA.md,
docs/DEPLOY.md va docs/VIDEO_SENARIY.md fayllarini o'qing: Phase 0–9 kod/oflayn
ishlar, limit/yo‘riqnoma va UX-1/2 tugagan, 384 test o'tgan. UX-2da oddiy
/start ochiq, shaxsiy ariza tasdiqlansa faqat sotuvchi paneli ochiladi;
UX-3 sotuvchi kabineti shu suhbatdagi umumiy ruxsat doirasida navbatda.
Kod `arena/18e1094b-4x40in-bot` shoxobchasida;
main'ga va AVTO_BOT'ga tegmang. Joriy shoxobchani almashtirmang, yangi
shoxobcha yoki PR ochmang. Jonli PostgreSQL/Redis/Telegram/bank, TLS, real
restore drill va video yozuvi bajarilmagan. Qolgan ishni avval o'zbekcha ayting;
resurs/ruxsat bo'lmasa jonli qabul o'tgandek da'vo qilmang. Har yangi bosqich
oldidan alohida ruxsat oling; bosqich yakunida hisobot bering.
```

---

## 12. Xulosa: "keyingi chat uchun yoriqnoma bormi?"

✅ **Bor.** Uch qatlamli:

1. **`SHOP_BOT/HOLAT.md`** (shu fayl) — holat, qolgan ishlar, shartnomalar, ish muhitini tiklash, yangi chat uchun tayyor so'rov.
2. **`SHOP_BOT/REJA.md`** — to'liq texnik reja (funksiya talablari, DB sxemasi, flow'lar, masshtablash, risklar, bosqichlar).
3. **Git tarixi** (`arena/18e1094b-4x40in-bot`) — kod va testlar GitHub'da, har bosqich alohida commit.

Yangi chatda yordamchi shu 3 ta manbani o'qisa, loyihani **aynan qolgan joyidan** davom ettira oladi:
`git status` → `pytest` → qolgan jonli qabul bandlari/cheklovlar hisoboti → keyingi yangi bosqichga alohida ruxsat.
