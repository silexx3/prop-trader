"""Ledger read/write and experiment statistics.

The ledger is the same prop-experiment-ledger.json schema the experiment
started with — history is never lost, the app just keeps appending to it.
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
    for t in sorted(ledger["closed_trades"], key=lambda t: (t["closed"], t.get("id", ""))):
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


def current_streak(ledger: dict) -> str:
    closed = sorted(ledger["closed_trades"], key=lambda t: (t["closed"], t.get("id", "")))
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
