# Market Intelligence — design spec (2026-07-10, approved)

Pure-reporting macro layer. Never touches watchlists, trades, sizing, or any
charter rule — read-only research feeding the digest and a regime-change
phone ping. No new dependency (yfinance covers VIX/sector ETFs already).

## Data — `market_intel.py`

- VIX via `^VIX` (yfinance); regime bands: <15 calm, 15–25 normal, >25 volatile.
- Sector rotation: 11 SPDR sector ETFs (XLK, XLF, XLE, XLV, XLY, XLP, XLI,
  XLB, XLU, XLRE, XLC), 5-day return each, ranked.
- Breadth: % of the union of (swing + day) watchlist tickers closing above
  their own 50-day SMA (reuses `data.add_indicators`, already computed).
- Regime verdict: risk-on/off from SPY vs its 50-SMA (reuses
  `setups._regime_off` logic, not a new definition) + VIX band, combined
  into one label. `build_report(now) -> dict` returns all of the above;
  pure function, testable without network via injected frames/VIX value.

## Change detection + notification

`market_intel_history.json`: appends one entry per run (date, regime label).
`detect_regime_change(history) -> str | None`: non-None when today's regime
differs from the last recorded entry. On change: phone ping (tags
`warning`) with old → new and which direction the swing charter historically
performs better in (simple lookup table, not a claim — clearly labeled
as a rule of thumb, not backtested per-regime stats, to avoid overclaiming).

## Schedule + dashboard

Runs inside the existing nightly workflow (adds ~seconds; same fetch
window), writes `market_intel_history.json`, feeds into `digest.py`'s
weekly report as a new section. New dashboard section: a "🌍 Market
Intel" panel at the top of the Swing desk (below Bot status) — regime
badge, VIX reading, sector bar chart (Altair, consistent with existing
chart style), breadth %.

## Testing

Regime/VIX-band classification at known values; breadth calculation on
synthetic frames; regime-change detection (no history → no ping first run;
same regime twice → no ping; changed regime → ping fires); report is pure
function over injected data (no live network needed in tests); history
file round-trip.

## Non-goals

No new tickers added to any watchlist. No new trading rule. No claim of
predictive backtested performance per regime — the "historically performs
better in X" note is a plain-English heuristic, explicitly labeled as such.
