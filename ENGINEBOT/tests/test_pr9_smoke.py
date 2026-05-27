"""
test_pr9_smoke.py — PR #9 yangi funksiyalari uchun standalone smoke test.

Pytest yoki tashqi kutubxonalarsiz ishlaydi (faqat stdlib).
Tekshiradi:
1. DB migration: admin_note ustuni qo'shilishi
2. set_admin_note mantiqi (500 belgi cheklov)
3. format_tenant_card admin_note ko'rsatishi
4. README.md narxlar olib tashlanganligi
5. super_admin_kb.py quick_extend funksiyalari
6. handlers.py yangi handler funksiyalari (registratsiya tartibi)
7. database.py set_admin_note + migration

ISHLATISH:
    python3 tests/test_pr9_smoke.py
"""
from __future__ import annotations

import ast
import os
import sqlite3
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Fake env
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("SUPER_ADMIN_ID", "999999")

# Stub dotenv (sandbox'da yo'q)
class _FakeDotenv:
    @staticmethod
    def load_dotenv(*a, **kw): pass
sys.modules.setdefault("dotenv", _FakeDotenv())  # type: ignore

passed = 0
failed = 0


def assert_eq(actual, expected, name):
    global passed, failed
    if actual == expected:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}\n     Expected: {expected!r}\n     Got:      {actual!r}")


def assert_in(needle, haystack, name):
    global passed, failed
    if needle in haystack:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}\n     Looking for: {needle!r}")


def assert_true(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}")


# ─────────────────────────────────────────────────────────────────
print("\n[TEST 1] DB Migration — admin_note ustuni qo'shilishi")

db_path = Path(tempfile.gettempdir()) / "test_eb_pr9.db"
if db_path.exists():
    db_path.unlink()

conn = sqlite3.connect(str(db_path))
conn.execute("""
    CREATE TABLE tenants (
        tenant_id INTEGER PRIMARY KEY,
        name TEXT DEFAULT '',
        description TEXT DEFAULT ''
    )
""")
conn.execute("INSERT INTO tenants (tenant_id, name) VALUES (?, ?)", (123, "Eski tenant"))
conn.commit()

cur = conn.execute("PRAGMA table_info(tenants)")
cols_before = {row[1] for row in cur.fetchall()}
assert_true("admin_note" not in cols_before, "Boshlang'ich: admin_note yo'q")
assert_true("description" in cols_before, "Boshlang'ich: description bor")


def ensure_columns(conn, table, columns):
    """database.py'dagi _ensure_columns mantigining sync versiyasi."""
    cur = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cur.fetchall()}
    for col_name, col_def in columns:
        if col_name in existing:
            continue
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
        except sqlite3.OperationalError:
            pass


ensure_columns(conn, "tenants", [
    ("description", "TEXT DEFAULT ''"),
    ("admin_note", "TEXT DEFAULT ''"),
])
conn.commit()

cur = conn.execute("PRAGMA table_info(tenants)")
cols_after = {row[1] for row in cur.fetchall()}
assert_true("admin_note" in cols_after, "Migratsiyadan keyin: admin_note bor")

cur = conn.execute("SELECT name, admin_note FROM tenants WHERE tenant_id=?", (123,))
row = cur.fetchone()
assert_eq(row[0], "Eski tenant", "Eski tenant ma'lumoti saqlandi")
assert_eq(row[1], "", "admin_note default qiymat ('')")

# Idempotent
ensure_columns(conn, "tenants", [("admin_note", "TEXT DEFAULT ''")])
cur = conn.execute("PRAGMA table_info(tenants)")
cols_after2 = {row[1] for row in cur.fetchall()}
assert_eq(len(cols_after2), len(cols_after), "Migratsiya idempotent")

# UPDATE: yangi qiymat saqlash
conn.execute("UPDATE tenants SET admin_note=? WHERE tenant_id=?",
             ("Ali aka, 100k oyiga", 123))
conn.commit()
cur = conn.execute("SELECT admin_note FROM tenants WHERE tenant_id=?", (123,))
assert_eq(cur.fetchone()[0], "Ali aka, 100k oyiga", "admin_note UPDATE ishlaydi")

conn.close()
db_path.unlink()


# ─────────────────────────────────────────────────────────────────
print("\n[TEST 2] set_admin_note mantiqi — uzunlik chekloviga rioya")

def simulate_set_admin_note(note):
    """database.set_admin_note dan: (note or "").strip()[:500]"""
    return (note or "").strip()[:500]

assert_eq(simulate_set_admin_note("Ali aka, 100k oyiga"),
          "Ali aka, 100k oyiga", "Oddiy izoh saqlanadi")
assert_eq(simulate_set_admin_note("  trim me  "), "trim me", "Bo'sh joylar trim")
assert_eq(simulate_set_admin_note(""), "", "Bo'sh string → bo'sh natija")
assert_eq(simulate_set_admin_note(None), "", "None → bo'sh natija")
assert_eq(len(simulate_set_admin_note("X" * 600)), 500, "600 belgi → 500 ga qisqaradi")


# ─────────────────────────────────────────────────────────────────
print("\n[TEST 3] format_tenant_card — admin_note ko'rsatadi")

# config stub
fake_config = types.ModuleType("config")
fake_config.BRAND_NAME = "ENGINEBOT"
fake_config.DEFAULT_TZ_OFFSET = 5
fake_config.get_brand_footer = lambda: "\n\n⚙️ ENGINEBOT"
sys.modules["config"] = fake_config

from utils import formatters as fmt

tenant_with = {
    "tenant_id": 123, "name": "Test", "username": "test_taxi",
    "tariff": "bronze", "status": "active",
    "admin_note": "Ali aka, har oyda 100k beradi",
}
card_with = fmt.format_tenant_card(tenant_with)
assert_in("Ali aka, har oyda 100k beradi", card_with, "admin_note matni kartada")
assert_in("📝", card_with, "Izoh emoji ishlatildi")

tenant_without = {**tenant_with, "admin_note": ""}
card_without = fmt.format_tenant_card(tenant_without)
assert_true("Izoh:" not in card_without, "Bo'sh admin_note → 'Izoh:' yozuvi yo'q")

# XSS himoya
tenant_xss = {**tenant_with, "admin_note": "<script>alert('hack')</script>"}
card_xss = fmt.format_tenant_card(tenant_xss)
assert_true("<script>" not in card_xss, "HTML tag escape qilindi")
assert_in("&lt;script&gt;", card_xss, "HTML entity'ga o'girildi")


# ─────────────────────────────────────────────────────────────────
print("\n[TEST 4] README.md — narxlar olib tashlangan")

readme = (ROOT / "README.md").read_text(encoding="utf-8")
assert_true("50,000 soʻm" not in readme, "Bronze 50k OLIB TASHLANDI")
assert_true("150,000 soʻm" not in readme, "Silver 150k OLIB TASHLANDI")
assert_true("300,000 soʻm" not in readme, "Gold 300k OLIB TASHLANDI")
assert_in("Og'zaki kelishuv", readme, "'Og'zaki kelishuv' qo'shildi")
assert_in("PAUSE", readme, "PAUSE rejimi tushuntirilgan")
assert_in("Foydalanish tartibi", readme, "Yangi 'Foydalanish tartibi' bo'limi")


# ─────────────────────────────────────────────────────────────────
print("\n[TEST 5] super_admin_kb.py — quick_extend funksiyalari")

kb_src = (ROOT / "keyboards" / "super_admin_kb.py").read_text(encoding="utf-8")
tree = ast.parse(kb_src)
func_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

assert_in("quick_extend_picker", func_names, "quick_extend_picker mavjud")
assert_in("tenant_actions", func_names, "tenant_actions saqlangan")

for days in ["7", "15", "30", "60", "90"]:
    assert_in(f"➕ {days} kun", kb_src, f"+{days} kun tugmasi mavjud")

assert_in("super:tenant:quick_extend:", kb_src, "quick_extend callback prefix")
assert_in("super:tenant:note_edit:", kb_src, "note_edit callback prefix")


# ─────────────────────────────────────────────────────────────────
print("\n[TEST 6] handlers.py — yangi handlerlar va registratsiya tartibi")

handlers_src = (ROOT / "panels" / "super_admin" / "handlers.py").read_text(encoding="utf-8")
tree = ast.parse(handlers_src)
funcs = {n.name for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

for fn in ["show_quick_extend_picker", "apply_quick_extend",
           "confirm_quick_extend_yes", "confirm_quick_extend_no",
           "start_note_edit", "receive_admin_note", "_is_admin_note_state"]:
    assert_in(fn, funcs, f"{fn} handler mavjud")

# CRITICAL: receive_admin_note ERTA registratsiya qilinganmi?
note_pos = handlers_src.find("async def receive_admin_note")
period_pos = handlers_src.find("async def receive_period_days")
lookup_pos = handlers_src.find("async def maybe_tenant_lookup")
assert_true(note_pos < period_pos,
            "receive_admin_note receive_period_days'dan OLDIN")
assert_true(note_pos < lookup_pos,
            "receive_admin_note maybe_tenant_lookup'dan OLDIN")


# ─────────────────────────────────────────────────────────────────
print("\n[TEST 7] database.py — set_admin_note va migration")

db_src = (ROOT / "core" / "database.py").read_text(encoding="utf-8")
tree = ast.parse(db_src)
funcs = {n.name for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

assert_in("set_admin_note", funcs, "set_admin_note funksiyasi qo'shilgan")
assert_in('("admin_note", "TEXT DEFAULT \'\'")', db_src, "admin_note migration qatori")
assert_in("[:500]", db_src, "500 belgi cheklov qoidasi")


# ─────────────────────────────────────────────────────────────────
print("\n" + "═" * 60)
print(f"NATIJA: ✅ {passed} ta o'tdi, ❌ {failed} ta xato")
print("═" * 60)
sys.exit(0 if failed == 0 else 1)
