"""Account engine: sizing, fills, R math, and charter rule enforcement.

Every rule here mirrors prop-experiment-charter.md. If the app ever lets you
break a charter rule, that's a bug — this module is where it gets caught.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

# Charter constants (also stored in the ledger's "rules" block; the ledger wins
# if they ever differ, see rules_from_ledger).
RISK_PER_TRADE_PCT = 1.0
COST_PER_TRADE_R = 0.05
MAX_OPEN_POSITIONS = 2
MAX_OPEN_RISK_R = 2.0


@dataclass
class Rules:
    risk_per_trade_pct: float = RISK_PER_TRADE_PCT
    cost_per_trade_R: float = COST_PER_TRADE_R
    max_open_positions: int = MAX_OPEN_POSITIONS
    max_open_risk_R: float = MAX_OPEN_RISK_R


def rules_from_ledger(ledger: dict) -> Rules:
    r = ledger.get("rules", {})
    return Rules(
        risk_per_trade_pct=r.get("risk_per_trade_pct", RISK_PER_TRADE_PCT),
        cost_per_trade_R=r.get("cost_per_trade_R", COST_PER_TRADE_R),
        max_open_positions=r.get("max_open_positions", MAX_OPEN_POSITIONS),
        max_open_risk_R=r.get("max_open_risk_R", MAX_OPEN_RISK_R),
    )


class RuleViolation(Exception):
    """Raised when an action would break a charter rule."""


def position_size(balance: float, entry: float, stop: float, rules: Rules) -> tuple[int, float]:
    """Return (shares, risk_usd). Long-only: entry must be above stop.

    shares = risk_usd / (entry - stop), floored to whole shares; risk_usd is
    then recomputed from the actual share count so 1R means what it says.
    """
    if entry <= stop:
        raise RuleViolation(f"Entry {entry} must be above stop {stop} (long-only swing).")
    risk_budget = balance * rules.risk_per_trade_pct / 100.0
    per_share_risk = entry - stop
    shares = int(risk_budget / per_share_risk)
    if shares < 1:
        raise RuleViolation(
            f"Stop is too wide: risking ${risk_budget:.2f} at ${per_share_risk:.2f}/share buys 0 shares."
        )
    return shares, shares * per_share_risk


def open_risk_R(open_trades: list[dict]) -> float:
    """Sum of remaining risk across open trades, in R.

    A trade whose stop has been moved to breakeven or beyond risks 0R.
    """
    total = 0.0
    for t in open_trades:
        initial_per_share = t["entry"] - t["initial_stop"]
        remaining_per_share = t["entry"] - t["stop"]
        if initial_per_share > 0:
            total += max(0.0, remaining_per_share / initial_per_share)
    return total


def check_can_place(ledger: dict, rules: Optional[Rules] = None) -> None:
    """Raise RuleViolation if placing one more 1R order would break limits.

    Pending orders count as committed risk: an order you've placed can fill
    before you next look at the market.
    """
    rules = rules or rules_from_ledger(ledger)
    committed = len(ledger["open_trades"]) + len(ledger["pending_orders"])
    if committed >= rules.max_open_positions:
        raise RuleViolation(
            f"Max {rules.max_open_positions} positions: {len(ledger['open_trades'])} open "
            f"+ {len(ledger['pending_orders'])} pending already."
        )
    risk_now = open_risk_R(ledger["open_trades"]) + len(ledger["pending_orders"])
    if risk_now + 1.0 > rules.max_open_risk_R + 1e-9:
        raise RuleViolation(
            f"Open risk would exceed {rules.max_open_risk_R}R (currently {risk_now:.2f}R committed)."
        )


def place_order(ledger: dict, *, ticker: str, setup: str, entry: float, stop: float,
                target: float, date: str, note: str = "") -> dict:
    """Validate against the charter and add a pending order (good for next session)."""
    rules = rules_from_ledger(ledger)
    check_can_place(ledger, rules)
    if target < entry + 2 * (entry - stop) - 1e-9:
        raise RuleViolation("Target must be at least 2R from entry (charter minimum).")
    shares, risk_usd = position_size(ledger["account"]["balance"], entry, stop, rules)
    order = {
        "id": uuid.uuid4().hex[:8],
        "ticker": ticker.upper(),
        "setup": setup,
        "entry": round(entry, 4),
        "stop": round(stop, 4),
        "target": round(target, 4),
        "shares": shares,
        "risk_usd": round(risk_usd, 2),
        "placed": date,
        "note": note,
    }
    ledger["pending_orders"].append(order)
    return order


def fill_pending(ledger: dict, order: dict, fill_date: str) -> dict:
    """Convert a pending order into an open trade, filled at the order price."""
    ledger["pending_orders"] = [o for o in ledger["pending_orders"] if o["id"] != order["id"]]
    trade = {
        "id": order["id"],
        "ticker": order["ticker"],
        "setup": order["setup"],
        "entry": order["entry"],
        "stop": order["stop"],
        "initial_stop": order["stop"],
        "target": order["target"],
        "shares": order["shares"],
        "risk_usd": order["risk_usd"],
        "opened": fill_date,
        "note": order.get("note", ""),
    }
    ledger["open_trades"].append(trade)
    return trade


def expire_pending(ledger: dict) -> list[dict]:
    """Orders are good for one session only; clear whatever didn't fill."""
    expired = list(ledger["pending_orders"])
    ledger["pending_orders"] = []
    return expired


def move_stop(trade: dict, new_stop: float) -> None:
    """Stops move only toward the trade (up, for longs). Charter law."""
    if new_stop <= trade["stop"]:
        raise RuleViolation(
            f"{trade['ticker']}: stop can only move up (currently {trade['stop']}, got {new_stop})."
        )
    trade["stop"] = new_stop


def close_trade(ledger: dict, trade: dict, *, exit_price: float, exit_date: str,
                reason: str) -> dict:
    """Close an open trade, charge the cost, update balance, and archive it."""
    rules = rules_from_ledger(ledger)
    per_share_risk = trade["entry"] - trade["initial_stop"]
    raw_r = (exit_price - trade["entry"]) / per_share_risk
    r_after_costs = raw_r - rules.cost_per_trade_R
    pnl = trade["shares"] * (exit_price - trade["entry"]) - rules.cost_per_trade_R * trade["risk_usd"]

    ledger["open_trades"] = [t for t in ledger["open_trades"] if t["id"] != trade["id"]]
    closed = dict(trade)
    closed.update({
        "exit": round(exit_price, 4),
        "closed": exit_date,
        "reason": reason,
        "r_multiple": round(r_after_costs, 3),
        "pnl_usd": round(pnl, 2),
        "balance_after": round(ledger["account"]["balance"] + pnl, 2),
    })
    ledger["account"]["balance"] = closed["balance_after"]
    ledger["closed_trades"].append(closed)
    ledger["account"]["open_risk_R"] = round(open_risk_R(ledger["open_trades"]), 3)
    return closed


def manage_open_trades(ledger: dict, bars_today: dict[str, dict], date: str) -> list[dict]:
    """Check stops and targets against today's high/low. Stop before target on
    the same bar — pessimistic fills. Returns the trades closed today.
    """
    closed = []
    for trade in list(ledger["open_trades"]):
        bar = bars_today.get(trade["ticker"])
        if bar is None:
            continue
        if bar["low"] <= trade["stop"]:
            # A gap through the stop fills at the open, not the stop price.
            exit_price = min(trade["stop"], bar["open"])
            closed.append(close_trade(ledger, trade, exit_price=exit_price,
                                      exit_date=date, reason="stop"))
        elif bar["high"] >= trade["target"]:
            # A gap past the target also fills at the open (in our favor).
            exit_price = max(trade["target"], bar["open"])
            closed.append(close_trade(ledger, trade, exit_price=exit_price,
                                      exit_date=date, reason="target"))
    return closed


def process_pending_fills(ledger: dict, bars_today: dict[str, dict], date: str) -> tuple[list, list]:
    """Fill buy-stop orders whose trigger traded today; expire the rest.

    Returns (filled_trades, expired_orders).
    """
    filled = []
    for order in list(ledger["pending_orders"]):
        bar = bars_today.get(order["ticker"])
        if bar is None:
            continue
        if bar["high"] >= order["entry"]:
            trade = fill_pending(ledger, order, date)
            filled.append(trade)
    expired = expire_pending(ledger)
    ledger["account"]["open_risk_R"] = round(open_risk_R(ledger["open_trades"]), 3)
    return filled, expired
