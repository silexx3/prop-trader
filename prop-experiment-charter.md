# The prop experiment — Abhi vs. the course

The bet: Claude claimed knowledge alone doesn't produce profit. Abhi is testing that claim by giving Claude a simulated $5,000 prop account trading against the real market. Every trade logged, every session recapped, verdict decided by data.

## Account and risk rules

Starting balance: $5,000 (simulated — no real money anywhere in this experiment). Risk per trade: 1% of current balance (~$50 to start), position size = risk ÷ (entry − stop). Costs: −0.05R charged on every trade so paper doesn't flatter. Max 2 open positions; total open risk capped at 2R. Style: swing on daily charts (matches free daily-granularity data; no scalping — data feed can't support it honestly).

## Allowed setups (curriculum only)

1. Pullback: uptrending name (rising 20/50-day averages, higher highs/lows) pulls back to the rising average zone or a prior breakout level and shows a reclaim — entry on the reclaim, stop below the pullback low, first target 2R.
2. Base breakout: multi-week tight consolidation near highs — entry on the break with volume, stop below the base, first target 2R.

No setup = no trade. Sitting out is a position.

## Data integrity rules

Quotes come from free public daily data. If exact levels can't be verified for a ticker on a given day, no new trade in that ticker — "no numbers, no trade." Entries are placed as next-session orders (limit or stop) at stated prices; fills assumed at order price. This overstates fill quality slightly; the 0.05R cost charge is the offset.

## Scoring

The verdict metric is expectancy (average R per trade after costs), judged at 100 trades or 6 months, whichever comes first. Win rate is tracked but is not the verdict — a 40% win rate can be a win, a 70% can be a loss; the ledger decides. Also tracked: max drawdown, R-distribution, expectancy by setup.

## Conduct rules (the ones that kill real traders)

No unlogged trades. No moving stops except toward the trade. No size changes after losses. No new rules mid-experiment without a dated amendment note here. Every session gets a recap: trades and R, technique used, market regime, brutality rating (0–5), lessons.

## How to run it

Say "run the session" on any market day. Claude pulls the day's data, manages open positions, hunts the two setups, logs everything to `prop-experiment-ledger.json`, and writes the recap.

Started July 7, 2026. This is a learning experiment, not financial advice, and none of it is real money.

## Amendments

**2026-07-09 — watchlist expanded with Asia via USD ETFs.** Added EWJ (Japan), FXI (China), EWY (Korea), EWT (Taiwan), INDA (India), EWA (Australia) to the watchlist. Rationale: more names scanning under the exact same two setups and risk rules means more legitimate candidates competing for the same 2 position slots. USD-listed ETFs were chosen over native Asian tickers deliberately: native tickers price in foreign currencies (breaking the USD sizing math) and close at different hours (breaking the single after-close session cadence). Nothing else changes — same setups, same caps, same one-session-per-day rhythm.

**2026-07-09 — Practice Lab (outside the experiment).** A separate research lane (`practice.py`) backtests parameter variants of the two charter setups against randomized historical windows on a scratch $10,000 account, accumulating results across runs in `practice-history.json`. It never touches this experiment's ledger, balance, or parameters. Promoting a practice finding into the live experiment requires a dated amendment here — hindsight-tuned settings are presumed overfit until argued otherwise.

**2026-07-08 — auto-place, no human confirmation.** Candidates that pass every rule above (1% risk sizing, 2R minimum target, max 2 positions, 2R max open risk) are now placed automatically by a scheduled script (`auto_session.py`), with no human place/skip step. This replaces the original "the human confirms in the GUI" line under Allowed setups. Reason: the experiment needed to run unattended (scheduled via GitHub Actions) so it keeps going on days nobody opens the dashboard. Everything else — sizing, stops-only-move-up, skip logging, no unlogged trades — still applies exactly as written; only the human-confirm step is removed. The dashboard remains available for manual runs and always shows what was auto-placed.
