# SHOP-BOT — video-qo‘llanma ssenariysi (yozib olish uchun)

> **Haqiqiy video hali yozilmagan.** Bu hujjat operatorga ekran yozuvi
> tayyorlash bo‘yicha matn va kadrlar rejasi; jonli bot/server/token mavjud
> bo‘lganda yozib, alohida ko‘rib chiqish kerak. Hech qanday sun’iy demo
> haqiqiy bank yoki production test sifatida taqdim etilmasin.

**Format:** 7–9 daqiqa, o‘zbekcha, 16:9, subtitr; faqat alohida test guruh va
soxta kontaktlardan foydalaning. Ekrandagi `.env`, token, parol, chek,
Telegram ID va shaxsiy telefonni yozuvdan **oldin** yoping; montajda yana
tekshiring. Ishlab chiqarish DBda restore/deployni video uchun takrorlamang.

| Vaqt | Ekranda | Ovoz uchun namunaviy matn |
|---|---|---|
| 00:00–00:40 | Loyiha nomi, `README.md`, ajratilgan test muhiti | “Bu bot guruhlar bo‘yicha e’lon navbatini boshqaradi. Namoyish test muhitida; haqiqiy bank va jonli infratuzilma alohida tekshiriladi.” |
| 00:40–01:30 | `.env.example` faqat maydon **nomlari**, `docs/DEPLOY.md` | “Token, admin ID, baza paroli va monitoring sirini alohida faylda saqlang. Yaroqlilik uchun `python3 -m scripts.preflight --env .env` va `./scripts/deploy.sh --check`ni bajaring; bu tarmoqqa ulanmaydi.” |
| 01:30–02:15 | `docker compose ps`; konteyner ichidan `/health`, `/stats` | “Deploy operator tasdig‘i bilan build, zaxira, migratsiya va start qiladi. `health`dagi `degraded` Redis ogohlantirishi; `/stats` faqat `X-Token` va ichki tarmoq bilan.” |
| 02:15–03:15 | Test superguruh, «Guruhlar» va «Toifalar» | “Botga kerakli admin huquqlarini bering. Har guruhda odam qo‘shish/Sanoqchi, Xavfsizlik, Tozalash va bepul opt-in’ni alohida sinang. Guruhda tijoriy interval, kunlik kvota yoki kanal talabi yo‘q.” |
| 03:15–04:10 | Test foydalanuvchi, 5/10 daqiqalik tarif, chek, e’lon moderatsiyasi va «▶️ Boshlash» | “Tarifni oddiy foydalanuvchi ham arizasiz xarid qiladi; bankdagi chek va e’lon mazmuni alohida tasdiqlanadi. Birinchi post admin tasdig‘idan emas, foydalanuvchi Startidan tarif oralig‘icha keyin navbatga tushadi.” |
| 04:10–05:00 | Posbon/tozalovchi/sanoqchining **dry-run** jurnali | “Avval sinov jurnalini ko‘ring; jonli o‘chirish yoki cheklash faqat aynan shu guruhda qo‘shimcha tasdiqdan keyin ishlaydi. Guruh pauzasi boshqa guruh sozlamalariga ta’sir qilmaydi.” |
| 05:00–05:50 | Test chek va admin tasdiqlash dialogi, **bank ma’lumoti yo‘q** | “Chek rasmini yuborish to‘lov tasdig‘i emas. Administrator pulning bank hisobiga haqiqatda tushganini mustaqil tekshirib, keyingina tasdiqlaydi.” |
| 05:50–06:35 | Referal/statistika, broadcast preview + test faqat adminning o‘zi | “Broadcast uchun auditoriya va chiqish huquqi muhim. Ommaviy yuborishdan oldin faqat o‘zingizga sinov yuboring; Redis bo‘lmasa ommaviy yuborish to‘xtaydi.” |
| 06:35–07:25 | `./scripts/backup.sh` fayl nomi va **faqat test muhitida** tiklash qadamlari yozuvi | “Zaxira arxivi tekshiriladi. Restore joriy bazani almashtiradi: servislarni to‘xtating, `ha` va baza nomini kiriting, so‘ng migratsiya, seed va yozuv sonini tekshiring. Buni ishlab chiqarishda video uchun bajarmang.” |
| 07:25–08:05 | `python -m scripts.load_smoke` JSON xulosasi, `docs/DEPLOY.md` cheklovlari | “200 guruh, 5000 e’lon va 24 simulyatsiya soati — faqat SQLite’da. Real Telegram, PostgreSQL, Redis, TLS va bank qabul sinovi alohida qoladi.” |

**Yakuniy tekshiruv:** subtitr va ovozdagi da’volar hujjat natijalariga mos;
URLda `token` parametri ko‘rsatilmagan; to‘lov/kontaktlar soxta; foydalanuvchi
roziligi va Telegram platformasi qoidalari operator tomonidan tekshirilgan.
Video tayyor bo‘lmaguncha README yoki hisobotda “video tayyor” deb yozmang.
