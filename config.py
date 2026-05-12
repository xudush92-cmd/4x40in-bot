import os

# ═══════════════════════════════════════════
#  4x40IN — Tizim Sozlamalari
# ═══════════════════════════════════════════

SYMBOL = "GC=F"   # Oltin futures (Yahoo Finance)

# ── TP/SL ───────────────────────────────────
POINT_SIZE        = 0.10   # 1 punkt = $0.10
SL_OFFSET_POINTS  = 10     # SL dan qo'shimcha masofa
RISK_REWARD       = 2.0    # TP = 2 × Risk

# ── Signal nazorati ──────────────────────────
SIGNAL_COOLDOWN_MIN = 15   # bir TF uchun min oraliq (daqiqa)
PRICE_CHANGE_PCT    = 0.002 # qayta yuborish uchun min o'zgarish (0.2%)

# ── Hisobot ──────────────────────────────────
REPORT_DAY  = 4        # Juma
REPORT_TIME = "23:00"

# ── Telegram — FAQAT environment'dan o'qiladi ─
# Replit → Secrets bo'limiga qo'shing:
#   TELEGRAM_TOKEN = botning tokeni
#   TELEGRAM_CHAT_ID = chat id raqami
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("TELEGRAM_CHAT_ID", "")
