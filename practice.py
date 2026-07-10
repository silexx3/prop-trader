"""Practice Lab — the bot's offline training ground.

Each run picks a fresh historical window and pits strategy VARIANTS (the
charter baseline plus parameter tweaks of the same two setups) against it on
a scratch $10,000 account. Results append to practice-history.json, so every
run adds sample size and the leaderboard genuinely sharpens over time.

Hard lines: never reads or writes prop-experiment-ledger.json, never changes
the live bot's parameters, and its scratch balance is not the experiment's
$5,000. Insights here are research; promoting one to the live charter is a
human decision requiring a dated charter amendment. Historical win ≠ future
edge — every variant that "wins" here was tuned on hindsight.

Run with:  python practice.py
Works offline once data-cache/ has been populated by any prior online run.
"""

from __future__ import annotations

import datetime as dt
import json
import random
import sys
from pathlib import Path

import backtest
import data as market
import journal

HISTORY_PATH = Path(__file__).parent / "practice-history.json"
PRACTICE_BALANCE = 10_000.0   # scratch money — NOT the experiment's $5k
WINDOW_SESSIONS = 500          # ~2 years per practice window
MIN_SESSIONS = backtest.WARMUP_SESSIONS + 150

# The charter baseline first, then one-knob-at-a-time tweaks of the same two
# setups — so a variant's edge (or lack of it) is attributable to one change.
VARIANTS = [
    {"name": "charter-baseline", "params": {}},
    {"name": "base-6-weeks", "params": {"base_breakout": {"base_weeks": 6}}},
    {"name": "base-8-weeks-tight", "params": {"base_breakout": {"base_weeks": 8, "max_range_pct": 8.0}}},
    {"name": "base-loose-range", "params": {"base_breakout": {"max_range_pct": 12.0}}},
    {"name": "pullback-deep-swing", "params": {"ma_pullback": {"pullback_lookback": 15}}},
    {"name": "pullback-wide-zone", "params": {"ma_pullback": {"zone_tolerance": 1.02}}},
    {"name": "wider-stop-buffer", "params": {"ma_pullback": {"stop_buffer": 0.99},
                                             "base_breakout": {"stop_buffer": 0.99}}},
]


def load_history() -> dict:
    if HISTORY_PATH.exists():
        with open(HISTORY_PATH) as f:
            return json.load(f)
    return {"runs": []}


def save_history(history: dict) -> None:
    tmp = HISTORY_PATH.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(history, f, indent=2)
    tmp.replace(HISTORY_PATH)


def pick_window(frames: dict, run_number: int) -> dict:
    """One shared calendar window per run, sliced across every ticker.

    All tickers see the SAME era — necessary for the correlation guard and
    SPY regime filter to mean anything inside a practice run. Tickers that
    didn't exist (or barely existed) in the chosen era are dropped. Seeding
    by run number: every run studies a different era, same run number
    reproduces the same window.
    """
    rng = random.Random(run_number)
    span = WINDOW_SESSIONS + backtest.WARMUP_SESSIONS
    all_dates = sorted(set().union(*(set(df.index) for df in frames.values())))
    if len(all_dates) <= span:
        end_i = len(all_dates) - 1
    else:
        end_i = rng.randint(span, len(all_dates) - 1)
    start_date, end_date = all_dates[max(0, end_i - span)], all_dates[end_i]

    trimmed = {}
    for ticker, df in frames.items():
        window = df.loc[start_date:end_date]
        if len(window) >= MIN_SESSIONS:
            trimmed[ticker] = window
    return trimmed


def run_practice(watchlist: list[str] | None = None) -> dict | None:
    """One practice run: returns the run record appended to history."""
    if watchlist is None:
        ledger = journal.load_ledger()   # read-only: just the watchlist tickers
        watchlist = ledger["watchlist"]

    frames = market.fetch_or_cache(watchlist, period="max")
    if not frames:
        print("No data online or cached — cannot practice. Run once online first.")
        return None

    history = load_history()
    run_number = len(history["runs"]) + 1
    window = pick_window(frames, run_number)
    if not window:
        print("Not enough history for a practice window.")
        return None

    window_start = min(str(df.index[0].date()) for df in window.values())
    window_end = max(str(df.index[-1].date()) for df in window.values())
    print(f"Practice run #{run_number}: window {window_start} → {window_end}, "
          f"{len(window)} tickers, {len(VARIANTS)} variants")

    results = []
    for v in VARIANTS:
        outcome = backtest.run_backtest_from_frames(
            window, starting_balance=PRACTICE_BALANCE, variant=v["params"])
        stats = outcome["stats"]
        results.append({
            "variant": v["name"],
            "trades": stats["trades_closed"],
            "expectancy_R": stats["expectancy_R"],
            "win_rate_pct": stats["win_rate_pct"],
            "total_R": stats["total_R"],
            "max_drawdown_pct": stats["max_drawdown_pct"],
        })
        exp = stats["expectancy_R"]
        print(f"  {v['name']:24s} {stats['trades_closed']:3d} trades  "
              f"expectancy {exp if exp is not None else '—'}")

    record = {
        "run": run_number,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "window": [window_start, window_end],
        "tickers": sorted(window.keys()),
        "results": results,
    }
    history["runs"].append(record)
    save_history(history)
    print(f"\nSaved run #{run_number}. Total practice runs banked: {len(history['runs'])}")
    return record


def leaderboard(history: dict | None = None) -> list[dict]:
    """Aggregate every run: expectancy per variant across ALL practice windows,
    weighted by trade count. More runs -> bigger samples -> sharper ranking."""
    history = history or load_history()
    agg: dict[str, dict] = {}
    for run in history["runs"]:
        for r in run["results"]:
            a = agg.setdefault(r["variant"], {"trades": 0, "total_R": 0.0, "runs": 0})
            a["trades"] += r["trades"]
            a["total_R"] += r["total_R"]
            a["runs"] += 1
    board = []
    for name, a in agg.items():
        board.append({
            "variant": name,
            "runs": a["runs"],
            "trades": a["trades"],
            "total_R": round(a["total_R"], 2),
            "expectancy_R": round(a["total_R"] / a["trades"], 3) if a["trades"] else None,
        })
    board.sort(key=lambda b: (b["expectancy_R"] is not None, b["expectancy_R"]), reverse=True)
    return board


# --- promotion pipeline: when practice evidence is strong enough to warrant
# --- a human charter-amendment decision, say so loudly. Never auto-applied.

PROMOTION_MIN_RUNS = 10        # windows a variant must have been tested in
PROMOTION_MIN_TRADES = 100     # total practice trades behind the number
PROMOTION_WIN_FRACTION = 0.7   # share of windows it must beat the baseline in


def promotion_candidates(history: dict | None = None) -> list[dict]:
    """Variants with enough evidence to justify a promotion *review*.

    Paired comparison: within each run (same window, same tickers) a variant's
    expectancy is compared to charter-baseline's. Beating it in ≥70% of ≥10
    windows with ≥100 total trades is the bar for flagging — not for adopting;
    that stays a human charter-amendment decision.
    """
    history = history or load_history()
    deltas: dict[str, list[float]] = {}
    for run in history["runs"]:
        results = {r["variant"]: r for r in run["results"]}
        base = results.get("charter-baseline")
        if not base or base["expectancy_R"] is None:
            continue
        for name, r in results.items():
            if name == "charter-baseline" or r["expectancy_R"] is None:
                continue
            deltas.setdefault(name, []).append(r["expectancy_R"] - base["expectancy_R"])

    board = {b["variant"]: b for b in leaderboard(history)}
    ready = []
    for name, ds in deltas.items():
        b = board.get(name)
        if b is None or len(ds) < PROMOTION_MIN_RUNS or b["trades"] < PROMOTION_MIN_TRADES:
            continue
        win_frac = sum(1 for d in ds if d > 0) / len(ds)
        avg_edge = sum(ds) / len(ds)
        if win_frac >= PROMOTION_WIN_FRACTION and avg_edge > 0:
            ready.append({
                "variant": name,
                "windows_compared": len(ds),
                "beat_baseline_pct": round(100 * win_frac, 1),
                "avg_edge_R": round(avg_edge, 3),
                "trades": b["trades"],
                "expectancy_R": b["expectancy_R"],
            })
    ready.sort(key=lambda x: x["avg_edge_R"], reverse=True)
    return ready


if __name__ == "__main__":
    try:
        record = run_practice()
        if record is not None:
            print("\n=== All-time leaderboard ===")
            for row in leaderboard():
                exp = row["expectancy_R"]
                print(f"  {row['variant']:24s} {row['trades']:4d} trades over {row['runs']} runs  "
                      f"expectancy {exp if exp is not None else '—'}")
            ready = promotion_candidates()
            if ready:
                print("\n🏆 READY FOR PROMOTION REVIEW (human charter-amendment decision):")
                for p in ready:
                    print(f"  {p['variant']}: beat baseline in {p['beat_baseline_pct']}% of "
                          f"{p['windows_compared']} windows, avg edge {p['avg_edge_R']:+.3f}R "
                          f"over {p['trades']} trades")
                import notify
                notify.send("Practice Lab: promotion review ready",
                            "; ".join(f"{p['variant']} +{p['avg_edge_R']:.3f}R edge over "
                                      f"{p['windows_compared']} windows" for p in ready),
                            priority="high", tags=["brain", "trophy"])
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
