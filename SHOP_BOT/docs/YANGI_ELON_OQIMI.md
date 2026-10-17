# Yangi e’lon oqimi — kelishilgan talablar va bosqichlar

**Holat (2026-10-17):** 1-bosqich kodlangan; 408/408 oflayn test, Alembic check va seed ×2 o‘tdi. Qolgan bosqichlar yozilmagan. Har yangi bosqich oldidan foydalanuvchidan alohida ruxsat olinadi.

## 1. Guruhning o‘zida qo‘lda yozish — 1-bosqich

- Oddiy guruh a’zosi bot menusiga kirmaydi, maxsus havola olmaydi. Telegram guruhidagi «A’zo qo‘shish» tugmasidan foydalanadi. Faqat shu guruhga yangi, alohida a’zolar qo‘shilgani hisoblanadi. Telegram kim qo‘shganini aniqlamasa boshqa odamga hisob yozilmaydi; o‘zini/botni/takrorni sanamaydi. Admin guruhdagi N va minimal qolish muddatini belgilaydi.
- Guruhga qo‘lda yozish oralig‘i **Telegram Slow Mode** orqali sozlanadi. Bot qo‘lda yozilgan e’lonni oldindan moderatsiya qilmaydi. Sanoqchi jonli bo‘lsa faqat reklama emas, barcha oddiy guruh xabarlarini ham tekshirishi mumkin; uni avval faqat e’lon guruhida sinash kerak.
- Taklif sharti bajarilmagan xabar uchun guruhdagi matn **aynan** «Guruhga yozish uchun odam qo‘shing.»: sonlar, havola, tugma, botga kirish bo‘yicha ko‘rsatma va ortiqcha DM yo‘q. 60 soniya spam cheklovi va taxminan 15 soniyalik o‘chirish navbati saqlanadi.
- Yangi guruhda `added_by` manbasi tayyor, link talab emas, lekin sanoqchi o‘chiq va sinov rejimida. Eski guruhning saqlangan sozlamalari yashirincha almashtirilmaydi; admin qaysi guruhda yoqishni tanlaydi. Shu guruhni qamragan faol pullik tarif egasiga taklif sharti tatbiq etilmaydi. Kanal obunasi sharti qo‘shilmaydi.

## 2. Bot orqali bepul e’lon — keyingi ruxsat

- Ochiq `/start` → «E’lon berish» → **soha guruhi nomi yozilgan tugma** → «Bepul/Pullik». Qisqa matn bilan shu guruhga xos shartlar ko‘rsatiladi. Sotuvchilik arizasi/adminning oldindan ruxsati kerak emas, lekin yangi/tahrirlangan **e’lon mazmunini admin tasdiqlaydi**.
- Bitta bepul reja pullik katalogdan alohida; «umr bo‘yi bitta e’lon» emas. Har guruhga alohida yangi a’zolar olib kelish hisobiga bir oylik huquq, 1 surat, shu muddatda e’lonni almashtirish/tahrirlash. E’lon va taklif boshqa sohaga ko‘chirilmaydi.
- Sanoqchining umrbod `CounterTotal` hisobini bepul davrga tenglashtirmaslik: guruhga xos yangi a’zolar hodisasi va har davrdagi huquq alohida, qayta ishlatilmasdan hisoblanishi kerak. Qo‘lda yozish eshigi va bir oylik bot huquqi bir-biridan mustaqil.

## 3. Pullik tarif va avtomatik poster — alohida ruxsatlar

- Oddiy foydalanuvchi ham pullik tarif sotib oladi. Admin tarifda narx, muddat, e’lon o‘rinlari, har e’londagi suratlar, joylash oralig‘i va ruxsat etilgan guruhlarni belgilaydi. Pullik huquq faol bo‘lsa o‘sha guruhda odam taklif qilish sharti yo‘q. E’lon mazmuni baribir moderatsiyadan o‘tadi. Keraksiz bot media boshqaruvini Telegram sozlamalari bilan takrorlamaslik.
- Har foydalanuvchi + guruhda bitta mustaqil **Boshlash ↔ To‘xtatish** holati va kelgusi vaqt saqlanadi. Bu botning `/start` buyrug‘i emas. Masalan, 5 daqiqalik tarifni 10:00 da boshlash → birinchi urinish 10:05; boshqa odamning 10 daqiqaligi 10:03 dan → 10:13. Keyingi vaqt oxirgi muvaffaqiyatli postdan hisoblanadi, to‘xtatilgan vaqt uchun «qarz» postlar yig‘ilmaydi. Bir odam ayni guruhdagi ko‘p e’lon orqali intervalni aylanib o‘tolmaydi.
- Bir guruhga 30 daqiqada jami bitta post degan umumiy taymer bo‘lmaydi. Bot odamlarni navbat bilan «uxlab» kutmaydi; vaqtlar DBda, vaqti kelganlar adolatli navbatda tekshiriladi. Bir vaqtdagi e’lonlar bir soniyada to‘kib tashlanmaydi, Telegram/kunlik/tinch vaqt/texnik limiterlar saqlanadi. Tarif intervali eng erta vaqt; sig‘im yetmasa aniq daqiqa kafolatlanmaydi.

## Hali tasdiqlanmagan raqamlar va siyosatlar

1. Har guruhda qo‘lda yozish va bepul bot e’loni uchun nechta yangi a’zo kerakligi, ularning bir xil yoki alohida bo‘lishi.
2. Qo‘lda yozish huquqi bir martami yoki davriymi; bepul navbatdagi oy uchun faqat yangi a’zolar sanaladimi; bir xil a’zo qo‘lda va birinchi bepul davrga bir vaqtda yordam berishi mumkinmi.
3. «Bir oy» 30×24 soatmi yoki taqvim oyimi; minimal qolish va keyin chiqib ketish siyosati.
4. Bepul yo‘lda bir guruhdagi faol e’lonlar soni va shaxsiy interval.
5. Guruhlar faqat e’lonlarmi yoki oddiy suhbat ham bormi; pullik foydalanuvchi guruhga qo‘lda yozsa taklifdan ozodligi tasdiqlanishi.

Bu noaniqliklar 2–4-bosqich kodini «tayyor» deb ko‘rsatishga yo‘l qo‘ymaydi. 1-bosqich raqamlarni adminning mavjud har-guruh sozlamasidan oladi; tayyor bo‘lmagan avtomatik e’lon oqimi uchun soxta huquq bermaydi. Real Telegram, PostgreSQL va Redis qabul sinovi oflayn testlardan alohida.
