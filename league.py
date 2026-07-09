"""The Forward League — a nightly tournament of rulesets.

Four challenger accounts trade the same watchlist forward alongside the
charter account, each under a different ruleset. Backtests suggest; the
league decides forward, on data nobody has seen. See
docs/superpowers/specs/2026-07-09-forward-league-design.md.

Hard lines: league code never writes the charter ledger
(prop-experiment-ledger.json) — challengers live in league/<id>.json.
Challenger ledgers are expendable (recreated fresh if corrupt); the charter
ledger is sacred and only displayed. No auto-promotion: league evidence
feeds a human charter-amendment decision.

Run with:  python league.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import data as market
import engine
import journal
import practice
import recap as recap_mod
import setups

LEAGUE_DIR = Path(__file__).parent / "league"
STARTING_BALANCE = 5000.0
FRONTRUNNER_MIN_TRADES = 30  # lab leader needs this much sample to be adopted

ACCOUNTS = [
    {"id": "control", "label": "🥼 Control",
     "desc": "Pre-2026-07-09 rules: no regime filter, no correlation guard. The scientific control.",
     "rules": {}, "guards": False, "variant_source": "baseline"},
    {"id": "frontrunner", "label": "📈 Frontrunner",
     "desc": "Adopts the Practice Lab leaderboard leader each session; charter baseline when none qualifies.",
     "rules": {}, "guards": True, "variant_source": "practice_leader"},
    {"id": "aggressive", "label": "🔥 Aggressive",
     "desc": "2% risk per trade, max 3 positions, 3R open-risk cap. Does the edge survive size?",
     "rules": {"risk_per_trade_pct": 2.0, "max_open_positions": 3, "max_open_risk_R": 3.0},
     "guards": True, "variant_source": "baseline"},
    {"id": "zen", "label": "🧘 Zen",
     "desc": "0.5% risk per trade, one position at a time. The patience extreme.",
     "rules": {"risk_per_trade_pct": 0.5, "max_open_positions": 1, "max_open_risk_R": 1.0},
     "guards": True, "variant_source": "baseline"},
]


def _ledger_path(account_id: str) -> Path:
    return LEAGUE_DIR / f"{account_id}.json"


def new_challenger_ledger(account: dict, started: str) -> dict:
    rules = {"risk_per_trade_pct": engine.RISK_PER_TRADE_PCT,
             "cost_per_trade_R": engine.COST_PER_TRADE_R,
             "max_open_positions": engine.MAX_OPEN_POSITIONS,
             "max_open_risk_R": engine.MAX_OPEN_RISK_R}
    rules.update(account["rules"])
    return {
        "experiment": f"Forward League challenger — {account['id']}",
        "started": started,
        "account": {"currency": "USD", "starting_balance": STARTING_BALANCE,
                    "balance": STARTING_BALANCE, "open_risk_R": 0},
        "rules": rules,
        "watchlist": [],  # challengers follow the charter watchlist at runtime
        "stats": {},
        "open_trades": [], "pending_orders": [], "closed_trades": [],
        "sessions": [], "skipped_candidates": [],
    }


def load_challenger(account: dict, started: str) -> dict:
    """Load a challenger ledger; recreate fresh when missing or corrupt.
    Challengers are expendable — the charter ledger is NOT handled here."""
    path = _ledger_path(account["id"])
    if path.exists():
        try:
            return journal.load_ledger(path)
        except (json.JSONDecodeError, KeyError):
            pass  # corrupt challenger: fall through to a fresh start
    return new_challenger_ledger(account, started)


def resolve_variant(account: dict) -> tuple[dict, str]:
    """(detector params, human-readable name) for this account's session."""
    if account["variant_source"] == "practice_leader":
        board = practice.leaderboard()
        leader = next((b for b in board
                       if b["expectancy_R"] is not None
                       and b["trades"] >= FRONTRUNNER_MIN_TRADES
                       and b["variant"] != "charter-baseline"), None)
        if leader:
            params = next((v["params"] for v in practice.VARIANTS
                           if v["name"] == leader["variant"]), {})
            return params, leader["variant"]
    return {}, "charter-baseline"


def run_league_from_frames(frames: dict, date: str, accounts: list[dict] | None = None) -> list[dict]:
    """One league night against pre-fetched frames. Returns per-account
    session entries (empty list entries for accounts already run today)."""
    LEAGUE_DIR.mkdir(exist_ok=True)
    accounts = accounts if accounts is not None else ACCOUNTS
    regime = market.regime_summary(frames)
    vol_pct = market.watchlist_volatility_pct(frames)
    bars = market.bars_today(frames)
    outcomes = []

    for account in accounts:
        ledger = load_challenger(account, started=date)
        if any(s["date"] == date for s in ledger["sessions"]):
            print(f"[{account['id']}] session {date} already logged.")
            continue

        closed_today = engine.manage_open_trades(ledger, bars, date)
        filled_today, _expired = engine.process_pending_fills(ledger, bars, date)

        variant, variant_name = resolve_variant(account)
        busy = {t["ticker"] for t in ledger["open_trades"]}
        candidates = setups.scan(frames, skip_tickers=busy,
                                 variant=variant, guards=account["guards"])

        placed, skipped = [], []
        for c in candidates:
            if c.get("blocked"):
                journal.log_skip(ledger, c, date, reason=c["blocked"])
                skipped.append(c)
                continue
            try:
                placed.append(engine.place_order(
                    ledger, ticker=c["ticker"], setup=c["setup"], entry=c["entry"],
                    stop=c["stop"], target=c["target"], date=date,
                    note=c["reason"], min_volume=c.get("min_volume")))
            except engine.RuleViolation as e:
                journal.log_skip(ledger, c, date, reason=f"blocked by rules: {e}")
                skipped.append(c)

        entry = recap_mod.build_recap(
            date=date, regime=regime, closed_today=closed_today,
            filled_today=filled_today, placed=placed, skipped=skipped,
            candidates_found=len(candidates), watchlist_vol_pct=vol_pct)
        entry["variant"] = variant_name
        ledger["sessions"].append(entry)

        journal.compute_stats(ledger)
        journal.save_ledger(ledger, _ledger_path(account["id"]))
        outcomes.append(entry)
        print(f"[{account['id']}] {date}: {len(closed_today)} closed, "
              f"{len(filled_today)} filled, {len(placed)} placed, "
              f"{len(skipped)} skipped (variant: {variant_name}). "
              f"Balance ${ledger['account']['balance']:,.2f}")
    return outcomes


def run_league() -> bool:
    """Nightly league run: same date/final-bar discipline as the main bot."""
    charter = journal.load_ledger()  # read-only: watchlist reference
    frames = market.fetch_or_cache(charter["watchlist"], period=market.LOOKBACK)
    if not frames:
        print("No data — the league sits out. No numbers, no trade.")
        return False
    date = market.latest_session_date(frames)
    if not market.bar_is_final(date):
        print(f"{date}'s bar is still in progress — the league waits for the close.")
        return False
    outcomes = run_league_from_frames(frames, date)
    print(f"\nLeague night {date} complete: {len(outcomes)} account(s) ran.")
    return bool(outcomes)


def summary() -> list[dict]:
    """League table rows, charter first, for the dashboard."""
    rows = []
    charter = journal.load_ledger()
    stats = journal.compute_stats(charter)
    rows.append({"account": "👑 Charter", "desc": "THE experiment — the verdict account",
                 "balance": charter["account"]["balance"], **stats,
                 "_ledger": charter})
    for account in ACCOUNTS:
        path = _ledger_path(account["id"])
        if not path.exists():
            continue
        ledger = journal.load_ledger(path)
        stats = journal.compute_stats(ledger)
        rows.append({"account": account["label"], "desc": account["desc"],
                     "balance": ledger["account"]["balance"], **stats,
                     "_ledger": ledger})
    # Rank by expectancy (None sorts last), charter stays wherever it earns.
    rows.sort(key=lambda r: (r["expectancy_R"] is not None, r["expectancy_R"] or 0), reverse=True)
    return rows


if __name__ == "__main__":
    try:
        run_league()
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
