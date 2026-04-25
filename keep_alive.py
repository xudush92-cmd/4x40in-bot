"""Keep-alive web server.

Tashqi monitoring xizmatlari (UptimeRobot, Cron-job.org va boshqalar)
shu URL'ni har 5 daqiqada chaqirib, loyihani uxlashga qo'ymaydi.
"""

from threading import Thread
from datetime import datetime
from flask import Flask, jsonify

app = Flask(__name__)
_started_at = datetime.now()


@app.route("/")
def home():
    return "✅ 4x40IN bot tirik. Bozor kuzatilmoqda."


@app.route("/status")
def status():
    return jsonify({
        "status": "alive",
        "started_at": _started_at.strftime("%Y-%m-%d %H:%M:%S"),
        "uptime_seconds": int((datetime.now() - _started_at).total_seconds()),
    })


def _run():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


def keep_alive():
    """main.py'dan chaqirilganda, web serverni alohida thread'da yoqadi."""
    t = Thread(target=_run, daemon=True)
    t.start()
