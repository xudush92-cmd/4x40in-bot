# 4x40IN — Telegram "mijoz topish" boti: to'liq texnik tavsif

> Bu hujjat boshqa AI modellariga (yoki konsultant/mutaxassisga) **nusxalab
> yuborish** uchun tayyorlangan. Ichida kod yo'q, faqat tizim qanday
> ishlayotganining aniq tavsifi, o'lchangan raqamlar va ochiq savollar bor.
> Hujjat oxirida "maslahat so'raladigan savollar" bo'limi turibdi.

---

## 1. Bir qarashda

**Nomi:** 4x40IN (ishchi nomi) — Telegram guruhlarini kuzatuvchi va
mijozlarni topib, xabar egasiga yetkazuvchi tizim.

**Texnologiyalar:** Python 3.11+, `aiogram 3.4.1` (boshqaruv boti),
`telethon 1.34.0` (foydalanuvchi sessiyalari / MTProto), `SQLite` (bitta
fayl), `cryptography` (Fernet), `aiohttp`. Bitta jarayon: `python main.py`
ichida bot ham, barcha foydalanuvchi sessiyalari ham birga ishlaydi.

**Kim uchun:** O'zbekistondagi kichik transport / yuk tashish / yo'lovchi
tashish xizmatlari (haydovchilar va dispetcherlar). Ular Telegram
guruhlarida mijoz e'lonlarini qo'lda qidirib, vaqt yo'qotadi.

**Nima qiladi (bir jumlada):** foydalanuvchi o'z Telegram akkaunti bilan
botga ulanadi, o'zi a'zo bo'lgan guruhlarni qo'shadi, tizim shu guruhlardagi
**yangi** xabarlarni kuzatadi va **mijozga o'xshash** xabarlarni topib,
**faqat o'sha guruh egasiga** Telegram bot xabari ko'rinishida yuboradi.

**Nima qilmaydi:** markaziy "userbot" yo'q, boshqa odamning guruhlarini
kuzatmaydi, topilgan xabarni boshqa foydalanuvchilarga tarqatmaydi, tarixni
(tarixiy xabarlarni) skanerlamaydi, to'lov tizimi yo'q.

---

## 2. Muammo va yechim

**Muammo.** Guruhlarda kuniga yuzlab xabar yoziladi. Ularning ichida ikkita
butunlay boshqa oqim aralashib ketadi:

- **mijoz** — xizmat kerak bo'lgan odam: «menga bugun bitta mashina kerak
  iltimos», «Toshkentdan Samarqandga 2 kishi ketamiz, kim olib ketadi»;
- **haydovchi** — xizmat taklif qiladigan odam: «Toshkent — Xorazm, 2 joy
  bor, tel 90 123 45 67», ko'pincha emoji bilan bezatilgan.

Haydovchi uchun foydali bo'lgani — **mijoz oqimi**. Uni qo'lda ajratish
sekin va charchatadi; bot bu ishni avtomatlashtiradi.

**Yechim.** Har bir foydalanuvchi uchun alohida MTProto sessiya + bitta
umumiy kalit so'zlar ro'yxati + ko'p bosqichli filtr zanjiri + shaxsiy
bildirishnoma.

---

## 3. Asosiy atamalar

| Atamalar | Ma'nosi |
|---|---|
| **Sessiya** | Foydalanuvchining Telegram akkaunti (Telethon `StringSession`), bazada Fernet bilan shifrlangan |
| **Guruh** | `user_groups` jadvalidagi yozuv: egasi + chat_id + holat (`pending`/`ok`/`error`) |
| **Kalit so'z** | `phrases` jadvalidagi bitta so'z. **Bitta umumiy ro'yxat, faqat admin kiritadi** |
| **Xabar sharti** (`match_count`) | Xabarda kamida nechta kalit so'z uchrasa xabar beriladi. Standart = 2, per-user override mumkin |
| **Verdict** | Filtr zanjiri natijasi: o'tdimi, qaysi bosqichda to'xtadi, qaysi kalitlar topildi |
| **Lead** | Filtrdan o'tgan xabar = potensial mijoz |

---

## 4. Arxitektura

```
                 ┌──────────────────────────────────────────┐
   Foydalanuvchi │  aiogram boti (bot.py) — boshqaruv/UI     │
   Telegram ────►│  ro'yxatdan o'tish · menyu · test · admin │
                 └───────────────┬──────────────────────────┘
                                 │ SQLite (scanner.db)
                 ┌───────────────▼──────────────────────────┐
                 │  scanner_manager.py                       │
                 │  har foydalanuvchi uchun 1 ta Telethon     │
                 │  client (NewMessage handler)              │
                 │  + 60 soniyalik sync loop                 │
                 └───────────────┬──────────────────────────┘
                                 │ har bir xabar
                 ┌───────────────▼──────────────────────────┐
                 │  filters.evaluate() — 6 bosqichli zanjir  │
                 │  └ matcher.match_keywords()               │
                 └───────────────┬──────────────────────────┘
                                 │ o'tdi
                 ┌───────────────▼──────────────────────────┐
                 │  notifier.py → Bot API sendMessage        │
                 │  faqat guruh EGASIGA                      │
                 └──────────────────────────────────────────┘
```

**Muhim printsip:** skanerning **real** ishlashi va botdagi **🧪 Skaner
testi** tugmasi **aynan bitta funksiyani** (`filters.evaluate`) chaqiradi.
Shuning uchun "test o'tdi, lekin xabar kelmadi" degan holat faqat sessiya
yoki guruh ulanishi bilan bog'liq bo'lishi mumkin — filtr bilan emas.

**Fayllar:**

| Fayl | Vazifasi |
|---|---|
| `main.py` | Bot + sessiya managerini birga ko'taradi; sozlamalarni oldindan tekshiradi |
| `bot.py` | Barcha UI: menyular, registratsiya, admin panel, guruhlar, test, statistika (~2800 qator) |
| `scanner_manager.py` | Telethon clientlari, event handler, sync loop, diagnostika (~560 qator) |
| `filters.py` | 6 bosqichli filtr zanjiri — yagona qaror nuqtasi |
| `matcher.py` | Kalit so'z moslashtirish algoritmi (normalizatsiya, transliteratsiya, indeks) |
| `notifier.py` | Bildirishnoma matni, telefon ajratish, Bot API orqali yuborish |
| `database.py` | SQLite sxemasi va barcha so'rovlar |
| `login_manager.py` | Akkaunt ulash (kod, 2FA, FloodWait limitlari) |
| `session_crypto.py` | Fernet shifrlash/ochish |
| `reset_db.py` | Bazani nolga tushirish vositasi (statistika + zaxira bilan) |
| `test_matcher.py` | Matcher uchun 39 ta test |

---

## 5. Foydalanuvchi yo'li

### 5.1 Ro'yxatdan o'tish va akkaunt ulash (QR siz)

1. `/start` → menyu. Admin bo'lmasa — tarif holati ko'rsatiladi.
2. **📱 Akkaunt holati → 🔑 Akkauntni ulash**:
   ism-familiya → telefon `+998...` → Telegram kodi **darhol** so'raladi va
   faqat **raqamli inline tugmalar** bilan teriladi (matn ko'rinishidagi kod
   o'chiriladi — bu xavfsizlik uchun) → 2FA parol (agar yoqilgan bo'lsa).
3. Sessiya **`pending`** holatda shifrlab saqlanadi, adminga ariza boradi
   (✅ Tasdiqlash / ❌ Rad etish). Tasdiqlanganda sessiya qayta tekshirilib
   `active` bo'ladi; rad etilsa revoke qilinadi.
4. Tekshiruv: sessiya Telegram UID == bot UID. Boshqa odamning sessiyasi
   qabul qilinmaydi.
5. Limitlar: bitta telefon raqami uchun **3 ta kod/soat**, noto'g'ri kod
   5 martadan keyin to'xtatish, `FloodWaitError` hurmat qilinadi.

### 5.2 Guruh qo'shish

- **➕ Guruh qo'shish** → avval **akkauntdagi guruhlar ro'yxati** chiqadi
  (`gadd:<chat_id>`, allaqachon qo'shilganlari ✅ bilan) + pastida
  **✍️ Qo'lda kiritish** (`@username`, `t.me/...`, `-100...`).
- Sessiya oflayn bo'lsa — faqat qo'lda kiritish. Akkauntda guruh bo'lmasa —
  «📭 a'zo emas» xabari.
- Yozuv `status='pending'` bilan saqlanadi. Sync loop har 60 soniyada
  `get_dialogs()` orqali tekshiradi: topilsa `status='ok'`, `chat_id`
  to'ldiriladi va egasiga «✅ Guruh ulandi» xabari boradi; topilmasa
  `status='error'` + aniq sabab («akkauntingiz bu guruhda a'zo emas yoki ID
  noto'g'ri», «bu guruh emas (kanal yoki foydalanuvchi)», «yopiq taklif
  havolasini tekshirib bo'lmaydi»).
- Faqat **guruh** va **superguruh** qabul qilinadi; kanal va shaxsiy chat
  rad etiladi.
- Limit: bir foydalanuvchiga **100 ta guruh**.
- Guruhni o'chirish = ro'yxatdan chiqarish (akkauntdan chiqmaydi).

### 5.3 Kalit so'zlar (faqat admin)

- Bitta umumiy ro'yxat (`phrases`). **Har bir qator — bitta so'z.**
- Bitta xabarda bir nechta so'z yuborilsa, hammasi ajratilib qo'shiladi
  (probel, vergul, yangi qator).
- Takror tekshiruvi **kanonik**: katta/kichik harf, ortiqcha bo'shliq,
  tinish belgilari, lotin/kirill farqi, "dangasa" kirill (ў→у, қ→к, ғ→г,
  ҳ→х) hisobga olinmaydi. `ТОШКЕНТ` = `toshkent`.
- Rad etiladi: 3 harfdan qisqa so'z (istisno: `uk`), ma'lum xato shakl
  (`mang'ud` → to'g'risi `mang'it`), **qo'shimchali shakl** (`toshkentga` —
  chunki `toshkent` o'zagi bor; qoida: o'zak + 1..5 harf qo'shimcha).
- Ro'yxatga **har doim lotin shaklida** yoziladi; kirill kiritilsa
  avtomatik lotinga o'giriladi.
- Ro'yxat 20 tadan sahifalanadi (◀️ ▶️), har so'z yonida 🗑 tugmasi bor va
  **o'chirilgandan keyin ro'yxat yopilmaydi** (o'sha xabar yangilanadi).

### 5.4 Xabar sharti

- Admin standart qiymatni belgilaydi (standart **2**).
- Har foydalanuvchi **🔔 Xabar sharti** orqali o'z chegara o'ziga
  belgilashi mumkin (`own_match_count`); 0 = "admin standartini ishlat".
- Bu yagona per-user sozlama. Kalitlarning o'zi per-user emas.

### 5.5 🧪 Skaner testi

Foydalanuvchi namuna matn yuboradi, bot `filters.evaluate` ni ishga
tushirib, **bosqichma-bosqich** hisobot beradi:
Tizim → Tarif → Skaner holati → Guruh → Emoji → Kalitlar.
Har bir bosqich ✅ o'tdi / ❌ to'xtadi / ⏭ tekshirilmadi deb ko'rsatiladi.
Bundan tashqari **sessiya diagnostikasi**: client tirikmi, nechta guruh
kuzatilmoqda, nechta guruh xabari ko'rilgan, oxirgi xabar qachon/qaysi
chatdan kelgan, oxirgi start xatosi.

---

## 6. Skanerlash yadrosi — batafsil

### 6.1 Xabar qanday ushlanadi

Har bir faol foydalanuvchi uchun bitta `TelegramClient` yaratiladi va unga
`events.NewMessage` handleri ulanadi. Har bir kelgan xabar uchun:

1. Diagnostika hisoblagichlari yangilanadi (`_seen_events`, `_last_event`).
2. **Shaxsiy chat** (`is_private`) — darhol `return` (skanerlanmaydi).
3. `chat_id is None` yoki `chat_id > 0` — `return` (bu PeerUser).
4. Matn ham, stiker ham bo'lmasa — `return`.
5. `filters.evaluate()` — yagona qaror nuqtasi.
6. O'tsa → `notifier` bilan **faqat egasiga** yuboriladi, hisoblagichlar
   oshiriladi (`leads_found`, `notifications_sent`), `last_found_at`
   yangilanadi.

Loglar: har bir guruh xabari uchun `[SCAN] event owner=... chat=...`,
yuborilganda `[SCAN] sent ...`, xato bo'lsa `[SCAN] SEND FAILED ...`.
Shu loglar orqali "xabar umuman kelmadimi yoki filtrda to'xtadimi"ni
ajratish mumkin.

### 6.2 Sync loop (60 soniya)

Har 60 soniyada:

1. Bazadagi barcha foydalanuvchilar bo'yicha **kerakli** clientlar
   to'plami hisoblanadi: sessiya bor + `awaiting_approval=0` + bloklanmagan
   + (admin bo'lmasa) tarif faol.
2. Kerakli, lekin hali ko'tarilmagan sessiyalar ko'tariladi.
3. Keraksiz bo'lib qolganlar uziladi.
4. Har bir client uchun: uzilgan bo'lsa qayta `connect()`; bo'lmasa
   `session_status='error'` va egasiga ogohlantirish.
5. Har bir onlayn client uchun `pending` guruhlar qayta tekshiriladi.

Sessiya ogohlantirishlari **6 soatda bir martadan** ko'p bo'lmasligi
uchun cooldown bor (spam bo'lmasin).

### 6.3 Sessiya holatlari

| Holat | Ma'nosi | Nima qilinadi |
|---|---|---|
| `none` | Sessiya yo'q | Login taklif qilinadi |
| `pending` | Arizada, admin tasdig'i kutilmoqda | Client ko'tarilmaydi |
| `active` | Ishlayapti | Event handler faol |
| `error` | Tarmoq/Telegram uzilishi | Sync loop qayta urinadi |
| `invalid` | Sessiya bekor qilingan / shifr ochilmadi / UID mos emas | Client to'xtatiladi, egasiga «qayta login qiling» |

Agar `SESSION_ENCRYPTION_KEY` o'zgarsa, barcha saqlangan sessiyalar
ochilmay qoladi → `invalid` + «qayta login kerak». Bu ataylab shunday:
noto'g'ri kalit bilan "yarim ishlaydigan" holat bo'lmasin.

### 6.4 Guruh tekshirish mantiqi

`get_dialogs()` bir marta chaqirilib, `chat_id` → entity va
`username` → entity xaritalari quriladi. Raqamli ID yuborilganda 3 ta
nomzod sinaladi (to'g'ridan-to'g'ri, `-100<id>`, `-id`) — chunki
foydalanuvchilar ID ni turli shaklda yozadi. Xato holatlar har 60 soniyada
qayta tekshiriladi, lekin xabar faqat **birinchi** urinishda yuboriladi.

### 6.5 Filtr zanjiri (6 bosqich)

Tartib qat'iy, birinchi to'xtagan bosqich sabab bo'ladi:

| # | Bosqich | Tekshiruv | To'xtasa |
|---|---|---|---|
| 1 | **Tizim** | `settings.is_active == '1'` (adminning global Stop/Start) | «tizim admin tomonidan ⏸ to'xtatilgan» |
| 2 | **Tarif** | bloklangan emas + `sub_expires_at` kelajakda (admin uchun talab qilinmaydi) | «bloklangan» / «tarif berilmagan» / «muddat tugagan» |
| 3 | **Skaner** | foydalanuvchining umumiy `scanner_enabled` (bitta tugma hamma guruhiga ta'sir qiladi) | «🔴 to'xtatilgan — ▶️ Start ni bosing» |
| 4 | **Guruh** | `chat_id` shu foydalanuvchining **faol** guruhlar ro'yxatida | «bu guruh sizning faol guruhlaringiz ro'yxatida yo'q» |
| 5 | **Emoji/stiker** | `contains_emoji(text)` yoki stiker | «emoji bor — haydovchi belgisi» |
| 6 | **Kalitlar** | `match_keywords(text, keywords, required)` → `matched_count >= required` | «N ta kalit, shart — M ta» |

Test rejimida 4-bosqich `INFO` bo'ladi (aniq guruh noma'lum), lekin
**umuman faol guruh yo'q bo'lsa** — baribir to'xtaydi, chunki bunda hech
qanday xabar kelmaydi.

### 6.6 Diagnostika tamoyili

"Xabar kelmayapti" shikoyatida 3 holat ajratiladi:

1. **Sessiya guruh xabarlarini umuman ko'rmayapti** (`events == 0`) →
   muammo Telegram/akkaunt tomonda (bildirishnomalar o'chirilgan, akkaunt
   cheklangan, xabar boshqa akkauntdan yozilgan). Filtr aybdor emas.
2. **Ko'ryapti, lekin chat_id ro'yxatda yo'q** → guruh boshqa akkauntga
   ulangan yoki ID mos emas.
3. **Ko'ryapti va ro'yxatda bor** → sabab filtr bosqichlarida (test
   aynan shuni ko'rsatadi).

Bu printsip amalda juda muhim bo'ldi: foydalanuvchilar aksariyat holatda
"bot buzuq" deydi, aslida esa sessiya yuklanmagan yoki guruh boshqa
akkauntda bo'lgan.

---

## 7. Matcher — kalit so'z moslashtirish algoritmi

Model: **har bir kalit so'z alohida**, ularning soni cheklanmagan
(o'lchov: 5000 kalitda bitta xabar ≈ 2 ms). Admin faqat "nechta kalit
topilsa xabar ber" sonini belgilaydi. Foiz, to'plam, ibora yo'q
(ibora qo'llab-quvvatlanadi, lekin hozir bitta so'zli kalitlar ishlatiladi).

### 7.1 Normalizatsiya

- Kichik harf; apostroflar birlashtiriladi (`’ ‘ ʻ ʼ \`` → `'`).
- Tokenizatsiya: harflar + ichki apostrof (`[^\W_]+(?:['’ʻʼ][^\W_]+)*`),
  ya'ni `jo'nat` bitta token, `jo'nat.` ham bitta token.
- Tinish belgilari, ortiqcha bo'shliq, emoji — token chegarasi.
- So'z tartibi va oradagi so'zlar ahamiyatsiz.

### 7.2 Lotin ↔ kirill

Har bir so'z solishtirishda **variantlarga** aylantiriladi:

- asl shakl;
- kirill bo'lsa — lotinga o'girilgan shakl (to'liq jadval: `ў→o'`,
  `қ→q`, `ғ→g'`, `ҳ→h`, `ж→j`, `ч→ch`, `ш→sh` ...);
- "dangasa lotin": `o'→u`, `q→k`, `h→x`, `g'→g`;
- apostrofsiz variant: `o'→o`.

Natijada bitta lotin kalit `қарши` = `карши` = `qarshi` = `karshi` kabi
barcha yozuvlarni topadi. Kirill so'zni ro'yxatga kiritish shart emas.

### 7.3 Shakl (qo'shimcha) tahlili

`_verb_parts()` so'zni **o'zak + shaxs + zamon** ga ajratadi:

- shaxs: 1-shaxs (`-man`, `-miz`, `-aman`, `-amiz`, `-yapman`...) va
  2-shaxs (`-siz`, `-san`, `-asiz`, `-yapsiz`...) — **bir-biriga
  tenglashtirilmaydi**, chunki «jo'natamiz» (biz yuboramiz = haydovchi)
  va «jo'natasizmi?» (siz yuborasizmi = mijoz) har xil ma'no;
- zamon: `moqchi` / `yap` / `oddiy` — ham ajratiladi.

Moslik qoidalari (`_word_matches_single`), tartib bilan:

| Qoida | Shart | Misol |
|---|---|---|
| Aniq tenglik | `key == message` | `kerak` = `kerak` |
| Fe'l o'zagi | shaxs teng **va** o'zak aynan teng **va** zamon teng | `kerakmiz` ~ `kerakman` |
| Kalit — o'zak | xabar so'zi kalit bilan boshlanadi | `kerak` ~ `kerakmi`, `odam` ~ `odamlar` |
| Kalit uzunroq, dumi 1–2 harf | kalit xabar so'zi bilan boshlanadi | `ketadi` ~ `ketad` |
| Uzun umumiy o'zak | prefiks ≥ 5 harf **va** ≥ 75% qisqa so'zning uzunligi | `toshkent` ~ `toshkentdan` |
| Kichik xato | ikkalasi ≥ 5 harf, `SequenceMatcher.ratio() ≥ 0.85` | `toshkent` ~ `toshket` |

`strict_question` rejimi bor (stop-so'zlar uchun): `бор` va `борми`
tenglashtirilmaydi. Hozir asosiy zanjirda ishlatilmaydi.

### 7.4 Tezlik uchun prefiks indeksi

Kalitlar ro'yxati bo'yicha `exact: variant → id[]` va
`prefix: variant[:3..n] → {id}` indekslari quriladi (`lru_cache`,
32 ro'yxatgacha). Xabar so'zi uchun nomzodlar O(1) topiladi, keyin
to'liq moslik tekshiriladi. Ro'yxat yuzlab/minglab so'z bo'lsa ham
xabar narxi deyarli o'zgarmaydi.

### 7.5 MatchResult

```text
required_count : admin/per-user belgilagan chegara
matched_words  : xabarda topilgan kalitlar (ro'yxat tartibida)
total_words    : bazadagi kalitlar soni
is_match       : matched_count >= required_count >= 1
```

---

## 8. Emoji filtri — "haydovchi detektori"

G'oya: **haydovchi e'lonlari deyarli doim emoji bilan bezatiladi**
(🚕 📞 ✅ 📦 ➡️), **mijoz xabarlarida esa emoji bo'lmaydi**.
Shu sababli haydovchi e'lonlarini bloklash uchun alohida so'zlar ro'yxati
kerak emas — bitta regex yetadi:

```text
[\U0001F000-\U0001FAFF \u2600-\u27BF \u2B00-\u2BFF \uFE0F \u20E3]
```

Ya'ni: emoji yoki emoji-variation-selector topilsa — xabar **bloklanadi**
(haydovchi deb hisoblanadi). Stiker ham xuddi shunday.

Bu yechim **arzon va tez**, lekin **qo'pol** (quyida 14-bo'limga qarang).

---

## 9. Bildirishnoma

O'tgan xabar uchun egasiga HTML formatda kartochka boradi:

- guruh nomi;
- yuboruvchi (ismi, `tg://user?id=` havolasi, username);
- Telegram ID (nusxalash uchun `<code>`);
- **telefon** — regex `(\+?998|8)?[\s\-]?\(?\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}` ;
  matnda topilmasa profildan (agar ochiq bo'lsa) `+998... (Profil raqami)`;
  bo'lmasa «Matnda ko'rsatilmagan»;
- xabar matni (HTML-escape qilingan);
- **topilgan kalitlar** va **shart** («kamida N ta — bajarildi»);
- inline tugmalar: **✍️ Mijozga yozish (Lichka)** (`tg://user?id=`) va
  **↗️ Guruhdagi asl xabarni ochish** (`https://t.me/username/id`,
  superguruh uchun `https://t.me/c/<id>/<msg>`; yopiq oddiy guruhda
  havola berilmaydi).

Yuborish Bot API orqali (`aiohttp`). Xato bo'lsa (HTML yoki tugma
muammosi) — **HTMLsiz, tugmasiz oddiy matn** bilan qayta yuboriladi, shunda
bildirishnoma yo'qolmaydi. Har bir yuborish `[NOTIFY]` / `[SCAN] sent`
logida qayd etiladi.

---

## 10. Ma'lumotlar bazasi (SQLite, bitta fayl)

| Jadval | Ustunlar (asosiylari) | Izoh |
|---|---|---|
| `phrases` | `id`, `text UNIQUE` | Kalit so'zlar (jadval nomi tarixiy) |
| `settings` | `key`, `value` | `is_active`, `match_count`, `userbot_last_seen`, hisoblagichlar |
| `users` | `user_id`, `first_name`, `username`, `is_blocked`, `sub_expires_at`, `full_name`, `phone`, `session_enc`, `pending_session_enc`, `awaiting_approval`, `session_status`, `last_warn_date`, `last_found_at`, `scanner_enabled`, `own_match_count` | Har foydalanuvchi kartochkasi |
| `user_groups` | `id`, `owner_user_id`, `input_value`, `chat_id`, `title`, `is_active`, `status`, `last_error`, `UNIQUE(owner, input_value)` | Guruhlar, egasi bilan |
| `user_counters` | `user_id`, `key`, `value` | `leads_found` va boshqa shaxsiy sonlar |

Eski modeldan qolgan `groups` jadvali avtomatik `DROP` qilinadi.
Ko'p so'zli eski yozuvlar avtomatik alohida kalitlarga bo'linadi.

---

## 11. Izolyatsiya va xavfsizlik

- **Ma'lumot aralashmaydi:** har bir guruh `owner_user_id` bilan bog'langan;
  `get_owner_active_chat_ids(uid)` faqat shu egasining chat_id larini
  qaytaradi; bildirishnoma `chat_id=owner_id` bilan yuboriladi — boshqa
  foydalanuvchiga ketish yo'li kodda yo'q.
- Sessiyalar Fernet bilan shifrlangan (`SESSION_ENCRYPTION_KEY`), baza
  fayli `gitignore`da.
- Parol/kod chatda saqlanmaydi; kod faqat inline tugmalar bilan teriladi.
- Admin sessiyasi ham alohida (admin o'z akkaunti bilan skanerlaydi, tarif
  talab qilinmaydi) — bu xatolarni o'z ko'zi bilan ko'rish uchun.
- Foydalanuvchi menyusida boshqa userlar, arizalar, broadcast, admin
  tugmalari, tarif yozish yo'q.
- Markaziy userbot **ataylab** olib tashlangan (bitta akkaunt barcha
  guruhlarni kuzatib, barcha oluvchilarga tarqatadigan model) — u
  foydalanuvchilar ma'lumotini aralashtirardi.

---

## 12. Nimalarni skanerlash kerak — domen modeli

**Skanerlash obyekti:** foydalanuvchi qo'shgan guruhlardagi **yangi,
jonli** matnli xabarlar (tarix skanerlanmaydi).

**Maqsad — mijoz xabarini topish.** Mijoz xabarining belgilari:

- xizmat **kerakligi** haqida gapiradi: `kerak`, `kerek`, `izlayapman`,
  `qidiraman`, `kim bor?`, `qancha?`, `necha pul?`;
- yuborishni so'raydi: `jo'natib bering`, `yuboring`, `olib ketadimi?`;
- odatda **qisqa**, imlo xatolari bilan, ko'pincha **emojisiz**;
- ko'pincha telefon raqami bor (lekin haydovchida ham bo'ladi).

**Haydovchi e'lonining belgilari:**

- taklif: `bor`, `bo'sh`, `xizmat`, `tashaymiz`, `olamiz`, `jo'natamiz`,
  `narx`, `kelishiladi`;
- marshrut va joy soni: `Toshkent — Xorazm`, `2 joy`, `pachka`, `posilka`;
- deyarli doim **emoji**, ba'zan rasm bilan, tez-tez takrorlanadi.

Muhim: **bir xil so'z ikkala tomonda ham uchrashi mumkin** (`yuk`, `joy`,
`mashina`, `tel`, `bugun`, `ertaga`, `posilka`, `xotin`, `kishi`,
`yo'lovchi`) — shuning uchun "joy nomi + umumiy so'z" strategiyasi
ishlamaydi. Bu o'lchov bilan tasdiqlangan (13-bo'lim).

---

## 13. O'lchangan natijalar (haqiqiy matcher bilan)

Korpus: **27 mijoz** xabari, **24 haydovchi** e'loni, **11 aloqasiz**
(tabrik, savdo, umumiy suhbat) xabar. Metrika: mijoz qancha topildi
(to'liqroq = yaxshi), haydovchi qancha o'tib ketdi (kamroq = yaxshi),
aloqasiz qancha o'tdi (kamroq = yaxshi).

### 13.1 Hozirda botga kiritilgan 75 so'zli ro'yxat

| Shart | Mijoz | Haydovchi o'tdi | Aloqasiz o'tdi |
|---|---|---|---|
| **1** | 25/27 | **23/24 (96%)** | 8/11 |
| 2 | 22/27 | 18/24 | 2/11 |
| 3 | 20/27 | 9/24 | 0/11 |

**Xulosa: bu ro'yxat amaliy jihatdan ishlamaydi.** 75 so'zning 42 tasi
matcherning o'zak/prefix mantiqi tufayli **ortiqcha** (ularsiz ham
topiladi): `kisi, xat, nassa, passajir, karakm, garakm, gerek,
jullamoqchi, jibermoqchi, jullayman, jiberaman, izlayapd, izlayapt,
izleyapti, izlayapman, izlayapmiz, qidiryapti, oxtorb, oxtarb, olip,
getad, kutilmoqda, kelishdik, jo'natish, yubormoqchi, ating, qling, qara,
ikk, ekki, ush, bes, bash, alti, sakkz, sakkis, hozir, hozr, erdaga,
artang, telefon, ayl` va h.k.

Ikkala tomonda ham uchraydigan (kalit bo'la olmaydigan) 14 so'z:
`bugun, ertaga, joy, kish, kishi, mashina, pachka, posilka, tel, xotin,
yo'lovchi, yolovchi, yuk` (yagona istisno — `kerak`, u mijoz belgisi).

### 13.2 Tavsiya etilgan 12 so'z (shart = 1)

```text
kerak kerek izl qidir jo'nat jonat jull jiber yubor qancha necha ketadi
```

| Ro'yxat | Shart | Mijoz | Haydovchi o'tdi | Aloqasiz o'tdi |
|---|---|---|---|---|
| 9 so'z (kerak kerek izl qidir jo'nat jonat jull jiber yubor) | 1 | 22/27 | 1/24 | 1/11 |
| + `qancha necha` (11) | 1 | 25/27 | 1/24 | 1/11 |
| **+ `ketadi` (12)** | **1** | **26/27** | **1/24** | 1/11 |

Qolgan yagona xato — `yuk bor kishi kerak bolsa qo'ng'iroq qiling`
(haydovchi e'loni, lekin ichida `kerak` bor). 24 tadan 1 tasi — qabul
qilingan.

`qanday` qo'shilsa mijoz 25/25 bo'ladi, lekin aloqasiz xato 2/11 ga
chiqadi — shuning uchun birlashtirilgan korpusda tavsiya etilmadi.

Diqqat: `bormi` kalit qilib bo'lmaydi — u «joy **bor**» degan haydovchi
matniga ham mos tushadi (12 haydovchi e'lonidan 9 tasi o'tib ketdi).

### 13.3 Amaliy saboqlar

1. **Ko'p so'z = yomon natija**, chunki har bir qo'shimcha so'z
   haydovchi e'lonida ham uchraydi.
2. **Shart = 1** bu domenda yaxshi: mijoz xabarida odatda bitta kuchli
   belgi bo'ladi (ko'pincha `kerak`). Shart = 2 qilinsa mijozning ~76%
   yo'qoladi.
3. **O'zak yozish** yetarli: `izlayapman`, `qidiryapti`, `jo'natmoqchiman`
   kabi shakllar o'zaklar orqali avtomatik topiladi.
4. **Joy nomlari (shahar/tuman) foydasiz** — ikkala tomon ham yozadi;
   foydalanuvchi ham shuni aytgan («joy nomlari kerak emas»).

---

## 14. Hozirgi cheklovlar va ochiq muammolar

Bular — boshqa AI modelidan fikr so'rash uchun asosiy ro'yxat.

### A. Tasniflash sifati
1. **Emoji filtri qo'pol.** Mijoz emoji ishlatsa (yoki telefon raqamini ✅
   bilan bezasa) — xabar butunlay yo'qoladi. Haydovchi emoji ishlatmasa —
   o'tib ketadi. Bu **bitta belgi**ga asoslangan qaror.
2. **Kalit so'z yondashuvi "so'z bor/yo'q" darajasida.** Sinonim, kontekst,
   inkor (`kerak emas`, `kerak bo'lsa`), savol shakli (`bormi?`) hisobga
   olinmaydi.
3. **Bitta noto'g'ri so'z butun qarorni buzadi** (`yuk bor kishi kerak
   bo'lsa` — haydovchi, lekin `kerak` bor).
4. **Korpus kichik** (27/24/11) va qo'lda tuzilgan — haqiqiy oqimdagi
   xilma-xillikni qoplamaydi. O'zbek lotin/kirill aralashmasi, imlo
   xatolari, translit, qisqartmalar ko'p.
5. **Per-user "sifat vs to'liqlik" sozlamasi yo'q** — faqat shart soni bor.

### B. Skanerlash qamrovi
6. **Faqat matnli xabarlar.** Rasm/video + izoh (caption), ovozli xabar,
   reply ichidagi matn, forward qilingan xabar matni alohida ishlanmaydi
   (matn bo'lmasa `return`).
7. **Tahrirlangan xabar** (`MessageEdited`) kuzatilmaydi — haydovchi
   e'lonni tahrirlab mijozga aylantirsa yoki aksincha, ko'rilmaydi.
8. **Guruh ichidagi mavzular (forum topics)**, comment-thread'lar
   (`linked chat`) alohida ishlanmagan.
9. **Tarixiy xabarlar** skanerlanmaydi (ataylab — faqat jonli oqim), lekin
   yangi guruh qo'shilganda o'tgan 1 soatdagi xabarlar ham ko'rilmaydi.
10. **Bitta jarayon** — barcha sessiyalar bitta `asyncio` loopda. 100+
    foydalanuvchi × 100 guruh = 10 000 chat, bitta SQLite fayli va bitta
    Telegram ulanish limitlari (flood, `get_dialogs`) muammo bo'lishi
    mumkin.
11. **`get_dialogs(limit=None)`** guruh tekshirishda har bir foydalanuvchi
    uchun og'ir so'rov; ko'p a'zoli akkauntlarda sekin/flood xavfi.

### C. Ishonchlilik
12. Telethon `NewMessage` sessiya darajasida ishlaydi — akkaunt telefonda
    "o'chirilgan"/cheklangan bo'lsa xabar kelmaydi (diagnostika buni
    ko'rsatadi, lekin oldini olmaydi).
13. `SESSION_ENCRYPTION_KEY` yo'qolsa — hamma qayta login qilishi kerak.
14. Qayta ishga tushirishda `_seen_events` kabi diagnostika hisoblagichlari
    nolga tushadi (xotirada).
15. SQLite + bir nechta yozuvchilik (bot + scanner) uchun WAL yoqilmagan.

### D. Huquqiy / siyosiy
16. Foydalanuvchi akkaunti (MTProto) bilan guruhlarni o'qish Telegram
    foydalanish shartlariga mos kelishi kerak; akkaunt ban xavfi bor.
    Hozir hech qanday tezlik cheklovi/insoniy pauza siyosati yo'q.
17. Boshqa odamlarning shaxsiy ma'lumotlari (telefon, ism, ID) bot orqali
    uzatiladi — rozilik va saqlash muddati masalasi ochiq.

### E. Mahsulot
18. Bildirishnoma "xom" — guruhlash, deduplikatsiya (bir mijoz 3 guruhga
    bir xil yozsa 3 ta xabar), prioritetlash, ovozli ogohlantirish yo'q.
19. Mijozning "sifati" baholanmaydi (marshrut mosligi, narx, telefon bormi).
20. Foydalanuvchi o'z guruhlarini qo'shishi kerak — yangi mijoz uchun
    "qaysi guruhlarni qo'shishim kerak" degan yo'l-yo'riq yo'q.

---

## 15. Boshqa AI modelidan so'raladigan savollar

Quyidagi savollarni **aynan shu tartibda** berish tavsiya etiladi.

### Tasniflash yadrosi
1. Emoji-asosidagi "haydovchi detektori" o'rniga **ko'p belgili skoring**
   (kalit so'z vazni + `kerak/bor` nisbati + savol shakli + emoji + telefon
   + xabar uzunligi + joy soni) qurish mantiqan to'g'rimi? Qanday formula
   va qanday chegaralar?
2. Kichik korpus (50–500 xabar) bilan **logistik regressiya / Naive Bayes
   / gradient boosting** o'qitish realmi? Xususiyatlar (feature) qanday
   bo'lishi kerak? O'zbek tili uchun tokenizatsiya muammosi qanday hal
   qilinadi (agglutinativ til, lotin+kirill)?
3. **Embedding / semantik qidiruv** (masalan, ko'p tilli model) o'zbek
   tilidagi qisqa, imlo xatoli xabarlar uchun amaliymi? Resurs narxi
   qancha? Gibrid (kalit so'z + embedding) yondashuv kerakmi?
4. Kalit so'zlar ro'yxatini **avtomatik** yaxshilash mumkinmi —
   foydalanuvchi "bu haydovchi edi / bu mijoz edi" bosganda ro'yxat va
   vaznlarni o'zi o'rgatadigan qilib (online learning / feedback loop)?
5. `kerak` kabi so'zlar inkor bilan kelishi (`kerak emas`, `kerak emas
   hozir`) — inkor/shart maydonini qanday arzon aniqlash mumkin?

### Filtrlash ketma-ketligi
6. Emoji filtri qaysi holatda **butunlay** olib tashlanishi kerak? Uning
   o'rniga nima qo'yish to'g'ri: og'irlik (ball) sifatidami yoki alohida
   bosqich sifatidami?
7. Zanjirdagi tartib to'g'rimi (tizim → tarif → skaner → guruh → emoji →
   kalit)? Guruh tekshiruvini kalitlardan oldin qo'yish samaralimi?
8. `matched_count >= required` o'rniga **vaznli ball** (`kerak` = 3,
   `qancha` = 2, `yuk` = 0.5) va chegara qo'yish yaxshiroqmi? Qanday
   kalibrlash mumkin?

### Skanerlash qamrovi
9. Rasm-caption, ovozli xabar (transkript), tahrirlangan xabar, reply va
   forward matnlarini qamrab olishning **eng arzon** yo'li qanday?
10. 100+ foydalanuvchi × 100 guruh shkalasida Telethon'ning bitta jarayonli
    modeli yetadimi, yoki worker/process bo'linishi kerakmi? Telegram
    flood limitlariga qanday sig'ish kerak?
11. Yangi guruh qo'shilganda **oxirgi N xabar**ni bir martalik skanerlash
    (backfill) kerakmi yoki bu foydalanuvchini charchatadimi? Qanday
    cheklash kerak?

### Ishonchlilik va xavfsizlik
12. Sessiya uzilishini (`invalid`) oldindan aniqlash va egasiga aniq
    yo'l-yo'riq berish uchun yana qanday signallar bor?
13. Ko'p foydalanuvchili izolyatsiyani **test bilan kafolatlash** uchun
    qanday avtomatik testlar yozish kerak (bir foydalanuvchi xabari
    boshqasiga hech qachon ketmasligi)?
14. MTProto bilan guruhlarni o'qishda huquqiy/ToS xavfini kamaytirish
    bo'yicha amaliy tavsiyalar (tezlik, akkaunt yoshi, 2FA, faqat o'zi
    a'zo guruhlar)?

### Mahsulot
15. Bildirishnomalarni **deduplikatsiya** qilish (bir xil matn bir necha
    guruhda) va **prioritetlash** (telefon bor, marshrut mos) qanday
    quriladi?
16. Foydalanuvchiga "bugun 12 mijoz topildi, 3 tasi mos" degan **kunlik
    hisobot** foydalimi? Qanday metrikalar kerak (precision/recall
    o'rniga biznes metrikasi)?

---

## 16. Texnik faktlar jadvali (qisqa ma'lumotnoma)

| Parametr | Qiymat |
|---|---|
| Til / runtime | Python 3.11+, bitta `asyncio` jarayon |
| Bot | aiogram 3.4.1 (long polling) |
| Sessiya | Telethon 1.34.0, `StringSession`, Fernet-shifrlangan |
| Baza | SQLite, bitta fayl `scanner.db` |
| Sync loop | har **60 soniya** |
| Guruh limiti | **100** / foydalanuvchi |
| Xabar sharti standart | **2** (tavsiya: 1 — yuqoridagi ro'yxat uchun) |
| Kalitlar soni | cheklanmagan (5000 kalitda ≈ 2 ms/xabar) |
| Ro'yxat sahifasi | 20 ta so'z |
| Emoji qoidasi | emoji yoki stiker bor → blok |
| Bildirishnoma | faqat guruh egasiga, HTML + inline tugmalar |
| Telefon regex | `+998` / 8 / 9 xonali formatlar |
| Sessiya ogohlantirish | 6 soatda 1 marta |
| Tarif ogohlantirish | tugashga ≤3 kun, kuniga 1 marta |
| Login limiti | 3 kod/soat/telefon, 5 noto'g'ri kod |
| Matcher testlari | 39 ta (hammasi o'tadi) |

---

## 17. Ilova — test xabarlari (skaner testi uchun namunalar)

**O'tishi kerak (mijoz):**

- `menga bugun bitta mashina kerak iltimos`
- `Toshkentdan Samarqandga 2 kishi ketamiz kim olib ketadi`
- `posilka yubormoqchiman qancha turadi`
- `yukim bor Buxoroga jo'natmoqchiman kim bor`
- `qizimni Urganchga olib boradigan odam bormi`

**O'tmasligi kerak (haydovchi):**

- `🚕 Toshkent — Xorazm 2 joy bor tel 90 123 45 67`
- `✅ Yuk tashish xizmati! Narx kelishiladi 📦`
- `bugun toshkent xorazm 2 joy bor tel`
- `xotin qiz kishi olib ketamiz tel`
- `yuk bor kishi kerak bolsa qo'ng'iroq qiling` ← *hozirgi ro'yxatda
  o'tib ketadigan yagona xato*

**O'tmasligi kerak (aloqasiz):**

- `Assalomu alaykum, guruhga yangi a'zo qo'shildi`
- `Kimda iPhone 15 bor, sotaman`
- `Bugun uchrashuv soat nechada?`

---

### Nusxalash bo'yicha eslatma

Agar hujjatni boshqa AI modeliga yuborsangiz, oxiriga quyidagini qo'shing:

> "Yuqoridagi tizim haqida ma'lumot berildi. Iltimos, **15-bo'limdagi
> savollarga** javob bering: har bir savol uchun (a) qisqa javob,
> (b) sabab, (c) amaliy qadam, (d) qanday o'lchash mumkinligi. Ortiqcha
> umumiy gaplar kerak emas — aniq, amalga oshiriladigan takliflar bering."
