"""Correlation guard and regime filter (charter amendments 2026-07-09).

Two positions that move together are one bet wearing two tickets, and
buying pullbacks while the index itself is breaking down is fighting the
tide — both now blocked at scan time, with the block reason logged."""

import numpy as np
import pandas as pd

import data as market
import setups
from tests.test_backtest import _uptrend_pullback_frame


def _correlated_pair(days=130, noise=0.0, seed=1):
    """Two frames driven by the same random walk (correlation ~1 when noise=0)."""
    rng = np.random.default_rng(seed)
    base_steps = rng.normal(0.3, 1.0, days)
    dates = pd.bdate_range("2020-01-01", periods=days)
    frames = {}
    for i, name in enumerate(("AAA", "BBB")):
        extra = rng.normal(0, noise, days) if noise else 0
        closes = 100 + np.cumsum(base_steps + extra) + i * 50
        df = pd.DataFrame({
            "open": closes - 0.1, "high": closes + 0.2, "low": closes - 0.3,
            "close": closes, "volume": [1_000_000] * days,
        }, index=dates)
        frames[name] = market.add_indicators(df)
    return frames


def test_returns_correlation_detects_twins_and_strangers():
    frames = _correlated_pair(noise=0.0)
    assert market.returns_correlation(frames["AAA"], frames["BBB"]) > 0.95
    rng_frames = _correlated_pair(noise=25.0, seed=7)
    assert market.returns_correlation(rng_frames["AAA"], rng_frames["BBB"]) < 0.85


def test_scan_blocks_candidate_correlated_with_open_position():
    df = _uptrend_pullback_frame()
    frames = {"OPEN1": df.copy(), "CAND": df.copy()}  # identical = corr 1.0
    out = setups.scan(frames, skip_tickers={"OPEN1"})
    cands = [c for c in out if c["ticker"] == "CAND"]
    assert cands and "correlat" in cands[0]["blocked"]


def test_scan_blocks_second_twin_candidate_but_keeps_first():
    df = _uptrend_pullback_frame()
    frames = {"AAA": df.copy(), "BBB": df.copy()}
    out = setups.scan(frames)
    blocked = [c for c in out if c.get("blocked")]
    kept = [c for c in out if not c.get("blocked")]
    assert len(kept) == 1 and len(blocked) == 1


def test_regime_filter_blocks_all_when_spy_below_50sma():
    cand_df = _uptrend_pullback_frame()
    # SPY in a downtrend: steady decline keeps close below the 50-day SMA.
    dates = pd.bdate_range("2020-01-01", periods=130)
    closes = np.linspace(500, 380, 130)
    spy = pd.DataFrame({
        "open": closes + 0.5, "high": closes + 1.0, "low": closes - 1.0,
        "close": closes, "volume": [50_000_000] * 130,
    }, index=dates)
    frames = {"SPY": market.add_indicators(spy), "CAND": cand_df}
    out = setups.scan(frames)
    cand = [c for c in out if c["ticker"] == "CAND"]
    assert cand and "regime" in cand[0]["blocked"]


def test_regime_filter_passes_when_spy_absent():
    # Practice windows from eras where a ticker didn't exist must still work.
    df = _uptrend_pullback_frame()
    out = setups.scan({"CAND": df})
    assert out and not out[0].get("blocked")
