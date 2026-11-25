import json
from decimal import Decimal
from pathlib import Path

import pytest

from mimic import kalshi

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


class FakeClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get_json(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        return self.pages.pop(0)


def test_dollars_tolkar_text_som_decimal():
    assert kalshi.dollars("0.9900") == Decimal("0.9900")
    assert kalshi.dollars("") is None
    assert kalshi.dollars(None) is None


def test_yes_ask_ar_ett_minus_basta_no_bid():
    assert kalshi.yes_ask_from_no_bid(Decimal("0.88")) == Decimal("0.12")
    assert kalshi.yes_ask_from_no_bid(None) is None


def test_yes_ask_fran_orderbok():
    book = load("kalshi_orderbook")
    best_no = max(Decimal(p) for p, _ in book["orderbook_fp"]["no_dollars"])
    assert kalshi.orderbook_yes_ask(book) == 1 - best_no
    assert kalshi.orderbook_yes_ask({"orderbook_fp": {"no_dollars": []}}) is None


def test_series_fran_event_ticker():
    assert kalshi.series_of("KXNBA3PTPROT-26NOV10MILNYK") == "KXNBA3PTPROT"
    assert kalshi.series_of("KXRAIN-26NOV11") == "KXRAIN"


def test_is_mve():
    assert kalshi.is_mve({"ticker": "KXMVECROSSCATEGORY-S1-X"})
    assert not kalshi.is_mve({"ticker": "KXRAIN-26NOV11-SGF"})


def test_markets_foljer_cursor_och_filtrerar_mve():
    rows = load("kalshi_markets_no_mve")["markets"][:2]
    mve = load("kalshi_markets")["markets"][:1]
    c = FakeClient(
        [{"markets": rows[:1] + mve, "cursor": "nästa"}, {"markets": rows[1:], "cursor": ""}]
    )
    got = list(kalshi.markets(c, "https://k/v2", historical=False, min_close_ts=100))
    assert [m["ticker"] for page in got for m in page] == [r["ticker"] for r in rows]
    assert c.calls[0] == (
        "https://k/v2/markets",
        {"limit": 1000, "mve_filter": "exclude", "min_close_ts": 100},
    )
    assert c.calls[1][1]["cursor"] == "nästa"


def test_historiska_marknader_har_egen_endpoint():
    c = FakeClient([{"markets": [], "cursor": ""}])
    list(kalshi.markets(c, "https://k/v2", historical=True, min_close_ts=1))
    assert c.calls[0][0] == "https://k/v2/historical/markets"


def test_iso_till_unix():
    assert kalshi.iso_ts("2026-11-13T00:30:00Z") == 1794529800
    assert kalshi.iso_ts("") is None


@pytest.mark.parametrize("freq, skip", [("hourly", True), ("fifteen_min", True), ("daily", False)])
def test_skip_series(freq, skip):
    series = {"ticker": "X", "frequency": freq}
    assert (freq in kalshi.SKIP_FREQUENCIES) == skip
    assert ("X" in kalshi.skipped_series([series])) == skip
