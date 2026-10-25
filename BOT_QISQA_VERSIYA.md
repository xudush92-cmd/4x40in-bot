# 4x40IN — qisqa tavsif (bir sahifalik, chatga tashlash uchun)

Men Telegram guruhlarini kuzatib, **mijoz** (xizmatga muhtoj odam) xabarlarini
topib, guruh egasiga yetkazadigan tizim qurdim. Transport / yuk tashish
sohasida: haydovchilar guruhlarda o'z e'lonlarini yozadi, mijozlar esa
"menga mashina kerak" deb yozadi. Bu ikki oqim aralashib ketadi.

**Arxitektura:** Python, `aiogram` (boshqaruv boti) + `telethon` (har bir
foydalanuvchining **o'z** MTProto sessiyasi), SQLite, Fernet-shifrlangan
sessiyalar. Markaziy userbot yo'q: har bir foydalanuvchi o'zi a'zo bo'lgan
guruhlarni qo'shadi, xabar **faqat shu guruh egasiga** boradi. Kalit so'zlar
**bitta umumiy ro'yxat**, faqat admin kiritadi (per-user faqat "xabar sharti"
soni).

**Oqim:** `NewMessage` hodisasi → shaxsiy chatlar tashlanadi → 6 bosqichli
filtr: (1) tizim global holati, (2) tarif/blok, (3) foydalanuvchining umumiy
Stop/Start, (4) guruh shu foydalanuvchiniki mi, (5) **emoji / stiker bormi**
(bor bo'lsa = haydovchi e'loni, blok), (6) kalit so'zlar soni shartga
yetadimi → o'tsa Bot API orqali egasiga HTML kartochka (ism, ID, telefon,
matn, topilgan kalitlar, "lichkaga yozish" va "asl xabarni ochish" tugmalari).

**Matcher:** tokenizatsiya (apostrof birlashtiriladi), lotin↔kirill
transliteratsiya + "dangasa" yozuv (ў→у, қ→к, ҳ→х, o'→u), fe'l o'zak +
shaxs (1-shaxs ≠ 2-shaxs) + zamon ajratiladi, o'zak/prefix mosligi
(`kerak` ~ `kerakmi`), 85% o'xshashlik bilan imlo xatosi, prefiks indeksi
bilan 5000 kalitda ~2 ms/xabar. Shart: "kamida N ta kalit topilsin"
(standart 2).

**O'lchov (27 mijoz / 24 haydovchi / 11 aloqasiz xabar):**
- hozirgi 75 so'zli ro'yxat, shart=1 → mijoz 25/27, **haydovchi 23/24 o'tib ketadi** (ya'ni ishlamaydi);
- 12 so'zli ro'yxat `kerak kerek izl qidir jo'nat jonat jull jiber yubor qancha necha ketadi`, shart=1 → mijoz **26/27**, haydovchi **1/24**, aloqasiz 1/11.

**Ochiq muammolar:**
1. Emoji filtri qo'pol (mijoz emoji ishlatsa xabar yo'qoladi; haydovchi emojisiz yozsa o'tib ketadi).
2. Tasniflash "so'z bor/yo'q" darajasida — kontekst, inkor (`kerak emas`), savol shakli hisobga olinmaydi.
3. Korpus kichik (qo'lda tuzilgan), o'zbek lotin/kirill aralashmasi va imlo xatolari ko'p.
4. Faqat matnli xabarlar: rasm-caption, ovozli xabar, tahrirlangan xabar, reply/forward ichidagi matn qamrab olinmagan.
5. 100 foydalanuvchi × 100 guruh shkalasida bitta jarayon / bitta SQLite / Telethon flood limitlari savol ostida.
6. Deduplikatsiya va prioritetlash yo'q (bir mijoz 3 guruhga yozsa 3 ta xabar keladi).

**Savolim:** (a) emoji o'rniga ko'p belgili **vaznli skoring** (kalit so'z vazni + `kerak/bor` nisbati + savol shakli + emoji + telefon + xabar uzunligi) qurish to'g'rimi, formula va chegaralarni qanday tanlash kerak? (b) 50–500 xabarlik korpus bilan kichik ML modeli (NB/logreg) yoki embedding-asosidagi semantik qidiruv amaliymi? (c) foydalanuvchi "bu mijoz / bu haydovchi" bosib ro'yxatni o'zi o'rgatadigan feedback loop qanday quriladi? (d) qamrovni (media, tahrir, reply) eng arzon yo'l bilan qanday kengaytiraman? (e) shkalani qanday buzaman — worker'larga bo'lishmi yoki boshqa yondashuvmi? Iltimos, har bir javobda aniq qadam va qanday o'lchash mumkinligini yozing.
