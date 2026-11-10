from copycheck import db, ranking

DAY = 86400


def trade(wallet, i, condition="c1", outcome_index=0, ts=0, side="BUY"):
    return {
        "proxy_wallet": wallet, "transaction_hash": f"0x{i}", "condition_id": condition,
        "token_id": f"{condition}-{outcome_index}", "outcome": "Yes",
        "outcome_index": outcome_index,
        "side": side, "price": 0.5, "size": 10, "usdc_size": 5, "timestamp": ts,
        "title": "t", "slug": "s", "event_slug": "e",
    }  # fmt: skip


def position(wallet, i, cost, pnl):
    return {
        "proxy_wallet": wallet, "token_id": f"t{i}", "condition_id": f"c{i}", "outcome": "Yes",
        "avg_price": 0.5, "total_size": cost / 0.5, "realized_pnl": pnl,
        "first_entry_at": 0, "last_event_at": 0, "end_date": "2026-01-01", "title": "t",
        "slug": "s",
    }  # fmt: skip


def setup(conn, wallet, trades, positions=()):
    db.upsert_trader(conn, wallet, wallet, "month:PNL", 0, 0)
    db.insert_activity(conn, trades, seen_ts=0)
    db.upsert_positions(conn, list(positions))


def flags(conn):
    ranking.flag_bots(conn)
    return dict(conn.execute("SELECT wallet, bot_reason FROM traders"))


def test_vanlig_trader_ar_inte_bot():
    conn = db.connect(":memory:")
    setup(
        conn, "ok", [trade("ok", i, f"c{i}", ts=i * DAY) for i in range(30)],
        [position("ok", i, 100, 20) for i in range(10)],
    )  # fmt: skip
    assert flags(conn) == {"ok": None}


def test_manga_affarer_per_dag_ar_bot():
    conn = db.connect(":memory:")
    setup(conn, "fast", [trade("fast", i, f"c{i}", ts=i * 60) for i in range(500)])
    assert "affärer/dag" in flags(conn)["fast"]


def test_bada_sidor_i_samma_marknad_ar_bot():
    conn = db.connect(":memory:")
    trades = [
        trade("mm", 2 * i + k, f"c{i}", outcome_index=k, ts=i * DAY)
        for i in range(10)
        for k in (0, 1)
    ]
    setup(conn, "mm", trades)
    assert "båda sidor" in flags(conn)["mm"]


def test_liten_vinst_per_krona_ar_bot():
    conn = db.connect(":memory:")
    setup(
        conn, "thin", [trade("thin", i, f"c{i}", ts=i * DAY) for i in range(30)],
        [position("thin", i, 10000, 10) for i in range(60)],
    )  # fmt: skip
    assert "marginal" in flags(conn)["thin"]


def test_avkortad_aktivitet_ar_bot():
    conn = db.connect(":memory:")
    setup(conn, "big", [trade("big", 1, ts=0)])
    conn.execute("UPDATE traders SET activity_truncated = 1")
    assert "avkortad" in flags(conn)["big"]


def test_avkortade_positioner_ar_bot():
    conn = db.connect(":memory:")
    setup(conn, "many", [trade("many", 1, ts=0)])
    conn.execute("UPDATE traders SET positions_truncated = 1")
    assert "positioner" in flags(conn)["many"]
