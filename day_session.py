"""Day-trading lane: after-close replay of the completed session.

Fetches the day's real 5-minute bars, walks them forward bar-by-bar, trades
the two day setups under the day charter's risk rules, and forces every
position flat by the close — day traders don't hold overnight. Fills are
pessimistic (stop checked before target inside every bar; gaps fill at the
bar's open). Same ledger schema as the swing experiment, so every stat and
chart works unchanged. Simulation only — no real money, ever.

Run with:  python day_session.py
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import engine
import intraday
import journal
from day_setups import scan_day

DAY_LEDGER_PATH = Path(__file__).parent / "day-trading-ledger.json"
STARTING_BALANCE = 5000.0
MAX_CONCURRENT = 2
MAX_ENTRIES_PER_DAY = 3
# Chase guard (amendment 2026-07-10): a fill more than this many R past the
# trigger is chasing a gap, not taking the setup — skip it. Evidence: the
# 2026-07-09 NVDA trade filled so far past its trigger that hitting the
# planned target still banked -0.15R.
MAX_CHASE_R = 0.25


def new_day_ledger() -> dict:
    return {
        "experiment": "Day-trading prop lane — after-close 5m replay",
        "started": dt.date.today().isoformat(),
        "account": {"currency": "USD", "starting_balance": STARTING_BALANCE,
                    "balance": STARTING_BALANCE, "open_risk_R": 0},
        "rules": {"risk_per_trade_pct": 1.0, "cost_per_trade_R": 0.05,
                  "max_open_positions": MAX_CONCURRENT,
                  "max_open_risk_R": float(MAX_CONCURRENT),
                  "max_entries_per_day": MAX_ENTRIES_PER_DAY,
                  "setups_allowed": ["orb_long", "vwap_pullback"],
                  "style": "day trading, 5-minute bars, replayed after the close",
                  "verdict_metric": "expectancy_R_after_costs",
                  "verdict_sample": "100 trades or 6 months"},
        "watchlist": list(intraday.DAY_WATCHLIST),
        "stats": {},
        "open_trades": [], "pending_orders": [], "closed_trades": [],
        "sessions": [], "skipped_candidates": [],
    }


def load_day_ledger() -> dict:
    if DAY_LEDGER_PATH.exists():
        return journal.load_ledger(DAY_LEDGER_PATH)
    return new_day_ledger()


def _close(ledger: dict, trade: dict, exit_price: float, reason: str, date: str) -> dict:
    rules = engine.rules_from_ledger(ledger)
    per_share = trade["entry"] - trade["stop_initial"]
    r = (exit_price - trade["entry"]) / per_share - rules.cost_per_trade_R
    pnl = trade["shares"] * (exit_price - trade["entry"]) - rules.cost_per_trade_R * trade["risk_usd"]
    closed = {**trade, "exit": round(exit_price, 4), "closed": date, "reason": reason,
              "r_multiple": round(r, 3), "pnl_usd": round(pnl, 2),
              "balance_after": round(ledger["account"]["balance"] + pnl, 2)}
    closed.pop("stop_initial", None)
    ledger["account"]["balance"] = closed["balance_after"]
    ledger["closed_trades"].append(closed)
    return closed


def replay_day(ledger: dict, frames: dict, date: str) -> list[dict]:
    """Walk the session forward. Returns the day's closed trades."""
    candidates = scan_day(frames)
    open_trades: list[dict] = []
    closed: list[dict] = []
    entries_taken = 0
    triggered_ids: set[int] = set()
    n_bars = max(len(df) for df in frames.values())
    rules = engine.rules_from_ledger(ledger)

    for k in range(n_bars):
        # 1) manage opens on this bar — stop before target, gaps at bar open.
        for trade in list(open_trades):
            df = frames[trade["ticker"]]
            if k >= len(df) or k <= trade["entry_bar"]:
                continue
            bar = df.iloc[k]
            if bar["low"] <= trade["stop"]:
                open_trades.remove(trade)
                closed.append(_close(ledger, trade, min(trade["stop"], float(bar["open"])),
                                     "stop", date))
            elif bar["high"] >= trade["target"]:
                open_trades.remove(trade)
                closed.append(_close(ledger, trade, max(trade["target"], float(bar["open"])),
                                     "target", date))

        # 2) new entries, caps willing.
        for idx, c in enumerate(candidates):
            if (idx in triggered_ids or c["active_from"] > k
                    or entries_taken >= MAX_ENTRIES_PER_DAY
                    or len(open_trades) >= MAX_CONCURRENT
                    or any(t["ticker"] == c["ticker"] for t in open_trades)):
                continue
            df = frames[c["ticker"]]
            if k >= len(df):
                continue
            bar = df.iloc[k]
            volume_ok = not c["min_volume"] or bar["volume"] >= c["min_volume"]
            if bar["high"] >= c["entry"] and volume_ok:
                fill = max(c["entry"], float(bar["open"]))  # gap over trigger fills worse
                risk_per_share = c["entry"] - c["stop"]
                if fill - c["entry"] > MAX_CHASE_R * risk_per_share:
                    triggered_ids.add(idx)
                    journal.log_skip(ledger, c, date,
                                     reason=f"gapped past trigger ({fill:.2f} vs {c['entry']:.2f}, "
                                            f">{MAX_CHASE_R}R) — chasing is not the setup")
                    continue
                try:
                    shares, risk_usd = engine.position_size(
                        ledger["account"]["balance"], c["entry"], c["stop"], rules)
                except engine.RuleViolation as e:
                    triggered_ids.add(idx)
                    journal.log_skip(ledger, c, date, reason=f"unsizeable: {e}")
                    continue
                open_trades.append({
                    "id": f"{date}-{c['ticker']}-{idx}", "ticker": c["ticker"],
                    "setup": c["setup"], "entry": fill, "stop": c["stop"],
                    "stop_initial": c["stop"], "target": c["target"],
                    "shares": shares, "risk_usd": risk_usd, "opened": date,
                    "entry_bar": k, "note": c["reason"]})
                triggered_ids.add(idx)
                entries_taken += 1

    # 3) flat by close — day traders do not hold overnight, ever.
    for trade in open_trades:
        df = frames[trade["ticker"]]
        closed.append(_close(ledger, trade, float(df["close"].iloc[-1]), "eod_flat", date))
    return closed


def run_day_session() -> bool:
    ledger = load_day_ledger()
    frames = intraday.fetch_day_bars(ledger["watchlist"])
    if not frames:
        print("No intraday bars available — no numbers, no trade.")
        return False
    date = intraday.session_date(frames)
    if any(s["date"] == date for s in ledger["sessions"]):
        print(f"Day session {date} already replayed.")
        return False
    import data as market
    if not market.bar_is_final(date):
        print(f"{date}'s session isn't complete yet — the replay waits for the close.")
        return False

    closed = replay_day(ledger, frames, date)
    realized = round(sum(t["r_multiple"] for t in closed), 3)
    actions = "; ".join(f"{t['ticker']} {t['setup']} → {t['reason']} {t['r_multiple']:+.2f}R"
                        for t in closed) or "No day trades — no setup triggered. Sitting out is a position."
    ledger["sessions"].append({
        "date": date, "trades": [t["id"] for t in closed],
        "realized_R": realized, "actions": actions,
        "lessons": [f"Replayed {len(frames)} tickers on 5-minute bars; "
                    f"{len(closed)} trade(s), {realized:+.2f}R after costs."],
    })
    journal.compute_stats(ledger)
    journal.save_ledger(ledger, DAY_LEDGER_PATH)
    print(f"Day session {date}: {len(closed)} trade(s), {realized:+.2f}R. "
          f"Balance ${ledger['account']['balance']:,.2f}")

    if closed:
        import notify
        notify.send(f"Day lane {date}: {realized:+.2f}R",
                    "; ".join(f"{t['ticker']} {t['reason']} {t['r_multiple']:+.2f}R" for t in closed)
                    + f" · bal ${ledger['account']['balance']:,.2f}",
                    tags=["zap"])
    return True


if __name__ == "__main__":
    try:
        run_day_session()
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
