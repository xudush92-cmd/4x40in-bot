# Telegram Scanner

Guruhlardagi xabarlarni berilgan iboralar bo'yicha kuzatib, mos kelgan
mijozlarni adminga yuboradigan tizim: **boshqaruv boti** (aiogram) +
**userbot** (Telethon).

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

## Ishga tushirish (ikkita alohida terminalda)

```bash
.venv/bin/python bot.py      # boshqaruv boti
.venv/bin/python userbot.py  # skaner (1-marta telefon + kod so'raydi)
```

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

3. **Birinchi marta** Shell (terminal) da userbotni alohida ishga tushirib
   Telegramga kiring — telefon raqami, kod (va 2FA parol) so'raladi:

   ```bash
   cd telegram_scanner
   pip install -r requirements.txt
   python userbot.py
   ```

   Kirgach `Ctrl+C` bilan to'xtating — `userbot_session.session` fayli
   saqlanib qoladi, keyingi safar kod so'ralmaydi.
   ⚠️ Bu sessiya faylini hech kimga bermang — u akkauntingiz kaliti.

4. Keyin **Run** tugmasini bosing (`.replit` sozlangan) yoki:

   ```bash
   python main.py
   ```

   `main.py` bot va userbotni bir vaqtda ishlatadi.

Eslatma: Replit bepul tarifida loyiha "uxlab" qolishi mumkin — bot
to'xtab qolmasligi uchun Always On / Reserved VM kerak bo'lishi mumkin.

## Rollar: Admin va foydalanuvchilar (biznes, server modeli)

- **Admin** (`ADMIN_ID`, bitta odam): kalitlar (faqat admin kiritadi),
  xabar sharti (standart), tizim stop/start, 🧪 test, 📊 umumiy
  statistika, 👥 foydalanuvchilar, 📝 arizalar, 📣 xabar yuborish.
  Admindan alohida "guruhlar" bo'limi YO'Q va admin guruh o'chirmaydi —
  har bir foydalanuvchining guruhlari, xabar sharti, skaner holati,
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
- **Foydalanuvchi menyusi**: ➕ Guruh qo'shish, 📋 Guruhlarim,
  📊 Statistika (faqat o'ziniki), 📱 Akkaunt holati (sessiya + tarif
  shu yerda), ℹ️ Yordam. Kalit/shart/test/alohida tarif tugmasi YO'Q.
- **Tarif**: to'lov tizimi yo'q — og'zaki. Admin muddatni qo'lda
  yozadi (yoki 1/7/30/90 tugma); **yangi muddat eskisini bekor
  qiladi** (ustiga qo'shilmaydi). Tugashga 3/2/1 kun qolganda
  kuniga 1 marta ogohlantirish boradi.
- Sessiyalar `SESSION_ENCRYPTION_KEY` bilan shifrlanadi (serverda
  alohida maxfiy kalit qo'ying).
- **Haydovchi filtri**: admin menyusidagi **🚫 Stop-so'zlar**
  tugmasidan boshqariladi. Tartib: (0) xabarda emoji bo'lsa yoki
  stiker bo'lsa — mijoz izlayotgan haydovchi deb bloklanadi;
  (1) admin kiritgan stop-so'zlardan bittasi bo'lsa — bloklanadi;
  (2) qolgan xabarda asosiy kalitlar (har bir foydalanuvchining o'z
  sharti bo'yicha) + admin kiritgan mijoz so'zlaridan kamida bittasi
  bo'lishi shart. Kodda tayyor so'z ro'yxatlari yo'q — barcha
  so'zlarni admin kiritadi, takroriy so'z (katta/kichik harf va
  lotin/kirill farqi bilan ham) ikkinchi marta qo'shilmaydi. So'z
  boshqa ro'yxatda (kalit/stop/mijoz) bo'lsa ham qo'shilmaydi —
  bot aynan qaysi ro'yxatda ekanini ko'rsatadi.

## Ish tartibi

1. **➕ Guruh qo'shish** tugmasi orqali guruh manzili (`@username`,
   t.me havola) yoki raqamli ID (`-100...`) dan birini yuboring.
   Skaner faqat shu yerda qo'shilgan guruhlarni tekshiradi —
   akkauntdagi barcha guruhlar avtomatik tortib kelinmaydi.
   Userbot akkaunti guruhda a'zo bo'lishi shart: userbot 30 soniya
   ichida tekshirib, "✅ Guruh ulandi" yoki sababi bilan xato xabarini
   yuboradi. Xato bo'lsa 🔄 Qayta tekshirish tugmasi bor.
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
5. **🧪 Skaner testi** tugmasi diagnostika uchun: tizim/userbot/guruhlar
   holatini ko'rsatadi va namuna xabarni kalitlarga tekshirib beradi.
   Bildirishnomalar faqat Secrets dagi `ADMIN_ID` ga — shu bot bilan
   bo'lgan shaxsiy chatga keladi, boshqa joyga yuborilmaydi.
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
