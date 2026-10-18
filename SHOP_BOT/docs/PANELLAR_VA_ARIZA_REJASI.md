# Boshqaruv panellari, limitlar va sotuvchilik arizasi — loyiha rejasi

> **ARXIV (UX-0/1/2/3):** Quyidagi eski ariza sharti, kanal paneli, guruh/toifa intervali va kunlik kvota oqimlari joriy kodga tatbiq etilmaydi. Hozir pullik tarifni oddiy foydalanuvchi ham oldindan arizasiz oladi; bot faqat guruhlar uchun. Amaldagi yo‘l: [YANGI_ELON_OQIMI.md](YANGI_ELON_OQIMI.md) va [ADMIN_QOLLANMA.md](ADMIN_QOLLANMA.md). Tarixiy qarorlar o‘chirilmay, oldingi bosqichlarni tushunish uchun saqlangan.


**Holat:** UX-0 rejasi, limitlar ×10/rolli yo‘riqnoma va **UX-1 admin navigatsiyasi** joriy qilindi. Foydalanuvchi 2026-10-16da UX-1/2/3ning barchasiga ruxsat berdi. **UX-2 sotuvchilik arizasi** kod va SQLite/soxta Telegram sinovlarida bajarildi; UX-3 kabineti keyingi ish. Jonli Replit/deploy bu ruxsatga kirmaydi.

**Doira:** `SHOP_BOT/`; `AVTO_BOT/`, `main` va jonli Replit muhitiga tegilmaydi.

**Qaror:** oddiy `/start` ochiq qoladi. **Faqat sotuvchilik arizasi** admin tasdig‘idan o‘tadi. Tarif, chek va e’lon bo‘yicha mavjud alohida tekshiruvlar o‘z kuchida qoladi.

## 1. UX-0dagi boshlang‘ich holat va chalkashliklar (tarixiy audit)

- `app/keyboards/admin.py`da 19 ta bo‘lim bir darajada turadi: guruhlar, posbon, tozalovchi, sanoqchi va sozlamalar turli joyda. Global funksiya o‘chirgichi, bir guruh o‘chirgichi va o‘sha guruhning «sinov/jonli» rejimi o‘rtasidagi farqni topish qiyin.
- `app/middlewares/user_context.py` yangi Telegram foydalanuvchisini `users`ga avtomatik yozadi; bu **sotuvchi sifatida tasdiqlanish emas**. `app/handlers/common.py`dagi `/start` oddiy foydalanuvchiga yordam va qisqa foydalanish yo‘riqnomasini taklif qiladi. Sotuvchini admin hozir `app/handlers/admin/sellers.py` orqali ID va kontakt ma’lumotlari bilan qo‘lda qo‘shadi.
- `SellerStatus.PENDING` (`app/constants.py`) **admin arizasi kutilmoqda** degani emas: sotuvchi yozuvi bor, lekin hali tarifi yo‘q. To‘lovning `PENDING`i va e’lonning `PENDING`i ham boshqa oqimlardir. Ariza uchun alohida holat zarur.
- Sotuvchi panelida e’lonlar, tarif, to‘lov allaqachon bor (`app/handlers/seller/`, `app/keyboards/seller_panel.py`), biroq har biriga alohida kiriladi: birinchi ekranda «nima qoldi / nima kutilyapti / keyin nima qilish kerak» aniq jamlanmagan. `/start`dagi sotuvchi holatini tekshirishda `BLOCKED` va `DELETED` kabi holatlar izchil ko‘rilishi kerak; bu hali amalga oshirilmagan UX taklifi; limit/yo‘riqnoma bosqichi sotuvchilik arizasi oqimini o‘zgartirmaydi.
- Majburiy **N kishi qo‘shish** (`sanoqchi`) va majburiy **kanalga a’zo bo‘lish** (`RequiredChannel`) alohida shart. Ular sotuvchi referal bonusidan ham, posbonning spam qoidasidan ham mustaqil bo‘lishi kerak.

## 2. Yangi admin navigatsiyasi (ekran sxemasi)

Bosh ekranda avval **harakat talab qiladigan ishlar**, keyin vazifalar bo‘yicha 5 bo‘lim. Bo‘limni ochish ortiqcha ichma-ich menyu bermasligi uchun har kartada «orqaga», «bosh sahifa» va «yangilash» bo‘ladi. «📥 Navbatlar» raqamlari faqat aniq qaror kutayotgan ishlar uchun (ariza, moderatsiya, chek); xatolar va umumiy foydalanuvchilar soni «yangi navbat» deb atalmasin.

```text
🛠 Boshqaruv
  📥 Navbatlar: 🛒 arizalar (N) | 📢 moderatsiya (N) | 🧾 cheklar (N)
  👥 Guruhlar       → guruh tanlash → shu guruh kartasi
  🛒 Savdo          → sotuvchilik arizalari | sotuvchilar | tariflar | to‘lovlar | referal
  📢 Kontent        → e’lonlar | moderatsiya | toifalar | broadcast
  📊 Nazorat        → statistika | foydalanuvchilar | xatolar | harakatlar tarixi
  ⚙️ Tizim          → global holat | umumiy kanallar | bot matnlari | adminlar*
  [🔄 Yangilash]
  * «Adminlar» faqat super-admin uchun.

👥 Guruhlar → [guruh kartasi]
  📊 Holat: bot huquqi, guruh pauzasi, keyingi post, faol funksiyalar
  📢 Joylash/toifalar: interval, ±jitter, kunlik post, tinch soatlar;
                      guruhga ulangan toifalar va alohida interval
  🛡 Posbon: spam/havola/forward/taqiqlangan so‘zlar, ogohlantirish/jazo
  🧹 Tozalovchi: xabar turlari, nechta e’lon qoldirish, o‘chirish muddati
  🧮 N kishi sharti: N, minimal qolish, kunlik hisob, taklif havolasi,
                    manbalar, SOFT/HARD, a’zo hisobi va tuzatishlar
  📣 Kanal a’zoligi: shu guruh kanallari + faqat O‘QISH uchun global kanallar;
                    shu guruhda «kanal sharti» o‘chirgichi
  🔑 Istisnolar: guruh/global ruxsatlar, kim uchun qaysi qoida ishlamasligi
  🔍 Nega ishlamayapti?: global → guruh → qoida → sinov/jonli → bot huquqi
  ⏸ Guruh pauzasi (alohida tasdiq)

⚙️ Tizim → Global holat
  🛑 Favqulodda to‘xtatish / 🔧 texnik rejim (yuqori xavf)
  📢 Joylash holati (hozircha faqat ko‘rish; yangi toggle alohida ruxsat bilan)
  🛡 Posbon | 🧹 Tozalovchi | 🧮 Sanoqchi | 📣 Broadcast
     global kalitlari (guruhlarning saqlangan qiymatini o‘zgartirmaydi)
  ℹ️ Defaultlar va yordam aloqasi / boshqa texnik parametrlar
```

**Qoidalar:** «Guruh kartasi» har doim shu `group_id`ga bog‘liq bo‘ladi; boshqa guruh qoidalarini tasodifan tahrirlamaydi. Matritsada bir nechta guruhni yoqish qulayligi saqlanadi, lekin posbon/tozalovchi/sanoqchining **har bir guruh uchun batafsil sozlamalari** kartada qoladi. Global o‘chirgich mahalliy qiymatlarni reset qilmaydi. Yoqilganda avvalgi sinov (`dry_run`) va alohida jonli tasdiq xavfsizligi saqlanadi. Mavjud `app/handlers/admin/groups.py`, `policy.py`, `counter.py` servislarini takror yozish emas, ularning oldiga qulay kirish joyini qo‘yish rejalashtiriladi.

### Guruh ekranining namunasi

```text
👥 Toshkent savdo — holat
Bot: ✅ admin (huquqlar yetarli)       Guruh: 🟢 faol
Joylash: 🟢 · har 30 daq · kuniga 50 tagacha
Posbon: 🧪 sinov (global 🟢, guruh 🟢)
Tozalovchi: 🔴 o‘chiq (faqat shu guruh)
N kishi: 🧪 sinov · N=3 · kunlik 20 · kanal sharti: 🔴

[📢 Joylash] [🛡 Posbon] [🧹 Tozalovchi]
[🧮 N kishi] [📣 Kanal a’zoligi] [🔑 Istisnolar]
[🔍 Nega ishlamayapti?] [⏸ Guruhni pauza qilish]
[◀️ Guruhlar] [🏠 Boshqaruv]
```

Diagnostika sababni aniq yozishi kerak: «global o‘chiq», «shu guruh o‘chiq», «sinovda (jazo yo‘q)», «botga o‘chirish/mute huquqi yetishmaydi», «kanal belgilangani yo‘q», «kanaldagi a’zolikni tekshirib bo‘lmadi». «Faol» belgisi *haqiqiy jazo ishlaydi* degan noto‘g‘ri taassurot bermasligi kerak. Telegram huquqlarini qayta tekshirish alohida tugma bilan, mavjud huquq tekshiruvi orqali bajariladi. Tekshiruv bo‘lmasa noma’lum natija «hammasi joyida» sifatida ko‘rsatilmaydi.

## 3. Limitlar auditi va ekranda joylashuvi

UX-0 tuzilgan paytdagi sonlar keyingi **alohida ruxsat** bilan o‘zgardi. Quyidagi **joriy kod** ustuni botdagi amaldagi yuqori chegaralar: faqat **maksimumlar** ko‘tarildi, bazadagi saqlangan qiymatlar, defaultlar, qoidalar, guruh konteksti va oldingi ariza/menyu oqimlari ko‘chirilmadi. «Taklif» ustuni — hali amalga oshirilmagan kelajak UX joylashuvi.

| Soha / maydon | Joriy koddagi oraliq / izoh (qavsda UX-0dagi eski maksimum) | Kelajakdagi aniq joy |
|---|---|---|
| Guruh va toifa post intervali | 1–14400 daq (1440); default guruh 30 daq | `Guruh → Joylash`; toifaning alohida override'i saqlanadi |
| Guruh kunlik post / jitter | 1–5000 xabar/kun (500), default 50; jitter **0–30% o‘zgarmadi** | `Guruh → Joylash`; tezlikni oshirish emas, admin belgilaydigan kvota |
| Tinch soatlar | Vaqt oralig‘i; guruh bo‘yicha, o‘zgarmadi | `Guruh → Joylash` |
| Posbon ogohlantirish / mute / oyna | 1–200 ta (20); 1–100800 daq (10080); 1–7200 soat (720) | `Guruh → Posbon`, har guruhning sinov/jonli holati saqlanadi |
| Posbon so‘z/domen ro‘yxati | ko‘pi bilan **300 tadan** (30); so‘z 2–50 belgi o‘zgarmadi | `Guruh → Posbon → Ro‘yxat` |
| Tozalovchi nusxalar / kechikish | 1–200 ta (20); 0–36000 soniya (3600) | `Guruh → Tozalovchi`, 0 — darhol |
| N kishi / minimal qolish | 0–1000 (100) / 0–100800 daq (10080); yangi guruh default N=3, 10 daq | `Guruh → N kishi`; N=0 kanal shartini o‘chirmaydi |
| Sanoqchi kunlik hisob / bitta havola limiti | 1–1000 / 1–1000 (100 / 100); default har ikkisida 20 | `Guruh → N kishi`, post kvotasidan alohida |
| Sanoqchi qo‘lda hisob tuzatish | har amal −10000…+10000 (±1000), sabab 3–255 belgi | `Guruh → N kishi → A’zo hisobi`, audit yoziladi |
| Majburiy kanal | global va guruh kanallari, har guruh switchi, o‘zgarmadi | `Guruh → Kanal a’zoligi`; kanal admin huquqi zarur |
| Istisno muddati | 1–3650 kun (365), yoki muddatsiz | `Guruh → Istisnolar`, global/guruh alohida |
| Tarif muddati / e’lon kvotasi | 1–36500 kun (3650) / 1–10000 e’lon (1000) | `Savdo → Tariflar` |
| Tarif rasm limiti | **1–10 rasm/e’lon, o‘zgarmadi**; Telegram albom limiti | `Savdo → Tariflar`; boshqa yuborish mexanizmisiz oshirib bo‘lmaydi |
| Tarif narxi; e’lon narxi | 0–9 999 999 990 so‘m (999 999 999); e’lon narxi 0–1 000 000 000 000 so‘m o‘zgarmadi | `Savdo → Tariflar` va e’lon ustasi; narx `Numeric(12,2)` va chek/referal bilan sinxron |
| E’lon/profil matn uzunliklari | sarlavha 3–120, tavsif 800, sotuvchi nomi 64, telefon 32, kontakt 64 belgi; **texnik DB/Telegram chegarasi, o‘zgarmadi** | Sotuvchi arizasi va e’lon ustasi |
| Qo‘lda beriladigan obuna e’lon limiti | 0–1000000 (100000); ishlatilgan son saqlanadi | `Savdo → Sotuvchilar → Obuna`, tarif kvotasidan boshqa amal |
| Referal kunlik bonus / qiymati | 1–500/kun (50); kun 1–3650 (365); balans 1000–10000000 so‘m (1 mln); **chegirma 1–50% o‘zgarmadi** | `Savdo → Referal`; sanoqchidan mustaqil va boshlanishida o‘chiq |
| Referal minimal chek | 0–9 999 999 990 so‘m (1 mlrd); sotib olinadigan eng katta tarifdan oshmasin | `Savdo → Referal` |
| Broadcast tezligi | **1–25 xabar/soniya o‘zgarmadi**, xavfsizlik/Telegram cheklovi | `Kontent → Broadcast`, tasdiq saqlanadi |
| Guruh post rate-limiteri | eng kam **2 soniya o‘zgarmadi**; paneldagi interval bilan bir xil emas | `Guruh → Joylash`da tizim cheklovi sifatida tushuntiriladi |
| Oddiy ro‘yxat sahifasi | guruh/sotuvchi/e’lon 6 tadan; toifa/tarif 8 tadan; **biznes limiti emas** | UXda pagination qayta ko‘rib chiqilishi mumkin |

Saqlanadigan, lekin paneldan bevosita tahrirlanmaydigan defaultlar (`settings_service.DEFAULTS`): `min_interval_sec=60`, `default_max_ads=5`, `default_max_photos=3`, `subscription_reminder_days=3`, `subscription_grace_days=0`, `log_retention_days=90` (oxirgisi panelda faqat ko‘rinadi). `posting_enabled_global` va `welcome_enabled_global` uchun yangi toggle qo‘shilmagan. Chegirma 50%dan oshsa manfiy chek xavfi bor; broadcast tezligi/rasm limiti esa Telegram bilan cheklangan. Tarif narxining ×10 chegarasi va referal minimal cheki DB sig‘imi va foydali chek qiymati hisobga olinib xavfsiz yaqinlashtirilgan; shuning uchun 10 000 000 000 emas, **9 999 999 990**. Baza sxemasi o‘zgarmagan, migratsiya kerak emas; shaxsiy `/start` va referal birinchi kirish qoidasi saqlangan.

Manbalar: `app/constants.py`, `app/services/group_service.py`, `group_policy_service.py`, `counter_service.py`, `tariff_service.py`, `subscription_service.py`, `referral_service.py`, `ad_service.py`, `app/handlers/admin/{groups,policy,counter,tariffs,settings,broadcast}.py`, `app/keyboards/common.py`.

## 4. Oddiy foydalanuvchi → sotuvchilik arizasi

### Ko‘rinadigan jarayon

```text
Shaxsiy chat: /start
  ├─ Oddiy foydalanuvchi → [🛒 Sotuvchi bo‘lish] [☎️ Yordam]
  │    → Ism/do‘kon nomi → aloqa (@username yoki telefon) → ma’lumotni tekshirish
  │    → [✅ Ariza yuborish] [✏️ Tahrirlash] [❌ Bekor]
  │    → «Ariza qabul qilindi #ID; admin ko‘rib chiqadi»
  │    → [📋 Arizam holati] [☎️ Yordam]
  ├─ Ariza ko‘rib chiqilmoqda → takroriy yuborish emas, holat va ID
  ├─ Rad etildi → sabab + tuzatib qayta topshirish yo‘li (tezlik chegarasi bilan)
  ├─ Tasdiqlandi → «Sotuvchi paneli ochildi; tarif hali tanlanmagan»
  └─ Bloklangan/o‘chirilgan sotuvchi → arizadan aylanib o‘tolmaydi; yordam

Admin: 🛒 Savdo → 📥 Arizalar (soni)
  → #ID | Telegram ID | ism | aloqa | yuborilgan vaqt | holat
  → [✅ Tasdiqlash] [❌ Sabab bilan rad etish] [◀️ Navbat]
  → tasdiqda 1 ta Seller yozuvi; ariza holati + audit + foydalanuvchiga DM
  → TARIF HAM, TO‘LOV HAM, E’LON HAM AVTOMATIK TASDIQLANMAYDI
```

Ariza faqat shaxsiy chatda ochiladi; Telegram `from_user.id` avtomatik olinadi (IDni qo‘lda so‘ramaslik). Foydalanuvchi kiritgan matn/aloqa tozalanadi va uzunligi tekshiriladi, admin ekraniga xavfsiz chiqariladi. Telefonni keraksiz joyda, masalan guruh yoki xato jurnalida, oshkor qilmaslik. `/start ref_<kod>`ning mavjud birinchi tashrif referal mexanizmi saqlanadi: ariza yuborish yoki tasdiqlash qayta «yangi foydalanuvchi» yoki takroriy bonus deb sanalmaydi.

### Ma’lumot va xavfsiz o‘tish (UX-2da amalga oshirildi)

- `seller_applications` **alohida jadval**: `user_id`, ko‘rsatiladigan ism, aloqa, holat (`pending/approved/rejected`), yuborilgan/ko‘rilgan vaqt, qaror bergan admin ID, rad sababi, bog‘liq `seller_id`. Tarix saqlanadi; `sellers.status=pending`ni ariza uchun qayta ishlatmaslik. Minimal Alembic migratsiya talab qilinadi.
- Bir foydalanuvchida bir vaqtning o‘zida faqat bitta ochiq ariza; ikki marta bosish, ikki adminning bir vaqtda tasdiqlashi va adminning qo‘lda «sotuvchi qo‘shish» yo‘li idempotent tekshirilsin. Seller `user_id` unikalligi saqlansin. Tasdiq va ariza holati **bitta DB tranzaksiyada**, DM esa commitdan keyin; xabar yuborilmasa qaror bekor bo‘lmaydi, navbatdagi tekshiruvda qayta xabar berish ko‘rib chiqiladi.
- Admin tasdiqlashi sotuvchiga faqat panel ochadi. Mavjud qo‘lda sotuvchi qo‘shish, tarif berish, chek tekshirish va e’lon moderatsiyasi o‘zgarmaydi. Agar shu ID allaqachon sotuvchi bo‘lsa, yangi ariza yaratish o‘rniga joriy holati ko‘rsatiladi; `BLOCKED`/`DELETED` uchun admin ko‘rigi talab qilinadi.
- Admin/super-admin arizani ko‘radi va qaror qiladi; moderator uni tasdiqlamaydi. Tugma yashirilishi **yetarli emas**: callback/servis ham rolni tekshiradi. Rad sababi foydalanuvchiga yuboriladi; qayta ariza alohida ID. UX-2 uchun konservativ spam chegarasi: **rad qaroridan 1 soat** kutish, **24 soatda ko‘pi bilan 3 ta ariza**. Eski ariza/yangi ariza statusi «tarifsiz sotuvchi»dan mustaqil.
- Ilgari qo‘lda qo‘shilgan sotuvchilar ariza jadvaliga ko‘chirilib «kutilayotgan» bo‘lib qolmaydi. Qo‘lda ID bilan qo‘shish ochiq arizani xuddi shu tranzaksiyada yopadi; ikkita adminning eski tugmasi qayta seller/DM yaratmaydi. `User` va ariza qatori/qulf, qisman UNIQUE pending indeksi, `Seller.user_id` UNIQUE va shartli UPDATE qo‘llanadi; PostgreSQLdagi haqiqiy parallel workerlar hali alohida sinovdan o‘tishi kerak. DM muvaffaqiyatsiz bo‘lsa foydalanuvchi `/start`dan statusini qayta ko‘radi. Eski callbacklar saqlangan; migratsiya oldingi sotuvchini/obunani ko‘chirmaydi.

## 5. Sotuvchi uchun birinchi ekran (UX-3da amalga oshirildi)

```text
🛒 Mening kabinetim
Holat: ✅ tasdiqlangan | 💳 Tarif: Boshlang‘ich (12 kun qoldi)
E’lon limiti: 2/5 ishlatilgan · 3 ta qolgan
E’lonlar: 1 faol · 1 tekshiruvda · 0 rad · 1 qoralama
To‘lov: 🕓 chek tekshiruvda / ✅ tasdiqlangan / ❌ rad (sabab)
Keyingi qadam: «tekshiruv natijasini kuting» yoki «tarif tanlang»

[📢 Mening e’lonlarim] [➕ Yangi e’lon]
[💳 Tarifim va limitlar] [🧾 To‘lovlarim]
[🛍 Tariflar katalogi] [👤 Aloqa ma’lumotlari]
[🎁 Referal] [☎️ Yordam]
```

`/start` va «Kabinetga» bir xil `seller_dashboard.get_overview` agregatidan foydalanadi: faol
tarif/muddat, **faol obunaning aynan `ads_used/ads_limit` hisoblagichi**,
`ad_service.seller_ads_stats`dagi e’lon holatlari (tarixiy/qoralama e’lon sonini limit deb hisoblamaydi)
hamda sotuvchining **oxirgi cheki** `payment_service.list_payments(seller_id=..., limit=1)` orqali
ko‘rsatiladi. Oxirgi chek rad bo‘lsa sababi HTML-escape qilinadi; tasdiqlangan chek ham faol tarifni
avtomatik anglatmaydi. Keyingi qadam tarif yo‘q, chek tekshiruvda/rad, obuna muddati tugagan/bekor
qilingan, limit tugagan, e’lon rad/tekshiruvda/qoralama va tez tugaydigan tarif holatiga mos tanlanadi.
«➕ Yangi e’lon» tugmasi `subscription_service.can_publish`ga mos yashiriladi, **eski callback esa baribir
servisda tekshiriladi**. «Mening e’lonlarim» tarifsiz ham avvalgi ro‘yxatni ko‘rsatadi, lekin uning
ichida ham yangi e’lon tugmasi yo‘q; «Kabinetga» qaytish bor. «👤 Aloqa ma’lumotlari» faqat o‘z shaxsiy
chatida o‘qish uchun; telefon/do‘kon/aloqa nomi tahriri mavjud admin/yordam oqimida qoladi, avtomatik
verifikatsiya yo‘q. Bloklangan/o‘chirilgan sotuvchi kabinet/profilni ocholmaydi, `/start` yordam
manzilini ko‘rsatadi. To‘lov `pending` holati ariza `pending`idan **alohida**. Sotuvchining e’lon ustasi
yoki chek rasmi FSMida ham `/start` umumiy kabinetga qaytadi (qoralama DBdan o‘chmaydi). Eski «Mening
e’lonlarim», «Mening tarifim», to‘lov va referal oqimlari saqlanadi; oddiy foydalanuvchining
`/takliflarim` sanoqchi ekrani alohida qoladi. Oflayn testda real bot/tashqi bank tekshiruvi sinovdan
o‘tmagan.

## 6. Bosqichlar va qabul mezonlari

Bu **Phase 0–9ni qayta boshlash emas**, keyingi UX ishlari uchun alohida kichik bosqichlar. 2026-10-16da foydalanuvchi **UX-1/2/3ning barchasiga** umumiy ruxsat berdi; har biri yakunida hisobot kerak. UX-4 yoki boshqa yangi bosqich uchun yana alohida ruxsat talab etiladi.

1. **UX-0 — hozirgi hujjat:** menyu/ariza sxemasi, amaldagi limitlar va xavflarni ko‘rsatish; funksional kodga tegmaslik. Qabul: foydalanuvchi reja va ustuvorlikni ko‘radi, yangi chegaralar hali kuchga kirmaydi.
2. **UX-1 — admin navigatsiyasi va guruh diagnostikasi:** mavjud xizmatlarga yangi kirish joyi, orqaga/yangilash, global–guruh–sinov holatlarini alohida ko‘rsatish; mavjud har guruhning mustaqil qoidalari saqlanadi. Qabul: admin oldingi amallarni yangi menyudan topadi, moderator ruxsatsiz sozlamani o‘zgartira olmaydi, eski callbacklar buzilmaydi.
3. **UX-2 — sotuvchilik arizasi:** DB migratsiyasi, xususiy chat ustasi, admin navbati/qarori, bildirishnoma, dublikat/race nazorati. Qabul: oddiy `/start` to‘siqsiz; tasdiqsiz sotuvchi paneliga/e’lon/to‘lovga o‘tolmaydi; tasdiq tarif yoki chekni tasdiqlamaydi; qo‘lda qo‘shilgan sotuvchilar saqlanadi.
4. **UX-3 — sotuvchi kabineti:** mavjud e’lon/tarif/to‘lov holatini jamlash va tez yo‘llar. Qabul: har holat uchun to‘g‘ri keyingi qadam, limit va to‘lov holati amaldagi servisga mos; mavjud e’lon/tarif/chek oqimlari buzilmaydi.
5. **UX-4 — keyingi alohida limit ko‘rib chiqish:** hozirgi ×10 bosqichidan boshqa o‘zgarish bo‘lsa, alohida ruxsat va maydon kesimidagi xavfsizlik tekshiruvi kerak. Qabul: UI, servis, test va mavjud ma’lumotlar mos; Telegram hard cheklovlari saqlanadi.

**Alohida bajarilgan limit/yo‘riqnoma bosqichi (2026-10-16):** foydalanuvchining ×10 so‘rovi doirasida admin belgilaydigan maksimumlar oshirildi (3-bo‘lim), admin/moderator/sotuvchi/oddiy foydalanuvchining shaxsiy ekranlarida «📖 Foydalanish yo‘riqnomasi» tugmasi qo‘shildi. Rol callbackda berilmaydi, DBdagi haqiqiy rolga qarab serverda aniqlanadi. **O‘sha bosqichda** ariza, navbatlar va menyu hali yo‘q edi; keyingi umumiy ruxsat doirasida UX-1/2/3 joriy qilindi. UX-3 uchun yangi jadval/migratsiya yoki avtomatik chek/e’lon qarori yo‘q.

Har bir **kod bosqichi** yakunida: to‘liq `pytest`, `compileall`, vaqtinchalik DBda Alembic `upgrade head` + `check` (yangi migratsiya bo‘lsa eski holatdan o‘tish), seedni ikki marta bajarib dublikat tekshiruvi, boundary/ruxsat/oqim testlari, diff va hisobot; so‘ng **faqat joriy branchga** commit/push. Oflayn testlar jonli Telegram/Redis/PostgreSQL yoki Replit qabul sinovi o‘rnini bosmaydi; jonli sinov/deploy alohida ruxsat va xavfsiz muhit bilan qilinadi.

**UX-0 tarixiy tekshiruv eslatmasi (2026-10-16, limit bosqichidan oldin):** real joriy vaqt bilan to‘liq `pytest`da 354 ta test o‘tdi, 1 tasi vaqtga bog‘liq bo‘lib qoldi: `tests/test_posting_service.py::test_quiet_hours_and_daily_cap_defer_without_claim`. Test `setup()`da navbat vaqtini bugungi `utcnow()`dan oladi, keyin esa `2026-10-15 18:30 UTC` sanasini qat’iy beradi; 16-oktabrda xabar «hali vaqti kelmadi» deb qaytadi. Faqat ushbu testni 15-oktabr nazoratli `utcnow()` bilan ishga tushirganda o‘tdi. `compileall`, Alembic `upgrade/check` va ikki martalik seed tekshiruvi muvaffaqiyatli. Hozirgi faqat-hujjat bosqichida test yoki bot kodi o‘zgartirilmadi; keyingi kod bosqichida test vaqtini barqaror qilish alohida ruxsat bilan ko‘riladi. **O‘sha UX-0 bosqichida to‘liq testlar yashil deb e’lon qilinmaydi.** Keyingi limit/yo‘riqnoma bosqichida `setup(now=...)` bilan bu test vaqtga bog‘liqlikdan xalos qilindi; joriy test natijalari `HOLAT.md`da.

## 7. Kelishilgan doira va ochiq tekshiruvlar

- **5 bo‘limli admin menyusi** va guruh ichidagi «N kishi» / «kanal a’zoligi» alohida yo‘li UX-1da joriy etildi; har guruh qoidalari mustaqil saqlanadi.
- UX-2 ariza maydonlari **ism/do‘kon nomi + @username yoki telefon**. Rad qaroridan keyin 1 soat kutish va 24 soatda eng ko‘pi 3 ta ariza qoidasi kodda/testda qo‘llanadi; operatsion ehtiyoj boshqa bo‘lsa alohida kelishish lozim.
- ×10 limit so‘rovi 3-bo‘limdagi xavfsiz chegaralar bilan bajarildi; 10 rasm/albom, 25 xabar/soniya, 30% jitter va 50% chegirma **oshirilmagan**. Boshqa limit kerak bo‘lsa alohida ruxsat bilan ko‘rib chiqiladi.
- UX-2 migratsiyasi oflayn eski sotuvchi bilan upgrade/check/downgrade sinovidan o‘tgan. UX-3 faqat mavjud bazani o‘qiydi; yangi jadval yoki avtomatik to‘lov/e’lon tasdig‘i yo‘q. Haqiqiy PostgreSQL parallel worker, Redis FSM, Telegram xabar yetkazish va jonli Replit/deploy alohida qabulni talab qiladi.

**Ruxsat chegarasi:** UX-1/2/3ga umumiy ruxsat berilgan, lekin boshqa yangi kod bosqichi yoki Replitni yangilashga avtomatik ruxsat yo‘q. Har bosqich yakunida hisobot beriladi.
