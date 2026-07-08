"""Backtest simulation tests. Uses small synthetic OHLCV data — never hits
the network — so these run fast and deterministically."""

import pandas as pd
import pytest

import backtest
import data as market
import engine
import journal
import setups


def _uptrend_pullback_frame(start_price: float = 50.0, days: int = 130) -> pd.DataFrame:
    """A steady uptrend for ~110 days, a 5-day pullback into the SMA zone,
    then a reclaim bar — engineered to trigger setups.ma_pullback on the
    reclaim day, with generous margins so it isn't fragile to rounding."""
    dates = pd.bdate_range("2020-01-01", periods=days)
    closes = []
    price = start_price
    for i in range(days):
        if i < days - 6:
            price += 0.30  # steady climb
        elif i < days - 1:
            price -= 0.60  # 5-day pullback, dips toward the rising SMAs
        else:
            price += 1.20  # reclaim day: strong bounce back up
        closes.append(price)

    df = pd.DataFrame({
        "open": [c - 0.1 for c in closes],
        "high": [c + 0.2 for c in closes],
        "low": [c - 0.3 for c in closes],
        "close": closes,
        "volume": [1_000_000] * days,
    }, index=dates)
    return market.add_indicators(df)


def test_no_lookahead_candidate_fills_after_signal_day_not_on_it():
    df = _uptrend_pullback_frame()
    frames = {"TEST": df}
    ledger = backtest.new_scratch_ledger(["TEST"])
    date_indices = {t: backtest.build_date_index(f) for t, f in frames.items()}
    dates = backtest.trading_dates(frames)

    signal_date = None
    for date in dates:
        bars = backtest.bars_on(frames, date_indices, date)
        engine.manage_open_trades(ledger, bars, date)
        engine.process_pending_fills(ledger, bars, date)
        busy = {t["ticker"] for t in ledger["open_trades"]}
        sliced = backtest.frames_through(frames, date_indices, date)
        candidates = setups.scan(sliced, skip_tickers=busy)
        for c in candidates:
            try:
                engine.place_order(ledger, ticker=c["ticker"], setup=c["setup"],
                                   entry=c["entry"], stop=c["stop"],
                                   target=c["target"], date=date, note=c["reason"])
                signal_date = date
            except engine.RuleViolation:
                pass
        if signal_date:
            break

    assert signal_date is not None, "test fixture should trigger at least one candidate"
    order = ledger["pending_orders"][0]
    assert ledger["open_trades"] == []
    assert order["placed"] == signal_date


def test_position_cap_enforced_across_tickers():
    df_a = _uptrend_pullback_frame(start_price=50.0)
    df_b = _uptrend_pullback_frame(start_price=200.0)
    df_c = _uptrend_pullback_frame(start_price=10.0)
    result = backtest.run_backtest_from_frames(
        {"AAA": df_a, "BBB": df_b, "CCC": df_c}, starting_balance=5000.0)
    committed_at_any_point = engine.open_risk_R(result["open_trades"]) + len(result["pending_orders"])
    assert committed_at_any_point <= engine.MAX_OPEN_RISK_R + 1e-9
    assert len(result["open_trades"]) + len(result["pending_orders"]) <= engine.MAX_OPEN_POSITIONS
    assert len(result["skipped_candidates"]) >= 1


def test_run_backtest_returns_ledger_journal_can_read():
    df = _uptrend_pullback_frame()
    result = backtest.run_backtest_from_frames({"TEST": df}, starting_balance=5000.0)
    stats = journal.compute_stats(result)
    assert "expectancy_R" in stats
    assert "trades_closed" in stats
    assert stats["trades_closed"] == len(result["closed_trades"])


def test_equity_curve_start_date_is_parseable():
    # journal.equity_curve() feeds ledger["started"] straight into
    # pd.to_datetime() for the dashboard chart — it must be a real date,
    # not a placeholder string like "backtest".
    df = _uptrend_pullback_frame()
    result = backtest.run_backtest_from_frames({"TEST": df}, starting_balance=5000.0)
    curve = journal.equity_curve(result)
    pd.to_datetime([d for d, _ in curve])  # raises if any point is unparseable


def test_run_backtest_never_touches_real_ledger():
    before = journal.LEDGER_PATH.read_bytes()
    df = _uptrend_pullback_frame()
    backtest.run_backtest_from_frames({"TEST": df}, starting_balance=5000.0)
    after = journal.LEDGER_PATH.read_bytes()
    assert before == after
