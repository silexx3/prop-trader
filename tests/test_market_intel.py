"""Market Intelligence tests: classification at known values, breadth math,
regime-change detection, and build_report as a pure function over injected
data (no network)."""

import pandas as pd
import pytest

import data as market
import market_intel as mi


def _spy(above_sma: bool):
    dates = pd.bdate_range("2026-01-01", periods=60)
    if above_sma:
        closes = [100 + i * 0.5 for i in range(60)]  # steady climb: close > sma50
    else:
        closes = [160 - i * 1.0 for i in range(60)]  # steady fall: close < sma50
    df = pd.DataFrame({"open": closes, "high": [c + 0.5 for c in closes],
                       "low": [c - 0.5 for c in closes], "close": closes,
                       "volume": [1_000_000] * 60}, index=dates)
    return market.add_indicators(df)


def _sector_frame(ret_pct: float, days=10):
    dates = pd.bdate_range("2026-01-01", periods=days)
    start = 100.0
    end = start * (1 + ret_pct / 100)
    closes = [start + (end - start) * i / (days - 1) for i in range(days)]
    df = pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes,
                       "volume": [500_000] * days}, index=dates)
    return market.add_indicators(df)


# ---------- classification ----------

def test_vix_bands():
    assert mi.vix_band(12.0) == "calm"
    assert mi.vix_band(18.0) == "normal"
    assert mi.vix_band(30.0) == "volatile"
    assert mi.vix_band(15.0) == "normal"   # boundary: not calm
    assert mi.vix_band(25.0) == "normal"   # boundary: not volatile


def test_regime_label_matches_setups_definition():
    assert mi.regime_label({"SPY": _spy(above_sma=True)}, vix_level=15) == "risk-on"
    assert mi.regime_label({"SPY": _spy(above_sma=False)}, vix_level=15) == "risk-off"
    assert mi.regime_label({}, vix_level=15) == "unknown"


def test_breadth_pct():
    frames = {"A": _spy(True), "B": _spy(True), "C": _spy(False)}
    assert mi.breadth_pct(frames) == pytest.approx(200 / 3, abs=0.1)
    assert mi.breadth_pct({}) is None


def test_sector_rotation_ranks_highest_first():
    frames = {"XLK": _sector_frame(3.0), "XLE": _sector_frame(-1.0), "XLU": _sector_frame(1.0)}
    ranked = mi.sector_rotation(frames)
    assert [r["ticker"] for r in ranked] == ["XLK", "XLU", "XLE"]
    assert ranked[0]["sector"] == "Technology"


# ---------- report is a pure function ----------

def test_build_report_pure_function():
    report = mi.build_report({"SPY": _spy(True)}, {"XLK": _sector_frame(2.0)}, vix_level=13.5)
    assert report["regime"] == "risk-on"
    assert report["vix_band"] == "calm"
    assert report["breadth_pct"] == 100.0
    assert len(report["sectors"]) == 1
    assert "generally more favorable" in report["regime_note"]


def test_build_report_handles_missing_vix():
    report = mi.build_report({"SPY": _spy(True)}, {}, vix_level=None)
    assert report["vix_band"] == "unknown"
    assert report["sectors"] == []


# ---------- regime-change detection ----------

def test_no_ping_on_first_run():
    assert mi.detect_regime_change([], "risk-on") is None


def test_no_ping_when_regime_unchanged():
    history = [{"date": "2026-07-08", "regime": "risk-on"}]
    assert mi.detect_regime_change(history, "risk-on") is None


def test_ping_on_real_flip():
    history = [{"date": "2026-07-08", "regime": "risk-off"}]
    assert mi.detect_regime_change(history, "risk-on") == "risk-off → risk-on"


def test_no_ping_when_either_side_unknown():
    history = [{"date": "2026-07-08", "regime": "unknown"}]
    assert mi.detect_regime_change(history, "risk-on") is None
    history2 = [{"date": "2026-07-08", "regime": "risk-on"}]
    assert mi.detect_regime_change(history2, "unknown") is None


# ---------- history file round-trip ----------

def test_history_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(mi, "HISTORY_PATH", tmp_path / "hist.json")
    mi.save_history([{"date": "2026-07-08", "regime": "risk-on"}])
    loaded = mi.load_history()
    assert loaded == [{"date": "2026-07-08", "regime": "risk-on"}]


def test_latest_report_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(mi, "LATEST_PATH", tmp_path / "latest.json")
    report = mi.build_report({"SPY": _spy(True)}, {"XLK": _sector_frame(2.0)}, vix_level=13.5)
    mi.save_latest_report(report)
    loaded = mi.load_latest_report()
    assert loaded == report


def test_load_latest_report_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(mi, "LATEST_PATH", tmp_path / "nope.json")
    assert mi.load_latest_report() is None
