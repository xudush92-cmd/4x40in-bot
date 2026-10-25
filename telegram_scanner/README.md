# Telegram Scanner

Guruhlardagi xabarlarni berilgan iboralar bo'yicha kuzatib, mos kelgan
mijozlarni **o'sha guruh egasiga** yuboradigan tizim: **boshqaruv boti**
(aiogram) + **har bir foydalanuvchining shaxsiy sessiyasi** (Telethon).

> ⚠️ Markaziy "userbot" rejimi **yo'q**. Har bir foydalanuvchi o'z Telegram
> akkaunti bilan ulanadi, faqat o'zi qo'shgan guruhlar kuzatiladi va
> topilgan xabar faqat shu foydalanuvchiga boradi. **Kalit so'zlar bitta
> umumiy ro'yxat** — ularni faqat admin kiritadi (stop-so'zlar va mijoz
> so'zlari kabi alohida ro'yxatlar yo'q).

## O'rnatish

```bash
cd telegram_scanner
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # ichini o'z ma'lumotlaringiz bilan to'ldiring
```

`.env` uchun kerak bo'ladi:
- `API_ID` / `API_HASH` — https://my.telegram.org → API development tools
- `BOT_TOKEN` — @BotFather dan
- `ADMIN_ID` — @userinfobot dan olingan shaxsiy ID

## Ishga tushirish

```bash
.venv/bin/python main.py
```

`main.py` ikkalasini birga ko'taradi: boshqaruv boti va barcha
foydalanuvchilar sessiyalari. Alohida terminal kerak emas — foydalanuvchilar
akkauntlarini 📱 Akkaunt holati → 🔑 Akkauntni ulash orqali ulaydi.

## Replitda ishga tushirish

1. Replitda **Import from GitHub** qiling (yoki shu papkadagi fayllarni yuklang).
2. Chap menyudagi **Secrets (🔒)** bo'limiga quyidagilarni qo'shing —
   kalitlarni kodga yozmang:

   | Secret nomi | Qiymati |
   |---|---|
   | `API_ID` | my.telegram.org dan (faqat raqam) |
   | `API_HASH` | my.telegram.org dan |
   | `BOT_TOKEN` | @BotFather dan |
   | `ADMIN_ID` | @userinfobot dan (faqat raqam) |

3. **Run** tugmasini bosing (`.replit` sozlangan) yoki:

   ```bash
   python main.py
   ```

   ⚠️ `SESSION_ENCRYPTION_KEY` ni keyinchalik o'zgartirmang — aks holda
   saqlangan sessiyalar ochilmay qoladi.

Eslatma: Replit bepul tarifida loyiha "uxlab" qolishi mumkin — bot
to'xtab qolmasligi uchun Always On / Reserved VM kerak bo'lishi mumkin.

## Rollar: Admin va foydalanuvchilar (biznes, server modeli)

- **Admin** (`ADMIN_ID`, bitta odam): kalitlar (faqat admin kiritadi),
  xabar sharti (standart), tizim stop/start, 🧪 test, 📊 umumiy
  statistika, 👥 foydalanuvchilar, 📝 arizalar, 📣 xabar yuborish.
  Admin ham **o'z akkaunti bilan skanerlaydi**: 📱 Akkaunt holati orqali akkauntini
  ulaydi (tasdiqlash talab qilinmaydi), ➕ Guruh qo'shish bilan o'z
  guruhlarini qo'shadi va 📋 Guruhlarim da ko'radi. Admin guruhlari
  `user_groups` jadvalida o'z `owner_user_id` si bilan turadi, shuning
  uchun boshqa foydalanuvchilarnikidan aralashmaydi. Admin tarif talab
  qilmaydi — bu xatolarni o'z ko'zi bilan kuzatish uchun.
  Har bir foydalanuvchining guruhlari, xabar sharti, skaner holati,
  tarifi, sessiyasi va statistikasi **bitta foydalanuvchi
  kartochkasida** ko'rsatiladi. 👥 Foydalanuvchilar bo'limida avval
  ism-familiya tugmalari chiqadi — bosilsa kartochka ochiladi,
  kartochkada **⬅️ Orqaga** tugmasi bilan ro'yxatga qaytiladi.
  Kartochkadagi tartibli tugmalar: ⏰ Muddat berish, ⛔ Bloklash,
  🔄 Kartochkani yangilash, 🔌 Sessiyani uzish,
  🗑 Foydalanuvchini o'chirish.
- **Registratsiya (QR siz)**: ism-familiya (bitta xabar) → telefon
  `+998...` → kod DARHOL so'raladi va faqat botdagi **raqamli
  tugmalar** bilan teriladi (matn kod o'chiriladi) → 2FA (bo'lsa) →
  Telegram UID == bot UID tekshiruvi → sessiya Fernet bilan
  shifrlangan `pending` holatda → admin ✅/❌ tasdig'i. Tasdiqda
  sessiya qayta tekshirilib aktiv bo'ladi.
- **Har kimniki alohida**: har foydalanuvchi o'z sessiyasi bilan
  ishlaydi, o'z guruhlarini qo'shadi (maks. **100 ta**), o'chiradi,
  menyuda bitta UMUMIY ⏸Stop/▶️Start tugmasi bor. Xabar FAQAT o'sha
  guruh egasiga boradi.
- **Admin menyusi** (6 qator): 🔑 Kalit so'zlar · 🔔 Xabar sharti ·
  ➕ Guruh qo'shish · 🔎 Akkauntdagi guruhlar · 📋 Guruhlarim ·
  🧪 Skaner testi · 👥 Foydalanuvchilar · 📝 Arizalar ·
  📣 Xabar yuborish · 📊 Statistika · 📱 Akkaunt holati ·
  ⏸/▶️ Tizim (hammaga). Alohida 🔑 Login va ℹ️ Yordam tugmalari
  YO'Q — login kerak bo'lsa 📱 Akkaunt holati ichidan ochiladi.
- **Foydalanuvchi menyusi**: 🔴/🟢 Stop (bitta umumiy tugma, eng
  tepada), ➕ Guruh qo'shish, 📋 Guruhlarim, 📊 Statistika (faqat
  o'ziniki), 📱 Akkaunt holati (sessiya + tarif shu yerda),
  🧪 Skaner testi, 🔔 Xabar sharti, ℹ️ Yordam. Kalitlar va boshqa
  foydalanuvchilar ko'rinmaydi.
- **Tarif**: to'lov tizimi yo'q — og'zaki. Admin muddatni qo'lda
  yozadi (yoki 1/7/30/90 tugma); **yangi muddat eskisini bekor
  qiladi** (ustiga qo'shilmaydi). Tugashga 3/2/1 kun qolganda
  kuniga 1 marta ogohlantirish boradi.
- Sessiyalar `SESSION_ENCRYPTION_KEY` bilan shifrlanadi (serverda
  alohida maxfiy kalit qo'ying).
- **Filtr zanjiri** (`filters.py` — skaner ham, test ham AYNAN shu
  kodni ishlatadi), 6 bosqich:
  1. Tizim (admin) to'xtatmaganmi;
  2. Tarif faolmi / bloklanmaganmi (admin bundan mustasno);
  3. Foydalanuvchining umumiy Stop/Start holati;
  4. Xabar shu foydalanuvchining faol guruhidanmi;
  5. Emoji yoki stiker bormi — haydovchi e'loni, blok;
  6. Kalit so'zlar shartga yetadimi.
  Emoji bosqichi hech qanday ro'yxat talab qilmaydi: haydovchi
  e'lonlari deyarli doim emoji bilan bezatiladi, mijoz xabarlarida
  esa emoji bo'lmaydi.
- **Bitta umumiy ro'yxat**: faqat 🔑 Kalit so'zlar bor (admin
  kiritadi). Ro'yxatga yozuv: takror so'z (katta/kichik harf,
  lotin/kirill, tinish belgisi farqi bilan) qo'shilmaydi; xato
  shakl («mang'ud» → «mang'it»), 3 harfdan qisqa so'z va
  qo'shimchali shakl («toshkentga» — o'zak «toshkent» bor) rad
  etiladi. Ro'yxatga har doim lotin shakli yoziladi.
- **Vazn (ball) — ixtiyoriy, lekin tavsiya etiladi**: har bir kalit
  so'zning **vazni** bor. Musbat vazn — *mijoz belgisi* (`kerak` +3),
  manfiy vazn — *haydovchi belgisi* (`joy bor` −4). Ikki rejim bor:
  **🔢 hisob** (nechta kalit topildi — standart) va **⚖️ ball**
  (vaznlar yig'indisi ≥ chegara). Rejim va chegara 🔑 Kalit so'zlar
  sahifasidagi `⚖️ Rejim` / `🎯 Chegara` tugmalaridan boshqariladi.
- **Vaznni kiritishda yozish**: so'z oldiga `+3` yoki `-4` qo'yiladi.
  Musbat vaznda bir necha so'z — har biri alohida yozuv; manfiy vaznda
  bir necha so'z — **ibora** (`-4 joy bor`). Ibora musbatda ham kerak
  bo'lsa: `+2: kim bor` yoki `+2 "kim bor"`.
- **Vaznni keyin o'zgartirish**: 📋 To'liq ro'yxat da so'zni bosing —
  kartochka ochiladi: ➖0.5/➕0.5, tayyor qiymatlar (Mijoz 3/2/1,
  Neytral 0, Haydovchi −1/−3/−4), 🔒 qat'iylik va 🗑 o'chirish.
  Ro'yxatda har so'z oldida vazni ko'rinadi (`➕3 kerak`, `➖4 joy bor`).
- **Fikr-mulohaza (o'z-o'zini sozlash)**: har bir bildirishnomada
  `✅ Foydali` / `❌ Keraksiz` tugmalari bor. Bosilganda o'sha xabarda
  qatnashgan so'zlarning vazni **avtomatik** moslashadi:
  ✅ — musbat so'zlar `+0.25`, manfiy so'zlar `0` tomon `+0.25`
  (ya'ni zaiflashadi); ❌ — faqat musbat so'zlar `−0.25`
  (manfiyga tegilmaydi — u o'z ishini qildi). Vazn hech qachon `0`
  bo'lib qolmaydi (belgi saqlanadi), chegarasi `±10`. Bir xabar faqat
  **bir marta** baholanadi. Ruxsat: bildirishnoma egasi yoki admin.
  📊 Statistikada `👍 Fikr-mulohaza` qatori ko'rinadi.
- **Nega manfiy yozuv qat'iy qidiriladi**: manfiy yozuv faqat aniq
  so'z yoki o'zak bo'yicha topiladi (imlo xatosi/prefiks yaqinligi
  ishlatilmaydi). Aks holda `xizmat` manfiysi «menga yuk tashish
  **xizmati** kerak» (mijoz) xabarini ham o'chirardi. Shu sababli
  manfiy ro'yxatga **umumiy so'z emas, haydovchi shakli** yoziladi:
  `xizmat ko'rsatamiz`, `qo'ng'iroq qiling`, `har kuni`, `reys`.
- **Ko'p so'zni bir martada kiritish**: bitta xabarda bir nechta
  so'z yuboriladi — probil, vergul yoki yangi qator bilan
  ajratiladi; har biri alohida kalit bo'ladi. Ro'yxat 20 tadan
  sahifalanadi (◀️ ▶️), so'z tugmasi bosilganda o'sha xabarning
  o'zi yangilanadi — ro'yxat yopilib qolmaydi.
- **Yozilish shakllari**: so'zlarni faqat **lotin** alifbosida kiritish
  yetarli. Skaner kirill alifbosini ham, "dangasa" yozilgan kirillni
  ham (ў→у, қ→к, ғ→г, ҳ→х) tanidi: `qarshi` = `қарши` = `карши`,
  `jo'naymiz` = `жўнаймиз` =
  `жунаймиз`. Apostrof muhim: `bo'sh` to'g'ri, `bosh` — boshqa so'z.
  Fe'l shakllari ham mos keladi: `olamiz`/`olaman` (bir shaxs),
  `odam`/`odamlar`.
- **Tezlik**: kalitlar prefiks indeksi bo'yicha qidiriladi. 5000 ta
  kalitda bitta xabar ~2 ms (avval ~600 ms edi).

## Ish tartibi

1. **➕ Guruh qo'shish** tugmasi orqali guruh manzili (`@username`,
   t.me havola) yoki raqamli ID (`-100...`) dan birini yuboring.
   Skaner faqat shu yerda qo'shilgan guruhlarni tekshiradi —
   akkauntdagi barcha guruhlar avtomatik tortib kelinmaydi.
   Akkauntingiz shu guruhda a'zo bo'lishi shart: 30 soniya ichida
   tekshirilib, "✅ Guruh ulandi" yoki sababi bilan xato xabari keladi.
   Xato bo'lsa 🔄 Qayta tekshirish tugmasi bor.
2. **📋 Guruhlarim** da har bir guruhda faqat **🗑 O'chirish** tugmasi
   bor. Stop/Start guruhga alohida EMAS — foydalanuvchi menyusining
   ENG TEPASIDA bitta UMUMIY tugma: yoniq bo'lsa `🔴 ⏸ Stop`,
   o'chiq bo'lsa `🟢 ▶️ Start` chiqadi va barcha guruhlariga
   bir vaqtda ta'sir qiladi. 📱 Akkaunt holati bo'limida tugmalar
   yo'q — faqat holat ko'rsatiladi (sessiyani uzish tugmasi yo'q).
   Menyuda shuningdek bitta umumiy **🧪 Skaner testi** tugmasi bor.
3. **➕ Kalit so'z qo'shish** orqali kalitlar qo'shing. Har bir so'z —
   alohida kalit, kalitlar soni **cheklanmagan**. Bitta xabarda bir
   nechta so'z yuborsangiz, har biri alohida kalit bo'lib saqlanadi.
4. **🔔 Xabar sharti**: kalitlardan kamida nechtasi topilsa xabar
   berilishi. Admin umumiy (standart) sonni belgilaydi; har bir
   foydalanuvchi menyudagi **🔔 Xabar sharti** dan O'Z shartini
   alohida belgilashi mumkin — bu faqat o'ziga ta'sir qiladi.
   Kalit so'zlarning o'zi esa umumiy (faqat admin kiritadi).
5. **🧪 Skaner testi** tugmasi diagnostika uchun: tizim, sessiya va
   guruhlar holatini ko'rsatadi va namuna xabarni tekshirib beradi.
   Bildirishnoma esa faqat o'sha guruh **egasiga** keladi — boshqa
   foydalanuvchilarga hech qachon yuborilmaydi.
   Replit logida `[SCAN]` yozuvlari qaysi bosqichda to'xtaganini,
   `[NOTIFY]` yozuvlari yuborilganini ko'rsatadi.
6. Mos xabar topilsa, bot adminga mijoz ismi, ID, telefoni, topilgan
   kalitlar ro'yxati va asl xabarga havola bilan xabar yuboradi.

### Kalit qanday ishlaydi?

- Har bir so'z = bitta kalit, umumiy kalitlar sonining ahamiyati yo'q.
- Admin belgilagan son (standart: **3**) — xabarda kalitlardan istalgan
  shuncha tasi uchrasa, qaysi kalitlar ekanligidan qat'iy nazar,
  xabar beriladi. Foiz ham, to'plam ham yo'q.

| Kalitlar: `toshkent samarqand odam mashina kerak yuk bugun`, shart: 3 | Natija |
|---|---|
| "Toshkentdan odam bor, mashina kerak" (3+ ta topildi) | ✅ xabar beradi |
| "Toshkentdan odam bor" (2 ta topildi) | ❌ bermaydi |
| "Samarqandga yuk kerak" (3 ta topildi) | ✅ xabar beradi |

Qo'shimcha: so'z tartibi va oradagi so'zlar ahamiyatsiz, katta-kichik
harf/tinish belgilari hisoblanmaydi, so'z shakllari ham taniladi
(`odam` ~ `odamlar`, `toshkent` ~ `toshkentdan`).

Eski bazadagi ko'p so'zli yozuvlar avtomatik ravishda alohida
kalit so'zlarga bo'linadi — ma'lumot yo'qolmaydi.

Maxfiy fayllar (`.env`, `*.db`, `*.session`) `.gitignore` da — ularni
hech qachon gitga qo'shmang.
