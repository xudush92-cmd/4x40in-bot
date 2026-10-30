# O'qitish to'plami — qo'llanma

Bot "aqlliroq" bo'lishi uchun **yorliqlangan xabarlar** kerak. Bu papkada
o'sha to'plamning boshlang'ich qismi va uni o'lchaydigan skript bor.

| Fayl | Nima |
|---|---|
| `qitish-matnlari.tsv` | **315 xabar**: 97 mijoz, 101 haydovchi, 117 boshqa |
| `baholash.py` | to'plamni joriy kalit so'zlar ro'yxati bilan o'lchaydi |

## 1. Format

Har qatorda: `yorliq<TAB>matn`. Yorliq — uchtadan biri:

| Yorliq | Ma'nosi | Bot nima qilishi kerak |
|---|---|---|
| `mijoz` | transport/posilka **so'rayotgan** odam | xabar yuboriladi |
| `haydovchi` | reys/joy taklif qilayotgan haydovchi | **blok** |
| `boshqa` | suhbat, savol-javob, reklama, ish e'loni | **blok** |

Nima uchun `boshqa` alohida: bot uchun "haydovchi" va "aloqasiz" bir xil
natija beradi (blok), lekin modelni o'qitishda ular **boshqa-boshqa
guruh** — aks holda model "hamma narsa haydovchi" degan xulosaga keladi.

Muhim qaror: **ish e'lonlari (`ishga odam kerak`, `ish qidiraman`,
`rezyume`) — `boshqa`**, chunki ular transport so'rovi emas.

## 2. Hozirgi o'lchov

`python3 o_qitish/baholash.py` (chegara 1.75, ro'yxat 76 yozuv):

```
mijoz       97 xabar -> 83 topildi   85.6%
haydovchi  101 xabar ->  0 o'tdi      0.0%   (yaxshi)
boshqa     117 xabar -> 14 o'tdi     12.0%   (xato)
```

Ya'ni: haydovchi e'loni **hech biri** o'tmayapti, mijozning ~86% topilyapti.
Batafsil: `--xato 40` bilan hamma xatoni va qaysi kalit so'z sabab
bo'lganini ko'rsatadi.

> **Halol eslatma.** Bu 315 xabarni men yozdim — real guruhdan olinmagan.
> Shuning uchun bu to'plam **regressiya to'plami** sifatida yaxshi
> (bir xil o'lchov har safar takrorlanadi), lekin **real hayotdagi
> aniqlikni to'liq ko'rsatmaydi**. Yakuniy haqiqat — guruhdagi haqiqiy
> xabarlar. Shu sababli 3-bo'limdagi yig'ish ishi baribir kerak.

## 3. Real guruhdan nima yig'ish kerak

Telegram'da guruh ichida qidiruv (🔍) bilan quyidagi so'zlarni terib,
chiqqan xabarlarni ko'chirib oling. Har xil odam yozganini olish muhim.

| Nima izlash | Nima chiqadi | Yorliq |
|---|---|---|
| `kerak`, `kerek` | "mashina kerak", "posilka yuborishim kerak" | `mijoz` |
| `bormi`, `bormikin` | "ertaga bormi?", "joy bormi?" | `mijoz` (yoki `haydovchi` — matnga qarab) |
| `kim ketadi`, `kim olib ketadi` | mijoz savoli | `mijoz` |
| `joy bor`, `bo'sh joy`, `chiqdim`, `reys` | haydovchi e'loni | `haydovchi` |
| 🚖 🚗 🚕 ✅ 📞 belgilari | deyarli doim haydovchi | `haydovchi` |
| `posilka`, `yuk`, `quti` | ikkisi ham bo'ladi — **matnni o'qing** | `mijoz` / `haydovchi` |
| `rahmat`, `assalom`, `admin`, `narx` | suhbat va shovqin | `boshqa` |
| `ishga odam kerak`, `qidiraman` | ish e'loni | `boshqa` |

Maqsad: **300–500 real xabar**. Har yorliqdan kamida ~100 tadan bo'lsin,
aks holda model bir tomonga og'ib ketadi.

**Maxfiylik (qat'iy):**

* telefon raqamlarini o'chirib tashlang yoki `90 000 00 00` ga almashtiring;
* ism-familiya, manzil, guruh nomini yozmang;
* hech kimning shaxsiy ma'lumoti boshqa foydalanuvchiga o'tmasligi kerak —
  bu to'plam faqat o'qitish uchun va repoda saqlanadi, shuning uchun
  **anonim bo'lishi shart**.

## 4. Qanday qo'shish

1. `qitish-matnlari.tsv` ga yangi qator qo'shing (TAB bilan ajratib).
2. Tekshiring:

```bash
python3 o_qitish/baholash.py            # takror xabar bo'lsa xato beradi
python3 o_qitish/baholash.py --threshold 2.5
```

Faqat **qo'shish** — mavjud qatorni o'chirmang: shunda o'lchov avvalgi
natija bilan solishtirishga yaroqli bo'lib qoladi.

## 5. Nega bu to'plam kerak

Kalit so'zlar modeli (1-daraja) kontekstni tushunmaydi. To'plamdagi
xatolarga qarab ko'rinadigan chegaralar:

| Xabar | Ball | Muammo |
|---|---|---|
| `2 ta sumka bilan ketamiz` | 0.00 | kalit so'z yo'q — faqat model topa oladi |
| `mashina kerak, qo'ng'iroq qiling` | 0.50 | `qo'ng'iroq qiling` (−3.5) mijozi ham aytadi |
| `kimda bo'sh joy bor` | −9.00 | bitta ibora uch marta manfiy hisoblanyapti |
| `admin bormi` | 4.50 | `bormi` + `bormikin` ikkalasi mos tushdi |

Oxirgi ikkitasi — **kod darajasidagi xato**, so'zlar emas (bir-birini
qoplaydigan mosliklar qo'shilib ketyapti). Ular tuzatilsa, o'lchov ham
yaxshilanadi.

Keyingi qadam — **2-daraja**: belgi n-gramma + Naive Bayes (sof Python,
8 GB RAM/CPU da ishlaydi). U aynan `2 ta sumka bilan ketamiz` kabi
kalit so'zsiz xabarlarni o'rganadi. Buning uchun aynan shu TSV formatidagi
300–500 yorliq yetarli.
