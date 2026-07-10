# Day League + trade-more — design spec (2026-07-10, approved)

## Day League

Four personality accounts (own $5k each, `day-league/<id>.json`, same ledger
schema) replay the same 5-minute tape nightly after the main day session:

| id | label | personality knobs |
|---|---|---|
| shark | 🦈 Shark | 2% risk, 3 concurrent, 5 entries/day, chase tolerance 0.35R |
| turtle | 🐢 Turtle | 0.5% risk, 1 concurrent, 1 entry/day, no entries before bar 12 (first hour) |
| owl | 🦉 Owl | 1% risk, 2 concurrent, 2 entries/day, only enters while SPY > its VWAP at that bar |
| rabbit | 🐇 Rabbit | 0.75% risk, 2 concurrent, 5 entries/day, looser detectors (vol_mult 1.0, max_range_pct 2.5) |

Mechanics: `day_session.replay_day` gains a `config` dict (max_entries,
earliest_bar, max_chase_r, require_spy_above_vwap, variant) with defaults
exactly matching current charter behavior; concurrency and risk come from
each ledger's own rules block (engine already honors them). `day_setups.
scan_day` gains the same per-detector `variant` kwargs pattern as the swing
scan. `day_league.py` mirrors `league.py`: expendable challenger ledgers,
charter day ledger never written, idempotent per date, one workflow step
after the main day replay, one commit.

## Trade more (charter day lane, dated amendment)

- Day watchlist 6 → 10: add TSLA, META, AMZN, GOOGL (deep-liquidity names).
- Max entries per day 3 → 4. Concurrency (2) and risk (1%) unchanged.

## Dashboard

Day desk tab gains a Day League section: roster personality cards, standings
table with 95% CI column, equity race chart. Swing League tab's roster gets
the same personality-card treatment. Bot status reports the full account
census. Nightly notification includes the day league.

## Tests

Turtle takes no entry before bar 12; Owl skips when SPY under VWAP and
enters when above; Shark honors 5-entry cap and 0.35R chase; Rabbit's looser
variant yields ≥ baseline's trade count on a marginal synthetic tape;
charter day ledger byte-identical after a day-league run; per-date
idempotence; defaults-config replay behaves exactly as before (regression).
