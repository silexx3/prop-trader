# Backtest module — design spec

Date: 2026-07-08
Status: approved, pending implementation plan

## Context

The prop-trader app (see `prop-experiment-charter.md`) runs a live, fully-automated
paper-trading experiment: `auto_session.py` runs daily via GitHub Actions, scans the
6-ticker watchlist for two setups (`ma_pullback`, `base_breakout`), auto-places
anything that passes the charter's rules, and the verdict is expectancy over 100
trades or 6 months.

This is the first of three planned off-hours "study" features (the other two —
richer LLM-written analysis, and a wider-universe candidate scanner — are separate,
later specs). Backtesting was chosen to build first because it costs nothing extra
to run (no new API keys, no recurring charges — same free GitHub Actions minutes)
and answers the question the whole experiment exists to answer — does the strategy
have edge — without waiting 6 months for enough live trades to accumulate.

## Goal

Given the current watchlist (SPY, QQQ, NVDA, AAPL, MSFT, AMD) and the maximum daily
history yfinance provides (typically 10+ years), simulate what the live engine would
have done, day by day, and report the same stats the live dashboard reports
(expectancy, win rate, max drawdown, R-distribution, expectancy by setup) — so the
user can see a much larger sample of hypothetical trades than the live ledger has
accumulated so far.

## Non-goals

- Not a general-purpose backtesting framework for arbitrary strategies or tickers
  beyond the current watchlist (that's the future "wider universe scanner" spec).
- Not wired into the daily GitHub Actions schedule — this is an on-demand, dashboard
  button action. History doesn't change day to day, so there's no need to re-run it
  automatically.
- Does not touch `prop-experiment-ledger.json` or any live-account state. Fully
  separate, in-memory scratch ledger.
- Not an attempt to remove or correct for survivorship/hindsight bias — the design
  surfaces the bias as a caveat rather than solving it (see Caveats below).

## Architecture

A new module, `backtest.py`, that reuses the existing engine/journal/setups code
directly rather than reimplementing trading logic:

- `engine.manage_open_trades`, `engine.process_pending_fills`, `engine.place_order`,
  `engine.close_trade`, `engine.open_risk_R` — unchanged, called against a scratch
  ledger dict shaped exactly like `prop-experiment-ledger.json`.
- `setups.scan` — unchanged, called with a `frames` dict that's been sliced to "as of
  a given historical date" rather than "as of today."
- `journal.compute_stats`, `journal.equity_curve`, `journal.r_distribution`,
  `journal.expectancy_by_setup` — unchanged; these already operate generically on any
  ledger dict, so they work on the backtest's scratch ledger with zero modification.

This guarantees the backtest can never silently diverge from what the live bot
actually does (same sizing math, same 0.05R cost charge, same stop/target fill
rules, same position/risk caps) — it is mechanically the same engine, replayed
against history instead of live data.

## Data flow

1. Fetch full available daily history for the watchlist (`data.fetch_watchlist`,
   reusing the existing `add_indicators` computation — SMA20/50, avg volume,
   52-week-high distance are already rolling/backward-looking, so no changes needed
   there).
2. Build the union of all trading dates across the watchlist, sorted ascending.
   Skip the initial warm-up window (~95 sessions) where indicators aren't valid yet.
3. Walk forward one calendar date at a time. On each date `d`, in this exact order
   (matches `auto_session.py`'s actual live order exactly, so there is no lookahead
   bias and no divergence from what the live bot does):
   a. `manage_open_trades` — check `d`'s bar against already-open trades, stop before
      target (pessimistic), exactly as live.
   b. `process_pending_fills` — orders placed after `d-1`'s close (good for exactly
      one session) either fill against `d`'s bar or expire tonight. A trade that
      fills today is not itself checked against its stop/target until the next
      day's bar — same simplification the live bot already makes.
   c. `setups.scan` against each ticker's data sliced through `d` (`df.loc[:d]`) —
      this can only see data up to and including today's close, so any candidate it
      finds becomes a pending order good for `d+1`, never for `d` itself.
   d. Auto-place every candidate that passes `engine.place_order`'s rule checks
      (matching the live charter amendment of 2026-07-08 — no human review step);
      log rule-blocked ones the same way `journal.log_skip` does live.
4. At the end of the date range, whatever's still open stays open (unclosed,
   excluded from expectancy — same convention the live ledger uses for open trades).
5. Return a ledger-shaped dict; the caller (dashboard) runs the existing `journal.py`
   stats functions on it.

## Caveats (surfaced in the UI, not hidden)

- **Survivorship/hindsight bias**: the current watchlist was chosen with the
  benefit of already knowing NVDA/AAPL/MSFT/AMD did well over the backtest window.
  This is a test of "would this specific watchlist have worked," not a blind
  strategy test. A visible caption near the backtest numbers states this plainly.
- Adjusted close (splits/dividends) is used via yfinance's `auto_adjust=True`,
  consistent with what the live engine already assumes.

## Dashboard integration

A new "Backtest" section in `app.py`, below the live scoreboard:

- Its own "▶ Run backtest" button — entirely separate from the live "Run today's
  session" button, never reads or writes `prop-experiment-ledger.json`.
- Cached (`st.cache_data`) so repeated views don't re-fetch/re-simulate.
- Same visual language as the live scoreboard (big expectancy number, win rate,
  total trades, max drawdown, equity curve, R-distribution, expectancy-by-setup
  table) — clearly labeled "BACKTEST (hypothetical — see caveat)" so it's never
  confused with the real, live ledger numbers.

## Testing

- Unit tests with small hand-crafted synthetic price series (not real market data):
  - A candidate detected on day `d` never fills before day `d+1` (no lookahead).
  - The 2-position/2R caps are enforced across tickers sharing one scratch account
    (e.g., if two tickers trigger candidates on the same day but only one slot is
    free, only one gets placed).
  - Resulting stats match hand-computed expectancy for a small scripted sequence
    of wins/losses.
- One live smoke test against real yfinance data (same pattern already used for the
  live detectors) confirming the full loop runs end-to-end without errors and
  produces plausible, finite numbers (no NaN expectancy, no negative share counts).

## Open questions

None — all resolved during brainstorming. Ready for implementation planning.
