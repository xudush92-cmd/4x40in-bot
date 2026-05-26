# ⚙️ ENGINEBOT v1.1

**Eʼlonlar mexanizmi — kanal va guruhlar uchun aqlli boshqaruv tizimi**

ENGINEBOT — bu Telegram kanal va guruh egalariga moʻljallangan universal eʼlon boshqaruv platformasi. Taxi, koʻchmas mulk, ish, bozor — har qanday kategoriyali eʼlon kanallarini avtomatik boshqaradi.

> ⚠️ **DIQQAT:** Bu loyiha AVTO_BOT'dan **butunlay alohida**. AVTO_BOT ishlab turibdi va unga tegilmaydi.

---

## 📑 Mundarija

1. [Maqsad va g'oya](#-maqsad-va-goya)
2. [v1.1 Yangiliklar](#-v11-yangiliklar)
3. [Mijozlar](#-mijozlar)
4. [Daromad modeli](#-daromad-modeli)
5. [3+1 darajali nazorat](#-31-darajali-nazorat-tizimi)
6. [Asosiy funksiyalar](#-asosiy-funksiyalar)
7. [Per-poster rotation](#-per-poster-rotation)
8. [Tasdiqlash va xavfsizlik](#-tasdiqlash-va-xavfsizlik)
9. [Texnik arxitektura](#-texnik-arxitektura)
10. [Kategoriyalar](#-kategoriyalar)
11. [DB jadvallar](#-db-jadvallar)
12. [O'rnatish va ishga tushirish](#-ornatish-va-ishga-tushirish)
13. [Roadmap](#-roadmap)

---

## 🎯 Maqsad va g'oya

### Muammo
- Telegram kanallarda eʼlonlar tartibsiz, yangi xabar tepaga chiqib eskisi yoʻqoladi.
- Kanal egasi qoʻlda boshqarsa — vaqt ketadi, yangiliklar tartibsiz.
- Foydalanuvchilar (taksist, sotuvchi) eʼlonlarini takror-takror qayta yuborishga majbur.
- Mijozlar (yoʻlovchi, xaridor) izlayotgan narsasini topa olmaydi.

### Yechim
ENGINEBOT — bitta bot, koʻp kanal, koʻp tenant.
- 🤖 Posterlar bot orqali eʼlon yozadi → kanalga avtomatik chiqadi.
- 🔄 Har **poster o'z intervalini** belgilaydi (min 10 daqiqa) — e'lonlar siklik aylanadi.
- 🗑 Vaqti oʻtgan eʼlonlar avtomatik oʻchadi.
- 🔍 Mijozlar kategoriya/kalit so'z bo'yicha qidiradi va bog'lanadi.
- 👥 Kanal egasi, poster, mijoz — har biri oʻz panelida ishlaydi.

---

## 🆕 v1.1 Yangiliklar

| Soha | v1.0 | **v1.1** |
|------|------|----------|
| Rotation | Tenant darajasidagi global | **Per-poster** — har poster o'z intervalini boshqaradi |
| E'lon shabloni | Plugin (faqat taxi) | **Erkin matn** + ixtiyoriy 1-3 rasm |
| Sub-rollar | Faqat poster | **POSTER + CUSTOMER + BOTH** |
| Mijoz paneli | ❌ Yo'q | **🔍 Qidiruv, 📰 Lenta, ⭐ Saqlanganlar** |
| Kategoriya | Taxi only | **13 universal** (taxi, usta, repetitor va h.k.) |
| To'lov | Avto + tarif | **Og'zaki kelishuv** (trial bilan) |
| Notification | DB'ga yoziladi | **Telegram'ga yuboradi** (notifier_service) |
| Kanal ulash | Faqat numeric ID | **@username + ID** (avto get_chat) |
| Tenant panel | 8 funksiya | **+E'lon nazorati, Kategoriya cheklovi, Deep-link, Profile, Detailed stats** |
| Bookmarks | ❌ | **⭐ Saqlangan e'lonlar** (mijoz uchun) |
| Rate limiter | Bor lekin ishlatilmagan | **Faol** — post/qidiruv/modify cheklovlari |
| Edit post | ❌ | **✏️ Poster e'lonni tahrirlay oladi** |

### 4 ta yangi background service
1. **scheduler** — per-poster rotation
2. **cleaner** — eskirgan e'lonlar
3. **billing_checker** — to'lov muddati
4. **notifier_service** ⭐ — DB'dan Telegram'ga bildirishnoma yuboradi

---

## 👥 Mijozlar

| Segment | Misol | Foydasi |
|---------|-------|---------|
| 🚖 Taxi guruh egalari | Toshkent–Samarqand taxi | Taksistlar eʼlonlari tartibli |
| 🏠 Koʻchmas mulk | "Toshkent uy-joy" | Sotuvchi/ijaraga beruvchilar |
| 💼 HR | "IT vakansiyalari" | Ish beruvchilar tez topadi |
| 🛍 Bozor | "Bolalar kiyimi" | Sotuvchilar uchun tartib |
| 📚 Ta'lim | "Repetitorlar bazasi" | Oʻqituvchilar eʼloni |

**Universal printsip:** har qanday "eʼlon kerak boʻladigan guruh" — sizning mijozingiz!

---

## 💰 Daromad modeli

### Tarif rejasi (taklif)

| Tarif | Aktiv e'lon | Cheklov | Narx (oyiga) |
|-------|-------------|---------|--------------|
| 🆓 **Trial** | 5 | 1 kanal, 7 kun | Bepul sinov |
| 🥉 **Bronze** | 10 | 1 kanal, 200 user | 50,000 soʻm |
| 🥈 **Silver** | 20 | 3 kanal, 1000 user | 150,000 soʻm |
| 🥇 **Gold** | 100 | Cheksiz | 300,000 soʻm |

### Toʻlov tartibi
- ⚠️ **Toʻlov OG'ZAKI kelishuv asosida** boshqariladi (v1.1 qoidasi)
- Karta orqali oʻtkazma
- **Faqat siz (Super Admin)** tasdiqlaganingizdan keyin tenant aktivlashadi
- Trial muddati tugagach — avtomatik **Pause** holatiga oʻtadi
  (eʼlonlar saqlanadi, lekin yangilari qabul qilinmaydi)
- Eslatma: tugashga 3 kun qolganda foydalanuvchiga avto-xabar

---

## 🛡 3+1 darajali nazorat tizimi

```
┌──────────────────────────────────┐
│ 1. SUPER ADMIN (siz)             │  ← Hammasi sizda
│    • Tenantlar boshqaruvi        │
│    • Toʻlovlar (qoʻlda)          │
│    • Global statistika           │
│    • Audit log (global)          │
└──────────────────────────────────┘
              ↓
┌──────────────────────────────────┐
│ 2. TENANT (guruh egasi)          │  ← Oʻz guruhi
│    • Kanal ulash (@username)     │
│    • Foydalanuvchi tasdiqlash    │
│    • E'lon nazorati              │
│    • Kategoriya cheklovi         │
│    • Deep-link havola            │
│    • Auto-tasdiq sozlash         │
│    • Min interval (10/15/.../60) │
└──────────────────────────────────┘
              ↓
┌──────────────────────────────────┐
│ 3. USER — sub-rolda              │
│   ┌─ 📝 POSTER ────────────────┐ │
│   │  • Yangi eʼlon (erkin matn) │ │
│   │  • Rotation: o'z interval'i │ │
│   │  • START/STOP boshqaruvi    │ │
│   │  • Edit/Delete o'z e'loni   │ │
│   └────────────────────────────┘ │
│   ┌─ 🔍 CUSTOMER ──────────────┐ │
│   │  • Qidiruv (kategoriya)     │ │
│   │  • Lenta (yangi e'lonlar)   │ │
│   │  • ⭐ Saqlanganlar          │ │
│   │  • 📞 Bog'lanish (counter)  │ │
│   └────────────────────────────┘ │
│   ┌─ 🔄 BOTH (ikkala) ─────────┐ │
│   │  • Posterlik + mijozlik     │ │
│   └────────────────────────────┘ │
└──────────────────────────────────┘

⏳ MODERATOR — v1.5'da qo'shiladi
```

---

## ✨ Asosiy funksiyalar

### 📝 Poster uchun
- ➕ **Yangi e'lon** — erkin matn + 1-3 rasm
- 📋 **Mening e'lonlarim** — gala (queue) ko'rinishida
- ▶️/⛔ **START/STOP** — auto-rotation
- ⏱ **Interval** — 10/15/30/60 daq yoki qo'lda
- 🔄 **Soha o'zgartirish** — kategoriya almashtirish
- ✏️ **E'lonni tahrirlash** — matn yangilash (kanaldagi xabar avto-yangilanadi)

### 🔍 Customer uchun
- 🔍 **Qidirish** — kategoriya bo'yicha (tenant ruxsat berganlari)
- 📰 **Yangi e'lonlar** — eng so'nggi 10 ta
- ⭐ **Saqlanganlar** — yulduzcha qilingan e'lonlar
- 📞 **Bog'lanish** — telefon ko'rsatadi va counter +1 qiladi

### 🏢 Tenant uchun
- 📺 **Kanallarim** — qo'shish/o'chirish/yoqish/to'xtatish (@username yoki ID)
- 👥 **Foydalanuvchilar** — filter (active/pending/blocked), tasdiqlash, blok, ogohlantirish
- 📋 **E'lonlar nazorati** — pause/delete/warn (poster'ga ham xabar)
- ⚙️ **Sozlamalar** — Bot ON/OFF, Eʼlon qabuli, Auto-tasdiq, Min interval
- 📊 **Statistika** — bugungi/haftalik dinamika, top kategoriyalar
- 📜 **Audit log** — o'z guruhi tarixi
- 🔗 **Deep-link** — `t.me/bot?start=join_<id>` (kanalga pin qilish uchun)
- 🚫 **Kategoriya cheklovi** — 13 dan kerakli kategoriyalarni tanlash
- 👤 **Profilim** — ism/telefon/tavsif tahrirlash

### 👑 Super Admin uchun
- 👥 **Tenantlar** — ro'yxat, ON/OFF, blok
- 💰 **Toʻlovlar** — tarif uzaytirish (qoʻlda)
- 📊 **Global statistika** — tizim bo'yicha
- 📨 **Broadcast** — barcha foydalanuvchilarga xabar
- 📜 **Audit log** — global

---

## 🔄 Per-poster rotation

### Yangi model (v1.1):

| Parametr | Min | Max | Default |
|----------|-----|-----|---------|
| Interval | 10 daq | 24 soat | 10 daq |
| E'lon yashash muddati | 1 soat | 7 kun | 24 soat |

### Mantiq:
- Har poster **o'z intervalini** belgilaydi (qat'iy min 10 daq)
- Birinchi e'lon → **darhol** kanalga chiqadi
- Keyingilari → galadan ketma-ket (queue_order)
- Vaqti tugagan e'lon → avtomatik o'chadi
- Poster STOP bosgunicha siklik aylanadi

### Tenant cheklovi:
- Tenant **MIN INTERVAL'ni** belgilaydi (10/15/20/30/60)
- Posterlar shu qiymatdan past qila olmaydi

---

## ✋ Tasdiqlash va xavfsizlik

### Universal tasdiqlash:
Har bir muhim amal foydalanuvchidan tasdiq soʻraydi (Ha/Yo'q tugmalari):
- ✅ E'lon joylashtirish
- 🗑 E'lonni o'chirish
- ⛔ Foydalanuvchini bloklash
- 📺 Kanalni olib tashlash
- 🚪 Logout
- ⛔ Tenantni bloklash (Super Admin)

### Rate Limiter (anti-spam):
| Action | Limit |
|--------|-------|
| Post yaratish | 10 / daqiqa |
| Login | 3 / 5 daqiqa |
| Komandalar | 30 / daqiqa |
| Modify (kanal/sozlama) | 20 / daqiqa |

Limit buzilganda — foydalanuvchi vaqtincha bloklanadi va aniq xabar oladi.

### Bildirishnomalar (tutorial):
- ✅ Tasdiqlandi / ❌ Rad etildi
- 📋 E'lon joylandi / vaqti tugadi
- ⏸ E'lon pauzaga olindi (admin tomonidan)
- ⚠️ Ogohlantirish berildi
- 🚫 Hisob bloklandi
- 💰 Tarif muddati yaqin (3 kun)
- 🚨 Bot to'xtatildi (muddat tugadi)

---

## 🏗 Texnik arxitektura

### Texnologiyalar
- **Python 3.11+**
- **aiogram 3.x** — Telegram bot framework
- **aiosqlite** — async SQLite (WAL mode)
- **python-dotenv** — env management

### Loyiha tuzilishi

```
ENGINEBOT/
├── main.py                   # Entry point
├── config.py                 # Markaziy sozlamalar
├── requirements.txt
├── .env.example
├── README.md
│
├── core/                     # YADRO (10 modul)
│   ├── database.py           # SQLite + per-tenant izolyatsiya
│   ├── tenant_manager.py     # Tenant lifecycle
│   ├── permissions.py        # 4 darajali ruxsat
│   ├── categories.py         # 13 universal kategoriya
│   ├── event_bus.py          # Plugin event tizimi
│   ├── audit_log.py          # Audit log
│   ├── rate_limiter.py       # Anti-spam
│   ├── notifier.py           # Bildirishnoma yaratish (DB)
│   └── error_handler.py      # Crash isolation
│
├── panels/                   # 5 boshqaruv paneli
│   ├── start.py              # /start (deep-link parser)
│   ├── super_admin/          # Bot egasi (siz)
│   ├── tenant/               # Guruh egasi
│   ├── moderator/            # v1.5+ uchun
│   ├── poster/               # E'lon beruvchi
│   ├── customer/             # Mijoz
│   └── user/                 # Eski legacy (bo'sh)
│
├── services/                 # 4 ta background servis
│   ├── publisher.py          # Kanalga e'lon yuborish
│   ├── scheduler.py          # Per-poster rotation
│   ├── cleaner.py            # Eskirgan e'lonlar
│   ├── billing_checker.py    # To'lov muddati
│   └── notifier_service.py   # ⭐ YANGI: DB → Telegram
│
├── keyboards/                # Tugmalar va menyular
│   ├── common_kb.py          # Btn class, helperlar
│   ├── routes.py             # 14 viloyat
│   ├── super_admin_kb.py
│   ├── tenant_kb.py          # +profile_edit_panel
│   ├── user_kb.py            # poster + customer + both menyular
│   └── moderator_kb.py
│
├── utils/                    # Yordamchilar
│   ├── session_state.py      # Per-user state
│   ├── confirmation.py       # Ha/Yo'q dialoglari
│   ├── validators.py         # Phone, channel, interval va h.k.
│   ├── formatters.py         # HTML escape, format
│   └── logger.py             # Strukturalangan log
│
├── data/                     # SQLite baza (gitignore)
├── logs/                     # Loglar (gitignore)
└── tests/                    # ⭐ YANGI: smoke tests
```

### Izolyatsiya printsiplari

1. **Per-tenant DB izolyatsiya:** har query'da `WHERE tenant_id=?`
2. **Per-user state izolyatsiya:** `session.get(uid)` alohida
3. **Crash isolation:** `safe_loop` har background uchun
4. **Atomic DB:** `BEGIN IMMEDIATE` transactions
5. **Filter-level routing:** `_in_<flow>` filterlar — to'qnashuvsiz handlerlar

---

## 🎯 Kategoriyalar

13 ta standart (kengaytirish: tenant kerak bo'lganini cheklaydi):

| Code | Label |
|------|-------|
| taxi | 🚖 Taxi |
| cargo | 🚛 Yuk tashish |
| builder | 🔨 Quruvchi |
| plumber | 🔧 Santexnik |
| electrician | 💡 Elektrik |
| painter | 🎨 Bo'yoqchi |
| cleaner | 🧹 Tozalovchi |
| cook | 👨‍🍳 Oshpaz |
| tutor | 📚 Repetitor |
| barber | 💇 Sartarosh |
| photographer | 📷 Fotograf |
| auto_mech | 🚗 Auto-usta |
| other | 💼 Boshqa |

---

## 🗄 DB jadvallar

| Jadval | Tavsif | Yangi v1.1 ustunlari |
|--------|--------|----------------------|
| `tenants` | Kanal egalari | + `description` |
| `tenant_settings` | Sozlamalar | + `allowed_categories` (JSON) |
| `channels` | Ulangan kanallar | — |
| `users` | Foydalanuvchilar | + `user_role`, `category_code`, `region`, `rotation_interval_min`, `rotation_active`, `current_post_index` |
| `announcements` | E'lonlar | + `category_code`, `raw_text`, `photos` (JSON), `queue_order` |
| `bookmarks` ⭐ | Mijoz saqlaganlari | YANGI |
| `moderators` | Yordamchilar (v1.5) | — |
| `audit_log` | Tarix | — |
| `notifications` | Bildirishnomalar | — |
| `payments` | To'lovlar | — |
| `warnings` | Ogohlantirishlar | — |

Barcha jadvallarda **`tenant_id` orqali izolyatsiya** taʼminlanadi.

Migratsiya — **idempotent** (`_ensure_columns`), eski DB avtomatik yangilanadi.

---

## 📥 O'rnatish va ishga tushirish

### Talablar
- Python 3.11+ (3.9+ ham ishlaydi)
- Linux/macOS/Windows
- Telegram Bot Token (@BotFather)

### Qadamlar

```bash
# 1. Klonlash
git clone https://github.com/xudush92-cmd/4x40in-bot.git
cd 4x40in-bot/ENGINEBOT

# 2. Virtual env (tavsiya etiladi)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Kutubxonalarni oʻrnatish
pip install -r requirements.txt

# 4. Sozlamalar
cp .env.example .env
# .env faylni tahrir qiling: BOT_TOKEN, SUPER_ADMIN_ID

# 5. Ishga tushirish
python main.py
```

### `.env` minimum
```env
BOT_TOKEN=123456:ABC-...
SUPER_ADMIN_ID=123456789
```

Boshqalari default qiymatlar bilan ishlaydi.

### Bot ishga tushgandan keyin
```
⚙️ ENGINEBOT v1.1.0 ishga tushmoqda...
🗄 DB tayyor
📡 7 ta router ulandi: start, super, tenant, mod, poster, customer, user-legacy
🛠 4 ta background servis ishga tushdi  ← scheduler, cleaner, billing, notifier
🤖 Bot polling boshlandi @your_bot
```

---

## 🗺 Roadmap

### ✅ v1.0 — MVP (yopildi)
- [x] Loyiha skeleti
- [x] 4 panel + permissions
- [x] Taxi plugin
- [x] Aylanish servisi (rotation)

### ✅ v1.1 — Universal redesign (HOZIR)
- [x] Per-poster rotation (har poster o'z intervalini)
- [x] Customer paneli (qidiruv + lenta + bookmarks)
- [x] 13 universal kategoriya
- [x] Erkin matn e'lon (+ rasm)
- [x] Notification service (DB → Telegram)
- [x] @username orqali kanal ulash
- [x] Deep-link generator
- [x] Kategoriya cheklovi (tenant)
- [x] E'lon nazorati (tenant)
- [x] Kengaytirilgan statistika
- [x] Rate limiter integratsiyasi
- [x] Tenant profile edit
- [x] Smoke testlar

### 🔜 v1.5 — Kengaytirish
- [ ] Moderator (yordamchi admin)
- [ ] Reyting tizimi (mijoz baholaydi)
- [ ] Kuzatuv (notification subscription)
- [ ] Eksport (Excel, PDF)
- [ ] Multi-channel poster (1 e'lon → 2-3 kanal)
- [ ] Tenant kategoriya qo'shish (custom)

### 🔮 v2.0 — Pro
- [ ] Click/Payme avto-toʻlov
- [ ] VIP eʼlonlar (premium)
- [ ] Push notification
- [ ] Analytics dashboard (web)
- [ ] Telegram WebApp panel

### 🚀 v3.0 — Ekosistema
- [ ] REST API
- [ ] Mobile app (iOS, Android)
- [ ] Multi-language (UZ, RU, EN)
- [ ] AI yordamchi
- [ ] Public plugin marketplace

---

## 👤 Muallif

**Owner:** [@xudush92-cmd](https://github.com/xudush92-cmd)

**Repo:** [xudush92-cmd/4x40in-bot](https://github.com/xudush92-cmd/4x40in-bot)

---

## ⚠️ Eslatma

ENGINEBOT loyihasi `ENGINEBOT/` papkasida joylashgan. Repodagi boshqa loyihalar (AVTO_BOT, signal botlar) — alohida ishlaydi va ularga **tegilmaydi**.

---

> 🤖 *"ENGINEBOT — sizning eʼlon dvigatelingiz."*
