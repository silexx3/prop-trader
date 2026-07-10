# The day-trading lane — charter

A second prop experiment alongside the swing charter: a simulated $5,000
account day-trading US large caps on real 5-minute bars. Same bet, faster
clock: does the system produce positive expectancy after costs?

## How it runs (and the honesty clause)

Free intraday data is delayed — so this lane runs as an **after-close replay**
of the completed session, every weekday at 21:30 UTC alongside the swing bot.
Real bars, real setups, pessimistic fills; never live-streaming execution.
Upgrading to near-live execution requires a real-time feed (e.g. Alpaca keys)
and is out of scope until deliberately added here by amendment.

## Account and risk rules

Starting balance: $5,000 (simulated — no real money anywhere, ever).
Risk per trade: 1% of current balance; shares = risk ÷ (entry − stop).
Costs: −0.05R per trade. Max 2 concurrent positions; max 3 entries per day.
**Flat by close, always** — no overnight holds, no exceptions.

## Allowed setups (long only)

1. **Opening-range breakout** (`orb_long`): first 30 minutes set the range
   (skipped when the range exceeds ~1.5% — that's a news bar, not a base);
   long on the break of the OR high with volume ≥ 1.2× the opening average;
   stop below the OR low; target 2R. A quiet break is not the setup — a
   later bar may confirm with volume, filled at that bar's (worse) price.
2. **VWAP pullback** (`vwap_pullback`): morning strength above VWAP, first
   orderly pullback into VWAP that holds, long on reclaim of the pullback
   bar's high, stop under the dip, target 2R.

No setup = no trade. Pessimistic fills everywhere: stop checked before
target inside every bar; gaps fill at the bar's open, not the wish price.

## Scoring

Verdict metric: expectancy (average R after costs) at 100 trades or
6 months, whichever first — same standard as the swing charter. Ledger:
`day-trading-ledger.json`, same schema, every trade and skip logged.

Started July 9, 2026. This is a learning experiment, not financial advice,
and none of it is real money.

## Amendments

**2026-07-10 — chase guard.** An entry whose fill would be more than 0.25R
past the trigger (gap-open beyond the entry price) is skipped and logged —
chasing a gap is not taking the setup. Evidence: on 2026-07-09, NVDA's
vwap_pullback filled so far past its trigger that reaching the planned
target still banked −0.15R. This also bounds the volume-confirmation rule:
a later bar may confirm a weak break with volume, but only at a price
within 0.25R of the original trigger.
