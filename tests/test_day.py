"""Day-trading lane tests: synthetic 5-minute sessions, no network."""

import pandas as pd
import pytest

import day_session
import intraday
import journal
from day_setups import orb_long, scan_day, vwap_pullback_long


def _bars(rows):
    """rows: list of (open, high, low, close, volume)."""
    idx = pd.date_range("2026-07-09 09:30", periods=len(rows), freq="5min")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)
    return intraday.add_vwap(df)


def _orb_day(break_bar=10, breakout_vol=2_000_000, after="run"):
    """Tight 30-min range 99.5–100.5, then a breakout at `break_bar`."""
    rows = [(100, 100.5, 99.5, 100, 1_000_000)] * 6           # opening range
    rows += [(100, 100.4, 99.8, 100.1, 800_000)] * (break_bar - 6)
    rows += [(100.2, 101.2, 100.1, 101.0, breakout_vol)]       # the break
    if after == "run":                                         # clean run to 2R+
        rows += [(101.0, 103.5, 100.9, 103.2, 1_500_000)] * 4
    elif after == "reverse":                                   # break then die
        rows += [(101.0, 101.1, 98.5, 98.9, 1_500_000)] * 4
    else:                                                      # drift into close
        rows += [(101.0, 101.2, 100.6, 100.9, 900_000)] * 4
    return _bars(rows)


def _ledger():
    return day_session.new_day_ledger()


def test_orb_detects_tight_range_and_sets_2R_target():
    c = orb_long("TEST", _orb_day())
    assert c is not None
    assert c["active_from"] == 6
    assert c["target"] == pytest.approx(c["entry"] + 2 * (c["entry"] - c["stop"]), abs=0.02)


def test_orb_skips_wide_news_range():
    rows = [(100, 103, 97, 101, 3_000_000)] * 6 + [(101, 102, 100, 101, 1_000_000)] * 30
    assert orb_long("TEST", _bars(rows)) is None


def test_vwap_pullback_detects_dip_and_reclaim():
    rows = [(100, 100.5, 99.8, 100.2, 1_000_000)] * 6
    rows += [(100.3, 101.5, 100.2, 101.4, 1_200_000)] * 4   # extended above vwap
    rows += [(101.3, 101.4, 100.4, 100.9, 900_000)]          # dip INTO vwap, holds
    rows += [(101.0, 101.6, 100.8, 101.5, 1_100_000)] * 8
    c = vwap_pullback_long("TEST", _bars(rows))
    assert c is not None
    assert c["setup"] == "vwap_pullback"


def test_replay_winner_hits_2R_target():
    ledger = _ledger()
    closed = day_session.replay_day(ledger, {"TEST": _orb_day(after="run")}, "2026-07-09")
    assert len(closed) == 1
    assert closed[0]["reason"] == "target"
    assert closed[0]["r_multiple"] == pytest.approx(2.0 - 0.05, abs=0.15)
    assert ledger["account"]["balance"] > day_session.STARTING_BALANCE


def test_replay_loser_stops_out_about_minus_1R():
    ledger = _ledger()
    closed = day_session.replay_day(ledger, {"TEST": _orb_day(after="reverse")}, "2026-07-09")
    assert len(closed) == 1
    assert closed[0]["reason"] == "stop"
    assert -1.6 < closed[0]["r_multiple"] <= -1.0  # gap through stop can cost extra


def test_flat_by_close_always():
    ledger = _ledger()
    closed = day_session.replay_day(ledger, {"TEST": _orb_day(after="drift")}, "2026-07-09")
    assert len(closed) == 1
    assert closed[0]["reason"] == "eod_flat"  # never holds overnight


def test_quiet_break_with_no_volume_all_day_never_enters():
    # Break happens but volume stays below the floor on every bar afterward —
    # a quiet drift over the range is not the setup, all day long.
    rows = [(100, 100.5, 99.5, 100, 1_000_000)] * 6
    rows += [(100, 100.4, 99.8, 100.1, 800_000)] * 4
    rows += [(100.2, 101.2, 100.1, 101.0, 500_000)]
    rows += [(101.0, 103.5, 100.9, 103.2, 600_000)] * 4
    ledger = _ledger()
    closed = day_session.replay_day(ledger, {"TEST": _bars(rows)}, "2026-07-09")
    assert closed == []


def test_weak_break_can_fill_later_on_volume_confirmation_at_worse_price():
    # Break on weak volume doesn't fill; the next bar brings the volume with
    # price still over the trigger — entry happens there, at the worse open.
    df = _orb_day(breakout_vol=500_000, after="run")
    ledger = _ledger()
    closed = day_session.replay_day(ledger, {"TEST": df}, "2026-07-09")
    assert len(closed) == 1
    assert closed[0]["entry"] >= 101.0  # paid up for confirmation, no fantasy fill


def test_concurrency_and_daily_entry_caps():
    ledger = _ledger()
    frames = {f"T{i}": _orb_day(after="drift") for i in range(5)}
    closed = day_session.replay_day(ledger, frames, "2026-07-09")
    # 5 identical candidates, but max 2 concurrent — and since none exit
    # before the close, only 2 can ever be on at once.
    assert len(closed) == 2


def test_day_ledger_readable_by_journal_and_swing_ledger_untouched():
    before = journal.LEDGER_PATH.read_bytes()
    ledger = _ledger()
    day_session.replay_day(ledger, {"TEST": _orb_day(after="run")}, "2026-07-09")
    stats = journal.compute_stats(ledger)
    assert stats["trades_closed"] == 1
    assert journal.equity_curve(ledger)[-1][1] == ledger["account"]["balance"]
    assert journal.LEDGER_PATH.read_bytes() == before
