"""Digest tests: built from the real repo ledgers (read-only), plus a
file round-trip into a temp reports dir."""

import datetime as dt

import digest
import journal


def test_digest_contains_standings_and_lanes():
    md = digest.build_digest(dt.date(2026, 7, 12))
    assert "League standings" in md
    assert "Swing (charter)" in md
    assert "Day lane" in md
    assert "Practice Lab" in md
    assert "Simulation only" in md


def test_digest_week_window_filters_trades():
    # A date far in the future: every existing trade falls out of "this week."
    md = digest.build_digest(dt.date(2030, 1, 1))
    assert "no closed trades" in md.lower()


def test_write_digest_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(digest, "REPORTS_DIR", tmp_path)
    before = journal.LEDGER_PATH.read_bytes()
    path = digest.write_digest(dt.date(2026, 7, 12))
    assert path.exists()
    assert (tmp_path / "latest-digest.md").read_text() == path.read_text()
    assert journal.LEDGER_PATH.read_bytes() == before  # read-only on ledgers
