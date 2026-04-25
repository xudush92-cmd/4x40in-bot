import pandas as pd
import pandas_ta as ta
import yfinance as yf
import asyncio
from config import SYMBOL, POINT_SIZE, SL_OFFSET_POINTS, SL_LOOKBACK, RISK_REWARD

class TradingBrain:
    async def get_data(self, tf):
        df = yf.download(SYMBOL, period="100d", interval=tf, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df

    def calculate_score(self, df):
        if len(df) < 50:
            return 0, "↔️ WAIT", None, None, None
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

        entry = float(last['Close'])
        tp, sl = self._calc_tp_sl(df, direction, entry)

        return abs(score), direction, entry, tp, sl

    def _calc_tp_sl(self, df, direction, entry):
        if "BUY" not in direction and "SELL" not in direction:
            return None, None

        offset = SL_OFFSET_POINTS * POINT_SIZE
        recent = df.iloc[-SL_LOOKBACK:]

        if "BUY" in direction:
            sl = float(recent['Low'].min()) - offset
            risk = entry - sl
            if risk <= 0:
                return None, None
            tp = entry + RISK_REWARD * risk
        else:  # SELL
            sl = float(recent['High'].max()) + offset
            risk = sl - entry
            if risk <= 0:
                return None, None
            tp = entry - RISK_REWARD * risk

        return round(tp, 2), round(sl, 2)

    async def full_scan(self):
        tasks = [self.get_data(tf) for tf in ["1d", "4h", "1h", "30m"]]
        datasets = await asyncio.gather(*tasks)
        results = {}
        for i, tf in enumerate(["D1", "H4", "H1", "M30"]):
            conf, dir, entry, tp, sl = self.calculate_score(datasets[i])
            results[tf] = {
                "conf": conf,
                "dir": dir,
                "entry": entry,
                "tp": tp,
                "sl": sl,
            }
        return results
