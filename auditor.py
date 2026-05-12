"""Mustaqil Auditor moduli.

Vazifalar:
- Har bir yuborilgan signalni 4 timeframe (D1/H4/H1/M30) × 5 indikator (jami 20)
  kesimida tahlil qilib, statistics.json fayliga yozadi.
- Signaldan keyin narx TP/SL ga yetganligini kuzatadi.
- Kun, hafta va oy oxirida Telegramga batafsil hisobot tayyorlaydi.
- Faqat ma'lumot yig'adi va belgilangan vaqtda hisobot beradi — signallarni TO'XTATMAYDI.
"""

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TASHKENT = ZoneInfo("Asia/Tashkent")
STATS_PATH = "statistics.json"
SIGNAL_EXPIRY_HOURS = 24

INDICATOR_NAMES = ["ema_trend", "macd_cross", "macd_hist", "rsi_zone", "stoch_zone"]
INDICATOR_UZ = {
    "ema_trend":  "EMA trend (EMA20 vs EMA50)",
    "macd_cross": "MACD kesishmasi",
    "macd_hist":  "MACD Histogramma",
    "rsi_zone":   "RSI zonasi",
    "stoch_zone": "Stochastic zonasi",
}


def _classify_indicators(ind: dict) -> dict:
    """Indikator raw qiymatlaridan signal-do'st belgi yasaydi."""
    if not ind:
        return {k: "n/a" for k in INDICATOR_NAMES}

    ema20    = ind.get("EMA20", 0) or 0
    ema50    = ind.get("EMA50", 0) or 0
    macd     = ind.get("MACD", 0) or 0
    # FIX: brain.py "MACDsig" kalit nomini ishlatadi — ikkalasini ham tekshiramiz
    macd_sig = ind.get("MACDsig", ind.get("MACDs", 0)) or 0
    # FIX: brain.py "RSI14" kalit nomini ishlatadi (oldin "RSI14" bilan mos emas edi)
    rsi      = ind.get("RSI14", ind.get("RSI21", ind.get("RSI7", 50))) or 50
    stoch    = ind.get("STOCHk", 50) or 50

    return {
        "ema_trend":  "bull" if ema20 > ema50 else "bear",
        "macd_cross": "bull" if macd > macd_sig else "bear",
        "macd_hist":  "positive" if (macd - macd_sig) > 0 else "negative",
        "rsi_zone":   "oversold" if rsi < 40 else ("overbought" if rsi > 60 else "neutral"),
        "stoch_zone": "oversold" if stoch < 20 else ("overbought" if stoch > 80 else "neutral"),
    }


def _agrees_with(direction: str, value: str) -> str:
    """'agree' / 'disagree' / 'neutral' qaytaradi."""
    bull_set = {"bull", "positive", "oversold"}
    bear_set = {"bear", "negative", "overbought"}
    if value in ("neutral", "n/a", None):
        return "neutral"
    if direction == "BUY":
        return "agree" if value in bull_set else "disagree"
    if direction == "SELL":
        return "agree" if value in bear_set else "disagree"
    return "neutral"


class Auditor:
    def __init__(self, path: str = STATS_PATH):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    d.setdefault("signals", [])
                    d.setdefault("last_daily_report", None)
                    d.setdefault("last_weekly_report", None)
                    d.setdefault("last_monthly_report", None)
                    d.setdefault("next_id", max(
                        [s.get("id", 0) for s in d.get("signals", [])] + [0]
                    ) + 1)
                    return d
            except Exception as e:
                print(f"⚠️ statistics.json o'qish xatosi: {e}")
        return {
            "signals": [],
            "last_daily_report": None,
            "last_weekly_report": None,
            "last_monthly_report": None,
            "next_id": 1,
        }

    def _save(self) -> None:
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:
            print(f"⚠️ statistics.json saqlash xatosi: {e}")

    # ─── Yozish ──────────────────────────────────────────────────────
    def record_signal(self, tf: str, sig: dict, all_results: dict, sent_at: datetime) -> int:
        """Yuborilgan signalni 4 TF × 5 indikator snapshot bilan saqlaydi."""
        snapshot = {}
        for label, data in all_results.items():
            snapshot[label] = _classify_indicators(data.get("indicators") or {})

        record = {
            "id": self.data["next_id"],
            "sent_at": sent_at.strftime("%Y-%m-%d %H:%M"),
            "tf": tf,
            "direction": "BUY" if "BUY" in sig["dir"] else "SELL",
            "entry": sig["entry"],
            "tp": sig["tp"],
            "sl": sig["sl"],
            "confidence": sig["conf"],
            "indicators": snapshot,
            "outcome": "open",
            "closed_at": None,
            "exit_price": None,
        }
        self.data["signals"].append(record)
        self.data["next_id"] += 1
        self._save()
        return record["id"]

    # ─── Kuzatish (TP/SL ga yetdimi?) ─────────────────────────────────
    def update_open_signals(self, all_results: dict, now: datetime) -> list[dict]:
        """Joriy narxlarga qarab ochiq signallarning natijasini belgilaydi."""
        prices_by_tf = {
            tf: data.get("entry")
            for tf, data in all_results.items()
            if data.get("entry") is not None
        }
        if not prices_by_tf:
            return []

        closed = []
        expiry = timedelta(hours=SIGNAL_EXPIRY_HOURS)

        for rec in self.data["signals"]:
            if rec["outcome"] != "open":
                continue
            current = prices_by_tf.get(rec["tf"])
            if current is None:
                continue

            tp, sl, d = rec["tp"], rec["sl"], rec["direction"]
            outcome = None

            if tp is None or sl is None:
                pass  # TP/SL yo'q bo'lsa — faqat expiry tekshiramiz
            elif d == "BUY":
                if current >= tp:
                    outcome = "win"
                elif current <= sl:
                    outcome = "loss"
            else:  # SELL
                if current <= tp:
                    outcome = "win"
                elif current >= sl:
                    outcome = "loss"

            if outcome:
                rec["outcome"]    = outcome
                rec["exit_price"] = current
                rec["closed_at"]  = now.strftime("%Y-%m-%d %H:%M")
                closed.append(rec)
                continue

            # Muddati o'tgan signallarni yopish
            try:
                sent_at = datetime.strptime(
                    rec["sent_at"], "%Y-%m-%d %H:%M"
                ).replace(tzinfo=TASHKENT)
            except Exception:
                continue

            if now - sent_at >= expiry:
                rec["outcome"]    = "expired"
                rec["exit_price"] = current
                rec["closed_at"]  = now.strftime("%Y-%m-%d %H:%M")
                closed.append(rec)

        if closed:
            self._save()
        return closed

    # ─── Statistika ───────────────────────────────────────────────────
    def _records_in(self, since: datetime, until: datetime) -> list:
        out = []
        for r in self.data["signals"]:
            try:
                t = datetime.strptime(
                    r["sent_at"], "%Y-%m-%d %H:%M"
                ).replace(tzinfo=TASHKENT)
            except Exception:
                continue
            if since <= t < until:
                out.append(r)
        return out

    def _compute_stats(self, records: list) -> dict:
        total   = len(records)
        wins    = sum(1 for r in records if r["outcome"] == "win")
        losses  = sum(1 for r in records if r["outcome"] == "loss")
        opens   = sum(1 for r in records if r["outcome"] == "open")
        expired = sum(1 for r in records if r["outcome"] == "expired")
        closed  = wins + losses
        win_rate = (wins / closed * 100) if closed else 0.0

        tf_stats = {}
        for tf in ["D1", "H4", "H1", "M30"]:
            tf_recs = [
                r for r in records
                if r["tf"] == tf and r["outcome"] in ("win", "loss")
            ]
            if not tf_recs:
                tf_stats[tf] = None
                continue
            w = sum(1 for r in tf_recs if r["outcome"] == "win")
            tf_stats[tf] = {
                "total": len(tf_recs),
                "wins": w,
                "win_rate": round(w / len(tf_recs) * 100, 1)
            }

        ind_stats = {name: {"correct": 0, "wrong": 0} for name in INDICATOR_NAMES}
        for r in records:
            if r["outcome"] not in ("win", "loss"):
                continue
            for tf_label, vals in (r.get("indicators") or {}).items():
                for ind_name in INDICATOR_NAMES:
                    val = vals.get(ind_name)
                    agree = _agrees_with(r["direction"], val)
                    if agree == "agree":
                        if r["outcome"] == "win":
                            ind_stats[ind_name]["correct"] += 1
                        else:
                            ind_stats[ind_name]["wrong"] += 1

        return {
            "total": total, "wins": wins, "losses": losses,
            "open": opens, "expired": expired, "closed": closed,
            "win_rate": round(win_rate, 1),
            "tf_stats": tf_stats,
            "indicator_stats": ind_stats,
        }

    def _format_report(self, title: str, period_label: str, stats: dict) -> str:
        lines = [
            f"📊 {title}",
            f"📅 Davr: {period_label}",
            "━━━━━━━━━━━━━━━━━━",
            f"Jami yuborilgan signallar: {stats['total']}",
            f"   ✅ Yutuqli (TP): {stats['wins']}",
            f"   ❌ Yo'qotilgan (SL): {stats['losses']}",
            f"   ⏳ Hali ochiq: {stats['open']}",
            f"   ⌛ Muddati o'tgan: {stats['expired']}",
        ]

        if stats["closed"]:
            lines.append(
                f"\n🏆 Win Rate: {stats['win_rate']}%   ({stats['wins']}/{stats['closed']})"
            )
        else:
            lines.append("\n🏆 Win Rate: hali yetarli yopiq signal yo'q")

        valid_tfs = [(tf, s) for tf, s in stats["tf_stats"].items() if s]
        if valid_tfs:
            lines.append("")
            lines.append("⏱️ Timeframe natijalari:")
            for tf in ["D1", "H4", "H1", "M30"]:
                s = stats["tf_stats"].get(tf)
                if s:
                    lines.append(f"   {tf}: {s['wins']}/{s['total']}  →  {s['win_rate']}%")
                else:
                    lines.append(f"   {tf}: ma'lumot yetmaydi")
            best_tf, best_s = max(valid_tfs, key=lambda x: x[1]["win_rate"])
            lines.append(f"🥇 Eng ko'p foyda keltirgan TF: {best_tf} ({best_s['win_rate']}%)")

        ind_eval = []
        for name, c in stats["indicator_stats"].items():
            n = c["correct"] + c["wrong"]
            if n >= 3:
                ind_eval.append((name, n, c["correct"], c["wrong"], c["wrong"] / n * 100))

        if ind_eval:
            lines.append("")
            lines.append("🔬 Indikatorlar baholashi:")
            for name, n, ok, bad, wrate in ind_eval:
                lines.append(
                    f"   {INDICATOR_UZ[name]}: to'g'ri {ok}, adashgan {bad} ({wrate:.0f}% xato)"
                )
            worst = max(ind_eval, key=lambda x: x[4])
            lines.append(
                f"⚠️ Eng ko'p adashgan indikator: {INDICATOR_UZ[worst[0]]}  ({worst[4]:.0f}% xato)"
            )

        return "\n".join(lines)

    # ─── Hisobot jadvali ──────────────────────────────────────────────
    async def maybe_send_reports(self, send_func, now: datetime) -> None:
        """Kunlik (00:00 dan keyin), haftalik (Du), oylik (1-sana) hisobot yuboradi."""

        # KUNLIK — kechagi kun uchun
        yday = (now - timedelta(days=1)).date()
        if str(self.data.get("last_daily_report")) != str(yday):
            since = datetime.combine(yday, datetime.min.time(), tzinfo=TASHKENT)
            until = since + timedelta(days=1)
            recs = self._records_in(since, until)
            if recs:
                stats = self._compute_stats(recs)
                msg = self._format_report(
                    "KUNLIK HISOBOT",
                    yday.strftime("%Y-%m-%d") + " (Toshkent)",
                    stats,
                )
                await send_func(msg)
            self.data["last_daily_report"] = str(yday)
            self._save()

        # HAFTALIK — Dushanba kuni o'tgan hafta uchun
        if now.weekday() == 0:
            week_label = (now - timedelta(days=7)).strftime("%G-W%V")
            if self.data.get("last_weekly_report") != week_label:
                since = (
                    now.replace(hour=0, minute=0, second=0, microsecond=0)
                    - timedelta(days=7)
                )
                until = since + timedelta(days=7)
                recs = self._records_in(since, until)
                if recs:
                    stats = self._compute_stats(recs)
                    msg = self._format_report(
                        "HAFTALIK HISOBOT",
                        f"{since.strftime('%Y-%m-%d')} – {(until - timedelta(days=1)).strftime('%Y-%m-%d')}",
                        stats,
                    )
                    await send_func(msg)
                self.data["last_weekly_report"] = week_label
                self._save()

        # OYLIK — oyning 1-kunida o'tgan oy uchun
        if now.day == 1:
            prev_month_end = now.replace(day=1) - timedelta(days=1)
            month_label = prev_month_end.strftime("%Y-%m")
            if self.data.get("last_monthly_report") != month_label:
                since = prev_month_end.replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                )
                until = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                recs = self._records_in(since, until)
                if recs:
                    stats = self._compute_stats(recs)
                    msg = self._format_report(
                        "OYLIK HISOBOT",
                        month_label,
                        stats,
                    )
                    await send_func(msg)
                self.data["last_monthly_report"] = month_label
                self._save()
