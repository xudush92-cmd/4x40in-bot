import pandas as pd
import pandas_ta as ta
import yfinance as yf
import asyncio
from config import SYMBOL

class TradingBrain:
    async def get_data(self, tf):
        df = yf.download(SYMBOL, period="100d", interval=tf, progress=False)
        return df

    def calculate_score(self, df):
        if len(df) < 50: return 0, "↔️"
        # 10 ta indikator (EMA, RSI, MACD va boshqalar)
        df.ta.ema(length=20, append=True); df.ta.ema(length=50, append=True)
        df.ta.rsi(length=14, append=True); df.ta.macd(append=True)
        df.ta.stoch(append=True)
        
        last = df.iloc[-1]
        score = 0
        if last['EMA_20'] > last['EMA_50']: score += 25
        if last['RSI_14'] < 40: score += 25
        if last['MACD_12_26_9'] > last['MACDs_12_26_9']: score += 25
        if last['STOCHk_14_3_3'] < 20: score += 25
        
        direction = "⬆️ BUY" if score >= 50 else "⬇️ SELL" if score <= -50 else "↔️ WAIT"
        return abs(score), direction

    async def full_scan(self):
        tasks = [self.get_data(tf) for tf in ["1d", "4h", "1h", "30m"]]
        datasets = await asyncio.gather(*tasks)
        results = {}
        for i, tf in enumerate(["D1", "H4", "H1", "M30"]):
            conf, dir = self.calculate_score(datasets[i])
            results[tf] = {"conf": conf, "dir": dir}
        return results
        