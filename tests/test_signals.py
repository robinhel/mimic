from copycheck import db, signals

MIN = 60


def fill(i, ts, usdc, price=0.5, token="t1", side="BUY", wallet="w"):
    return {
        "proxy_wallet": wallet, "transaction_hash": f"0x{i}", "condition_id": "c1",
        "token_id": token, "outcome": "Yes", "outcome_index": 0, "side": side,
        "price": price, "size": usdc / price, "usdc_size": usdc, "timestamp": ts,
        "title": "t", "slug": "s", "event_slug": "e",
    }  # fmt: skip


def build(fills, bot=False):
    conn = db.connect(":memory:")
    db.upsert_trader(conn, "w", "w", "month:PNL", 0, 0)
    conn.execute("UPDATE traders SET is_bot = ?", (int(bot),))
    db.insert_activity(conn, fills, seen_ts=0)
    signals.build(conn, min_usd=250, window=10 * MIN)
    cur = conn.execute(
        "SELECT token_id, usdc, avg_price, first_ts, trigger_ts, last_ts, n_fills FROM signals"
    )
    return [tuple(r) for r in cur]


def test_fyllningar_inom_10_min_blir_en_signal():
    got = build([fill(1, 0, 100), fill(2, 5 * MIN, 100), fill(3, 14 * MIN, 100)])
    assert got == [("t1", 300, 0.5, 0, 14 * MIN, 14 * MIN, 3)]


def test_paus_over_10_min_ger_ny_signal_och_sma_tas_bort():
    got = build([fill(1, 0, 300), fill(2, 11 * MIN, 100)])
    assert got == [("t1", 300, 0.5, 0, 0, 0, 1)]


def test_trigger_nar_summan_passerar_gransen():
    got = build([fill(1, 0, 200), fill(2, 2 * MIN, 100), fill(3, 4 * MIN, 100)])
    assert got[0][4] == 2 * MIN


def test_snittpris_viktas_med_storlek():
    got = build([fill(1, 0, 100, price=0.4), fill(2, MIN, 200, price=0.5)])
    # size: 250 + 400 = 650 kontrakt för 300 USDC
    assert round(got[0][2], 4) == round(300 / 650, 4)


def test_salj_och_andra_token_slas_inte_ihop():
    got = build([fill(1, 0, 300), fill(2, MIN, 300, side="SELL"), fill(3, MIN, 300, token="t2")])
    assert sorted(r[0] for r in got) == ["t1", "t2"]


def test_bottar_far_inga_signaler():
    assert build([fill(1, 0, 300)], bot=True) == []


def test_kan_byggas_om():
    conn = db.connect(":memory:")
    db.upsert_trader(conn, "w", "w", "month:PNL", 0, 0)
    db.insert_activity(conn, [fill(1, 0, 300)], seen_ts=0)
    signals.build(conn, min_usd=250, window=600)
    signals.build(conn, min_usd=250, window=600)
    assert conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 1
