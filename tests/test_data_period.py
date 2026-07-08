"""fetch_watchlist must accept a period override without changing the default."""

import inspect

import data as market


def test_fetch_watchlist_accepts_period_override():
    sig = inspect.signature(market.fetch_watchlist)
    assert "period" in sig.parameters
    assert sig.parameters["period"].default == market.LOOKBACK


def test_fetch_watchlist_default_unchanged():
    sig = inspect.signature(market.fetch_watchlist)
    assert sig.parameters["tickers"].default is inspect.Parameter.empty
