import json
from decimal import Decimal
from pathlib import Path

from copycheck import db, kalshi, live

FIXTURES = Path(__file__).parent / "fixtures"
BOOK = json.loads((FIXTURES / "kalshi_orderbook.json").read_text())
NOW = 1_800_000_000


def fill(ts, token="tok", side="BUY", i=1):
    return {
        "proxy_wallet": "w", "transaction_hash": f"0x{i}", "condition_id": "c1", "token_id": token,
        "outcome": "Yes", "outcome_index": 0, "side": side, "price": 0.5, "size": 600,
        "usdc_size": 300, "timestamp": ts, "title": "t", "slug": "s", "event_slug": "e",
    }  # fmt: skip


class Client:
    def __init__(self, fills):
        self.fills = fills
        self.calls = []

    def get_json(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        if url.endswith("/activity"):
            return {"data": self.fills, "pagination": {"next_cursor": None}}
        if url.endswith("/orderbook"):
            return BOOK
        raise AssertionError(url)


def setup():
    conn = db.connect(":memory:")
    db.upsert_trader(conn, "w", "w", "month:PNL", 0, 0)
    conn.execute(
        """INSERT INTO matches (pm_condition, kalshi_ticker, level, outcome0_side, reason, model,
               judged_ts) VALUES ('c1', 'K1', 'exact', 'yes', '', 'm', 0)"""
    )
    return conn


def test_orderbok_yes_bid():
    best = max(Decimal(p) for p, _ in BOOK["orderbook_fp"]["yes_dollars"])
    assert kalshi.orderbook_yes_bid(BOOK) == best


def test_tick_sparar_affar_orderbok_och_heartbeat():
    conn = setup()
    client = Client([fill(NOW - 20)])
    live.tick(conn, client, "https://k", ["w"], now=NOW)
    assert conn.execute("SELECT seen_ts FROM pm_activity").fetchone() == (NOW,)
    q = conn.execute("SELECT ticker, ts, yes_ask, source FROM kalshi_quotes").fetchone()
    assert q == ("K1", NOW, float(kalshi.orderbook_yes_ask(BOOK)), "orderbook")
    seen = conn.execute("SELECT kalshi_ticker, late FROM live_seen").fetchone()
    assert seen == ("K1", 0)
    assert conn.execute("SELECT component, status FROM heartbeats").fetchone() == ("live", "ok")


def test_sen_upptackt_markeras_late():
    conn = setup()
    live.tick(conn, Client([fill(NOW - 600)]), "https://k", ["w"], now=NOW)
    assert conn.execute("SELECT late FROM live_seen").fetchone() == (1,)


def test_samma_affar_tva_ganger_ger_en_orderbok():
    conn = setup()
    client = Client([fill(NOW - 20)])
    live.tick(conn, client, "https://k", ["w"], now=NOW)
    live.tick(conn, client, "https://k", ["w"], now=NOW + 30)
    assert sum(u.endswith("/orderbook") for u, _ in client.calls) == 1


def test_omatchad_eller_salj_ger_ingen_orderbok():
    conn = setup()
    client = Client([fill(NOW - 20, token="annan", i=2), fill(NOW - 20, side="SELL", i=3)])
    client.fills[0]["condition_id"] = "c2"
    live.tick(conn, client, "https://k", ["w"], now=NOW)
    assert not any(u.endswith("/orderbook") for u, _ in client.calls)


def test_fel_skrivs_i_heartbeat():
    conn = setup()

    class Broken:
        def get_json(self, url, params=None):
            raise RuntimeError("nere")

    live.tick(conn, Broken(), "https://k", ["w"], now=NOW)
    status = conn.execute("SELECT status FROM heartbeats").fetchone()[0]
    assert status.startswith("error") and "nere" in status
