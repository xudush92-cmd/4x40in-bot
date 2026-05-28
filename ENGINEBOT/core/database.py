"""
core/database.py — SQLite asosidagi storage + per-tenant izolyatsiya.

ASOSIY PRINSIPLAR:
─────────────────
1. PER-TENANT IZOLYATSIYA
   Har bir jadvalda `tenant_id` ustuni bor. Barcha soʻrovlar
   `WHERE tenant_id=?` filtri bilan bajariladi. Ikki tenant bir-birini
   koʻra olmaydi — bu ENGINEBOT'ning eng muhim xavfsizlik printsipi.

2. ATOMIC OPERATSIYALAR
   Limit va INSERT'lar `BEGIN IMMEDIATE` transaction ichida bajariladi.
   Race condition yoʻq — ikki user bir vaqtda eʼlon bersa ham
   limit aniq saqlanadi.

3. WAL MODE
   Concurrent oʻqish/yozish xavfsiz. Bir vaqtda koʻp foydalanuvchi
   ishlasa ham DB blokirovka boʻlmaydi.

4. INDEKSLAR
   Har asosiy ustun (tenant_id, user_id, status) boʻyicha indeks bor —
   1000+ tenantda ham tez ishlaydi.

5. FOREIGN KEYS + CASCADE
   Tenant oʻchirilganda — barcha unga tegishli maʼlumot ham oʻchadi.
   Maʼlumot etim qolmaydi.

JADVALLAR:
──────────
- tenants         — kanal egalari (sizning mijozlaringiz)
- channels        — ulangan kanallar
- users           — foydalanuvchilar (per-tenant)
- announcements   — eʼlonlar
- moderators      — tenant yordamchilari
- audit_log       — har bir amal yoziladi
- notifications   — bildirishnomalar
- payments        — toʻlovlar tarixi
- warnings        — ogohlantirishlar
- tenant_settings — tenant boʻyicha sozlamalar (rotation, schedule)
"""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite

from config import (
    DB_PATH,
    DEFAULT_TZ_OFFSET,
    PostStatus,
    Rotation,
    TenantStatus,
    UserStatus,
)

logger = logging.getLogger("enginebot.db")


# ─────────────────────────────────────────────────────────────────────
# Connection helper
# ─────────────────────────────────────────────────────────────────────
@contextlib.asynccontextmanager
async def _conn() -> AsyncIterator[aiosqlite.Connection]:
    """
    SQLite ulanish konteksti.

    Har soʻrov uchun yangi ulanish ochiladi va avtomatik yopiladi.
    Bu — koʻp tenantli muhitda eng xavfsiz pattern (long-living
    connections — race riskini oshiradi).
    """
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("PRAGMA foreign_keys=ON")
        db.row_factory = aiosqlite.Row
        yield db
    finally:
        await db.close()


# ─────────────────────────────────────────────────────────────────────
# init_db — barcha jadvallarni yaratish
# ─────────────────────────────────────────────────────────────────────
async def init_db() -> None:
    """
    Bazani yaratish va sozlash.

    Idempotent — agar jadvallar mavjud boʻlsa hech narsa qilmaydi.
    Birinchi ishga tushirishda chaqiriladi (main.py'da).
    """
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        # WAL — concurrent access uchun
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("PRAGMA foreign_keys=ON")

        # ─── tenants ─────────────────────────────────────────────────
        # Asosiy jadval — har bir kanal egasi shu yerda.
        # tenant_id = Telegram user ID (tabiiy unique key).
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                tenant_id        INTEGER PRIMARY KEY,
                name             TEXT DEFAULT '',
                username         TEXT DEFAULT '',
                phone            TEXT DEFAULT '',
                email            TEXT DEFAULT '',
                tariff           TEXT DEFAULT 'trial',
                status           TEXT DEFAULT 'pending',
                paid_until       TEXT,
                total_paid_uzs   INTEGER DEFAULT 0,
                blocked_reason   TEXT,
                blocked_at       TEXT,
                created_at       TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at       TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ─── tenant_settings ─────────────────────────────────────────
        # Tenant'ning ON/OFF holatlari va rotation sozlamalari.
        # Alohida jadvalda — tez-tez oʻzgaradi, tenants jadvalini
        # bezovta qilmaydi.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tenant_settings (
                tenant_id            INTEGER PRIMARY KEY,
                bot_active           INTEGER DEFAULT 1,
                post_intake_active   INTEGER DEFAULT 1,
                rotation_active      INTEGER DEFAULT 0,
                rotation_interval_min INTEGER DEFAULT 30,
                post_lifetime_hours  INTEGER DEFAULT 24,
                active_from          TEXT DEFAULT '06:00',
                active_to            TEXT DEFAULT '23:00',
                require_approval     INTEGER DEFAULT 1,
                updated_at           TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
            )
        """)

        # ─── channels ────────────────────────────────────────────────
        # Tenant ulagan kanallar. Bot kanal admini boʻlishi shart.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL,
                channel_id      INTEGER NOT NULL,
                channel_username TEXT,
                title           TEXT DEFAULT '',
                category        TEXT DEFAULT 'general',
                is_active       INTEGER DEFAULT 1,
                added_at        TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, channel_id),
                FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
            )
        """)

        # ─── users ───────────────────────────────────────────────────
        # Foydalanuvchilar (taksist, sotuvchi, mijoz va h.k.).
        # MUHIM: bitta Telegram user bir nechta tenantda alohida user'dir!
        # Shuning uchun UNIQUE = (tenant_id, user_id).
        #
        # V1 yangiliklar:
        #   user_role           — "poster" | "customer" | "both"
        #   category_code       — "taxi", "plumber", ... (faqat poster uchun)
        #   region              — viloyat (mijoz uchun ham, poster uchun ham)
        #   rotation_interval_min — per-poster aylanish intervali (min 10)
        #   rotation_active     — poster auto-post ON/OFF
        #   current_post_index  — siklda hozir qaysi e'lon (0-based)
        #   last_rotated_at     — oxirgi rotation vaqti
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL,
                user_id         INTEGER NOT NULL,
                full_name       TEXT DEFAULT '',
                username        TEXT DEFAULT '',
                phone           TEXT DEFAULT '',
                user_role       TEXT DEFAULT 'customer',
                category_code   TEXT DEFAULT '',
                region          TEXT DEFAULT '',
                profile_data    TEXT DEFAULT '{}',
                status          TEXT DEFAULT 'pending',
                approved_by     INTEGER,
                approved_at     TEXT,
                rating          REAL DEFAULT 5.0,
                warnings_count  INTEGER DEFAULT 0,
                rotation_interval_min INTEGER DEFAULT 10,
                rotation_active INTEGER DEFAULT 0,
                current_post_index INTEGER DEFAULT 0,
                last_rotated_at TEXT,
                created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
                last_active_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, user_id),
                FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
            )
        """)

        # ─── announcements ───────────────────────────────────────────
        # Eʼlonlar. V1 — erkin matn (raw_text) + ixtiyoriy rasmlar (photos JSON).
        # message_id — kanaldagi post ID (yangilash/oʻchirish uchun).
        # category_code — kategoriya yorlig'i (qidiruvda foydalaniladi).
        await db.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL,
                user_id         INTEGER NOT NULL,
                channel_id      INTEGER NOT NULL,
                category_code   TEXT DEFAULT '',
                raw_text        TEXT DEFAULT '',
                photos          TEXT DEFAULT '[]',
                rendered_text   TEXT DEFAULT '',
                message_id      INTEGER,
                status          TEXT DEFAULT 'draft',
                queue_order     INTEGER DEFAULT 0,
                views_count     INTEGER DEFAULT 0,
                contacts_count  INTEGER DEFAULT 0,
                rotation_count  INTEGER DEFAULT 0,
                last_rotated_at TEXT,
                created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at      TEXT,
                FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
            )
        """)

        # ─── moderators ──────────────────────────────────────────────
        # Tenant yordamchilari. permissions = JSON (qaysi amallarga ruxsat).
        await db.execute("""
            CREATE TABLE IF NOT EXISTS moderators (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id   INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                permissions TEXT DEFAULT '[]',
                added_by    INTEGER,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, user_id),
                FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
            )
        """)

        # ─── audit_log ───────────────────────────────────────────────
        # HAR BIR muhim amal shu yerga yoziladi. Tergov, statistika,
        # xavfsizlik audit uchun.
        # tenant_id NULL boʻlishi mumkin (super admin global amallari).
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT DEFAULT CURRENT_TIMESTAMP,
                level       TEXT DEFAULT 'info',
                actor_role  TEXT NOT NULL,
                actor_id    INTEGER NOT NULL,
                tenant_id   INTEGER,
                action      TEXT NOT NULL,
                target_type TEXT,
                target_id   INTEGER,
                details     TEXT DEFAULT '{}'
            )
        """)

        # ─── notifications ───────────────────────────────────────────
        # Foydalanuvchilarga yuborilgan bildirishnomalar tarixi.
        # is_read — Telegram'dan tashqari ichki kuzatish uchun.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id   INTEGER,
                user_id     INTEGER NOT NULL,
                type        TEXT DEFAULT 'info',
                title       TEXT DEFAULT '',
                message     TEXT NOT NULL,
                payload     TEXT DEFAULT '{}',
                is_sent     INTEGER DEFAULT 0,
                sent_at     TEXT,
                is_read     INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ─── payments ────────────────────────────────────────────────
        # Toʻlovlar tarixi. Super admin qoʻlda kiritadi (ogʻzaki kelishuv).
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id    INTEGER NOT NULL,
                amount_uzs   INTEGER NOT NULL,
                tariff       TEXT NOT NULL,
                period_days  INTEGER NOT NULL,
                paid_at      TEXT DEFAULT CURRENT_TIMESTAMP,
                approved_by  INTEGER NOT NULL,
                note         TEXT DEFAULT '',
                FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
            )
        """)

        # ─── warnings ────────────────────────────────────────────────
        # Foydalanuvchiga berilgan ogohlantirishlar.
        # MAX_WARNINGS_BEFORE_BLOCK ga yetganida user avtomatik bloklanadi.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id   INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                issued_by   INTEGER NOT NULL,
                reason      TEXT NOT NULL,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
            )
        """)

        # ─── search_history ──────────────────────────────────────────
        # Mijoz qidiruv tarixi (max 20 ta oxirgi qidiruv).
        # category_code, keyword, region filtrlar saqlanadi.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS search_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL,
                user_id         INTEGER NOT NULL,
                category_code   TEXT DEFAULT '',
                keyword         TEXT DEFAULT '',
                region          TEXT DEFAULT '',
                results_count   INTEGER DEFAULT 0,
                created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
            )
        """)

        # ─── bookmarks ───────────────────────────────────────────────
        # Mijoz saqlagan e'lonlar (yulduzcha qilingan).
        # UNIQUE (tenant_id, user_id, post_id) — bir e'lonni 2 marta saqlash yo'q.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bookmarks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id   INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                post_id     INTEGER NOT NULL,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, user_id, post_id),
                FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
            )
        """)

        # ─── INDEKSLAR ───────────────────────────────────────────────
        # Tezlik uchun (1000+ tenant, 100k+ eʼlon stsenariysida)
        for stmt in [
            "CREATE INDEX IF NOT EXISTS idx_users_tenant       ON users(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_users_status       ON users(tenant_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_users_rotation     ON users(rotation_active, status)",
            "CREATE INDEX IF NOT EXISTS idx_users_role         ON users(tenant_id, user_role)",
            "CREATE INDEX IF NOT EXISTS idx_users_category     ON users(tenant_id, category_code)",
            "CREATE INDEX IF NOT EXISTS idx_channels_tenant    ON channels(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_ann_tenant_status  ON announcements(tenant_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_ann_user           ON announcements(tenant_id, user_id)",
            "CREATE INDEX IF NOT EXISTS idx_ann_user_status    ON announcements(tenant_id, user_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_ann_expires        ON announcements(status, expires_at)",
            "CREATE INDEX IF NOT EXISTS idx_ann_category       ON announcements(tenant_id, category_code, status)",
            "CREATE INDEX IF NOT EXISTS idx_audit_ts           ON audit_log(ts DESC)",
            "CREATE INDEX IF NOT EXISTS idx_audit_tenant       ON audit_log(tenant_id, ts DESC)",
            "CREATE INDEX IF NOT EXISTS idx_audit_actor        ON audit_log(actor_id, ts DESC)",
            "CREATE INDEX IF NOT EXISTS idx_notif_user         ON notifications(user_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_payments_tenant    ON payments(tenant_id, paid_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_warnings_tenant_u  ON warnings(tenant_id, user_id)",
            "CREATE INDEX IF NOT EXISTS idx_mods_tenant        ON moderators(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_bookmarks_user     ON bookmarks(tenant_id, user_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_search_hist_user   ON search_history(tenant_id, user_id, created_at DESC)",
        ]:
            await db.execute(stmt)

        # ─── MIGRATION (idempotent) ──────────────────────────────────
        # Eski DB bo'lsa — yangi ustunlarni qo'shamiz. ALTER TABLE
        # ustun mavjud bo'lsa "duplicate column" xatosi beradi —
        # try/except orqali jim o'tamiz.
        await _ensure_columns(db, "users", [
            ("user_role", "TEXT DEFAULT 'customer'"),
            ("category_code", "TEXT DEFAULT ''"),
            ("region", "TEXT DEFAULT ''"),
            ("rotation_interval_min", "INTEGER DEFAULT 10"),
            ("rotation_active", "INTEGER DEFAULT 0"),
            ("current_post_index", "INTEGER DEFAULT 0"),
            ("last_rotated_at", "TEXT"),
        ])
        await _ensure_columns(db, "announcements", [
            ("category_code", "TEXT DEFAULT ''"),
            ("raw_text", "TEXT DEFAULT ''"),
            ("photos", "TEXT DEFAULT '[]'"),
            ("queue_order", "INTEGER DEFAULT 0"),
        ])
        await _ensure_columns(db, "tenant_settings", [
            ("allowed_categories", "TEXT DEFAULT ''"),
        ])
        await _ensure_columns(db, "tenants", [
            ("description", "TEXT DEFAULT ''"),
        ])

        await db.commit()
        logger.info(f"DB tayyor: {DB_PATH}")


async def _ensure_columns(
    db: aiosqlite.Connection, table: str, columns: list[tuple[str, str]]
) -> None:
    """
    Idempotent migration: yo'q ustunlarni qo'shadi.

    SQLite'da ALTER TABLE ADD COLUMN IF NOT EXISTS yo'q, shuning uchun
    avval pragma_table_info bilan tekshiramiz.
    """
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        rows = await cur.fetchall()
    existing = {row[1] for row in rows}  # row[1] = column name

    for col_name, col_def in columns:
        if col_name in existing:
            continue
        try:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
            logger.info(f"migration: {table}.{col_name} qoʻshildi")
        except aiosqlite.OperationalError as e:
            # Boshqa concurrent process qoʻshib qoʻygan boʻlishi mumkin
            logger.debug(f"migration: {table}.{col_name} skip — {e}")


# ─────────────────────────────────────────────────────────────────────
# Yordamchilar
# ─────────────────────────────────────────────────────────────────────
def _now_iso() -> str:
    """Hozirgi vaqt ISO formatda (timezone bilan)."""
    return datetime.now(timezone(timedelta(hours=DEFAULT_TZ_OFFSET))).isoformat()


def _row_to_dict(row: aiosqlite.Row | None) -> dict | None:
    return dict(row) if row else None


def _rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════
# TENANTS — kanal egalari (sizning mijozlaringiz)
# ═════════════════════════════════════════════════════════════════════
async def create_tenant(
    tenant_id: int,
    name: str = "",
    username: str = "",
    tariff: str = "trial",
) -> dict:
    """
    Yangi tenantni yaratish (yoki mavjud boʻlsa qaytarish).

    Idempotent — bir necha marta chaqirish xavfsiz.
    """
    async with _conn() as db:
        await db.execute(
            """INSERT OR IGNORE INTO tenants
               (tenant_id, name, username, tariff, status)
               VALUES (?, ?, ?, ?, ?)""",
            (tenant_id, name, username, tariff, TenantStatus.PENDING),
        )
        # Default settings ham yaratamiz
        await db.execute(
            "INSERT OR IGNORE INTO tenant_settings (tenant_id) VALUES (?)",
            (tenant_id,),
        )
        await db.commit()

    tenant = await get_tenant(tenant_id)
    assert tenant is not None  # endi albatta bor
    return tenant


async def get_tenant(tenant_id: int) -> dict | None:
    async with _conn() as db:
        async with db.execute(
            "SELECT * FROM tenants WHERE tenant_id=?", (tenant_id,)
        ) as cur:
            return _row_to_dict(await cur.fetchone())


async def update_tenant(tenant_id: int, **fields) -> None:
    """Tenant'ning ixtiyoriy ustunlarini yangilash."""
    if not fields:
        return
    fields["updated_at"] = _now_iso()
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [tenant_id]
    async with _conn() as db:
        await db.execute(f"UPDATE tenants SET {sets} WHERE tenant_id=?", vals)
        await db.commit()


async def list_tenants(status: str | None = None, limit: int = 100) -> list[dict]:
    """Barcha tenantlar (status filtri bilan)."""
    async with _conn() as db:
        if status:
            cur = await db.execute(
                "SELECT * FROM tenants WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM tenants ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


async def count_tenants(status: str | None = None) -> int:
    async with _conn() as db:
        if status:
            cur = await db.execute(
                "SELECT COUNT(*) FROM tenants WHERE status=?", (status,)
            )
        else:
            cur = await db.execute("SELECT COUNT(*) FROM tenants")
        row = await cur.fetchone()
        await cur.close()
        return int(row[0]) if row else 0


# ═════════════════════════════════════════════════════════════════════
# TENANT SETTINGS — sozlamalar (ON/OFF, rotation, schedule)
# ═════════════════════════════════════════════════════════════════════
async def get_settings(tenant_id: int) -> dict:
    """Tenant sozlamalarini olish (yoki default yaratish)."""
    async with _conn() as db:
        async with db.execute(
            "SELECT * FROM tenant_settings WHERE tenant_id=?", (tenant_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            await db.execute(
                "INSERT INTO tenant_settings (tenant_id) VALUES (?)", (tenant_id,)
            )
            await db.commit()
            async with db.execute(
                "SELECT * FROM tenant_settings WHERE tenant_id=?", (tenant_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else {}


async def update_settings(tenant_id: int, **fields) -> None:
    """
    Tenant sozlamalarini yangilash.

    Boolean qiymatlar avtomatik 0/1 ga aylantiriladi.
    """
    if not fields:
        return
    # bool → int (SQLite tushunmaydi True/False)
    fields = {k: (int(v) if isinstance(v, bool) else v) for k, v in fields.items()}
    fields["updated_at"] = _now_iso()
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [tenant_id]
    async with _conn() as db:
        # Settings boʻlmasligi mumkin — avval yaratamiz
        await db.execute(
            "INSERT OR IGNORE INTO tenant_settings (tenant_id) VALUES (?)", (tenant_id,)
        )
        await db.execute(f"UPDATE tenant_settings SET {sets} WHERE tenant_id=?", vals)
        await db.commit()


# ═════════════════════════════════════════════════════════════════════
# CHANNELS — ulangan kanallar
# ═════════════════════════════════════════════════════════════════════
async def add_channel(
    tenant_id: int,
    channel_id: int,
    channel_username: str = "",
    title: str = "",
    category: str = "general",
) -> tuple[bool, str]:
    """
    Kanal qoʻshish (atomic).

    Returns: (ok, status)
        (True, "ok")        — qoʻshildi
        (False, "duplicate") — allaqachon mavjud
    """
    async with _conn() as db:
        try:
            await db.execute(
                """INSERT INTO channels (tenant_id, channel_id, channel_username, title, category)
                   VALUES (?, ?, ?, ?, ?)""",
                (tenant_id, channel_id, channel_username, title, category),
            )
            await db.commit()
            return True, "ok"
        except aiosqlite.IntegrityError:
            return False, "duplicate"


async def list_channels(tenant_id: int, only_active: bool = True) -> list[dict]:
    """Tenant kanallarini olish (faqat oʻzi)."""
    async with _conn() as db:
        if only_active:
            cur = await db.execute(
                "SELECT * FROM channels WHERE tenant_id=? AND is_active=1 ORDER BY id",
                (tenant_id,),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM channels WHERE tenant_id=? ORDER BY id",
                (tenant_id,),
            )
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


async def get_channel(tenant_id: int, channel_id: int) -> dict | None:
    """Maʼlum bir kanalni olish (tenant filtri bilan!)."""
    async with _conn() as db:
        async with db.execute(
            "SELECT * FROM channels WHERE tenant_id=? AND channel_id=?",
            (tenant_id, channel_id),
        ) as cur:
            return _row_to_dict(await cur.fetchone())


async def remove_channel(tenant_id: int, channel_id: int) -> bool:
    """Kanalni oʻchirish (faqat oʻz tenantnikini)."""
    async with _conn() as db:
        cur = await db.execute(
            "DELETE FROM channels WHERE tenant_id=? AND channel_id=?",
            (tenant_id, channel_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def update_channel_active(
    tenant_id: int, channel_id: int, *, is_active: bool
) -> bool:
    """Kanalni vaqtincha yoqish/o'chirish."""
    async with _conn() as db:
        cur = await db.execute(
            "UPDATE channels SET is_active=? WHERE tenant_id=? AND channel_id=?",
            (int(bool(is_active)), tenant_id, channel_id),
        )
        await db.commit()
        return cur.rowcount > 0


# ═════════════════════════════════════════════════════════════════════
# USERS — foydalanuvchilar (per-tenant)
# ═════════════════════════════════════════════════════════════════════
async def upsert_user(
    tenant_id: int,
    user_id: int,
    full_name: str = "",
    username: str = "",
    phone: str = "",
    profile_data: dict | None = None,
) -> dict:
    """
    Foydalanuvchini yaratish yoki yangilash (per-tenant).

    Returns: yangilangan foydalanuvchi dict.
    """
    profile_json = json.dumps(profile_data or {}, ensure_ascii=False)
    async with _conn() as db:
        # Avval mavjudligini tekshiramiz
        async with db.execute(
            "SELECT id FROM users WHERE tenant_id=? AND user_id=?",
            (tenant_id, user_id),
        ) as cur:
            existing = await cur.fetchone()

        if existing:
            await db.execute(
                """UPDATE users SET
                       full_name=COALESCE(NULLIF(?,''), full_name),
                       username=COALESCE(NULLIF(?,''), username),
                       phone=COALESCE(NULLIF(?,''), phone),
                       profile_data=?,
                       last_active_at=?
                   WHERE tenant_id=? AND user_id=?""",
                (full_name, username, phone, profile_json, _now_iso(), tenant_id, user_id),
            )
        else:
            await db.execute(
                """INSERT INTO users
                   (tenant_id, user_id, full_name, username, phone, profile_data, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (tenant_id, user_id, full_name, username, phone, profile_json, UserStatus.PENDING),
            )
        await db.commit()

        async with db.execute(
            "SELECT * FROM users WHERE tenant_id=? AND user_id=?",
            (tenant_id, user_id),
        ) as cur:
            return _row_to_dict(await cur.fetchone())  # type: ignore[return-value]


async def get_user(tenant_id: int, user_id: int) -> dict | None:
    """Foydalanuvchini olish (tenant filtri bilan)."""
    async with _conn() as db:
        async with db.execute(
            "SELECT * FROM users WHERE tenant_id=? AND user_id=?",
            (tenant_id, user_id),
        ) as cur:
            row = _row_to_dict(await cur.fetchone())
            if row and row.get("profile_data"):
                with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
                    row["profile_data"] = json.loads(row["profile_data"])
            return row


async def list_users(
    tenant_id: int,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Tenant foydalanuvchilari roʻyxati (faqat oʻz tenantida)."""
    async with _conn() as db:
        if status:
            cur = await db.execute(
                """SELECT * FROM users
                   WHERE tenant_id=? AND status=?
                   ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (tenant_id, status, limit, offset),
            )
        else:
            cur = await db.execute(
                """SELECT * FROM users
                   WHERE tenant_id=?
                   ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (tenant_id, limit, offset),
            )
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


async def count_users(tenant_id: int, status: str | None = None) -> int:
    async with _conn() as db:
        if status:
            cur = await db.execute(
                "SELECT COUNT(*) FROM users WHERE tenant_id=? AND status=?",
                (tenant_id, status),
            )
        else:
            cur = await db.execute(
                "SELECT COUNT(*) FROM users WHERE tenant_id=?", (tenant_id,)
            )
        row = await cur.fetchone()
        await cur.close()
        return int(row[0]) if row else 0


async def update_user(tenant_id: int, user_id: int, **fields) -> None:
    """User maydonlarini yangilash. profile_data dict boʻlsa JSON ga aylanadi."""
    if not fields:
        return
    if "profile_data" in fields and isinstance(fields["profile_data"], dict):
        fields["profile_data"] = json.dumps(fields["profile_data"], ensure_ascii=False)
    if isinstance(fields.get("warnings_count"), bool):
        fields["warnings_count"] = int(fields["warnings_count"])
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [tenant_id, user_id]
    async with _conn() as db:
        await db.execute(
            f"UPDATE users SET {sets} WHERE tenant_id=? AND user_id=?", vals
        )
        await db.commit()


async def set_user_status(
    tenant_id: int, user_id: int, status: str, approved_by: int | None = None
) -> None:
    """User statusini oʻzgartirish (approved_by — kim tasdiqlagan)."""
    fields: dict[str, Any] = {"status": status}
    if status == UserStatus.ACTIVE and approved_by is not None:
        fields["approved_by"] = approved_by
        fields["approved_at"] = _now_iso()
    await update_user(tenant_id, user_id, **fields)


# ═════════════════════════════════════════════════════════════════════
# ANNOUNCEMENTS — eʼlonlar
# ═════════════════════════════════════════════════════════════════════
async def create_announcement(
    tenant_id: int,
    user_id: int,
    channel_id: int,
    raw_text: str,
    rendered_text: str,
    *,
    category_code: str = "",
    photos: list[str] | None = None,
    lifetime_hours: int = Rotation.DEFAULT_LIFETIME_HOURS,
    max_active_per_user: int | None = None,
) -> tuple[bool, str, int | None]:
    """
    Yangi eʼlon yaratish (atomic, race-safe).

    V1: erkin matn + ixtiyoriy rasmlar (foto file_id'lar JSON ro'yxati).
    Limit tekshirish + INSERT bitta transactionda.

    Returns:
        (True, "ok", post_id)             — yaratildi (status=draft)
        (False, "limit", None)            — user limitiga yetdi
        (False, "channel_inactive", None) — kanal yoʻq yoki nofaol
    """
    expires_at = (
        datetime.now(timezone(timedelta(hours=DEFAULT_TZ_OFFSET)))
        + timedelta(hours=lifetime_hours)
    ).isoformat()
    photos_json = json.dumps(photos or [], ensure_ascii=False)

    async with _conn() as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            # 1. Kanal aktivmi?
            async with db.execute(
                """SELECT 1 FROM channels
                   WHERE tenant_id=? AND channel_id=? AND is_active=1""",
                (tenant_id, channel_id),
            ) as cur:
                if not await cur.fetchone():
                    await db.rollback()
                    return False, "channel_inactive", None

            # 2. Limit tekshirish (faqat aktiv eʼlonlar)
            if max_active_per_user is not None:
                async with db.execute(
                    """SELECT COUNT(*) FROM announcements
                       WHERE tenant_id=? AND user_id=?
                         AND status IN (?, ?, ?)""",
                    (tenant_id, user_id,
                     PostStatus.DRAFT, PostStatus.QUEUED, PostStatus.ACTIVE),
                ) as cur:
                    row = await cur.fetchone()
                    cnt = int(row[0]) if row else 0
                if cnt >= max_active_per_user:
                    await db.rollback()
                    return False, "limit", None

            # 3. queue_order — bitta ortga (galaning oxiriga)
            async with db.execute(
                """SELECT COALESCE(MAX(queue_order), 0) FROM announcements
                   WHERE tenant_id=? AND user_id=?""",
                (tenant_id, user_id),
            ) as cur:
                row = await cur.fetchone()
                next_order = int(row[0] or 0) + 1

            # 4. INSERT (status=DRAFT, scheduler tomonidan ACTIVE qilinadi)
            cur = await db.execute(
                """INSERT INTO announcements
                   (tenant_id, user_id, channel_id, category_code,
                    raw_text, photos, rendered_text,
                    status, queue_order, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    tenant_id, user_id, channel_id, category_code,
                    raw_text, photos_json, rendered_text,
                    PostStatus.DRAFT, next_order, expires_at,
                ),
            )
            post_id = cur.lastrowid
            await db.commit()
            return True, "ok", post_id

        except Exception:
            with contextlib.suppress(Exception):
                await db.rollback()
            raise


async def get_announcement(post_id: int, tenant_id: int | None = None) -> dict | None:
    """
    Eʼlonni ID boʻyicha olish.

    Agar tenant_id berilsa — qoʻshimcha izolyatsiya filtri qoʻshiladi
    (tenant boshqa tenantning postini koʻra olmaydi).
    """
    async with _conn() as db:
        if tenant_id is not None:
            cur = await db.execute(
                "SELECT * FROM announcements WHERE id=? AND tenant_id=?",
                (post_id, tenant_id),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM announcements WHERE id=?", (post_id,)
            )
        row = _row_to_dict(await cur.fetchone())
        await cur.close()
        if row:
            # photos JSON ni list'ga aylantirish
            if row.get("photos"):
                with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
                    row["photos"] = json.loads(row["photos"])
        return row


async def update_announcement(post_id: int, tenant_id: int, **fields) -> None:
    """Eʼlonni yangilash (tenant filtri bilan)."""
    if not fields:
        return
    if "photos" in fields and isinstance(fields["photos"], list):
        fields["photos"] = json.dumps(fields["photos"], ensure_ascii=False)
    fields["updated_at"] = _now_iso()
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [post_id, tenant_id]
    async with _conn() as db:
        await db.execute(
            f"UPDATE announcements SET {sets} WHERE id=? AND tenant_id=?", vals
        )
        await db.commit()


async def list_user_announcements(
    tenant_id: int,
    user_id: int,
    status: str | None = None,
) -> list[dict]:
    """Foydalanuvchining eʼlonlari (oʻz tenantida)."""
    async with _conn() as db:
        if status:
            cur = await db.execute(
                """SELECT * FROM announcements
                   WHERE tenant_id=? AND user_id=? AND status=?
                   ORDER BY created_at DESC""",
                (tenant_id, user_id, status),
            )
        else:
            cur = await db.execute(
                """SELECT * FROM announcements
                   WHERE tenant_id=? AND user_id=?
                   ORDER BY created_at DESC""",
                (tenant_id, user_id),
            )
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


async def list_active_announcements(
    tenant_id: int | None = None,
    channel_id: int | None = None,
) -> list[dict]:
    """
    Aktiv eʼlonlar roʻyxati (rotation va publishing uchun).

    tenant_id berilsa — faqat oʻsha tenantning. Aks holda hammasi
    (faqat super admin yoki global service uchun).
    """
    async with _conn() as db:
        clauses = ["status=?"]
        params: list[Any] = [PostStatus.ACTIVE]
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if channel_id is not None:
            clauses.append("channel_id=?")
            params.append(channel_id)
        where = " AND ".join(clauses)
        cur = await db.execute(
            f"SELECT * FROM announcements WHERE {where} ORDER BY last_rotated_at ASC NULLS FIRST, created_at ASC",
            params,
        )
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


async def list_expired_announcements() -> list[dict]:
    """Vaqti tugagan, lekin hali active boʻlgan eʼlonlar (cleaner uchun)."""
    async with _conn() as db:
        cur = await db.execute(
            """SELECT * FROM announcements
               WHERE status=? AND expires_at IS NOT NULL AND expires_at < ?""",
            (PostStatus.ACTIVE, _now_iso()),
        )
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


async def increment_announcement_counter(
    post_id: int, tenant_id: int, field: str
) -> None:
    """views_count / contacts_count / rotation_count ni +1."""
    if field not in ("views_count", "contacts_count", "rotation_count"):
        raise ValueError(f"Noruxsat ustun: {field}")
    async with _conn() as db:
        await db.execute(
            f"UPDATE announcements SET {field}={field}+1 WHERE id=? AND tenant_id=?",
            (post_id, tenant_id),
        )
        await db.commit()


# ═════════════════════════════════════════════════════════════════════
# MODERATORS
# ═════════════════════════════════════════════════════════════════════
async def add_moderator(
    tenant_id: int, user_id: int, permissions: list[str], added_by: int
) -> bool:
    """Moderator qoʻshish."""
    async with _conn() as db:
        try:
            await db.execute(
                """INSERT INTO moderators (tenant_id, user_id, permissions, added_by)
                   VALUES (?, ?, ?, ?)""",
                (tenant_id, user_id, json.dumps(permissions), added_by),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_moderator(tenant_id: int, user_id: int) -> bool:
    async with _conn() as db:
        cur = await db.execute(
            "DELETE FROM moderators WHERE tenant_id=? AND user_id=?",
            (tenant_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def is_moderator(tenant_id: int, user_id: int) -> bool:
    async with _conn() as db:
        async with db.execute(
            "SELECT 1 FROM moderators WHERE tenant_id=? AND user_id=?",
            (tenant_id, user_id),
        ) as cur:
            return (await cur.fetchone()) is not None


async def get_moderator(tenant_id: int, user_id: int) -> dict | None:
    async with _conn() as db:
        async with db.execute(
            "SELECT * FROM moderators WHERE tenant_id=? AND user_id=?",
            (tenant_id, user_id),
        ) as cur:
            row = _row_to_dict(await cur.fetchone())
            if row and row.get("permissions"):
                with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
                    row["permissions"] = json.loads(row["permissions"])
            return row


async def list_moderators(tenant_id: int) -> list[dict]:
    async with _conn() as db:
        cur = await db.execute(
            "SELECT * FROM moderators WHERE tenant_id=? ORDER BY created_at",
            (tenant_id,),
        )
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


# ═════════════════════════════════════════════════════════════════════
# AUDIT LOG
# ═════════════════════════════════════════════════════════════════════
async def write_audit(
    actor_role: str,
    actor_id: int,
    action: str,
    tenant_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    details: dict | None = None,
    level: str = "info",
) -> None:
    """Bitta audit yozuvi qoʻshish (har bir muhim amalda)."""
    async with _conn() as db:
        await db.execute(
            """INSERT INTO audit_log
               (level, actor_role, actor_id, tenant_id, action,
                target_type, target_id, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                level, actor_role, actor_id, tenant_id, action,
                target_type, target_id,
                json.dumps(details or {}, ensure_ascii=False),
            ),
        )
        await db.commit()


async def list_audit(
    tenant_id: int | None = None,
    actor_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Audit log oʻqish (filtr bilan)."""
    async with _conn() as db:
        clauses = []
        params: list[Any] = []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if actor_id is not None:
            clauses.append("actor_id=?")
            params.append(actor_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])
        cur = await db.execute(
            f"SELECT * FROM audit_log {where} ORDER BY ts DESC LIMIT ? OFFSET ?",
            params,
        )
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


# ═════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═════════════════════════════════════════════════════════════════════
async def add_notification(
    user_id: int,
    message: str,
    title: str = "",
    type_: str = "info",
    tenant_id: int | None = None,
    payload: dict | None = None,
) -> int:
    """Yangi bildirishnoma yozish (yuborilgunicha is_sent=0)."""
    async with _conn() as db:
        cur = await db.execute(
            """INSERT INTO notifications
               (tenant_id, user_id, type, title, message, payload)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                tenant_id, user_id, type_, title, message,
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )
        nid = cur.lastrowid
        await db.commit()
        return nid


async def mark_notification_sent(notif_id: int) -> None:
    async with _conn() as db:
        await db.execute(
            "UPDATE notifications SET is_sent=1, sent_at=? WHERE id=?",
            (_now_iso(), notif_id),
        )
        await db.commit()


async def list_pending_notifications(limit: int = 100) -> list[dict]:
    """Hali yuborilmagan bildirishnomalar (notifier service uchun)."""
    async with _conn() as db:
        cur = await db.execute(
            "SELECT * FROM notifications WHERE is_sent=0 ORDER BY created_at LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


# ═════════════════════════════════════════════════════════════════════
# PAYMENTS
# ═════════════════════════════════════════════════════════════════════
async def add_payment(
    tenant_id: int,
    amount_uzs: int,
    tariff: str,
    period_days: int,
    approved_by: int,
    note: str = "",
) -> int:
    """
    Yangi toʻlov yozuvi.

    paid_until ni avtomatik uzaytiradi (mavjud muddatga period_days qoʻshiladi,
    yoki bugundan boshlab).
    """
    now = datetime.now(timezone(timedelta(hours=DEFAULT_TZ_OFFSET)))
    async with _conn() as db:
        # 1. Toʻlov yozuvi
        cur = await db.execute(
            """INSERT INTO payments
               (tenant_id, amount_uzs, tariff, period_days, approved_by, note)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tenant_id, amount_uzs, tariff, period_days, approved_by, note),
        )
        payment_id = cur.lastrowid

        # 2. paid_until ni uzaytirish
        async with db.execute(
            "SELECT paid_until, total_paid_uzs FROM tenants WHERE tenant_id=?",
            (tenant_id,),
        ) as cur2:
            row = await cur2.fetchone()
        current_until = None
        total_paid = 0
        if row:
            if row[0]:
                with contextlib.suppress(ValueError, TypeError):
                    current_until = datetime.fromisoformat(row[0])
            total_paid = int(row[1] or 0)

        base = current_until if current_until and current_until > now else now
        new_until = (base + timedelta(days=period_days)).isoformat()

        await db.execute(
            """UPDATE tenants SET
                   paid_until=?,
                   total_paid_uzs=?,
                   tariff=?,
                   status=?,
                   updated_at=?
               WHERE tenant_id=?""",
            (
                new_until,
                total_paid + amount_uzs,
                tariff,
                TenantStatus.ACTIVE,
                _now_iso(),
                tenant_id,
            ),
        )
        await db.commit()
        return payment_id


async def list_payments(tenant_id: int, limit: int = 50) -> list[dict]:
    async with _conn() as db:
        cur = await db.execute(
            "SELECT * FROM payments WHERE tenant_id=? ORDER BY paid_at DESC LIMIT ?",
            (tenant_id, limit),
        )
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


# ═════════════════════════════════════════════════════════════════════
# WARNINGS
# ═════════════════════════════════════════════════════════════════════
async def add_warning(
    tenant_id: int, user_id: int, issued_by: int, reason: str
) -> int:
    """
    Foydalanuvchiga ogohlantirish yozish.

    user.warnings_count avtomatik +1 boʻladi.
    Chaqiruvchi MAX_WARNINGS_BEFORE_BLOCK ga yetganligini oʻzi tekshiradi.
    """
    async with _conn() as db:
        cur = await db.execute(
            """INSERT INTO warnings (tenant_id, user_id, issued_by, reason)
               VALUES (?, ?, ?, ?)""",
            (tenant_id, user_id, issued_by, reason),
        )
        wid = cur.lastrowid
        await db.execute(
            """UPDATE users
               SET warnings_count = warnings_count + 1
               WHERE tenant_id=? AND user_id=?""",
            (tenant_id, user_id),
        )
        await db.commit()
        return wid


async def list_warnings(tenant_id: int, user_id: int) -> list[dict]:
    async with _conn() as db:
        cur = await db.execute(
            """SELECT * FROM warnings
               WHERE tenant_id=? AND user_id=? ORDER BY created_at DESC""",
            (tenant_id, user_id),
        )
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


# ═════════════════════════════════════════════════════════════════════
# PER-POSTER ROTATION — V1 yangiliklari
# ═════════════════════════════════════════════════════════════════════
async def get_posters_with_active_rotation(limit: int = 10000) -> list[dict]:
    """
    Auto-post yoqilgan barcha posterlarni olish (scheduler uchun).

    Filter: status=active, rotation_active=1, user_role IN (poster, both)
    Faqat hech bo'lmaganda 1 ta aktiv eʼloni borlar.
    """
    async with _conn() as db:
        cur = await db.execute(
            """
            SELECT u.* FROM users u
            WHERE u.status = ?
              AND u.rotation_active = 1
              AND u.user_role IN ('poster', 'both')
              AND EXISTS (
                  SELECT 1 FROM announcements a
                  WHERE a.tenant_id = u.tenant_id
                    AND a.user_id = u.user_id
                    AND a.status IN (?, ?)
              )
            ORDER BY COALESCE(u.last_rotated_at, '0') ASC
            LIMIT ?
            """,
            (UserStatus.ACTIVE, PostStatus.ACTIVE, PostStatus.QUEUED, limit),
        )
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


async def get_user_post_queue(tenant_id: int, user_id: int) -> list[dict]:
    """
    Posterning gala ro'yxati (queue) — queue_order bo'yicha.

    Faqat aktiv yoki navbatdagi eʼlonlar (DRAFT/QUEUED/ACTIVE).
    Eskirgan/o'chirilganlar — chiqarilmaydi.
    """
    async with _conn() as db:
        cur = await db.execute(
            """SELECT * FROM announcements
               WHERE tenant_id=? AND user_id=?
                 AND status IN (?, ?, ?)
               ORDER BY queue_order ASC, id ASC""",
            (tenant_id, user_id,
             PostStatus.DRAFT, PostStatus.QUEUED, PostStatus.ACTIVE),
        )
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


async def advance_user_rotation(
    tenant_id: int, user_id: int, new_index: int
) -> None:
    """
    Posterning current_post_index'ini yangilash + last_rotated_at.

    Scheduler har rotation tickda chaqiradi.
    """
    await update_user(
        tenant_id, user_id,
        current_post_index=new_index,
        last_rotated_at=_now_iso(),
    )


async def set_poster_rotation(
    tenant_id: int, user_id: int, *, active: bool, interval_min: int | None = None
) -> None:
    """
    Posterning auto-post holatini yoqish/oʻchirish va intervalni belgilash.

    interval_min None boʻlsa — faqat ON/OFF oʻzgaradi.
    """
    fields: dict = {"rotation_active": int(bool(active))}
    if interval_min is not None:
        # MIN cheklov tasdiqlash
        from config import Rotation
        if interval_min < Rotation.MIN_INTERVAL_MIN:
            interval_min = Rotation.MIN_INTERVAL_MIN
        fields["rotation_interval_min"] = int(interval_min)
    await update_user(tenant_id, user_id, **fields)


async def reorder_user_queue(tenant_id: int, user_id: int) -> None:
    """
    Posterning eʼlonlar gala-tartibini qayta raqamlash (1, 2, 3, ...).

    Eʼlonni oʻchirgandan keyin chaqiriladi — qoʻshlik bo'lmasin.
    """
    async with _conn() as db:
        async with db.execute(
            """SELECT id FROM announcements
               WHERE tenant_id=? AND user_id=?
                 AND status IN (?, ?, ?)
               ORDER BY queue_order ASC, id ASC""",
            (tenant_id, user_id,
             PostStatus.DRAFT, PostStatus.QUEUED, PostStatus.ACTIVE),
        ) as cur:
            rows = await cur.fetchall()

        for new_order, (post_id,) in enumerate(rows, start=1):
            await db.execute(
                "UPDATE announcements SET queue_order=? WHERE id=?",
                (new_order, post_id),
            )
        await db.commit()


# ═════════════════════════════════════════════════════════════════════
# CUSTOMER QIDIRUV — V1 yangiliklari
# ═════════════════════════════════════════════════════════════════════
async def search_announcements(
    tenant_id: int,
    *,
    category_code: str | None = None,
    keyword: str | None = None,
    region: str | None = None,
    limit: int = 30,
) -> list[dict]:
    """
    Mijoz uchun aktiv eʼlonlarni qidirish.

    Filter: status=active, faqat shu tenantning.
    keyword bo'lsa — raw_text'da LIKE qidiruv.
    region bo'lsa — poster'ning viloyati bo'yicha JOIN filtr.
    """
    params: list = [tenant_id, PostStatus.ACTIVE]

    if region:
        # region filtri uchun users jadvaliga JOIN kerak
        q = """SELECT a.* FROM announcements a
               JOIN users u ON u.tenant_id = a.tenant_id
                           AND u.user_id   = a.user_id
               WHERE a.tenant_id = ? AND a.status = ?"""
        if category_code:
            q += " AND a.category_code = ?"
            params.append(category_code)
        if keyword:
            q += " AND a.raw_text LIKE ?"
            params.append(f"%{keyword}%")
        q += " AND u.region = ?"
        params.append(region)
        q += " ORDER BY a.last_rotated_at DESC, a.created_at DESC LIMIT ?"
    else:
        clauses = ["tenant_id = ?", "status = ?"]
        if category_code:
            clauses.append("category_code = ?")
            params.append(category_code)
        if keyword:
            clauses.append("raw_text LIKE ?")
            params.append(f"%{keyword}%")
        where = " AND ".join(clauses)
        q = (f"SELECT * FROM announcements WHERE {where}"
             " ORDER BY last_rotated_at DESC, created_at DESC LIMIT ?")

    params.append(limit)
    async with _conn() as db:
        cur = await db.execute(q, params)
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


# ─────────────────────────────────────────────────────────────────────
# SEARCH HISTORY — mijoz qidiruv tarixi
# ─────────────────────────────────────────────────────────────────────
async def add_search_history(
    tenant_id: int,
    user_id: int,
    *,
    category_code: str | None = None,
    keyword: str | None = None,
    region: str | None = None,
    results_count: int = 0,
) -> None:
    """
    Mijozning qidiruv tarixini saqlash (max 20 ta oxirgi).

    Yangi qidiruv qo'shilganda eng eski yozuv avtomatik o'chadi.
    """
    async with _conn() as db:
        await db.execute(
            """INSERT INTO search_history
               (tenant_id, user_id, category_code, keyword, region, results_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tenant_id, user_id,
             category_code or "", keyword or "", region or "",
             results_count),
        )
        # Max 20 ta: eski yozuvlarni tozalash
        await db.execute(
            """DELETE FROM search_history
               WHERE tenant_id=? AND user_id=?
                 AND id NOT IN (
                     SELECT id FROM search_history
                     WHERE tenant_id=? AND user_id=?
                     ORDER BY created_at DESC LIMIT 20
                 )""",
            (tenant_id, user_id, tenant_id, user_id),
        )
        await db.commit()


async def get_search_history(
    tenant_id: int, user_id: int, limit: int = 10
) -> list[dict]:
    """Mijozning oxirgi qidiruv tarixi (eng yangisi birinchi)."""
    async with _conn() as db:
        cur = await db.execute(
            """SELECT * FROM search_history
               WHERE tenant_id=? AND user_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (tenant_id, user_id, limit),
        )
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


async def clear_search_history(tenant_id: int, user_id: int) -> None:
    """Mijozning barcha qidiruv tarixini o'chirish."""
    async with _conn() as db:
        await db.execute(
            "DELETE FROM search_history WHERE tenant_id=? AND user_id=?",
            (tenant_id, user_id),
        )
        await db.commit()


async def get_recent_announcements(
    tenant_id: int, limit: int = 20
) -> list[dict]:
    """Eng so'nggi aktiv eʼlonlar (mijoz lentasi uchun)."""
    return await search_announcements(tenant_id, limit=limit)


# ═════════════════════════════════════════════════════════════════════
# Statistika (tenant darajasida)
# ═════════════════════════════════════════════════════════════════════
async def tenant_stats(tenant_id: int) -> dict:
    """Tenant uchun qisqa statistika."""
    async with _conn() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE tenant_id=?", (tenant_id,)
        ) as cur:
            users_total = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE tenant_id=? AND status=?",
            (tenant_id, UserStatus.ACTIVE),
        ) as cur:
            users_active = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM announcements WHERE tenant_id=? AND status=?",
            (tenant_id, PostStatus.ACTIVE),
        ) as cur:
            posts_active = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM channels WHERE tenant_id=? AND is_active=1",
            (tenant_id,),
        ) as cur:
            channels_active = (await cur.fetchone())[0]

        return {
            "users_total": users_total,
            "users_active": users_active,
            "posts_active": posts_active,
            "channels_active": channels_active,
        }


async def global_stats() -> dict:
    """Global statistika (super admin uchun)."""
    async with _conn() as db:
        async with db.execute("SELECT COUNT(*) FROM tenants") as cur:
            tenants_total = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM tenants WHERE status=?", (TenantStatus.ACTIVE,)
        ) as cur:
            tenants_active = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            users_total = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM announcements WHERE status=?", (PostStatus.ACTIVE,)
        ) as cur:
            posts_active = (await cur.fetchone())[0]
        async with db.execute("SELECT COALESCE(SUM(amount_uzs),0) FROM payments") as cur:
            total_revenue = (await cur.fetchone())[0]

        return {
            "tenants_total": tenants_total,
            "tenants_active": tenants_active,
            "users_total": users_total,
            "posts_active": posts_active,
            "total_revenue_uzs": int(total_revenue or 0),
        }



# ═════════════════════════════════════════════════════════════════════
# TENANT E'LON NAZORATI — v1.1
# ═════════════════════════════════════════════════════════════════════
async def list_tenant_announcements(
    tenant_id: int,
    status: str | None = None,
    category_code: str | None = None,
    limit: int = 30,
    offset: int = 0,
) -> list[dict]:
    """
    Tenant uchun e'lonlar ro'yxati (nazorat paneli).

    Filter: status va/yoki categoriya.
    """
    async with _conn() as db:
        clauses = ["tenant_id = ?"]
        params: list[Any] = [tenant_id]

        if status:
            clauses.append("status = ?")
            params.append(status)

        if category_code:
            clauses.append("category_code = ?")
            params.append(category_code)

        where = " AND ".join(clauses)
        params.extend([limit, offset])
        cur = await db.execute(
            f"""SELECT * FROM announcements
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?""",
            params,
        )
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


async def count_tenant_announcements(
    tenant_id: int, status: str | None = None
) -> int:
    """Tenant e'lonlar soni (status bo'yicha)."""
    async with _conn() as db:
        if status:
            cur = await db.execute(
                "SELECT COUNT(*) FROM announcements WHERE tenant_id=? AND status=?",
                (tenant_id, status),
            )
        else:
            cur = await db.execute(
                "SELECT COUNT(*) FROM announcements WHERE tenant_id=?",
                (tenant_id,),
            )
        row = await cur.fetchone()
        await cur.close()
        return int(row[0]) if row else 0


# ═════════════════════════════════════════════════════════════════════
# TENANT KENGAYTIRILGAN STATISTIKA — v1.1
# ═════════════════════════════════════════════════════════════════════
async def tenant_detailed_stats(tenant_id: int) -> dict:
    """
    Tenant uchun kengaytirilgan statistika.

    Bugungi, haftalik ma'lumotlar va top kategoriyalar.
    """
    now = _now_iso()
    today_start = now[:10] + "T00:00:00"
    # 7 kun oldin
    from datetime import datetime, timedelta, timezone
    week_ago = (
        datetime.now(timezone(timedelta(hours=DEFAULT_TZ_OFFSET)))
        - timedelta(days=7)
    ).isoformat()

    async with _conn() as db:
        # Umumiy raqamlar
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE tenant_id=?", (tenant_id,)
        ) as cur:
            users_total = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE tenant_id=? AND status=?",
            (tenant_id, UserStatus.ACTIVE),
        ) as cur:
            users_active = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE tenant_id=? AND user_role IN ('poster','both')",
            (tenant_id,),
        ) as cur:
            posters_count = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE tenant_id=? AND user_role IN ('customer','both')",
            (tenant_id,),
        ) as cur:
            customers_count = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM announcements WHERE tenant_id=? AND status=?",
            (tenant_id, PostStatus.ACTIVE),
        ) as cur:
            posts_active = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM channels WHERE tenant_id=? AND is_active=1",
            (tenant_id,),
        ) as cur:
            channels_active = (await cur.fetchone())[0]

        # Bugungi yangi foydalanuvchilar
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE tenant_id=? AND created_at >= ?",
            (tenant_id, today_start),
        ) as cur:
            today_new_users = (await cur.fetchone())[0]

        # Bugungi yangi e'lonlar
        async with db.execute(
            "SELECT COUNT(*) FROM announcements WHERE tenant_id=? AND created_at >= ?",
            (tenant_id, today_start),
        ) as cur:
            today_new_posts = (await cur.fetchone())[0]

        # Haftalik yangi e'lonlar
        async with db.execute(
            "SELECT COUNT(*) FROM announcements WHERE tenant_id=? AND created_at >= ?",
            (tenant_id, week_ago),
        ) as cur:
            week_new_posts = (await cur.fetchone())[0]

        # Aktiv rotation posterlar
        async with db.execute(
            """SELECT COUNT(*) FROM users
               WHERE tenant_id=? AND rotation_active=1 AND status=?""",
            (tenant_id, UserStatus.ACTIVE),
        ) as cur:
            rotation_active_posters = (await cur.fetchone())[0]

        # Top kategoriyalar (top 5)
        async with db.execute(
            """SELECT category_code, COUNT(*) as cnt
               FROM announcements
               WHERE tenant_id=? AND status=? AND category_code != ''
               GROUP BY category_code
               ORDER BY cnt DESC
               LIMIT 5""",
            (tenant_id, PostStatus.ACTIVE),
        ) as cur:
            top_categories = _rows_to_list(await cur.fetchall())

        return {
            "users_total": users_total,
            "users_active": users_active,
            "posters_count": posters_count,
            "customers_count": customers_count,
            "posts_active": posts_active,
            "channels_active": channels_active,
            "today_new_users": today_new_users,
            "today_new_posts": today_new_posts,
            "week_new_posts": week_new_posts,
            "rotation_active_posters": rotation_active_posters,
            "top_categories": top_categories,
        }


# ═════════════════════════════════════════════════════════════════════
# TENANT_SETTINGS: allowed_categories ustuni — v1.1
# ═════════════════════════════════════════════════════════════════════
async def get_allowed_categories(tenant_id: int) -> list[str]:
    """
    Tenant ruxsat bergan kategoriyalar ro'yxati.

    Bo'sh ro'yxat = BARCHASI ruxsat (default).
    """
    settings = await get_settings(tenant_id)
    raw = settings.get("allowed_categories", "") or ""
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


async def set_allowed_categories(tenant_id: int, codes: list[str]) -> None:
    """Tenant uchun ruxsat etilgan kategoriyalarni saqlash."""
    val = json.dumps(codes, ensure_ascii=False) if codes else ""
    await update_settings(tenant_id, allowed_categories=val)



# ═════════════════════════════════════════════════════════════════════
# BOOKMARKS — mijoz saqlagan e'lonlar (v1.1)
# ═════════════════════════════════════════════════════════════════════
async def add_bookmark(tenant_id: int, user_id: int, post_id: int) -> bool:
    """Mijoz e'lonni saqlash (yulduzcha)."""
    async with _conn() as db:
        try:
            await db.execute(
                """INSERT INTO bookmarks (tenant_id, user_id, post_id)
                   VALUES (?, ?, ?)""",
                (tenant_id, user_id, post_id),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False  # allaqachon saqlangan


async def remove_bookmark(tenant_id: int, user_id: int, post_id: int) -> bool:
    """Saqlangan e'lonni olib tashlash."""
    async with _conn() as db:
        cur = await db.execute(
            """DELETE FROM bookmarks
               WHERE tenant_id=? AND user_id=? AND post_id=?""",
            (tenant_id, user_id, post_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def is_bookmarked(tenant_id: int, user_id: int, post_id: int) -> bool:
    """E'lon saqlanganmi?"""
    async with _conn() as db:
        async with db.execute(
            """SELECT 1 FROM bookmarks
               WHERE tenant_id=? AND user_id=? AND post_id=?""",
            (tenant_id, user_id, post_id),
        ) as cur:
            return (await cur.fetchone()) is not None


async def list_bookmarks(
    tenant_id: int, user_id: int, limit: int = 30
) -> list[dict]:
    """
    Foydalanuvchining saqlangan e'lonlari (eng yangidan).

    JOIN qilamiz announcements bilan — barcha post ma'lumotlari bilan.
    Faqat aktiv yoki paused e'lonlar (deleted/expired chiqarilmaydi).
    """
    async with _conn() as db:
        cur = await db.execute(
            """SELECT a.*, b.created_at as bookmarked_at
               FROM bookmarks b
               JOIN announcements a ON a.id = b.post_id
               WHERE b.tenant_id=? AND b.user_id=?
                 AND a.status IN (?, ?, ?)
               ORDER BY b.created_at DESC
               LIMIT ?""",
            (
                tenant_id, user_id,
                PostStatus.ACTIVE, PostStatus.PAUSED, PostStatus.QUEUED,
                limit,
            ),
        )
        rows = await cur.fetchall()
        await cur.close()
        return _rows_to_list(rows)


async def count_bookmarks(tenant_id: int, user_id: int) -> int:
    """Saqlanganlar soni."""
    async with _conn() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM bookmarks WHERE tenant_id=? AND user_id=?",
            (tenant_id, user_id),
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0
