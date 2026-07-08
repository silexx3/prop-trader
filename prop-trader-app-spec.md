# Prop Trader — build spec for Claude Code

Hand this file to Claude Code in a new project folder, along with `prop-experiment-charter.md` and `prop-experiment-ledger.json`. Say: "Read all three files, then build Phase 1."

## What this is

A local, simulation-only paper-trading app that continues an existing experiment: a $5,000 simulated prop account trading swing setups on real market data, with every trade journaled and every session recapped. The experiment's rules live in the charter and are law — the app enforces them instead of trusting willpower.

**Non-goals (hard lines):** No brokerage connections, no API keys to real accounts, no order routing, no real money — ever, in any phase. This is a training and measurement tool. Live trading is out of scope (and 18+).

## Continuity

Import the existing `prop-experiment-ledger.json` as the starting state (balance, rules, session history). The app must read and write the same schema so history is never lost. Keep JSON as storage for Phase 1–2; migrate to SQLite only if it gets slow.

## Recommended stack

Python 3.11+, `yfinance` for daily OHLCV data (free, EOD/delayed — fine for swing, never for scalping), `pandas` for the math, **Streamlit** for the GUI (fastest path to a clean dashboard a beginner can read and modify). Plain functions over classes where possible; every module small enough to read in one sitting.

## Modules

- `engine.py` — account state, position sizing (`shares = risk_usd / (entry - stop)`), fill simulation at order price, the −0.05R cost charge per trade, R-multiple math, rule enforcement (1% risk, max 2 open positions, 2R max open risk, stops move only toward the trade).
- `data.py` — fetch daily OHLCV for the watchlist, compute 20/50-day SMAs, swing highs/lows, 20-day average volume, and "distance from 52-week high" (for base detection).
- `setups.py` — two detectors, exactly per the charter:
  - `ma_pullback`: uptrend (rising 20 & 50 SMA, price above both a month ago), pullback into the 20/50 zone, entry = reclaim of prior day's high, stop = below pullback low, target = 2R minimum.
  - `base_breakout`: ≥4 weeks of tight range within ~10% of highs, entry = break of range high on volume above 1.5× average, stop = below base low or last swing low (whichever risks less), target = 2R minimum.
  - Detectors emit *candidate orders*, never auto-execute; the human confirms in the GUI ("place / skip"), and every skip gets logged too.
- `journal.py` — read/write ledger; compute stats: expectancy (R after costs), win rate, total R, max drawdown, R-distribution histogram data, expectancy by setup, current streak.
- `recap.py` — end-of-session recap generator: what triggered, what filled, what stopped, regime summary (SPY/QQQ vs their 20/50 SMAs), brutality rating 0–5 (from realized R + watchlist volatility), and lessons (template-based in Phase 1; optionally rewritten via an LLM later).
- `app.py` — Streamlit dashboard: equity curve, scoreboard (balance, trades, win rate, expectancy — with expectancy visually biggest, it's the verdict metric), open positions and pending orders with their R status, R-distribution chart, session recap feed, and one button: **Run today's session**.

## The daily session flow (what the button does)

1. Update data for watchlist (SPY, QQQ, NVDA, AAPL, MSFT, AMD — editable in GUI).
2. Manage open trades first: check stops/targets against today's high/low (stop checked before target on the same bar — pessimistic fills).
3. Run detectors, show candidate orders with computed size, stop, target, and R.
4. Human confirms place/skip. Placed orders become pending (good for next session).
5. Write session entry + recap to ledger; refresh dashboard.

## Build phases (one Claude Code session each — read the code it writes)

1. **Engine + journal, CLI only.** Load ledger, place a fake trade by hand, close it, see expectancy math work. Unit tests for sizing, R math, and the cost charge.
2. **Data + detectors.** Fetch real data, print today's candidates with full numbers. Sanity-check by eye against a chart before trusting.
3. **Streamlit dashboard.** Scoreboard, equity curve, session button, confirm/skip flow.
4. **Recap generator + polish.** Recap templates, R-histogram, expectancy-by-setup, CSV export of the ledger.

## Prompting tips for Claude Code

Build one phase per session and run the tests before moving on. When something breaks, paste the actual error, not a description of it. Ask Claude Code to explain any block you can't read yet — the app is the homework, understanding it is the grade. Keep the charter open; if the app ever lets you break a charter rule, that's a bug, file it like one.

## Definition of done for the experiment

100 confirmed trades or 6 months. The dashboard's expectancy number — not the win rate, not the balance on a good week — settles the original bet.
