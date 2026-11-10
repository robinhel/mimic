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
    assert isinstance(db.search_kalshi(conn, 'Jr.: 5+ "threes" -x'), list)
