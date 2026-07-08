"""Headless session runner — no human in the loop.

Amendment (2026-07-08, see prop-experiment-charter.md): candidates that pass
every charter rule (1% risk, 2R minimum target, position/risk caps) are
placed automatically. This is what lets the experiment run unattended on a
schedule (GitHub Actions) instead of needing someone at the dashboard.

Run with:  python auto_session.py
Exits 0 whether or not anything happened; exits 1 only on a real error, so
CI can tell "boring day" apart from "broken."
"""

from __future__ import annotations

import sys

import data as market
import engine
import journal
import recap as recap_mod
import setups


def run() -> bool:
    """Returns True if the ledger changed (worth committing)."""
    ledger = journal.load_ledger()

    frames = market.fetch_watchlist(ledger["watchlist"])
    if not frames:
        print("No market data returned — no numbers, no trade. Nothing to do.")
        return False

    session_date = market.latest_session_date(frames)
    if any(s["date"] == session_date for s in ledger["sessions"]):
        print(f"Session for {session_date} already logged. Markets close once a day.")
        return False

    bars = market.bars_today(frames)
    closed_today = engine.manage_open_trades(ledger, bars, session_date)
    filled_today, expired = engine.process_pending_fills(ledger, bars, session_date)

    busy = {t["ticker"] for t in ledger["open_trades"]}
    candidates = setups.scan(frames, skip_tickers=busy)

    placed, skipped = [], []
    for c in candidates:
        try:
            order = engine.place_order(
                ledger, ticker=c["ticker"], setup=c["setup"], entry=c["entry"],
                stop=c["stop"], target=c["target"], date=session_date, note=c["reason"])
            placed.append(order)
            print(f"AUTO-PLACED {order['ticker']} {order['setup']}: entry {order['entry']}, "
                  f"stop {order['stop']}, target {order['target']}, {order['shares']} sh")
        except engine.RuleViolation as e:
            journal.log_skip(ledger, c, session_date, reason=f"blocked by charter: {e}")
            skipped.append(c)
            print(f"SKIPPED {c['ticker']}: {e}")

    session_entry = recap_mod.build_recap(
        date=session_date, regime=market.regime_summary(frames),
        closed_today=closed_today, filled_today=filled_today, placed=placed,
        skipped=skipped, candidates_found=len(candidates),
        watchlist_vol_pct=market.watchlist_volatility_pct(frames))
    ledger["sessions"].append(session_entry)

    journal.compute_stats(ledger)
    journal.save_ledger(ledger)

    print(f"\nSession {session_date} complete. "
          f"{len(closed_today)} closed, {len(filled_today)} filled, "
          f"{len(placed)} placed, {len(skipped)} skipped.")
    print(f"Balance: ${ledger['account']['balance']:,.2f} | "
          f"Expectancy: {ledger['stats']['expectancy_R']}")
    return True


if __name__ == "__main__":
    try:
        run()
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
