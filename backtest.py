"""Historical backtest of the two charter setups against a watchlist.

Reuses engine.py/journal.py/setups.py unchanged — see
docs/superpowers/specs/2026-07-08-backtest-design.md. Read-only: never
constructs or touches prop-experiment-ledger.json; the ledger this module
builds is a throwaway in-memory dict with the same shape.
"""

from __future__ import annotations

import pandas as pd

import data as market
import engine
import journal
import setups

# Sessions to skip before scanning for candidates: base_breakout's longest
# lookback is a 4-week (20-session) base plus ~55 sessions of avg-volume/SMA
# warmup: 20 + 55 = 75, matching setups.py's own guard. 95 gives margin.
WARMUP_SESSIONS = 95


def new_scratch_ledger(watchlist: list[str], starting_balance: float = 5000.0) -> dict:
    """A ledger-shaped dict, structurally identical to journal.load_ledger()'s
    output, but never read from or written to disk."""
    return {
        "started": "backtest",
        "account": {"currency": "USD", "starting_balance": starting_balance,
                    "balance": starting_balance, "open_risk_R": 0},
        "rules": {"risk_per_trade_pct": engine.RISK_PER_TRADE_PCT,
                  "cost_per_trade_R": engine.COST_PER_TRADE_R,
                  "max_open_positions": engine.MAX_OPEN_POSITIONS,
                  "max_open_risk_R": engine.MAX_OPEN_RISK_R},
        "watchlist": list(watchlist),
        "stats": {},
        "open_trades": [], "pending_orders": [], "closed_trades": [],
        "sessions": [], "skipped_candidates": [],
    }


def build_date_index(df: pd.DataFrame) -> dict[str, int]:
    """date-string -> positional row index, computed once per ticker so the
    day-by-day loop below never re-scans a ticker's full date range."""
    return {str(idx.date()): pos for pos, idx in enumerate(df.index)}


def trading_dates(frames: dict[str, pd.DataFrame]) -> list[str]:
    """Union of all tickers' trading dates, sorted ascending, after warmup."""
    all_dates: set[str] = set()
    for df in frames.values():
        all_dates.update(str(d.date()) for d in df.index)
    dates = sorted(all_dates)
    return dates[WARMUP_SESSIONS:] if len(dates) > WARMUP_SESSIONS else []


def _row_to_bar(row) -> dict:
    return {"open": float(row["open"]), "high": float(row["high"]),
            "low": float(row["low"]), "close": float(row["close"])}


def bars_on(frames: dict[str, pd.DataFrame], date_indices: dict[str, dict[str, int]],
            date: str) -> dict[str, dict]:
    """bars-shaped dict (ticker -> OHLC) for one historical date."""
    out = {}
    for ticker, df in frames.items():
        idx = date_indices[ticker].get(date)
        if idx is not None:
            out[ticker] = _row_to_bar(df.iloc[idx])
    return out


def frames_through(frames: dict[str, pd.DataFrame], date_indices: dict[str, dict[str, int]],
                    date: str) -> dict[str, pd.DataFrame]:
    """Each ticker's frame sliced to only include data through `date` — a
    detector called on this can never see a future bar."""
    out = {}
    for ticker, df in frames.items():
        idx = date_indices[ticker].get(date)
        if idx is not None:
            out[ticker] = df.iloc[:idx + 1]
    return out


def run_backtest_from_frames(frames: dict[str, pd.DataFrame], starting_balance: float = 5000.0) -> dict:
    """The simulation loop itself, taking pre-fetched frames. Split out from
    run_backtest() so tests can pass synthetic data without hitting yfinance."""
    ledger = new_scratch_ledger(list(frames.keys()), starting_balance)
    date_indices = {t: build_date_index(df) for t, df in frames.items()}
    dates = trading_dates(frames)

    for date in dates:
        bars = bars_on(frames, date_indices, date)
        if not bars:
            continue
        # Order matches auto_session.py exactly: manage opens, then fills,
        # then scan for new candidates — see the design spec's Data Flow section.
        engine.manage_open_trades(ledger, bars, date)
        engine.process_pending_fills(ledger, bars, date)

        busy = {t["ticker"] for t in ledger["open_trades"]}
        sliced = frames_through(frames, date_indices, date)
        candidates = setups.scan(sliced, skip_tickers=busy)
        for c in candidates:
            try:
                engine.place_order(ledger, ticker=c["ticker"], setup=c["setup"],
                                   entry=c["entry"], stop=c["stop"], target=c["target"],
                                   date=date, note=c["reason"])
            except engine.RuleViolation as e:
                journal.log_skip(ledger, c, date, reason=f"blocked by charter: {e}")

    journal.compute_stats(ledger)
    return ledger


def run_backtest(watchlist: list[str], starting_balance: float = 5000.0) -> dict:
    """Fetch max available history for `watchlist` and simulate the live
    engine day-by-day over it. Never touches the real ledger file."""
    frames = market.fetch_watchlist(watchlist, period="max")
    if not frames:
        raise ValueError("No historical data available for backtest.")
    return run_backtest_from_frames(frames, starting_balance)
