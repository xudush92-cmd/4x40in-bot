import pandas as pd
import pandas_ta as ta
import yfinance as yf
import asyncio
from config import SYMBOL, POINT_SIZE, SL_OFFSET_POINTS, SL_LOOKBACK, RISK_REWARD


TF_CONFIG = {
    "D1":  {"interval": "1d",  "period": "200d"},
    "H4":  {"interval": "1h",  "period": "60d", "resample": "4h"},
    "H1":  {"interval": "1h",  "period": "60d"},
    "M30": {"interval": "30m", "period": "60d"},
}


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.loc[:, ~df.columns.duplicated()]
    return df


class TradingBrain:
    async def get_data(self, tf_label: str) -> pd.DataFrame:
        cfg = TF_CONFIG[tf_label]
        df = await asyncio.to_thread(
            yf.download,
            SYMBOL,
            period=cfg["period"],
            interval=cfg["interval"],
            progress=False,
            auto_adjust=False,
        )
        df = _flatten(df)
        if df is None or df.empty:
            return df
        if "resample" in cfg:
            df = df.resample(cfg["resample"]).agg({
                "Open":  "first",
                "High":  "max",
                "Low":   "min",
                "Close": "last",
                "Volume": "sum",
            }).dropna()
        return df

    def calculate(self, df: pd.DataFrame) -> dict:
        empty = {"conf": 0, "dir": "↔️ WAIT", "entry": None,
                 "tp": None, "sl": None, "indicators": {}}
        if df is None or df.empty or len(df) < 60:
            return empty

        df = df.copy()
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.macd(append=True)
        df.ta.stoch(append=True)

        last = df.iloc[-1]
        try:
            ema20    = float(last["EMA_20"])
            ema50    = float(last["EMA_50"])
            rsi      = float(last["RSI_14"])
            macd_l   = float(last["MACD_12_26_9"])
            macd_s   = float(last["MACDs_12_26_9"])
            stoch_k  = float(last["STOCHk_14_3_3"])
            close    = float(last["Close"])
        except (KeyError, ValueError, TypeError):
            return empty

        score = 0
        score += 25 if ema20 > ema50 else -25       # Trend
        score += 25 if macd_l > macd_s else -25     # MACD
        if rsi < 40:   score += 25                  # RSI oversold → BUY
        elif rsi > 60: score -= 25                  # RSI overbought → SELL
        if stoch_k < 20:  score += 25
        elif stoch_k > 80: score -= 25

        if score >= 50:    direction = "⬆️ BUY"
        elif score <= -50: direction = "⬇️ SELL"
        else:              direction = "↔️ WAIT"

        entry, tp, sl = close, None, None
        if "BUY" in direction:
            recent_low = float(df["Low"].iloc[-SL_LOOKBACK:].min())
            sl = recent_low - SL_OFFSET_POINTS * POINT_SIZE
            tp = entry + (entry - sl) * RISK_REWARD
        elif "SELL" in direction:
            recent_high = float(df["High"].iloc[-SL_LOOKBACK:].max())
            sl = recent_high + SL_OFFSET_POINTS * POINT_SIZE
            tp = entry - (sl - entry) * RISK_REWARD

        return {
            "conf": abs(score),
            "dir": direction,
            "entry": round(entry, 2),
            "tp": round(tp, 2) if tp is not None else None,
            "sl": round(sl, 2) if sl is not None else None,
            "indicators": {
                "EMA20":   round(ema20, 2),
                "EMA50":   round(ema50, 2),
                "RSI14":   round(rsi, 2),
                "MACD":    round(macd_l, 4),
                "MACDsig": round(macd_s, 4),
                "STOCHk":  round(stoch_k, 2),
            },
        }

    async def full_scan(self) -> dict:
        labels = ["D1", "H4", "H1", "M30"]
        datasets = await asyncio.gather(
            *(self.get_data(t) for t in labels),
            return_exceptions=True,
        )
        results = {}
        for label, d in zip(labels, datasets):
            if isinstance(d, Exception):
                print(f"⚠️ {label} ma'lumot xatosi: {d}")
                results[label] = {"conf": 0, "dir": "↔️ WAIT",
                                  "entry": None, "tp": None, "sl": None,
                                  "indicators": {}}
            else:
                results[label] = self.calculate(d)
        return results
