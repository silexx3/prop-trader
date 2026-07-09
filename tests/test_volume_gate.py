"""base_breakout's charter text requires the break to come WITH volume
(>1.5x the 20-day average). The candidate carries that requirement and the
fill simulation enforces it — a quiet break is not the setup."""

import engine
import setups
from tests.test_engine import fresh_ledger


def _place(ledger, min_volume=None):
    return engine.place_order(ledger, ticker="TEST", setup="base_breakout",
                              entry=100.0, stop=98.0, target=104.0,
                              date="2026-07-08", min_volume=min_volume)


def test_low_volume_break_does_not_fill():
    ledger = fresh_ledger()
    _place(ledger, min_volume=1_500_000)
    bars = {"TEST": {"open": 99.0, "high": 101.0, "low": 98.5, "close": 100.5,
                     "volume": 900_000}}
    filled, expired = engine.process_pending_fills(ledger, bars, "2026-07-09")
    assert filled == []
    assert len(expired) == 1
    assert ledger["open_trades"] == []


def test_high_volume_break_fills():
    ledger = fresh_ledger()
    _place(ledger, min_volume=1_500_000)
    bars = {"TEST": {"open": 99.0, "high": 101.0, "low": 98.5, "close": 100.5,
                     "volume": 2_000_000}}
    filled, _ = engine.process_pending_fills(ledger, bars, "2026-07-09")
    assert len(filled) == 1


def test_order_without_min_volume_ignores_volume():
    # ma_pullback orders carry no volume requirement — unchanged behavior.
    ledger = fresh_ledger()
    _place(ledger, min_volume=None)
    bars = {"TEST": {"open": 99.0, "high": 101.0, "low": 98.5, "close": 100.5}}
    filled, _ = engine.process_pending_fills(ledger, bars, "2026-07-09")
    assert len(filled) == 1


def test_base_breakout_candidate_carries_min_volume():
    import pandas as pd
    import data as market
    # A flat tight base near highs with steady volume.
    dates = pd.bdate_range("2020-01-01", periods=120)
    df = pd.DataFrame({
        "open": [100.0] * 120, "high": [101.0] * 120,
        "low": [99.5] * 120, "close": [100.5] * 120,
        "volume": [1_000_000] * 120,
    }, index=dates)
    df = market.add_indicators(df)
    c = setups.base_breakout("TEST", df)
    assert c is not None
    assert c["min_volume"] == 1_500_000  # 1.5 x the 20-day average
