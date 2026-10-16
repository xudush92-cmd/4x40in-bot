"""UX-2: eski sotuvchilarga tegmasdan faqat ariza jadvali qo'shiladi."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


def test_upgrade_keeps_legacy_sellers_and_partial_unique(tmp_path: Path) -> None:
    db_path = tmp_path / "ux2.sqlite3"
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "ALEMBIC_DB_URL": f"sqlite+aiosqlite:///{db_path}"}

    def alembic(*args: str) -> None:
        subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root, env=env,
                       capture_output=True, text=True, check=True, timeout=60)

    alembic("upgrade", "8d93a17e623c")
    with sqlite3.connect(db_path) as conn:
        now = "2026-10-15 10:30:00"
        conn.execute("INSERT INTO sellers(user_id,display_name,status,is_verified,balance,created_at,updated_at) "
                     "VALUES (9876001,'Eski sotuvchi','active',0,0,?,?)", (now, now))
        assert conn.execute("SELECT count(*) FROM sellers").fetchone() == (1,)
    alembic("upgrade", "head")
    alembic("check")
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT user_id,status FROM sellers").fetchall() == [(9876001, "active")]
        assert conn.execute("SELECT count(*) FROM seller_applications").fetchone() == (0,)
        now = "2026-10-16 11:00:00"
        sql = ("INSERT INTO seller_applications(user_id,display_name,contact_type,contact_value,status,"
               "created_at,updated_at) VALUES (9876002,'Yangi','username','@market_uz',?,?,?)")
        conn.execute(sql, ("pending", now, now))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql, ("pending", now, now))
        conn.execute("UPDATE seller_applications SET status='rejected' WHERE user_id=9876002")
        conn.execute(sql, ("pending", now, now))  # tarix + yangi ochiq ariza mumkin
        assert conn.execute("SELECT count(*) FROM seller_applications").fetchone() == (2,)
    alembic("downgrade", "8d93a17e623c")
    alembic("upgrade", "head")
    alembic("check")
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT user_id,status FROM sellers").fetchall() == [(9876001, "active")]
