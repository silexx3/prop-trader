"""Prop Trader dashboard — simulation only, no real money, ever.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import requests
import streamlit as st

import backtest
import data as market
import engine
import journal
import recap as recap_mod
import setups

st.set_page_config(page_title="Prop Trader — $5k experiment", page_icon="📒", layout="wide")

st.markdown("""
<style>
.big-expectancy { font-size: 4rem; font-weight: 800; line-height: 1; margin: 0; }
.big-label { font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.1em; opacity: 0.6; }
.verdict-note { font-size: 0.8rem; opacity: 0.5; }
</style>
""", unsafe_allow_html=True)


# ---------- ledger ----------

if "ledger" not in st.session_state:
    st.session_state.ledger = journal.load_ledger()
ledger = st.session_state.ledger


def persist():
    journal.compute_stats(ledger)
    journal.save_ledger(ledger)


@st.cache_data(ttl=600, show_spinner="Fetching daily data…")
def fetch(tickers: tuple[str, ...]):
    return market.fetch_watchlist(list(tickers))


@st.cache_data(ttl=3600, show_spinner="Running historical backtest (this can take a bit)…")
def run_cached_backtest(tickers: tuple[str, ...]):
    return backtest.run_backtest(list(tickers))


# ---------- header ----------

st.title("📒 Prop Trader — Abhi vs. the course")
st.caption(
    f"Simulated ${ledger['account']['starting_balance']:,.0f} account · swing on daily charts · "
    "verdict at 100 trades or 6 months · **simulation only, no real money**"
)

# ---------- scoreboard (expectancy is the verdict, so it's biggest) ----------

stats = journal.compute_stats(ledger)
exp = stats["expectancy_R"]
exp_txt = f"{exp:+.3f}R" if exp is not None else "—"
exp_color = "inherit" if exp is None else ("#0a9950" if exp > 0 else "#d43a3a")

left, right = st.columns([2, 3])
with left:
    st.markdown('<div class="big-label">Expectancy per trade (after costs)</div>', unsafe_allow_html=True)
    st.markdown(f'<p class="big-expectancy" style="color:{exp_color}">{exp_txt}</p>', unsafe_allow_html=True)
    st.markdown('<div class="verdict-note">This number settles the bet — not the win rate, '
                'not the balance on a good week.</div>', unsafe_allow_html=True)
with right:
    c1, c2, c3, c4 = st.columns(4)
    pnl = ledger["account"]["balance"] - ledger["account"]["starting_balance"]
    c1.metric("Balance", f"${ledger['account']['balance']:,.2f}", f"{pnl:+,.2f}")
    c2.metric("Trades closed", stats["trades_closed"], f"of 100 · streak {journal.current_streak(ledger)}")
    c3.metric("Win rate", f"{stats['win_rate_pct']}%" if stats["win_rate_pct"] is not None else "—",
              f"total {stats['total_R']:+.2f}R")
    c4.metric("Max drawdown", f"{stats['max_drawdown_pct']}%",
              f"{len(ledger['open_trades'])} open · {len(ledger['pending_orders'])} pending",
              delta_color="off")

st.divider()

# ---------- bot status (what the bot is doing right now) ----------

REPO_SLUG = "silexx3/prop-trader"
ACTIONS_URL = f"https://github.com/{REPO_SLUG}/actions"


@st.cache_data(ttl=120)
def fetch_latest_workflow_run():
    """Latest scheduled-run status from the public GitHub API (no auth needed).
    Returns None when offline or rate-limited — the dashboard must still work."""
    try:
        r = requests.get(
            f"https://api.github.com/repos/{REPO_SLUG}/actions/workflows/daily-session.yml/runs",
            params={"per_page": 1}, timeout=5)
        runs = r.json().get("workflow_runs", [])
        if not runs:
            return {"status": "no_runs", "conclusion": None, "url": ACTIONS_URL}
        run = runs[0]
        return {"status": run["status"], "conclusion": run["conclusion"],
                "started": run["run_started_at"], "url": run["html_url"]}
    except Exception:
        return None


def next_scheduled_run_utc() -> dt.datetime:
    """Next weekday 21:30 UTC — mirrors the cron in daily-session.yml."""
    now = dt.datetime.now(dt.timezone.utc)
    candidate = now.replace(hour=21, minute=30, second=0, microsecond=0)
    while candidate <= now or candidate.weekday() >= 5:
        candidate += dt.timedelta(days=1)
    return candidate


run_info = fetch_latest_workflow_run()

if run_info and run_info["status"] in ("queued", "in_progress"):
    status_line = "⚙️ **Running today's session right now** — refresh in a minute for results."
elif ledger["open_trades"]:
    tickers = ", ".join(t["ticker"] for t in ledger["open_trades"])
    status_line = (f"📈 **Trading** — managing {len(ledger['open_trades'])} open position(s): "
                   f"{tickers}. Stops and targets get checked at the next session run.")
elif ledger["pending_orders"]:
    tickers = ", ".join(o["ticker"] for o in ledger["pending_orders"])
    status_line = (f"🎯 **Orders armed** — buy-stops waiting on {tickers}; "
                   "they fill or expire at the next session.")
else:
    status_line = "👁️ **Watching** — flat, scanning for the two charter setups every session."

nxt = next_scheduled_run_utc()
away = nxt - dt.datetime.now(dt.timezone.utc)
hrs, mins = divmod(int(away.total_seconds() // 60), 60)

with st.container(border=True):
    st.markdown(f"### 🤖 Bot status")
    st.markdown(status_line)
    pieces = [f"Next scheduled run in **{hrs}h {mins}m** (weekdays 21:30 UTC, after US close)"]
    if run_info and run_info["status"] == "completed":
        if run_info["conclusion"] == "success":
            pieces.append(f"last auto-run [✅ succeeded]({run_info['url']})")
        else:
            pieces.append(f"last auto-run [❌ {run_info['conclusion']}]({run_info['url']}) — check the Actions tab")
    elif run_info and run_info["status"] == "no_runs":
        pieces.append(f"no scheduled runs yet — the first fires at the next slot ([Actions tab]({ACTIONS_URL}))")
    elif run_info is None:
        pieces.append(f"couldn't reach GitHub for run status ([Actions tab]({ACTIONS_URL}))")
    st.caption(" · ".join(pieces))

# ---------- overnight briefing (what the bot did while you were away) ----------

if ledger["sessions"]:
    latest = ledger["sessions"][-1]
    try:
        days_ago = (dt.date.today() - dt.date.fromisoformat(latest["date"])).days
    except ValueError:
        days_ago = None
    freshness = ("today" if days_ago == 0 else
                 "yesterday" if days_ago == 1 else
                 f"{days_ago} days ago" if days_ago is not None else latest["date"])

    with st.container(border=True):
        st.markdown(f"### 🌙 Overnight briefing — last session was **{freshness}** ({latest['date']})")
        st.write(f"**Regime:** {latest.get('regime', '—')}")
        st.write(f"**What happened:** {latest.get('actions', '—')}")
        flames = "🔥" * latest.get("brutality", 0) or "calm"
        st.caption(f"Brutality {latest.get('brutality', 0)}/5 {flames} — {latest.get('brutality_note', '')}")
        if latest.get("lessons"):
            st.markdown("**Lessons logged:**")
            for lesson in latest["lessons"]:
                st.markdown(f"- {lesson}")
        if days_ago is not None and days_ago >= 2:
            st.warning(
                f"No session logged in {days_ago} days — the scheduled GitHub Actions run may "
                "have failed or the market's been closed. Check the repo's Actions tab."
            )

    all_lessons = [(s["date"], lesson) for s in ledger["sessions"] for lesson in s.get("lessons", [])]
    if all_lessons:
        with st.expander(f"📚 Everything the bot has learned so far ({len(all_lessons)} lessons)"):
            for date, lesson in reversed(all_lessons):
                st.markdown(f"- **{date}** — {lesson}")
else:
    st.info("No sessions logged yet — the bot hasn't run overnight. It runs automatically on "
            "the GitHub Actions schedule, or click \"Run today's session\" below to trigger one now.")

st.divider()

# ---------- session runner ----------

run_col, wl_col = st.columns([1, 3])
with wl_col:
    wl_text = st.text_input("Watchlist (editable)", value=", ".join(ledger["watchlist"]),
                            help="Comma-separated tickers. Saved with the ledger.")
    new_wl = [t.strip().upper() for t in wl_text.split(",") if t.strip()]
    if new_wl and new_wl != ledger["watchlist"]:
        ledger["watchlist"] = new_wl
        persist()

with run_col:
    st.write("")  # vertical alignment
    run_clicked = st.button("▶ Run today's session", type="primary", use_container_width=True)

if run_clicked:
    frames = fetch(tuple(ledger["watchlist"]))
    if not frames:
        st.error("No data came back for the watchlist — no numbers, no trade. Try again later.")
    else:
        session_date = market.latest_session_date(frames)
        already = any(s["date"] == session_date for s in ledger["sessions"])
        if already:
            st.warning(f"A session for {session_date} is already in the ledger. "
                       "Markets close once a day — come back after the next close.")
        else:
            # Amendment 2026-07-08: candidates that pass every charter rule are
            # placed automatically — no human place/skip step. This is what lets
            # the scheduled (GitHub Actions) run behave identically to a manual
            # click here. See prop-experiment-charter.md.
            bars = market.bars_today(frames)
            closed_today = engine.manage_open_trades(ledger, bars, session_date)
            filled_today, expired = engine.process_pending_fills(ledger, bars, session_date)
            busy = {t["ticker"] for t in ledger["open_trades"]}
            candidates = setups.scan(frames, skip_tickers=busy)

            placed, skipped = [], []
            for c in candidates:
                try:
                    placed.append(engine.place_order(
                        ledger, ticker=c["ticker"], setup=c["setup"], entry=c["entry"],
                        stop=c["stop"], target=c["target"], date=session_date, note=c["reason"]))
                except engine.RuleViolation as e:
                    journal.log_skip(ledger, c, session_date, reason=f"blocked by charter: {e}")
                    skipped.append(c)

            session_entry = recap_mod.build_recap(
                date=session_date, regime=market.regime_summary(frames),
                closed_today=closed_today, filled_today=filled_today, placed=placed,
                skipped=skipped, candidates_found=len(candidates),
                watchlist_vol_pct=market.watchlist_volatility_pct(frames))
            ledger["sessions"].append(session_entry)
            persist()
            st.session_state.last_run = session_entry
            st.rerun()

if "last_run" in st.session_state:
    rv = st.session_state.last_run
    st.subheader(f"Session {rv['date']} — auto-run result")
    st.write(f"**Regime:** {rv['regime']}")
    st.write(rv["actions"])
    for lesson in rv["lessons"]:
        st.caption(f"• {lesson}")

st.divider()

# ---------- positions ----------

pos_col, chart_col = st.columns([2, 3])

with pos_col:
    st.subheader("Open positions")
    if ledger["open_trades"]:
        for t in ledger["open_trades"]:
            risk_left = max(0.0, (t["entry"] - t["stop"]) / (t["entry"] - t["initial_stop"]))
            with st.container(border=True):
                st.markdown(f"**{t['ticker']}** · `{t['setup']}` · {t['shares']} sh @ {t['entry']} · "
                            f"stop {t['stop']} → target {t['target']} · **{risk_left:.2f}R at risk**")
                new_stop = st.number_input(f"Move {t['ticker']} stop (up only)", value=float(t["stop"]),
                                           step=0.01, key=f"stop_{t['id']}", format="%.2f")
                if new_stop > t["stop"]:
                    try:
                        engine.move_stop(t, new_stop)
                        persist()
                        st.rerun()
                    except engine.RuleViolation as e:
                        st.error(str(e))
    else:
        st.caption("None. Flat is a position too.")

    st.subheader("Pending orders")
    if ledger["pending_orders"]:
        for o in ledger["pending_orders"]:
            st.markdown(f"**{o['ticker']}** buy-stop {o['entry']} · stop {o['stop']} · "
                        f"target {o['target']} · {o['shares']} sh (good next session)")
    else:
        st.caption("None.")

    st.markdown(f"**Committed risk:** {engine.open_risk_R(ledger['open_trades']) + len(ledger['pending_orders']):.2f}R "
                f"of {engine.rules_from_ledger(ledger).max_open_risk_R:.0f}R allowed")

with chart_col:
    st.subheader("Equity curve")
    curve = journal.equity_curve(ledger)
    curve_df = pd.DataFrame(curve, columns=["date", "balance"])
    curve_df["date"] = pd.to_datetime(curve_df["date"])
    st.line_chart(curve_df.set_index("date")["balance"], height=240)

    rs = journal.r_distribution(ledger)
    if rs:
        st.subheader("R distribution")
        bins = pd.cut(pd.Series(rs), bins=[-5, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 5])
        hist = bins.value_counts().sort_index()
        hist.index = [f"{iv.left:g}…{iv.right:g}" for iv in hist.index]
        st.bar_chart(hist, height=200)

# ---------- expectancy by setup + export ----------

by_setup = journal.expectancy_by_setup(ledger)
if by_setup:
    st.subheader("Expectancy by setup")
    st.dataframe(pd.DataFrame(by_setup).T, use_container_width=True)

if ledger["closed_trades"]:
    csv = pd.DataFrame(ledger["closed_trades"]).to_csv(index=False).encode()
    st.download_button("⬇ Export closed trades (CSV)", csv, "prop-experiment-trades.csv", "text/csv")

st.divider()

# ---------- recap feed ----------

st.subheader("Session recaps")
for s in reversed(ledger["sessions"]):
    flames = "🔥" * s.get("brutality", 0) or "—"
    with st.expander(f"{s['date']} · brutality {s.get('brutality', 0)}/5 {flames}", expanded=False):
        st.write(f"**Regime:** {s.get('regime', '—')}")
        st.write(f"**Actions:** {s.get('actions', '—')}")
        if s.get("brutality_note"):
            st.caption(s["brutality_note"])
        for lesson in s.get("lessons", []):
            st.markdown(f"- {lesson}")

st.divider()

# ---------- backtest (hypothetical, read-only, never touches the real ledger) ----------

st.subheader("📊 Backtest — hypothetical, not real results")
st.caption(
    "Runs the exact same engine against this watchlist's full historical daily data. "
    "**Survivorship/hindsight-bias caveat:** these tickers were picked with the benefit "
    "of already knowing how they performed — this shows what THIS watchlist would have "
    "done, not a blind test of the strategy on an unbiased universe."
)

if st.button("▶ Run backtest"):
    st.session_state.backtest_result = run_cached_backtest(tuple(ledger["watchlist"]))

if "backtest_result" in st.session_state:
    bt = st.session_state.backtest_result
    bt_stats = journal.compute_stats(bt)
    bt_exp = bt_stats["expectancy_R"]
    bt_exp_txt = f"{bt_exp:+.3f}R" if bt_exp is not None else "—"
    bt_color = "inherit" if bt_exp is None else ("#0a9950" if bt_exp > 0 else "#d43a3a")

    bl, br = st.columns([2, 3])
    with bl:
        st.markdown('<div class="big-label">Backtest expectancy per trade</div>', unsafe_allow_html=True)
        st.markdown(f'<p class="big-expectancy" style="color:{bt_color}">{bt_exp_txt}</p>', unsafe_allow_html=True)
    with br:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Trades", bt_stats["trades_closed"])
        c2.metric("Win rate", f"{bt_stats['win_rate_pct']}%" if bt_stats["win_rate_pct"] is not None else "—")
        c3.metric("Total R", f"{bt_stats['total_R']:+.2f}")
        c4.metric("Max drawdown", f"{bt_stats['max_drawdown_pct']}%")

    bt_curve = pd.DataFrame(journal.equity_curve(bt), columns=["date", "balance"])
    bt_curve["date"] = pd.to_datetime(bt_curve["date"])
    st.line_chart(bt_curve.set_index("date")["balance"], height=240)

    bt_rs = journal.r_distribution(bt)
    if bt_rs:
        bt_bins = pd.cut(pd.Series(bt_rs), bins=[-5, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 5])
        bt_hist = bt_bins.value_counts().sort_index()
        bt_hist.index = [f"{iv.left:g}…{iv.right:g}" for iv in bt_hist.index]
        st.bar_chart(bt_hist, height=200)

    bt_by_setup = journal.expectancy_by_setup(bt)
    if bt_by_setup:
        st.dataframe(pd.DataFrame(bt_by_setup).T, use_container_width=True)
