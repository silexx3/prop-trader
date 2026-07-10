"""The two day-trading setups (day-trading-charter.md; course module 18).

A day candidate is a dict with entry trigger, stop, target, the bar index it
becomes active from, and a volume floor for the trigger bar. Detection only
ever reads bars BEFORE the active index — the replay engine walks forward
from there, so there is no lookahead to leak.
"""

from __future__ import annotations

import pandas as pd

from intraday import OR_BARS, opening_range

MIN_TARGET_R = 2.0


def _candidate(ticker: str, setup: str, entry: float, stop: float,
               active_from: int, min_volume: float, reason: str) -> dict | None:
    entry, stop = round(entry, 2), round(stop, 2)
    if entry <= stop:
        return None
    return {
        "ticker": ticker, "setup": setup, "entry": entry, "stop": stop,
        "target": round(entry + MIN_TARGET_R * (entry - stop), 2),
        "active_from": active_from, "min_volume": min_volume, "reason": reason,
    }


def orb_long(ticker: str, df: pd.DataFrame, *, or_bars: int = OR_BARS,
             vol_mult: float = 1.2, max_range_pct: float = 1.5) -> dict | None:
    """Opening-range breakout: first 30 minutes set the range; entry on a
    break of the OR high on volume, stop below the OR low, 2R target.

    A too-wide opening range (> max_range_pct of price) is a news bar, not a
    base — skipped. Active from the first bar after the range completes."""
    if len(df) <= or_bars:
        return None
    or_high, or_low, or_avg_vol = opening_range(df, or_bars)
    if or_low <= 0 or (or_high / or_low - 1) * 100 > max_range_pct:
        return None
    return _candidate(
        ticker, "orb_long", or_high * 1.0005, or_low * 0.999, or_bars,
        vol_mult * or_avg_vol,
        f"30-min opening range {or_low:.2f}–{or_high:.2f}; long on the break of "
        f"{or_high:.2f} with volume ≥ {vol_mult}× the opening average.",
    )


def vwap_pullback_long(ticker: str, df: pd.DataFrame, *, or_bars: int = OR_BARS,
                       extended_bars: int = 3) -> dict | None:
    """Morning strength above VWAP, first orderly pullback INTO VWAP that
    holds, entry on reclaim of the pullback bar's high, stop under the dip.

    Scans forward from the opening range; the first qualifying bar defines
    the trade. Detection at bar i uses only bars ≤ i; active from i+1."""
    for i in range(or_bars + extended_bars, len(df) - 6):
        window = df.iloc[:i + 1]
        bar = window.iloc[-1]
        vwap = bar["vwap"]
        if pd.isna(vwap):
            continue
        prior = window.iloc[-1 - extended_bars:-1]
        was_extended = (prior["close"] > prior["vwap"] * 1.0005).all()
        touched = bar["low"] <= vwap * 1.0005
        held = bar["close"] >= vwap * 0.999
        if was_extended and touched and held:
            dip_low = float(window["low"].iloc[-2:].min())
            return _candidate(
                ticker, "vwap_pullback", float(bar["high"]) + 0.01,
                dip_low * 0.999, i + 1, 0.0,
                f"Held above VWAP then first pullback into it (bar {i}); long on "
                f"reclaim of {bar['high']:.2f}, stop under the dip {dip_low:.2f}.",
            )
    return None


def scan_day(frames: dict[str, pd.DataFrame], variant: dict | None = None) -> list[dict]:
    """One candidate max per ticker per day; ORB first (it forms earlier).

    `variant` (Day League personalities): {"orb_long": {kwargs},
    "vwap_pullback_long": {kwargs}} — the main day lane never passes it."""
    variant = variant or {}
    out = []
    for ticker, df in frames.items():
        for detector in (orb_long, vwap_pullback_long):
            c = detector(ticker, df, **variant.get(detector.__name__, {}))
            if c:
                out.append(c)
                break
    out.sort(key=lambda c: c["active_from"])
    return out
