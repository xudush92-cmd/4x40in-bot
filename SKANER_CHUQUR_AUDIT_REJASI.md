# Telegram skaner: chuqur audit va yaxshilash rejasi

**Audit qilinayotgan kod:** `279c316979a96626f30d871ee30e52d19d44d364`, `telegram_scanner/`.
**Maqsad:** xabarni tezroq ko‘rish, topilmay qolgan xabarlarni kamaytirish va bildirishnomani ishonchli yuborish.
**Chegara:** bu kod va ochiq manbalar auditi; VPS holati, boshqa botning ichki kodi va haqiqiy Telegram trafikining yangi o‘lchovi bu hisobotda tekshirilmagan. Ishlab turgan botga o‘zgartirish kiritilmagan.

## 1. Qisqa xulosa

- Biz har bir akkaunt uchun bitta Telethon client va `NewMessage` handler ishlatamiz. Bu Telegram’dan real-time hodisalar olishning odatiy usullaridan biri; guruhlarni ketma-ket tarixdan aylanib chiqish emas.
- Oldingi nazoratli sinovda ikki guruhda manbadan handlergacha median kechikish 27,7 va 37,5 soniya; to‘rtta boshqa guruhda taxminan 0,8–1 soniya bo‘lgan. Bu sinovda **mos kelgan va yuborilgan bildirishnomalar yo‘q** edi: bildirishnoma yo‘li o‘lchanmagan. Tegishli guruhlarda `channel_difference` yaqinida kechikkan hodisalar qayd qilingan, lekin bitta xabarning kelish yo‘li va triggeri isbotlanmagan.
- Kodda qabul ishonchliligi, Telethon differencelarini kuzatish va Bot API xatolarini boshqarishda tuzatishga arziydigan aniq zaifliklar bor. **Ularning qaysi biri ushbu 30–60 soniya yoki yo‘qolishning asl sababi ekani hozircha ma’lum emas.**
- Faqat filtrni tezlatish, barcha guruhga doimiy polling qilish yoki `catch_up=True` qo‘yishning o‘zi Telegram hali yubormagan/o‘chirilgan xabarni kafolatli tiklamaydi.

## 2. Tizim amalda qanday ishlaydi?

```text
Telegram MTProto → har bir foydalanuvchi uchun Telethon StringSession
  → NewMessage handler → umumiy/tarif/skaner/guruh/emoji/kalit filtrlari
  → bloklangan yuboruvchini tekshirish → guruh/yuboruvchi ma’lumotlari
  → bildirishnomani tuzish → Bot API sendMessage → foydalanuvchi
```

- Handler: `scanner_manager.py:466–730`. Registratsiya ulanishdan oldin bajariladi, ammo akkaunt egasi tasdiqlanguncha handler `ready` ni kutadi. Private chatlar filtrdan o‘tkazilmaydi.
- Filtr `filters.py:evaluate` bitta SQLite ulanishida bir necha tekshiruvni bajaradi. Har bir group hodisasiga `SCAN event` yozuvi tushadi, lekin unda xabar IDsi yo‘q; shu sababli u biror xabarning qabul qilinganini alohida isbotlamaydi.
- Bot API yuborish: `notifier.py:42–99`. Har bir yuborishda yangi `aiohttp.ClientSession` yaratiladi.
- Jarayon `main.py` ichida aiogram va scanner manager’ni bir event loop’da ishga tushiradi. `systemd active` va Telethon `is_connected()` amaliy xabar kelishini kafolatlamaydi.
- Manba va xabar vaqti orasidagi farq devor soatiga bog‘liq; Telegram timestamp aniqligi, vaqt sinxronligi, log rotatsiyasi va selektiv yozish hisobga olinadi. Bot API qabul qilishi telefonda bildirishnoma paydo bo‘lishiga teng emas.

## 3. Ochiq manbalardan tekshirilgan asoslar

1. Telegram superguruh/kanal yangilanishlarida `pts` bo‘yicha uzilishlarni aniqlash va `getChannelDifference` bilan to‘ldirishni ta’riflaydi. 10–100 kabi `limit` bir sahifadagi natijaga tegishli; o‘zi jami 100 tadan keyin hamma narsa yo‘qolishini anglatmaydi. Boshqa, juda eski yoki tiklab bo‘lmaydigan gaplarda `channelDifferenceTooLong` qaytishi mumkin. [1](https://core.telegram.org/api/updates)
2. Telegram ayrim kanallardan passiv yangilanishlar kamayishi mumkinligini yozadi va ochiq ko‘rib turilgan chatlar uchun cheklangan short-polling modelini ta’riflaydi; bunda eng ko‘pi 10 ta chat tavsiya etilgan. Bu 60–100 ta guruhni agressiv polling qilishga ruxsat yoki tezlik kafolati emas. [1](https://core.telegram.org/api/updates)
3. Telethon `StringSession` ma’lumotni xotirada saqlaydi va serializatsiya asosan autentifikatsiya/ulanish uchun zarur ma’lumotni qamraydi. Sessiya oddiy qayta ishga tushganda yangilanish holatining doimiy saqlanishini o‘zi kafolatlamaydi. [2](https://docs.telethon.dev/en/stable/modules/sessions.html), [3](https://github.com/LonamiWebs/Telethon/blob/65c27c5ceda65b3c2980b7d585dacd0f4a55e54f/telethon/sessions/string.py)
4. Ishlatilayotgan Telethon **1.34.0** manbasida `ChannelDifferenceTooLong` javobida yangi `pts` olinib, javobdagi qisman xabarlar handlerga berilmaydi. Bu — koddagi aniq xulq, lekin aynan bizning VPS’da bunday javob bo‘lganining dalili emas. [4](https://github.com/LonamiWebs/Telethon/blob/65c27c5ceda65b3c2980b7d585dacd0f4a55e54f/telethon/_updates/messagebox.py)
5. O‘sha versiyada auto-reconnect handleri `get_me()` dan so‘ng qaytadi; pastdagi catch-up kodi shu joyda bajarilmaydi. Bundan barcha qayta ulanishlarda xabarlar albatta yo‘qoladi degan xulosa chiqmaydi: boshqa Telegram/Telethon mexanizmlari ham mavjud. [5](https://github.com/LonamiWebs/Telethon/blob/65c27c5ceda65b3c2980b7d585dacd0f4a55e54f/telethon/client/updates.py)
6. Telethon handlerlari default holatda parallel task sifatida ishlatiladi; `sequential_updates=True` ularni ketma-ketlashtiradi. Tartib kerak bo‘lsa foydali, ammo sekin handler keyingi xabarlarni navbatda ushlashi mumkin; u tarmoqdan kelmagan xabarni yaratmaydi. [6](https://docs.telethon.dev/en/stable/concepts/updates.html)
7. Bot API `429` javobida `parameters.retry_after` berishi mumkin. Format xatosi, rate limit va tarmoq xatosiga bir xil reaksiya bermaslik zarur. [7](https://core.telegram.org/bots/api)

## 4. Audit natijalari — aniqlik va ustuvorlik

### A. Muhim: `ChannelDifferenceTooLong` diagnostikada ko‘rinmay qolishi mumkin

**Fakt:** `scan_diagnostics.py:record_channel_difference` tez (<1 s), xatosiz, yoshi 10 s ga yetmagan javoblarni yozmaydi. `ChannelDifferenceTooLong` odatdagi `new_messages` maydonidan foydalanmasligi sababli uning `oldest_message_age_ms` qiymati bo‘sh bo‘lishi mumkin. Shunda tez qaytgan bunday javob yozuvga tushmaydi.

**Ta’sir:** bunday javob bo‘lgan-bo‘lmaganini mavjud selektiv diagnostika orqali inkor qilish mumkin emas. Telethon 1.34 da aynan shu javobdagi qisman xabarlar dispatch qilinmasligi sababli bu **muhim ko‘r zona**.

**Tuzatish:** bunday javob turini, xato va tegishli agregat sonlarni har doim yozish; faqat vaqt, javob turi va hisoblar. Xabar matni, telefon, session, auth key yoki update payload yozilmasin. Guruh/owner IDlari zarur bo‘lsa mavjud maxfiy lokal diagnostika chegarasida saqlansin, tashqariga faqat agregat hisobot chiqarilsin. Yozuv soni aylanish va hajm bilan cheklansin.

### B. Muhim: qayta ulanish va o‘tkazib yuborilgan yangilanishlar

**Fakt:** `StringSession` ishlatiladi; `sync_loop` clientning `is_connected()` holatiga qarab qayta ulaydi. Telethon 1.34 auto-reconnect yo‘lida yuqorida qayd etilgan chegaralar bor. Startup owner-verification gate bilan himoyalangan.

**Noma’lum:** avvalgi ikki soatlik jimlik aynan shu sababdan bo‘lganmi yoki qaysi xabarlar yo‘qolganmi — aniqlanmagan. Aiogram Bot API xatosi o‘zicha Telethon uzilganini isbotlamaydi.

**Tuzatish:** qayta ulanish/exception holatlari va update-loop hayotini minimal maxfiy telemetry bilan ajratish; tartibli holat mashinasi, chegaralangan backoff va admin ogohlantirish. Telethon private atributlariga to‘g‘ridan-to‘g‘ri qattiq bog‘lanish oldidan versiya shartlari va testlar kerak. Harakatsiz, lekin guruhlar jim bo‘lishi mumkin bo‘lgan vaziyatda avtomatik restart qilinmasin.

**Keyingi tadqiqot:** yangilanish holatini xavfsiz persist qilish va catch-up mexanizmi prototipi. Avval migratsiya/restart/reconnect, ownership va secret-at-rest sinovlari; StringSession o‘zini o‘chirib, qayta login qilib sinash taqiqlanadi. Bunday mexanizm ham Telegram o‘chirgan yoki juda eski yangilanishni kafolatlamaydi.

### C. Muhim: Bot API yuborish xatolari farqlanmaydi

**Fakt:** `notifier.py:60–99` non-200 javobda darhol boshqa formatdagi yuborishni urinadi. 429 uchun `retry_after` maxsus qayta ishlanmaydi; tarmoq istisnosida `False` qaytadi. Koddа har bir yuborish uchun HTTP sessiya alohida yaratiladi.

**Ta’sir:** rate limitga tushganda formatni almashtirish yordam bermasligi, xabar yuborilmay qolishi mumkin. Bu aynan oldingi 30–60 s kechikishni keltirib chiqargani isbotlanmagan. Timeout paytida Telegram xabarni qabul qilganmi-yo‘qmi noaniq bo‘lishi ham mumkin: ko‘r-ko‘rona retry dublikat yaratadi.

**Tuzatish:** cheklangan timeout va qayta ishlatiladigan HTTP session; 400 format xatolariga mos fallback, 429 uchun `retry_after`, ayrim 5xx/tarmoq xatolariga chegaralangan retry/backoff; foydalanuvchilararo adolat va noaniq yuborish natijasini aniq qayd qilish. Bot API sendMessage’da kafolatli aynan bir marta yetkazish bor deb va’da qilmaslik. Yopilishda sessionni tartibli yopish; himoyalangan matnlarni fallbackda ham chiqarib yubormaslik.

### D. O‘rtacha: sinxron SQLite va qo‘shimcha entity so‘rovlari

**Fakt:** handler ichida `evaluate()` va boshqa SQLite amallari sinxron; SQLite ulanish timeout’i 10 s. Matched xabarda `get_chat()` va `get_sender()` bajariladi; ba’zan keshga, ba’zan so‘rovga bog‘liq. Bu event loopni yoki yuborishni kechiktirishi mumkin.

**Kuzatuv:** oldingi namunada filtr mediani 1 ms, p95 69 ms, maksimal 186 ms; bu namunada filtr asosiy 30–60 s sababga o‘xshamagan. Bitta sekin disk/lock yoki boshqa sharoitni butunlay inkor etmaydi.

**Tuzatish:** avval lock/loop-lag va bosqich vaqtlarini tekshirib, keyin xavfsiz o‘qish snapshot/kesh yoki threadga chiqarishni baholash. Kesh o‘zgarganda darhol invalidatsiya; tarif/blok/Stop holati eskirib qolmasligi shart. Yuboruvchining ismi, original havola, mavjud telefon va per-user bloklash xususiyatlari saqlansin.

### E. O‘rtacha: navbat, yuk va dublikat nazorati

**Fakt:** default Telethon handlerlar task tarzida parallel ishlashi mumkin; bizda maxsus cheklangan qabul/yuborish navbati yoki xabar darajasida doimiy deduplikatsiya ko‘rinmaydi. Guruh yozuvlaridagi duplicate tekshiruvi — boshqa narsa.

**Xavf:** portlashda ko‘p handler, yozuv yoki yuborish yukni oshirishi mumkin; qat’iy ketma-ketlashtirish esa keyingi xabarlarni ushlab turadi. Navbat Telegram’dan umuman kelmagan xabarni qutqarmaydi.

**Tuzatish:** faqat o‘lchov va 1 vCPU/2 GB chegarasiga mos bounded queue/adolatli ish taqsimoti prototipi. To‘lish, kutish va yo‘qotishlar oshkor hisoblanishi, turg‘un xotira/disk limiti, per-user izolyatsiya va ustuvorlik aniq bo‘lishi kerak. Dedupe kaliti kamida owner/chat/message darajasida bo‘lsin; bitta Telegram message ID turli guruhlarda takrorlanishi mumkin. Yuborishdagi noaniq natija va dublikat xavfi alohida ko‘rib chiqilsin.

### F. Pastroq: kutubxona versiyasi va private API

**Fakt:** `requirements.txt` Telethon 1.34.0 ni mahkamlaydi; diagnostika `_call` va `_updates.messagebox` kabi private APIlardan foydalanadi. Kutubxona versiyasini almashtirish bu instrumentatsiyani buzishi mumkin.

**Tuzatish:** yangi 1.x versiyasini alohida test/canary’da taqqoslash, versiyaga xos instrumentation testlari, dependency/security tekshiruvi va rollback. Yangilash avtomatik ravishda tezlik muammosini hal qiladi deb aytmaslik; ishlab turgan sessiyani qayta yaratmaslik.

## 5. Nimalarni hozir qilmaslik kerak

- 60–100 ta guruh uchun tez-tez majburiy `getChannelDifference` yubormaslik; flood/rate limit va sessiya xavfi bor.
- `server_timeout_s=30` ni RPC 30 soniya ishladi deb talqin qilmaslik: RPC davomiyligi alohida o‘lchanadi.
- `sequential_updates=True`, yangi sessiya, qayta login yoki `catch_up=True` ni universal yechim sifatida yoqmaslik.
- Xom Telethon TRACE/DEBUG yangilanishlar, guruh xabarlari, telefon, IDlar yoki session ma’lumotlarini foydalanuvchidan so‘ramaslik yoki logga chiqarmaslik.
- Himoyalangan `noforwards` xabarning xom matnini saqlash/yuborish kabi hozirgi xavfsizlik cheklovlarini zaiflashtirmaslik.
- Kalit, emoji yoki tarif qoidalarini qabul kechikishi uchun dalilsiz o‘zgartirmaslik; foydalanuvchilarning kalit bazasini tozalamaslik.

## 6. Amalga oshirish rejasi

### 1-bosqich: xavfsiz kuzatuv va regressiya testlari

1. Telethon 1.34 `ChannelDifferenceTooLong`, xato va timeoutlarni mazmunsiz, rotatsiyali maxfiy logda aniq hisoblash; tez TooLong javobi yo‘qolmasligiga test.
2. Conn/update-loop/reconnect va `systemd active` tushunchalarini alohida ko‘rsatish. Sessiya xabari yo‘q degani yaroqsiz degani emas; noto‘g‘ri restart bo‘lmasin.
3. `get_chat`/`get_sender`, filtr va Bot API qabul qilish vaqtlarini ixtiyoriy, faqat urinishlar uchun va IDsiz o‘lchash; soat aniqligi cheklovini tushuntirish.
4. 1.34 instrumentatsiyasi va mavjud 60 s sozlamasini versiyaga bog‘liq testlarda tekshirish. 60 s butun messagebox timeout’iga ta’sir qiladi; VPS’da hozir yoqilganini faqat tekshiruv tasdiqlaydi.

**Qabul mezoni:** mazmun/telefon/kalit/sessiya ma’lumoti logga tushmasligi; diagnostika xatosi skanerni to‘xtatmasligi; eski default xulq o‘zgarmasligi.

### 2-bosqich: yuborishning ishonchliligi

1. 429, 400, 5xx va timeoutni ajratish; `retry_after` ga rioya qilish va ortiqcha format fallback so‘rovlarini to‘xtatish.
2. HTTP sessionni boshqariladigan qayta foydalanish; bounded retry va yopilishda tozalash.
3. Noaniq natija, dublikat va foydalanuvchiga adolatli yetkazish siyosatini belgilash.

**Qabul mezoni:** mock Bot API testlari: 429 + retry_after, 400 format fallback, 5xx, timeout, cancellation va bir nechta foydalanuvchi. Himoyalangan xabar testlari saqlansin.

### 3-bosqich: qabul yo‘li va yuk

1. Lokal 1 vCPU/2 GB chekloviga mos synthetic burst / disk-lock / sekin API sinovlari. Xabarni saqlash siyosati va maxfiylik oldindan belgilanadi.
2. O‘lchov oqlasa, bounded queue yoki kesh prototipi; to‘lib ketishni jim yashirmaslik, owner/session/blocked/tariff qoidalarini buzmaslik.
3. `ChannelDifferenceTooLong` va uzilish holatlari uchun **faylsiz sintetik** Telethon testlari; mumkin bo‘lgan tiklash variantlari va limitlarini tekshirish.

**Qabul mezoni:** baseline bilan p50/p95/p99, handler kutish, event-loop lag, o‘tkazilgan/duplicated xabarlar va resurslarni solishtirish; yangi xususiyatlar default xavfsiz va rollback bilan.

### 4-bosqich: ehtiyotkor VPS canary

Oldindan admin roziligi bilan kichik guruh va qisqa muddat; avvalgi konfiguratsiya zaxirasi, restart uzilishi va StringSession cheklovi tushuntiriladi. Agregat natija: qabul qilingan / sinovda yuborilgan, matched, API qabul qilgan, p50/p95, queue overflow, tarmoq/rate xatolari. Xom xabar yoki IDlar tashqariga chiqarilmaydi. Faqat dalil yaxshi bo‘lsa kengaytirish; yomonlashsa rollback.

## 7. Ochiq loyihalardan nimalarni olish mumkin?

- [WorldWatcher](https://github.com/edbarron/worldwatcher) kodida Telethon `NewMessage` va ruxsatli manbalar filtri mavjud; bizning asosiy oqim ham event-based. [8](https://github.com/edbarron/worldwatcher)
- [TeleKeyword-Finder](https://github.com/dark5087knight/TeleKeyword-Finder) kodining ko‘rilgan holatida `NewMessage(chats=...)` ishlatiladi. Bu Python handler ishini kamaytirishi mumkin, lekin tarmoq pushini avtomatik tezlashtirishi isbotlanmagan. [9](https://github.com/dark5087knight/TeleKeyword-Finder)
- [AdBot](https://github.com/YuriiMotov/AdBot) kodining ko‘rilgan holatida dialoglar va o‘qilmagan tarix bo‘ylab yurish hamda limitdan ortiq xabarni tashlab ketish bor. O‘chirilgan xabarni tarixdan topishga kafolat yo‘q. [10](https://github.com/YuriiMotov/AdBot)

Bu loyihalar o‘z README’dagi tezlik da’volarini mustaqil kafolatlamaydi; kod/litsenziya/qaramlik va maxfiylik tekshirilmasdan ko‘chirib ishlatilmaydi. Boshqa foydalanuvchi botining ichki arxitekturasi bu ma’lumotlardan aniqlanmaydi.

## 8. Qaror talab qiladigan masalalar

- Navbat xotiradami yoki diskda bo‘ladimi? Diskka matn yozish maxfiylik va `noforwards` talablariga bog‘liq; avtomatik qabul qilinmaydi.
- Telegram Bot API timeoutida natija noma’lum bo‘lsa: dublikat ehtimoli bilan retry yoki ogohlantirib qo‘lda tekshirish? Aniq bir marta kafolat yo‘q.
- Agar navbat to‘lsa: vaqtinchalik backpressure, foydalanuvchiga ogohlantirish va resurs cheklovi qanday qo‘llanadi?
- Kutubxona versiyasi, prototip va VPS restarti faqat sinov va aniq rollback rejasidan keyin.

## Havolalar

- [1](https://core.telegram.org/api/updates) — Telegram update, PTS va difference mexanizmi.
- [2](https://docs.telethon.dev/en/stable/modules/sessions.html) — Telethon session turlari.
- [3](https://github.com/LonamiWebs/Telethon/blob/65c27c5ceda65b3c2980b7d585dacd0f4a55e54f/telethon/sessions/string.py) — aynan 1.34.0 StringSession.
- [4](https://github.com/LonamiWebs/Telethon/blob/65c27c5ceda65b3c2980b7d585dacd0f4a55e54f/telethon/_updates/messagebox.py) — aynan 1.34.0 messagebox va TooLong.
- [5](https://github.com/LonamiWebs/Telethon/blob/65c27c5ceda65b3c2980b7d585dacd0f4a55e54f/telethon/client/updates.py) — aynan 1.34.0 update loop va reconnect.
- [6](https://docs.telethon.dev/en/stable/concepts/updates.html) — Telethon update dispatch modeli.
- [7](https://core.telegram.org/bots/api) — Bot API `retry_after` va sendMessage.
- [8](https://github.com/edbarron/worldwatcher), [9](https://github.com/dark5087knight/TeleKeyword-Finder), [10](https://github.com/YuriiMotov/AdBot) — ko‘rilgan ochiq loyihalar.
