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

## 5. Emoji filtri haqida qaror

O'lchov shuni ko'rsatdi: **emoji qat'iy bloklash shart emas**. D variantida
emoji jarimasi (−2.5) natijani o'zgartirmadi (44/45, 0/30, 1/20 — o'sha).

**Tavsiya:** emoji qat'iy blokdan **vaznga** o'tsin (`−1.5`), chunki:
- mijoz ham emoji ishlatadi (`🙏`, `📞`) → hozir bunday xabar butunlay yo'qoladi;
- haydovchi emojisiz yozsa → hozir o'tib ketadi;
- vaznli modelda emoji bitta belgi bo'lib qoladi, hukm chiqarmaydi.

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
| 5 | Emoji | qat'iy blok → **−1.5 vazn** (yoki o'chirish) |
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
2. **Emoji vazni** −1.5 to'g'rimi yoki umuman olib tashlansinmi?
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
