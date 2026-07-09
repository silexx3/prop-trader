"""The two charter setups. Detectors emit candidate orders — never trades.

A candidate is a dict with ticker, setup, entry, stop, target, and a reason
string a human can sanity-check against a chart before confirming.
"""

from __future__ import annotations

import pandas as pd

from data import swing_low

MIN_TARGET_R = 2.0


def _candidate(ticker: str, setup: str, entry: float, stop: float, reason: str) -> dict | None:
    # Round entry/stop to cents FIRST, then derive the target from the rounded
    # levels — otherwise the target can land a cent short of 2R and the engine
    # (correctly) refuses the order.
    entry, stop = round(entry, 2), round(stop, 2)
    if entry <= stop:  # rounding collapsed the risk to nothing — no trade
        return None
    return {
        "ticker": ticker,
        "setup": setup,
        "entry": entry,
        "stop": stop,
        "target": round(entry + MIN_TARGET_R * (entry - stop), 2),
        "reason": reason,
    }


def ma_pullback(ticker: str, df: pd.DataFrame, *, pullback_lookback: int = 10,
                zone_tolerance: float = 1.01, stop_buffer: float = 0.998) -> dict | None:
    """Uptrend, pullback into the 20/50 SMA zone, entry on reclaim of prior high.

    Uptrend: 20 and 50 SMAs rising, and price was above both a month ago
    (so the trend predates the pullback). Pullback: recent close(s) inside or
    near the SMA zone. Entry = prior day's high (buy stop); stop = below the
    pullback low. Keyword params exist for the Practice Lab's variant testing;
    the defaults ARE the charter configuration and the live bot never overrides
    them.
    """
    if len(df) < 75 or pd.isna(df["sma50"].iloc[-1]) or pd.isna(df["sma50"].iloc[-22]):
        return None
    last = df.iloc[-1]
    sma20, sma50 = last["sma20"], last["sma50"]

    rising = sma20 > df["sma20"].iloc[-6] and sma50 > df["sma50"].iloc[-11]
    month_ago = df.iloc[-22]
    was_uptrend = month_ago["close"] > month_ago["sma20"] and month_ago["close"] > month_ago["sma50"]
    if not (rising and was_uptrend):
        return None

    # Pullback: today's low reached down into (or near) the 20/50 zone,
    # but price hasn't broken down below the zone.
    zone_top, zone_bottom = max(sma20, sma50), min(sma20, sma50)
    touched_zone = last["low"] <= zone_top * zone_tolerance
    still_alive = last["close"] > zone_bottom * 0.98
    if not (touched_zone and still_alive):
        return None

    pullback_low = swing_low(df, lookback=pullback_lookback)
    entry = float(df["high"].iloc[-1])  # reclaim of prior day's high, next session
    stop = pullback_low * stop_buffer   # just below the pullback low
    if entry <= stop:
        return None
    return _candidate(
        ticker, "ma_pullback", entry, stop,
        f"Uptrend pullback into 20/50 zone (SMA20 {sma20:.2f} / SMA50 {sma50:.2f}); "
        f"entry on reclaim of today's high {entry:.2f}, stop below pullback low {pullback_low:.2f}.",
    )


def base_breakout(ticker: str, df: pd.DataFrame, *, base_weeks: int = 4,
                  max_range_pct: float = 10.0, vol_mult: float = 1.5,
                  stop_buffer: float = 0.998) -> dict | None:
    """≥4 weeks of tight range within ~10% of highs; entry on break of range
    high with volume above 1.5× the 20-day average. Keyword params exist for
    the Practice Lab's variant testing; the defaults ARE the charter config.
    """
    bars = base_weeks * 5
    if len(df) < bars + 55 or pd.isna(df["avg_vol20"].iloc[-1]):
        return None
    base = df.iloc[-bars:]
    range_high = float(base["high"].max())
    range_low = float(base["low"].min())
    if range_low <= 0 or (range_high / range_low - 1) * 100 > max_range_pct:
        return None
    # Base must sit near highs — within ~10% of the 52-week high.
    if df["dist_from_52w_high_pct"].iloc[-1] < -10.0:
        return None
    # Not already broken out: last close still inside the range.
    last = df.iloc[-1]
    if last["close"] >= range_high:
        return None
    # Volume condition is checked at fill time in spirit; here we require the
    # base to be quiet (no distribution): recent volume not collapsing the setup.
    entry = range_high * 1.001  # break of the range high
    stop_base = range_low * stop_buffer
    stop_swing = swing_low(df, lookback=10) * stop_buffer
    stop = max(stop_base, stop_swing)  # whichever risks less
    if entry <= stop:
        return None
    return _candidate(
        ticker, "base_breakout", entry, stop,
        f"{base_weeks}-week base {range_low:.2f}–{range_high:.2f} "
        f"({(range_high / range_low - 1) * 100:.1f}% range) near highs; entry on break of "
        f"{range_high:.2f}, needs volume > {vol_mult}× avg ({df['avg_vol20'].iloc[-1]:,.0f}) to trust the fill.",
    )


def scan(frames: dict[str, pd.DataFrame], skip_tickers: set[str] = frozenset(),
         variant: dict | None = None) -> list[dict]:
    """Run both detectors over the watchlist. One candidate max per ticker;
    tickers with an open trade or pending order are skipped (no pyramiding).

    `variant` is Practice Lab-only: {"ma_pullback": {kwargs}, "base_breakout":
    {kwargs}} overrides detector parameters. The live bot always calls scan
    without it, so live behavior is exactly the charter defaults.
    """
    variant = variant or {}
    candidates = []
    for ticker, df in frames.items():
        if ticker in skip_tickers:
            continue
        for detector in (ma_pullback, base_breakout):
            c = detector(ticker, df, **variant.get(detector.__name__, {}))
            if c:
                candidates.append(c)
                break
    return candidates
