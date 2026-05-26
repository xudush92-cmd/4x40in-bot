# ⚙️ ENGINEBOT

**E'lonlar mexanizmi — kanal va guruhlar uchun aqlli boshqaruv tizimi**

ENGINEBOT — bu Telegram kanal va guruh egalariga moʻljallangan universal eʼlon boshqaruv platformasi. Taxi, koʻchmas mulk, ish, bozor — har qanday kategoriyali eʼlon kanallarini avtomatik boshqaradi.

> ⚠️ **DIQQAT:** Bu loyiha AVTO_BOT'dan **butunlay alohida**. AVTO_BOT ishlab turibdi va unga tegilmaydi.

---

## 📑 Mundarija

1. [Maqsad va g'oya](#-maqsad-va-goya)
2. [Mijozlar](#-mijozlar)
3. [Daromad modeli](#-daromad-modeli)
4. [4 darajali nazorat](#-4-darajali-nazorat-tizimi)
5. [Asosiy funksiyalar](#-asosiy-funksiyalar)
6. [Aylanish tizimi](#-aylanish-tizimi)
7. [Tasdiqlash va xavfsizlik](#-tasdiqlash-va-xavfsizlik)
8. [Texnik arxitektura](#-texnik-arxitektura)
9. [Plugin tizimi](#-plugin-tizimi-kengaytirish)
10. [DB jadvallari](#-db-jadvallari)
11. [O'rnatish va ishga tushirish](#-ornatish-va-ishga-tushirish)
12. [Roadmap](#-roadmap)

---

## 🎯 Maqsad va g'oya

### Muammo
- Telegram kanallarda eʼlonlar tartibsiz, yangi xabar tepaga chiqib eskisi yoʻqoladi.
- Kanal egasi qoʻlda boshqarsa — vaqt ketadi, yangiliklar tartibsiz.
- Foydalanuvchilar (taksist, sotuvchi) eʼlonlarini takror-takror qayta yuborishga majbur.
- Mijozlar (yoʻlovchi, xaridor) izlayotgan narsasini topa olmaydi.

### Yechim
ENGINEBOT — bitta bot, koʻp kanal, koʻp tenant.
- 🤖 Foydalanuvchilar bot orqali eʼlon yozadi → kanalga avtomatik chiqadi.
- 🔄 Eʼlonlar belgilangan vaqtda aylanib turadi (har 10 daqiqadan boshlab).
- 🗑 Vaqti oʻtgan eʼlonlar avtomatik oʻchadi.
- 👥 Kanal egasi, moderator, foydalanuvchi — har biri oʻz panelida ishlaydi.

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

| Tarif | Cheklov | Narx (oyiga) |
|-------|---------|--------------|
| 🆓 **Trial** | 1 kanal, 7 kun | Bepul sinov |
| 🥉 **Bronze** | 1 kanal, 50 eʼlon/oy | 50,000 soʻm |
| 🥈 **Silver** | 3 kanal, 200 eʼlon/oy | 150,000 soʻm |
| 🥇 **Gold** | Cheksiz | 300,000 soʻm |

### Toʻlov tartibi
- Toʻlov **ogʻzaki kelishuv** asosida
- Karta orqali oʻtkazma
- **Faqat siz (Super Admin)** tasdiqlaganingizdan keyin tenant aktivlashadi
- Muddati tugagach — avtomatik **Pause** holatiga oʻtadi (eʼlonlar saqlanadi, lekin yangilari qabul qilinmaydi)

---

## 🛡 4 darajali nazorat tizimi

```
┌──────────────────────────────────┐
│ 1. SUPER ADMIN (siz)             │  ← Hammasi sizda
│    • Tenantlar boshqaruvi        │
│    • Toʻlovlar                   │
│    • Global statistika           │
│    • Audit log                   │
└──────────────────────────────────┘
              ↓
┌──────────────────────────────────┐
│ 2. TENANT (guruh egasi)          │  ← Oʻz guruhi
│    • Kanal ulash                 │
│    • Foydalanuvchi tasdiqlash    │
│    • Aylanish sozlamalari        │
│    • Statistika                  │
└──────────────────────────────────┘
              ↓
┌──────────────────────────────────┐
│ 3. MODERATOR (yordamchi)         │  ← Cheklangan
│    • Eʼlonlarni koʻrish          │
│    • Foydalanuvchini tasdiqlash  │
│    • Ogohlantirish               │
└──────────────────────────────────┘
              ↓
┌──────────────────────────────────┐
│ 4. USER (foydalanuvchi)          │  ← Faqat oʻzi
│    • Roʻyxatdan oʻtish           │
│    • Eʼlon yozish                │
│    • Oʻz eʼlonlari               │
└──────────────────────────────────┘
```

### Ruxsat matritsasi

| Funksiya | Super | Tenant | Mod | User |
|----------|:-----:|:------:|:---:|:----:|
| Barcha tenantlarni koʻrish | ✅ | ❌ | ❌ | ❌ |
| Tenantni bloklash | ✅ | ❌ | ❌ | ❌ |
| Toʻlov boshqaruvi | ✅ | ❌ | ❌ | ❌ |
| Oʻz guruhi statistika | ✅ | ✅ | ❌ | ❌ |
| Foydalanuvchi tasdiqlash | ✅ | ✅ | ✅ | ❌ |
| Foydalanuvchi bloklash | ✅ | ✅ | ❌ | ❌ |
| Eʼlonni oʻchirish (boshqa) | ✅ | ✅ | ✅ | ❌ |
| Aylanish boshqaruvi | ✅ | ✅ | ❌ | ❌ |
| Oʻz eʼloni tahriri | ✅ | ✅ | ✅ | ✅ |
| Audit log koʻrish | ✅ (global) | ✅ (oʻzi) | ❌ | ❌ |

---

## ✨ Asosiy funksiyalar

### 🤖 Foydalanuvchi uchun
- 🔍 **Qidirish** — yoʻnalish/kategoriya tanlab eʼlonlarni koʻrish
- 📝 **Eʼlon yozish** — bosqichma-bosqich shaklni toʻldirish
- 📋 **Mening eʼlonlarim** — aktiv eʼlonlar boshqaruvi
- 👤 **Profil** — shaxsiy maʼlumotlar
- 🔔 **Kuzatish** — yangi eʼlon kelganda xabar olish

### 🏢 Tenant (guruh egasi) uchun
- 📺 **Kanal ulash** — botni admin qilib qoʻygach avtomatik tekshirish
- 👥 **Foydalanuvchi boshqaruvi** — tasdiqlash, ogohlantirish, bloklash
- 📊 **Statistika** — kunlik/haftalik/oylik
- ⚙️ **Aylanish sozlamalari** — interval, vaqt jadvali, ON/OFF
- 👮 **Moderator tayinlash** — cheklangan huquqli yordamchi
- 📜 **Audit log** — oʻz guruhi boʻyicha

### 👑 Super Admin (siz) uchun
- 👥 **Tenantlar** — roʻyxat, ON/OFF, qidirish
- 💰 **Billing** — toʻlov tarixi, muddat uzaytirish
- 📊 **Global statistika** — tizim boʻyicha
- 📨 **Broadcast** — barcha foydalanuvchilarga xabar
- 📜 **Audit log** — global
- 🛠 **Tizim** — RAM, CPU, uptime, errorlar

---

## 🔄 Aylanish tizimi

### Default holat: 🔴 **OFF** (aylanmaydi)

Aylanish — guruh egasining **shaxsiy tanlovi**. U yoqmaguncha eʼlonlar shunchaki guruhda turadi (yangilanmaydi).

### Sozlanadigan parametrlar:

| Parametr | Min | Max | Standart |
|----------|-----|-----|----------|
| Interval | 10 daq | 24 soat | 30 daq |
| Eʼlon yashash muddati | 1 soat | 7 kun | 24 soat |
| Aktiv vaqt | 00:00 | 23:59 | 06:00–23:00 |
| Bir userga max eʼlon | 1 | 10 | 3 |

### Mantiq:
- Yangi eʼlon → **darhol** kanalga chiqadi
- Aktiv eʼlonlar → har **interval daqiqada** yangilanadi (eskisi oʻchadi, yangisi pastroqqa qoʻyiladi)
- Vaqti tugagan eʼlon → **avtomatik oʻchadi**
- Kechqurun (00:00–06:00) → tinch holat (default)

---

## ✋ Tasdiqlash va xavfsizlik

### Universal tasdiqlash:
Har bir muhim amal foydalanuvchidan tasdiq soʻraydi:

```
⚠️ TASDIQLASH

[Amal nima qiladi]

📌 Natijasi:
   • [natija 1]
   • [natija 2]

[✅ Ha, tasdiqlayman]
[❌ Yoʻq, bekor qilish]
```

### Tasdiq talab qilinadigan amallar:
- ✅ Eʼlon joylashtirish
- 🗑 Eʼlonni oʻchirish
- 👤 Profilni tahrirlash
- 🚪 Logout
- ⛔ Bot/aylanish/eʼlon qabulini toʻxtatish
- ⛔ Foydalanuvchini bloklash
- ⛔ Tenantni bloklash (Super Admin)

### START / STOP — har joyda:
| Daraja | Boshqaruv |
|--------|-----------|
| Bot umumiy | 🟢/🔴 ON/OFF |
| Eʼlon qabuli | 🟢/🔴 ON/OFF |
| Aylanish | 🟢/🔴 ON/OFF |

Har biri **alohida** boshqariladi — bittasini toʻxtatish boshqasiga taʼsir qilmaydi.

---

## 🏗 Texnik arxitektura

### Texnologiyalar
- **Python 3.11+**
- **aiogram 3.x** — Telegram bot framework
- **aiosqlite** — async SQLite
- **aiohttp** — HTTP server (health/monitoring)
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
├── core/                     # YADRO (oʻzgarmaydigan qism)
│   ├── database.py           # SQLite + tenant izolyatsiya
│   ├── tenant_manager.py     # Tenant boshqaruv
│   ├── permissions.py        # 4 darajali ruxsat
│   ├── event_bus.py          # Plugin event tizimi
│   ├── audit_log.py          # Audit log
│   ├── rate_limiter.py       # Anti-spam
│   ├── notifier.py           # Bildirishnoma
│   └── error_handler.py      # Crash isolation
│
├── panels/                   # 4 boshqaruv paneli
│   ├── super_admin/          # Bot egasi (siz)
│   ├── tenant/               # Guruh egasi
│   ├── moderator/            # Yordamchi
│   └── user/                 # Foydalanuvchi
│
├── plugins/                  # Kengaytirish (har soha)
│   └── taxi/                 # MVP — taxi plugin
│       ├── plugin.json
│       ├── handlers.py
│       ├── templates.py
│       └── keyboards.py
│
├── services/                 # Background servislar
│   ├── publisher.py          # Kanalga eʼlon yuborish
│   ├── scheduler.py          # Aylanish (rotation)
│   ├── cleaner.py            # Eskirgan eʼlonni oʻchirish
│   └── billing_checker.py    # Toʻlov muddati
│
├── keyboards/                # Tugmalar va menyular
├── utils/                    # Validators, formatters, session
├── data/                     # SQLite baza (gitignore)
├── logs/                     # Loglar (gitignore)
└── templates/                # Eʼlon shablonlari
```

### Izolyatsiya printsiplari

1. **Per-tenant DB izolyatsiya:**
   - Har bir jadvalda `tenant_id` ustuni
   - Hamma soʻrov `WHERE tenant_id=?` bilan
   - Bittasi boshqasini koʻrmaydi

2. **Per-user state izolyatsiya:**
   - `user_states[uid]` — alohida
   - `user_locks[uid]` — race-free

3. **Crash isolation:**
   - Har bir background task `try/except` bilan oʻralgan
   - Bittasi crash boʻlsa boshqasi davom etadi
   - Auto-restart on error

4. **Atomic DB operations:**
   - `BEGIN IMMEDIATE` transactions
   - `INSERT ... ON CONFLICT` upserts
   - `db.rollback()` on error

---

## 🔌 Plugin tizimi (kengaytirish)

Yangi sohani qoʻshish — yadroga **TEGMASLIK** kerak. Faqat yangi plugin yarating.

### Plugin tuzilishi
```
plugins/realestate/
├── plugin.json       # Metadata, fields, template
├── handlers.py       # Buyruqlar
├── templates.py      # Matnli shablonlar
└── keyboards.py      # Tugmalar
```

### `plugin.json` namunasi
```json
{
  "name": "Real Estate",
  "version": "1.0.0",
  "category": "property",
  "icon": "🏠",
  "fields": [
    {"name": "type", "type": "choice", "options": ["sotuv", "ijara"]},
    {"name": "rooms", "type": "number", "min": 1, "max": 10},
    {"name": "area", "type": "number", "unit": "m²"},
    {"name": "price", "type": "price"}
  ],
  "template": "🏠 {type} | {rooms} xona | {area} m²\n💰 {price}\n📞 {phone}"
}
```

### Event tizimi
Pluginlar bir-biriga bogʻlanmasdan **event** orqali aloqa qiladi:

```python
# Plugin emit qiladi
event_bus.emit("post_created", {"user_id": ..., "tenant_id": ...})

# Boshqa pluginlar tinglaydi
@event_bus.on("post_created")
async def analytics_track(data):
    ...
```

---

## 🗄 DB jadvallari

| Jadval | Tavsif | Asosiy ustunlar |
|--------|--------|-----------------|
| `tenants` | Kanal egalari | tenant_id, tariff, paid_until, is_active |
| `channels` | Ulangan kanallar | channel_id, tenant_id, route_info, is_active |
| `users` | Foydalanuvchilar | user_id, tenant_id, full_name, status, rating |
| `announcements` | Eʼlonlar | id, tenant_id, user_id, channel_id, content, status |
| `moderators` | Yordamchi adminlar | id, tenant_id, user_id, permissions |
| `audit_log` | Har bir amal | id, ts, actor, action, target, details |
| `notifications` | Bildirishnomalar | id, user_id, type, message, is_read |
| `payments` | Toʻlovlar | id, tenant_id, amount, period_days, paid_at |
| `warnings` | Ogohlantirishlar | id, user_id, tenant_id, reason, issued_by |

Barcha jadvallarda **`tenant_id` orqali izolyatsiya** taʼminlanadi.

---

## 📥 O'rnatish va ishga tushirish

### Talablar
- Python 3.11+
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

### `.env` namunasi
```env
BOT_TOKEN=123456:ABC-DEF...
SUPER_ADMIN_ID=123456789
DB_PATH=data/enginebot.db
LOG_LEVEL=INFO
HEALTH_PORT=8080
```

---

## 🗺 Roadmap

### ✅ v1.0 — MVP (1-bosqich)
- [x] Loyiha skeleti
- [ ] Yadro (DB, permissions, tenant manager, audit log)
- [ ] 4 panel (super admin, tenant, moderator, user)
- [ ] Taxi plugin
- [ ] Aylanish servisi (rotation)
- [ ] Tasdiqlash tizimi
- [ ] Bildirishnoma tizimi

### 🔜 v1.5 — Kengaytirish (2-bosqich)
- [ ] Real estate plugin
- [ ] Jobs plugin
- [ ] Marketplace plugin
- [ ] Reyting tizimi
- [ ] Eksport (Excel, PDF)
- [ ] Kuzatish (notification subscription)

### 🔮 v2.0 — Pro (3-bosqich)
- [ ] Click/Payme avto-toʻlov
- [ ] VIP eʼlonlar (premium)
- [ ] Push notification
- [ ] Analytics dashboard (web)
- [ ] Telegram WebApp panel

### 🚀 v3.0 — Ekosistema
- [ ] REST API
- [ ] Mobile app (iOS, Android)
- [ ] Multi-language (UZ, RU, EN)
- [ ] AI yordamchi (eʼlonni yaxshilash)
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
