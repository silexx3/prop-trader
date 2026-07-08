"""The charter says "no numbers, no trade" — an in-progress daily bar is not
a number, it's a guess. Sessions may only run on final (post-close) bars."""

import datetime as dt

import data as market

UTC = dt.timezone.utc


def test_yesterdays_bar_is_final():
    now = dt.datetime(2026, 7, 8, 14, 0, tzinfo=UTC)  # market open Wednesday
    assert market.bar_is_final("2026-07-07", now=now) is True


def test_todays_bar_during_market_hours_is_not_final():
    now = dt.datetime(2026, 7, 8, 14, 0, tzinfo=UTC)  # 10:00am ET, market open
    assert market.bar_is_final("2026-07-08", now=now) is False


def test_todays_bar_after_close_buffer_is_final():
    now = dt.datetime(2026, 7, 8, 21, 30, tzinfo=UTC)  # the scheduled run time
    assert market.bar_is_final("2026-07-08", now=now) is True


def test_todays_bar_just_after_summer_close_still_waits_for_buffer():
    # 20:30 UTC is after the 20:00 UTC summer close but before the DST-proof
    # 21:05 cutoff — conservatively still treated as not final.
    now = dt.datetime(2026, 7, 8, 20, 30, tzinfo=UTC)
    assert market.bar_is_final("2026-07-08", now=now) is False


def test_fridays_bar_on_saturday_is_final():
    now = dt.datetime(2026, 7, 11, 10, 0, tzinfo=UTC)  # Saturday morning
    assert market.bar_is_final("2026-07-10", now=now) is True
