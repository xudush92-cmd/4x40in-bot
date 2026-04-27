"""Keep-alive web server.

Tashqi monitoring xizmatlari (UptimeRobot, Cron-job.org va boshqalar)
shu URL'ni har 5 daqiqada chaqirib, loyihani uxlashga qo'ymaydi.
"""

from threading import Thread
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask

app = Flask(__name__)
TASHKENT = ZoneInfo("Asia/Tashkent")
_started_at = datetime.now(TASHKENT)


def _format_uptime(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} soat {m} daqiqa"
    if m:
        return f"{m} daqiqa {s} soniya"
    return f"{s} soniya"


@app.route("/")
def home():
    return "✅ 4x40IN bot tirik. Bozor kuzatilmoqda."


@app.route("/status")
def status():
    now = datetime.now(TASHKENT)
    uptime = int((now - _started_at).total_seconds())
    return (
        "✅ 4x40IN bot HOLATI: TIRIK\n"
        f"🕒 Hozir (Toshkent): {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"🚀 Ishga tushgan: {_started_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"⏳ Ish vaqti: {_format_uptime(uptime)}\n",
        200,
        {"Content-Type": "text/plain; charset=utf-8"},
    )


def _run():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


def keep_alive():
    """main.py'dan chaqirilganda, web serverni alohida thread'da yoqadi."""
    t = Thread(target=_run, daemon=True)
    t.start()
