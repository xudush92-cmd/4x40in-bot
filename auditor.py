import sqlite3
import json
import os
from datetime import datetime, timedelta

class Auditor:
    def __init__(self):
        self.db = sqlite3.connect('audit.db')
        self.cursor = self.db.cursor()
        self.cursor.execute('CREATE TABLE IF NOT EXISTS signals (time TEXT, tf TEXT, res TEXT)')
        self.db.commit()

    def log_result(self, tf, res):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.cursor.execute("INSERT INTO signals VALUES (?,?,?)", (now, tf, res))
        self.db.commit()

    def export_weekly_report(self, reports_dir="reports"):
        os.makedirs(reports_dir, exist_ok=True)
        now = datetime.now()
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")

        self.cursor.execute(
            "SELECT time, tf, res FROM signals WHERE time >= ? ORDER BY time ASC",
            (week_ago,),
        )
        rows = self.cursor.fetchall()

        signals = [{"time": t, "tf": tf, "result": res} for (t, tf, res) in rows]

        summary = {}
        for s in signals:
            key = s["tf"]
            bucket = summary.setdefault(key, {"BUY": 0, "SELL": 0, "WAIT": 0, "total": 0})
            bucket["total"] += 1
            if "BUY" in s["result"]:
                bucket["BUY"] += 1
            elif "SELL" in s["result"]:
                bucket["SELL"] += 1
            else:
                bucket["WAIT"] += 1

        report = {
            "generated_at": now.strftime("%Y-%m-%d %H:%M"),
            "period_start": week_ago,
            "period_end": now.strftime("%Y-%m-%d %H:%M"),
            "total_signals": len(signals),
            "summary_by_timeframe": summary,
            "signals": signals,
        }

        filename = f"report_{now.strftime('%Y-%m-%d_%H-%M')}.json"
        path = os.path.join(reports_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return path
        