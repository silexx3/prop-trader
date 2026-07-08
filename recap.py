"""End-of-session recap: what happened, the regime, brutality, and lessons.

Template-based per Phase 1 of the spec. The lessons lean on the course rules
the experiment was built around — sitting out is a position, expectancy is
the verdict, stops define where you're wrong.
"""

from __future__ import annotations


def brutality_rating(realized_r: float, watchlist_vol_pct: float) -> tuple[int, str]:
    """0–5 from realized R plus how violent the tape was.

    Volatility sets the floor (rough tape is rough even if you're flat);
    realized losses push it up, realized wins soften the note, not the number.
    """
    if watchlist_vol_pct < 0.75:
        vol_score = 0
    elif watchlist_vol_pct < 1.5:
        vol_score = 1
    elif watchlist_vol_pct < 2.5:
        vol_score = 2
    else:
        vol_score = 3

    r_score = 0
    if realized_r <= -2:
        r_score = 2
    elif realized_r <= -0.5:
        r_score = 1

    rating = min(5, vol_score + r_score)
    if realized_r > 0:
        note = f"Tape moved {watchlist_vol_pct:.1f}% on average; we banked +{realized_r:.2f}R."
    elif realized_r < 0:
        note = f"Tape moved {watchlist_vol_pct:.1f}% on average and took {realized_r:.2f}R from us."
    else:
        note = f"Tape moved {watchlist_vol_pct:.1f}% on average; we were flat. Sitting out is a position."
    return rating, note


def lessons(closed_today: list[dict], filled_today: list[dict], placed: list[dict],
            skipped: list[dict], candidates_found: int) -> list[str]:
    out = []
    for t in closed_today:
        if t["reason"] == "stop" and t["r_multiple"] < -1.05:
            out.append(f"{t['ticker']} gapped through the stop ({t['r_multiple']:+.2f}R): "
                       "size for the gap, not the stop — daily swing risk includes overnight.")
        elif t["reason"] == "stop":
            out.append(f"{t['ticker']} stopped for {t['r_multiple']:+.2f}R — a planned loss "
                       "is tuition, not failure. The stop did its one job: define where we're wrong.")
        else:
            out.append(f"{t['ticker']} hit target for {t['r_multiple']:+.2f}R — the 2R minimum "
                       "is what lets a sub-50% win rate still print positive expectancy.")
    for t in filled_today:
        out.append(f"{t['ticker']} filled at {t['entry']}: the trade only exists because the "
                   "level traded — orders wait for price, we don't chase it.")
    if placed and not filled_today:
        out.append("Orders placed, none filled yet — patience between signal and fill is part of the edge.")
    if skipped:
        out.append(f"Skipped {len(skipped)} candidate(s) and logged them: skips are data too.")
    if candidates_found == 0 and not closed_today:
        out.append("No setup = no trade. Most sessions in a two-setup system are correctly boring.")
    return out or ["Quiet session. The ledger, not the excitement level, decides the verdict."]


def build_recap(*, date: str, regime: str, closed_today: list[dict], filled_today: list[dict],
                placed: list[dict], skipped: list[dict], candidates_found: int,
                watchlist_vol_pct: float) -> dict:
    realized_r = sum(t["r_multiple"] for t in closed_today)
    rating, note = brutality_rating(realized_r, watchlist_vol_pct)

    actions = []
    for t in closed_today:
        actions.append(f"{t['ticker']} closed on {t['reason']} at {t['exit']} ({t['r_multiple']:+.2f}R)")
    for t in filled_today:
        actions.append(f"{t['ticker']} order filled at {t['entry']} (stop {t['stop']}, target {t['target']})")
    for o in placed:
        actions.append(f"{o['ticker']} {o['setup']} order placed: entry {o['entry']}, "
                       f"stop {o['stop']}, target {o['target']}, {o['shares']} shares")
    for s in skipped:
        actions.append(f"{s['ticker']} {s['setup']} candidate skipped")
    if not actions:
        actions.append("No trades. No setup = no trade; sitting out is a position.")

    return {
        "date": date,
        "regime": regime,
        "actions": "; ".join(actions) + ".",
        "trades": [t["id"] for t in closed_today],
        "realized_R": round(realized_r, 3),
        "brutality": rating,
        "brutality_note": note,
        "lessons": lessons(closed_today, filled_today, placed, skipped, candidates_found),
    }
