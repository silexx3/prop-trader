"""Charter math tests. If any of these fail, the app can lie to the ledger."""

import copy

import pytest

import engine
import journal
import recap as recap_mod

RULES = engine.Rules()


def fresh_ledger(balance=5000.0):
    return {
        "started": "2026-07-07",
        "account": {"currency": "USD", "starting_balance": 5000.0,
                    "balance": balance, "open_risk_R": 0},
        "rules": {"risk_per_trade_pct": 1.0, "cost_per_trade_R": 0.05,
                  "max_open_positions": 2, "max_open_risk_R": 2},
        "watchlist": ["SPY"], "stats": {},
        "open_trades": [], "pending_orders": [], "closed_trades": [],
        "sessions": [], "skipped_candidates": [],
    }


# ---------- position sizing ----------

def test_sizing_basic():
    # $5000 * 1% = $50 risk; $2 per-share risk -> 25 shares, exactly $50.
    shares, risk = engine.position_size(5000, entry=100.0, stop=98.0, rules=RULES)
    assert shares == 25
    assert risk == pytest.approx(50.0)


def test_sizing_floors_shares_and_recomputes_risk():
    # $50 / $3 = 16.67 -> 16 shares, risk = $48, never rounds risk UP.
    shares, risk = engine.position_size(5000, entry=100.0, stop=97.0, rules=RULES)
    assert shares == 16
    assert risk == pytest.approx(48.0)


def test_sizing_rejects_stop_above_entry():
    with pytest.raises(engine.RuleViolation):
        engine.position_size(5000, entry=98.0, stop=100.0, rules=RULES)


def test_sizing_rejects_zero_share_position():
    # Stop $100 wide on a $50 budget -> 0 shares -> refuse the trade.
    with pytest.raises(engine.RuleViolation):
        engine.position_size(5000, entry=500.0, stop=400.0, rules=RULES)


# ---------- R math and the cost charge ----------

def place_and_fill(ledger, entry=100.0, stop=98.0, target=104.0):
    order = engine.place_order(ledger, ticker="TEST", setup="ma_pullback",
                               entry=entry, stop=stop, target=target, date="2026-07-08")
    return engine.fill_pending(ledger, order, "2026-07-09")


def test_full_stop_costs_1R_plus_costs():
    ledger = fresh_ledger()
    trade = place_and_fill(ledger)
    closed = engine.close_trade(ledger, trade, exit_price=98.0, exit_date="2026-07-10", reason="stop")
    assert closed["r_multiple"] == pytest.approx(-1.05)
    # 25 shares * -$2 = -$50, plus 0.05 * $50 = $2.50 costs.
    assert closed["pnl_usd"] == pytest.approx(-52.50)
    assert ledger["account"]["balance"] == pytest.approx(4947.50)


def test_target_hit_pays_2R_minus_costs():
    ledger = fresh_ledger()
    trade = place_and_fill(ledger)
    closed = engine.close_trade(ledger, trade, exit_price=104.0, exit_date="2026-07-10", reason="target")
    assert closed["r_multiple"] == pytest.approx(1.95)
    assert closed["pnl_usd"] == pytest.approx(100.0 - 2.50)
    assert ledger["account"]["balance"] == pytest.approx(5097.50)


def test_r_uses_initial_stop_after_trailing():
    ledger = fresh_ledger()
    trade = place_and_fill(ledger)
    engine.move_stop(trade, 101.0)  # trail to breakeven-plus
    closed = engine.close_trade(ledger, trade, exit_price=101.0, exit_date="2026-07-10", reason="stop")
    # R is measured against the INITIAL stop: (101-100)/2 - 0.05 = +0.45R.
    assert closed["r_multiple"] == pytest.approx(0.45)


# ---------- charter rule enforcement ----------

def test_stop_only_moves_toward_trade():
    ledger = fresh_ledger()
    trade = place_and_fill(ledger)
    with pytest.raises(engine.RuleViolation):
        engine.move_stop(trade, 97.0)  # widening = cheating


def test_max_two_positions():
    ledger = fresh_ledger()
    place_and_fill(ledger)
    place_and_fill(ledger)
    with pytest.raises(engine.RuleViolation):
        engine.place_order(ledger, ticker="THIRD", setup="base_breakout",
                           entry=50.0, stop=49.0, target=52.0, date="2026-07-08")


def test_pending_orders_count_toward_position_cap():
    ledger = fresh_ledger()
    place_and_fill(ledger)
    engine.place_order(ledger, ticker="PEND", setup="ma_pullback",
                       entry=50.0, stop=49.0, target=52.0, date="2026-07-08")
    with pytest.raises(engine.RuleViolation):
        engine.place_order(ledger, ticker="THIRD", setup="ma_pullback",
                           entry=50.0, stop=49.0, target=52.0, date="2026-07-08")


def test_breakeven_stop_frees_risk_budget():
    ledger = fresh_ledger()
    t1 = place_and_fill(ledger)
    place_and_fill(ledger)
    assert engine.open_risk_R(ledger["open_trades"]) == pytest.approx(2.0)
    engine.move_stop(t1, 100.0)  # breakeven: risk released
    assert engine.open_risk_R(ledger["open_trades"]) == pytest.approx(1.0)


def test_target_must_be_at_least_2R():
    ledger = fresh_ledger()
    with pytest.raises(engine.RuleViolation):
        engine.place_order(ledger, ticker="TEST", setup="ma_pullback",
                           entry=100.0, stop=98.0, target=103.0, date="2026-07-08")


# ---------- fills: pessimistic same-bar behavior ----------

def test_stop_checked_before_target_same_bar():
    ledger = fresh_ledger()
    place_and_fill(ledger)  # entry 100, stop 98, target 104
    bar = {"TEST": {"open": 100.0, "high": 105.0, "low": 97.0, "close": 104.0}}
    closed = engine.manage_open_trades(ledger, bar, "2026-07-10")
    assert len(closed) == 1
    assert closed[0]["reason"] == "stop"  # pessimistic: stop wins the tie


def test_gap_through_stop_fills_at_open():
    ledger = fresh_ledger()
    place_and_fill(ledger)  # stop 98
    bar = {"TEST": {"open": 95.0, "high": 96.0, "low": 94.0, "close": 95.5}}
    closed = engine.manage_open_trades(ledger, bar, "2026-07-10")
    assert closed[0]["exit"] == pytest.approx(95.0)  # open, not the stop price
    assert closed[0]["r_multiple"] < -1.05  # worse than a clean stop


def test_pending_fills_and_expiry():
    ledger = fresh_ledger()
    engine.place_order(ledger, ticker="FILL", setup="ma_pullback",
                       entry=100.0, stop=98.0, target=104.0, date="2026-07-08")
    engine.place_order(ledger, ticker="MISS", setup="ma_pullback",
                       entry=200.0, stop=196.0, target=208.0, date="2026-07-08")
    bars = {"FILL": {"open": 99.0, "high": 101.0, "low": 98.5, "close": 100.5},
            "MISS": {"open": 190.0, "high": 195.0, "low": 189.0, "close": 194.0}}
    filled, expired = engine.process_pending_fills(ledger, bars, "2026-07-09")
    assert [t["ticker"] for t in filled] == ["FILL"]
    assert [o["ticker"] for o in expired] == ["MISS"]
    assert ledger["pending_orders"] == []


# ---------- journal stats ----------

def test_expectancy_and_stats():
    ledger = fresh_ledger()
    for exit_price, reason in [(104.0, "target"), (98.0, "stop"), (104.0, "target")]:
        trade = place_and_fill(ledger)
        engine.close_trade(ledger, trade, exit_price=exit_price, exit_date="2026-07-10", reason=reason)
    stats = journal.compute_stats(ledger)
    assert stats["trades_closed"] == 3
    assert stats["wins"] == 2 and stats["losses"] == 1
    # (1.95 - 1.05 + 1.95) / 3 = 0.95
    assert stats["expectancy_R"] == pytest.approx(0.95)
    assert stats["total_R"] == pytest.approx(2.85)


def test_equity_curve_and_drawdown():
    ledger = fresh_ledger()
    t = place_and_fill(ledger)
    engine.close_trade(ledger, t, exit_price=98.0, exit_date="2026-07-10", reason="stop")
    curve = journal.equity_curve(ledger)
    assert curve[0][1] == 5000.0
    assert curve[-1][1] == pytest.approx(4947.50)
    assert journal.max_drawdown_pct(ledger) == pytest.approx(1.05, abs=0.01)


def test_ledger_roundtrip(tmp_path):
    ledger = fresh_ledger()
    place_and_fill(ledger)
    path = tmp_path / "ledger.json"
    journal.save_ledger(ledger, path)
    loaded = journal.load_ledger(path)
    assert loaded["open_trades"][0]["ticker"] == "TEST"
    assert loaded["account"]["balance"] == ledger["account"]["balance"]


# ---------- recap ----------

def test_brutality_flat_quiet_day():
    rating, note = recap_mod.brutality_rating(0.0, 0.5)
    assert rating == 0
    assert "Sitting out" in note


def test_brutality_bloodbath():
    rating, _ = recap_mod.brutality_rating(-2.1, 3.0)
    assert rating == 5
