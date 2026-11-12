import json
import sqlite3
from pathlib import Path

from copycheck import db

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_rows(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())["data"]


def test_schema_och_wal(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"traders", "pm_activity", "pm_positions"} <= tables


def test_aktivitet_och_positioner_kan_sparas_igen_utan_dubbletter():
    conn = db.connect(":memory:")
    act = fixture_rows("pm_activity")
    pos = fixture_rows("pm_positions_closed")
    for _ in range(2):
        db.upsert_trader(conn, "0xw", "namn", "month:PNL", 1.0, 2.0)
        db.insert_activity(conn, act, seen_ts=123)
        db.upsert_positions(conn, pos)
    assert conn.execute("SELECT COUNT(*) FROM traders").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM pm_activity").fetchone()[0] == len(act)
    assert conn.execute("SELECT COUNT(*) FROM pm_positions").fetchone()[0] == len(pos)


def test_aktivitet_sparar_avrundat_pris_och_tider():
    conn = db.connect(":memory:")
    db.insert_activity(conn, fixture_rows("pm_activity")[:1], seen_ts=999)
    price, trade_ts, seen_ts = conn.execute(
        "SELECT price, trade_ts, seen_ts FROM pm_activity"
    ).fetchone()
    assert price == 0.09
    assert trade_ts == 1794306829
    assert seen_ts == 999


def test_upsert_trader_slar_ihop_kallor():
    conn = db.connect(":memory:")
    db.upsert_trader(conn, "0xw", "a", "month:PNL", 1.0, 2.0)
    db.upsert_trader(conn, "0xw", "a", "all:VOLUME", None, None)
    db.upsert_trader(conn, "0xw", "a", "month:PNL", None, None)
    assert conn.execute("SELECT sources FROM traders").fetchone()[0] == "all:VOLUME,month:PNL"


def test_senaste_affar():
    conn = db.connect(":memory:")
    assert db.last_trade_ts(conn, "0xw") is None
    rows = fixture_rows("pm_activity")
    db.insert_activity(conn, rows, seen_ts=1)
    wallet = rows[0]["proxy_wallet"]
    assert db.last_trade_ts(conn, wallet) == max(r["timestamp"] for r in rows)


def test_gammal_databas_far_nya_kolumner(tmp_path):
    path = tmp_path / "gammal.db"
    old = sqlite3.connect(path)
    old.executescript(
        """CREATE TABLE pm_markets (condition_id TEXT PRIMARY KEY, question TEXT);
           INSERT INTO pm_markets VALUES ('c', 'q');
           CREATE TABLE sim_trades (signal_id INTEGER, strategy TEXT, delay INTEGER);
           INSERT INTO sim_trades VALUES (1, 'A', 0);"""
    )
    old.commit()
    old.close()
    conn = db.connect(str(path))
    assert conn.execute("SELECT question, fee_rate, closed_ts FROM pm_markets").fetchall() == [
        ("q", None, None)
    ]
    cols = [r[1] for r in conn.execute("PRAGMA table_info(sim_trades)")]
    assert "venue" in cols


def test_gammal_live_seen_tillater_rader_utan_kalshi(tmp_path):
    path = tmp_path / "gammal.db"
    old = sqlite3.connect(path)
    old.execute(
        """CREATE TABLE live_seen (wallet TEXT NOT NULL, tx_hash TEXT NOT NULL,
               token_id TEXT NOT NULL, trade_ts INTEGER NOT NULL, seen_ts INTEGER NOT NULL,
               late INTEGER NOT NULL, kalshi_ticker TEXT NOT NULL,
               PRIMARY KEY (wallet, tx_hash, token_id))"""
    )
    old.commit()
    old.close()
    conn = db.connect(str(path))
    conn.execute("INSERT INTO live_seen VALUES ('w', 'x', 't', 1, 2, 0, NULL)")
