# 🛒 SHOP-BOT — Telegram guruhlari uchun e’lonlar boti

Sohalar bo‘yicha **superguruhlarga** tasdiqlangan e’lonlarni shaxsiy oralig‘ida yuboradi. Guruhdagi odam qo‘shish talabi, bepul 30 kunlik huquq, pullik tarif/chek va moderator qarorlari alohida boshqariladi. Bot kanallar bilan ishlamaydi; guruh qoidalari har guruhda mustaqil. **Oflayn tekshirilgan**, jonli Telegram, bank, Replit, PostgreSQL/Redis va tiklash sinovi hali talab etiladi.

> **Joriy manba:** [e’lon oqimi va aniq qoidalar](docs/YANGI_ELON_OQIMI.md) · [adminning amaliy qo‘llanmasi](docs/ADMIN_QOLLANMA.md) · [holat va davom ettirish](HOLAT.md) · [deploy/backup](docs/DEPLOY.md). [REJA.md](REJA.md) — tarixiy v1 texnik reja: undagi guruh/toifa intervali, kunlik kvota va kanal bo‘yicha eski qoidalar **amal qilmaydi**. Har yangi bosqich oldidan alohida ruxsat olinadi.

## Hozir qanday ishlaydi?

- Foydalanuvchi shaxsiy `/start` yoki `/elon` → guruh nomli tugma → **bepul yoki pullik** imkoniyat. Sotuvchilik arizasi oldindan talab etilmaydi. Bot `/start`i reklama kampaniyasi Starti **emas**. Bosh sahifada qolgan muddat, e’lon/guruh soni, haqiqiy navbat va shaxsiy interval; aloqa/yordam bitta tugma.
- **Bepul:** faqat e’lon chiqadigan guruhning o‘zida, Telegramning «A’zo qo‘shish» tugmasi bilan N ta boshqa haqiqiy a’zo (eski taklif havolasi Nga kirmaydi); minimal qolish, joriy a’zolik va admin tasdig‘i. Huquq **30 × 24 soat**, **bir surat**, muddat ichida e’lonni almashtirish va qayta tasdiqlatish mumkin. Har user+guruhning joriy e’loni mustaqil; yangi 30 kun uchun yangi N kerak. Admin belgilaydigan **bitta umumiy bepul reja oralig‘i** (standart 30 daqiqa), yangi guruhda bepul e’lon opt-in **OFF**. Admin aynan bir bepul e’lonni tasdiqni bekor qilmasdan pauza/qayta yoqa oladi.
- **Pullik:** foydalanuvchi narxi musbat/sinov bo‘lmagan tarifni sotib oladi. Bank kirimini admin tekshiradi, chek tasdig‘i obuna beradi; mazmun moderatsiyasi baribir kerak. Tarifning **narx, muddat, umumiy e’lon/surat limiti, shaxsiy joylash oralig‘i** o‘zida (1–1440 daqiqa). Yangi pullik e’lon admin tasdiqlangach **egasi «▶️ Boshlash»ni bosmaguncha post ketmaydi**; birinchi urinish Start + tarif oralig‘i, so‘ng oxirgi muvaffaqiyatli post + oraliq. «⏸ Pauza»/«▶️ Boshlash» holatga qarab almashadi. Tahrir yangi moderatsiyani talab qiladi, qayta yuborish yangi slot olmaydi. Xarid paytidagi shartlar chek/obuna/grant tarixida saqlanadi; keyingi tarif tahriri oldingi xaridni o‘zgartirmaydi. Pullik tarif egasiga qamralgan guruhda N taklif talabi qo‘yilmaydi.
- **Guruh kartasi:** «👥 Odam qo‘shish sharti / Sanoqchi», «🧹 Tozalash», «🛡 Xavfsizlik» mustaqil; xavfsiz 🧪 sinov → alohida 🔴 jonli tasdiq. Admin «👤 Foydalanuvchilar» ro‘yxati va ism/`@username`/ID qidiruvi orqali tarif, e’lon, guruh, holat va bepul e’lon kartalarini topadi. Guruhdagi N ogohlantirishi **faqat «Guruhga yozish uchun odam qo‘shing.»**, taxminan 15 soniyadan keyin o‘chiriladi. Qo‘lda yozish oralig‘ini Telegram Slow Mode’da sozlang.
- Guruh/toifa umumiy tijoriy intervali, jitter, tinch soat, **kunlik kvota** va majburiy kanal tekshiruvlari joriy UI/runtime’da yo‘q. Texnik navbat (bir guruhda bittadan yuborish, umumiy Telegram tezlik himoyasi) kunlik kvota emas. Eski kanal/kvota/havola ustunlari tarixiy ma’lumotni saqlash uchun DBda qolgan, kanal va havola talabi migratsiyada faolsizlantirilgan; avvalgi link kreditlari joriy N hisobidan ayriladi, xom tadbirlar o‘chirilmaydi.

## Xavfsiz lokal sinov (faqat `SHOP_BOT/`)

Bu buyruqlarni hech qachon foydalanuvchining jonli bazasida tasodifan ishlatmang. `.env.example`dan lokal `.env` yarating, **test token/baza**ni va `ADMIN_IDS`ni kiriting; haqiqiy tokenni Git/chatga qo‘ymang. SQLite — bir processli vaqtinchalik sinov, production emas. Python talablarini [requirements.txt](requirements.txt)dan o‘rnating.

```bash
cd SHOP_BOT
python3 -m pip install -r requirements.txt
mkdir -p data
# .env: DB_URL=sqlite+aiosqlite:///./data/shopbot.db, DEV_MODE=true,
#       USE_WEBHOOK=false, RUN_MODE=all, test BOT_TOKEN, ADMIN_IDS
alembic upgrade head                 # shu jumladan a7c890e42d1b
alembic check
python3 -m scripts.seed              # mavjud tarif va admin matnlarini o'chirmaydi
python3 -m app.main
```

Alohida test rejimida:

```bash
PYTHONPATH=. python3 -m pytest -q
python3 -m compileall -q app alembic scripts tests
python3 -m scripts.load_smoke --groups 4 --ads 40 --hours 3
```

**428/428 offline test** va o‘zgargan kodga Ruff/compileall, SQLite toza/eski ma’lumotli migratsiya, `alembic check`, seed ×2 hamda qisqa smoke sinovlari o‘tgan. Oflayn testlar real Telegram bot huquqi, flood wait, bank tasdig‘i, ko‘p worker yoki PostgreSQLning transaction semantikasini to‘liq tasdiqlamaydi.

## Joylash va huquqlar

- Telegram **superguruhi**; botni administrator qiling (xabar o‘chirish, HARD xavfsizlik rejimi kerak bo‘lsa a’zolarni cheklash), Privacy Mode’ni @BotFather’da **Disable** qiling. N uchun botga taklif havolasi yaratish huquqi shart emas. Telegram **kanali kerak emas**. «👥 Guruhlar» → guruh → «🔄 Huquqlarni tekshirish», faol toifani shu guruhga biriktiring. Bepul dasturni va Sanoqchini avval sinovda har guruh uchun alohida yoqing.
- Xavfli «🚀 Hoziroq» tugmasi haqiqiy xabar yuboradi. `RUN_MODE=all` yoki alohida poster 15 soniyalik guruh izohini o‘chirish uchun ishlashi kerak. Replitni foydalanuvchi o‘zi yangilaydi; bu kod uni avtomatik deploy qilmaydi.
- Production uchun [DEPLOY.md](docs/DEPLOY.md)dagi sirlar, backup, migratsiya, rollback va qabul ro‘yxatiga rioya qiling. Eski grant narxining migratsiyadan **oldin** tahrirlangan asl qiymati tarixdan tiklanmaydi — dastlabki snapshot migratsiya vaqtida mavjud tarifdan olinadi.
