"""Weekly digest — the bot writes its own week-in-review every Sunday.

Reads every ledger plus the practice history and produces one markdown
report: league standings, each lane's week in R and dollars, what practice
learned, promotion status, and discipline (skip) counts. Committed to
reports/ and rendered on the dashboard's Digest tab.

Run with:  python digest.py
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import day_session
import journal
import league
import practice

REPORTS_DIR = Path(__file__).parent / "reports"


def _week_slice(ledger: dict, since: str) -> list[dict]:
    return [t for t in ledger["closed_trades"] if t["closed"] >= since]


def _lane_week(name: str, ledger: dict, since: str) -> str:
    week = _week_slice(ledger, since)
    stats = journal.compute_stats(ledger)
    ci = journal.expectancy_ci(ledger)
    ci_txt = f"{ci[0]:+.2f}R…{ci[1]:+.2f}R" if ci else "n/a"
    lines = [f"### {name}",
             f"Balance **${ledger['account']['balance']:,.2f}** · lifetime expectancy "
             f"**{stats['expectancy_R'] if stats['expectancy_R'] is not None else '—'}** "
             f"(95% CI {ci_txt}) over {stats['trades_closed']} trades."]
    if week:
        week_r = sum(t["r_multiple"] for t in week)
        week_pnl = sum(t["pnl_usd"] for t in week)
        lines.append(f"This week: **{len(week)} closed trades, {week_r:+.2f}R "
                     f"(${week_pnl:+,.2f})**.")
        for t in week:
            lines.append(f"- {t['closed']} {t['ticker']} `{t['setup']}` → "
                         f"{t['reason']} **{t['r_multiple']:+.2f}R**")
    else:
        lines.append("This week: no closed trades. Sitting out is a position.")
    skips = [s for s in ledger.get("skipped_candidates", []) if s["date"] >= since]
    if skips:
        lines.append(f"Discipline: {len(skips)} candidate(s) declined "
                     f"(guards, caps, and rules doing their job).")
    return "\n".join(lines)


def build_digest(now: dt.date | None = None) -> str:
    now = now or dt.date.today()
    since = (now - dt.timedelta(days=7)).isoformat()
    iso_week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"

    parts = [f"# 📰 Week {iso_week} — Prop Trader digest",
             f"*Covering {since} → {now.isoformat()}. Simulation only — no real money.*", ""]

    # League standings — the tournament is the headline.
    rows = league.summary()
    parts.append("## 🏆 League standings")
    parts.append("| account | balance | expectancy | trades |")
    parts.append("|---|---|---|---|")
    for r in rows:
        exp = f"{r['expectancy_R']:+.3f}R" if r["expectancy_R"] is not None else "—"
        parts.append(f"| {r['account']} | ${r['balance']:,.2f} | {exp} | {r['trades_closed']} |")
    parts.append("")

    # Each lane's week.
    parts.append("## The week by lane")
    parts.append(_lane_week("👑 Swing (charter)", journal.load_ledger(), since))
    parts.append("")
    parts.append(_lane_week("⚡ Day lane", day_session.load_day_ledger(), since))
    parts.append("")

    # Practice Lab.
    history = practice.load_history()
    week_runs = [r for r in history["runs"] if r["at"][:10] >= since]
    parts.append("## 🧠 Practice Lab")
    parts.append(f"{len(week_runs)} practice run(s) this week, "
                 f"{len(history['runs'])} banked all-time.")
    board = practice.leaderboard(history)
    if board:
        top = board[0]
        parts.append(f"Current leader: **{top['variant']}** at "
                     f"{top['expectancy_R'] if top['expectancy_R'] is not None else '—'}R "
                     f"over {top['trades']} practice trades.")
    ready = practice.promotion_candidates(history)
    if ready:
        parts.append("**🏆 Promotion review ready:** " +
                     "; ".join(f"{p['variant']} (+{p['avg_edge_R']:.3f}R edge, "
                               f"{p['windows_compared']} windows)" for p in ready))
    else:
        parts.append("No variant has met the promotion bar yet — the bar is the point.")

    return "\n".join(parts) + "\n"


def write_digest(now: dt.date | None = None) -> Path:
    now = now or dt.date.today()
    md = build_digest(now)
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "weekly").mkdir(exist_ok=True)
    iso_week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    weekly_path = REPORTS_DIR / "weekly" / f"{iso_week}.md"
    weekly_path.write_text(md)
    (REPORTS_DIR / "latest-digest.md").write_text(md)
    return weekly_path


if __name__ == "__main__":
    try:
        path = write_digest()
        print(f"Digest written: {path}")
        import notify
        headline = path.read_text().splitlines()[0].lstrip("# ")
        notify.send("Weekly digest is in", headline, tags=["newspaper"])
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
