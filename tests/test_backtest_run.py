from pathlib import Path

from copycheck import backtest, db

FIXTURES = Path(__file__).parent / "fixtures"
DAY = 86400
TRAIN, TEST_END = (0, 100 * DAY), 160 * DAY


class KalshiClient:
    def __init__(self):
        self.calls = []

    def get_json(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        if url.endswith("/prices-history"):  # Polymarket: ett mittpris 10 s före signalen
            return {"history": [{"t": params["startTs"] + DAY - 10, "p": 0.42}]}
        if url.endswith("/candlesticks"):
            t = params["start_ts"] + DAY
            c = {"end_period_ts": t - 10, "yes_bid": {"close_dollars": "0.40"},
                 "yes_ask": {"close_dollars": "0.44"}}  # fmt: skip
            return {"markets": [{"market_ticker": params["market_tickers"], "candlesticks": [c]}]}
        return {"market": {"yes_bid_dollars": "0.50", "yes_ask_dollars": "0.52"}}


def setup():
    conn = db.connect(":memory:")
    db.upsert_trader(conn, "w", "w", "month:PNL", 0, 0)
    db.upsert_positions(conn, [
        {"proxy_wallet": "w", "token_id": f"t{i}", "condition_id": f"x{i}", "avg_price": 0.5,
         "total_size": 20, "realized_pnl": 2, "last_event_at": 50 * DAY}
        for i in range(60)
    ])  # fmt: skip
    rows = [
        ("c1", 0, 110 * DAY, "K1", "yes", 0),   # matchad, avgjord
        ("c2", 0, 120 * DAY, "K2", "", None),   # matchad, öppen
        ("c3", 0, 130 * DAY, None, None, None),  # ingen matchning
        ("c4", 0, 50 * DAY, "K4", "yes", 0),    # träningsperioden, räknas inte
    ]  # fmt: skip
    for cid, idx, ts, ticker, result, pm_result in rows:
        conn.execute(
            """INSERT INTO signals (wallet, condition_id, token_id, outcome_index, avg_price,
                   usdc, first_ts, trigger_ts, last_ts, n_fills)
               VALUES ('w', ?, ?, ?, 0.42, 300, ?, ?, ?, 1)""",
            (cid, cid + "tok", idx, ts, ts, ts),
        )
        conn.execute(
            """INSERT INTO pm_markets (condition_id, question, end_ts, result_index, outcomes,
                   fee_rate) VALUES (?, 'q', ?, ?, '["Yes","No"]', 0.05)""",
            (cid, ts + 10 * DAY, pm_result),
        )
        if ticker:
            conn.execute(
                """INSERT INTO matches (pm_condition, kalshi_ticker, level, outcome0_side, reason,
                       model, judged_ts) VALUES (?, ?, 'exact', 'yes', '', 'm', 0)""",
                (cid, ticker),
            )
            conn.execute(
                """INSERT INTO kalshi_markets (ticker, event_ticker, series_ticker, close_ts,
                       result, source) VALUES (?, 'E', 'S', ?, ?, 'live')""",
                (ticker, ts + 10 * DAY, result),
            )
    conn.commit()
    return conn


def test_run_skriver_en_rad_per_signal_strategi_och_fordrojning():
    conn = setup()
    client = KalshiClient()
    backtest.run(conn, client, "https://k", *TRAIN, TEST_END, backtest.Config(), top=5,
                 log=lambda *a: None)  # fmt: skip
    n = len(backtest.DELAYS) * len(backtest.STRATEGIES)
    rows = conn.execute(
        """SELECT venue, kalshi_ticker, skip_reason, exit_kind, COUNT(*) FROM sim_trades
           GROUP BY 1, 2, 3, 4"""
    ).fetchall()
    # Polymarket simuleras för alla signaler, Kalshi bara där det finns en matchning.
    assert sorted(rows, key=str) == sorted([
        ("kalshi", "K1", None, "settled", n), ("kalshi", "K2", None, "open", n),
        ("kalshi", None, "no_match", None, n),
        ("polymarket", None, None, "settled", n), ("polymarket", None, None, "open", 2 * n),
    ], key=str)  # fmt: skip
    # körs igen utan dubbletter
    backtest.run(conn, client, "https://k", *TRAIN, TEST_END, backtest.Config(), top=5,
                 log=lambda *a: None)  # fmt: skip
    assert conn.execute("SELECT COUNT(*) FROM sim_trades").fetchone()[0] == 6 * n


def test_run_anvander_kalshis_stangningstid():
    conn = setup()  # PM:s slutdatum ligger 10 dagar efter signalen
    conn.execute(
        """UPDATE kalshi_markets SET close_ts = (SELECT trigger_ts + 60 FROM signals s
           JOIN matches m ON m.pm_condition = s.condition_id WHERE m.kalshi_ticker = 'K1')
           WHERE ticker = 'K1'"""
    )
    backtest.run(conn, KalshiClient(), "https://k", *TRAIN, TEST_END, backtest.Config(), top=5,
                 log=lambda *a: None)  # fmt: skip
    got = dict(conn.execute(
        "SELECT delay, MAX(skip_reason) FROM sim_trades WHERE kalshi_ticker = 'K1' GROUP BY 1"
    ))  # fmt: skip
    assert got == {0: None, 30: None, 120: "closed", 600: "closed"}


def test_avvisad_matchning_anvands_inte():
    conn = setup()
    conn.execute("UPDATE matches SET review_ok = 0 WHERE kalshi_ticker = 'K1'")
    backtest.run(conn, KalshiClient(), "https://k", *TRAIN, TEST_END, backtest.Config(), top=5,
                 log=lambda *a: None)  # fmt: skip
    assert (
        conn.execute("SELECT COUNT(*) FROM sim_trades WHERE kalshi_ticker = 'K1'").fetchone()[0]
        == 0
    )
