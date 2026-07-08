# Backtest Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a historical backtest of the two charter setups against the current watchlist, reusing `engine.py`/`journal.py`/`setups.py` unchanged, surfaced as a new read-only section in the Streamlit dashboard.

**Architecture:** A day-by-day simulation loop (`backtest.py`) walks the full available history of the watchlist, calling the exact same `engine.manage_open_trades` / `engine.process_pending_fills` / `engine.place_order` functions the live bot uses, against a throwaway in-memory ledger. `journal.py`'s stats functions already operate generically on any ledger dict, so no changes are needed there.

**Tech Stack:** Python 3.11+, pandas, yfinance, Streamlit, pytest (all already in the project).

## Global Constraints

- Never write to `prop-experiment-ledger.json` from any backtest code path — it must use a fully separate in-memory ledger dict (see `docs/superpowers/specs/2026-07-08-backtest-design.md`, "Non-goals").
- Daily loop order must be `manage_open_trades` then `process_pending_fills` then `setups.scan` then auto-place — matching `auto_session.py`'s actual order exactly (see spec's corrected Data Flow section).
- The backtest UI must display the survivorship/hindsight-bias caveat caption; do not omit it.
- No new dependencies beyond what's already in `requirements.txt`.

---

### Task 1: Add a `period` parameter to `data.fetch_watchlist`

The live bot only needs ~18 months of history (`data.py`'s `LOOKBACK = "18mo"`), but the backtest needs the maximum history yfinance has (often 10-30+ years). This task makes the lookback period configurable without changing live behavior.

**Files:**
- Modify: `data.py:1-30` (the `LOOKBACK` constant and `fetch_watchlist` function)
- Test: `tests/test_data_period.py` (new file)

**Interfaces:**
- Produces: `fetch_watchlist(tickers: list[str], period: str = LOOKBACK) -> dict[str, pd.DataFrame]` — same return shape as before, callers that don't pass `period` get identical behavior to today.

- [ ] **Step 1: Write the failing test**

Create `tests/test_data_period.py`:

```python
"""fetch_watchlist must accept a period override without changing the default."""

import inspect

import data as market


def test_fetch_watchlist_accepts_period_override():
    sig = inspect.signature(market.fetch_watchlist)
    assert "period" in sig.parameters
    assert sig.parameters["period"].default == market.LOOKBACK


def test_fetch_watchlist_default_unchanged():
    # Calling with just tickers must still work exactly as before (default period).
    sig = inspect.signature(market.fetch_watchlist)
    assert sig.parameters["tickers"].default is inspect.Parameter.empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_data_period.py -v`
Expected: FAIL — `fetch_watchlist()` has no `period` parameter yet.

- [ ] **Step 3: Modify `data.py`**

In `data.py`, change the `fetch_watchlist` signature and its use of `LOOKBACK`:

```python
def fetch_watchlist(tickers: list[str], period: str = LOOKBACK) -> dict[str, pd.DataFrame]:
    """Fetch daily OHLCV for each ticker; missing/failed tickers are omitted.

    `period` defaults to the live bot's 18-month window; pass "max" for a
    backtest that wants the fullest history yfinance has for each ticker.
    """
    frames: dict[str, pd.DataFrame] = {}
    data = yf.download(tickers, period=period, interval="1d",
                       group_by="ticker", auto_adjust=True, progress=False)
    for t in tickers:
        try:
            df = data[t] if len(tickers) > 1 else data
        except KeyError:
            continue
        df = df.dropna(subset=["Close"])
        if len(df) < 60:  # not enough history to trust the 50 SMA
            continue
        frames[t] = add_indicators(df)
    return frames
```

(Only the function signature's first line and the `data = yf.download(...)` line change — `period=LOOKBACK` becomes `period=period`. Nothing else in `data.py` changes.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_data_period.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full existing suite to confirm nothing broke**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all previously-passing tests (21+2) still pass — this change is additive and backward-compatible.

- [ ] **Step 6: Commit**

```bash
cd "/Users/abhikhaira/car deals/prop-trader"
git add data.py tests/test_data_period.py
git commit -m "Add period override to fetch_watchlist for backtest history depth"
```

---

### Task 2: Core backtest simulation loop

**Files:**
- Create: `backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `data.fetch_watchlist(tickers, period="max")`, `data.add_indicators` (already applied inside `fetch_watchlist`), `engine.manage_open_trades(ledger, bars, date)`, `engine.process_pending_fills(ledger, bars, date)`, `engine.place_order(ledger, *, ticker, setup, entry, stop, target, date, note="")`, `engine.RuleViolation`, `engine.RISK_PER_TRADE_PCT`, `engine.COST_PER_TRADE_R`, `engine.MAX_OPEN_POSITIONS`, `engine.MAX_OPEN_RISK_R`, `setups.scan(frames, skip_tickers=set())`, `journal.compute_stats(ledger)`, `journal.log_skip(ledger, candidate, date, reason="")`
- Produces: `backtest.run_backtest(watchlist: list[str], starting_balance: float = 5000.0) -> dict` — returns a ledger-shaped dict (same shape as `journal.load_ledger()`'s return value: keys `account`, `rules`, `watchlist`, `stats`, `open_trades`, `pending_orders`, `closed_trades`, `sessions`, `skipped_candidates`) that every `journal.py` stats function accepts unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_backtest.py`:

```python
"""Backtest simulation tests. Uses small synthetic OHLCV data — never hits
the network — so these run fast and deterministically."""

import pandas as pd
import pytest

import backtest
import data as market
import engine


def _uptrend_pullback_frame(start_price: float = 50.0, days: int = 130) -> pd.DataFrame:
    """A steady uptrend for ~110 days, a 4-day pullback into the SMA zone,
    then a reclaim bar — engineered to trigger setups.ma_pullback on the
    reclaim day, with generous margins so it isn't fragile to rounding."""
    dates = pd.bdate_range("2020-01-01", periods=days)
    closes = []
    price = start_price
    for i in range(days):
        if i < days - 6:
            price += 0.30  # steady climb
        elif i < days - 1:
            price -= 0.60  # 5-day pullback, dips toward the rising SMAs
        else:
            price += 1.20  # reclaim day: strong bounce back up
        closes.append(price)

    df = pd.DataFrame({
        "open": [c - 0.1 for c in closes],
        "high": [c + 0.2 for c in closes],
        "low": [c - 0.3 for c in closes],
        "close": closes,
        "volume": [1_000_000] * days,
    }, index=dates)
    return market.add_indicators(df)


def test_no_lookahead_candidate_fills_after_signal_day_not_on_it():
    df = _uptrend_pullback_frame()
    frames = {"TEST": df}
    ledger = backtest.new_scratch_ledger(["TEST"])
    date_indices = {t: backtest.build_date_index(f) for t, f in frames.items()}
    dates = backtest.trading_dates(frames)

    signal_date = None
    for date in dates:
        bars = backtest.bars_on(frames, date_indices, date)
        engine.manage_open_trades(ledger, bars, date)
        engine.process_pending_fills(ledger, bars, date)
        busy = {t["ticker"] for t in ledger["open_trades"]}
        sliced = backtest.frames_through(frames, date_indices, date)
        import setups
        candidates = setups.scan(sliced, skip_tickers=busy)
        for c in candidates:
            try:
                engine.place_order(ledger, ticker=c["ticker"], setup=c["setup"],
                                   entry=c["entry"], stop=c["stop"],
                                   target=c["target"], date=date, note=c["reason"])
                signal_date = date
            except engine.RuleViolation:
                pass
        if signal_date:
            break

    assert signal_date is not None, "test fixture should trigger at least one candidate"
    order = ledger["pending_orders"][0]
    # The order's entry/stop were computed FROM the signal day's own bar (today's
    # high), so it cannot have filled on the signal day itself — it's placed
    # as pending, good for the next session only.
    assert ledger["open_trades"] == []
    assert order["placed"] == signal_date


def test_position_cap_enforced_across_tickers():
    df_a = _uptrend_pullback_frame(start_price=50.0)
    df_b = _uptrend_pullback_frame(start_price=200.0)
    df_c = _uptrend_pullback_frame(start_price=10.0)
    result = backtest.run_backtest_from_frames(
        {"AAA": df_a, "BBB": df_b, "CCC": df_c}, starting_balance=5000.0)
    # All three fixtures are engineered identically, so all three should signal
    # on the same relative day. Only 2 may ever be open/pending at once.
    committed_at_any_point = engine.open_risk_R(result["open_trades"]) + len(result["pending_orders"])
    assert committed_at_any_point <= engine.MAX_OPEN_RISK_R + 1e-9
    assert len(result["open_trades"]) + len(result["pending_orders"]) <= engine.MAX_OPEN_POSITIONS
    assert len(result["skipped_candidates"]) >= 1  # the 3rd candidate got blocked


def test_run_backtest_returns_ledger_journal_can_read():
    df = _uptrend_pullback_frame()
    result = backtest.run_backtest_from_frames({"TEST": df}, starting_balance=5000.0)
    import journal
    stats = journal.compute_stats(result)
    assert "expectancy_R" in stats
    assert "trades_closed" in stats
    # Whatever's still open at the end of history stays open, not counted as closed.
    assert stats["trades_closed"] == len(result["closed_trades"])


def test_run_backtest_never_touches_real_ledger():
    import journal
    before = journal.LEDGER_PATH.read_bytes()
    df = _uptrend_pullback_frame()
    backtest.run_backtest_from_frames({"TEST": df}, starting_balance=5000.0)
    after = journal.LEDGER_PATH.read_bytes()
    # Byte-for-byte unchanged: backtest.py must never open, read, or write
    # the real ledger file at all.
    assert before == after
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_backtest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backtest'`

- [ ] **Step 3: Write `backtest.py`**

Create `backtest.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_backtest.py -v`
Expected: PASS (4 passed). If `test_no_lookahead_candidate_fills_after_signal_day_not_on_it` or
`test_position_cap_enforced_across_tickers` fail because the synthetic fixture doesn't
actually trigger `ma_pullback` (e.g. the pullback doesn't dip far enough into the SMA
zone, or the reclaim isn't big enough), adjust the constants in `_uptrend_pullback_frame`
(the `0.30`/`0.60`/`1.20` step sizes or the `days` count) — the goal shape is: a long
clean uptrend, a shallow multi-day pullback that touches the 20/50 SMA zone without
closing below it, then a strong one-day reclaim. Re-run after each adjustment.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all tests pass (21 + 2 + 4 = 27 total, plus whatever Task 1 added).

- [ ] **Step 6: Commit**

```bash
cd "/Users/abhikhaira/car deals/prop-trader"
git add backtest.py tests/test_backtest.py
git commit -m "Add backtest simulation module reusing the live engine"
```

---

### Task 3: Live smoke test against real yfinance data

Confirms the full loop runs end-to-end against real market data without errors and produces finite, sane numbers — the synthetic tests in Task 2 prove correctness of the mechanics, this proves it survives contact with messy real data (splits, gaps, missing days).

**Files:**
- Test: `tests/test_backtest_live.py` (new file, marked slow — hits the network)

**Interfaces:**
- Consumes: `backtest.run_backtest(watchlist, starting_balance)`, `journal.compute_stats`

- [ ] **Step 1: Write the test**

Create `tests/test_backtest_live.py`:

```python
"""Live smoke test — hits yfinance for real. Skip in offline environments."""

import math

import pytest

import backtest
import journal


@pytest.mark.slow
def test_backtest_runs_end_to_end_on_real_data():
    result = backtest.run_backtest(["SPY", "QQQ"], starting_balance=5000.0)
    stats = journal.compute_stats(result)

    assert stats["trades_closed"] >= 0
    if stats["expectancy_R"] is not None:
        assert math.isfinite(stats["expectancy_R"])
        assert not math.isnan(stats["expectancy_R"])
    assert result["account"]["balance"] > 0  # never goes to zero or negative
    for t in result["closed_trades"]:
        assert t["shares"] >= 1
        assert t["pnl_usd"] == pytest.approx(t["pnl_usd"])  # no NaN/inf pnl
```

- [ ] **Step 2: Register the `slow` marker**

Create `pytest.ini` in `prop-trader/`:

```ini
[pytest]
markers =
    slow: marks tests that hit the network (deselect with '-m "not slow"')
```

- [ ] **Step 3: Run only this test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_backtest_live.py -v -m slow`
Expected: PASS (1 passed) — takes longer than the other tests since it fetches real data.

- [ ] **Step 4: Confirm the fast suite still excludes it by default if desired**

Run: `.venv/bin/python -m pytest tests/ -v -m "not slow"`
Expected: all non-network tests pass, this one is deselected.

- [ ] **Step 5: Commit**

```bash
cd "/Users/abhikhaira/car deals/prop-trader"
git add tests/test_backtest_live.py pytest.ini
git commit -m "Add live smoke test for backtest against real market data"
```

---

### Task 4: Dashboard integration

**Files:**
- Modify: `app.py` (add a new "Backtest" section; imports at the top)

**Interfaces:**
- Consumes: `backtest.run_backtest(watchlist, starting_balance)`, `journal.compute_stats`, `journal.equity_curve`, `journal.r_distribution`, `journal.expectancy_by_setup` (all already imported/used elsewhere in `app.py`)

- [ ] **Step 1: Add the import**

In `app.py`, alongside the existing imports near the top (`import data as market`, `import engine`, etc.), add:

```python
import backtest
```

- [ ] **Step 2: Add a cached runner function**

Below the existing `fetch` cached function in `app.py` (the one wrapping `market.fetch_watchlist`), add:

```python
@st.cache_data(ttl=3600, show_spinner="Running historical backtest (this can take a bit)…")
def run_cached_backtest(tickers: tuple[str, ...]):
    return backtest.run_backtest(list(tickers))
```

- [ ] **Step 3: Add the Backtest section**

At the end of `app.py`, after the existing "Session recaps" section, add:

```python
st.divider()

# ---------- backtest (hypothetical, read-only, never touches the real ledger) ----------

st.subheader("📊 Backtest — hypothetical, not real results")
st.caption(
    "Runs the exact same engine against this watchlist's full historical daily data. "
    "**Survivorship/hindsight-bias caveat:** these tickers were picked with the benefit "
    "of already knowing how they performed — this shows what THIS watchlist would have "
    "done, not a blind test of the strategy on an unbiased universe."
)

if st.button("▶ Run backtest"):
    st.session_state.backtest_result = run_cached_backtest(tuple(ledger["watchlist"]))

if "backtest_result" in st.session_state:
    bt = st.session_state.backtest_result
    bt_stats = journal.compute_stats(bt)
    bt_exp = bt_stats["expectancy_R"]
    bt_exp_txt = f"{bt_exp:+.3f}R" if bt_exp is not None else "—"
    bt_color = "inherit" if bt_exp is None else ("#0a9950" if bt_exp > 0 else "#d43a3a")

    bl, br = st.columns([2, 3])
    with bl:
        st.markdown('<div class="big-label">Backtest expectancy per trade</div>', unsafe_allow_html=True)
        st.markdown(f'<p class="big-expectancy" style="color:{bt_color}">{bt_exp_txt}</p>', unsafe_allow_html=True)
    with br:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Trades", bt_stats["trades_closed"])
        c2.metric("Win rate", f"{bt_stats['win_rate_pct']}%" if bt_stats["win_rate_pct"] is not None else "—")
        c3.metric("Total R", f"{bt_stats['total_R']:+.2f}")
        c4.metric("Max drawdown", f"{bt_stats['max_drawdown_pct']}%")

    bt_curve = pd.DataFrame(journal.equity_curve(bt), columns=["date", "balance"])
    bt_curve["date"] = pd.to_datetime(bt_curve["date"])
    st.line_chart(bt_curve.set_index("date")["balance"], height=240)

    bt_rs = journal.r_distribution(bt)
    if bt_rs:
        bt_bins = pd.cut(pd.Series(bt_rs), bins=[-5, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 5])
        bt_hist = bt_bins.value_counts().sort_index()
        bt_hist.index = [f"{iv.left:g}…{iv.right:g}" for iv in bt_hist.index]
        st.bar_chart(bt_hist, height=200)

    bt_by_setup = journal.expectancy_by_setup(bt)
    if bt_by_setup:
        st.dataframe(pd.DataFrame(bt_by_setup).T, use_container_width=True)
```

- [ ] **Step 4: Syntax-check the file**

Run: `.venv/bin/python -c "import ast; ast.parse(open('app.py').read())" && echo OK`
Expected: `OK`

- [ ] **Step 5: Manual verification with the preview tool**

Start the Streamlit server (or reuse a running one), click "▶ Run backtest," and confirm:
- A spinner appears while it runs
- The expectancy number, win rate, total R, and max drawdown metrics render
- The equity curve and R-distribution charts render
- The caveat caption is visible above the button
- Clicking "▶ Run today's session" (the live button) still works independently and is unaffected

- [ ] **Step 6: Commit**

```bash
cd "/Users/abhikhaira/car deals/prop-trader"
git add app.py
git commit -m "Add backtest section to the dashboard"
```

---

### Task 5: Final verification and push

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite one more time**

Run: `.venv/bin/python -m pytest tests/ -v -m "not slow"`
Expected: all tests pass.

- [ ] **Step 2: Run the live smoke test once more**

Run: `.venv/bin/python -m pytest tests/test_backtest_live.py -v -m slow`
Expected: PASS.

- [ ] **Step 3: Confirm the real ledger file is untouched**

Run: `cd "/Users/abhikhaira/car deals/prop-trader" && git status --short prop-experiment-ledger.json`
Expected: no output (clean — nothing modified by any of the above test runs).

- [ ] **Step 4: Ask the user before pushing**

Pushing is an explicit-permission action per this project's working agreement — confirm with the user before running `git push`, same as every previous push in this project.
