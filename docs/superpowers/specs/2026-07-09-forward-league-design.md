# The Forward League — design spec (2026-07-09, approved)

## What this is

The experiment becomes a nightly tournament. Alongside the charter account,
four challenger accounts — each a different ruleset — trade the same watchlist
forward every session. Backtests suggest; the league decides forward, on data
nobody has seen. The league table becomes the designated evidence source for
promotion decisions.

## Roster (all simulated $5,000, same watchlist, same −0.05R cost, long-only)

| id | label | difference from charter |
|---|---|---|
| (main ledger) | 👑 Charter | THE experiment — displayed as reference row, never written by league code |
| control | 🥼 Control | no regime filter, no correlation guard (pre-2026-07-09 rules) — the scientific control |
| frontrunner | 📈 Frontrunner | adopts the Practice Lab leaderboard leader (≥30 trades) each session; baseline when none qualifies. Forward-tests "always follow the lab" |
| aggressive | 🔥 Aggressive | 2% risk/trade, max 3 positions, 3R open-risk cap |
| zen | 🧘 Zen | 0.5% risk/trade, max 1 position, 1R cap |

## Architecture

- `league.py` — roster config (in code), challenger ledger creation/loading,
  `run_league_from_frames(frames, date, accounts)` (testable core),
  `run_league()` (fetch once, run all), `summary()` for the dashboard.
- Challenger ledgers live in `league/<id>.json` with the SAME schema as the
  main ledger — every `journal.py` stat function works on them unchanged, and
  `engine.rules_from_ledger` already honors per-ledger risk/caps, so
  aggressive/zen need zero engine changes.
- `setups.scan` gains `guards: bool = True`; `guards=False` (control only)
  skips the regime filter and correlation guard.
- Nightly flow: existing session step, then `python league.py` in the same
  workflow run; all ledgers committed together (no push races).
- Guards: same one-session-per-date and bar-final checks as the main bot,
  per account. A corrupt/missing challenger ledger is recreated fresh
  (challengers are expendable); the charter ledger is never auto-created or
  written by league code.

## Dashboard

New 🏆 League tab: table ranked by expectancy (charter row crowned),
overlaid equity curves (one line per account), per-account expander with
recent sessions. Bot status strip mentions the league.

## Charter

One dated amendment: the league exists outside the experiment; its forward
results are the designated evidence source for future promotion decisions.

## Tests

Challenger creation applies rule overrides; control bypasses guards while a
guarded twin skips; frontrunner pins the current lab leader (and falls back
to baseline); full synthetic-frames league session; idempotence per date;
charter ledger byte-identical after any league run.

## Non-goals

No shorts, no intraday, no real money (charter hard lines). No auto-promotion:
league evidence feeds a human charter-amendment decision, same as practice.
