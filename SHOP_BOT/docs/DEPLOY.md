# SHOP-BOT — joylash, monitoring va tiklash qo‘llanmasi

> Bu **operator yo‘riqnomasi**, jonli deploy bajarilgani haqidagi dalil emas.
> Phase 9 va joriy tarif/bepul oqim oflayn sinovlari PostgreSQL/Redis, Telegram, bank va TLSning jonli
> ishlashini tasdiqlamaydi. Bularni ishlab chiqarishga chiqarishdan **oldin**
> ajratilgan test muhitida tekshiring. **Joriy xatti-harakat:** [YANGI_ELON_OQIMI.md](YANGI_ELON_OQIMI.md).
> `a7c890e42d1b` migratsiyasidan oldin DB backup oling; mavjud grant/cheklar migratsiyadagi
> tarifdan snapshot oladi, oldingi tahrirlangan narxlarning asl qiymati tiklanmaydi.
> Eski kanal va link manbalari faolsizlanadi; avval hisoblangan link N kreditlari
> joriy agregatdan ayriladi, ammo xom taklif yozuvlari saqlanadi. Faqat Telegram
> superguruhlari va «A’zo qo‘shish» manbasi uchun sozlang.

## 1. Tayyorlash (operator)

- Faqat `SHOP_BOT/` bilan ishlang; `AVTO_BOT/`, `main` yoki boshqa botning
  token/bazasidan foydalanmang. Serverda Docker Compose **v2**, DNS, webhook
  uchun 80/443 port va HTTPS sertifikat olish imkoni bo‘lsin.
- `cp .env.example .env && chmod 600 .env`; maxfiy qiymatlarni hech qachon
  chat, video, Git yoki buyruq satridagi URLga qo‘ymang. `BOT_TOKEN`, haqiqiy
  `ADMIN_IDS`, **16+ belgili** `POSTGRES_PASSWORD`, unga mos `DB_URL`, va **24+
  belgili** `HEALTH_TOKEN` majburiy. Tasodifiy sir uchun
  `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`dan foydalaning.
  `USE_WEBHOOK=true` bo‘lsa, `DOMAIN`, `WEBHOOK_BASE_URL=https://<DOMAIN>`,
  `WEBHOOK_PATH=/webhook`, **24+ belgili** `WEBHOOK_SECRET` ham shart.
  Polling uchun `USE_WEBHOOK=false` qoldiring, Caddy ishga tushmaydi.
- `.env`ni faqat ishonchli administrator tahrirlasin: backup/restore skriptlari
  uni Bash konfiguratsiyasi sifatida o‘qiydi. **Mavjud** `pgdata` hajmida parolni
  faqat `.env`da almashtirish yetmaydi — PostgreSQL rolini ham mos yangilang.
- Hostdagi `./logs` bind mount ichiga Docker image UID **1001** yozadi:
  `mkdir -p logs backups && sudo chown -R 1001:1001 logs` (keng `chmod 777`
  qilmang). `backups/` hostda operator/cron uchun yoziladigan va begonalardan
  yopiq bo‘lsin. Disk sig‘imi va backup’ni serverdan tashqarida shifrlangan
  saqlash rejasini oldindan tayyorlang.

```bash
cd SHOP_BOT
python3 -m scripts.preflight --env .env  # sirlar qiymatini chop qilmaydi
./scripts/deploy.sh --check               # qo‘shimcha: Docker Compose config --quiet
```

`--check` faqat sintaksis/maydon/servis mavjudligini tekshiradi; **DB ulanishi,
parol autentifikatsiyasi, Docker build, TLS va Telegramni tekshirmaydi**.
`.env.example` qasddan yaroqsiz; uni to‘ldirmasdan deploy qilmang.

## 2. Deploy va dastlabki seed

```bash
./scripts/deploy.sh  # terminalda DEPLOY deb tasdiqlang
# script: DB/Redisni --wait bilan kutadi → build → bot/posterni to‘xtatadi
#         → backup → migrate → bot/poster → (webhook bo‘lsa) caddy
# Birinchi ishga tushirishda / yangidan admin qo‘shilganda:
docker compose run --rm --no-deps migrate python -m scripts.seed
```

Skript har deployda backup oladi. Backup xatoda **migratsiya qilinmaydi**,
bot/poster to‘xtagan qolishi mumkin: sababni tekshirib, kerak bo‘lsa
`docker compose up -d bot poster`ni operator qo‘lda ishga tushiradi. Kod yoki
migratsiya xatosida ham xuddi shunday: avval sababni hal qiling, zarur bo‘lsa
operator tiklash tartibini qo‘llasin. `docker compose down -v`ni **ishlatmang**:
`pgdata`, `redisdata`ni yo‘qotishi mumkin. Mavjud bazani `pg_dump` izchil snapshot
qiladi, ammo backup va bot to‘xtashi orasidagi yangi yozuvlar rollbackda
saqlanmasligi mumkin; qo‘shimcha inkremental/offsite strategiyasini ko‘rib chiqing.

**Tekshirish (8080 hostga chiqarilmagan):**

```bash
docker compose ps
docker compose exec bot curl -fsS http://127.0.0.1:8080/health
docker compose exec bot sh -c 'curl -fsS -H "X-Token: $HEALTH_TOKEN" http://127.0.0.1:8080/stats'
docker compose logs --tail=100 bot poster migrate
```

`/stats` Caddy orqali tashqariga berilmaydi, URL `?token=` qabul qilinmaydi.
`/health` DB ishlamasa 503, Redis ishlamasa 200 + `status=degraded`:
monitoring **JSON statusni** ham kuzatsin; production broadcast Redis bo‘lmasa
yuborishni to‘xtatadi. Webhookda DNS/TLS va Telegram webhook holatini operator
Telegram Bot API bilan alohida tekshirsin; pollingda `/webhook` marshruti yo‘q.
Botni faqat test **supergroup**ga administrator (xabarni o‘chirish, a’zoni
cheklash, invite-link yaratish huquqlari) sifatida kiriting; Privacy Mode uchun
@BotFather `/setprivacy`ni sozlang va zarur bo‘lsa botni qayta qo‘shing.
Posbon/tozalovchi/sanoqchining **har bir guruhdagi** dry-run natijasini ko‘rib,
jonli amalni faqat o‘sha guruhda alohida tasdiqlang. To‘lovni bank ilovasida
operator tekshirmaguncha chekni tasdiqlamang.

## 3. Kunlik backup va real restore drill (hali bajarilmagan)

```bash
BACKUP_REQUIRE_DOCKER=true ./scripts/backup.sh
# cron namunasi (server yo‘li va operatorga moslang):
# 0 3 * * * cd /opt/shopbot/SHOP_BOT && BACKUP_REQUIRE_DOCKER=true ./scripts/backup.sh >> logs/backup.log 2>&1
```

Backup `pg_dump --clean --if-exists | gzip` bilan vaqtinchalik faylga yoziladi,
`pipefail` va `gzip -t`dan o‘tgachgina nomlanadi (`0600`). Xatoda yarim fayl
o‘chadi; faqat shu papkadagi `shopbot_*.sql.gz` 14 kundan eskilari o‘chiriladi
(`BACKUP_RETENTION_DAYS=1..365`). Cron xatolariga va bo‘sh diskka ogohlantirish
sozlang. Faqat **ishonchli** dumpni tiklang (SQL fayli kod bajaradi).

Tiklashni avval **alohida server/test bazada** sinang (Compose project/volume
nomlari bu repoda doimiy — ayni serverda parallel nusxa uchun qayta sozlash
kerak). Ishlab chiqarish bazasini tiklash boshqa yozuvlarni yo‘qotadi:

1. Tiklashdan oldin `groups`, `ads`, `post_logs`, `payments` sonini va Alembic
   revisionini yozib oling. Arxivning sanasi va nusxasi to‘g‘riligini tekshiring.
2. `docker compose stop bot poster caddy` (webhook bo‘lsa); postgres ishlasin.
   Skript `shopbot-bot` yoki `shopbot-poster` hali ishlayotganini aniqlasa
   tiklashni rad etadi (serveringizda servis nomini o‘zgartirsangiz qo‘lda ham
   alohida tekshiring).
3. `./scripts/restore.sh backups/shopbot_YYYY-...sql.gz` — `ha`, so‘ng aynan
   `POSTGRES_DB` nomini kiriting. Interaktiv terminal shart. Avval `gzip -t`,
   so‘ng `psql -X -v ON_ERROR_STOP=1 --single-transaction --file=/dev/stdin`;
   SQL xatoda butun tranzaksiya bekor qilinadi (faqat normal `pg_dump` uchun).
4. `docker compose run --rm migrate` bilan kerakli migratsiyani qo‘llang;
   `docker compose run --rm --no-deps migrate python -m scripts.seed`ni 2 marta
   bajarib, dublikat paydo bo‘lmaganini va maxfiy admin ID mosligini tekshiring.
5. Jadvallar soni/namunalari, to‘lov holati, saqlangan postlar va mavjud
   `sending`/`uncertain` loglarni **operator qo‘lda** solishtirsin. Noaniq
   Telegram natijasi bor postlarni avtomatik qayta yubormang.
6. `docker compose up -d bot poster` va webhook bo‘lsa `docker compose up -d caddy`;
   `/health`, `/stats`, test xabari va guruh funksiyalarini ko‘rib chiqing.

Bu muhitda Docker/PostgreSQL klienti va jonli baza yo‘qligi sabab **real restore
drill bajarilmadi**. Shell mock testlari arxiv, tasdiq va xatoni ushlashni
tekshiradi, ma’lumotlarning real PostgreSQLga tiklanganini emas.

## 4. Oflayn yuklama va ishlab chiqarish qabul ro‘yxati

```bash
python -m scripts.load_smoke                    # 200 guruh, 5000 e’lon, 24 soat
python -m scripts.load_smoke --groups 4 --ads 40 --hours 3  # tezkor smoke
```

Skript alohida vaqtinchalik SQLite yaratadi va har soatda 200 guruh uchun
`due_group_ids → claim_post → commit → finish_post → commit`ni 24 marta bajaradi;
Telegram yuborish vaqti **simulyatsiya qilinadi**, API so‘rovi yo‘q. Natijadagi
millisekundlar lokal mashina/SQLitega xos; ular production SLA, PostgreSQL
`SKIP LOCKED` yoki Telegram flood limitiga kafolat emas. Haqiqiy qabul uchun
**alohida test server**da jonli PostgreSQL/Redis, ikki worker poygasi, Telegram
superguruh, webhook TLS, to‘lovni bankda solishtirish va tiklash drillini
tekshirib, natija/vaqt/xatolarni qayd qiling. Bularni bu muhitda bajarib bo‘lmadi.

## 5. Maxfiylik va huquqiy eslatma (yuridik maslahat emas)

- Sotuvchi telefon/kontaktlari, Telegram ID, takliflar, xabarlar, chek foto-ID va
  bank to‘lov yozuvlari shaxsiy/moliyaviy ma’lumot bo‘lishi mumkin. O‘zbekiston
  qonunchiligi bo‘yicha xabardor qilish, rozilik, saqlash muddati va o‘chirish
  tartibini **malakali yurist bilan aniqlang**; kerak bo‘lmagan ma’lumotni
  yig‘mang, admin rolini cheklang, backupga kirishni nazorat qiling.
- Kartaning to‘liq ma’lumotlari yoki PIN/CVVni botda talab qilmang.
  Chek “to‘lov bo‘ldi” isboti emas; admin bankdagi kirimni qo‘lda tasdiqlaydi.
  Qaytarish/nizolar va noqonuniy e’lonlar uchun operator tartibini yozing.
- Telegram Bot API qoidalari, xabarlar tezligi, spamga qarshi va platformadagi
  tijorat qoidalarini ishga tushirish **paytida** rasmiy manbadan qayta tekshiring.
  Broadcast faqat shaxsiy `/start` qilgan va chiqmaganlarga, opt-out uchun
  `/xabarlar_stop`; “jo‘natib ko‘rish”ni ommaviy auditoriyaga qilmang.
- Token/sirlarni va haqiqiy foydalanuvchi/chek ma’lumotlarini ekran yozuvida
  ko‘rsatmang. Insidentda tokenlarni bekor qiling, backup va logga kirishni
  qayta baholang, zarar ko‘rganlarga tegishli tartibda xabar bering.
