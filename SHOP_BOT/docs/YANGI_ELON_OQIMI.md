# Yangi e’lon oqimi — bajarilgan ishlar va keyingi bosqichlar

**Holat (2026-10-17):** 1-bosqich (guruhga bevosita odam qo‘shish) va alohida ruxsat olingan **2-bosqich (soha guruhi + 30 kunlik bepul e’lon)** kodlangan. Pullik tarifni har kim sotib olishi va barcha pullik/bepul kampaniyalarning yagona mustaqil Start/Stop tizimi **hali bajarilmagan**; har yangi bosqich oldidan alohida ruxsat kerak. Oflayn tekshiruvlar jonli Telegram/PostgreSQL/Redis sinovi o‘rnini bosmaydi.

## 1. Guruhning o‘zida qo‘lda yozish — bajarilgan

- Oddiy a’zo bot menyusiga kirmaydi, maxsus havola olmaydi. Telegram guruhining **«A’zo qo‘shish»** tugmasidan foydalanadi. Shu guruhdagi tasdiqlangan, alohida yangi odamlar sanaladi; atributsiya noma’lum/o‘zini/botni/takrorni sanamaydi. Admin har guruhda N va minimal qolish muddatini belgilaydi.
- Guruhga qo‘lda yozish oralig‘i Telegram **Slow Mode**da sozlanadi. Sanoqchi jonli bo‘lsa barcha oddiy xabarlarni tekshirishi mumkin; avval test guruhida yoqing.
- Taklif sharti sabab guruhdagi bot matni **aynan** «Guruhga yozish uchun odam qo‘shing.» — son, havola, tugma, `/start`, menyu va qo‘shimcha DM yo‘q. Spam cheklovi va taxminan 15 soniyalik o‘chirish navbati saqlanadi.
- Yangi guruhda `added_by=true`, `link=false`, `notify_inviter=false`, biroq sanoqchi default o‘chiq/dry-run; eski guruhlar yashirincha o‘zgarmaydi. Faol, sinov bo‘lmagan va shu guruhni qamragan pullik tarif egasiga **guruhda qo‘lda yozish** uchun taklif sharti qo‘yilmaydi.

## 2. Bot orqali bepul e’lon — bajarilgan

### Admin uchun ishga tushirish

1. **Alembic migratsiyasi** (`871c32b421d5`) qo‘llanadi. Eski guruhlar uchun `group_settings.free_ads_enabled=false`: pullik guruhlarda bepul dastur kutilmaganda yoqilmaydi.
2. Bot guruhda admin, guruh **supergroup**, faol toifa shu guruhga biriktirilgan va «E’lon joylash» yoqilgan bo‘lsin.
3. «👥 Guruhlar → guruh → 🧩 Funksiyalar»da **🎁 Bepul e’lonlar**ni har guruhda alohida yoqing. **Sanoqchi** ham shu guruhda jonli (`enabled=true`, `dry_run=false`, `added_by=true`, `required_n>0`, `group_settings.counter_enabled=true`) bo‘lishi kerak. Bu bepul yo‘l uchun majburiy kanal obunasini qo‘ymang (`require_subscription=false`). Tugma N ni/joylashni avtomatik yoqmaydi.
4. `required_n` va `min_stay_minutes` — shu guruhning Sanoqchi sozlamalari; bepul shaxsiy taymer `group_settings.interval_sec`dan (kamida 60 soniya), kunlik umumiy limit/tinch soat/timezone esa guruhning mavjud sozlamalaridan olinadi. Interval o‘zgarsa yoki guruh qayta yoqilsa faol due’lar yangi oraliqqa qayta qo‘yiladi. Bepul e’lon yangi **tarif** sifatida pullik katalogga kirmaydi.
5. «🎁 Bepul e’lonlar» navbatida rasm va matnni ko‘rib tasdiqlang yoki rad eting; har tahrir **alohida** tasdiqlanadi. Ro‘yxat tasdiqlangan e’lonlarni ham ko‘rsatadi: tasdiqni ikki qadamda bekor qilish o‘sha e’lonning keyingi postlarini to‘xtatadi (user Start bilan aylanib o‘tolmaydi), ammo yuborilayotgan post tugamaguncha bekor qilishga ruxsat yo‘q. Qaror tarixi `action_log`da saqlanadi. Admin xabari yetmasa navbat bazada turadi.

### Foydalanuvchi uchun yo‘l

- Shaxsiy `/start` yoki `/elon` → «📢 E’lon joylash — guruhni tanlash» → **guruh nomli tugma** → shu guruhga xos bepul/pullik shartlar → «🎁 Bepul e’lon». **Sotuvchilik arizasi, pullik obuna yoki shaxsiy havola talab emas.** Oddiy pullik xarid hali ochilmagan; «💳 Pullik imkoniyat» faqat ma’lumot beradi, avvalgi sotuvchi kabineti o‘zgarishsiz.
- Foydalanuvchi guruh a’zosi bo‘lishi kerak. Guruhning o‘zida «A’zo qo‘shish» orqali N ta haqiqiy do‘st qo‘shadi. Telegram a’zolik va minimal qolish muddatini tekshirgandan keyin `InviteEvent.counted=true` bo‘ladi. **Faqat `source=added_by`** sanaladi: umumiy/shaxsiy havola, adminning qo‘lda bonus krediti va boshqa guruh taklifi bepul oy uchun yaramaydi.
- Bitta surat va uning kamida 10 belgili, ko‘pi bilan 900 UTF-16 birlikli izohida e’lon+aloqa matni yuboriladi (emoji 2 birlik sanaladi); albom qabul qilinmaydi. Preview → «Adminga yuborish»; admin faqat **shu** rasm/matnni tasdiqlaydi. Yangi/tahrirdagi tasdiqlanmagan mazmun guruhga **hech qachon** chiqmaydi. Tahrir rad etilsa avvalgi tasdiqlangan mazmun saqlanadi; qayta ishga tushganda faqat o‘sha mazmun chiqadi.
- Admin tasdig‘i, shu guruhdagi **N ta tasdiqlangan, sarflanmagan qo‘shilish**, foydalanuvchining joriy a’zoligi va «Boshlash» istagi bir vaqtda bajarilganda **30×24 soat** boshlanadi (taqvim oyi emas). Birinchi urinish **shu odamning** guruh intervali o‘tgach, keyingisi oxirgi muvaffaqiyatli postdan keyin; dastlab yuborilganda «Boshlash» istagi avtomatik, «⏹ To‘xtatish / ▶️ Boshlash» faqat shu bepul e’lonni boshqaradi. Bot `/start` kampaniya starti emas. Stop/tahrir muddatni to‘xtatmaydi yoki uzaytirmaydi.
- Har **foydalanuvchi+guruh**da bitta joriy bepul e’lon, bir nechta guruhda alohida e’lon mumkin; bu umr bo‘yi bir dona degani emas. 30 kun tugagach **yangi N ta boshqa tasdiqlangan taklif** sarflanib navbatdagi davr ochiladi; eski event `free_invite_uses.event_id` noyobligi sabab qayta ishlatilmaydi. Qo‘lda yozish uchun `CounterTotal` alohida: oldingi tasdiqlangan direct-add takliflar birinchi davrda ishlashi mumkin; minimal muddatdan keyin tark etgan invitee krediti orqaga olinmaydi.
- Bepul postlar pullik `Ad/Subscription`dan alohida yuboriladi. Guruhning **umumiy 30 daqiqalik pullik navbati** bepul odamning taymerini to‘smaydi: bir guruhga due bo‘lganlardan har 10 soniyalik tick’da bittasi, Telegram umumiy 2 soniya texnik bo‘shlig‘i va mavjud kunlik limit/tinch soatlar hamma postlarga tatbiq etiladi. Sig‘im yetmasa aniq daqiqa kafolat emas. Noma’lum Telegram natijasi avtomatik qayta yuborilmaydi — guruh pauza, adminga xabar, qo‘lda tekshiruv. Muvaffaqiyatli/yakunlangan bepul post jurnali 90 kundan keyin tozalanadi; `sending`/`uncertain` qo‘lda tekshirilguncha saqlanadi. Global pauzada overdue post «qarz» sifatida to‘planmaydi.

## 3. Keyingi alohida ruxsatli bosqichlar

1. **Oddiy odamga pullik xarid**: tarif narxi, suratlar soni, intervali, guruhlar, to‘lov/moderatsiya; faol pullik tarif bilan shu guruhda taklif majburiyati yo‘q. Mavjud seller/payment modullarini xavfsiz ulang.
2. **Barcha pullik va bepul foydalanuvchiga yagona kampaniya Start/Stop**: tarifga xos individual 5/10 daqiqa, birinchi post Start+interval, odil texnik navbat. Hozir bepul oqimning shaxsiy taymeri/Start/Stop bor, lekin eski **pullik** poster hali guruh/toifa aylanma navbatida; uni tayyor individual tarif rejimi deb ko‘rsatmang.

Har yangi bosqich oldidan alohida ruxsat olinadi. Replitni foydalanuvchi o‘zi yangilatadi. Jonli testda avval sinov superguruhida bot huquqlari, qo‘lda qo‘shish, moderator, 30 kun/Stop/interval, PostgreSQL+Redis va Telegram cheklovlari tekshiriladi.
