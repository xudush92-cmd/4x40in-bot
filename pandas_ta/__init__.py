"""Local pandas_ta shim.

Provides the subset of indicators used by the project (ema, rsi, macd, stoch)
via the `ta` library, exposed through the `df.ta` accessor in the same style
as the upstream pandas_ta package.
"""

import pandas as pd
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator


def _as_series(x):
    if isinstance(x, pd.DataFrame):
        return x.iloc[:, 0]
    return x


@pd.api.extensions.register_dataframe_accessor("ta")
class _TAAccessor:
    def __init__(self, df: pd.DataFrame):
        self._df = df

    def _col(self, name):
        if name in self._df.columns:
            return _as_series(self._df[name])
        for cand in ("Close", "close", "Adj Close"):
            if cand in self._df.columns:
                return _as_series(self._df[cand])
        return _as_series(self._df.iloc[:, 0])

    def ema(self, length=20, append=False, **_):
        close = self._col("Close")
        out = EMAIndicator(close=close, window=length, fillna=False).ema_indicator()
        out.name = f"EMA_{length}"
        if append:
            self._df[out.name] = out
        return out

    def rsi(self, length=14, append=False, **_):
        close = self._col("Close")
        out = RSIIndicator(close=close, window=length, fillna=False).rsi()
        out.name = f"RSI_{length}"
        if append:
            self._df[out.name] = out
        return out

    def macd(self, fast=12, slow=26, signal=9, append=False, **_):
        close = self._col("Close")
        m = MACD(close=close, window_slow=slow, window_fast=fast,
                 window_sign=signal, fillna=False)
        macd_line = m.macd()
        macd_signal = m.macd_signal()
        macd_hist = m.macd_diff()
        suffix = f"{fast}_{slow}_{signal}"
        macd_line.name = f"MACD_{suffix}"
        macd_hist.name = f"MACDh_{suffix}"
        macd_signal.name = f"MACDs_{suffix}"
        out = pd.concat([macd_line, macd_hist, macd_signal], axis=1)
        if append:
            for c in out.columns:
                self._df[c] = out[c]
        return out

    def stoch(self, k=14, d=3, smooth_k=3, append=False, **_):
        high = self._col("High")
        low = self._col("Low")
        close = self._col("Close")
        s = StochasticOscillator(high=high, low=low, close=close,
                                 window=k, smooth_window=smooth_k, fillna=False)
        k_line = s.stoch()
        d_line = s.stoch_signal()
        suffix = f"{k}_{d}_{smooth_k}"
        k_line.name = f"STOCHk_{suffix}"
        d_line.name = f"STOCHd_{suffix}"
        out = pd.concat([k_line, d_line], axis=1)
        if append:
            for c in out.columns:
                self._df[c] = out[c]
        return out
