# Prop Trader — Abhi vs. the course

[![Daily prop session](https://github.com/silexx3/prop-trader/actions/workflows/daily-session.yml/badge.svg)](https://github.com/silexx3/prop-trader/actions/workflows/daily-session.yml)

A fully automated, **simulation-only** paper-trading experiment: a $5,000 simulated
account swing-trading two curriculum setups on real daily market data. Every trade
journaled, every session recapped, verdict decided by expectancy at 100 trades or
6 months. **No brokerage, no API keys to real accounts, no real money — ever.**

The rules live in [prop-experiment-charter.md](prop-experiment-charter.md) and the
code enforces them instead of trusting willpower.

## How it runs

- **Automated:** GitHub Actions runs [auto_session.py](auto_session.py) every weekday
  at 21:30 UTC (after US market close). It manages open trades (stops before targets,
  pessimistic fills), fills or expires pending orders, scans the watchlist for the two
  charter setups, auto-places anything that passes every rule, writes the session
  recap, and commits the updated ledger back to this repo.
- **Dashboard:** a Streamlit app ([app.py](app.py)) shows bot status, the overnight
  briefing, expectancy (the verdict metric), equity curve, R-distribution, open
  positions, every lesson logged, and a historical backtest — deployed on Streamlit
  Community Cloud, auto-updating on every push.

## The two setups (charter law)

1. **`ma_pullback`** — uptrend (rising 20/50-day SMAs), pullback into the SMA zone,
   entry on reclaim of the prior day's high, stop below the pullback low, 2R target.
2. **`base_breakout`** — ≥4 weeks of tight range near highs, entry on the break of
   the range high, stop below the base, 2R target.

Risk: 1% of balance per trade, −0.05R cost charge on every trade, max 2 open
positions, 2R max open risk, stops only move toward the trade.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest tests/ -m "not slow"   # fast suite
.venv/bin/streamlit run app.py                     # local dashboard
```

This is a learning experiment, not financial advice, and none of it is real money.
