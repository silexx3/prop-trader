"""Live smoke test — hits yfinance for real. Skip in offline environments."""

import math

import pytest

import backtest
import journal


@pytest.mark.slow
def test_backtest_runs_end_to_end_on_real_data():
    result = backtest.run_backtest(["SPY", "QQQ"], starting_balance=5000.0)
    stats = journal.compute_stats(result)

    assert stats["trades_closed"] >= 0
    if stats["expectancy_R"] is not None:
        assert math.isfinite(stats["expectancy_R"])
        assert not math.isnan(stats["expectancy_R"])
    assert result["account"]["balance"] > 0
    for t in result["closed_trades"]:
        assert t["shares"] >= 1
        assert t["pnl_usd"] == pytest.approx(t["pnl_usd"])
