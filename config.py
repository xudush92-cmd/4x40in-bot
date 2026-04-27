import os

# 4x40IN Sozlamalari
SYMBOL = "GC=F"  # Oltin (XAUUSD)
TIMEFRAMES = ["1d", "4h", "1h", "30m"]
REPORT_DAY = 4     # Juma (0-Dushanba, 4-Juma)
REPORT_TIME = "23:00"
WAKEUP_TIME = "02:55"

# TP/SL sozlamalari
POINT_SIZE = 0.10           # 1 punkt = $0.10 (oltin uchun)
SL_OFFSET_POINTS = 10       # SL oxirgi 3 shamning Low/High'idan masofada
SL_LOOKBACK = 3             # nechta sham orqaga qarash
RISK_REWARD = 2.0           # TP = 2 * Risk

# Signal yuborish nazorati (spam'ning oldini olish)
SIGNAL_COOLDOWN_MIN = 15    # bir TF uchun signal oralig'i (daqiqa)
PRICE_CHANGE_PCT = 0.002    # cooldown'dan keyin qayta yuborish uchun min narx o'zgarishi (0.2%)

# Telegram sozlamalari (environment'dan ham o'qiladi — xavfsizroq)
TELEGRAM_TOKEN = os.environ.get(
    "TELEGRAM_TOKEN",
    "8660573802:AAH5cDX3uvFZVmr-b9WNQBX3FXCOMUNBO6k",
)
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "991460501")
