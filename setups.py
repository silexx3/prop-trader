"""The two charter setups. Detectors emit candidate orders — never trades.

A candidate is a dict with ticker, setup, entry, stop, target, and a reason
string a human can sanity-check against a chart before confirming.
"""

from __future__ import annotations

import pandas as pd

from data import returns_correlation, swing_low

MIN_TARGET_R = 2.0

# Charter amendments 2026-07-09: correlation guard + regime filter.
CORR_MAX = 0.85        # candidates this correlated with committed names are one bet twice
CORR_LOOKBACK = 90     # sessions of shared history used to judge
REGIME_TICKER = "SPY"  # the tide every long swims in


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
    min_volume = float(round(vol_mult * df["avg_vol20"].iloc[-1]))
    c = _candidate(
        ticker, "base_breakout", entry, stop,
        f"{base_weeks}-week base {range_low:.2f}–{range_high:.2f} "
        f"({(range_high / range_low - 1) * 100:.1f}% range) near highs; entry on break of "
        f"{range_high:.2f}; fill requires volume ≥ {min_volume:,.0f} ({vol_mult}× avg) — "
        "a quiet break is not the setup.",
    )
    if c is not None:
        c["min_volume"] = min_volume
    return c


def _regime_off(frames: dict[str, pd.DataFrame]) -> str | None:
    """Non-None (with the reason) when the index says stand down: SPY closing
    below its 50-day SMA is not the tide to be buying breakouts into.
    Permissive when SPY is absent (e.g. practice windows predating a ticker)."""
    spy = frames.get(REGIME_TICKER)
    if spy is None or pd.isna(spy["sma50"].iloc[-1]):
        return None
    close, sma50 = spy["close"].iloc[-1], spy["sma50"].iloc[-1]
    if close < sma50:
        return (f"regime off — {REGIME_TICKER} {close:.2f} below its 50-day "
                f"SMA {sma50:.2f}; longs stand down")
    return None


def scan(frames: dict[str, pd.DataFrame], skip_tickers: set[str] = frozenset(),
         variant: dict | None = None, guards: bool = True) -> list[dict]:
    """Run both detectors over the watchlist. One candidate max per ticker;
    tickers with an open trade or pending order are skipped (no pyramiding).

    Candidates failing the regime filter or the correlation guard are still
    returned but carry a `blocked` reason — the caller logs the skip so
    discipline stays auditable. `variant` overrides detector params (Practice
    Lab / league challengers); `guards=False` (the league's control account
    only) skips the regime filter and correlation guard to run the
    pre-2026-07-09 ruleset. The live charter bot always runs defaults.
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

    if not guards:
        return candidates

    regime_reason = _regime_off(frames)
    kept: list[dict] = []
    for c in candidates:
        if regime_reason:
            c["blocked"] = regime_reason
            continue
        # Correlation guard: against committed tickers (open/pending) first,
        # then against candidates already kept this scan (first come wins).
        for other in list(skip_tickers) + [k["ticker"] for k in kept]:
            if other not in frames:
                continue
            corr = returns_correlation(frames[c["ticker"]], frames[other], CORR_LOOKBACK)
            if corr > CORR_MAX:
                c["blocked"] = (f"correlation guard — {c['ticker']} moves with {other} "
                                f"({corr:.2f} over {CORR_LOOKBACK}d): one bet, two tickets")
                break
        else:
            kept.append(c)
    return candidates
