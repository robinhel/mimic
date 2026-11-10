from copycheck import db, report


def setup(trades):
    """trades: (signal_id, delay, strategy, pnl, cost, skip_reason)"""
    conn = db.connect(":memory:")
    for sid in {t[0] for t in trades}:
        conn.execute(
            """INSERT INTO signals (id, wallet, condition_id, token_id, outcome_index, avg_price,
                   usdc, first_ts, trigger_ts, last_ts, n_fills)
               VALUES (?, 'w', ?, 't', 0, 0.5, 300, 0, 0, 0, 1)""",
            (sid, f"c{sid}"),
        )
        conn.execute(
            """INSERT INTO pm_markets (condition_id, question, result_index, outcomes, category)
               VALUES (?, 'q', ?, '["Yes","No"]', 'Sports')""",
            (f"c{sid}", sid % 2),
        )
    for sid, delay, st, pnl, cost, skip in trades:
        conn.execute(
            """INSERT INTO sim_trades (signal_id, strategy, delay, pnl, cost, entry_price, stale,
                   exit_kind, mismatch, skip_reason)
               VALUES (?, ?, ?, ?, ?, 0.52, 0, 'settled', 0, ?)""",
            (sid, st, delay, pnl, cost, skip),
        )
    return conn


def test_roi_tackning_och_slippage():
    conn = setup(
        [(1, 0, "A", 5, 10, None), (2, 0, "A", -10, 10, None), (3, 0, "A", None, None, "no_match")]
    )
    rows = report.summary(conn, by="wallet")
    r = next(x for x in rows if x["group"] == "w" and x["delay"] == 0 and x["strategy"] == "A")
    assert r["signals"] == 3 and r["trades"] == 2
    assert round(r["coverage"], 3) == round(2 / 3, 3)
    assert r["roi"] == -5 / 20
    assert round(r["slippage"], 4) == 0.02


def test_pm_jamforelse_traderns_eget_resultat():
    # signal 1: result_index 1 != outcome 0 -> förlust; signal 2: result 0 -> vinst (10/0.5 = 20)
    conn = setup([(1, 0, "A", 0, 10, None), (2, 0, "A", 0, 10, None)])
    assert report.pm_roi(conn)["w"] == (20 - 20) / 20


def test_bootstrap_ar_deterministiskt_och_tackar_roi():
    pnl, cost = [1, -1, 2, -0.5] * 10, [10] * 40
    lo, hi = report.bootstrap_ci(pnl, cost, n=500, seed=1)
    assert lo < sum(pnl) / sum(cost) < hi
    assert (lo, hi) == report.bootstrap_ci(pnl, cost, n=500, seed=1)


def test_beslut():
    assert report.verdict(-0.10, -0.05, 250).startswith("Tydligt negativt")
    assert report.verdict(0.05, 0.10, 250).startswith("Tydligt positivt")
    assert report.verdict(-0.05, 0.05, 250).startswith("Oklart")
    assert "för få" in report.verdict(-0.1, -0.05, 50)


def test_markdown_innehaller_tabeller():
    conn = setup([(1, 120, "A", 5, 10, None), (2, 120, "A", -1, 10, None)])
    text = report.render(conn, now=1794311314)
    assert "| delay |" in text.lower() or "| fördröjning |" in text.lower()
    assert "Beslut" in text
