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

# Telegram sozlamalari
# Joy (placeholder) — haqiqiy qiymatlarni shu yerga yoki environment'ga qo'ying
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "PUT_YOUR_TELEGRAM_BOT_TOKEN_HERE")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "PUT_YOUR_CHAT_ID_HERE")
