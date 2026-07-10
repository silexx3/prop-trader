# Quality-of-Life Quartet — design spec (2026-07-10, approved)

Four additions, built in this order (later ones consume earlier ones):

## 1. Phone notifications — `notify.py`

ntfy.sh (free, no account): `send(title, message, priority="default", tags=None)`
POSTs to `https://ntfy.sh/<topic>`. Topic = random hex string committed in
`notify.py`, overridable via `NTFY_TOPIC` env var (the upgrade path to a
GitHub secret if the public topic ever attracts spam — repo is public, topic
is visible, stakes are fake-money pings). Never raises: any exception is
swallowed and printed — a notification must never break a trading run.

Pings: swing fills/closes/placements (one summary per active session),
day-lane session result, league night summary, practice promotion-ready,
workflow failure (curl step with `if: failure()` in both workflows).
Quiet nights send nothing.

## 2. Chase guard — day lane

At fill time (day replay only): fill = max(trigger, bar open); if
`fill - trigger > 0.25 × (trigger - stop)` the entry is SKIPPED and logged
("gapped past trigger — chasing is not the setup"). Evidence: 2026-07-09
NVDA filled a gap so far past its trigger that hitting the planned target
banked −0.15R. Dated amendment in day-trading-charter.md.

## 3. Statistical honesty — `journal.expectancy_ci`

`expectancy_ci(ledger, confidence=0.95) -> (low, high) | None` — Student-t
interval on the R-multiples (t-table dict for df≤30, 1.96 beyond; None when
n < 2). Dashboard: CI caption under every big expectancy number with a
plain-English state ("too early to call" when the CI spans 0 or n < 20);
verdict progress bar (n/100 trades) on Swing and Day desks; ± half-width
column in the league table. No new dependencies.

## 4. Weekly digest — `digest.py` + `digest.yml`

`build_digest(now) -> str` (markdown): league standings (with CI), each
lane's week — closed trades, R and $ banked — practice runs added and
leaderboard movement, promotion status, skip counts. Written to
`reports/weekly/<ISO-week>.md` plus `reports/latest-digest.md`.
Workflow: Sundays 21:00 UTC + manual dispatch; commits `reports/`; ntfy
ping with the headline. Dashboard: new 📰 Digest tab rendering the latest
report.

## Testing

notify: monkeypatched requests — payload shape, never-raises, env override.
chase guard: gap within 0.25R fills; beyond skips and logs. CI: known-values
interval, n<2 → None, spans-zero detection. digest: built from synthetic
ledgers, contains standings + week's trades; file round-trip.

## Non-goals

No Discord/Slack (needs webhooks/accounts), no real-time alerts (the bot
runs nightly — pings arrive when it runs), no auto-promotion (unchanged).
