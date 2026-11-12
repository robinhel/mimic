import json
from decimal import Decimal
from pathlib import Path

import requests

from copycheck import db, kalshi, live, polymarket

FIXTURES = Path(__file__).parent / "fixtures"
BOOK = json.loads((FIXTURES / "kalshi_orderbook.json").read_text())
PM_BOOK = json.loads((FIXTURES / "pm_book.json").read_text())  # riktig, Gen.G Worlds 2026-11-12
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
        self.book_error = False

    def get_json(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        if url.endswith("/activity"):
            return {"data": self.fills, "pagination": {"next_cursor": None}}
        if url.endswith("/orderbook"):
            return BOOK
        if url.endswith("/book"):
            if self.book_error:
                raise requests.HTTPError("404 No orderbook exists")
            return PM_BOOK
        if url.endswith("/markets"):  # Gamma: inget nytt, raden i pm_markets gäller
            return []
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
    assert sum(u.endswith("/book") for u, _ in client.calls) == 1


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


def test_polymarket_basta_bud_och_utbud():
    # Buden står stigande och utbudet fallande, så bästa priset ligger sist i båda listorna.
    assert polymarket.best_bid_ask(PM_BOOK) == (
        Decimal("0.62"),
        Decimal("0.63"),
        Decimal("207524.61"),
    )
    assert polymarket.best_bid_ask({"bids": [], "asks": []}) == (None, None, None)


def test_tick_sparar_polymarket_orderbok_for_kop_och_salj():
    # Robins flöde: köp när tradern köper, sälj när tradern säljer. Båda behöver priset.
    conn = setup()
    fills = [fill(NOW - 20, token="a", i=1), fill(NOW - 20, token="b", side="SELL", i=2)]
    fills[0]["condition_id"] = "c9"  # ingen Kalshi-matchning, ska ändå sparas
    live.tick(conn, Client(fills), "https://k", ["w"], now=NOW)
    rows = conn.execute(
        "SELECT token_id, ts, bid, ask, ask_size FROM pm_quotes ORDER BY 1"
    ).fetchall()
    assert rows == [("a", NOW, 0.62, 0.63, 207524.61), ("b", NOW, 0.62, 0.63, 207524.61)]
    seen = conn.execute("SELECT token_id, kalshi_ticker FROM live_seen ORDER BY 1").fetchall()
    assert seen == [("a", None), ("b", None)]


def test_saknad_polymarket_orderbok_stoppar_inte_rundan():
    conn = setup()
    client = Client([fill(NOW - 20)])
    client.book_error = True  # stängd marknad: 404 "No orderbook exists"
    live.tick(conn, client, "https://k", ["w"], now=NOW)
    assert conn.execute("SELECT COUNT(*) FROM live_seen").fetchone() == (1,)
    assert conn.execute("SELECT COUNT(*) FROM pm_quotes").fetchone() == (0,)
    assert conn.execute("SELECT status FROM heartbeats").fetchone() == ("ok",)


def test_statussida_visar_senaste_heartbeat_och_antal(tmp_path):
    # En Box-tjänst måste svara på $PORT. Sidan visar också om livetestet lever.
    path = str(tmp_path / "live.db")
    conn = db.connect(path)
    live.tick(conn, Client([fill(NOW - 20)]), "https://k", ["w"], now=NOW)
    server = live.serve_status(path, port=0)
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        text = requests.get(url, timeout=5).text
    finally:
        server.shutdown()
    assert "senaste runda: 2027-01-15 08:00:00 UTC ok" in text
    assert "affärer sedda: 1" in text and "orderböcker Polymarket: 1" in text


def test_efter_paus_hamtas_affarer_sedan_senaste_rundan():
    # Orben pausar i timmar. Affärer under pausen ska hämtas och markeras sena.
    conn = setup()
    live.heartbeat(conn, NOW - 7 * 3600, "ok")
    client = Client([fill(NOW - 5 * 3600)])
    live.tick(conn, client, "https://k", ["w"], now=NOW)
    starts = [p["start"] for u, p in client.calls if u.endswith("/activity")]
    assert starts == [NOW - 7 * 3600]
    assert conn.execute("SELECT late FROM live_seen").fetchone() == (1,)


# --- Pappershandel: gör som en riktig bot, i samma ögonblick som vi ser köpet ---

MARKET = PM_BOOK["market"]


def paper_setup(result_index=None):
    conn = setup()
    conn.execute(
        """INSERT INTO pm_markets (condition_id, closed, result_index, outcome0_token,
               outcome1_token, fee_rate) VALUES (?, ?, ?, 'tok', 'annan', 0.04)""",
        (MARKET, int(result_index is not None), result_index),
    )
    return conn


def buy(ts, price=0.62, usdc=300, i=1):
    f = fill(ts, i=i)
    f["price"], f["usdc_size"] = price, usdc
    return f


def paper(conn):
    return conn.execute(
        """SELECT status, skip_reason, shares, entry_price, cost, proceeds
           FROM paper_trades"""
    ).fetchall()


def test_kop_gar_igenom_orderboken_niva_for_niva():
    book = {"asks": [{"price": "0.6", "size": "100"}, {"price": "0.5", "size": "4"}]}
    assert polymarket.fill_buy(book, Decimal(10)) == [
        (Decimal("0.5"), Decimal("4")),
        (Decimal("0.6"), Decimal("13.33")),  # 8 dollar kvar / 0.6, avrundat nedåt
    ]


def test_salj_tar_hogsta_budet_forst():
    book = {"bids": [{"price": "0.4", "size": "5"}, {"price": "0.45", "size": "3"}]}
    assert polymarket.fill_sell(book, Decimal(6)) == [
        (Decimal("0.45"), Decimal("3")),
        (Decimal("0.4"), Decimal("3")),
    ]


def test_kop_nar_traderns_kop_passerar_250_dollar():
    # Samma regel som backtestet: under 250 dollar händer inget, sedan köper vi direkt.
    conn = paper_setup()
    client = Client([buy(NOW - 5, usdc=100, i=1)])
    live.tick(conn, client, "https://k", ["w"], now=NOW)
    assert paper(conn) == []
    client.fills = [buy(NOW + 1, usdc=200, i=2)]
    live.tick(conn, client, "https://k", ["w"], now=NOW + 3)
    # 10 dollar / 0.63 = 15.87 andelar. Avgift 0.04 * 15.87 * 0.63 * 0.37 = 0.14797.
    assert paper(conn) == [("open", None, 15.87, 0.63, 10.14607, 0.0)]
    assert live.cash(conn) == Decimal("989.85393")


def test_salj_mot_buden_nar_tradern_saljer():
    conn = paper_setup()
    client = Client([buy(NOW - 5)])
    live.tick(conn, client, "https://k", ["w"], now=NOW)
    client.fills = [fill(NOW + 60, side="SELL", i=9)]
    live.tick(conn, client, "https://k", ["w"], now=NOW + 62)
    # 15.87 * 0.62 = 9.8394, minus avgift 0.04 * 15.87 * 0.62 * 0.38 = 0.14956.
    assert paper(conn) == [("sold", None, 15.87, 0.63, 10.14607, 9.68984)]


def test_avgjord_marknad_betalar_ut():
    conn = paper_setup()
    live.tick(conn, Client([buy(NOW - 5)]), "https://k", ["w"], now=NOW)
    conn.execute("UPDATE pm_markets SET closed = 1, result_index = 0")  # 'tok' vann
    live.settle(conn, Client([]), now=NOW + 3600)
    assert paper(conn)[0][0] == "settled"
    assert paper(conn)[0][5] == 15.87


def test_kop_som_inte_gar_att_gora_hoppas_over_med_skal():
    cases = [
        (buy(NOW - 600), "late"),  # vi såg köpet för sent
        (buy(NOW - 5, price=0.5), "price_ran"),  # priset har stigit mer än 5 cent
        (buy(NOW - 5, price=0.05), "longshot"),  # under 10 cent
    ]
    for f, reason in cases:
        conn = paper_setup()
        live.tick(conn, Client([f]), "https://k", ["w"], now=NOW)
        assert [r[:2] for r in paper(conn)] == [("skipped", reason)], reason
        assert live.cash(conn) == live.START_CASH
