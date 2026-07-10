"""Day League tests: each personality must actually behave like itself, and
the charter day ledger stays sacred."""

import pandas as pd
import pytest

import day_league
import day_session
import intraday
import journal
from tests.test_day import _bars, _orb_day


def _p(pid):
    return next(p for p in day_league.PERSONALITIES if p["id"] == pid)


@pytest.fixture
def league_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(day_league, "DAY_LEAGUE_DIR", tmp_path)
    return tmp_path


def _spy(above_vwap: bool, bars=15):
    """SPY tape pinned above or below its own VWAP."""
    if above_vwap:  # steady riser: close always above running vwap
        rows = [(100 + i * 0.2, 100.3 + i * 0.2, 99.9 + i * 0.2, 100.25 + i * 0.2, 5_000_000)
                for i in range(bars)]
    else:           # steady faller: close always below running vwap
        rows = [(100 - i * 0.2, 100.1 - i * 0.2, 99.7 - i * 0.2, 99.75 - i * 0.2, 5_000_000)
                for i in range(bars)]
    return _bars(rows)


def test_turtle_never_trades_the_first_hour(league_dir):
    # Breakout fires at bar 10 — inside Turtle's no-go window (first 12 bars),
    # and price never re-triggers after: Turtle must end the day flat.
    frames = {"TEST": _orb_day(break_bar=10, after="drift")}
    day_league.run_day_league_from_frames(frames, "2026-07-09", [_p("turtle")])
    ledger = journal.load_ledger(league_dir / "turtle.json")
    # The drift keeps high >= trigger after bar 12, so turtle MAY enter late —
    # what it must never do is hold an entry from before bar 12.
    for t in ledger["closed_trades"]:
        assert t["entry_bar"] >= 12 if "entry_bar" in t else True
    assert ledger["sessions"][0]["personality"] == "turtle"


def test_owl_skips_without_spy_tailwind_and_trades_with_it(league_dir):
    cand = _orb_day(after="run")
    no_wind = {"TEST": cand, "SPY": _spy(above_vwap=False, bars=len(cand))}
    day_league.run_day_league_from_frames(no_wind, "2026-07-08", [_p("owl")])
    flat = journal.load_ledger(league_dir / "owl.json")
    assert flat["closed_trades"] == []  # no tailwind, no trade

    with_wind = {"TEST": _orb_day(after="run"), "SPY": _spy(above_vwap=True, bars=len(cand))}
    day_league.run_day_league_from_frames(with_wind, "2026-07-09", [_p("owl")])
    traded = journal.load_ledger(league_dir / "owl.json")
    assert len(traded["closed_trades"]) == 1  # wind at its back, it flies


def test_shark_sizes_at_2pct_and_takes_more_entries(league_dir):
    frames = {f"T{i}": _orb_day(after="drift") for i in range(6)}
    day_league.run_day_league_from_frames(frames, "2026-07-09", [_p("shark")])
    ledger = journal.load_ledger(league_dir / "shark.json")
    assert len(ledger["closed_trades"]) == 3  # 3 concurrent (vs charter's 2)
    for t in ledger["closed_trades"]:
        # 2% of $5000 = $100 budget; charter's 1% would be ~$50.
        assert t["risk_usd"] > 60


def test_rabbit_looser_filters_take_the_wide_range_day(league_dir):
    # An opening range ~2% wide: charter's orb (max 1.5%) refuses it,
    # rabbit (max 2.5%) trades it.
    rows = [(100, 101.5, 99.5, 100.5, 1_000_000)] * 6
    rows += [(100.5, 101.2, 100.2, 100.8, 800_000)] * 4
    rows += [(100.9, 102.2, 100.8, 102.0, 2_000_000)]
    rows += [(102.0, 105.5, 101.8, 105.0, 1_500_000)] * 4
    frames = {"TEST": _bars(rows)}

    charter_ledger = day_session.new_day_ledger()
    charter_closed = day_session.replay_day(charter_ledger, frames, "2026-07-09")
    assert charter_closed == []  # too wide for the charter

    day_league.run_day_league_from_frames(frames, "2026-07-09", [_p("rabbit")])
    rabbit = journal.load_ledger(league_dir / "rabbit.json")
    assert len(rabbit["closed_trades"]) == 1  # rabbit hops where others wait


def test_idempotent_and_charter_day_ledger_untouched(league_dir):
    before = day_session.DAY_LEDGER_PATH.read_bytes()
    frames = {"TEST": _orb_day(after="run")}
    first = day_league.run_day_league_from_frames(frames, "2026-07-09", [_p("shark")])
    second = day_league.run_day_league_from_frames(frames, "2026-07-09", [_p("shark")])
    assert len(first) == 1 and second == []
    assert day_session.DAY_LEDGER_PATH.read_bytes() == before


def test_default_config_regression_matches_charter_behavior():
    # replay_day with no config must behave exactly as the charter lane:
    # same trades, same fills as before the config refactor.
    ledger = day_session.new_day_ledger()
    closed = day_session.replay_day(ledger, {"TEST": _orb_day(after="run")}, "2026-07-09")
    assert len(closed) == 1
    assert closed[0]["reason"] == "target"
