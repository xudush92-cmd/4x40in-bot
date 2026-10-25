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
