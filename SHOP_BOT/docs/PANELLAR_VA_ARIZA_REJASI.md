# Boshqaruv panellari, limitlar va sotuvchilik arizasi — loyiha rejasi

**Holat:** tasdiqqa taqdim etilgan UX va texnik reja; **hozircha bot kodiga kiritilmagan**.

**Doira:** `SHOP_BOT/`; `AVTO_BOT/`, `main` va jonli Replit muhitiga tegilmaydi.

**Qaror:** oddiy `/start` ochiq qoladi. **Faqat sotuvchilik arizasi** admin tasdig‘idan o‘tadi. Tarif, chek va e’lon bo‘yicha mavjud alohida tekshiruvlar o‘z kuchida qoladi.

## 1. Mavjud holat va asosiy chalkashliklar

- `app/keyboards/admin.py`da 19 ta bo‘lim bir darajada turadi: guruhlar, posbon, tozalovchi, sanoqchi va sozlamalar turli joyda. Global funksiya o‘chirgichi, bir guruh o‘chirgichi va o‘sha guruhning «sinov/jonli» rejimi o‘rtasidagi farqni topish qiyin.
- `app/middlewares/user_context.py` yangi Telegram foydalanuvchisini `users`ga avtomatik yozadi; bu **sotuvchi sifatida tasdiqlanish emas**. `app/handlers/common.py`dagi `/start` oddiy foydalanuvchiga faqat yordamni taklif qiladi. Sotuvchini admin hozir `app/handlers/admin/sellers.py` orqali ID va kontakt ma’lumotlari bilan qo‘lda qo‘shadi.
- `SellerStatus.PENDING` (`app/constants.py`) **admin arizasi kutilmoqda** degani emas: sotuvchi yozuvi bor, lekin hali tarifi yo‘q. To‘lovning `PENDING`i va e’lonning `PENDING`i ham boshqa oqimlardir. Ariza uchun alohida holat zarur.
- Sotuvchi panelida e’lonlar, tarif, to‘lov allaqachon bor (`app/handlers/seller/`, `app/keyboards/seller_panel.py`), biroq har biriga alohida kiriladi: birinchi ekranda «nima qoldi / nima kutilyapti / keyin nima qilish kerak» aniq jamlanmagan. `/start`dagi sotuvchi holatini tekshirishda `BLOCKED` va `DELETED` kabi holatlar izchil ko‘rilishi kerak; bu ushbu rejada tuzatish taklifi, hozirgi kod o‘zgartirilmaydi.
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

Quyidagilar **hozir kod qo‘llaydigan chegaralar**, yangi qiymatlar emas. «Panel» degani hozir tahrirlanadigan joy; «taklif» — kelajakdagi ko‘rinish. Raqamlar biznes kelishuvisiz oshirilmaydi, ayniqsa Telegram va spam/xavfsizlik chegaralari.

| Soha / maydon | Hozirgi oraliq yoki default | Kelajakdagi aniq joy va eslatma |
|---|---|---|
| Guruh post intervali; toifa intervali | 1–1440 daqiqa; default guruh 30 daq | `Guruh → Joylash`, toifa uchun shu ekran ichidagi override; toifa override guruhdan mustaqil |
| Guruh kunlik post limiti; jitter | 1–500 xabar/kun (default 50); 0–30% (default 10%) | `Guruh → Joylash`; kiritishda birlik va amaldagi qiymat ko‘rsatiladi |
| Tinch soatlar / e’lon oqimi | Vaqt oralig‘i; guruh bo‘yicha | `Guruh → Joylash`; kunlik limit bilan aralashtirmaslik |
| Posbon ogohlantirish / mute / oyna | 1–20 ta; 1–10080 daqiqa; 1–720 soat | `Guruh → Posbon`; jazo, sinov/jonli va global ta’sir alohida |
| Posbon taqiqlangan so‘zlari | ko‘pi bilan 30 so‘z, har biri 2–50 belgi | `Guruh → Posbon → So‘zlar`; ro‘yxat uzunligi xavfsizlik chegarasi, e’lon limitiga aloqasi yo‘q |
| Tozalovchi nechta e’lon qoldiradi / qachon o‘chiradi | 1–20 ta; 0–3600 soniya | `Guruh → Tozalovchi`; 0 «darhol» degani ekanini yozish |
| N kishi / minimal qolish | 0–100 kishi; 0–10080 daqiqa (yangi guruhda N=3, qolish=10 daq) | `Guruh → N kishi`; N=0 faqat taklif shartini o‘chiradi, kanal sharti alohida qolishi mumkin; eski hisoblar N o‘zgarsa qayta baholanadi |
| Sanoqchi kunlik hisob / bitta havola limiti | 1–100 / 1–100 (yangi guruhda ikkalasi 20) | `Guruh → N kishi`; kunlik hisob bilan post kunlik limitini farqlash |
| Sanoqchi hisobini admin qo‘lda tuzatishi | bir amal uchun −1000…+1000, sabab 3–255 belgi | `Guruh → N kishi → A’zo hisobi`; amal auditga yoziladi, N cheklovi bilan adashtirmaslik |
| Majburiy kanal | global va guruh kanallari, shart on/off | `Guruh → Kanal a’zoligi`; global ro‘yxat `Tizim → Umumiy kanallar`; kanalga admin huquqi va tekshirish talabi |
| Istisno muddati | 1–365 kun yoki muddatsiz | `Guruh → Istisnolar`; global ruxsat bilan guruh ruxsatini ajratish |
| Tarif muddati / e’lon kvotasi | 1–3650 kun / 1–1000 e’lon | `Savdo → Tariflar`; sotuvchi panelida obuna «ishlatilgan / jami / qolgan» |
| Tarif rasm limiti | 1–10 rasm/e’lon; default 3 | `Savdo → Tariflar`; **10 Telegram albomi chegarasi**, oshirish boshqa yuborish mexanizmini talab qiladi |
| Tarif narxi; e’lon narxi | 0–999 999 999 so‘m; 0–1 000 000 000 000 so‘m | `Savdo → Tariflar` va sotuvchining e’lon ustasi; DB va to‘lov chegaralari bilan tekshirmay oshirmaslik |
| E’lon sarlavhasi/tavsifi; sotuvchi profil maydonlari | sarlavha 3–120 belgi, tavsif ko‘pi bilan 800; sotuvchi nomi 64, telefon 32, kontakt 64 belgi | sotuvchi arizasi/profili va e’lon ustasidagi yordam matni; servisda kesilishi va DB maydoni mosligi tekshirilsin |
| Obunaga qo‘lda beriladigan e’lon limiti | 0–100000 | `Savdo → Sotuvchilar → Obuna`; tarif kvotasi va qo‘lda o‘zgarishni farqlash |
| Referal kunlik bonus, bonus qiymati | 1–50/kun; kun bonusi 1–365, balans 1000–1000000 so‘m, chegirma 1–50%; min. to‘lov 0–1 mlrd so‘m | `Savdo → Referal`; sotuvchi referali **guruh sanoqchisidan alohida**; default o‘chiq, ikki bosqichli yoqish |
| Broadcast yuborish tezligi | 1–25 xabar/soniya (default 25) | `Kontent → Broadcast`; global kalit va yuborish tasdig‘i saqlanadi; Telegram tezlik chegarasidan yuqoriga oshirilmaydi |
| Post rate-limiterining guruh oralig‘i | eng kam 2 soniya (koddagi xavfsizlik chegarasi) | `Guruh → Joylash`dagi 1 daqiqalik minimumdan boshqa qoida; panelda «sozlanadigan kunlik limit» deb ko‘rsatilmaydi |
| Oddiy ro‘yxat sahifasi | guruh/sotuvchi/e’lon 6 tadan; toifa/tarif 8 tadan | navigatsiya/pagination, **biznes limiti emas**; keyin qulay sahifalash bilan sinash |

Kodda default sifatida saqlanadigan, lekin bugun paneldan bevosita tahrirlanmaydigan qiymatlar ham bor: `settings_service.DEFAULTS`da `min_interval_sec=60`, `default_max_ads=5`, `default_max_photos=3`, `subscription_reminder_days=3`, `subscription_grace_days=0`, `log_retention_days=90` (oxirgisi panelda faqat ko‘rinadi). `posting_enabled_global` va `welcome_enabled_global` ham mavjud, lekin hozirgi umumiy toggle ro‘yxatida yo‘q: yangi menyuda ularni «hozir sozlanadigan» tugma deb ko‘rsatmaslik; zarur bo‘lsa alohida ruxsat, ekran va validatsiya bilan qo‘shish. Matn/miqdor chegaralarini oshirishdan oldin Telegram format, to‘lov va DB turlariga ta’siri tekshiriladi.

**Limit o‘zgartirish qoidasi (keyingi bosqichda):** har maydon uchun `amaldagi → so‘ralgan yangi → hard cheklov → xavf → migratsiya kerakmi` jadvali tasdiqlanadi. Handler va servisdagi tekshiruvlar, ekran matni, mavjud DB qiymatlari va test chegaralari birga yangilanadi; servisning qiymatni sezdirmasdan qisqartirishi o‘rniga xato va ruxsat etilgan oraliq ravshan ko‘rsatiladi. *Hozir hech bir limit qiymati o‘zgarmaydi.*

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

### Ma’lumot va xavfsiz o‘tish (implementatsiya taklifi, hali bajarilmagan)

- `seller_applications` kabi **alohida jadval**: `user_id`, ko‘rsatiladigan ism, aloqa, holat (`pending/approved/rejected`), yuborilgan/ko‘rilgan vaqt, qaror bergan admin ID, rad sababi, bog‘liq `seller_id`. Tarix saqlanadi; `sellers.status=pending`ni ariza uchun qayta ishlatmaslik. Minimal Alembic migratsiya talab qilinadi.
- Bir foydalanuvchida bir vaqtning o‘zida faqat bitta ochiq ariza; ikki marta bosish, ikki adminning bir vaqtda tasdiqlashi va adminning qo‘lda «sotuvchi qo‘shish» yo‘li idempotent tekshirilsin. Seller `user_id` unikalligi saqlansin. Tasdiq va ariza holati **bitta DB tranzaksiyada**, DM esa commitdan keyin; xabar yuborilmasa qaror bekor bo‘lmaydi, navbatdagi tekshiruvda qayta xabar berish ko‘rib chiqiladi.
- Admin tasdiqlashi sotuvchiga faqat panel ochadi. Mavjud qo‘lda sotuvchi qo‘shish, tarif berish, chek tekshirish va e’lon moderatsiyasi o‘zgarmaydi. Agar shu ID allaqachon sotuvchi bo‘lsa, yangi ariza yaratish o‘rniga joriy holati ko‘rsatiladi; `BLOCKED`/`DELETED` uchun admin ko‘rigi talab qilinadi.
- Admin/super-admin arizani ko‘radi va qaror qiladi; moderator uni tasdiqlamaydi. Tugma yashirilishi **yetarli emas**: callback/servis ham rolni tekshiradi. Rad sababi sotuvchiga tushunarli yuboriladi; rad etilgandan so‘ng qayta ariza alohida ID bo‘ladi, cheksiz spamga qarshi vaqt/urinish qoidasi keyin kelishiladi.
- Ilgari qo‘lda qo‘shilgan sotuvchilar ariza jadvaliga ko‘chirilib «kutilayotgan» bo‘lib qolmasin. Eski tugmalar/callbacklar ishlashda davom etsin yoki foydali yangi sahifaga yo‘naltirilsin; migratsiya eski ma’lumotlarga xavf tug‘dirmaydi.

## 5. Sotuvchi uchun birinchi ekran (prioritet)

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

Ma’lumot mavjud servislar (`seller_service`, `subscription_service`, `payment_service`, `ad_service`) orqali olinadi; kabinetdagi jamlangan sonlar bilan amaldagi limit hisoblagichi turlicha chiqmasin. Tarif yo‘q bo‘lsa «e’lon yarata olmaysiz», muddat o‘tgan bo‘lsa «yangilang», limit tugagan bo‘lsa ishlatilgan/jami, bloklangan bo‘lsa yordam ko‘rsatiladi. To‘lovning `pending/approved/rejected` holati sotuvchilik arizasining holatidan aniq farqlanadi. Eski «Mening e’lonlarim», «Mening tarifim», to‘lov va referal oqimlari saqlanadi; birinchi ekran ularga tez kirishdir, qayta yozish emas. Oddiy foydalanuvchining `/takliflarim` sanoqchi ekrani alohida qoladi.

## 6. Bosqichlar va qabul mezonlari

Bu **Phase 0–9ni qayta boshlash emas**, keyingi UX ishlari uchun alohida kichik bosqichlar. **Har biri boshlanishidan oldin alohida ruxsat, yakunida hisobot** talab etiladi.

1. **UX-0 — hozirgi hujjat:** menyu/ariza sxemasi, amaldagi limitlar va xavflarni ko‘rsatish; funksional kodga tegmaslik. Qabul: foydalanuvchi reja va ustuvorlikni ko‘radi, yangi chegaralar hali kuchga kirmaydi.
2. **UX-1 — admin navigatsiyasi va guruh diagnostikasi:** mavjud xizmatlarga yangi kirish joyi, orqaga/yangilash, global–guruh–sinov holatlarini alohida ko‘rsatish; mavjud har guruhning mustaqil qoidalari saqlanadi. Qabul: admin oldingi amallarni yangi menyudan topadi, moderator ruxsatsiz sozlamani o‘zgartira olmaydi, eski callbacklar buzilmaydi.
3. **UX-2 — sotuvchilik arizasi:** DB migratsiyasi, xususiy chat ustasi, admin navbati/qarori, bildirishnoma, dublikat/race nazorati. Qabul: oddiy `/start` to‘siqsiz; tasdiqsiz sotuvchi paneliga/e’lon/to‘lovga o‘tolmaydi; tasdiq tarif yoki chekni tasdiqlamaydi; qo‘lda qo‘shilgan sotuvchilar saqlanadi.
4. **UX-3 — sotuvchi kabineti:** mavjud e’lon/tarif/to‘lov holatini jamlash va tez yo‘llar. Qabul: har holat uchun to‘g‘ri keyingi qadam, limit va to‘lov holati amaldagi servisga mos; mavjud e’lon/tarif/chek oqimlari buzilmaydi.
5. **UX-4 — limit chegaralarini qayta ko‘rib chiqish:** faqat foydalanuvchi aniq sonlarni tasdiqlasa; imkon bo‘lsa maydon kesimida. Qabul: UI, servis, xavfsizlik, test va mavjud ma’lumotlar mos; Telegram hard cheklovlari saqlangan.

Har bir **kod bosqichi** yakunida: to‘liq `pytest`, `compileall`, vaqtinchalik DBda Alembic `upgrade head` + `check` (yangi migratsiya bo‘lsa eski holatdan o‘tish), seedni ikki marta bajarib dublikat tekshiruvi, boundary/ruxsat/oqim testlari, diff va hisobot; so‘ng **faqat joriy branchga** commit/push. Oflayn testlar jonli Telegram/Redis/PostgreSQL yoki Replit qabul sinovi o‘rnini bosmaydi; jonli sinov/deploy alohida ruxsat va xavfsiz muhit bilan qilinadi.

**UX-0 tekshiruv eslatmasi (2026-10-16):** real joriy vaqt bilan to‘liq `pytest`da 354 ta test o‘tdi, 1 tasi vaqtga bog‘liq bo‘lib qoldi: `tests/test_posting_service.py::test_quiet_hours_and_daily_cap_defer_without_claim`. Test `setup()`da navbat vaqtini bugungi `utcnow()`dan oladi, keyin esa `2026-10-15 18:30 UTC` sanasini qat’iy beradi; 16-oktabrda xabar «hali vaqti kelmadi» deb qaytadi. Faqat ushbu testni 15-oktabr nazoratli `utcnow()` bilan ishga tushirganda o‘tdi. `compileall`, Alembic `upgrade/check` va ikki martalik seed tekshiruvi muvaffaqiyatli. Hozirgi faqat-hujjat bosqichida test yoki bot kodi o‘zgartirilmadi; keyingi kod bosqichida test vaqtini barqaror qilish alohida ruxsat bilan ko‘riladi. **To‘liq testlar yashil deb e’lon qilinmaydi.**

## 7. Keyingi ruxsatdan oldin tasdiqlanishi kerak bo‘lganlar

- Ushbu **5 bo‘limli admin menyusi** va guruh ichidagi «N kishi» / «kanal a’zoligi» bo‘linishi sizga mosmi?
- Ariza minimal maydonlari sifatida **ism/do‘kon nomi + @username yoki telefon** yetarlimi? Rad etilgach qayta ariza uchun kutish muddati va kunlik urinish limitini keyingi bosqichda aniqlaymiz.
- Qaysi **aniq** limitlar kichik tuyulyapti va ularning yangi oraliqlari qancha bo‘lsin? Hozirgi 10 rasm/albom va 25 xabar/soniya kabi xavfsizlik chegaralari oshirilmaydi.

**Reja tasdig‘i kodlashga avtomatik ruxsat emas.** Avval UX-1 uchun alohida ruxsat so‘raladi; undan keyin har bir bosqich alohida kelishiladi.
