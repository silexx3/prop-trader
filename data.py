"""Daily OHLCV via yfinance, plus the indicators the detectors need.

Free EOD/delayed data — fine for swing on daily charts, never for scalping.
If a ticker's data can't be fetched, it returns no frame and the charter's
"no numbers, no trade" rule applies downstream.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

LOOKBACK = "18mo"  # enough history for the 52-week-high distance plus SMAs


def fetch_watchlist(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Fetch daily OHLCV for each ticker; missing/failed tickers are omitted."""
    frames: dict[str, pd.DataFrame] = {}
    data = yf.download(tickers, period=LOOKBACK, interval="1d",
                       group_by="ticker", auto_adjust=True, progress=False)
    for t in tickers:
        try:
            df = data[t] if len(tickers) > 1 else data
        except KeyError:
            continue
        df = df.dropna(subset=["Close"])
        if len(df) < 60:  # not enough history to trust the 50 SMA
            continue
        frames[t] = add_indicators(df)
    return frames


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    df["sma20"] = df["close"].rolling(20).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    df["avg_vol20"] = df["volume"].rolling(20).mean()
    df["high_52w"] = df["high"].rolling(252, min_periods=60).max()
    df["dist_from_52w_high_pct"] = (df["close"] / df["high_52w"] - 1) * 100
    return df


def swing_low(df: pd.DataFrame, lookback: int = 10) -> float:
    """Most recent swing low: the lowest low of the last `lookback` bars."""
    return float(df["low"].iloc[-lookback:].min())


def last_bar(df: pd.DataFrame) -> dict:
    row = df.iloc[-1]
    return {
        "date": str(df.index[-1].date()),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]),
    }


def bars_today(frames: dict[str, pd.DataFrame]) -> dict[str, dict]:
    return {t: last_bar(df) for t, df in frames.items()}


def latest_session_date(frames: dict[str, pd.DataFrame]) -> str:
    """Most recent trading date across the watchlist."""
    return max(str(df.index[-1].date()) for df in frames.values())


def regime_summary(frames: dict[str, pd.DataFrame]) -> str:
    """SPY/QQQ vs their 20/50-day SMAs — the tide the trades swim in."""
    parts = []
    for t in ("SPY", "QQQ"):
        df = frames.get(t)
        if df is None or pd.isna(df["sma50"].iloc[-1]):
            continue
        close = df["close"].iloc[-1]
        s20, s50 = df["sma20"].iloc[-1], df["sma50"].iloc[-1]
        if close > s20 > s50:
            state = "uptrend (above rising 20/50)"
        elif close > s50:
            state = "choppy uptrend (above 50, testing 20)"
        elif close > s20:
            state = "bounce attempt (above 20, below 50)"
        else:
            state = "downtrend (below 20/50)"
        parts.append(f"{t} {close:.2f}, {state}")
    return "; ".join(parts) if parts else "regime unavailable (index data missing)"


def watchlist_volatility_pct(frames: dict[str, pd.DataFrame]) -> float:
    """Average absolute % move of the watchlist today — feeds the brutality rating."""
    moves = []
    for df in frames.values():
        if len(df) >= 2:
            moves.append(abs(df["close"].iloc[-1] / df["close"].iloc[-2] - 1) * 100)
    return round(sum(moves) / len(moves), 2) if moves else 0.0
