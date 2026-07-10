"""Intraday data layer for the day-trading lane: 5-minute bars via yfinance.

Free intraday data is delayed ~15 minutes, which is why the day lane runs as
an after-close REPLAY of the completed session, never as live execution —
same "no numbers, no trade" honesty as the swing charter, applied to the
clock: by 21:30 UTC the day's bars are final.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

# Deep-liquidity names only — thin intraday tape makes 5m fills a fantasy.
# Expanded 6 -> 10 per day-charter amendment 2026-07-10 ("trade more").
DAY_WATCHLIST = ["SPY", "QQQ", "NVDA", "AAPL", "MSFT", "AMD",
                 "TSLA", "META", "AMZN", "GOOGL"]
OR_BARS = 6  # opening range = first 6 five-minute bars = 30 minutes


def fetch_day_bars(tickers: list[str], interval: str = "5m") -> dict[str, pd.DataFrame]:
    """Regular-session 5m bars for the most recent trading day, per ticker.

    Only tickers with a full-looking session (enough bars to have an opening
    range and an afternoon) are returned — a halted or half-day tape is not
    a day to replay."""
    data = yf.download(tickers, period="1d", interval=interval,
                       group_by="ticker", auto_adjust=True, prepost=False,
                       progress=False)
    frames: dict[str, pd.DataFrame] = {}
    for t in tickers:
        try:
            df = data[t] if len(tickers) > 1 else data
        except KeyError:
            continue
        df = df.dropna(subset=["Close"])
        if len(df) < OR_BARS + 20:  # opening range plus a tradable rest-of-day
            continue
        frames[t] = add_vwap(df)
    return frames


def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Session VWAP: cumulative typical-price dollars over cumulative volume."""
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    typical = (df["high"] + df["low"] + df["close"]) / 3
    cum_vol = df["volume"].cumsum()
    df["vwap"] = (typical * df["volume"]).cumsum() / cum_vol.replace(0, pd.NA)
    return df


def opening_range(df: pd.DataFrame, or_bars: int = OR_BARS) -> tuple[float, float, float]:
    """(high, low, avg volume) of the first `or_bars` bars."""
    head = df.iloc[:or_bars]
    return float(head["high"].max()), float(head["low"].min()), float(head["volume"].mean())


def session_date(frames: dict[str, pd.DataFrame]) -> str:
    """The calendar date these bars belong to."""
    return max(str(df.index[-1].date()) for df in frames.values())
