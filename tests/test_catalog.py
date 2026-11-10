import json
from pathlib import Path

from copycheck import db

FIXTURES = Path(__file__).parent / "fixtures"


def markets():
    return json.loads((FIXTURES / "kalshi_markets_no_mve.json").read_text())["markets"]


def test_marknader_sparas_utan_dubbletter_och_gar_att_soka():
    conn = db.connect(":memory:")
    rows = markets()
    for _ in range(2):
        db.upsert_kalshi_markets(conn, rows, source="live", categories={})
    db.rebuild_kalshi_search(conn)
    assert conn.execute("SELECT COUNT(*) FROM kalshi_markets").fetchone()[0] == len(rows)
    word = rows[0]["title"].split()[0].strip(":")
    hits = db.search_kalshi(conn, word)
    assert rows[0]["ticker"] in [h["ticker"] for h in hits]


def test_marknad_sparar_serie_kategori_och_tider():
    conn = db.connect(":memory:")
    m = markets()[0]
    db.upsert_kalshi_markets(conn, [m], source="historical", categories={"KXNBA3PTPROT": "Sports"})
    row = conn.execute(
        "SELECT series_ticker, category, close_ts, source FROM kalshi_markets"
    ).fetchone()
    assert row == ("KXNBA3PTPROT", "Sports", 1794529800, "historical")


def test_sok_klarar_specialtecken():
    conn = db.connect(":memory:")
    db.upsert_kalshi_markets(conn, markets(), source="live", categories={})
    db.rebuild_kalshi_search(conn)
    assert isinstance(db.search_kalshi(conn, 'Jr.: 5+ "threes" -x'), list)


class RoutingClient:
    def __init__(self):
        self.calls = []

    def get_json(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        if url.endswith("/series"):
            return json.loads((FIXTURES / "kalshi_series.json").read_text())
        rows = markets()
        hourly = {**rows[0], "ticker": "KXGOLDH-1-T1", "event_ticker": "KXGOLDH-1"}
        if "/historical/" in url:
            return {"markets": [rows[0], hourly], "cursor": ""}
        return {"markets": rows, "cursor": ""}


def test_catalog_hamtar_historik_och_live_utan_timserier():
    from copycheck import cli

    conn = db.connect(":memory:")
    client = RoutingClient()
    cli.catalog(client, conn, "https://k/v2", days=150, now=1794311314, log=lambda *a: None)
    tickers = {t for (t,) in conn.execute("SELECT ticker FROM kalshi_markets")}
    assert tickers == {m["ticker"] for m in markets()}
    assert "KXGOLDH-1-T1" not in tickers
    assert {p["min_close_ts"] for u, p in client.calls if "markets" in u} == {
        1794311314 - 150 * 86400
    }
    assert db.search_kalshi(conn, "threes")


def test_catalog_slanger_gamla_marknader_fran_historiken():
    """/historical/markets ignorerar min_close_ts (lucka 47), så vi filtrerar själva."""
    from copycheck import cli

    class OldClient(RoutingClient):
        def get_json(self, url, params=None):
            body = super().get_json(url, params)
            if "/historical/" in url:
                old = {**markets()[0], "ticker": "KXOLD-1-T1", "close_time": "2024-11-06T16:00:00Z"}
                body = {"markets": body["markets"] + [old], "cursor": ""}
            return body

    conn = db.connect(":memory:")
    cli.catalog(OldClient(), conn, "https://k/v2", days=150, now=1794311314, log=lambda *a: None)
    tickers = {t for (t,) in conn.execute("SELECT ticker FROM kalshi_markets")}
    assert "KXOLD-1-T1" not in tickers
