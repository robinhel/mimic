"""De sparade svaren från röktestet har de fält vi bygger på. Inga nätanrop."""

import json
from pathlib import Path

import pytest

from copycheck.smoke import check

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def rows(name):
    data = load(name)
    return data.get("data") or data.get("markets") or data.get("candlesticks")


@pytest.mark.parametrize(
    "name, sample",
    [
        ("pm_status", lambda: load("pm_status")["data"]),
        ("pm_leaderboard", lambda: rows("pm_leaderboard")[0]),
        ("pm_activity", lambda: rows("pm_activity")[0]),
        ("kalshi_historical_cutoff", lambda: load("kalshi_historical_cutoff")),
        ("kalshi_candlesticks", lambda: rows("kalshi_candlesticks")[0]),
        ("kalshi_markets", lambda: rows("kalshi_markets")[0]),  # KXMVE-rad, har alla fält
    ],
)
def test_fixture_har_vantade_falt(name, sample):
    problems = []
    check(name, sample(), problems)
    assert problems == []


def test_leaderboard_har_cursor():
    assert load("pm_leaderboard")["pagination"]["next_cursor"]


def test_mve_filter_tar_bort_kombinationsmarknader():
    assert all(m["ticker"].startswith("KXMVE") for m in rows("kalshi_markets"))
    assert not any(m["ticker"].startswith("KXMVE") for m in rows("kalshi_markets_no_mve"))
