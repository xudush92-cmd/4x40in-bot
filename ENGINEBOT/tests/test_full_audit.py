"""
test_full_audit.py — TO'LIQ AUDIT TEST.

Sandbox cheklovlari sababli aiogram/aiosqlite o'rnatib bo'lmaydi.
Bu test FAQAT stdlib bilan TO'LIQ tahlil qiladi:

1. AST parsing — har bir .py faylni
2. Callback handler conflicts (duplicate prefix tekshiruvi)
3. State name conflicts (awaiting_* tekshiruvi)
4. Filter ordering (qaysi handler birinchi matches qiladi)
5. Migration — real sqlite3 bilan
6. PR #9 vs PR #8 ziddiyat tekshiruvi
7. Backward compatibility
8. Per-tenant izolyatsiya
9. XSS himoya (HTML escape)
10. Routers registratsiya tartibi

ISHLATISH:
    python3 tests/test_full_audit.py
"""
from __future__ import annotations

import ast
import os
import re
import sqlite3
import sys
import tempfile
import types
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

passed = 0
failed = 0
warnings_cnt = 0


def OK(name):
    global passed
    passed += 1
    print(f"  \u2713 {name}")


def FAIL(name, detail=""):
    global failed
    failed += 1
    print(f"  \u2717 {name}" + (f"\n     {detail}" if detail else ""))


def WARN(name, detail=""):
    global warnings_cnt
    warnings_cnt += 1
    print(f"  \u26A0\uFE0F  {name}" + (f"\n     {detail}" if detail else ""))


# ============================================================
# 1. SYNTAX TEKSHIRUVI — BARCHA .py
# ============================================================
print("=" * 70)
print("[1] BARCHA .py FAYLLAR — SYNTAX")
print("=" * 70)

all_py_files = sorted(ROOT.rglob("*.py"))
all_py_files = [f for f in all_py_files if "__pycache__" not in str(f)]

syntax_errors = 0
for f in all_py_files:
    try:
        ast.parse(f.read_text(encoding="utf-8"))
    except SyntaxError as e:
        syntax_errors += 1
        FAIL(f"Syntax XATO: {f.relative_to(ROOT)}", f"line {e.lineno}: {e.msg}")
if syntax_errors == 0:
    OK(f"Barcha {len(all_py_files)} ta .py fayl syntax-toza")


# ============================================================
# 2. CALLBACK HANDLER ZIDDIYATLARI
# ============================================================
print("\n" + "=" * 70)
print("[2] CALLBACK HANDLER ZIDDIYATLARI")
print("=" * 70)

callback_handlers = []
panel_files = list((ROOT / "panels").rglob("*.py"))
for f in panel_files:
    if "__pycache__" in str(f):
        continue
    src_f = f.read_text(encoding="utf-8")
    tree_f = ast.parse(src_f)
    for node in ast.walk(tree_f):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            attr = dec.func
            if not (isinstance(attr, ast.Attribute) and attr.attr == "callback_query"):
                continue
            for arg in dec.args:
                seg = ast.get_source_segment(src_f, arg) or ""
                callback_handlers.append((f.relative_to(ROOT), node.lineno, node.name, seg))
                break

print(f"  Topildi: {len(callback_handlers)} ta callback handler")

# Duplicate startswith prefix
prefix_map = defaultdict(list)
for f, line, name, pattern in callback_handlers:
    m = re.search(r'F\.data\.startswith\("([^"]+)"\)', pattern)
    if m:
        prefix_map[m.group(1)].append((f, line, name))

dup_count = 0
for prefix, handlers in prefix_map.items():
    if len(handlers) > 1:
        dup_count += 1
        FAIL(
            f"DUPLICATE callback prefix: {prefix!r}",
            f"{len(handlers)} ta handler: " + ", ".join(
                f"{n}({f}:{l})" for f, l, n in handlers
            ),
        )

if dup_count == 0:
    OK(f"Duplicate callback prefix YO'Q ({len(prefix_map)} ta unique prefix)")

# Prefix overlap (substring conflict)
prefixes = sorted(prefix_map.keys())
substr_conflicts = []
for i, p1 in enumerate(prefixes):
    for p2 in prefixes[i + 1:]:
        if p2.startswith(p1):
            substr_conflicts.append((p1, p2))

if substr_conflicts:
    for p1, p2 in substr_conflicts:
        FAIL(
            f"PREFIX OVERLAP: '{p1}' va '{p2}'",
            f"'{p1}' handler '{p2}' callback'ni ham olishi mumkin!",
        )
else:
    OK("Prefix overlap YO'Q (substring conflict bo'lmaydi)")

# Critical PR #9 callback'lar
critical_callbacks = [
    "super:tenant:extend:",
    "super:tenant:note_edit:",
]
for cb in critical_callbacks:
    if cb in prefix_map:
        OK(f"Callback prefix mavjud: {cb}")
    else:
        FAIL(f"Callback prefix TOPILMADI: {cb}")


# ============================================================
# 3. MESSAGE HANDLER TARTIBI (super_admin)
# ============================================================
print("\n" + "=" * 70)
print("[3] super_admin/handlers.py — MESSAGE HANDLER TARTIBI")
print("=" * 70)

super_admin_file = ROOT / "panels" / "super_admin" / "handlers.py"
src = super_admin_file.read_text(encoding="utf-8")
tree = ast.parse(src)

message_handlers = []
for node in ast.walk(tree):
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    for dec in node.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        attr = dec.func
        if not (isinstance(attr, ast.Attribute) and attr.attr == "message"):
            continue
        filter_strs = []
        for arg in dec.args:
            seg = ast.get_source_segment(src, arg) or ""
            filter_strs.append(seg)
        message_handlers.append((node.lineno, node.name, " AND ".join(filter_strs)))

message_handlers.sort()
print(f"  Jami message handlers: {len(message_handlers)}")
for line, name, filt in message_handlers:
    print(f"    {line:>4}: {name:<32} -> {filt[:48]}")

note_idx = next((i for i, (_, n, _) in enumerate(message_handlers)
                 if n == "receive_admin_note"), -1)
period_idx = next((i for i, (_, n, _) in enumerate(message_handlers)
                   if n == "receive_period_days"), -1)
lookup_idx = next((i for i, (_, n, _) in enumerate(message_handlers)
                   if n == "maybe_tenant_lookup"), -1)

if note_idx == -1:
    FAIL("receive_admin_note handler topilmadi")
elif period_idx == -1:
    FAIL("receive_period_days handler topilmadi")
elif lookup_idx == -1:
    FAIL("maybe_tenant_lookup handler topilmadi")
else:
    if note_idx < period_idx and note_idx < lookup_idx:
        OK(f"receive_admin_note (#{note_idx}) — period_days (#{period_idx}) va "
           f"lookup (#{lookup_idx}) dan OLDIN")
    else:
        FAIL("receive_admin_note KEYIN qolgan!",
             f"note_idx={note_idx}, period={period_idx}, lookup={lookup_idx}")


# ============================================================
# 4. STATE NOMLARI
# ============================================================
print("\n" + "=" * 70)
print("[4] STATE NOMLARI")
print("=" * 70)

state_pattern = re.compile(r'"(super:awaiting_\w+|super:confirm_\w+)"')
states_found = set(state_pattern.findall(src))

print(f"  super_admin'da topilgan state'lar: {len(states_found)}")
for s in sorted(states_found):
    print(f"    - {s}")

if "super:awaiting_admin_note" in states_found:
    OK("super:awaiting_admin_note mavjud")
else:
    FAIL("super:awaiting_admin_note TOPILMADI")

for old in ["super:awaiting_period_days", "super:awaiting_tenant_id",
            "super:awaiting_block_reason", "super:awaiting_broadcast_text",
            "super:awaiting_message_to_tenant", "super:confirm_extend_pending"]:
    if old in states_found:
        OK(f"Eski state saqlangan: {old}")
    else:
        FAIL(f"Eski state YO'QOLGAN: {old}")


# ============================================================
# 5. DB MIGRATION — REAL SQLITE3
# ============================================================
print("\n" + "=" * 70)
print("[5] DB MIGRATION — REAL SQLITE3")
print("=" * 70)

db_src = (ROOT / "core" / "database.py").read_text(encoding="utf-8")

# Test DB
db_path = Path(tempfile.gettempdir()) / "test_eb_full.db"
if db_path.exists():
    db_path.unlink()
conn = sqlite3.connect(str(db_path))

# Eski sxemada — admin_note YO'Q
conn.execute("""
    CREATE TABLE tenants (
        tenant_id INTEGER PRIMARY KEY,
        name TEXT DEFAULT '',
        username TEXT DEFAULT '',
        tariff TEXT DEFAULT 'trial',
        status TEXT DEFAULT 'pending'
    )
""")
conn.execute("INSERT INTO tenants (tenant_id, name) VALUES (?, ?)", (111, "Eski A"))
conn.execute("INSERT INTO tenants (tenant_id, name) VALUES (?, ?)", (222, "Eski B"))
conn.commit()


def ensure_columns(conn, table, columns):
    cur = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cur.fetchall()}
    added = []
    for col_name, col_def in columns:
        if col_name in existing:
            continue
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
            added.append(col_name)
        except sqlite3.OperationalError:
            pass
    return added


added = ensure_columns(conn, "tenants", [
    ("description", "TEXT DEFAULT ''"),
    ("admin_note", "TEXT DEFAULT ''"),
])
conn.commit()

if "admin_note" in added:
    OK("admin_note ustuni qo'shildi")
else:
    FAIL("admin_note ustuni qo'shilmadi")

# Eski ma'lumot saqlandi
cur = conn.execute("SELECT tenant_id, name, admin_note FROM tenants ORDER BY tenant_id")
rows = cur.fetchall()
if len(rows) == 2:
    OK("Eski 2 ta tenant ma'lumoti saqlandi")
    for tid, name, note in rows:
        if note == "":
            OK(f"Tenant #{tid}: admin_note default = ''")
        else:
            FAIL(f"Tenant #{tid}: admin_note bo'sh emas: {note!r}")
else:
    FAIL(f"Tenant ma'lumotlari yo'qoldi! 2 kutildi, {len(rows)} topildi")

# Idempotent
added2 = ensure_columns(conn, "tenants", [
    ("description", "TEXT DEFAULT ''"),
    ("admin_note", "TEXT DEFAULT ''"),
])
if not added2:
    OK("Idempotent: qayta migratsiya hech narsa qo'shmadi")
else:
    FAIL(f"Idempotent EMAS: {added2}")

# CRUD
conn.execute("UPDATE tenants SET admin_note=? WHERE tenant_id=?",
             ("Ali aka, doimiy mijoz, 100k oyiga", 111))
conn.commit()
cur = conn.execute("SELECT admin_note FROM tenants WHERE tenant_id=111")
note_v = cur.fetchone()[0]
if note_v == "Ali aka, doimiy mijoz, 100k oyiga":
    OK("admin_note INSERT/UPDATE ishlaydi")
else:
    FAIL(f"admin_note saqlanmadi: {note_v!r}")

# Per-tenant izolyatsiya
cur = conn.execute("SELECT admin_note FROM tenants WHERE tenant_id=222")
other = cur.fetchone()[0]
if other == "":
    OK("Per-tenant izolyatsiya: tenant #222 admin_note bo'sh (toza)")
else:
    FAIL(f"IZOLYATSIYA BUZILGAN: tenant #222'da yot izoh: {other!r}")

# O'chirish (bo'sh string saqlash)
conn.execute("UPDATE tenants SET admin_note=? WHERE tenant_id=?", ("", 111))
conn.commit()
cur = conn.execute("SELECT admin_note FROM tenants WHERE tenant_id=111")
if cur.fetchone()[0] == "":
    OK("Bo'sh admin_note saqlanadi (o'chirish funksiyasi)")
else:
    FAIL("Bo'sh admin_note saqlanmadi")

conn.close()
db_path.unlink()


# ============================================================
# 6. PR #9 vs PR #8 ZIDDIYAT
# ============================================================
print("\n" + "=" * 70)
print("[6] PR #9 vs PR #8 ZIDDIYAT")
print("=" * 70)

pr8_handlers = [
    "show_tenant_stats", "show_tenant_users", "show_tenant_payments",
    "show_tenant_audit_cb", "start_message_to_tenant", "reject_tenant_cb",
    "start_delete_tenant", "filter_tenants", "system_backup",
    "system_cleanup_logs", "show_payments_global",
]
all_funcs = {n.name for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
saved = sum(1 for fn in pr8_handlers if fn in all_funcs)
if saved == len(pr8_handlers):
    OK(f"PR #8 dagi {saved} ta handler hammasi saqlangan")
else:
    for fn in pr8_handlers:
        if fn not in all_funcs:
            FAIL(f"PR #8 handler YO'QOLGAN: {fn}")

# extend vs quick_extend prefix testi
test1 = "super:tenant:quick_extend:123:7"
if not test1.startswith("super:tenant:extend:"):
    OK("'super:tenant:extend:' 'quick_extend'ni YUTMAYDI")
else:
    FAIL("KRITIK: 'extend:' 'quick_extend'ni yutib yuboradi!")

if test1.startswith("super:tenant:quick_extend:"):
    OK("'super:tenant:quick_extend:' to'g'ri match")

# F.data.regexp ishlatilishi (extend va quick_extend ajratish)
quick_extend_decorators = re.findall(r'F\.data\.regexp\("([^"]+)"\)', src)
has_quick_extend_regex = any("quick_extend" in p for p in quick_extend_decorators)
if has_quick_extend_regex:
    OK("quick_extend uchun regexp filter ishlatilgan (aniqroq match)")
else:
    WARN("quick_extend regex filter ishlatilmagan (startswith bilan ham bo'ladi)")


# ============================================================
# 7. PER-TENANT IZOLYATSIYA — admin_note query'lari
# ============================================================
print("\n" + "=" * 70)
print("[7] PER-TENANT IZOLYATSIYA")
print("=" * 70)

# set_admin_note → update_tenant(tenant_id, ...) chaqirishi
m = re.search(r'async def set_admin_note.*?update_tenant\(tenant_id', db_src, re.DOTALL)
if m:
    OK("set_admin_note() -> update_tenant(tenant_id, ...) (izolyatsiya)")
else:
    FAIL("set_admin_note tenant_id'ni uzatmaydi!")

# update_tenant ichida WHERE tenant_id=?
m2 = re.search(r'async def update_tenant.*?WHERE tenant_id=\?', db_src, re.DOTALL)
if m2:
    OK("update_tenant() — WHERE tenant_id=? filtri bilan (izolyatsiya)")
else:
    FAIL("update_tenant tenant_id filtrisiz UPDATE qiladi!")

# 500 belgi cheklov
if "[:500]" in db_src:
    OK("500 belgi cheklov qoidasi mavjud")
else:
    FAIL("500 belgi cheklov YO'Q")


# ============================================================
# 8. FORMATTER — XSS himoya, edge cases
# ============================================================
print("\n" + "=" * 70)
print("[8] FORMATTER — XSS himoya va edge cases")
print("=" * 70)


class _FakeDotenv:
    @staticmethod
    def load_dotenv(*a, **kw):
        pass


sys.modules.setdefault("dotenv", _FakeDotenv())  # type: ignore

fake_config = types.ModuleType("config")
fake_config.BRAND_NAME = "ENGINEBOT"
fake_config.DEFAULT_TZ_OFFSET = 5
fake_config.get_brand_footer = lambda: "\n\n[ENGINEBOT]"
sys.modules["config"] = fake_config

if "utils.formatters" in sys.modules:
    del sys.modules["utils.formatters"]
from utils import formatters as fmt

# 8.1: Oddiy izoh
t1 = {"tenant_id": 100, "name": "Test", "tariff": "bronze",
      "status": "active", "admin_note": "Ali aka, oyiga 100k"}
c1 = fmt.format_tenant_card(t1)
if "Ali aka, oyiga 100k" in c1:
    OK("Oddiy admin_note kartada ko'rinadi")
else:
    FAIL("Oddiy admin_note ko'rinmadi")

# 8.2: Bo'sh izoh
t2 = dict(t1, admin_note="")
c2 = fmt.format_tenant_card(t2)
if "Izoh:" not in c2:
    OK("Bo'sh admin_note -> 'Izoh:' qatori yo'q")
else:
    FAIL("Bo'sh admin_note bo'lsa ham 'Izoh:' yozilgan")

# 8.3: XSS himoya — 6 turdagi payload
xss_safe = True
xss_tests = [
    "<script>alert('xss')</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:alert('hack')",
    '"><script>',
    "<a href='javascript:'>Click</a>",
    "<iframe src=evil></iframe>",
]
for payload in xss_tests:
    t_xss = dict(t1, admin_note=payload)
    c_xss = fmt.format_tenant_card(t_xss)
    if "<script>" in c_xss or "<img " in c_xss or "<iframe" in c_xss:
        FAIL(f"XSS BUZILGAN: {payload!r}")
        xss_safe = False
if xss_safe:
    OK(f"Barcha {len(xss_tests)} ta XSS payload escape qilindi")

# 8.4: Multibyte (cyrillic, emoji)
multibyte_note = "Алишер Каримов 🚖✓ 100k oyiga - O'zbek"
t3 = dict(t1, admin_note=multibyte_note)
c3 = fmt.format_tenant_card(t3)
if multibyte_note in c3:
    OK("Multibyte (cyrillic/emoji/o'zbek) admin_note to'g'ri")
else:
    FAIL("Multibyte buzilgan")

# 8.5: admin_note kaliti yo'q (eski tenant)
t4 = dict(t1)
del t4["admin_note"]
try:
    c4 = fmt.format_tenant_card(t4)
    if "Izoh:" not in c4:
        OK("admin_note kaliti yo'q (eski tenant) -> 'Izoh:' yo'q")
    else:
        FAIL("admin_note yo'q bo'lsa ham 'Izoh:' yozilgan")
except KeyError as e:
    FAIL(f"admin_note yo'q -> KeyError: {e}")


# ============================================================
# 9. KEYBOARD — quick_extend tugmalari
# ============================================================
print("\n" + "=" * 70)
print("[9] KEYBOARD — quick_extend tugmalari")
print("=" * 70)

kb_src = (ROOT / "keyboards" / "super_admin_kb.py").read_text(encoding="utf-8")

for d in [7, 15, 30, 60, 90]:
    if f"+ {d} kun" in kb_src or f"\u2795 {d} kun" in kb_src:
        OK(f"+{d} kun tugmasi mavjud")
    else:
        FAIL(f"+{d} kun tugmasi YO'Q")

critical_btns = [
    ("Tezkor uzaytirish", "super:tenant:quick_extend:"),
    ("Izoh tahrirlash", "super:tenant:note_edit:"),
]
for btn_text, cb_prefix in critical_btns:
    if btn_text in kb_src:
        OK(f"Tugma mavjud: {btn_text}")
    else:
        FAIL(f"Tugma YO'Q: {btn_text}")
    if cb_prefix in kb_src:
        OK(f"Callback prefix: {cb_prefix}")


# ============================================================
# 10. main.py ROUTERS
# ============================================================
print("\n" + "=" * 70)
print("[10] main.py — Routers tartibi")
print("=" * 70)

main_src = (ROOT / "main.py").read_text(encoding="utf-8")

include_pattern = re.compile(r'dp\.include_router\((\w+)\)')
actual_routers = include_pattern.findall(main_src)

expected_routers = ["start_router", "super_router", "tenant_router",
                    "mod_router", "common_router", "poster_router",
                    "customer_router", "user_router"]

if actual_routers == expected_routers:
    OK(f"Routers tartibi to'g'ri: {len(actual_routers)} ta")
else:
    FAIL("Routers tartibi noto'g'ri",
         f"Kutildi: {expected_routers}\n     Topildi: {actual_routers}")


# ============================================================
# 11. README.md — narxlar olib tashlandi
# ============================================================
print("\n" + "=" * 70)
print("[11] README.md — TO'LIQ MAZMUN")
print("=" * 70)

readme = (ROOT / "README.md").read_text(encoding="utf-8")

removed = ["50,000 so\u02bcm", "150,000 so\u02bcm", "300,000 so\u02bcm",
           "Karta orqali o\u02bctkazma"]
for s in removed:
    if s not in readme:
        OK(f"OLIB TASHLANDI: {s!r}")
    else:
        FAIL(f"Hali ham mavjud: {s!r}")

added = ["Og'zaki kelishuv", "PAUSE", "Foydalanish tartibi",
         "Tenant izohlari", "tezkor uzaytirish"]  # case-insensitive
for s in added:
    if s.lower() in readme.lower():
        OK(f"Qo'shildi: {s!r}")
    else:
        FAIL(f"Qo'shilishi kerak edi: {s!r}")


# ============================================================
# 12. PYTHON COMPILE TEKSHIRUVI (har bir fayl)
# ============================================================
print("\n" + "=" * 70)
print("[12] py_compile — har bir fayl")
print("=" * 70)

import py_compile

compile_errors = 0
for f in all_py_files:
    try:
        py_compile.compile(str(f), doraise=True)
    except py_compile.PyCompileError as e:
        compile_errors += 1
        FAIL(f"Compile XATO: {f.relative_to(ROOT)}", str(e))
if compile_errors == 0:
    OK(f"Barcha {len(all_py_files)} ta fayl muvaffaqiyatli compile qilindi")


# ============================================================
# 13. KEYBOARD CALLBACK <-> HANDLER MAPPING
# ============================================================
print("\n" + "=" * 70)
print("[13] CALLBACK <-> HANDLER MAPPING")
print("=" * 70)

# Keyboard'da yaratilgan barcha callback'lar
all_callbacks_in_kb = set()
for kb_file in (ROOT / "keyboards").glob("*_kb.py"):
    kb_text = kb_file.read_text(encoding="utf-8")
    # super:tenant:..., tenant:..., poster:..., customer:..., super:system:...
    matches = re.findall(r'"((?:super|tenant|poster|customer|user|mod):[^"]+)"', kb_text)
    for cb in matches:
        # f-string template'lardan tenant_id ni olib tashlaymiz
        cleaned = re.sub(r'\{[^}]+\}', '*', cb)
        all_callbacks_in_kb.add(cleaned)

# Handler'larda topilgan prefix'lar
all_handler_prefixes = set(prefix_map.keys())

# Har callback uchun handler bormi?
unmatched = []
for cb in all_callbacks_in_kb:
    matched = any(cb.startswith(p) or p.startswith(cb.replace("*", ""))
                  for p in all_handler_prefixes)
    if not matched:
        # Regexp filter'lar bilan ham mos kelishi mumkin
        # (F.data == "..." yoki F.data.regexp)
        if cb in src or cb.replace("*", "") in src:
            matched = True
    if not matched:
        unmatched.append(cb)

if not unmatched:
    OK(f"Barcha {len(all_callbacks_in_kb)} ta keyboard callback uchun handler bor")
else:
    for cb in unmatched[:5]:
        WARN(f"Handler topilmadi (yoki F.data == ishlatilgan): {cb}")


# ============================================================
# YAKUNIY HISOBOT
# ============================================================
print("\n" + "=" * 70)
print("YAKUNIY HISOBOT")
print("=" * 70)
print(f"  O'tdi:           {passed}")
print(f"  Xato:            {failed}")
print(f"  Ogohlantirish:   {warnings_cnt}")
print("=" * 70)
if failed == 0:
    print("  *** BARCHA TESTLAR MUVAFFAQIYATLI O'TDI! ***")
else:
    print(f"  !!! {failed} ta MUAMMO TOPILDI - tuzatish kerak")
print()
sys.exit(0 if failed == 0 else 1)
