import json
from decimal import Decimal
from pathlib import Path

from mimic import polymarket

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClient:
    """Svarar med sidor i tur och ordning och sparar anropen."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get_json(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        return self.pages.pop(0)


def page(rows, cursor=None):
    return {"data": rows, "pagination": {"has_more": bool(cursor), "next_cursor": cursor}}


def test_price_tar_bort_brus():
    assert polymarket.price(0.4900001785) == Decimal("0.4900")
    assert polymarket.price(0.0900000243) == Decimal("0.0900")
    assert polymarket.price(1) == Decimal("1.0000")


def test_fetch_all_foljer_cursor_och_skickar_aldrig_offset():
    c = FakeClient([page([1, 2], "abc"), page([3])])
    rows, truncated = polymarket.fetch_all(c, "/activity", {"user": "0x1"})
    assert rows == [1, 2, 3]
    assert truncated is False
    assert c.calls[0][0].endswith("/v2/activity")
    assert "cursor" not in c.calls[0][1]
    assert c.calls[1][1]["cursor"] == "abc"
    assert all("offset" not in p and "market" not in p for _, p in c.calls)


def test_fetch_all_markerar_avkortat():
    c = FakeClient([page([1], "a"), page([2], "b"), page([3])])
    rows, truncated = polymarket.fetch_all(c, "/activity", {}, max_pages=2)
    assert rows == [1, 2]
    assert truncated is True


def test_leaderboard_skickar_period_och_sortering():
    c = FakeClient([json.loads((FIXTURES / "pm_leaderboard.json").read_text())])
    rows = polymarket.leaderboard(c, "month", "VOLUME", limit=5)
    assert len(rows) == 5
    assert c.calls[0][1] == {"time_period": "month", "order_by": "VOLUME", "limit": 5}


def test_activity_skickar_start_och_type():
    c = FakeClient([page([])])
    polymarket.activity(c, "0xabc", start=1700000000)
    assert c.calls[0][1] == {"user": "0xabc", "type": "TRADE", "start": 1700000000, "limit": 1000}
