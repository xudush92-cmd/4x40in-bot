"""Phase 8: eski cheklar va userlar bilan Alembic round-trip regressiyasi."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_old_users_cannot_earn_retroactive_bonus_and_old_payments_keep_price(tmp_path: Path) -> None:
    database = tmp_path / "old.sqlite3"
    env = {**os.environ, "ALEMBIC_DB_URL": f"sqlite+aiosqlite:///{database}"}
    root = Path(__file__).resolve().parents[1]

    def alembic(*args: str) -> None:
        subprocess.run([sys.executable, "-m", "alembic", *args],
                       cwd=root, env=env, capture_output=True, text=True,
                       check=True, timeout=45)

    alembic("upgrade", "4f30ae7c912b")
    with sqlite3.connect(database) as conn:
        now = "2026-10-14 12:00:00"
        conn.execute("INSERT INTO users(user_id,language,is_blocked,created_at,updated_at) "
                     "VALUES (7001,'uz',0,?,?)", (now, now))
        conn.execute("INSERT INTO sellers(user_id,status,is_verified,balance,created_at,updated_at) "
                     "VALUES (7001,'active',0,0,?,?)", (now, now))
        conn.execute("INSERT INTO tariffs(name,price,currency,duration_days,max_ads,max_photos,"
                     "is_active,position,is_trial,created_at,updated_at) "
                     "VALUES ('Old',150000,'UZS',30,5,3,1,1,0,?,?)", (now, now))
        conn.execute("INSERT INTO payments(seller_id,tariff_id,amount,currency,is_duplicate_receipt,"
                     "status,created_at,updated_at) "
                     "VALUES (1,1,150000,'UZS',0,'approved',?,?)", (now, now))

    alembic("upgrade", "head")
    alembic("check")
    with sqlite3.connect(database) as conn:
        old = conn.execute("SELECT private_started_at,referral_legacy,broadcast_opt_out "
                           "FROM users WHERE user_id=7001").fetchone()
        assert old == (None, 1, 0)
        assert conn.execute("SELECT amount,base_amount,discount_amount,balance_used "
                            "FROM payments").fetchone() == (150000, 150000, 0, 0)
        conn.execute("INSERT INTO users(user_id,language,is_blocked,created_at,updated_at) "
                     "VALUES (7002,'uz',0,?,?)", (now, now))
        assert conn.execute("SELECT referral_legacy FROM users WHERE user_id=7002").fetchone() == (0,)

    alembic("downgrade", "4f30ae7c912b")
    alembic("upgrade", "head")
    alembic("check")
