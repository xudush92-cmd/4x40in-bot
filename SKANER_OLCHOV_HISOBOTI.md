# SKANER: VAZNLI MODEL — O'LCHOV HISOBOTI

**Sana:** 2026-10-25 · **Holat:** faqat o'lchov, **kodga tegilmagan** (ruxsat kutilmoqda)
**Tanlov (sizning javobingiz):** model = *vaznli skoring*, yetkazish = *avval o'lchov*,
stop-so'zlar = *bo'sh (admin o'zi kiritadi)*.

---

## 1. Nima o'lchandi

Yangi, oldingisidan **qiyinroq** korpus tuzildi (oldingi 27/24/11 emas):

| Toifa | Soni | Tavsifi |
|---|---|---|
| **Mijoz** | **45** | Xizmat so'raydiganlar — `kerak`, `kim olib ketadi`, `qancha turadi`, `bormi`, `yordam bering` |
| **Haydovchi** | **30** | Taklif e'lonlari — `joy bor`, `reys`, `har kuni`, `tashaymiz`, `qo'ng'iroq qiling` |
| **Aloqasiz** | **20** | Ish e'loni, ijara, savdo, suhbat, guruh qoidalari |

Metrika: **mijoz qancha topildi** (yuqori = yaxshi), **haydovchi nechta o'tib
ketdi** (past = yaxshi), **aloqasiz nechta o'tdi** (past = yaxshi).

Barcha o'lchovlar **haqiqiy `matcher.py`** bilan bajarildi (yangi kod yozilmadi —
mavjud `_find_entries`, `normalize_tokens`, `contains_emoji` ishlatildi).

---

## 2. Natijalar

| Variant | Chegara | Mijoz | Haydovchi o'tdi | Aloqasiz o'tdi |
|---|---|---|---|---|
| **Bugungi holat** (emoji qat'iy blok + 12 so'z, shart=1) | — | **38/45** (84%) | 1/30 | 3/20 |
| A. 12 so'z, vaznsiz | 0.25 | 36/45 (80%) | 1/30 | 2/20 |
| B. + niyat iboralari (`bormi`, `kim bor`, `ketadimi`…) | 1.75 | 44/45 (98%) | **5/30** | 2/20 |
| C. + stop-so'zlar (qat'iy moslik) | 1.75 | 44/45 (98%) | **0/30** | 2/20 |
| **D. C + domen-manfiy** (ish/ijara/savdo) | **1.75** | **44/45 (98%)** | **0/30 (0%)** | **1/20** |

**Xulosa:** D varianti bugungi holatdan **+6 mijoz** topadi, haydovchi
o'tishini **1 → 0** ga tushiradi, aloqasizni **3 → 1** ga tushiradi.

Qolgan xatolar (jami 2 ta, 95 xabardan):

| Xato | Sabab |
|---|---|
| `salom kimda Nukusga ketadigan mashina bor` — mijoz, topilmadi | `ketadigan` shakli `ketadi` o'zagiga mos kelmadi (fe'l shakli chegarasi) |
| `shu guruhda kimlar bor tanishamiz` — aloqasiz, o'tdi | `kim bor` iborasi suhbatda ham uchraydi |

---

## 3. Nima uchun ishladi — 4 mexanizm

### 3.1 Vazn: har so'zga ball, "bor/yo'q" emas

`kerak` = +3, `bormi` = +2.5, `qancha` = +2, `ketadi` = +1, `joy bor` = −4,
`reys` = −3. Yig'indi **chegaradan** (bizda 1.75) o'tsa — yuboriladi.
Bitta tasodifiy so'z endi butun qarorni hal qilmaydi.

### 3.2 Manfiy yozuvlar oddiy "stop" emas — **qat'iy** moslik talab qiladi

Bu eng muhim topilma. Manfiy yozuvni oddiy qidiruv bilan solishtirsak, u
**mijozni ham uradi**:

| Xabar | Oddiy moslik bilan | Qat'iy moslik bilan |
|---|---|---|
| `menga yuk tashish xizmati kerak 2 tonna` (mijoz!) | `xizmat −1.5`, `yuk tashish −2` → **blok** ❌ | moslik yo'q → **o'tadi** ✅ |
| `kim yuk tashish bilan shugullanadi menga kerak` (mijoz) | `shugullan −3` → **blok** ❌ | moslik yo'q → **o'tadi** ✅ |

Qoida: **manfiy yozuv = faqat aniq so'z yoki o'zak-prefiks** (`tashaymiz` ~
`tashaymizda`). 85% o'xshashlik, `SequenceMatcher`, uzun prefiks — manfiy
yozuvlar uchun **o'chirilgan**. Natijada mijoz 42 → 44 ga chiqdi.

### 3.3 Umumiy so'zlar manfiy bo'la olmaydi

`xizmat`, `yuk tashish`, `mashina`, `ketamiz`, `ketaman`, `yo'lovchi`, `tel` —
bularni manfiy qilib bo'lmaydi, **ikkala tomon ham yozadi**. Manfiy faqat
**haydovchi shakli** bo'lishi kerak:

| ❌ Noto'g'ri (umumiy) | ✅ To'g'ri (tor shakl) |
|---|---|
| `xizmat` | `xizmat ko'rsatamiz` |
| `yuk tashish` | `yukingizni tashaymiz` |
| `ketamiz` | `olib ketaman` |
| `narx` | `narx kelishiladi` |
| `bo'sh` | `bo'sh joy`, `bo'sh mashina` |

### 3.4 Domen-manfiy: begona mavzular

Aloqasiz xabarlarning asosiy manbai — **boshqa domen** (ish e'loni, ijara,
savdo), ular `kerak` so'zi bilan keladi:

- `ishga odam kerak oshpaz` → `kerak +3` o'tib ketardi
- `guruh uchun yangi admin kerakmi` → `kerak +3`
- `Kimda iPhone 15 bor sotaman` → `bor`/`bormi`

Yechim: `ishga −3`, `oshpaz −3`, `sotaman −3`, `ijaraga −3`, `reklama −3`.
Natija: aloqasiz 2 → **1**.

---

## 4. Topilgan BUGLAR

> **Holat: A qadami bajarildi** (2026-10-25) — 3 bug tuzatildi, 13 yangi test
> qo'shildi. Batafsil: **10-bo'lim**.

### 4.1 🔴 Jiddiy: `yo'q` va `yuk` tenglashtiriladi

`matcher._lazy_latin()` "dangasa lotin" uchun `o'→u`, `q→k` almashtiradi.
Natijada:

```
_lazy_latin("yo'q") = "yuk"
_word_matches("yo'q", "yuk")   → True   ❌
_word_matches("yo'q", "yukim") → True   ❌
```

**Ta'siri:** kalit `yo'q` bo'lsa, xabardagi `yuk`, `yukim`, `yuklar` ham
topiladi. Bu domenda `yuk` eng ko'p uchraydigan so'z — ya'ni xato katta.
Xuddi shunday: `to'q` ~ `tuk`, `bo'q` ~ `buk`, `qo'y` ~ `kuy`.

**Sabab:** "dangasa lotin" qoidasi **lotin yozuvidagi** so'zlarga ham
qo'llanadi, holbuki u faqat kirillni soddalashtirib yozishni tenglashtirish
uchun kerak.

**Tuzatish (sinovdan o'tgan, 1 satr mantiq):** lazy variant faqat so'z
**kirill** bo'lganda qo'shiladi:

```python
if _is_cyrillic(word):
    variants.append(_lazy_latin(base))
```

Tekshiruv: `yo'q`~`yuk` → **False** ✅, `kerak`~`kerak` → True ✅,
`qarshi`~`карши` → True ✅ (kirill birikmasi saqlanadi).

### 4.2 🟠 `bormi` oddiy `bor` bilan tenglashadi

```
_word_matches("bormi", "bor") → True            # strict_question yo'q
_word_matches("bormi", "bor", strict_question=True) → False  ✅
```

Mijoz belgisi `bormi` ni haydovchining `joy bor` i bilan aralashtiradi.
**Tuzatish:** musbat (mijoz) yozuvlar uchun `strict_question=True`.

### 4.3 🟡 Qisqa so'z prefiksi juda erkin

`menga` kaliti xabardagi `men` bilan mos keladi (kalit uzunroq, dumi 2 harf).
`men ham shu sohada ishlayman` → noto'g'ri ball. **Tuzatish:** "kalit uzunroq"
qoidasida xabar so'zi kamida **4 harf** bo'lsin.

---

## 5. Emoji filtri — TASDIQLANGAN QAT'IY BLOK

**Qaror (2026-10-25, egasi tomonidan tasdiqlangan):** emoji va stiker —
**qat'iy blok**, 5-bosqichda, kalit so'zlardan **oldin**. Vaznga
o'tkazilmaydi va o'chirilmaydi.

Sabab (egasining domen bilimi): **bu guruhlarda mijoz emoji ishlatmaydi** —
u shunchaki matn yozadi («mashina kerak», «2 joy kerak»). Emoji qo'shib
yozadigan odam — haydovchi e'loni. Shuning uchun emoji eng ishonchli va
eng arzon haydovchi belgisi.

Amaliy natija: ball qanchalik yuqori bo'lsa ham, emoji bosqichi birinchi
bo'lgani uchun xabar to'xtaydi:

```
OTADI     [ok]     mashina kerak iltimos
TO'XTAYDI [emoji]  mashina kerak iltimos 🙏
TO'XTAYDI [emoji]  🚕 2 joy bor
TO'XTAYDI [emoji]  kerak ✅✅✅
```

O'lchovdagi eski kuzatuv (emoji jarimasi −2.5 natijani o'zgartirmagan)
endi ahamiyatsiz: model o'zgarmaydi, qoida soddaroq va tezroq.

**Yagona xavf:** mijoz tasodifan `🙏` yoki `📞` qo'shsa — o'sha xabar
yo'qoladi. Egasi bu holatni bu domenda bo'lmaydi deb hisoblaydi. Agar
keyinchalik shikoyat kelsa, 🧪 Skaner testi `emoji` bosqichini ko'rsatadi
va qaror qayta ko'rib chiqiladi.

---

## 6. Natijada tizim qanday ko'rinadi

### 6.1 Ma'lumotlar bazasi

`phrases` jadvaliga **ikkita ustun**:

```sql
ALTER TABLE phrases ADD COLUMN weight   REAL    DEFAULT 1.0;   -- +mijoz / −haydovchi
ALTER TABLE phrases ADD COLUMN strict   INTEGER DEFAULT 0;     -- 1 = faqat o'zak/exact
```

`settings` ga: `score_threshold = 1.75` (hozirgi `match_count` o'rniga yoki
uning yonida). Per-user chegara ham mumkin (`own_threshold`).

### 6.2 Filtr zanjiri (6 bosqich saqlanadi, 5-6 o'zgaradi)

| # | Bosqich | O'zgarish |
|---|---|---|
| 1–4 | Tizim / tarif / Stop-Start / guruh | **o'zgarmaydi** |
| 5 | Emoji | **qat'iy blok — tasdiqlangan, o'zgarmaydi** |
| 6 | Ball yig'indisi | `matched_count >= shart` → `sum(weight) >= chegara` |

### 6.3 Admin panel

`🔑 Kalit so'zlar` sahifasi:
- har yozuv yonida vazn (`+3` / `−4`) ko'rsatiladi;
- tugmalar: **➕ Musbat**, **🚫 Manfiy**, **⚖️ Vaznni o'zgartirish**;
- ro'yxat ikki guruhga bo'linadi: *mijoz belgilari* va *haydovchi belgilari*;
- 🗑 o'chirishda ro'yxat yopilmaydi (hozirgi xatti-harakat saqlanadi);
- takror va qo'shimchali shakl tekshiruvi saqlanadi (`toshkentga` rad).

### 6.4 Test tugmasi

`🧪 Skaner testi` endi **ball hisobini** ko'rsatadi:

```
6. Kalitlar:  +3.00 kerak, +2.50 bormi  = 5.50   (chegara 1.75)  ✅
   Manfiy:    −4.00 joy bor                        = 1.50        ❌
```

---

## 7. Ish rejasi (ruxsat bergandan keyin)

| # | Ish | Fayl | Xavf |
|---|---|---|---|
| 1 | lazy-folding tuzatish + testlar | `matcher.py`, `test_matcher.py` | Past (1 satr + 4 test) |
| 2 | `strict_question` musbat yozuvlarga | `matcher.py`, `filters.py` | Past |
| 3 | "kalit uzunroq" qoidasida 4 harf sharti | `matcher.py` | Past |
| 4 | `weight`/`strict` ustunlari + migratsiya | `database.py` | O'rta (migratsiya) |
| 5 | `score()` funksiyasi zanjirga | `filters.py` | O'rta |
| 6 | Admin UI: vazn bilan ro'yxat | `bot.py` | O'rta |
| 7 | Per-user chegara | `database.py`, `bot.py` | Past |
| 8 | Regressiya: 95 xabarlik korpus testi | `test_matcher.py` | — |

Har bir qadam **alohida commit** va **test bilan**, keyin o'lchov qayta
bajariladi — natija yomonlashsa qaytariladi.

---

## 8. Ochiq savollar (javob kerak)

1. **Chegara 1.75** hozirgi korpusda eng yaxshi. Real oqimda ko'proq mijoz
   kerakmi (chegara 1.0) yoki aniqlik (2.5)?
2. ~~Emoji vazni~~ — **hal qilindi:** qat'iy blok (egasi tasdiqladi).
3. **Domen-manfiy** (ish/ijara/savdo) alohida ro'yxat bo'ladimi yoki umumiy
   manfiy ro'yxat ichida?
4. Foydalanuvchiga **"bu mijoz / bu haydovchi"** tugmasi qo'shilsinmi
   (ro'yxatni o'zi o'rgatishi uchun)? Bu 4-bosqichdan keyin eng katta foyda.
5. Chegara **per-user** bo'lishi kerakmi yoki faqat admin belgilaydimi?

---

## 9. Takrorlash (reproduce)

O'lchov skripti vaqtinchalik papkada (`/tmp/sk/`), snapshotga kirmaydi.
Kerak bo'lsa repoga `tools/measure_scanner.py` sifatida qo'shiladi (korpus
bilan birga). Hozircha faqat raqamlar va qarorlar saqlangan.

---

## 10. A QADAMI BAJARILDI — 3 bug tuzatildi

**Sana:** 2026-10-25 · **Fayllar:** `matcher.py`, `test_matcher.py`
**Testlar:** 39 → **52** (13 yangi, hammasi o'tadi)

### 10.1 Nima o'zgardi

| # | Bug | Tuzatish | Ta'sir |
|---|---|---|---|
| 1 | `yo'q` = `yuk` | `o'`→`u` almashtirish endi **faqat kirill manbali** va **4+ harfli** lotin so'zlarda | `yo'q`~`yuk` yopildi; `jo'nat`~`жунат`, `jo'naymiz`~`жунаймиз` saqlandi |
| 2 | `bormi` = `bor` | so'roq shakli **assimmetrik**: kalit `bormi` bo'lsa, xabar so'zi ham so'roq shaklida bo'lishi shart. `kerak` → `kerakmi` ochiq qoldi | haydovchining «2 joy bor» e'loni `bormi` kalitini endi tutmaydi |
| 3 | `menga` = `men` | «kalit uzunroq» qoidasida xabar so'zi **kamida 4 harf** | «men ham ishlayman» begona xabari endi ball olmaydi |

**Bonus (shu bugning davomi):** `canonical_entry()` — takror tekshiruvi ham
`yo'q` va `yuk` ni bir xil deb hisoblardi, ya'ni admin `yuk` ni qo'shgandan
keyin `yo'q` ni qo'sha olmasdi. Endi ikkalasi ham qabul qilinadi.

### 10.2 Cheklov (halol qayd)

«Dangasa» kirillda `йук` yozuvi **ikki xil** bo'lishi mumkin: `йўқ` (yo'q)
va `юк` (yuk). Bunday noaniqlik **taxmin qilinmaydi**: `yo'q` kaliti uni
tutmaydi, `yuk` kaliti tutadi. Bu ataylab — xato taxmin qilgandan ko'ra
tutmaslik yaxshiroq.

### 10.3 O'lchov (tuzatishdan keyin, 45/30/20 korpus)

| Ko'rsatkich | A dan oldin | A dan keyin |
|---|---|---|
| Ishlab chiqarish mantiqi (emoji + 12 so'z): mijoz | 38/45 | **38/45** (o'zgarmadi) |
| … haydovchi o'tdi | 1/30 | 1/30 |
| … aloqasiz o'tdi | 3/20 | 3/20 |
| D varianti (vaznli model): mijoz | 44/45 | **44/45** |
| … haydovchi o'tdi | 0/30 | **0/30** |
| … aloqasiz o'tdi | 1/20 | **1/20** |

Ya'ni A **hech narsani buzmadi** (regressiya yo'q), lekin keyingi B qadam
uchun poydevor tayyor: `bormi` endi kalit sifatida xavfsiz, `yo'q` esa
manfiy vazn sifatida ishlatilishi mumkin.

### 10.4 Yangi testlar (13 ta)

- `TestApostropheFoldGuard` (6): `yo'q`~`yuk`/`yukim`/`yuklar` yopilgan;
  `yo'q` o'zi bilan (lotin + `йўқ`) mos; `to'q`~`tuk`, `bo'sh`~`bush`;
  uzun so'zlarda `o'`→`u` saqlangan; `canonical_entry` ikkalasini ajratadi;
  `йук` noaniqligi taxmin qilinmaydi.
- `TestQuestionKeyRequired` (3): `bormi` faqat so'roq shaklini topadi;
  `kerak` → `kerakmi` ochiq.
- `TestShortWordPrefixGuard` (3): `menga`~`men` yopilgan; `menga` o'zi bilan
  mos; `ketadi`~`ketad` saqlangan.
- Mavjud `test_client_short_message_passes_filters` tuzatilgan semantikaga
  moslandi (endi `bormi` o'rniga haqiqiy savol shakli sinaladi va
  «2 odam bor» e'lon sifatida qabul qilinishi tekshiriladi).

### 10.5 Qayta tekshirish buyruqlari

```bash
cd telegram_scanner
python3 test_matcher.py          # 52 test
python3 -m py_compile *.py       # sintaksis
```

### 10.6 Keyingi qadam (B)

B1 — baza ustunlari (`weight`, `strict`) + `score()` + regressiya testi.
A dan farqi: bu yerda **model** o'zgaradi, shuning uchun alohida commit va
alohida o'lchov talab qilinadi.

---

## 11. B QADAMI BAJARILDI — vaznli model (baza + filtr + bot UI)

**Sana:** 2026-10-25 · **Fayllar:** `database.py`, `matcher.py`, `filters.py`,
`bot.py`, yangi `test_weights.py`
**Testlar:** `test_matcher` 52 + `test_weights` **30** + UI/oqim 49 = **131**

### 11.1 Savolga javob: vazn qanday beriladi — bot orqali

Uch yo'l bor, **kodda tayyor ro'yxat yo'q** — hammasi admin qo'lida:

**1) Kiritishda matn bilan** (eng tez, 56 so'z bir xabarda):

```
+3 kerak kerek
+3 izl qidir
+3 jo'nat jonat jull jiber yubor
+2 qancha
+1.5 necha
+1 ketadi
+2.5 bormi
+2: kim bor
+3: kim olib ketadi
-4 joy bor
-3 reys
-3: har kuni
-3.5 tashaymiz
-3.5: qo'ng'iroq qiling
-3 ishga
```

Qoidalar:

| Yozuv | Natija |
|---|---|
| `kerak` | bitta yozuv, vazn **+1** |
| `+3 kerak kerek` | ikki yozuv, har biri +3 (musbatda bo'linadi) |
| `-4 joy bor` | **bitta ibora** «joy bor», −4 (manfiyda birlashadi) |
| `-4: joy bor` / `-4 "joy bor"` | har qanday holatda ibora |
| `-3 reys +2 yukim` | ikki yozuv, har xil vazn |
| `+2.5 bormi, kerak` | vergul → ikki yozuv, +2.5 |

**2) Kartochkadan** — 📋 To'liq ro'yxat → so'zni bosing:
➖0.5 / ➕0.5, tayyor qiymatlar (Mijoz 3/2/1, Neytral 0, Haydovchi −1/−3/−4),
🔒 qat'iylik, 🗑 o'chirish. Ro'yxatda har so'z oldida vazni:
`➕3 kerak`, `➖4 joy bor`, `🔒` = qat'iy.

**3) Rejim va chegara** — 🔑 Kalit so'zlar sahifasidagi tugmalar:
`⚖️ Rejim` (hisob ⇄ ball), `🎯 Chegara` (0.5 … 4.0, ✅ joriy qiymatda).

### 11.2 Baza o'zgarishlari (migratsiya avtomatik)

```sql
ALTER TABLE phrases ADD COLUMN weight REAL    DEFAULT 1.0;  -- +mijoz / −haydovchi
ALTER TABLE phrases ADD COLUMN strict INTEGER DEFAULT 0;    -- 1 = aniq yozuv
INSERT settings: match_mode = 'count'        -- 'count' | 'weight'
INSERT settings: score_threshold = 1.75
```

Eski baza avtomatik yangilanadi: mavjud so'zlar `weight=1.0`, rejim
`count` bo'lib qoladi — **xatti-harakat o'zgarmaydi** (test bilan
tekshirilgan). `reset_db.py` ishlatish shart emas.

### 11.3 Filtr zanjiri

1–4 bosqich (tizim / tarif / Stop-Start / guruh) **o'zgarmadi**.
5-bosqich emoji — hozircha qat'iy blok (vaznga o'tkazish keyingi qadam).
6-bosqich endi rejimga qarab:

* `count` — `matched_count >= match_count` (eski mantiq);
* `weight` — `score >= score_threshold`, bunda:

| Tur | Qidiruv | Nega |
|---|---|---|
| Musbat yozuv | odatdagi moslik + so'roq qat'iy | `kerak` ~ `kerakmi`, `bormi` ≠ `bor` |
| Manfiy yozuv | **qat'iy**: aniq so'z yoki o'zak | imlo xatosi/prefiks yaqinligi manfiy so'zni mijozga tegizmasin |
| Emoji | **qat'iy blok** (5-bosqich, tasdiqlangan) | o'zgarmaydi |

### 11.4 O'lchov (haqiqiy kod, 45/30/20 korpus)

Vaznlar **botdagi kabi matn bilan** kiritildi, keyin `filters.evaluate()`
chaqirildi:

| Variant | Mijoz | Haydovchi o'tdi | Aloqasiz o'tdi |
|---|---|---|---|
| Hisob rejimi, 12 so'z, shart=1 | 38/45 | 1/30 | 3/20 |
| Ball, 12 musbat, chegara 0.5 | 36/45 | 1/30 | 2/20 |
| Ball, + niyat iboralari (21 yozuv), 1.75 | 39/45 | 0/30 | 1/20 |
| **Ball, to'liq tavsiya (56 yozuv), 1.75** | **44/45** | **0/30** | **1/20** |
| Ball, to'liq tavsiya (56), 2.5 | 40/45 | 0/30 | 0/20 |

Qo'shimcha: avval qabul qilingan yagona xato
(`yuk bor kishi kerak bolsa qo'ng'iroq qiling`) ham endi **bloklanadi** —
`qo'ng'iroq qiling` manfiysi (3+ −3.5) uni o'chiradi.

### 11.5 Test tugmasi endi ballni ko'rsatadi

```
❌ TO'XTAYDI: bugun toshkent xorazm 2 joy bor tel 90 123 45 67
   ball=-4/1.75  musbat={}  manfiy={'joy bor': -4.0}

✅ O'TADI: menga bugun bitta mashina kerak iltimos
   ball=4/1.75  musbat={'kerak': 3.0, 'iltimos': 1.0}  manfiy={}
```

Ya'ni «nega bu xabar keldi / nega kelmadi» degan savolga aniq javob bor.

### 11.6 Testlar

| Fayl | Soni | Nima tekshiriladi |
|---|---|---|
| `test_matcher.py` | 52 | moslik, alifbo, shakl, so'roq, qisqa so'z |
| `test_weights.py` | 30 | sxema/migratsiya, vazn chegarasi, qat'iy manfiy, rejim, filtr zanjiri, kiritish parseri |
| UI test (vaqtinchalik) | 31 | kartochka, vazn tugmalari, rejim, chegara, o'chirish |
| Oqim testi (vaqtinchalik) | 18 | matn bilan kiritish → ro'yxat → rejim → real filtr |

### 11.7 Keyingi qadam (B3 va undan keyin)

1. ~~Emoji~~ — **bekor qilindi:** qat'iy blok tasdiqlangan (egasi qarori).
2. **Per-user chegara** — har foydalanuvchi o'z chegarasini tanlashi.
3. **Feedback** — bildirishnomada «✅ Foydali / ❌ Keraksiz» tugmasi:
   bosilganda so'z vazni avtomatik moslashadi (eng katta foyda).
4. **So'rovnoma** (`SOROVNOMA_SKANER.md`) — real misollar bilan vaznlarni
   aniqlashtirish.

---

## 12. SOLISHTIRMA: vaznli model qanchalik yaxshi?

**Savol:** «vazn berish oldingi variantlarga qaraganda qanchalik yaxshi?»
**Javob qisqa:** mexanizm o'zi hech narsani yaxshilamaydi — **foyda
kontentdan** (niyat iboralari + manfiy yozuvlar) keladi, vazn esa ularni
**bitta tizimda** ifodalash imkonini beradi.

### 12.1 Bir xil 12 so'z: hisob ≈ ball

| Rejim | Mijoz | Haydovchi o'tdi | Aloqasiz o'tdi | F1 |
|---|---|---|---|---|
| Hisob (12 so'z, shart=1) | 38/45 (84%) | 1/30 | 3/20 | 0.874 |
| Ball (12 so'z, chegara 0.5–1.0) | 38/45 (84%) | 1/30 | 3/20 | 0.874 |

Ya'ni **bir xil ro'yxatda vazn hech narsa qo'shmaydi**. Bu kutilgan:
12 so'zning hammasi musbat, yig'indi ham «bor/yo'q» bilan bir xil.

> Diqqat: bu o'lchov davomida bitta **haqiqiy xato** topildi va tuzatildi —
> vazn rejimida musbat so'zlar simmetrik so'roq tekshiruvidan o'tib,
> `ketadi` kaliti `ketadimi`, `kerak` kaliti `kerakmi` shakllarini
> tutmay qolgan edi (mijoz xabari yo'qolardi). Endi musbat yozuvlarda
> tekshiruv **assimmetrik**: `bormi` ≠ `bor`, lekin `kerak` = `kerakmi`.

### 12.2 Asosiy farq: kontent + chegara

| Variant | Yozuv | Mijoz | Haydovchi | Aloqasiz | Aniqlik | F1 |
|---|---|---|---|---|---|---|
| Hisob, 12 so'z | 12 | 38/45 (84%) | 1/30 | 3/20 | 90% | 0.874 |
| Ball, 12 musbat | 12 | 38/45 (84%) | 1/30 | 3/20 | 90% | 0.874 |
| Ball, + niyat iboralari | 21 | 39/45 (87%) | **0/30** | 1/20 | 95% | 0.928 |
| **Ball, to'liq (56), 1.75** | **56** | **44/45 (98%)** | **0/30 (0%)** | 2/20 | **96%** | **0.967** |
| Ball, to'liq (56), 2.5 | 56 | 40/45 (89%) | 0/30 | **0/20** | **100%** | 0.930 |

**F1: 0.874 → 0.967 (+11%)**. Mijoz qamrovi **84% → 98%**, haydovchi
o'tishi **1 → 0**.

### 12.3 Chegara — yangi imkoniyat (oldin yo'q edi)

| Chegara | Mijoz | Haydovchi | Aloqasiz |
|---|---|---|---|
| 0.5–1.0 | 45/45 (100%) | 0/30 | 4/20 |
| **1.75–2.0** | **44/45 (98%)** | **0/30** | **2/20** |
| 2.5 | 40/45 (89%) | 0/30 | 1/20 |
| 3.0 | 39/45 (87%) | 0/30 | 1/20 |
| 3.5–4.0 | 25–27/45 (56–60%) | 0/30 | 0/20 |

Oldin faqat «nechta kalit» bor edi va u **sakraydi** (1 → 2 → 3 orasida
katta farq). Endi bitta raqam bilan **aniqlik ⇄ to'liqlik** almashinadi:
foydalanuvchi o'zi tanlaydi (ko'proq mijoz kerakmi yoki kamroq shovqin).

### 12.4 Nima uchun farq shunchalik katta

| Sabab | Hisob rejimida | Ball rejimida |
|---|---|---|
| Manfiy (haydovchi) belgisi | **umuman ifodalab bo'lmaydi** | `-4 joy bor`, `-3 reys` |
| Bitta so'zning ta'siri | hammasi teng (1 ta) | `kerak` = 3, `iltimos` = 1 |
| Niyat iboralari (`kim bor`, `ketadimi`) | faqat yakka so'z | ibora sifatida |
| Shovqin bilan kurash | faqat shart sonini oshirish | manfiy + chegara |

### 12.5 Iflos matn (imlo xatosi, kirill, apostrofsiz)

12 ta suniy «iflos» xabar: **hisob 11/12, ball 11/12** — vazn bu yerda
ustunlik bermaydi, chunki ikkalasi ham bir xil matcher yadrosidan
foydalanadi. Yagona xato ikkalasida ham bir xil:

* `karak bitta mashina` — `kerak` bilan o'xshashlik 0.80, chegara 0.85.

### 12.6 Halol ogohlantirishlar (muhim)

1. **Korpus kichik va qo'lda tuzilgan** (45/30/20). Raqamlar «in-sample»:
   manfiy yozuvlar aynan shu 30 e'longa qarab tanlangan — **overfit**
   xavfi bor. Real hayotda natija pastroq bo'ladi (taxminan 90–95%).
2. **Narx:** 56 yozuv (12 emas). Lekin bu bir martalik ish — keyin
   kartochkadan boshqariladi; va vazn berish `+3 kerak` kabi bitta
   qatorda bo'lgani uchun 2 daqiqa vaqt oladi.
3. **Qolgan kamchiliklar:**
   * `admin kerakmi`, `ishga odam kerak` kabi **boshqa domen** `kerak` li
     xabarlar hali ham o'tadi (`-3 admin`, `-3 ishga` yordam beradi, lekin
     hammasini qoplamaydi);
   * emoji hali **qat'iy blok** (5-bosqich) — mijoz `🙏📞` bilan yozsa
     xabar yo'qoladi;
   * imlo xatosi (`karak`) topilmaydi.
4. **Vaznlar qo'lda** — hozircha o'zi o'rganmaydi. Keyingi qadam:
   bildirishnomadagi «✅ Foydali / ❌ Keraksiz» tugmasi vaznlarni
   avtomatik moslashtiradi (bu eng katta foyda beradi).

### 12.7 Xulosa jadvali

| Savol | Javob |
|---|---|
| Vazn o'zi yaxshimi? | Yo'q — bir xil ro'yxatda natija bir xil |
| Kontent bilan yaxshimi? | **Ha** — F1 0.874 → 0.967, mijoz 84% → 98% |
| Nega? | Manfiy belgilarni ifodalash imkoniyati + iboralar + chegara |
| Narxi? | 56 yozuv (bir martalik), keyin botdan boshqariladi |
| Tavsiya? | **Rejim: ball, chegara 1.75**, 56 yozuvli ro'yxat bilan |
| Muqobil? | Aniqlik ustun bo'lsa — chegara **2.5** (100% aniqlik, 89% qamrov) |

---

## 13. C QADAMI BAJARILDI — fikr-mulohaza (`✅ Foydali / ❌ Keraksiz`)

**Sana:** 2026-10-25 · **Fayllar:** yangi `feedback.py`, `database.py`,
`notifier.py`, `scanner_manager.py`, `bot.py`, yangi `test_feedback.py`

### 13.1 Nima qiladi

Har bir bildirishnomada ikkita tugma:

```
[💬 Mijozga yozish (Lichka)]
[↗️ Guruhdagi asl xabarni ochish]
[✅ Foydali] [❌ Keraksiz]      ← yangi
```

Foydalanuvchi bosganda **o'sha xabarda qatnashgan so'zlarning vazni**
avtomatik moslashadi:

| Tugma | Musbat so'z | Manfiy so'z |
|---|---|---|
| ✅ Foydali | `+0.25` (kuchayadi) | `+0.25` (0 tomon zaiflashadi) |
| ❌ Keraksiz | `−0.25` (zaiflashadi) | **tegilmaydi** (o'z ishini qildi) |

Qoidalar:

* vazn hech qachon `0` ga tushmaydi — belgi saqlanadi (`0.25` → `−0.25`);
* chegara `±10`;
* bir xabar **bir marta** baholanadi (takror bosish e'tiborsiz);
* ruxsat: bildirishnoma **egasi** yoki **admin** (boshqasi olmaydi);
* tugmalar bosilgach o'sha xabardan olib tashlanadi;
* 📊 Statistikada yangi qator: `👍 Fikr-mulohaza: N ta baholangan — ✅ x (y%), ❌ z`.

### 13.2 Nega bu muhim

12-bo'limdagi asosiy xavf — **overfit**: 56 ta vazn men tuzgan 30 e'longa
qarab tanlangan. Feedback bu muammoni yo'q qiladi: vaznlar real oqimga
moslashadi, qo'lda sozlash yoki so'rovnoma shart bo'lmaydi.

Amaliy ta'sir: `❌` bosilgan xabardagi `kerak` kabi so'zlar sekin
zaiflashadi; `✅` bosilgan xabardagi noyob so'zlar kuchayadi. 10–20 ta
bosishdan keyin ro'yxat foydalanuvchining o'z guruhlariga moslashadi.

### 13.3 Baza

```sql
CREATE TABLE lead_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_user_id INTEGER NOT NULL,
  words TEXT NOT NULL,              -- '|' bilan ajratilgan topilgan so'zlar
  verdict TEXT DEFAULT '',          -- '' | 'useful' | 'useless'
  created_at INTEGER DEFAULT 0
);
```

Yozuv bildirishnoma yuborilayotganda yaratiladi (`scanner_manager`),
so'zlar ro'yxati verddiktadan olinadi (musbat + manfiy).

### 13.4 Testlar

| Test | Soni | Nima |
|---|---|---|
| `test_feedback.py` | 13 | siljitish chegaralari, ✅/❌ mantiqi, takror bosish, begona foydalanuvchi, noma'lum so'z, statistika, matnlar |
| UI test (aiogram) | 11 | tugma bosilishi, vazn o'zgarishi, ruxsat, takror, yo'q id, buzuq callback |

Jami loyihada: **52 matcher + 31 vazn + 13 feedback + 31 UI + 18 oqim +
11 feedback-UI = 156 tekshiruv**.

### 13.5 Ochiq savol

**Qadam 0.25 to'g'rimi?** Kichik qadam — sekin, lekin barqaror.
Katta qadam (0.5) tezroq moslashadi, lekin bitta xato bosish vaznni
sezilarli buzadi. Hozircha 0.25; statistikada `❌` ulushi 50% dan oshsa,
qadamni oshirish kerak bo'ladi.

---

## 14. D QADAMI BAJARILDI — per-user chegara + emoji qarori

**Sana:** 2026-10-25 · **Fayllar:** `database.py`, `filters.py`, `bot.py`,
`test_weights.py`, `README.md`

### 14.1 Emoji — yakuniy qaror (hujjat to'g'rilandi)

5-bo'lim qayta yozildi: emoji **qat'iy blok**, tasdiqlangan, o'zgarmaydi.
Sabab — egasining domen bilimi: mijoz faqat matn yozadi, emoji
haydovchining belgisi. Kodda o'zgartirish kerak bo'lmadi (allaqachon
shunday ishlaydi), faqat hujjat va README'dagi «keyingi qadamda vaznga
o'tkazamiz» degan noto'g'ri reja olib tashlandi.

### 14.2 Per-user chegara

| Nima | Qiymat |
|---|---|
| Yangi ustun | `users.own_score_threshold REAL DEFAULT 0` |
| `0` ma'nosi | «admin standartini ishlat» |
| Tanlash | 🔔 Xabar sharti → tugmalar `0.5 … 4.0`, joriy qiymat `✅` bilan |
| Qaytish | o'zi tanlagan bo'lsa `↩️ Admin standartiga qaytish` chiqadi |
| Ta'sir doirasi | **faqat o'ziga** — boshqa foydalanuvchilarga tegmaydi |
| Hisob rejimi | eski oqim (nechta kalit) saqlanadi |

Funksiyalar: `get_user_score_threshold()` (samarali qiymat, fallback bilan),
`get_own_score_threshold()` (faqat o'zi belgilagani, 0 = yo'q),
`set_user_score_threshold()` (0 = qaytish, `±10` chegarasi).

`filters.evaluate()` endi 6-bosqichda `get_user_score_threshold(owner_id)`
ishlatadi; `Verdict.own_threshold` bayrog'i test va diagnostikada
ko'rsatiladi.

### 14.3 🧪 Skaner testi

Holat blokida yangi qator:

```
🎯 Ball chegarasi: 2.5 (o'zingizniki)      # yoki
🎯 Ball chegarasi: 1.75 (admin standarti)
```

Hisob rejimida esa avvalgi `🔔 Xabar sharti: kamida N ta kalit` qatori.

### 14.4 Testlar

| Test | Soni | Nima |
|---|---|---|
| `test_weights.py` (yangi blok) | +7 | fallback, override, qaytish, chegaralar, filtrda qo'llanishi, migratsiya |
| UI test (aiogram) | 12 | menyu matni, tugmalar, tanlash, qaytish tugmasi, hisob rejimi |

Jami: `test_matcher` 52 + `test_weights` **38** + `test_feedback` 13 +
UI 31 + oqim 18 + feedback-UI 11 + chegara-UI 12 = **175 tekshiruv**.

### 14.5 Nega bu foydali

Turli foydalanuvchilar turli ehtiyoj bilan ishlaydi: dispetcherga ko'proq
mijoz kerak (past chegara), haydovchiga faqat aniq buyurtma kerak (yuqori
chegara). Endi har biri o'zi tanlaydi — admin standarti esa yangi
foydalanuvchilar uchun boshlang'ich qiymat bo'lib qoladi.

## 15. E QADAMI BAJARILDI — so'zlar bo'yicha tahlil (B varianti)

Fikr-mulohaza umumiy raqam beradi («70% foydali»), lekin **qaysi so'z**
aybdorligini ko'rsatmaydi. E qadami shu bo'shliqni to'ldiradi: `❌ Keraksiz`
bosilgan xabarlarda qatnashgan so'zlar yig'iladi va ulush bo'yicha saralanadi.

### 15.1 Qayerda ko'rinadi

`📊 Statistika` sahifasida yangi inline tugma:

```
🔍 So'zlar tahlili (fikr-mulohaza)
```

Tugma bosilganda (faqat admin):

```
🔍 So'zlar tahlili

Baholangan xabarlar: 24 ta

❌ Ko'p «keraksiz» bo'lgan so'zlar — vaznni pasaytirish kerak:
  • kerak — 6/9 (67%) · vazn +3
  • manzil — 3/4 (75%) · vazn +2
✅ Ko'p «foydali» bo'lgan so'zlar — ishonchli belgilar:
  • reys — 8/9 (89%)
```

Har bir «yomon» so'z ostida tugma turadi — bir bosishda vazn **0.25** ga
pasayadi (`➖0.25 kerak`). Qayta bosish mumkin. `🔄 Yangilash` qayta hisoblaydi,
`◀️ Statistika` asosiy sahifaga qaytaradi.

### 15.2 Qoidalar

| Qoida | Qiymat | Sabab |
|---|---|---|
| Minimal qatnashish | `STATS_MIN_TOTAL = 2` | bitta tasodifiy bosish statistikani buzmasin |
| Bir qadam | `STATS_STEP = 0.25` | feedback bilan bir xil (kutilmagan sakrash yo'q) |
| Musbat vazn | `0` dan o'tmaydi → `−0.25` | `0` = «e'tiborsiz», ya'ni blok ham, ishora ham emas |
| Bir xabar bir marta | so'z takrori sanalmaydi | `kerak kerak` ≠ ikki barobar |
| Baholanmagan xabar | hisobga olinmaydi | faqat `✅`/`❌` bosilganlar |

Saralash: **ulush** (`❌ soni / jami`) bo'yicha kamayish tartibida; teng
ulushda ko'proq qatnashgan so'z yuqorida.

### 15.3 Nega ikkinchi (`✅`) ro'yxat ham bor

`✅` ro'yxati — «bu so'z ishlayapti» degan ishonch. Agar vaznni pasaytirish
kerak bo'lsa, aynan shu so'zlar **oxirgi navbatda** tegiladi. Ro'yxat 5 ta
bilan cheklangan — ekran to'lib ketmasin.

### 15.4 Sxema

Yangi jadval **yo'q**: hammasi mavjud `lead_reviews` dan hisoblanadi
(`words` — JSON ro'yxat, `useful` — 0/1). Shu sababli migratsiya talab
qilinmaydi va eski fikr-mulohazalar darhol tahlilga tushadi.

```sql
-- get_word_feedback_stats(min_total)
SELECT words, useful FROM lead_reviews WHERE useful IS NOT NULL
```

### 15.5 Testlar

| Test | Soni | Nima |
|---|---|---|
| `test_feedback.py` → `TestWordStats` | +7 | bo'sh holat, sanash, ulush, saralash, `min_total`, baholanmagan, takror |
| So'zlar tahlili UI (aiogram) | 23 | bo'sh holat, matn, `%`, tugmalar, `−0.25`, `0` dan o'tish, `◀️` qaytish, prefiks to'qnashuvi |
| `test_feedback.py` jami | 20 | 13 + 7 yangi |

Jami: `test_matcher` 52 + `test_weights` 38 + `test_feedback` **20** +
UI 31 + oqim 18 + feedback-UI 11 + chegara-UI 12 + tahlil-UI 23 =
**205 tekshiruv**.

### 15.6 Nima uchun bu «avto-vazn» emas

Tahlil **maslahat beradi**, qaror qilmaydi. Sabab: bitta guruhdagi noto'g'ri
bosish butun tizim vaznini o'zgartirsa, boshqa foydalanuvchilar zarar
ko'radi — kalitlar esa umumiy (admin). Shuning uchun avtomatik o'zgarish
yo'q: admin ko'radi, o'zi bosadi. Har bosish jurnalga tushadi (`INFO`),
ya'ni keyin qaytarish oson.

## 16. Tashqi sharh bo'yicha tekshiruv va tuzatishlar

Boshqa model yozgan sharh keldi. U **kodni ko'rmagan** va eski 12 so'zlik
ro'yxat bo'yicha yozilgan edi, lekin ichida ikkita haqiqiy xato bor edi.
Hammasi haqiqiy kod bilan o'lchandi (56 yozuv, chegara 1.75).

### 16.1 Sharhdagi 7 misol — tekshiruv

| Xabar | Sharh dedi | Haqiqat (o'lchandi) |
|---|---|---|
| `Ertaga Xorazmga mashina ketadi` | mijoz bo'ladi | 1.0 ball → o'tmaydi ✅ |
| `Posilka jo'natamiz, yuboramiz` | — | **9.0 ball bilan o'tardi** ⚠️ |
| `Taksi xizmati kerak` | `-3 xizmat` bilan bloklanadi | 3.0 → o'tadi ✅ |
| `Mashina kerak ✅ 901234567` | xato | **ataylab** — emoji = qat'iy blok |
| `Mashina kerak emas` | inkor yo'q | **3.0 → o'tardi** ⚠️ |
| `Машина керак` (kirill) | translit yo'q | o'tadi ✅ (`cyr_to_lat` bor) |
| `Nechada uchrashamiz?` | `necha` juda keng | 1.5 < 1.75 → o'tmaydi ✅ |

Sharhning «kunlik limit 200», «xotiradagi dedup», `Verdict.add_step`,
`notifier.send` degan bandlari bu loyihada **umuman yo'q** — boshqa kod
haqida yozilgan.

### 16.2 Tuzatish 1 — bitta so'z ikki marta sanalmasin

**Muammo:** ro'yxatda `jo'nat` va `jonat` ikkalasi ham bo'lsa, bitta xabar
ikkala vaznni ham olardi:

```
"Posilka jo'natamiz, yuboramiz"  ->  +3 jo'nat  +3 jonat  +3 yubor  = 9.0
```

**Sabab:** `canonical_entry("jo'nat")` = `junat`, `canonical_entry("jonat")`
= `jonat` — dangasa-lotin qoidasi apostrofli shaklga qo'llanadi, apostrofsiziga
yo'q. Shuning uchun takroriy tekshiruv ularni ajratadi.

**Tuzatish (`matcher.py`):** yangi `_variant_signature()` — yozuvning
`_fold_variants` shakllari to'plami. `score_text()` da `_collapse_variants()`
bir xil so'zning barcha yozuvlarini birlashtiradi va **mutlaq qiymati eng
katta** vaznni qoldiradi. Musbat/manfiy birga ko'riladi: bitta so'z ikki
tomonda tursa ham faqat bittasi ishlaydi (aks holda `+3` va `-3` bir-birini
bekor qilardi). Teng bo'lsa manfiy qoladi — ortiqcha xabar yubormaslik
xavfsizroq.

Natija: `9.0` → `6.0` (`jo'nat` +3, `yubor` +3). `yo'q` ~ `yuk` kabi
omonimlar **ajralib turadi** (test bilan qulflangan).

### 16.3 Tuzatish 2 — inkor (`kerak emas`)

Kodda inkor qoidasi yo'q va **qo'shish shart emas**: bu ro'yxat masalasi.
Manfiy ibora qo'shilsa yetadi:

| Ro'yxat | Mijoz | Haydovchi xato | Aloqasiz xato | `Mashina kerak emas` |
|---|---|---|---|---|
| hozir | 44/45 | 0/30 | 2/20 | o'tadi ❌ |
| `-2: kerak emas` | 44/45 | 0/30 | 2/20 | **bloklanadi ✅** |

Korpusda birorta xabar yo'qolmadi; `kerak emasmi?` (mijoz savoli) ham
buzilmadi — manfiy ibora qat'iy moslikda ishlaydi.

### 16.4 Tuzatish 3 — WAL

`database._connect()` endi `PRAGMA journal_mode=WAL` + `timeout=10` bilan
ulanadi. Bot va skaner bir vaqtda yozganda `database is locked` xatosi
kamayadi. WAL yoqilmasa (tarmoq diski va h.k.) — jim o'tib, oddiy rejimda
davom etadi.

### 16.5 Tuzatish 4 — log va past chegara

- `[SCAN] topildi` vazn rejimida `3/0` deb yozardi. Endi:
  `topildi ball=4/1.75: +3 kerak, +1 iltimos`.
- Per-user chegara **0.5–1.0** da «nechada uchrashamiz?» (1.5 ball) kabi
  umumiy gaplar ham o'tadi. Endi 1.5 dan past tanlansa ogohlantirish
  chiqadi (`LOW_THRESHOLD_WARN = 1.5`), lekin taqiqlanmaydi.

### 16.6 Ro'yxat bo'yicha tavsiya (kod emas)

Tuzatishdan keyin ham `Posilka jo'natamiz, yuboramiz` 6.0 oladi, chunki
`jo'nat` va `yubor` — musbat yozuvlar, xizmat reklamasida ham uchraydi.
Yechim: shu so'zlarga manfiy juft qo'shish — `-3: jo'natamiz`,
`-3: yuboramiz`. Mijoz shakli (`yubormoqchiman`) qat'iy moslikda
tegilmaydi, ya'ni mijoz xabarlari o'tishda davom etadi.

### 16.7 Testlar

| Test | Soni | Nima |
|---|---|---|
| `test_matcher.py` → `TestVariantCollapse` | +7 | apostrof jufti, omonimlar, `bo'sh`/`bosh`, kuchli manfiy, iboralar, aloqasiz so'zlar |
| `test_weights.py` → `TestDatabaseWAL` | +2 | `journal_mode=wal`, WAL bilan yozish/o'qish |
| chegara-UI | +4 | 0.5 da ogohlantirish, 2.0/1.5 da yo'q |

Jami: `test_matcher` **59** + `test_weights` **40** + `test_feedback` 20 +
UI 31 + oqim 18 + feedback-UI 11 + chegara-UI **16** + tahlil-UI 23 =
**218 tekshiruv**.

Korpus regressiyasi: mijoz 44/45, haydovchi 0/30, aloqasiz 2/20 —
tuzatishlardan oldingi bilan **bir xil**.

## 17. Menyularni yopish tugmasi + admin «Xabar sharti» rejimga moslashdi

### 17.1 «❌ Yopish» tugmasi

Skrinshotdagi shikoyat: inline menyu ochiladi, lekin uni yopish tugmasi yo'q
— faqat `/cancel` yozish kerak edi. Endi **har bir inline menyuda**
`❌ Yopish` bor:

| Menyu | Tugma |
|---|---|
| 🔔 Xabar sharti (admin, hisob rejimi) | 1…5 + ❌ Yopish |
| 🔔 Xabar sharti (foydalanuvchi, ikkala rejim) | sonlar/chegaralar + ❌ Yopish |
| 🎯 Ball chegarasi (admin) | qiymatlar + ◀️ Ro'yxat + ❌ Yopish |
| 🔑 Kalit so'zlar menyusi va 📋 to'liq ro'yxat | … + ❌ Yopish |
| So'z kartochkasi | 🗑 · ◀️ Ro'yxat · ❌ Yopish |
| Guruh kartochkasi, guruhlar ro'yxati | … + ❌ Yopish |
| 👥 Foydalanuvchilar ro'yxati va kartochkasi | ⬅️ Orqaga + ❌ Yopish |
| 📊 Statistika, 🔍 So'zlar tahlili | … + ❌ Yopish |

Xatti-harakat (`close_inline_menu`): xabar **o'chiriladi** va FSM holati
tozalanadi (shu bilan «matn kutilmoqda» rejimi ham yopiladi). Xabar juda
eski bo'lib Telegram o'chirishga ruxsat bermasa — klaviatura olib tashlanadi.

### 17.2 Admin «Xabar sharti» — rejimga qarab

**Bug:** admin menyusi rejimni hisobga olmasdi. Ball rejimida ham
«kamida N ta kalit so'z» va 1…5 tugmalari chiqardi (skrinshot aynan shu).
Faqat foydalanuvchi tomonida shox bor edi.

**Endi:**

| Rejim | Admin ko'radi | Foydalanuvchi ko'radi |
|---|---|---|
| 🔢 hisob | «kamida N ta kalit» + 1…5 + ❌ Yopish | o'z soni (1…5) + ❌ Yopish |
| ⚖️ ball | «umumiy chegara N» + qiymatlar + ❌ Yopish | o'z chegarasi (0.5…4.0, ✅ joriy) + ↩️ admin standarti + ❌ Yopish |

Ball rejimida «Nechta kalit» sozlamasi umuman ishlatilmaydi — shuning uchun
admin menyusida FSM holati ham o'rnatilmaydi.

### 17.3 Testlar

| Test | Soni | Nima |
|---|---|---|
| `/tmp/t2/close.py` (yangi) | 21 | har bir menyuda tugma borligi, yopish xabarni o'chiradi + holatni tozalaydi, o'chirish imkoni bo'lmasa klaviatura olinadi, admin ball rejimida chegara menyusi |

Jami: **239 tekshiruv** (matcher 59, weights 40, feedback 20, UI 31, oqim 18,
feedback-UI 11, chegara-UI 16, tahlil-UI 23, yopish-UI 21).

## 18. Nazorat rejimi — modelni faqat admin o'qitadi

### 18.1 Muammo

Ilgari **har bir foydalanuvchi** `✅ Foydali / ❌ Keraksiz` bosib, umumiy
kalit so'zlar vaznini o'zgartira olardi. Kalitlar hammaga umumiy, ya'ni
bitta xato bosish boshqa foydalanuvchilarning filtriga ta'sir qilardi.

### 18.2 Yechim

```
foydalanuvchi guruhi → skaner topadi → ① bildirishnoma foydalanuvchiga
                                    → ② nusxa: adminning YOPIQ guruhi
                                            ↓
                                    bitta xabar (slayd)
                                            ↓
                          ✅ To'g'ri · ❌ Noto'g'ri · ⏭ O'tkazish
```

| Kim bosadi | Natija |
|---|---|
| **Admin** (`✅`/`❌`) | vazn **haqiqatan** o'zgaradi (±0.25) — yagona o'quv manbasi |
| Foydalanuvchi (`✅`/`❌`) | faqat **statistika** (`lead_reviews`); vazn o'zgarmaydi |

Foydalanuvchiga javob matni ham o'zgardi: «Fikringiz statistikaga
yozildi. Kalit so'zlar vaznini faqat bot egasi o'zgartiradi.»

### 18.3 Slayd (guruh to'lmaydi)

Guruhda **bitta** xabar turadi; yangi xabar kelganda bot uni
`editMessageText` bilan yangilaydi (`review_msg_id` sozlamada saqlanadi).
Xabar o'chirilgan bo'lsa — yangisi yuboriladi va id yangilanadi.

```
🔍 Nazorat — baholash
Kutilayotgan: 12 ta · jami 240 ta

Xabar #37
«menga bugun bitta mashina kerak iltimos»

⚖️ Ball: 4 (chegara 1.75)
🔑 So'zlar: kerak, iltimos
```

Tugmalar: `✅ To'g'ri` · `❌ Noto'g'ri` / `⏭ O'tkazish` · `📊 Statistika`.

### 18.4 Buyruqlar (faqat admin)

| Buyruq | Nima |
|---|---|
| `/nazorat` | shu guruhni nazorat guruhi qiladi va slaydni ochadi (lichkada — yo'riqnoma) |
| `/nazorat_stat` | statistika: ✅/❌/⏭/kutilayotgan |
| `/nazorat_ochir` | nazoratni o'chiradi (nusxalar kelmaydi) |

### 18.5 Maxfiylik

| Saqlanadi | Saqlanmaydi |
|---|---|
| matn, ball, chegara, ishlagan so'zlar, vaqt, yorliq | egasi (user_id), ism, telefon, guruh nomi/ID |

- nusxa faqat adminning o'z guruhiga boradi — boshqa foydalanuvchi ko'rmaydi;
- o'quv ma'lumoti Git ga tushmaydi;
- baholanmagan yozuvlar `purge_review_items(90)` bilan o'chiriladi.

### 18.6 Kod

| Fayl | Nima |
|---|---|
| `database.py` | `review_items` jadvali + `add_review_item`, `get_next_review_item`, `get_review_item`, `set_review_item_label`, `review_stats`, `purge_review_items` |
| `review.py` (yangi) | slayd matni/tugmalari, `refresh()`, `enqueue()`, `label()` (vaznni shu yerda o'zgartiradi) |
| `feedback.py` | `record_vote()` — foydalanuvchi fikri faqat statistika uchun |
| `scanner_manager.py` | bildirishnoma yuborilgandan keyin `review.enqueue(...)` — **fonda** (`asyncio.create_task`), skanerlash kutmaydi |
| `bot.py` | `/nazorat*` buyruqlari, `rv:*` callbacklari, foydalanuvchi tugmasi endi vaznga tegmaydi |

### 18.7 Testlar

`test_review.py` (yangi, repo ichida) — **23 test**: jadval va anonimlik
(egasi/telefon ustuni yo'q), navbat, birinchi slayd, ikkinchi xabar yangi
xabar emas tahrir, `✅` +0.25, `❌` −0.25 (manfiyga tegilmaydi), `⏭` vazn
o'zgarmaydi, takror bosish, noto'g'ri yorliq, statistika, `/nazorat`
guruhda va lichkada, `/nazorat_ochir`, o'chirilgan slayd qayta yuborilishi,
foydalanuvchi ovozi vaznga ta'sir qilmasligi.

Jami repo testlari: `test_matcher` 59 + `test_weights` 40 +
`test_feedback` 20 + `test_review` 23 = **142**.

### 18.8 Keyingi qadam (o'qitish)

Endi ma'lumot yig'iladi. 300–500 yorliq to'plangach:

1. 70% o'quv / 30% dev (dev hech qachon o'quvga tushmaydi);
2. uch variant bir xil dev to'plamda o'lchanadi — qoidalar / kichik model
   (belgi n-gramma + Naive Bayes) / LLM;
3. g'olib 1 hafta **soya rejimida** ishlaydi (qaror qabul qilmaydi, faqat
   logga yoziladi).

8 GB RAM / CPU sharoitida kutilgan g'olib — **kichik model**: 1–2 ms,
~50 MB, barqaror. LLM (3B) kechikishi 5–12 s va ishonchi past.

## 19. Ro'yxatning zaxira nusxasi: eksport / import

Ro'yxat faqat `scanner.db` ichida edi — baza buzilsa yoki noldan
tozalashdan keyin 65 ta yozuv yo'qolar edi. Endi `🔑 Kalit so'zlar`
menyusida ikki tugma bor:

```
📤 Nusxa (eksport)   📥 Import
```

### 19.1 Eksport

`kalit-sozlar.txt` fayli yuboriladi, har qatorda bitta yozuv:

```
+3 kerak
+2 bormi
-4 joy bor
-3 reys
```

Format `parse_weighted_entries` tushunadigan format bilan **bir xil** —
ya'ni faylni keyin `📥 Import` orqali qaytarib yuklash mumkin.

### 19.2 Import

Matn yoki `.txt` fayl yuboriladi:

| Holat | Natija |
|---|---|
| Baza'da yo'q | **qo'shiladi** |
| Bor, vazni boshqa | **vazni yangilanadi** |
| Bor, vazni bir xil | o'tkazib yuboriladi |
| Boshqa ro'yxatda (masalan stop-so'z) | rad etiladi, sabab ko'rsatiladi |

Hisobot: qo'shildi / yangilandi / o'tkazildi / rad etildi + o'zgargan
vaznlar ro'yxati (`kerak: +3 → +4`) + ro'yxatdagi jami son.

### 19.3 Kod

| Fayl | Nima |
|---|---|
| `database.py` | `export_phrases_text()`, `import_phrases(pairs)` |
| `bot.py` | `📤 Nusxa (eksport)` (`wexport`), `📥 Import` (`wimport`), `ImportWords` holati + fayl o'qish |

### 19.4 Testlar

`test_export.py` — **8 test**: format (`+3 kerak`, `-4 joy bor`), fayl
yuborilishi, **aylanma yo'l** (eksport → import → hech narsa o'zgarmaydi),
yangi qo'shish + vazn yangilash, bo'sh ro'yxat, matn orqali import,
bo'sh matn rad etilishi, menyudagi tugmalar.

Jami repo testlari: 59 + 40 + 20 + 23 + **8** = **150**.

## 20. Jonli ro'yxat auditi (65 yozuv) va tuzatilgan ro'yxat

**Sana:** 2026-10-25 · Manba: serverdan olingan eksport (`kalit-sozlar.txt`, 65 yozuv).

### 20.1 O'lchov: hozirgi ro'yxat korpusda yiqildi

| Ro'yxat | Mijoz | Haydovchi xato o'tdi | Aloqasiz xato | F1 |
|---|---|---|---|---|
| **Jonli (65 yozuv, 0 manfiy)** | **34/45** | **10/20** | **6/20** | 0.618 |
| Tavsiya etilgan (63 yozuv, 28 manfiy) | **45/45** | **0/20** | 2/20 | **0.978** |

Ya'ni jonli ro'yxat mijoz xabarlarining **11 tasini yo'qotadi** va
haydovchi e'lonlarining **yarmini** o'tkazib yuboradi.

### 20.2 Uch ildiz sabab

**1) `kerak` umuman yo'q.** Ro'yxatda `+0.5 karakm` va `+1 garakm`
(«kerakmi» xato yozuvlari) bor, lekin **`kerak`** yo'q. Natijada:

```
mashina kerak        -> ball 1     chegaradan (1.75) past -> YO'QOLADI
yuk kerak            -> ball 1     -> YO'QOLADI
menga mashina kerak  -> ball 1     -> YO'QOLADI
```

Eng kuchli mijoz belgisi tushib qolgan.

**2) Bitta ham manfiy yozuv yo'q (0/65).** Faqat emoji blok qolgan:

```
2 joy bor        -> ball 4  -> haydovchi e'loni O'TIB KETADI
3 joy bor ...    -> ball 4  -> O'TIB KETADI
```

**3) Umumiy so'zlar yuqori vazn bilan.** `odam +2.75`, `bor +3`,
`bir +1.75`, `ikki +1.25` — bular mijozga ham, haydovchiga ham tegishli.

Boshqa nuqsonlar: `ketad`, `olib`, `olp`, `getad`, `ating`, `qling`,
`bash`, `alti`, `ikk`, `kish` — **o'zak noto'g'ri kesilgan** (bu shakllar
haqiqiy so'zlarga mos kelmaydi yoki tasodifiy so'zni tutadi).

### 20.3 Tuzatilgan ro'yxat

`kalit-sozlar-tavsiya.txt` (repo ildizida, 63 yozuv: 35 musbat + 28 manfiy).
O'lchangan (45/20/20 korpus):

| Ko'rsatkich | Qiymat |
|---|---|
| Mijoz xabari | **45/45** |
| Haydovchi e'lonlari o'tib ketdi | **0/20** |
| Aloqasiz o'tib ketdi | 2/20 (`shu guruhda kimlar bor`, `admin kerakmi`) |
| F1 | **0.978** |

Asosiy yozuvlar:

```
+3 kerak kerek          -4 joy bor           -3.5: qo'ng'iroq qiling
+3 izl qidir            -4: bo'sh joy        -3.5 tashaymiz
+3 jo'nat jonat ...     -3 reys              -4: xizmat ko'rsatamiz
+2.5 bormi              -3: har kuni         -3: olib ketaman
+3: kim olib ketadi     -2.5 kelishiladi     -3: bo'sh mashina
+2: kim bor             -3: kerak emas       -3 sotaman/sotiladi/...
```

### 20.4 Inkor ham yopildi (kod o'zgarmadi)

```
mashina kerak emas       -> ball 1   -> bloklanadi ✅
menga mashina kerak emas -> ball 1   -> bloklanadi ✅
kerak emasmi? kim bor    -> ball 5   -> o'tadi (mijoz savoli) ✅
```

Buning uchun `-3: kerak emas` va `-3 kerakmas` yozuvlari yetadi —
manfiy ibora qat'iy moslikda qidiriladi, shuning uchun `emasmi` shakli
tegilmaydi.

### 20.5 Qanday qo'llanadi

```
🔑 Kalit so'zlar → 📥 Import → kalit-sozlar-tavsiya.txt ni yuborish
```

Import mavjud yozuvlarning vaznini yangilaydi, yangisini qo'shadi.
`kerak`, `bor`, `odam` kabi eski yuqori vaznli umumiy so'zlar yangi
ro'yxatda **yo'q** — ular o'chirilmaydi, lekin importdan keyin
`📋 To'liq ro'yxat` da qolib ketadi. Ularni qo'lda o'chirish kerak
(yoki o'chirilgan ro'yxat bilan to'liq almashtirish — keyingi ish).

## 21. Yakuniy kalit so'zlar ro'yxati + to'liq almashtirish importi

### 21.1 Ro'yxat kengaytirildi: 63 → 76 yozuv

20-bo'limdagi bazaga 13 yozuv qo'shildi va har biri alohida o'lchandi
(faqat natijani buzmaydiganlari qabul qilindi):

| Yo'nalish | Qo'shilgan yozuvlar |
|---|---|
| Musbat | `+1.5 turadi`, `+2 bormikin`, `+1.5 ketadigan`, `+2: olib boradigan`, `+1.5 kimda`, `+1.5 yetkazish`, `+1 odam` |
| Manfiy | `-3 joylar`, `-3.5: qabul qilamiz`, `-3 yuklab`, `-2.5 haydovchiman`, `-3: kimlar bor`, `-4: admin kerak` |

**Rad etilgan:** `+1 bor` (haydovchi e'lonida ham uchraydi — 1 ta xato
keltirdi), `-3 guruh` (mijoz xabarini ham o'chirishi mumkin).

### 21.2 O'lchov

| Ro'yxat | Mijoz | Haydovchi xato | Aloqasiz xato |
|---|---|---|---|
| Jonli (65, 0 manfiy) | 34/45 | 10/20 | 6/20 |
| Tavsiya v1 (63) | 45/45 | 0/20 | 2/20 |
| **Tavsiya v2 (76)** | **45/45** | **0/20** | **1/20** |

Yagona qolgan xato — `guruh uchun yangi admin kerakmi` (guruh a'zosi
admin so'raydi). Uni `-4 admin` bilan yopish mumkin, lekin mijoz ham
«admin, mashina kerak» deb yozishi mumkin — shuning uchun **ataylab
qoldirildi**.

### 21.3 Import endi ikki rejimda

`📥 Import` → fayl (yoki matn) yuboriladi → bot **avval ko'rsatadi**:

```
📥 Fayl o'qildi

Faylda: 70 ta yozuv
Bazada hozir: 65 ta

[➕ Qo'shish/yangilash]   [🧹 To'liq almashtirish]
```

| Rejim | Nima qiladi |
|---|---|
| ➕ Qo'shish/yangilash | fayldagi yozuvlar qo'shiladi, mavjudlarining vazni yangilanadi; **boshqa yozuvlar qoladi** |
| 🧹 To'liq almashtirish | ro'yxat fayldagi bilan **bir xil** bo'ladi: faylda yo'q yozuvlar o'chiriladi |

Hisobotda `🗑 O'chirildi: N ta` qatori ham chiqadi.

### 21.4 Real sinov (eski ro'yxat → yangi)

65 ta yozuvdan 76 talikka **bir bosishda** o'tildi:

```
qo'shildi 70 | yangilandi 1 | o'chirildi 59 | rad 0 | jami 76
o'chirilganlar: bor, kim, olib, ketad, bir, ikki, uch, to'rt, besh, ...
```

Natija: mijoz **45/45**, haydovchi xatosi **0/20**, aloqasiz **1/20**.

```
mashina kerak        -> O'TDI  ball 4     (ilgari 1 -> yo'qolardi)
2 joy bor            -> yo'q   ball -4    (ilgari O'TIB KETARDI)
odam kerak           -> O'TDI  ball 4
mashina kerak emas   -> yo'q   ball 1
nechada uchrashamiz  -> yo'q   ball 1.5
```

### 21.5 Testlar

`test_export.py` — **7 test** (preview + merge + replace + hisobot).
Jami repo: 59 + 40 + 20 + 23 + 7 = **149 test**.

---

## 22. Zaxira nusxasi (`zaxira.sh`) va iboralar bug'i

### 22.1 Skript nima qiladi

```bash
./zaxira.sh                  # to'liq nusxa (xizmatni to'xtatib, keyin yoqadi)
./zaxira.sh --no-stop        # xizmatni to'xtatmasdan (tez)
./zaxira.sh --list           # mavjud nusxalar
./zaxira.sh --restore FILE   # tiklash (avval hozirgi holat saqlanadi)
```

Arxiv ichida: `scanner.db` (+ `-wal` / `-shm`), `.env`, `kalit-sozlar.txt`
(o'qish uchun oddiy matn), `README.txt` (sana, git commit, tiklash buyrug'i).
Fayl huquqi `600`. Xizmat nomi — `SCANNER_SERVICE` (standart `scanner-bot`),
papka — `SCANNER_BACKUP_DIR` (standart `<loyiha>/zaxira`).

`--restore` avval arxivni `tar -tzf` bilan tekshiradi, xizmatni to'xtatadi,
joriy bazani `oldin-tiklash-<sana>.tar.gz` ga saqlaydi, keyin arxivni ochadi.

### 22.2 Sinov natijalari (sandbox, vaqtinchalik papkada)

| Sinov | Natija |
|---|---|
| `--help`, `--list`, noto'g'ri parametr | ✅ |
| `--no-stop` bilan nusxa | ✅ 4 fayl, `kalit-sozlar.txt` to'g'ri |
| bazani o'chirib `--restore` | ✅ 4 yozuv **vazni bilan** qaytdi |
| `oldin-tiklash-*.tar.gz` | ✅ yaratildi |
| mavjud bo'lmagan arxiv | ✅ tushunarli xato, kod 1 |

### 22.3 Topilgan va tuzatilgan bug (muhim)

`_migrate_old_sets()` **har `init_db()` da** ishlar edi: ko'p so'zli har bir
yozuvni alohida so'zlarga bo'lib tashlardi. Ya'ni bot har restartda
`joy bor (-4)` ni `joy (+1)` + `bor (+1)` ga aylantirardi — **vazn yo'qolardi**.

Tuzatish:

* migratsiya `settings.legacy_sets_split` belgisi bilan **faqat bir marta**;
* bo'lishda `weight` va `strict` **saqlanadi**;
* iboralar (`joy bor`, `kim olib ketadi`) endi qonuniy yozuv.

Regressiya: `test_weights.py` ga 3 test qo'shildi (ibora restartdan keyin
butun; eksport iborani saqlaydi; legacy bo'lish bir martagina, vazni bilan).

### 22.4 Testlar

59 (matcher) + **43** (weights) + 20 (feedback) + 23 (review) + 7 (export)
= **152 test** — hammasi OK.

---

## 23. O'qitish to'plami (yangi)

`o_qitish/` papkasi:

| Fayl | Nima |
|---|---|
| `qitish-matnlari.tsv` | **315 yorliqlangan xabar**: 97 mijoz, 101 haydovchi, 117 boshqa |
| `baholash.py` | to'plamni joriy 76 yozuvli ro'yxat bilan o'lchaydi |
| `OQITISH_QOLLANMA.md` | format, yig'ish qoidalari, maxfiylik |

### 23.1 O'lchov (chegara 1.75)

```
mijoz       97 -> 83 topildi   85.6%
haydovchi  101 ->  0 o'tdi      0.0%
boshqa     117 -> 14 o'tdi     12.0%
```

Haydovchi e'lonlarining **birortasi ham o'tmayapti** (emoji filtri +
manfiy so'zlar). Mijozning 14 tasi topilmayapti — ularning ko'pchiligida
umuman kalit so'z yo'q.

### 23.2 Topilgan haqiqiy xatolar (kod darajasida)

| Xabar | Ball | Sabab |
|---|---|---|
| `kimda bo'sh joy bor` | **−9.00** | `joy bor` (−4) + `bo'sh joy` (−4) + `bo'sh` (−2.5) — bitta ibora uch marta |
| `admin bormi` | **+4.50** | `bormi` (+2.5) + `bormikin` (+2) — prefiks mosligi ikki marta |
| `bo'sh joy bor` | −10.50 | yuqoridagi bilan bir xil |
| `mashina kerak, qo'ng'iroq qiling` | 0.50 | `qo'ng'iroq qiling` (−3.5) mijozi ham aytadi |
| `bugun kechqurun chiqamiz, mashina kerak` | 1.50 | `chiqamiz` (−2.5) mijozi ham aytadi |

Birinchi ikkitasi — **bir-birini qoplaydigan mosliklar qo'shilib ketishi**.
Tuzatish: bir xil matn bo'lagiga tushgan yozuvlardan faqat **eng uzuni**
(eng aniq iborasi) hisoblansin. Bu `matcher.score_text` ga tegadi —
ruxsat so'raladi.

### 23.3 Testlar

O'zgarish yo'q: 152 test OK. `baholash.py` — alohida vosita, botga ta'sir qilmaydi.

---

## 24. Vazn xatolari va qoplama tuzatildi (4 + 1)

### 24.1 Tuzatilgan xatolar

| # | Xato | Avval | Endi |
|---|---|---|---|
| 1 | Manfiy so'zlar **qo'shilib** ketardi | `bo'sh joy bor` → **−10.50** | **−4.00** (eng kuchlisi) |
| 2 | Vazn **belgisi almashardi** | `+0.25` ga ❌ → **−0.25** | `+0.25` da qoladi |
| 3 | Yuqori chegara juda baland | 28 ✅ → **10.0** | 5.0 (`MAX_ABS`) |
| 4 | Admin panelidagi «➖0.25» ham belgini almashtirardi | `+0.5` → `−0.25` | umumiy `_shift` qoidasi |
| 5 | Ikki so'z mijozni bloklardi | `qo'ng'iroq qiling` (−3.5), `chiqamiz` (−2.5) | ro'yxatdan olib tashlandi |

`feedback._shift` endi uch qoidani biladi: **0 ga o'tilmaydi**, **belgi
almashmaydi**, **|vazn| ≤ 5**. `matcher.score_text` esa manfiylardan faqat
**eng kuchlisini** hisoblaydi (musbatlar avvalgidek qo'shiladi).

Muhim: foydalanuvchining ✅/❌ tugmasi **vaznga umuman tegmaydi** — faqat
statistika. Vaznni faqat admin o'zgartiradi.

### 24.2 O'lchov (315 xabar, chegara 1.75)

| | Mijoz | Haydovchi xatosi | Boshqa xatosi |
|---|---|---|---|
| Avval (76 yozuv) | 83/97 — 85.6% | 0/101 | 14/117 |
| **Endi (74 yozuv)** | **86/97 — 88.7%** | **0/101** | 14/117 |

Ya'ni **+3 mijoz, haydovchilarda yo'qotish yo'q**.

Tekshiruv:

```
bo'sh joy bor                      -4.00   (avval -10.50)
kimda bo'sh joy bor                -2.50   (avval -9.00)
mashina kerak, qo'ng'iroq qiling    4.00   (avval 0.50 -> o'tmasdi)
bugun kechqurun chiqamiz, mashina kerak  4.00  (avval 1.50 -> o'tmasdi)
Toshkentdan chiqdim, 2 joy bor     -4.00   (haydovchi, baribir blok)
reys bor, 2 joy                    -3.00   (haydovchi, baribir blok)
```

### 24.3 Testlar

59 + **47** + **23** + 23 + 7 = **159 test** — hammasi OK.
Yangi testlar: belgi almashmasligi, 40 marta bosishdan keyin ham musbat
qolishi, chegara 5.0, qoplama manfiylar bir marta hisoblanishi.

---

## 25. Kirill inkori tuzatildi

### 25.1 Muammo

```
машина керак эмас   ->  +3.00  O'TIB KETARDI
```

Sabab: musbat yozuvlar ``_fold_variants`` orqali solishtirilardi (u yerda
``cyr_to_lat`` bor), manfiy yozuvlar esa **xom** tokenlar bilan —
``керак эмас`` lotin ``kerak emas`` ga aylanmasdi.

### 25.2 Tuzatish

`_find_entries_strict` endi ham lotin-kirill farqini biladi:

* **so'z**: `_strict_word_match` — aynan teng, qo'shimchali shakl
  (``reys`` ~ ``reyslar``) yoki **uzun so'zda bitta harf farqi**
  (``kerak`` ~ ``kerek``, ya'ni ``керек эмас``);
* **ibora**: `_phrase_token_match` — tenglik + uzun so'zda bitta harf
  farqi (``керек эмас`` ~ ``kerak emas``);
* qisqa so'zlarda bitta harf farqi **qo'llanmaydi**: ``bor`` ~ ``bir``
  kabi tasodifiy moslik bo'lmasin.

### 25.3 Natija

| Xabar | Avval | Endi |
|---|---|---|
| `машина керак эмас` | +3.00 **o'tardi** | **+1.00 o'tmaydi** |
| `керек эмас` | +3.00 o'tardi | **0.00 o'tmaydi** |
| `mashina kerek emas` | +4.00 o'tardi | **+1.00 o'tmaydi** |
| `Машина керак Тошкентдан` | +4.00 o'tadi | +4.00 **o'tadi** (o'zgarmadi) |
| `Ташкентдан чиқдим, 2 жой бор` | −4.00 blok | −4.00 **blok** |

315 xabarlik to'plamda o'zgarish yo'q: mijoz **86/97**, haydovchi xatosi
**0/101**, boshqa **14/117**.

Tezlik: bitta xabar ~**2.2 ms** (600 xabar = 1.3 s) — bot uchun muammo emas.

### 25.4 Testlar

59 + **53** + 23 + 23 + 7 = **165 test** — OK.
Yangi 6 test: kirill inkori topilishi, o'tib ketmasligi, `керек` imlo
varianti, kirill mijoz xabari o'tishi, kirill haydovchi e'loni bloki,
qisqa so'zda bitta harf qoidasi ishlamasligi.

---

## 26. Guruh olib tashlandi — baholash bot ichida

### 26.1 Muammo (skrinshotlardan)

Bot **guruhda ham** shaxsiy chatdagidek ishlardi: menyu tugmalari bosilganda
panel guruhga qayta yuborilardi, `Tushunmadim 🙂 Quyidagi menyudan
foydalaning` esa har qanday matnga javob berardi. 44 ta handlerning
**birortasida ham** chat turi tekshirilmasdi.

### 26.2 Nima o'zgardi

| Narsa | Avval | Endi |
|---|---|---|
| Bot guruhda | menyu, javob, tugmalar | **butunlay jim** (`PrivateChatOnlyMiddleware`) |
| Baholash (nazorat) | yopiq guruh + `/nazorat` | **bot ichida**, `🎓 Nazorat (baholash)` tugmasi |
| Slayd qayerga ketadi | istalgan chat ID | **faqat `ADMIN_ID`** — guruh ID rad etiladi |
| Bir xil xabar navbatda | har safar yangi qator | **takrorlanmaydi** |

Batafsil:

* `PrivateChatOnlyMiddleware` — `dp.message` va `dp.callback_query` uchun
  outer middleware. Guruh/kanal eventlari handlerlarga **umuman yetib
  bormaydi** (44 handlerga tegilmadi).
* `review.review_chat_id()` endi faqat `ADMIN_ID` ni qaytaradi;
  `set_review_chat()` boshqa ID ni **rad etadi** (log yoziladi). Eski
  sozlamada guruh ID qolgan bo'lsa — e'tiborsiz qoldiriladi, ya'ni slayd
  hech qachon guruhga ketmaydi.
* `🎓 Nazorat (baholash)` — 🛠 Admin panel ichida. Bosilganda slayd shu
  shaxsiy chatda ochiladi va **o'sha bitta xabar tahrirlanib turadi** —
  chat to'lmaydi.
* `database.add_review_item` — bir xil matn (bo'sh joylar hisobsiz)
  ikkinchi marta qo'shilmaydi, `0` qaytaradi. Slayd faqat yangi xabar
  kelganda yangilanadi.
* Nusxa anonim: matn + ball + ishlagan so'zlar. Egasi, ismi, telefoni,
  guruh nomi **saqlanmaydi**; boshqa foydalanuvchi hech narsa ko'rmaydi.

### 26.3 Testlar

59 + 53 + 23 + **31** + 7 = **173 test** — OK.

Yangi testlar: guruh eventi handlerlarga yetib bormasligi, shaxsiy chat
o'tishi, guruh ID rad etilishi, `/nazorat` guruhda jim qolishi,
`🎓` tugmasi shaxsiy chatda ochilishi, bir xil matnning takror
qo'shilmasligi (bo'sh joy va bo'sh matn bilan birga).

---

## 27. ⚡ Chegaraga yaqin xabarlar (B varianti)

### 27.1 Nega kerak

Ilgari navbatga faqat **o'tgan** xabarlar tushardi: admin faqat
«noto'g'ri o'tganlarni» ko'rardi. Model **o'tkazib yuborgan mijozlar**
umuman ko'rinmasdi — ya'ni xatoning yarmi yashirin qolardi.

### 27.2 Nima qilindi

| Narsa | Qiymat / xatti-harakat |
|---|---|
| Chegara oralig'i | `NEAR_MIN = 1.0` — ball `1.0 ≤ ball < chegara` bo'lsa navbatga tushadi |
| Faqat qaysi holatda | `mode == "weight"` va to'xtash bosqichi **`keywords`** (emoji/tarif/guruh sababli to'xtaganlar hisobga olinmaydi — ball mazmunli emas) |
| Navbat chegarasi | `NEAR_MAX_PENDING = 300` — shundan ko'p baholanmagan xabar bo'lsa yangi ⚡ qo'shilmaydi |
| Slaydda belgisi | `⚡ Chegarada — o'tmadi` + «Model buni o'tkazib yubordi. Mijoz xabarimi?» |
| Statistika | `⚡ Chegarada (o'tmagan): N` qatori |

Yozuvni ⚡ deb aniqlash uchun yangi ustun kerak emas: ball va chegara
allaqachon saqlanadi, `score < threshold` bo'lsa — chegarada.
`✅ To'g'ri` bosilsa o'sha so'zlar kuchayadi (+0.25), ya'ni keyingi safar
xabar chegaradan o'tadi.

### 27.3 Testlar

59 + 53 + 23 + **36** + 7 = **178 test** — OK.

Yangi 5 test: oraliq chegaralari (1.0 / 1.75 / 0.9 / manfiy / chegara 0),
⚡ slayd belgisi, o'tgan xabarning belgisi, statistikada `near` soni,
`_queue_near_miss` faqat `weight` + `keywords` + oraliq holatda qo'shishi.

---

## 28. 🧾 Diagnostika va 👁 Kuzatuv (botni kuzatish)

### 28.1 🧾 Diagnostika — log faylini botning o'zi yuboradi

`logbuffer.py` — halqa buferi (oxirgi **2000** qator). `main.py` va
`bot.py` ishga tushganda `logbuffer.install()` chaqiriladi.

* 🛠 Admin panel → **🧾 Diagnostika** → oxirgi 300 qator `diagnostika-*.txt`
  bo'lib shu chatga keladi (serverga kirish shart emas).
* **Maxfiylik:** yuborishdan oldin 9+ raqamli ketma-ketliklar `[raqam]` ga
  almashtiriladi. `ball=4/1.75`, `2 kishi` kabi qiymatlar tegilmaydi.
* Root logger darajasi INFO dan past bo'lsa, `install()` uni tushiradi —
  aks holda loglar bufferga umuman yetib bormasdi.

### 28.2 👁 Kuzatuv — har bir xabar va sababi

`/kuzat 15` (yoki `/kuzat_ochir`) — admin uchun. Yoqilganda **har bir**
skanerlangan xabar kartasi shaxsiy chatga keladi:

```
👁 Kuzatuv · 14 daq qoldi
«mashina kerak 2 kishi»
⚖️ ball 1.5 / 1.75
➕ +1 mashina, +3 kerak
➖ —
Natija: ⚡ chegarada — o'tmadi
```

Cheklovlar:

* faqat **adminning o'z akkaunti** skanerlagan xabarlar (`owner_id == ADMIN_ID`);
* faqat `ADMIN_ID` ga yuboriladi;
* 1–120 daqiqa, vaqt tugagach o'zi o'chadi;
* matn 400 belgigacha qisqartiriladi, HTML escape qilinadi.

### 28.3 Testlar

59 + 53 + 23 + 36 + 7 + **18** = **196 test** — OK.

Yangi 18 test: buffer yig'ishi, `tail` chegarasi, telefon yopilishi,
ball `4/1.75` tegilmasligi, `install()` takrorlanmasligi, `clear`;
kuzatuv yoqish/o'chirish, daqiqa chegarasi (1–120), muddat tugashi,
karta matni (o'tgan / chegarada / emoji), HTML escape, qisqartirish.

---

## 29. Diagnostika faylidan topilgan 3 xato

Fayl: `diagnostika-20261025-1231.txt` (34 qator).

### 29.1 Tizim to'xtatilgan (eng muhim)

Har bir xabar shu bosqichda to'xtagan:

```
[SCAN] skip owner=… chat=…: system: tizim admin tomonidan ⏸ to'xtatilgan
```

Ya'ni skaner ishlayapti (xabarlar kelmoqda), lekin **umumiy o'chirgich
o'chirilgan** — hech kimga xabar ketmaydi. Yechim: **⏸/▶️ Tizim
(hammaga)** tugmasi.

Endi bu holat ikki joyda ko'rinadi: menyudagi holat matnida
(`⏸ TIZIM TO'XTATILGAN …`) va diagnostika faylining eng boshida
(`tizim: 🔴 TO'XTATILGAN`).

### 29.2 Har bir xabar IKKI marta skanerlanardi

Logda har bir yozuv ikki nusxada:

```
12:30:43 [SESSION] owner=… client ishga tushdi
12:30:43 [SESSION] owner=… client ishga tushdi
12:30:44 [SCAN] skip … system
12:30:44 [SCAN] skip … system
```

Sabab: `start_user_client()` da `_clients` ga yozish **ulanishdan keyin**
bo'ladi. `bot.main()` dagi `sync_now()` va sync loop birinchi aylanishi
bir vaqtda ishga tushib, ikkalasi ham "client yo'q" deb ko'rgan va
**ikkita Telethon klienti** yaratilgan. Natijada: ikki ulanish, ikki
handler, har xabar ikki marta ishlanadi — ya'ni **egasiga bildirishnoma
ikki marta** ketishi mumkin.

Tuzatish: `_starting` to'plami — sessiya ko'tarilayotganda ikkinchi
chaqiruv darhol qaytadi (`try/finally` bilan tozalanadi).

### 29.3 Redakt qatorlarni birlashtirib yuborardi

Logda shunday qator chiqqan:

```
… is handled. Duration 288 ms by bot id=[raqam].10 12:31:00 I scanner_manager: [SCAN] …
```

Sabab: telefon regexida `\s` bor edi — u **yangi qatorni ham** yutgan,
ikki qator bitta bo'lib qolgan. Tuzatish: `[ \t\d\-()]` (yangi qatorsiz)
+ oldida `=` yoki harf bo'lsa tegilmaydi — endi `owner=777`,
`chat=-1001234567890`, `bot id=123456789` kabi texnik ID lar saqlanadi,
faqat haqiqiy telefon raqamlar `[raqam]` bo'ladi.

### 29.4 Testlar

59 + 53 + 23 + 36 + 7 + **24** = **202 test** — OK.

Yangi testlar: redakt qatorlarni buzmasligi, texnik ID lar saqlanishi,
telefon yopilishi, sessiya bir marta ko'tarilishi (uch parallel chaqiruv),
xato bo'lsa `_starting` tozalanishi, mavjud client qayta ko'tarilmasligi.

---

## 30. Ikkinchi diagnostika: tizim hanuz pauzada

Fayl: `diagnostika-20261025-132530.txt` (185 ta log qatori; 13:23–13:25).

### Holat

Diagnostika sarlavhasi muammoni aniq ko'rsatadi:

```
tizim: 🔴 TO'XTATILGAN (Tizim tugmasi)
kalitlar: 74 ta · chegara: 1.75 · rejim: weight
faol guruhlar: 1 ta · sessiyalar: 1 ta
kuzatuv: — · ko'rilgan xabar: 66
```

**Bot yangilangan va ishlayapti, lekin global tizim tugmasi hanuz pauzada.**
66 ta event kelgan — sessiya onlayn. Shu logda bir xil `event` lar juft
bo'lib takrorlanmaydi, ikkinchi klient belgisi ko'rinmaydi. 13:25:02 dagi
uzilishdan keyingi bitta qayta ulanish odatiy reconnect ko'rinishida;
13:25:02 da bitta `[SESSION] ... client ishga tushdi` yozuvi bor.

Skanerni ishga tushirish uchun admin menyudagi **⏸/▶️ Tizim (hammaga)**
tugmasini bosing, yoki `/start` dan keyin chiqadigan yangi **▶️ Tizimni
yoqish** inline tugmasini bosing. Bu faqat global pauzani yechadi; egasi
va guruhlar uchun alohida yoqilgan holat ham talab qilinadi.

### Guruh ro'yxati

13:25:13 da bitta xabar `group: bu guruh sizning faol guruhlaringiz
ro'yxatida yo'q` deb to'xtagan. Sarlavhada **faol guruhlar: 1 ta** —
demak, bot faqat bitta yoqilgan guruhni taniydi. Boshqa guruhni ham
skanerlash kutilsa, uni **📋 Guruhlarim** bo'limida ro'yxatga qo'shib,
faol holatga o'tkazing. Logdagi bu guruh to'xtashi global `system`
tekshiruvidan oldin bo'lishi mumkin; asosiy joriy to'siq baribir qizil
global holat.

### Qo'shilgan yaxshilashlar

- `/start` dagi admin javobida pauza bo'lsa, alohida **▶️ Tizimni yoqish**
tugmasi chiqadi; bosilganda global `is_active` yoqiladi va bot holatni
javob qiladi.
- Takroriy `skip` sababi har daqiqada bir marta yoziladi; oraliqdagi
son keyingi yozuvda ko'rsatiladi. `system` sababi barcha chatlar uchun
bitta hisoblagich, guruh kabi boshqa sabablar chat bo'yicha alohida.
- Hisoblagich xotirasi 2,000 kalit bilan chegaralangan.

### Tekshiruv

Matcher 59 + weights 53 + feedback 23 + review 36 + export 7 + diag 27
= **205 test — OK**.

---

## 31. Nazorat buyruqlari tugmalarga almashtirildi

Skrinshotdagi `REVIEW_HELP` matnida `/nazorat`, `/nazorat_ochir` va
`/nazorat_stat` buyruqlari ko'rsatilgan edi. Endi xabar ostida inline
boshqaruv tugmalari bor:

- **🔍 Slaydni ochish** — navbat slaydini yangilaydi;
- **📊 Statistika** — baholash statistikasini ko'rsatadi;
- **🔕 Nazoratni o'chirish** — nazoratni o'chiradi, ochiq slaydni holat
  xabariga almashtiradi va undagi eski baholash tugmalarini olib tashlaydi;
- **❌ Yopish** — yordam xabarini yopadi.

`🛠 Admin panel → 🎓 Nazorat (baholash)` nazoratni ochish tugmasi bo'lib
qoladi. Eski slash-buyruqlar moslik uchun ishlashda davom etadi, lekin
foydalanuvchiga ko'rsatiladigan yordam matnidan olib tashlandi.

### Tekshiruv

Matcher 59 + weights 53 + feedback 23 + review **38** + export 7 + diag
27 = **207 test — OK**. Yangi testlar tugmalar ko'rsatilishi, slayd va
baholash tugmalari nazorat o'chirilganda tozalanishi, hamda stop callback
ishlashini tekshiradi.

---

## 32. 13:57 diagnostika: nazorat API timeoutlari

Fayl: `diagnostika-20261025-135751.txt` (169 log qatori; jarayon
13:56:06 da qayta ishga tushgan).

### Skaner holati

```
tizim: 🟢 yoniq
kalitlar: 74 ta · chegara: 1.75 · rejim: weight
faol guruhlar: 1 ta · sessiyalar: 1 ta
nazorat: jami 3 · ⏳ 0 · ⚡ 0
```

Skaner va sessiya ishlayapti; **97 ta xabar** ko'rilgan. Bu oraliqda
`[SCAN] topildi` yoki `[SCAN] sent` yo'q: ko'ringan xabarlarning aksari
faol ro'yxatga kiritilmagan guruhlardan. Kerakli guruhlarni 📋 Guruhlarim
orqali faollashtirish kerak.

### Topilgan nosozlik

Nazorat slaydi uchun Telegram Bot API uch marta timeout bo'lgan:

- `sendMessage`: 13:56:43 va 13:57:22;
- `editMessageText`: 13:57:38.

So'rovlar 15 sekundlik kutishdan keyin tugagan, mos aiogram update'lari
15–25 sekund davom etgan. Bu nazorat xabarini ochish/yangilashni
sekinlashtirishi mumkin.

### Tuzatish

- Har so'rovda yangi HTTP sessiya ochish o'rniga birta qayta ishlatiladigan
  sessiya qo'shildi.
- Timeoutlar: umumiy 4.5 s, ulanish 2 s; tarmoq xatosida `edit*` xavfsiz
  ravishda yana bir marta urinadi.
- `sendMessage` timeoutdan sonra retry qilinmaydi — Telegram xabarni
  yetkazgan чоғда javob yo'qolsa dublikat yuborish xavfi bor.
- Tarmoq vaqtincha uzilsa, `editMessageText` muvaffaqiyatsiz deb
  hisoblab yangi slayd yuborilmaydi.
- Telegram «message is not modified» degan javobni xato emas,
  muvaffaqiyat deb qabul qiladi; bu o'zgarmagan slayd uchun dublikat
  `sendMessage` yuborilishining oldini oladi.
- Nazorat oynasini qayta ochish `force_new` o'rniga mavjud slaydni tahrirlaydi.
- Bot yopilganda doimiy HTTP sessiya to'g'ri yopiladi.

### Tekshiruv

Matcher 59 + weights 53 + feedback 23 + review 44 + export 7 + diag 27
= **213 test — OK**.

---

## 33. Amaldagi 74 kalit va 315 xabar bo'yicha qayta o'lchov

Kiritilgan fayl: `kalit-sozlar (1).txt` (74 yozuv; so'nggi qatorda
newline yo'q, shuning uchun `wc -l` 73 ko'rsatadi).

- **42 musbat, 32 manfiy**; 52 ta bir so'zli yozuv, 22 ta ibora.
- 74 ta yozuvning barchasi alohida sinov matnida topildi; `jonat` yozuvi
  canonical shaklga `jo'nat` bo'lib tushadi. Bu juftlik alohida ro'yxat
  yozuvlari bo'lsa ham matcher bir xabarga vaznni bir marta hisoblaydi.
- Joriy chegara **2.0**. Mavjud 315 anonim etiketli xabarda 1.75 va 2.0
  natijalari bir xil chiqdi — datasetda ball 1.75–2.0 oralig'ida bo'lgan
  xabar yo'q.

| Toifa | O'tdi | Foiz |
|---|---:|---:|
| Mijoz | 85 / 97 | 87.6% |
| Haydovchi | 0 / 101 | 0% noto'g'ri o'tdi |
| Boshqa | 14 / 117 | 12.0% noto'g'ri o'tdi |

Boshlang'ich `kalit-sozlar-tavsiya.txt` bilan mijoz 86/97 (88.7%),
haydovchi 0/101 va boshqa 14/117 bo'lgan. Faqat bitta dataset qarori
almashgan: **“odam kerak emas, posilka”** 2.0 ball bilan o'tishdan
0.75 ball bilan to'xtashga o'tgan; musbat `odam`/`kerak` vaznlari pasaygan
va `kerak emas` manfiy iborasi hisoblangan. Namuna yorlig'ini tekshirish
kerak.

Sinovdagi ko'zga tashlangan xato misollar:

- mijoz, o'tmadi: `2 ta sumka bilan ketamiz`, `meni olib keting,
  Toshkentdan Sirdaryoga`, `kimda bo'sh joy bor`, `ichki reys kerak ...`;
- boshqa, o'tdi: `admin bormi`, `ish qidiraman, haydovchi bo'lib`,
  `yoqilg'i narxi qancha`, `kim yordam bera oladi`, `manzilni yuboraman`.

Bularni yangi so'z qo'shishdan oldin admin **✅/❌/⏭** bilan baholashi
kerak; hozircha vaznlar va so'zlar o'zgartirilmadi.

### Jonli diagnostika

`diagnostika-20261025-143606.txt`: tizim yoniq, threshold 2, bitta
sessiya va bitta faol guruh, 1,344 event. Log buferining oxirgi 300
qatorida 251 event va 30 skip-summary bor, keyword `topildi/sent`
chiqishi yo'q; ko'ringan skiplar guruh ro'yxati bosqichida. Demak shu
vaqt oralig'ida faol guruhdan real scoringni tekshirib bo'lmadi. API
va timeout xatosi ko'rinmadi.

### Eksport/import tuzatishi

Eski eksport `+2 kim bor` deb chiqargan. Import parseri buni `kim` va
`bor` kabi alohida kalitlarga ajratishi mumkin edi. Endi ko'p so'zli
yozuvlar `+2: kim bor` ko'rinishida eksport qilinadi; parser uni aynan
bitta ibora sifatida qayta oladi. Eski attachmentni qayta import
qilmang; yangi format deploy qilingandan keyin yangi nusxa oling.

### Tekshiruv

Matcher 59 + weights 53 + feedback 23 + review 44 + export 8 + diag 27
= **214 test — OK**. Merge hamda replace importida ijobiy ko'p so'zli
iboralar saqlanishi regressiya testi bilan tekshirildi.

---

## 34. Bildirishnomada «kamida 0 ta» ko'rinishi

Admin yuborgan amaldagi bildirishnoma matnida vazn rejimida
`🔔 Shart: kamida 0 ta — bajarildi` chiqqan. Bu **skoring xatosi emas**:
`Verdict.required` vazn rejimida ishlatilmaydi va default 0 bo'lib qoladi;
bildirishnoma formatlagichi esa count rejimidagi matnni qo'llagan.

Tuzatish: vazn rejimida endi `⚖️ Ball: X / chegara — o'tdi` va mos
musbat/manfiy vaznlar ko'rsatiladi. Count rejimida esa eski `kamida N ta`
sharti qoladi. Notification builder-ru testlar ikkala rejimni qoplaydi.

Pasted alertda `bor`, `toshkentga` mos kalit sifatida ko'rsatilgan,
lekin yuborilgan avvalgi eksportda bu ikkitasi alohida kalit sifatida
ko'rinmadi. Ishlayotgan baza eksportdan keyin o'zgargan bo'lishi mumkin;
keyingi deploydan so'ng yangi eksport bilan mosligini solishtirish kerak.

Testlar: 59 + 53 + 23 + 44 + 8 + 27 + 3 = **217 test — OK**.

---

## 35. Mustaqil, o'zakdosh kalitlar va ball ustuvorligi

Admin tanlagan qoida bo'yicha o'zakka o'xshab boshlanadigan mustaqil
so'zlar (`bor` / `borm` kabi) endi faqat prefiks bo'lgani uchun rad
etilmaydi; har biri alohida kalit va alohida vazn bilan saqlanadi.

Bitta xabar tokeni bir nechta shunday kalitga mos tushsa, aniq yozilgan
kalit, yoki token ichida to'liq qatnashgan eng uzun kalit ustun bo'ladi.
Masalan, `bor +1` va `borm +2` bo'lsa:

- `borm` xabar tokeni → faqat `borm`ning +2 bali;
- `bormo` → `borm` mavjud bo'lsa `borm`ning bali, u bo'lmasa `bor`ning
  bali;
- `bor borm` → ikki alohida token bo'lgani uchun ikkala kalitning balli.

Bu ustuvorlik count rejimida ham qo'llanadi. Ko'p so'zli iboralar
alohida kalitligicha qoladi. Testlar kalit kiritish, o'zak/aniq kalit
ustuvorligi, alohida tokenlar, aynan shakl va musbat/manfiy ustuvorlikni
tekshiradi.

Tekshiruv: matcher 62 + weights 59 + feedback 23 + review 44 + export 8
+ diagnostics 27 + notifier 3 = **226 test — OK**; `compileall` va
`git diff --check` ham muvaffaqiyatli.

---

## 36. O'rganuvchi navbat o'chirildi

Admin tanlovi: **faqat o'rganuvchi navbat/slaydni o'chirish**. Har bir
bildirishnoma yuborilgandan keyingi anonim matn nusxasi hamda weight
rejimidagi chegaraga yaqin xabarlarning navbatga yozilishi to'xtatildi.
`🎓 Nazorat (baholash)` menyusi va `/nazorat*` handlerlari olib tashlandi.
Yangilanish paytida avvalgi versiyadan qolgan slayd bo'lsa, bir marta
bekor qilinadi.

Asosiy skaner, kalitlar va vaznlar o'zgarishsiz. Bildirishnomadagi
foydalanuvchi feedback tugmalari/statistikasi qoladi; foydalanuvchining
✅/❌ vazn o'zgartirmaydi, adminning bahosi esa oldingi qoida bo'yicha
vaznni sozlashi mumkin. Eski anonim o'rganuvchi yozuvlari o'chirilmadi;
ular uchun yangi nusxa qo'shilmaydi. Bildirishnoma feedbacki uchun
saqlanadigan topilgan-kalit ro'yxati alohida qoladi.

Sekinlik: olib tashlangan enqueue chaqiruvlari fon tasklari edi, shu
sabab skanerlashni API javobigacha kutdirmasdi; lekin qo'shimcha DB/API
ishlarini bajarardi. Oldingi mavjud diagnostikadagi event ishlovi
213–358 ms edi; bu **joriy server o'lchovi emas**. Hozirgi ishga tushgan
server tezligini yangi diagnostikasiz tasdiqlab bo'lmaydi.

Tekshiruv: matcher 62 + weights 59 + feedback 23 + bu o'chirish bo'yicha
6 + export 8 + diagnostics 27 + notifier 3 = **188 test — OK**;
`compileall` va `git diff --check` ham muvaffaqiyatli.
