"""
Shared price-history fetching. Every other module (candidate engine,
backtester) goes through here so there's one place that talks to Yahoo
Finance and one place to fix things if the data source changes.
"""

import time

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None


def to_yf_symbol(sym: str) -> str:
    sym = sym.strip().upper()
    if sym.startswith("^"):          # index ticker such as ^NSEI: no exchange suffix
        return sym
    if not sym.endswith(".NS") and not sym.endswith(".BO"):
        sym += ".NS"
    return sym


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Indicator columns every strategy, filter and the backtester rely on.
    All are trailing windows including the current bar, so no lookahead."""
    df = df.copy()
    df["ema20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["vol_avg20"] = df["Volume"].rolling(20).mean()
    df["high_20"] = df["High"].rolling(20).max()
    df["low_20"] = df["Low"].rolling(20).min()
    df["sma200"] = df["Close"].rolling(200).mean()
    df["high_252"] = df["High"].rolling(252, min_periods=200).max()   # ~52-week high
    df["avg_value20"] = (df["Close"] * df["Volume"]).rolling(20).mean()  # avg daily traded value, Rs
    df["traded_value20"] = df["avg_value20"]                          # name used by filters.py
    return df


def fetch_history(symbol: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """
    Returns a DataFrame with Open/High/Low/Close/Volume, indexed by date,
    plus ema20/ema50/vol_avg20 columns pre-computed since every strategy
    and the backtester need them.
    """
    if yf is None:
        raise ImportError("yfinance not installed. Run: pip install -r requirements.txt")

    yf_symbol = to_yf_symbol(symbol)
    df = None
    for attempt in (1, 2):                       # one retry: Yahoo sometimes answers empty on a first request
        df = yf.Ticker(yf_symbol).history(period=period, interval=interval, auto_adjust=True)
        if df is not None and not df.empty:
            break
        if attempt == 1:
            time.sleep(1.0)
    if df is None or df.empty:
        raise ValueError(f"no price data returned for {yf_symbol}")

    return add_indicators(df)


# Market-cap bands from the shortlisting doc (Rs crore)
LARGE_CAP_MIN_CR = 20000
MID_CAP_MIN_CR = 5000


def classify_market_cap(cap_cr):
    if cap_cr is None or cap_cr <= 0:
        return "Unknown"
    if cap_cr > LARGE_CAP_MIN_CR:
        return "Large"
    if cap_cr >= MID_CAP_MIN_CR:
        return "Mid"
    return "Small"


def fetch_market_cap_cr(symbol: str):
    """
    Current market cap in Rs crore from Yahoo, or None if unavailable.
    This is a live snapshot only -- NOT point-in-time -- so it is used for
    screening/labelling, never inside the backtester.
    """
    if yf is None:
        return None
    try:
        cap = yf.Ticker(to_yf_symbol(symbol)).fast_info["market_cap"]
        return round(float(cap) / 1e7, 1) if cap else None   # 1 crore = 1e7
    except Exception:
        return None
