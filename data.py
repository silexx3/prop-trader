"""Daily OHLCV via yfinance, plus the indicators the detectors need.

Free EOD/delayed data — fine for swing on daily charts, never for scalping.
If a ticker's data can't be fetched, it returns no frame and the charter's
"no numbers, no trade" rule applies downstream.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import yfinance as yf

LOOKBACK = "18mo"  # enough history for the 52-week-high distance plus SMAs

# US equities close at 20:00 UTC in summer (EDT) and 21:00 UTC in winter (EST).
# 21:05 UTC is a DST-proof "the daily bar is final now" cutoff; the scheduled
# 21:30 UTC run clears it year-round.
FINAL_BAR_CUTOFF_UTC = dt.time(21, 5)


def fetch_watchlist(tickers: list[str], period: str = LOOKBACK) -> dict[str, pd.DataFrame]:
    """Fetch daily OHLCV for each ticker; missing/failed tickers are omitted.

    `period` defaults to the live bot's 18-month window; pass "max" for a
    backtest that wants the fullest history yfinance has for each ticker.
    """
    frames: dict[str, pd.DataFrame] = {}
    data = yf.download(tickers, period=period, interval="1d",
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


CACHE_DIR = Path(__file__).parent / "data-cache"


def save_cache(frames: dict[str, pd.DataFrame]) -> None:
    """Persist fetched history so the Practice Lab can run fully offline."""
    CACHE_DIR.mkdir(exist_ok=True)
    for ticker, df in frames.items():
        df.to_csv(CACHE_DIR / f"{ticker}.csv")


def load_cache(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Load whatever cached history exists for `tickers` (missing ones omitted).
    Indicators were computed before caching, so no recomputation needed."""
    frames: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        path = CACHE_DIR / f"{ticker}.csv"
        if path.exists():
            frames[ticker] = pd.read_csv(path, index_col=0, parse_dates=True)
    return frames


def fetch_or_cache(tickers: list[str], period: str = "max") -> dict[str, pd.DataFrame]:
    """Fetch fresh history and update the cache; if the network is down or
    yfinance returns nothing, fall back to the last cached copy."""
    try:
        frames = fetch_watchlist(tickers, period=period)
    except Exception:
        frames = {}
    if frames:
        save_cache(frames)
        return frames
    return load_cache(tickers)


def returns_correlation(df_a: pd.DataFrame, df_b: pd.DataFrame,
                        lookback: int = 90) -> float:
    """Correlation of daily returns over the last `lookback` shared sessions.

    Two names moving together are one bet wearing two tickets — the scan
    layer uses this to stop the 2-position cap being eaten by twins.
    Returns 0.0 when there isn't enough overlapping history to judge.
    """
    a = df_a["close"].pct_change().dropna()
    b = df_b["close"].pct_change().dropna()
    joined = pd.concat([a, b], axis=1, join="inner").dropna().iloc[-lookback:]
    if len(joined) < 30:
        return 0.0
    corr = joined.iloc[:, 0].corr(joined.iloc[:, 1])
    return float(corr) if pd.notna(corr) else 0.0


def bar_is_final(bar_date: str, now: dt.datetime | None = None) -> bool:
    """True if `bar_date`'s daily bar can no longer change.

    A bar from any earlier day is final. Today's bar is only final after the
    DST-proof close cutoff — while the market is open (or just closed), the
    "daily bar" yfinance returns is still in progress, and the charter says
    no numbers, no trade.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    bar = dt.date.fromisoformat(bar_date)
    if bar < now.date():
        return True
    return now.time() >= FINAL_BAR_CUTOFF_UTC


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
