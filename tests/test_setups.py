"""Detector output must always be placeable: the candidate builder and the
engine's 2R check have to agree, including after cent rounding."""

import engine
import setups
from tests.test_engine import fresh_ledger


def test_candidate_targets_survive_the_engines_2R_check():
    # Awkward decimals that round badly — the exact bug class caught live:
    # target derived from unrounded levels came out cents short of 2R.
    awkward = [(746.196, 701.404), (524.9749, 494.3551), (100.005, 99.995), (33.333, 31.111)]
    for entry, stop in awkward:
        c = setups._candidate("TEST", "base_breakout", entry, stop, "rounding check")
        if c is None:
            # Rounding collapsed the risk to zero — correctly refused upstream.
            assert round(entry, 2) <= round(stop, 2)
            continue
        ledger = fresh_ledger(balance=500000.0)  # big enough to size any of these
        order = engine.place_order(ledger, ticker=c["ticker"], setup=c["setup"],
                                   entry=c["entry"], stop=c["stop"], target=c["target"],
                                   date="2026-07-08")
        assert order["target"] >= order["entry"] + 2 * (order["entry"] - order["stop"]) - 1e-9
