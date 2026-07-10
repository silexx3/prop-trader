"""Ledger read/write and experiment statistics.

The ledger is the same prop-experiment-ledger.json schema the experiment
started with — history is never lost, the app just keeps appending to it.

Ordering note: closed_trades is always appended in true chronological order
(engine.close_trade only ever appends). Every sort in this file keys on
`closed` date ALONE, never a tiebreaker like id — Python's sort is stable,
so same-day trades keep their real append order for free. Adding an id (or
any other) tiebreaker would scramble same-day ordering with an unrelated key.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

LEDGER_PATH = Path(__file__).parent / "prop-experiment-ledger.json"


def load_ledger(path: Path = LEDGER_PATH) -> dict:
    with open(path) as f:
        ledger = json.load(f)
    # Older ledger files may lack keys the engine writes; normalize once here.
    ledger.setdefault("open_trades", [])
    ledger.setdefault("pending_orders", [])
    ledger.setdefault("closed_trades", [])
    ledger.setdefault("sessions", [])
    ledger.setdefault("skipped_candidates", [])
    return ledger


def save_ledger(ledger: dict, path: Path = LEDGER_PATH) -> None:
    """Write atomically, keeping one .bak of the previous state."""
    if path.exists():
        shutil.copy2(path, path.with_suffix(".json.bak"))
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(ledger, f, indent=2)
    tmp.replace(path)


def compute_stats(ledger: dict) -> dict:
    """Recompute the stats block from closed trades. Expectancy is the verdict."""
    closed = ledger["closed_trades"]
    rs = [t["r_multiple"] for t in closed]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]

    stats = {
        "trades_closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100 * len(wins) / len(rs), 1) if rs else None,
        "expectancy_R": round(sum(rs) / len(rs), 3) if rs else None,
        "total_R": round(sum(rs), 3),
        "max_drawdown_pct": max_drawdown_pct(ledger),
    }
    ledger["stats"] = stats
    return stats


def equity_curve(ledger: dict) -> list[tuple[str, float]]:
    """(date, balance) points: start of experiment, then each closed trade."""
    points = [(ledger["started"], ledger["account"]["starting_balance"])]
    for t in sorted(ledger["closed_trades"], key=lambda t: t["closed"]):
        points.append((t["closed"], t["balance_after"]))
    return points


def max_drawdown_pct(ledger: dict) -> float:
    peak = ledger["account"]["starting_balance"]
    max_dd = 0.0
    for _, balance in equity_curve(ledger):
        peak = max(peak, balance)
        max_dd = max(max_dd, (peak - balance) / peak * 100)
    return round(max_dd, 2)


def expectancy_by_setup(ledger: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for t in ledger["closed_trades"]:
        s = out.setdefault(t["setup"], {"trades": 0, "total_R": 0.0, "wins": 0})
        s["trades"] += 1
        s["total_R"] += t["r_multiple"]
        s["wins"] += 1 if t["r_multiple"] > 0 else 0
    for s in out.values():
        s["expectancy_R"] = round(s["total_R"] / s["trades"], 3)
        s["win_rate_pct"] = round(100 * s["wins"] / s["trades"], 1)
        s["total_R"] = round(s["total_R"], 3)
    return out


def r_distribution(ledger: dict) -> list[float]:
    return [t["r_multiple"] for t in ledger["closed_trades"]]


# Two-sided 95% Student-t critical values by degrees of freedom; 1.96 beyond.
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
        8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160,
        14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
        20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
        26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042}


def expectancy_ci(ledger: dict) -> tuple[float, float] | None:
    """95% confidence interval on expectancy (Student-t on the R-multiples).

    None with fewer than 2 trades — one trade has no variance to estimate.
    An interval spanning zero means the data can't yet distinguish edge from
    noise; the dashboard says so in words instead of faking precision.
    """
    rs = [t["r_multiple"] for t in ledger["closed_trades"]]
    n = len(rs)
    if n < 2:
        return None
    mean = sum(rs) / n
    var = sum((r - mean) ** 2 for r in rs) / (n - 1)
    se = (var / n) ** 0.5
    t_crit = _T95.get(n - 1, 1.96)
    return round(mean - t_crit * se, 3), round(mean + t_crit * se, 3)


def rolling_expectancy(ledger: dict, window: int = 20) -> list[tuple[int, float]]:
    """(trade_number, trailing-window expectancy) for each closed trade in
    order. Trade N's point averages the last `window` trades ending at N —
    fewer than `window` trades so far just averages what exists. Shows
    whether performance is improving or decaying, which the single lifetime
    expectancy number can't.
    """
    closed = sorted(ledger["closed_trades"], key=lambda t: t["closed"])
    rs = [t["r_multiple"] for t in closed]
    points = []
    for i in range(len(rs)):
        chunk = rs[max(0, i - window + 1):i + 1]
        points.append((i + 1, round(sum(chunk) / len(chunk), 3)))
    return points


def current_streak(ledger: dict) -> str:
    closed = sorted(ledger["closed_trades"], key=lambda t: t["closed"])
    if not closed:
        return "no closed trades yet"
    streak, kind = 0, None
    for t in reversed(closed):
        this = "W" if t["r_multiple"] > 0 else "L"
        if kind is None:
            kind = this
        if this != kind:
            break
        streak += 1
    return f"{streak}{kind}"


def log_skip(ledger: dict, candidate: dict, date: str, reason: str = "") -> None:
    """Every skip gets logged too — skips are data about discipline."""
    ledger["skipped_candidates"].append({
        "date": date,
        "ticker": candidate["ticker"],
        "setup": candidate["setup"],
        "entry": candidate["entry"],
        "stop": candidate["stop"],
        "reason": reason or "skipped in session review",
    })
