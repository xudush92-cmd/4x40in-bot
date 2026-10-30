#!/usr/bin/env python3
"""Bazani tozalash vositasi.

Eski modeldan qolgan ma'lumotlar (eski userlar, uzilgan sessiyalar,
o'chirilgan guruhlar, stop_words/client_words kabi bo'sh jadvallar)
botni chalg'itishi mumkin. Bu skript bazani noldan boshlash uchun.

Ishlatish (botni to'xtatib):

    systemctl stop scanner-bot
    python3 reset_db.py --stats      # avval nimalar borligini ko'rish
    python3 reset_db.py --full       # hammasini tozalash (zaxira bilan)
    systemctl start scanner-bot

``--full`` dan oldin baza fayli avtomatik zaxiralanadi:
``scanner.db.bak-YYYYmmdd-HHMMSS``. Tiklash uchun shu faylni qaytaring.

Diqqat: ``--full`` kalit so'zlarni ham, foydalanuvchilarni ham,
sessiyalarni ham o'chiradi — hamma qaytadan login qiladi.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time

from config import BASE_DIR, DB_NAME

# Kod ishlatadigan jadvallar
LIVE_TABLES = (
    "phrases",
    "users",
    "user_groups",
    "user_counters",
    "settings",
)
# Eski modeldan qolgan, endi kodda ishlatilmaydigan jadvallar
LEGACY_TABLES = ("stop_words", "client_words", "groups")


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_NAME)


def _tables(conn) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def show_stats(conn) -> None:
    """Bazada nimalar borligini ko'rsatadi."""
    tables = _tables(conn)
    print(f"📁 Baza: {DB_NAME}")
    if not os.path.exists(DB_NAME):
        print("   (fayl hali yo'q)")
        return
    size = os.path.getsize(DB_NAME) / 1024
    print(f"📦 Hajmi: {size:.1f} KB\n")
    if not tables:
        print("   Jadvallar yo'q — baza bo'sh.")
        return
    for name in tables:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        except sqlite3.Error as exc:  # buzilgan jadval
            print(f"   {name:16} ⚠️ o'qilmadi: {exc}")
            continue
        tag = " (eski, keraksiz)" if name in LEGACY_TABLES else ""
        print(f"   {name:16} {count:>6} qator{tag}")


def backup() -> str | None:
    """Bazadan vaqt belgisi bilan nusxa oladi."""
    if not os.path.exists(DB_NAME):
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = f"{DB_NAME}.bak-{stamp}"
    shutil.copy2(DB_NAME, target)
    return target


def reset_full() -> None:
    """Hamma ma'lumotni o'chiradi: kalitlar, userlar, guruhlar, sessiyalar."""
    conn = _connect()
    try:
        tables = _tables(conn)
        with conn:
            for name in LIVE_TABLES:
                if name in tables:
                    conn.execute(f"DELETE FROM {name}")
            # Eski jadvallar butunlay olib tashlanadi
            for name in LEGACY_TABLES:
                if name in tables:
                    conn.execute(f"DROP TABLE IF EXISTS {name}")
        # Bo'shagan joyni diskda ham bo'shatamiz
        conn.execute("VACUUM")
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
    finally:
        conn.close()

    # Standart sozlamalar va yangi jadvallar
    import database

    database.init_db()
    # Markaziy "userbot" sessiyasi ishlatilmaydi — qolib ketgan faylni
    # o'chiramiz (u eski modeldan qolgan).
    for leftover in BASE_DIR.glob("*userbot*.session*"):
        try:
            leftover.unlink()
            print(f"🗑 Eski sessiya fayli o'chirildi: {leftover.name}")
        except OSError:
            pass
    print("✅ Baza tozalandi: kalit so'zlar, userlar, guruhlar, sessiyalar.")
    print("   Standart holat: tizim 🟢 yoniq, xabar sharti = 2, kalitlar = 0.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bot bazasini tozalash (eski ma'lumotlarni olib tashlash)."
    )
    parser.add_argument(
        "--stats", action="store_true", help="faqat holatni ko'rsatish"
    )
    parser.add_argument(
        "--full", action="store_true", help="hamma ma'lumotni o'chirish"
    )
    parser.add_argument(
        "--yes", action="store_true", help="tasdiq so'ramaslik (avtomatik)"
    )
    args = parser.parse_args()

    if not (args.stats or args.full):
        parser.print_help()
        return 0

    if not os.path.exists(DB_NAME):
        print(f"⚠️ Baza topilmadi: {DB_NAME}")
        print("   Bot hali ishga tushmagan bo'lishi mumkin.")
        return 1

    conn = _connect()
    try:
        show_stats(conn)
    finally:
        conn.close()

    if args.stats:
        return 0

    if not args.yes:
        print(
            "\n⚠️  DIQQAT: kalit so'zlar, foydalanuvchilar, guruhlar va "
            "sessiyalar butunlay o'chadi.\n"
            "    Hamma qaytadan login qilishi va guruh qo'shishi kerak bo'ladi."
        )
        answer = input("Davom etamizmi? (ha/yo'q): ").strip().lower()
        if answer not in {"ha", "h", "yes", "y", "да"}:
            print("Bekor qilindi. Hech narsa o'zgarmadi.")
            return 1

    saved = backup()
    if saved:
        print(f"\n💾 Zaxira nusxa: {saved}")
    else:
        print("\n⚠️ Zaxira olinmadi (baza fayli yo'q).")

    reset_full()
    print("\nEndi botni qayta ishga tushiring:")
    print("   systemctl start scanner-bot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
