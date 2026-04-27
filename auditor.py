"""Auditor — signallarni SQLite ga yozadi va haftalik JSON hisobot tayyorlaydi."""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DB_PATH = "audit.db"
REPORTS_DIR = "reports"
TASHKENT = ZoneInfo("Asia/Tashkent")


class Auditor:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.db.cursor()
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                time TEXT NOT NULL,
                tf   TEXT NOT NULL,
                res  TEXT NOT NULL
            )
            """
        )
        self.db.commit()
        os.makedirs(REPORTS_DIR, exist_ok=True)

    def log_result(self, tf: str, res: str) -> None:
        now = datetime.now(TASHKENT).strftime("%Y-%m-%d %H:%M")
        try:
            self.cursor.execute(
                "INSERT INTO signals (time, tf, res) VALUES (?, ?, ?)",
                (now, tf, res),
            )
            self.db.commit()
        except sqlite3.Error as e:
            print(f"⚠️ Auditor yozish xatosi: {e}")

    def _classify(self, res: str) -> str:
        if "BUY" in res:
            return "BUY"
        if "SELL" in res:
            return "SELL"
        return "WAIT"

    def stats_since(self, since: datetime) -> dict:
        since_str = since.strftime("%Y-%m-%d %H:%M")
        self.cursor.execute(
            "SELECT time, tf, res FROM signals WHERE time >= ? ORDER BY time",
            (since_str,),
        )
        rows = self.cursor.fetchall()
        per_tf: dict = {}
        totals = {"BUY": 0, "SELL": 0, "WAIT": 0}
        for time_str, tf, res in rows:
            cat = self._classify(res)
            totals[cat] += 1
            tf_bucket = per_tf.setdefault(tf, {"BUY": 0, "SELL": 0, "WAIT": 0})
            tf_bucket[cat] += 1
        return {
            "rows": len(rows),
            "totals": totals,
            "per_timeframe": per_tf,
        }

    def get_today_stats(self) -> dict:
        now = datetime.now(TASHKENT)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return self.stats_since(start)

    def export_weekly_report(self) -> str:
        """Oxirgi 7 kun signallarini JSON faylga saqlaydi va yo'lini qaytaradi."""
        now = datetime.now(TASHKENT)
        week_ago = now - timedelta(days=7)
        stats = self.stats_since(week_ago)

        # batafsil yozuvlar
        since_str = week_ago.strftime("%Y-%m-%d %H:%M")
        self.cursor.execute(
            "SELECT time, tf, res FROM signals WHERE time >= ? ORDER BY time",
            (since_str,),
        )
        rows = [
            {"time": t, "timeframe": tf, "result": r}
            for (t, tf, r) in self.cursor.fetchall()
        ]

        report = {
            "generated_at": now.strftime("%Y-%m-%d %H:%M") + " (Toshkent)",
            "period_from": week_ago.strftime("%Y-%m-%d %H:%M"),
            "period_to":   now.strftime("%Y-%m-%d %H:%M"),
            "summary": {
                "total_records": stats["rows"],
                "totals": stats["totals"],
                "per_timeframe": stats["per_timeframe"],
            },
            "records": rows,
        }
        filename = f"weekly_report_{now.strftime('%Y%m%d_%H%M')}.json"
        path = os.path.join(REPORTS_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return path

    def close(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass
