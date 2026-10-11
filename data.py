"""
Shared price-history fetching. Every other module (candidate engine,
backtester) goes through here so there's one place that talks to Yahoo
Finance and one place to fix things if the data source changes.
"""

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None


def to_yf_symbol(sym: str) -> str:
    sym = sym.strip().upper()
    if sym.startswith("^"):          # index symbols such as ^NSEI are used as-is
        return sym
    if not sym.endswith(".NS") and not sym.endswith(".BO"):
        sym += ".NS"
    return sym


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds the indicator columns every strategy / filter relies on:
    ema20, ema50, vol_avg20, high_20, low_20, atr14 (Wilder), and
    traded_value20 (20-day average of Close x Volume, in rupees).
    """
    df["ema20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["vol_avg20"] = df["Volume"].rolling(20).mean()
    df["high_20"] = df["High"].rolling(20).max()
    df["low_20"] = df["Low"].rolling(20).min()

    prev_close = df["Close"].shift(1)
    true_range = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = true_range.ewm(alpha=1 / 14, adjust=False).mean()
    df["traded_value20"] = (df["Close"] * df["Volume"]).rolling(20).mean()
    return df


def fetch_history(symbol: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """
    Returns a DataFrame with Open/High/Low/Close/Volume, indexed by date,
    plus the indicator columns from add_indicators() pre-computed since
    every strategy, filter and the backtester need them.
    """
    if yf is None:
        raise ImportError("yfinance not installed. Run: pip install -r requirements.txt")

    yf_symbol = to_yf_symbol(symbol)
    df = yf.Ticker(yf_symbol).history(period=period, interval=interval, auto_adjust=True)
    if df.empty:
        raise ValueError(f"no price data returned for {yf_symbol}")

    return add_indicators(df)
