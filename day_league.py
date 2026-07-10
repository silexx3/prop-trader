"""The Day League — four day-trading personalities on the same tape.

Every night, right after the main day replay, each personality account
replays the identical 5-minute session under its own behavior knobs. Same
proven pattern as the swing league: expendable challenger ledgers in
day-league/, same schema everywhere, the charter day account is never
written by this code, and promotion of any personality trait into the day
charter stays a human amendment decision.

Run with:  python day_league.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import data as market
import day_session
import intraday
import journal

DAY_LEAGUE_DIR = Path(__file__).parent / "day-league"
STARTING_BALANCE = 5000.0

PERSONALITIES = [
    {"id": "shark", "label": "🦈 Shark",
     "desc": "The risky one: 2% risk, 3 at once, 5 entries a day, tolerates chasing to 0.35R. "
             "Eats volatility — or bleeds out on costs. We'll know soon.",
     "rules": {"risk_per_trade_pct": 2.0, "max_open_positions": 3, "max_open_risk_R": 3.0},
     "config": {"max_entries": 5, "max_chase_r": 0.35}},
    {"id": "turtle", "label": "🐢 Turtle",
     "desc": "The patient one: 0.5% risk, one trade a day, and never enters during the first "
             "hour — lets the open shake out the amateurs first.",
     "rules": {"risk_per_trade_pct": 0.5, "max_open_positions": 1, "max_open_risk_R": 1.0},
     "config": {"max_entries": 1, "earliest_bar": 12}},
    {"id": "owl", "label": "🦉 Owl",
     "desc": "The right-opportunity one: normal size, but only pulls the trigger while SPY "
             "is above its VWAP at that exact moment — demands a market tailwind.",
     "rules": {"risk_per_trade_pct": 1.0, "max_open_positions": 2, "max_open_risk_R": 2.0},
     "config": {"max_entries": 2, "require_spy_above_vwap": True}},
    {"id": "rabbit", "label": "🐇 Rabbit",
     "desc": "The trades-more one: smaller size (0.75%) but looser filters — accepts wider "
             "opening ranges and a lighter volume bar. Frequency: edge or churn?",
     "rules": {"risk_per_trade_pct": 0.75, "max_open_positions": 2, "max_open_risk_R": 2.0},
     "config": {"max_entries": 5,
                "variant": {"orb_long": {"vol_mult": 1.0, "max_range_pct": 2.5}}}},
]


def _ledger_path(pid: str) -> Path:
    return DAY_LEAGUE_DIR / f"{pid}.json"


def new_personality_ledger(p: dict, started: str) -> dict:
    ledger = day_session.new_day_ledger()
    ledger["experiment"] = f"Day League personality — {p['id']}"
    ledger["started"] = started
    ledger["rules"].update(p["rules"])
    ledger["rules"]["personality"] = p["id"]
    return ledger


def load_personality(p: dict, started: str) -> dict:
    path = _ledger_path(p["id"])
    if path.exists():
        try:
            return journal.load_ledger(path)
        except (json.JSONDecodeError, KeyError):
            pass  # expendable: corrupt challenger restarts fresh
    return new_personality_ledger(p, started)


def run_day_league_from_frames(frames: dict, date: str,
                               personalities: list[dict] | None = None) -> list[dict]:
    """One league night on pre-fetched bars. Idempotent per account/date."""
    DAY_LEAGUE_DIR.mkdir(exist_ok=True)
    personalities = personalities if personalities is not None else PERSONALITIES
    outcomes = []
    for p in personalities:
        ledger = load_personality(p, started=date)
        if any(s["date"] == date for s in ledger["sessions"]):
            print(f"[{p['id']}] {date} already replayed.")
            continue
        closed = day_session.replay_day(ledger, frames, date, config=p["config"])
        realized = round(sum(t["r_multiple"] for t in closed), 3)
        actions = ("; ".join(f"{t['ticker']} {t['reason']} {t['r_multiple']:+.2f}R" for t in closed)
                   or "No trades — this personality found nothing worth doing.")
        ledger["sessions"].append({"date": date, "trades": [t["id"] for t in closed],
                                   "realized_R": realized, "actions": actions,
                                   "personality": p["id"]})
        journal.compute_stats(ledger)
        journal.save_ledger(ledger, _ledger_path(p["id"]))
        outcomes.append({"id": p["id"], "label": p["label"], "closed": len(closed),
                         "realized_R": realized,
                         "balance": ledger["account"]["balance"]})
        print(f"[{p['id']}] {date}: {len(closed)} trade(s), {realized:+.2f}R, "
              f"bal ${ledger['account']['balance']:,.2f}")
    return outcomes


def run_day_league() -> bool:
    charter_day = day_session.load_day_ledger()  # read-only: shared watchlist
    frames = intraday.fetch_day_bars(charter_day["watchlist"])
    if not frames:
        print("No intraday bars — the day league sits out.")
        return False
    date = intraday.session_date(frames)
    if not market.bar_is_final(date):
        print(f"{date}'s session isn't complete — the day league waits for the close.")
        return False
    outcomes = run_day_league_from_frames(frames, date)
    if outcomes and any(o["closed"] for o in outcomes):
        import notify
        notify.send(f"Day League {date}",
                    "; ".join(f"{o['label']} {o['realized_R']:+.2f}R" for o in outcomes),
                    tags=["zap", "trophy"])
    return bool(outcomes)


def summary() -> list[dict]:
    """Standings rows, main day account first as the reference."""
    rows = []
    charter = day_session.load_day_ledger()
    stats = journal.compute_stats(charter)
    rows.append({"account": "👑 Day charter", "desc": "The day lane's verdict account",
                 "balance": charter["account"]["balance"], **stats, "_ledger": charter})
    for p in PERSONALITIES:
        path = _ledger_path(p["id"])
        if not path.exists():
            continue
        ledger = journal.load_ledger(path)
        stats = journal.compute_stats(ledger)
        rows.append({"account": p["label"], "desc": p["desc"],
                     "balance": ledger["account"]["balance"], **stats, "_ledger": ledger})
    rows.sort(key=lambda r: (r["expectancy_R"] is not None, r["expectancy_R"] or 0), reverse=True)
    return rows


if __name__ == "__main__":
    try:
        run_day_league()
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
