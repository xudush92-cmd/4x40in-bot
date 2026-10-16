# SHOP-BOT — administrator uchun amaliy qo‘llanma

> Ushbu yo‘riqnoma **`SHOP_BOT/`** loyihasining `arena/18e1094b-4x40in-bot` branchidagi amaldagi paneliga tegishli. Telegram tugmalaridagi matnlarni imkon qadar aynan keltirdik. Admin panel **bot bilan shaxsiy chatda** ishlaydi; guruhning o‘zida sozlash tugmalarini qidirmang. Bu qo‘llanma jonli Telegram/bank/production sinovi o‘tkazilgani haqida dalil emas. Deploy/backup bo‘yicha alohida hujjat: [DEPLOY.md](DEPLOY.md).

Botning shaxsiy `/start` ekranida oddiy foydalanuvchi/sotuvchi, «🛠 Boshqaruv paneli»da admin/moderator uchun **«📖 Foydalanish yo‘riqnomasi»** tugmasi bor. Ular faqat amaldagi imkoniyatlarni qisqa tushuntiradi; batafsil operator tartibi shu qo‘llanmada. Oddiy `/start` **ochiq**: «🛒 Sotuvchi bo‘lish» arizasi admin tasdig‘i bilan **faqat sotuvchi panelini** ochadi; ID orqali qo‘lda qo‘shish ham qolgan.

## 1. Tezkor yo‘l xaritasi

1. Botni ishga tushiring, migratsiya va seedni bajaring; o‘zingizning **raqamli Telegram ID**ingiz `ADMIN_IDS`da bo‘lsin.
2. Botga **shaxsiy** `/start` yuboring → «🛠 Boshqaruv paneli». Qayta kirish: `/admin`; IDni bilish: `/id`.
3. «👥 Guruhlar» → test superguruhni ulang → bot huquqlarini tekshiring → «🧩 Funksiyalar»da kerakli switchlarni yoqing.
4. «🗂 Toifalar»da guruhga biriktirilgan toifa yarating; tekshirib tasdiqlash kerak bo‘lsa «Moderatsiya»ni yoqing.
5. «💳 Tariflar»ni tekshiring; test foydalanuvchi `/start` → «🛒 Sotuvchi bo‘lish» orqali ariza yuborsin. «🛒 Savdo → 📥 Arizalar»da admin qaroridan keyin tarifni **alohida** bering (yoki «🛒 Sotuvchilar»dan ID bilan qo‘lda qo‘shing). Sotuvchi o‘z chatida `/start` → tarif mavjud bo‘lsa e’lon qo‘shadi.
6. «✅ Moderatsiya» → e’lonni tasdiqlang; «👥 Guruhlar» → guruh → «📋 E’lonlar navbati»da uni tekshiring. «🚀 Hoziroq» tugmasi **haqiqiy post** yuboradi — faqat test guruhida bosing.
7. Posbon, tozalovchi va sanoqchini **har bir guruhda alohida**, avval 🧪 sinov rejimida tekshiring. 🔴 JONLI rejimni alohida tasdiqlamaguncha xabar o‘chirish/jazo ishlamaydi.

**Terminlar:** «global» — barcha guruhlarga ta’sir qiladigan yuqori daraja switchi; «guruh switchi» — faqat tanlangan guruhniki; «🧪 sinov / dry-run» — qaror jurnalga tushadi, ammo jonli Telegram jazosi/o‘chirishi bajarilmaydi. Switchlar va qoidalar bazada saqlanadi; odatda botni qayta ishga tushirish shart emas, boshqa process keshiga tarqalish **15 soniyagacha** olishi mumkin.

## 2. Birinchi ishga tushirish (Replitda xavfsiz sinov)

- Aynan shu branch va `SHOP_BOT/` papkasidan ishlang; `main` yoki boshqa `AVTO_BOT/` loyihasining token/bazasini ishlatmang. Kod olingan bo‘lsa, joriy branchni `git branch --show-current` bilan tekshiring.
- Replit **Secrets**ga haqiqiy `BOT_TOKEN` va o‘zingizning raqamli Telegram IDingizni `ADMIN_IDS` sifatida kiriting. Tokenni chatga, ommaviy `.env`ga yoki Gitga yozmang. `USE_WEBHOOK=false` (polling) va `RUN_MODE=all` (bot + poster bitta process) qo‘ying. Bir token bilan **faqat bitta** polling process ishlasin.
- Faqat qisqa, bir processli **sinov** uchun `DB_URL=sqlite+aiosqlite:///./data/shopbot.db` va `DEV_MODE=true` ishlatish mumkin. `mkdir -p data` qiling. Replit fayl tizimini doimiy production baza deb hisoblamang; Redis ulanmasa FSM xotirada bo‘ladi va restartda davom etayotgan anketalar yo‘qolishi mumkin. Real ishga tushirishda alohida PostgreSQL (`postgresql+asyncpg://...`) va Redis, zaxira nusxa va alohida qabul sinovi talab etiladi. Redis yo‘q production rejimida broadcast xavfsizlik uchun to‘xtaydi.
- Replit web/health ko‘rinishi kerak bo‘lsa `HEALTH_HOST=0.0.0.0`, `HEALTH_PORT=8080` qo‘ying. `USE_WEBHOOK=false`da HTTPS domen/Caddy shart emas; `/health` javobini va loglarni tekshiring.

Replit Shell’da (agar allaqachon `SHOP_BOT/` ichida bo‘lsangiz `cd`ni takrorlamang):

```bash
cd SHOP_BOT
python3 -m pip install -r requirements.txt
mkdir -p data
alembic upgrade head
python3 -m scripts.seed
python3 -m app.main
```

`seed` super-adminni, standart sozlamalar va matnlarni hamda **3 ta namuna tarifni** kiritadi; mavjud ma’lumotlarni oddiy qayta ishga tushishda o‘chirmaydi. Namuna tariflar narxlarini haqiqiy savdodan oldin tekshiring. O‘zgaruvchilarni/branchni almashtirsangiz mos bazaga migratsiya va seed bajarilganini qayta tekshiring; productionda `--reset-texts` yoki bazani qayta yaratish bilan tajriba qilmang. Docker bilan ishga tushirish, backup va tiklash tartibi [DEPLOY.md](DEPLOY.md)da.

**Boshqa odamga admin berish:** avval u botda shaxsiy `/start` bossin va `/id` bilan IDini yuborsin. `.env`/Secretsdagi `ADMIN_IDS` — himoyalangan **super-adminlar**; panel orqali qo‘shiladigan adminlar uchun 16-bo‘limga qarang.

## 3. Panel, rollar va umumiy boshqaruv qoidasi

| Rol | Nima qila oladi |
|---|---|
| **Super-admin** (`ADMIN_IDS`) | Hamma bo‘limlar; «🛠 Adminlar» orqali boshqa adminlarni qo‘shish/rol berish. `.env`dagi super-admin panelda o‘chirib yuborilmaydi. |
| **Admin** | Guruh/toifa, sotuvchi/tarif, to‘lov, siyosat/sanoqchi, matn, broadcast va boshqa operatsion sozlamalar. Boshqa adminlarning rolini o‘zgartirmaydi. |
| **Moderator** | «✅ Moderatsiya» va e’lonlarni ko‘rish/qaror qilish. Guruh, toifa, global sozlama, siyosat, sanoqchi, ruxsat, referal va matnlarning ko‘pini **faqat ko‘radi**; navbatni qo‘lda joylay olmaydi, sotuvchi/tarif va to‘lov paneliga kira olmaydi; moliyaviy CSV olmaydi. |

Asosiy menyuda «📥 Qaror kutayotganlar» (admin/super-admin uchun sotuvchilik arizasi, moderatsiya va chek; moderator uchun faqat moderatsiya), «👥 Guruhlar», «🛒 Savdo», «📢 Kontent», «📊 Nazorat», «⚙️ Tizim» bor. Guruh kartasida «🧮 N kishi» va «📣 Kanal a’zoligi» mustaqil tugmalar; «🔍 Nega ishlamayapti?» saqlangan global/guruh/sinov holati va so‘nggi bot huquqlarini faqat o‘qib ko‘rsatadi, Telegramdagi huquqlarni «🔄 qayta tekshirish» alohida amalga oshiradi. «⚙️ Tizim → 📚 Barcha bo‘limlar»da eski navigatsiya saqlangan.

Paneldagi emoji raqamlar — joriy hisoblagich, tugmani «🔄 Yangilash» bilan qayta chizish mumkin. Amallarda «/cancel» — kiritilayotgan qiymatni bekor qiladi. Tugma eskirgan bo‘lsa `/start` yoki `/admin` bilan panelni qayta oching. **Ko‘rish** va **jonli amalga ruxsat** bir xil narsa emas: xavfli tugmalarni tasdiqlashdan avval guruh nomi va holatini qayta o‘qing.

## 4. «⚙️ Sozlamalar» — hamma guruhlarga tegishli

- «🛑 HAMMASINI TO‘XTATISH»: odatiy foydalanuvchi murojaatlarini va global funksiyalarni to‘xtatadi; admin paneldan o‘chirishi mumkin. «🔧 Texnik rejim (faqat adminlar)»: oddiy foydalanuvchilar vaqtincha bloklanadi, avtomatik posting/jonli siyosat ishlamaydi. Testdan keyin ikkisini qayta tekshiring.
- «🧮 Sanoqchi global», «🛡 Posbon global», «🧹 Tozalovchi global», «📣 Broadcast global pauza»: butun tizimdagi tegishli funksiyani to‘xtatish/qayta yoqish. **Global switchni o‘chirish guruh ichidagi N, so‘zlar yoki istisnolarni o‘chirmaydi**; qayta yoqishda eski jonli qoidalar qayta ishga tushishi mumkin, shuning uchun panel ogohlantirishini tasdiqlashdan oldin guruhlarni tekshiring.
- «🧾 Chek rasmi majburiy» va «🔍 Takroriy chekni ushlash»: sukut bo‘yicha yoqilgan; sinovda ham xavfsizlik uchun yoqilgan holda qoldiring. Cheksiz yuborishga ruxsat berish **bank tekshiruvini bekor qilmaydi**.
- «⏱ Joylash intervali (default)»: guruh uchun boshqa qiymat belgilanmagandagi interval, **1–14400 daqiqa**. «☎️ Yordam kontakti»: `@username` (tavsiya) yoki telefon; yordam tugmasi Telegram havolasini tuzishi sabab `@username` ishonchliroq.
- Referal bu yerdan yoqilmaydi: «🤝 Referal» bo‘limida alohida tasdiqlanadi. «Posting global» uchun alohida panel tumbleri yo‘q; guruhdagi «E’lon joylash», guruh pauzasi, umumiy kill switch va texnik rejimni nazorat qiling.

## 5. «👥 Guruhlar» — ulash va **har bir guruh** sozlamasi

1. «➕ Guruh qo‘shish» tugmasi ID kiritish formasi **emas**: botni test **supergroup**ga qo‘shing va administrator qiling. Telegramda **xabarlarni o‘chirish**, **a’zolarni cheklash** (mute/ban) va **taklif havolalari yaratish** huquqlarini bering. @BotFather → `/setprivacy` → **Disable**; zarur bo‘lsa botni guruhdan chiqarib, qayta qo‘shing. Bot qo‘shilishi/roli haqidagi `my_chat_member` xabari kelgach guruh bazada paydo bo‘ladi; «🔄 Ro‘yxatni yangilash»ni bosing.
2. Guruh kartasida «🔍 Huquqlarni tekshirish»ni bosing. Yetishmayotgan huquqni **Telegramning guruh administratorlari sozlamasida** tuzating, so‘ng yana tekshiring. Bot guruhdan chiqarilsa yoki zarur huquqni yo‘qotsa joylash/tozalash ishlamasligi va guruh pauzalanishi mumkin.
3. «⏸ To‘xtatish / ▶️ Yoqish» — faqat shu guruhni pauzalash/tiklash; sinov paytida ommaviy guruhni to‘xtatish uchun shu usul xavfsizroq. «🧩 Funksiyalar» → «E’lon joylash», «Sanoqchi», «Posbon», «Tozalovchi» switchlari va «🖼 Kontentni himoya qilish». «🎛 Matritsa»da bir nechta guruhning shu **4 ta asosiy** switchini ko‘rib boshqarasiz. Funksiya switchini yoqishning o‘zi posbon/tozalovchi/sanoqchini jonli qilmaydi: 10–12-bo‘limlar bo‘yicha guruhning **o‘zida** tasdiq kerak.
4. «⚙️ Sozlamalar» → «⏱ Joylash intervali» (1–14400 daqiqa), «🔀 Jitter (±%)» (0–30), «📆 Kunlik limit» (1–5000), «🌙 Tinch soatlar» (`23:00-08:00`; olib tashlash `off`). Jitter post vaqtini siljitadi. «🧹 Eski e’lon nusxalarini o‘chirish» tezkor tugmasi yangi siyosatni **faqat sinov rejimida** sozlaydi; haqiqiy o‘chirish uchun guruhning «🧹 Tozalovchi» ekranida jonli rejimni tasdiqlash zarur.
5. «🗂 Toifalar», «📋 E’lonlar navbati», «🛡 Posbon», «🧹 Tozalovchi», «🧮 Sanoqchi», «🔑 Guruh ruxsatlari» — aynan shu guruh kontekstiga kirish. Boshqa guruhga o‘tish uning qoidalarini avtomatik ko‘chirmaydi.

**Eslatma:** «👋 Salomlashuv» tugmasi sozlamani saqlaydi, ammo hozirgi kodda yangi a’zoga avtomatik salomlashuv xabarini yuboradigan jonli oqim yo‘q; uni ishlayapti deb hisoblamang. «🗑 Guruhni o‘chirish» bazadagi guruhni o‘chiradi — oddiy pauza uchun ishlatmang, bog‘liq ma’lumotlarni oldin tekshiring.

## 6. «🗂 Toifalar» — e’lon qayerga tushadi?

«➕ Yangi toifa» → nom yuboring (`📱 Telefonlar` kabi) → yaratilgan kartadagi «📎 Guruh»dan kerakli guruhni tanlang. Agar toifa guruh kartasidan yaratilsa, guruh oldindan biriktiriladi. **Guruhga biriktirilmagan toifa e’lonlari post qilinmaydi.** Kartadagi:

- «✅ / ⚪️ Moderatsiya» — yoqilsa yangi e’lon admin tekshiruvini kutadi; o‘chiq bo‘lsa boshqa shartlar bajarilganda to‘g‘ridan-to‘g‘ri navbatga tushishi mumkin. Testda tasdiq talabini yoqing.
- «🟢 Faol / ⏸ To‘xtatilgan» — toifa bo‘yicha postingni boshqaradi. «⏱ Alohida interval» — 1–14400 daqiqa; `0` yuborsangiz guruh intervaliga qaytadi.
- «✏️ Nomini o‘zgartirish», «⬆️/⬇️» va «🔀 Tartib» — nom/tartibni boshqaradi. «📎 Guruh»dan boshqa guruhga ko‘chirishdan oldin tarif cheklovlari va mavjud e’lonlarni tekshiring. «🗑» toifani va unga bog‘liq e’lonlarni yo‘qotishi mumkin; faqat ataylab, tasdiqdan keyin foydalaning.

## 7. «💳 Tariflar» va «🛒 Sotuvchilar» — kim qancha e’lon beradi?

**Tariflar:** seed yaratgan 3 ta namunani tekshiring yoki «➕ Yangi tarif» → **nom → narx (0–9 999 999 990 so‘m; bepul bo‘lsa `0`) → muddat (1–36500 kun) → e’lon limiti (1–10000) → rasm limiti (1–10)**. Tarif kartasida narx, muddat, limit, nom va tavsif alohida o‘zgartiriladi; «⏸ To‘xtatish/▶️ Yoqish», «🎁 Sinov», tartib va o‘chirish bor. «🗂 Toifalar cheklovi»/«👥 Guruhlar cheklovi»da «♾ Barchasiga ruxsat» — cheklovsiz; aniq belgilar — faqat belgilanganlar; **0 ta tanlangan** — shu yo‘nalishdagi yangi joylash to‘xtaydi. Obuna/to‘lov bog‘langan tarif «o‘chirish»da odatda tarix uchun saqlanib, faqat to‘xtatiladi. Narx yoki cheklovni o‘zgartirishdan oldin haqiqiy sotuvchilarga ta’sirini tekshiring.

**Arizalar (shaxsiy chat):** oddiy foydalanuvchi `/start` → «🛒 Sotuvchi bo‘lish» → ism/do‘kon (2–64 belgi) → `@username` yoki telefon → preview → «✅ Ariza yuborish». «📋 Arizam holati»dan navbat yoki rad sababini ko‘radi; botda oddiy `/start` ro‘yxatdan o‘tishga majbur qilmaydi. Admin/super-admin «📥 Arizalar» (yoki «🛒 Savdo → 📥 Arizalar») → ariza kartasi → «✅ Tasdiqlash» → «✅ Ha, faqat panelni ochish» yoki «❌ Rad etish» → tayyor sabab/3–500 belgili qo‘lda sabab. Moderatorga bu qaror yopiq. Tasdiq **tarif bermaydi, chekni ham e’lonni ham tasdiqlamaydi**; yangi sotuvchi «tarifsiz» holatda qoladi. Rad etilgach **1 soat**, 24 soatda **3 ta** ariza chegarasi bor; tekshiruv davomida takror bosish yangi ariza yaratmaydi. Qaror/xabar yo‘li: DB/audit saqlanadi, so‘ng shaxsiy DM; DM kelmasa `/start` orqali joriy holatni tekshiring. Aloqa (telefon) faqat shaxsiy chat va admin ariza kartasida, guruhda emas.

**Sotuvchilar (qo‘lda):** «➕ Sotuvchi qo‘shish» → sotuvchining **raqamli Telegram ID**si (`/id`) → ism/do‘kon → telefon (`-` mumkin) → kontakt (`-` mumkin). Ochiq ariza bo‘lsa qo‘lda qo‘shish uni bir qarorda yopadi; eski tasdiq callbacki qayta seller/DM yaratmaydi. Bloklangan yoki o‘chirilgan sotuvchi yangi ariza bilan cheklovni chetlab o‘tolmaydi; admin qo‘lda holatini tekshiradi. Sotuvchi botga shaxsiy `/start` bosgan bo‘lsin, shunda unga xabar boradi. Ro‘yxatda holat filtrlari bor; kartada «💳 Tarif berish» → faol tarifni tanlash bilan obuna **darhol** beriladi: bir xil tarif bo‘lsa muddat/limit qo‘shiladi, boshqasi bo‘lsa yangisi bugundan boshlanadi. «➕ Muddatni uzaytirish (+30 kun)» ham bir bosishda bajariladi; «⏱ Muddat qo‘lda» — 1–36500 qo‘shimcha kun; «📢 Limit qo‘lda» — 0–1000000 yangi jami limit (ishlatilgan son o‘zgarmaydi). «✅ Tasdiqlangan», «📝 Profil», «🚫 Bloklash» (sabab bilan), «✅ Blokdan chiqarish», «🕘 Obunalar tarixi» mavjud. Kartadagi «✅ Tasdiqlangan» belgisi (profil is_verified) ariza qarori bilan bir xil emas. Bloklash sotuvchi panelini yopadi va e’lonlarini to‘xtatadi; oddiy sinov uchun bloklash/o‘chirishdan foydalanmang.

**UX-3 sotuvchi kabineti:** sotuvchi shaxsiy `/start` yoki «◀️ Kabinetga»dan
faol obuna va uning `ads_used/ads_limit` miqdori, holat bo‘yicha e’lonlar,
**oxirgi** chek va keyingi qadamni ko‘radi. E’lonlar soni tarixiy/qoralamalarni
ham sanaydi, shuning uchun u limit ishlatilgani bilan majburan teng emas.
Chek «tekshiruvda/rad/tasdiqlandi» bo‘lishi sotuvchilik arizasidan mustaqil:
faol obuna yo‘q bo‘lsa tasdiqlangan eski chek ham yangi e’lon berolmaydi.
Tarifsiz sotuvchi «Mening e’lonlarim» va «To‘lovlarim»ni ko‘radi, lekin yangi
e’lon tugmasi ko‘rsatilmaydi; eski callback servisda qayta tekshiriladi.
«👤 Aloqa ma’lumotlari» sotuvchining o‘ziga shaxsiy chatda read-only: nom,
telefon yoki aloqa o‘zgarsa admin profilida tuzating; e’londagi aloqani esa
sotuvchi e’lon kartasida alohida tahrirlaydi. Bloklangan sotuvchi panelga kira
olmaydi, `/start`dan yordam manzilini ko‘radi. E’lon ustasi/chek rasmi
kutishidagi sotuvchi `/start` bossa eski FSM tozalanib kabinetga qaytadi;
qoralama e’lon yozuvi saqlansa «Mening e’lonlarim»da ko‘radi. Bu ekran **tarif berish yoki
chekni tasdiqlash amali emas** — adminning mavjud qarorlari alohida qoladi.

## 8. «✅ Moderatsiya», «📢 E’lonlar» va joylash navbati

Sotuvchi shaxsiy panelda toifa, sarlavha, tavsif, narx, aloqa va rasmlarni kiritib e’lon yuboradi. Toifada moderatsiya yoqilgan bo‘lsa:

1. «✅ Moderatsiya» → «🕓 Tekshiruvda» ro‘yxati → e’lon kartasini/rasmlarini tekshiring.
2. «✅ Tasdiqlash» uni faol navbatga qo‘shadi va sotuvchiga xabar beradi. «❌ Rad etish» → tayyor sabab yoki o‘zingiz yozgan sabab; sotuvchi sababni ko‘radi, tegishli e’lon limiti qaytariladi.
3. «📢 E’lonlar»da holat bo‘yicha filtr (`Tekshiruvda`, `Faol`, `To‘xtatilgan`, `Rad etilgan`, `Arxiv`, `Hammasi`), kartada pauza/yoqish, o‘chirish (tasdiq bilan) va «🕘 Moderatsiya tarixi» bor.
4. «👥 Guruhlar» → guruh → «📋 E’lonlar navbati» → toifa: e’lonlar ketma-ketligi, oxirgi joylangan va keyingi vaqt ko‘rinadi. Admin «⬆️/⬇️» bilan tartibni o‘zgartiradi; «🚀 Hoziroq» darhol **Telegramga yuborishga urinadi**, lekin guruh/toifa/sotuvchi/obuna va pauza shartlari baribir tekshiriladi. Moderator bu tugmadan foydalana olmaydi.

Avtomatik aylanish uchun `RUN_MODE=all` yoki alohida `poster` processi ishlashi, bot guruhda admin bo‘lishi, guruh va «E’lon joylash» yoqilishi, toifa shu guruhga biriktirilgan/faol, e’lon tasdiqlangan va obuna faol bo‘lishi kerak. Tinch soat/kunlik limit/intervalni ham tekshiring. Telegramga yuborish natijasi **noma’lum** qolgan postni ko‘rmasdan takroriy «Hoziroq» bosmang.

## 9. «💰 To‘lovlar» — rekvizit va chekni qo‘lda ko‘rish

1. Admin «💰 To‘lovlar» → «💳 Rekvizitlar (kartalar)» → «➕ Yangi karta»: nom, **16–19 raqamli** karta, egasi (`-` mumkin), bank (`-` mumkin), sotuvchiga ko‘rinadigan izoh (`-` mumkin), valyuta (`-` = `UZS`). Karta kartochkasida faollik, tartib, tahrir va tarixni saqlab «to‘xtatish» bor. Bir nechta faol karta bo‘lsa tanlash ketma-ket aylanadi. Raqamni faqat admin panelga kiriting; **PIN/CVV so‘ralmaydi**.
2. Sotuvchi tarifni tanlab to‘lov qiladi va chek rasmini yuboradi; «Chek rasmi majburiy» o‘chiq bo‘lsa cheksiz yuborishi mumkin. Hatto bonus bilan bankka `0 UZS` bo‘lsa ham **admin tasdig‘i zarur**.
3. Admin «📥 Kelgan cheklar» → chek kartasida sotuvchi, tarif, summa, rekvizit va rasmni ko‘radi. **Bank hisobidagi haqiqiy kirimni alohida tekshiring**: chek surati to‘lovning o‘zi emas. «✅ Tasdiqlash» → «✅ Ha, bankda tekshirdim» shundan keyingina obunani beradi/uzaytiradi. «❌ Sabab bilan rad etish» → tayyor yoki qo‘lda sabab yuboradi. 🔴 takroriy chekni tasdiqlab bo‘lmaydi; «🕘 To‘lovlar tarixi»da qarorni qayta ko‘ring.

To‘lovlar va kartalar **faqat admin/super-admin** uchun. Demo davomida haqiqiy pul o‘tkazmasini simulyatsiya qilib bankda tasdiqlanmagan chekni «tasdiqlash»ga bosmang; test sotuvchiga tarifni qo‘lda berish xavfsizroq.

## 10. «🛡 Posbon» — guruhdagi qoidabuzarliklar

Panel → «🛡 Posbon» → **guruhni tanlang** (yoki guruh kartasidan). «Posbonni yoqish/to‘xtatish» yoqilganda u **🧪 sinov** holatiga qaytadi. Guruh switchi, global switch, guruhning faol holati va botning Telegram huquqlari ham zarur. Tugmalar:

- «Havolalar», «Forward», «@mention», «Guruh adminlari istisno»; «🌐 Oq ro‘yxat domenlari» (`example.uz`), «🚫 Taqiqlangan so‘zlar» (vergul/yangi qatorda, har biri ko‘pi bilan 300 ta; so‘z 2–50 belgi). Ro‘yxatni tozalash uchun `-` yuboring.
- «📊 Jazo rejimi»: **warn** — jonli holatda xabarni o‘chirish va ogohlantirish, mute/ban emas; **mute** — ogohlantirish chegarasidan so‘ng vaqtincha cheklash; **ban** — alohida tasdiqdan keyin ikki baravar chegarada doimiy ban ehtimoli. «🎯 Ogohlantirish chegarasi» (1–200), «⏱ Mute daqiqasi» (1–100800), «🕒 Hisob oynasi (soat)» (1–7200) shu guruhniki.
- «📋 Sabab-amallar jurnali» va «👤 Foydalanuvchini topish»dan avval **sinovdagi natijani** ko‘ring. Keyin aynan shu guruhda «🧪 Sinov — rejimni almashtirish» → **JONLI REJIMNI TASDIQLASH**. Jonli rejimda haqiqiy xabarlar o‘chishi/jazo qo‘yilishi mumkin. Xatoda guruhni pauzalang yoki yana sinovga qaytaring; bir guruhning sozlamasi boshqasini o‘zgartirmaydi.

## 11. «🧹 Tozalovchi» va «🔑 Ruxsatlar» / «👤 Foydalanuvchilar»

**Tozalovchi:** paneldan guruhni tanlang → «Tozalovchini yoqish/to‘xtatish» → «Kirdi-chiqdi», «Xizmat», «Havolalar», «Qoidabuzar xabar», «Eski e’lonlar», «Mahkamlanganni saqla» switchlarini sozlang. «🔢 E’londan nechta qolsin» — 1–200; «⏱ Xabarni kechiktirish» — 0–36000 soniya. Avval «📋 Tozalash jurnali»da 🧪 natijani ko‘ring, keyin **faqat shu guruh** uchun «🧪 Sinov — rejimni almashtirish» → jonli tasdiq. Telegram xabarni boshqalarning nomidan tahrirlamaydi: jonli tozalash — **o‘chirish**. «Eski e’lon nusxalari» tezkor tugmasi ham jonli tasdiqni chetlab o‘tmaydi.

**Ruxsatlar:** «🔑 Ruxsatlar» → guruhni tanlash yoki «🌐 Global ruxsatlar» → «➕ Ruxsat berish» → odamning **raqamli ID**si → istisno turi («Hammasidan ozod», «Posbondan ozod», «Tozalovchidan ozod», «Havola yuborish») → muddat `1–3650` kun yoki `0` doimiy → sabab (3–255 belgi) → **tasdiq**. Global istisno barcha guruhlarga, guruhniki faqat shu guruhga ta’sir qiladi; ro‘yxatda amal qilish sanasi ko‘rinadi, kerak bo‘lsa qaytarib oling. **Eslatma:** «Sanoqchidan ozod» turi koddagi ro‘yxatda bo‘lsa ham hozirgi adminning ruxsat berish tugmalarida yo‘q; panelda uni berish mumkin deb hisoblamang.

**Foydalanuvchilar:** «👤 Foydalanuvchilar» → ID bo‘yicha qidirish/holatini ko‘rish: guruh kesimidagi ogohlantirish, cheklov va qoidabuzarlik tarixi. Guruh kontekstida admin «⏱ Qo‘lda mute (10 min)» yoki «🚫 Qo‘lda ban»ni sabab va **alohida jonli tasdiq** bilan berishi, cheklovni bekor qilishi yoki ogohlantirishni nollashi mumkin. **Ommaviy guruhda tajriba qilmang.** «🛑 GURUHNI FAVQULODDA PAUZA» ham aynan tanlangan guruhda alohida tasdiqlanadi.

## 12. «🧮 Sanoqchi» (kanal sharti ixtiyoriy)

1. «🧮 Sanoqchi» → **guruhni tanlang** → «Sanoqchini yoqish/o‘chirish». Yangi/yoqilgan guruh dastlab 🧪 sinovda. «👥 N» — nechta odam taklif qilish sharti (`0–1000`); «⏳ Qolish» — a’zo necha daqiqa qolishi (`0–100800`); «📆 Kunlik» va «🔗 Havola limiti» — `1–1000`. Manbalar: «Havola orqali» va/yoki «Qo‘lda qo‘shish»; «DM xabar» ham alohida switch.
2. Kanal talab qilinsa «✅ Majburiy kanal»ni yoqing. «📣 Shu guruh kanallari» faqat unga xos; «🌐 Umumiy kanallar» tegishli **barcha guruhlarga** ta’sir qiladi, lekin faqat ularda kanal sharti yoqilgan bo‘lsa. «➕ Kanal qo‘shish» → kanal `@username` yoki `-100...` ID; xususiy kanal uchun `-100... https://t.me/+...`. Bot **kanal administratori** bo‘lsin. Xususiy havolaning haqiqatan shu kanalga mosligini operatorning o‘zi tekshirsin. Kanal sharti yoqilib, kanal kiritilmagan bo‘lsa jonli rejim yoqilmaydi.
3. «SOFT (delete)» — shart bajarilmasa xabarni o‘chirish; «HARD (mute)» — bunga qo‘shimcha cheklash. HARDni tanlash **qaytadan 🧪 sinovga** o‘tkazadi. Avval «📋 Hisob va sozlama tarixi»ni, N/kanal/a’zolik natijasini tekshiring; so‘ng «🧪 SINOV rejim» → tasdiq bilan **🔴 JONLI**. Botning guruh va kerak bo‘lsa kanal huquqlari tasdiqlashda Telegram orqali qayta tekshiriladi.
4. «👤 A’zo hisobi (+/−/0)» → ID: hisobi va auditini ko‘ring. Qo‘lda o‘zgartirishda `2 hisob xatosi` kabi **−10000…+10000 miqdor + sabab** yuboring; nolga tushirish yoki shaxsiy havolani bekor qilish alohida tasdiqlanadi. Foydalanuvchi bot bilan shaxsiy chatda `/takliflarim` → guruhni tanlaydi, shaxsiy havolasini va holatini ko‘radi. Telegram a’zolikni aniqlay olmasa bot **jazo bermaydi**. Sanoqchi guruh bo‘yicha; 13-bo‘limdagi sotuvchi referali bilan **bir xil tizim emas**.
5. **A’zoga tushuntirish:** jonli SOFT xabarni o‘chirsa yoki HARD yangi a’zoni muvaffaqiyatli mute qilsa, bot shu guruhda sabab va «botni ochish → shaxsiy `/start` → `/takliflarim`» yo‘lini yozadi. A’zo botga oldin `/start` bosmagan bo‘lsa ham guruhdagi izoh ko‘rinadi; **individual hisob ommaga yozilmaydi**. Shu a’zo uchun shu guruhda izoh 60 soniyada ko‘pi bilan bir marta yuboriladi, taxminan **15 soniyadan keyin** botning o‘zi o‘chiradi. Bu uchun botda guruh xabarlarini o‘chirish huquqi va `RUN_MODE=all` yoki ishlayotgan alohida **poster** (1 soniyalik job) kerak. 🧪 sinov, o‘chirilgan qoida, istisno yoki Telegramning noaniq javobida izoh ham yuborilmaydi. Global switch odatda yoqilgan turadi, bir guruhni sozlash uchun uni bosish shart emas; o‘chirilsa barcha guruhlardagi sanoqchi to‘xtaydi. Poster to‘xtab tursa o‘chirish kechikadi; Telegram/DBda xato yoki bot huquqi yo‘qolsa avtomatik o‘chirish kafolatlanmaydi.

## 13. «🤝 Referal» — sotuvchi bonusi

Standart holat **pauza**. Bu Telegram guruhiga odam qo‘shish sanoqchisi emas: sotuvchi bergan `ref_<kod>` havolasi bilan **yangi** foydalanuvchi botga shaxsiy `/start` qiladi. Panelda «💳 Birinchi chek» (tavsiya etiladigan standart) yoki «📋 Shart: ro‘yxatdan o‘tish» (to‘lovsiz bonus xavfi sabab **tasdiq** talab qiladi); «📆 Kun», «💰 Balans», «% Chegirma» turi; «🎁 Bonus miqdori», «📆 Kunlik limit», «💳 Minimal chek (UZS)»ni belgilang. Tur o‘zgarsa bonus miqdori xavfsizlik uchun standartga qaytadi — qayta tekshiring. «🏆 Top-10» natijani ko‘rsatadi. Kunlik limit 1–500; kun bonusi 1–3650, balans bonusi 1000–10000000 so‘m, minimal chek 0–9 999 999 990 so‘m. **Chegirma 1–50%**: 50%dan oshirish manfiy chek xatari tufayli ruxsat etilmaydi. Hammasi to‘g‘ri bo‘lsa «🟢 Yoqish (tasdiq)»ni bosing; «⏸ O‘chirish» eski yozuvlarni o‘chirmaydi. Har foydalanuvchi bir marta, kunlik limit bilan hisoblanadi; birinchi chekni **bank bo‘yicha admin** tasdiqlaydi. `0` so‘mlik bonus ham avtomatik obuna bermaydi.

## 14. «📊 Statistika», «✍️ Bot matnlari», «⚠️ Xatolar jurnali»

- **Statistika:** kechagi kun, 7 yoki 30 kunlik ko‘rinish; «👥 Guruhlar kesimi»da guruhni tanlang. Kunlar `Asia/Tashkent` (sozlangan timezone) bo‘yicha **00:10**dan so‘ng jamlanadi; hozirgi kun to‘liq emas. Admin/super-admin «📥 CSV» oladi; unda moliyaviy ma’lumot bo‘lishi mumkin, begonalarga yubormang. Chekda guruh belgilanmagani uchun **guruh daromadi hisoblanmaydi**, bank summasi faqat umumiy kesimda.
- **Bot matnlari:** kalitni tanlang → «👀 Ko‘rish (preview)» → admin «✏️ Tahrirlash» yoki «♻️ Zavodga qaytarish». Tahrirda 1–2800 belgi, **faqat shu shablondagi** `{placeholder}`lar va ruxsat etilgan `<b>`, `<i>`, `<u>`, `<s>`, `<code>`, `<pre>` HTML teglari; kod yaroqsiz formatni rad etadi. Previewni yuborishdan oldin sinang. Bu xabarlar umumiy bot matnlari; guruhga maxsus salomlashuvni ishga tushirish paneli emas.
- **Xatolar jurnali:** «⏳ Ochiq», «🔴 Kritik», «✅ Hal qilingan», «📚 Hammasi» → manba/vaqt/izohni ko‘ring. «✅ Hal qilindi» tasdiqdan keyin **faqat yozuvni belgilaydi**, asl muammoni avtomatik tuzatmaydi. Botning Replit loglari, `/health` va DB/Redis holatini ham ko‘ring. Ushbu bo‘lim faqat admin/super-admin uchun.

## 15. «📣 Broadcast» — ommaviy shaxsiy xabar

**Faqat admin/super-admin**, faqat ehtiyotkorlik bilan: «➕ Barcha shaxsiy foydalanuvchilar», «➕ Sotuvchilar» yoki «➕ Adminlar» → **bitta matn yoki rasm** (caption ixtiyoriy) → qoralama kartasi. Avval «👀 Faqat menga sinov yuborish»ni bosing. «✅ Tarqatishni tasdiqlash» → son/auditoriyani ko‘ring → faqat haqiqatan kerak bo‘lsa «✅ Ha, hammaga yuborish». So‘ng qabul qiluvchilar ro‘yxati muzlatiladi, poster fon navbatida yuboradi; «⚙️ Tezlikni sozlash» `1–25 xabar/sekund`. Global broadcast switchi ham yoqilgan bo‘lsin. Replitda Redis yo‘q va `DEV_MODE=true` bo‘lsa faqat yakka processli sinov; productionda Redis bo‘lmasa yuborish to‘xtaydi.

Faqat botga **shaxsiy `/start` qilgan**, bloklanmagan va `/xabarlar_stop` bilan voz kechmaganlar auditoriyaga kiradi; guruh a’zolariga faqat guruhda turgani uchun DM ketmaydi. Foydalanuvchi `/xabarlar_on` bilan qaytadi. «⏸ Pauza»/«▶️ Davom ettirish»/«🚫 Bekor qilish» oldin yetib borgan xabarlarni qaytarib olmaydi. «⚠️ Qo‘lda tekshirish» — tarmoq natijasi noma’lum; avtomatik qayta yubormang, kerak bo‘lsa «✅ Tekshirildi, qayta yubormay yopish» bilan yoping. Sinov auditoriyasidan tashqariga xabar jo‘natishni **demo uchun ishlatmang**.

## 16. «🛠 Adminlar» — faqat super-admin

«➕ Admin qo‘shish» → u avval botga shaxsiy `/start` yuboradi → uning `/id`dagi raqamli IDsi → «👑 Super» / «🛠 Admin» / «✅ Moderator» → **tasdiq**. Kartada rolni o‘zgartirish, adminlikdan chiqarish yoki nofaol adminni qayta qo‘shish mumkin; amallar «📋 Amallar tarixi»ga yoziladi. O‘zingizning va `ADMIN_IDS`dagi himoyalangan super-adminning huquqini paneldan olib tashlay olmaysiz. Eng kam zarur huquqni bering; bank/chek ishlari uchun moderatordan foydalanmang.

## 17. Birinchi xavfsiz sinov va muammolarni topish

1. **Bitta alohida test superguruh** va **bitta test sotuvchi** bilan boshlang. Privacy Mode, Telegram huquqlari va guruh kartasidagi «Huquqlarni tekshirish»ni tasdiqlang. Guruh/toifa/postingni sozlang, e’lonni ko‘rib, test guruhida navbatni tekshiring. Pul o‘tkazma, broadcast va jonli jazo sinovlarini begona guruh/odamlarga qo‘llamang.
2. Posbon, tozalovchi va sanoqchini bittadan guruhda avval **🧪 sinov** qiling; jurnalni tekshirmasdan JONLIga o‘tmang. Adashsangiz guruhni «⏸ To‘xtatish» yoki global switch orqali pauzalang, lekin qoidalar saqlanib qolishini esda tuting.
3. **Panel ochilmasa:** `/id`dan chiqqan ID `ADMIN_IDS`da ekanini, botga shaxsiy `/start` bosilganini, seed va bot ishga tushganini tekshiring. **Guruh ko‘rinmasa:** botning `my_chat_member` yangilanishini olganini, roli/huquqlari va polling ishlayotganini, keyin ro‘yxatni yangilang. **Post ketmasa:** guruh/toifa/e’lon/obuna holati, tinch soatlar/kunlik limit, `RUN_MODE=all`/poster loglari, global/mahalliy pauzalarni tekshiring.
4. **Siyosat faqat jurnalga yozsa:** 🧪 dry-run va barcha 3 daraja (global, guruh, siyosat `enabled`)ni ko‘ring; jonli tasdiqni faqat xavfsiz guruhda bering. **Kanal ishlamasa:** bot kanal adminligini va `@username`/IDni tekshiring. **Chek kelmasa:** faol rekvizit, sotuvchining tarif/obunasi va `receipt_required`ni tekshiring; tasdiqni faqat bank kirimi bilan qiling.
5. Replit sinovi **ishlab chiqarish qabul sinovi emas**: real PostgreSQL/Redis, Telegram supergroup/kanal, TLS/webhook, bankdagi haqiqiy kirim, backup/restore va ko‘p worker poygasi alohida test muhitida tasdiqlanishi kerak. Oflayn testlar va operator ro‘yxati uchun [README.md](../README.md) va [DEPLOY.md](DEPLOY.md)ga qarang.
