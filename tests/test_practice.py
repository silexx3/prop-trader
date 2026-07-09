"""Practice Lab tests: variant params must actually reach the detectors, the
cache must round-trip, history must accumulate, and none of it may ever touch
the real ledger."""

import json

import pandas as pd
import pytest

import data as market
import journal
import practice
import setups
from tests.test_backtest import _uptrend_pullback_frame


def test_variant_params_reach_detector():
    df = _uptrend_pullback_frame()
    baseline = setups.scan({"TEST": df})
    tweaked = setups.scan({"TEST": df}, variant={"ma_pullback": {"stop_buffer": 0.95}})
    assert baseline and tweaked
    # A 5% stop buffer must produce a lower stop than the 0.2% default.
    assert tweaked[0]["stop"] < baseline[0]["stop"]


def test_unknown_variant_key_is_ignored_for_other_detector():
    df = _uptrend_pullback_frame()
    # base_breakout params must not leak into ma_pullback calls.
    out = setups.scan({"TEST": df}, variant={"base_breakout": {"base_weeks": 8}})
    assert out  # ma_pullback still fires with its defaults


def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(market, "CACHE_DIR", tmp_path)
    df = _uptrend_pullback_frame()
    market.save_cache({"TEST": df})
    loaded = market.load_cache(["TEST", "MISSING"])
    assert list(loaded.keys()) == ["TEST"]
    assert len(loaded["TEST"]) == len(df)
    assert "sma20" in loaded["TEST"].columns  # indicators survive the round-trip


def test_practice_run_appends_history_and_leaderboard_aggregates(tmp_path, monkeypatch):
    monkeypatch.setattr(practice, "HISTORY_PATH", tmp_path / "hist.json")
    monkeypatch.setattr(practice, "MIN_SESSIONS", 100)
    monkeypatch.setattr(practice, "WINDOW_SESSIONS", 30)
    monkeypatch.setattr(practice, "VARIANTS", practice.VARIANTS[:2])

    frames = {"TEST": _uptrend_pullback_frame(days=260)}
    monkeypatch.setattr(market, "fetch_or_cache", lambda tickers, period="max": frames)

    before = journal.LEDGER_PATH.read_bytes()
    r1 = practice.run_practice(["TEST"])
    r2 = practice.run_practice(["TEST"])
    assert journal.LEDGER_PATH.read_bytes() == before  # real ledger untouched

    assert r1["run"] == 1 and r2["run"] == 2
    history = practice.load_history()
    assert len(history["runs"]) == 2

    board = practice.leaderboard(history)
    assert {b["variant"] for b in board} == {v["name"] for v in practice.VARIANTS}
    for b in board:
        assert b["runs"] == 2  # every variant appears in every run


def test_pick_window_is_deterministic_per_run_number():
    frames = {"TEST": _uptrend_pullback_frame(days=900)}
    w1 = practice.pick_window(frames, run_number=3)
    w2 = practice.pick_window(frames, run_number=3)
    w3 = practice.pick_window(frames, run_number=4)
    assert w1["TEST"].index.equals(w2["TEST"].index)
    assert not w1["TEST"].index.equals(w3["TEST"].index)
