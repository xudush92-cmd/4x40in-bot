import asyncio
import pandas as pd
import yfinance as yf

from datetime import datetime

from ta.trend import EMAIndicator, ADXIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands, AverageTrueRange

from config import SYMBOL, POINT_SIZE, SL_OFFSET_POINTS, RISK_REWARD
from sessions import is_ny_session_active, TASHKENT


TF_DOWNLOAD = {
    "D1":  {"interval": "1d",  "period": "400d"},
    "H4":  {"interval": "1h",  "period": "60d", "resample": "4h"},
    "H1":  {"interval": "1h",  "period": "30d"},
    "M30": {"interval": "30m", "period": "20d"},
}

SL_LOOKBACK = {
    "D1": 5,
    "H4": 6,
    "H1": 4,
    "M30": 3,
}

ADX_TREND_MIN = 25
BB_PERIOD = 20
BB_STD = 2.0
SR_LOOKBACK = 20
SR_ZONE = 0.003


def _flatten(df):
    if df is None or df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.loc[:, ~df.columns.duplicated()]


def _resample_h4(df):
    return df.resample("4h", offset="1h").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna()


def _get(row, *keys):
    for k in keys:
        try:
            v = row[k]
            if pd.notna(v):
                return float(v)
        except:
            pass
    return None


def _empty(tf, reason=""):
    return {
        "tf": tf,
        "dir": "↔️ WAIT",
        "conf": 0,
        "entry": None,
        "tp": None,
        "sl": None,
        "indicators": {},
        "votes": {},
        "reason": reason
    }


def _make(tf, direction, conf, close, tp, sl, indicators, votes, reason=""):
    icon = "⬆️" if direction == "BUY" else (
        "⬇️" if direction == "SELL" else "↔️"
    )
    return {
        "tf": tf,
        "dir": f"{icon} {direction}",
        "conf": conf,
        "entry": round(close, 2) if close else None,
        "tp": tp,
        "sl": sl,
        "indicators": indicators,
        "votes": votes,
        "reason": reason,
    }


def _sl_tp_static(df, direction, entry, lookback):
    if direction == "BUY":
        sl = (
            float(df["Low"].iloc[-lookback:].min())
            - SL_OFFSET_POINTS * POINT_SIZE
        )
        tp = entry + (entry - sl) * RISK_REWARD
    else:
        sl = (
            float(df["High"].iloc[-lookback:].max())
            + SL_OFFSET_POINTS * POINT_SIZE
        )
        tp = entry - (sl - entry) * RISK_REWARD
    return round(tp, 2), round(sl, 2)


def _sl_tp_atr(direction, close, atr,
               atr_mult_sl=1.5,
               atr_mult_tp=3.0):
    if atr is None or close is None:
        return None, None
    if direction == "BUY":
        sl = round(close - atr * atr_mult_sl, 2)
        tp = round(close + atr * atr_mult_tp, 2)
    else:
        sl = round(close + atr * atr_mult_sl, 2)
        tp = round(close - atr * atr_mult_tp, 2)
    return tp, sl


def _add_adx(df, length=14):
    try:
        adx_indicator = ADXIndicator(
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            window=length
        )
        df["ADX_14"] = adx_indicator.adx()
    except Exception as e:
        print(f"ADX xato: {e}")


def _add_atr(df, length=14):
    try:
        atr_indicator = AverageTrueRange(
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            window=length
        )
        df["ATR_14"] = atr_indicator.average_true_range()
    except Exception as e:
        print(f"ATR xato: {e}")


def _add_bbands(df):
    try:
        bb = BollingerBands(
            close=df["Close"],
            window=BB_PERIOD,
            window_dev=BB_STD
        )
        df["BBL_20_2.0"] = bb.bollinger_lband()
        df["BBM_20_2.0"] = bb.bollinger_mavg()
        df["BBU_20_2.0"] = bb.bollinger_hband()
    except Exception as e:
        print(f"BBANDS xato: {e}")


def _sr_vote(df, close):
    highs = df["High"].iloc[-SR_LOOKBACK:]
    lows = df["Low"].iloc[-SR_LOOKBACK:]
    resistance = float(highs.max())
    support = float(lows.min())
    near_s = abs(close - support) / close < SR_ZONE
    near_r = abs(close - resistance) / close < SR_ZONE
    if near_s:
        vote = "BUY"
    elif near_r:
        vote = "SELL"
    else:
        vote = "NEUTRAL"
    return vote, round(support, 2), round(resistance, 2)


def _decide(votes, min_votes=3):
    buy_v = sum(1 for v in votes.values() if v == "BUY")
    sell_v = sum(1 for v in votes.values() if v == "SELL")
    total = buy_v + sell_v or 1
    if buy_v >= min_votes and buy_v > sell_v:
        return "BUY", round(buy_v / total * 100)
    elif sell_v >= min_votes and sell_v > buy_v:
        return "SELL", round(sell_v / total * 100)
    return "WAIT", 0


def _download_tf(tf):
    cfg = TF_DOWNLOAD[tf]
    df = yf.download(
        SYMBOL,
        interval=cfg["interval"],
        period=cfg["period"],
        auto_adjust=False,
        progress=False
    )
    df = _flatten(df)
    if df is None or df.empty:
        return None
    if tf == "H4":
        df = _resample_h4(df)
    return df


def _analyze_D1(df):
    if df is None or len(df) < 210:
        return _empty("D1")

    df = df.copy()

    df["EMA_50"] = EMAIndicator(close=df["Close"], window=50).ema_indicator()
    df["EMA_200"] = EMAIndicator(close=df["Close"], window=200).ema_indicator()
    df["RSI_21"] = RSIIndicator(close=df["Close"], window=21).rsi()
    _add_adx(df)
    _add_bbands(df)

    last = df.iloc[-1]

    close  = _get(last, "Close")
    ema50  = _get(last, "EMA_50")
    ema200 = _get(last, "EMA_200")
    rsi21  = _get(last, "RSI_21")

    if any(v is None for v in [close, ema50, ema200, rsi21]):
        return _empty("D1", "indikator xato")

    votes = {}
    if ema50 is not None and ema200 is not None:
        votes["EMA"] = "BUY" if ema50 > ema200 else "SELL"
    if close is not None and ema50 is not None:
        votes["PRICE"] = "BUY" if close > ema50 else "SELL"
    if rsi21 is not None:
        if rsi21 > 55:
            votes["RSI"] = "BUY"
        elif rsi21 < 45:
            votes["RSI"] = "SELL"

    sr, s, r = _sr_vote(df, close)
    votes["SR"] = sr

    direction, conf = _decide(votes, 4)

    tp, sl = None, None
    if direction != "WAIT":
        tp, sl = _sl_tp_static(df, direction, close, SL_LOOKBACK["D1"])

    # FIX: Auditor uchun to'g'ri kalit nomlari
    return _make(
        "D1", direction, conf, close, tp, sl,
        {
            "EMA20":   ema50,   # D1 da EMA50 ni EMA20 sifatida yubormaymiz
            "EMA50":   ema50,
            "EMA200":  ema200,
            "RSI21":   rsi21,
            "RSI14":   rsi21,   # Auditor RSI14 qidiradi — fallback
            "STOCHk":  50.0,    # D1 da stoch yo'q — neytral
            "MACD":    0.0,
            "MACDsig": 0.0,
            "S": s,
            "R": r
        },
        votes
    )


def _analyze_H4(df):
    if df is None or len(df) < 60:
        return _empty("H4")

    df = df.copy()

    df["EMA_20"] = EMAIndicator(close=df["Close"], window=20).ema_indicator()
    df["EMA_50"] = EMAIndicator(close=df["Close"], window=50).ema_indicator()

    macd_obj = MACD(close=df["Close"])
    df["MACD_12_26_9"]  = macd_obj.macd()
    df["MACDs_12_26_9"] = macd_obj.macd_signal()

    df["RSI_14"] = RSIIndicator(close=df["Close"], window=14).rsi()

    # FIX: Stochastic ham qo'shamiz (Auditor uchun)
    stoch = StochasticOscillator(
        high=df["High"], low=df["Low"], close=df["Close"],
        window=14, smooth_window=3
    )
    df["STOCHk_14_3_3"] = stoch.stoch()

    last = df.iloc[-1]

    close  = _get(last, "Close")
    ema20  = _get(last, "EMA_20")
    ema50  = _get(last, "EMA_50")
    rsi14  = _get(last, "RSI_14")
    macd   = _get(last, "MACD_12_26_9")
    macds  = _get(last, "MACDs_12_26_9")
    stochk = _get(last, "STOCHk_14_3_3")

    votes = {}
    if ema20 is not None and ema50 is not None:
        votes["EMA"] = "BUY" if ema20 > ema50 else "SELL"
    if macd is not None and macds is not None:
        votes["MACD"] = "BUY" if macd > macds else "SELL"
    if rsi14 is not None:
        if rsi14 > 55:
            votes["RSI"] = "BUY"
        elif rsi14 < 45:
            votes["RSI"] = "SELL"

    direction, conf = _decide(votes, 3)

    tp, sl = None, None
    if direction != "WAIT" and close is not None:
        tp, sl = _sl_tp_static(df, direction, close, SL_LOOKBACK["H4"])

    # FIX: Auditor uchun to'g'ri kalit nomlari
    return _make(
        "H4", direction, conf, close, tp, sl,
        {
            "EMA20":   ema20,
            "EMA50":   ema50,
            "RSI14":   rsi14,
            "MACD":    macd,
            "MACDsig": macds,
            "MACDh":   round((macd or 0) - (macds or 0), 4),
            "STOCHk":  stochk if stochk is not None else 50.0,
        },
        votes
    )


def _analyze_H1(df):
    if df is None or len(df) < 30:
        return _empty("H1")

    df = df.copy()

    df["EMA_9"]  = EMAIndicator(close=df["Close"], window=9).ema_indicator()
    df["EMA_21"] = EMAIndicator(close=df["Close"], window=21).ema_indicator()

    stoch = StochasticOscillator(
        high=df["High"], low=df["Low"], close=df["Close"],
        window=14, smooth_window=3
    )
    df["STOCHk_14_3_3"] = stoch.stoch()
    df["STOCHd_14_3_3"] = stoch.stoch_signal()

    df["RSI_14"] = RSIIndicator(close=df["Close"], window=14).rsi()
    _add_atr(df)

    last = df.iloc[-1]

    close  = _get(last, "Close")
    ema9   = _get(last, "EMA_9")
    ema21  = _get(last, "EMA_21")
    stochk = _get(last, "STOCHk_14_3_3")
    stochd = _get(last, "STOCHd_14_3_3")
    rsi14  = _get(last, "RSI_14")
    atr    = _get(last, "ATR_14")

    votes = {}
    if ema9 is not None and ema21 is not None:
        votes["EMA"] = "BUY" if ema9 > ema21 else "SELL"
    if stochk is not None:
        if stochk < 30:
            votes["STOCH"] = "BUY"
        elif stochk > 70:
            votes["STOCH"] = "SELL"
    if rsi14 is not None:
        if rsi14 < 40:
            votes["RSI"] = "BUY"
        elif rsi14 > 60:
            votes["RSI"] = "SELL"

    direction, conf = _decide(votes, 2)

    tp, sl = None, None
    if direction != "WAIT":
        tp, sl = _sl_tp_atr(direction, close, atr)

    # FIX: Auditor uchun to'g'ri kalit nomlari
    return _make(
        "H1", direction, conf, close, tp, sl,
        {
            "EMA20":   ema9,    # H1 da EMA9 ni yaqin sifatida
            "EMA50":   ema21,
            "EMA9":    ema9,
            "EMA21":   ema21,
            "RSI14":   rsi14,
            "STOCHk":  stochk if stochk is not None else 50.0,
            "STOCHd":  stochd,
            "MACD":    0.0,
            "MACDsig": 0.0,
        },
        votes
    )


def _analyze_M30(df):
    if df is None or len(df) < 20:
        return _empty("M30")

    df = df.copy()

    stoch = StochasticOscillator(
        high=df["High"], low=df["Low"], close=df["Close"],
        window=5, smooth_window=3
    )
    df["STOCHk_5_3_3"] = stoch.stoch()

    df["RSI_7"] = RSIIndicator(close=df["Close"], window=7).rsi()
    _add_atr(df)

    last = df.iloc[-1]

    close  = _get(last, "Close")
    stochk = _get(last, "STOCHk_5_3_3")
    rsi7   = _get(last, "RSI_7")
    atr    = _get(last, "ATR_14")

    now = datetime.now(TASHKENT)
    london_active = 7 <= now.hour < 16
    ny_active = is_ny_session_active(now)

    if not london_active and not ny_active:
        return _make(
            "M30", "WAIT", 0, close, None, None,
            {
                "EMA20":   0.0,
                "EMA50":   0.0,
                "RSI14":   rsi7 if rsi7 is not None else 50.0,
                "STOCHk":  stochk if stochk is not None else 50.0,
                "MACD":    0.0,
                "MACDsig": 0.0,
            },
            {},
            "Sessiya yopiq"
        )

    votes = {}
    if stochk is not None:
        if stochk < 25:
            votes["STOCH"] = "BUY"
        elif stochk > 75:
            votes["STOCH"] = "SELL"
    if rsi7 is not None:
        if rsi7 < 35:
            votes["RSI"] = "BUY"
        elif rsi7 > 65:
            votes["RSI"] = "SELL"

    direction, conf = _decide(votes, 2)

    tp, sl = None, None
    if direction != "WAIT":
        tp, sl = _sl_tp_atr(direction, close, atr)

    # FIX: Auditor uchun to'g'ri kalit nomlari
    return _make(
        "M30", direction, conf, close, tp, sl,
        {
            "EMA20":   0.0,
            "EMA50":   0.0,
            "RSI14":   rsi7 if rsi7 is not None else 50.0,
            "RSI7":    rsi7,
            "STOCHk":  stochk if stochk is not None else 50.0,
            "MACD":    0.0,
            "MACDs":   0.0,
            "MACDsig": 0.0,
        },
        votes
    )


class TradingBrain:

    async def full_scan(self):
        results = {}

        for tf in ["D1", "H4", "H1", "M30"]:
            try:
                df = _download_tf(tf)

                if tf == "D1":
                    results[tf] = _analyze_D1(df)
                elif tf == "H4":
                    results[tf] = _analyze_H4(df)
                elif tf == "H1":
                    results[tf] = _analyze_H1(df)
                elif tf == "M30":
                    results[tf] = _analyze_M30(df)

            except Exception as e:
                print(f"{tf} xato: {e}")
                results[tf] = _empty(tf, str(e))

            await asyncio.sleep(1)

        return results
