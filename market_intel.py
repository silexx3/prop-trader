"""Market Intelligence — pure-reporting macro layer.

Studies the overall tape: VIX regime, sector rotation, breadth, and a
combined risk-on/off verdict (reusing the exact SPY-vs-50-SMA definition
setups.py already uses for the regime filter — one definition, not two).

Never touches any watchlist, trade, size, or charter rule. Feeds the weekly
digest and pings the phone on regime CHANGES. If a claim here can't be
backed by the data in front of it, it doesn't get made — the "historically
performs better" note is a labeled rule of thumb, not a backtested stat.

Run with:  python market_intel.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

import data as market
from setups import REGIME_TICKER

HISTORY_PATH = Path(__file__).parent / "market-intel-history.json"
LATEST_PATH = Path(__file__).parent / "market-intel-latest.json"

SECTOR_ETFS = {
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
    "XLV": "Health Care", "XLY": "Consumer Discretionary", "XLP": "Consumer Staples",
    "XLI": "Industrials", "XLB": "Materials", "XLU": "Utilities",
    "XLRE": "Real Estate", "XLC": "Communication Services",
}

VIX_CALM, VIX_VOLATILE = 15.0, 25.0

# Plain-English heuristic, not a backtested per-regime statistic — labeled
# as such everywhere it's shown.
REGIME_NOTES = {
    "risk-on": "the swing charter's continuation setups (pullback, breakout) "
               "are generally more favorable in a rising tape",
    "risk-off": "longs face more headwind; the regime filter already stands "
                "the swing bot down on new entries in this state",
}


def vix_band(vix_level: float) -> str:
    if vix_level < VIX_CALM:
        return "calm"
    if vix_level > VIX_VOLATILE:
        return "volatile"
    return "normal"


def breadth_pct(frames: dict[str, pd.DataFrame]) -> float | None:
    """% of tickers closing above their own 50-day SMA. None if no data."""
    above = 0
    counted = 0
    for df in frames.values():
        if pd.isna(df["sma50"].iloc[-1]):
            continue
        counted += 1
        if df["close"].iloc[-1] > df["sma50"].iloc[-1]:
            above += 1
    return round(100 * above / counted, 1) if counted else None


def regime_label(frames: dict[str, pd.DataFrame], vix_level: float | None) -> str:
    """risk-on / risk-off, using the SAME SPY-vs-50-SMA test setups.py's
    regime filter uses — one definition of "regime" across the whole app."""
    spy = frames.get(REGIME_TICKER)
    if spy is None or pd.isna(spy["sma50"].iloc[-1]):
        return "unknown"
    return "risk-off" if spy["close"].iloc[-1] < spy["sma50"].iloc[-1] else "risk-on"


def sector_rotation(frames: dict[str, pd.DataFrame]) -> list[dict]:
    """5-day return per sector ETF, ranked highest first."""
    rows = []
    for ticker, sector in SECTOR_ETFS.items():
        df = frames.get(ticker)
        if df is None or len(df) < 6:
            continue
        ret = (df["close"].iloc[-1] / df["close"].iloc[-6] - 1) * 100
        rows.append({"ticker": ticker, "sector": sector, "return_5d_pct": round(ret, 2)})
    rows.sort(key=lambda r: r["return_5d_pct"], reverse=True)
    return rows


def build_report(watchlist_frames: dict[str, pd.DataFrame],
                 sector_frames: dict[str, pd.DataFrame],
                 vix_level: float | None, now: dt.date | None = None) -> dict:
    """Pure function over already-fetched data — testable without network."""
    now = now or dt.date.today()
    regime = regime_label(watchlist_frames, vix_level)
    return {
        "date": now.isoformat(),
        "regime": regime,
        "regime_note": REGIME_NOTES.get(regime, ""),
        "vix": vix_level,
        "vix_band": vix_band(vix_level) if vix_level is not None else "unknown",
        "breadth_pct": breadth_pct(watchlist_frames),
        "sectors": sector_rotation(sector_frames),
    }


def load_history() -> list[dict]:
    if HISTORY_PATH.exists():
        return json.loads(HISTORY_PATH.read_text())
    return []


def save_history(history: list[dict]) -> None:
    tmp = HISTORY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(history, indent=2))
    tmp.replace(HISTORY_PATH)


def save_latest_report(report: dict) -> None:
    """Full snapshot (VIX, breadth, sectors) for the dashboard — HISTORY_PATH
    only keeps the lightweight regime timeline needed for change detection."""
    tmp = LATEST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=2))
    tmp.replace(LATEST_PATH)


def load_latest_report() -> dict | None:
    if LATEST_PATH.exists():
        return json.loads(LATEST_PATH.read_text())
    return None


def detect_regime_change(history: list[dict], today_regime: str) -> str | None:
    """None on the first run, on repeats, or on 'unknown' either side —
    only a real risk-on<->risk-off flip is worth a ping."""
    if not history:
        return None
    last = history[-1]["regime"]
    if last == today_regime or "unknown" in (last, today_regime):
        return None
    return f"{last} → {today_regime}"


def run_market_intel() -> dict | None:
    import journal
    from day_session import load_day_ledger

    swing_watchlist = journal.load_ledger()["watchlist"]
    day_watchlist = load_day_ledger()["watchlist"]
    all_tickers = sorted(set(swing_watchlist) | set(day_watchlist) | {"SPY"})

    watchlist_frames = market.fetch_watchlist(all_tickers)
    if not watchlist_frames:
        print("No market data — market intel sits out.")
        return None
    sector_frames = market.fetch_watchlist(list(SECTOR_ETFS.keys()))
    vix_frames = market.fetch_watchlist(["^VIX"])
    vix_level = float(vix_frames["^VIX"]["close"].iloc[-1]) if "^VIX" in vix_frames else None

    report = build_report(watchlist_frames, sector_frames, vix_level)
    history = load_history()
    change = detect_regime_change(history, report["regime"])
    history.append({"date": report["date"], "regime": report["regime"]})
    save_history(history)
    save_latest_report(report)

    print(f"Market intel {report['date']}: regime={report['regime']} "
          f"vix={report['vix']} ({report['vix_band']}) breadth={report['breadth_pct']}%")
    if change:
        import notify
        notify.send(f"Regime flip: {change}",
                    f"{report['regime_note']}. VIX {report['vix']} ({report['vix_band']}), "
                    f"breadth {report['breadth_pct']}%.",
                    tags=["warning"])
    return report


if __name__ == "__main__":
    try:
        run_market_intel()
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
