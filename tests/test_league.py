"""Forward League tests. The charter ledger is sacred; challengers are
expendable; each account really runs its own ruleset."""

import numpy as np
import pandas as pd
import pytest

import data as market
import engine
import journal
import league
import practice
from tests.test_backtest import _uptrend_pullback_frame


@pytest.fixture
def league_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(league, "LEAGUE_DIR", tmp_path)
    return tmp_path


def _downtrend_spy(days=130):
    dates = pd.bdate_range("2020-01-01", periods=days)
    closes = np.linspace(500, 380, days)
    spy = pd.DataFrame({"open": closes + 0.5, "high": closes + 1.0,
                        "low": closes - 1.0, "close": closes,
                        "volume": [50_000_000] * days}, index=dates)
    return market.add_indicators(spy)


def test_challenger_rules_overrides_apply(league_dir):
    agg = next(a for a in league.ACCOUNTS if a["id"] == "aggressive")
    ledger = league.new_challenger_ledger(agg, started="2026-07-09")
    rules = engine.rules_from_ledger(ledger)
    assert rules.risk_per_trade_pct == 2.0
    assert rules.max_open_positions == 3
    # 2% of $5000 = $100 at $2/share risk -> 50 shares (charter would size 25).
    shares, _ = engine.position_size(5000.0, 100.0, 98.0, rules)
    assert shares == 50


def test_control_trades_through_regime_off_while_guarded_account_skips(league_dir):
    frames = {"SPY": _downtrend_spy(), "CAND": _uptrend_pullback_frame()}
    control = next(a for a in league.ACCOUNTS if a["id"] == "control")
    zen = next(a for a in league.ACCOUNTS if a["id"] == "zen")
    league.run_league_from_frames(frames, "2026-07-09", accounts=[control, zen])

    control_ledger = journal.load_ledger(league_dir / "control.json")
    zen_ledger = journal.load_ledger(league_dir / "zen.json")
    assert len(control_ledger["pending_orders"]) == 1      # traded through it
    assert zen_ledger["pending_orders"] == []              # regime filter said no
    assert any("regime" in s["reason"] for s in zen_ledger["skipped_candidates"])


def test_frontrunner_adopts_lab_leader(league_dir, monkeypatch):
    fake_board = [{"variant": "pullback-wide-zone", "runs": 12, "trades": 90,
                   "total_R": 40.0, "expectancy_R": 0.44}]
    monkeypatch.setattr(practice, "leaderboard", lambda history=None: fake_board)
    params, name = league.resolve_variant(
        next(a for a in league.ACCOUNTS if a["id"] == "frontrunner"))
    assert name == "pullback-wide-zone"
    assert params == {"ma_pullback": {"zone_tolerance": 1.02}}


def test_frontrunner_falls_back_to_baseline_on_thin_sample(league_dir, monkeypatch):
    fake_board = [{"variant": "pullback-wide-zone", "runs": 2, "trades": 10,
                   "total_R": 5.0, "expectancy_R": 0.5}]
    monkeypatch.setattr(practice, "leaderboard", lambda history=None: fake_board)
    params, name = league.resolve_variant(
        next(a for a in league.ACCOUNTS if a["id"] == "frontrunner"))
    assert name == "charter-baseline" and params == {}


def test_league_night_is_idempotent_per_date(league_dir):
    frames = {"CAND": _uptrend_pullback_frame()}
    zen = [next(a for a in league.ACCOUNTS if a["id"] == "zen")]
    first = league.run_league_from_frames(frames, "2026-07-09", accounts=zen)
    second = league.run_league_from_frames(frames, "2026-07-09", accounts=zen)
    assert len(first) == 1 and second == []
    ledger = journal.load_ledger(league_dir / "zen.json")
    assert len(ledger["sessions"]) == 1


def test_corrupt_challenger_recreated_fresh(league_dir):
    (league_dir / "zen.json").write_text("{not json")
    frames = {"CAND": _uptrend_pullback_frame()}
    zen = [next(a for a in league.ACCOUNTS if a["id"] == "zen")]
    outcomes = league.run_league_from_frames(frames, "2026-07-09", accounts=zen)
    assert len(outcomes) == 1
    ledger = journal.load_ledger(league_dir / "zen.json")
    assert ledger["account"]["starting_balance"] == 5000.0


def test_charter_ledger_untouched_by_league(league_dir):
    before = journal.LEDGER_PATH.read_bytes()
    frames = {"CAND": _uptrend_pullback_frame()}
    league.run_league_from_frames(frames, "2026-07-09")
    assert journal.LEDGER_PATH.read_bytes() == before
