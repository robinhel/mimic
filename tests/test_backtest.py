import json
from decimal import Decimal
from pathlib import Path

import pytest

from copycheck import backtest, db

FIXTURES = Path(__file__).parent / "fixtures"
D = Decimal


def candles():
    return json.loads((FIXTURES / "kalshi_candles_batch.json").read_text())["markets"][0][
        "candlesticks"
    ]


def test_quote_at_tar_senaste_candle_och_alder():
    c = candles()
    last = c[-1]
    q = backtest.quote_at(c, last["end_period_ts"] + 100)
    assert q["yes_ask"] == D(last["yes_ask"]["close_dollars"])
    assert q["yes_bid"] == D(last["yes_bid"]["close_dollars"])
    assert q["age"] == 100
    assert backtest.quote_at(c, c[0]["end_period_ts"] - 1) is None


def sig(**kw):
    base = dict(
        signal_id=1, wallet="w", trigger_ts=1000, avg_price=0.40, outcome_index=0,
        pm_end_ts=1000 + 86400, pm_result_index=0, kalshi_ticker="K", outcome0_side="yes",
        kalshi_result="yes", category="Sports",
    )  # fmt: skip
    base.update(kw)
    return base


def flat(yes_bid, yes_ask, ts=990):
    return [{"end_period_ts": ts, "yes_bid": {"close_dollars": yes_bid},
             "yes_ask": {"close_dollars": yes_ask}}]  # fmt: skip


CFG = backtest.Config(amount=D(10), slippage=D("0.01"), max_gap=D("0.05"), stale_after=900)


def test_kop_yes_och_hall_till_avgorande():
    r = backtest.simulate(sig(), flat("0.40", "0.44"), sells=[], delay=0, strategy="A", cfg=CFG)
    # pris 0.45 med slippage, 22 kontrakt, avgift ceil(0.07*22*0.45*0.55*100)/100 = 0.39
    assert (r["entry_price"], r["contracts"], r["fee_in"]) == (D("0.45"), 22, D("0.39"))
    assert r["exit_kind"] == "settled" and r["exit_price"] == 1
    assert r["pnl"] == 22 * (1 - D("0.45")) - D("0.39")
    assert r["mismatch"] == 0 and r["stale"] == 0


def test_no_sidan_anvander_ett_minus_yes_bid():
    s = sig(outcome_index=1, kalshi_result="yes", pm_result_index=0)
    r = backtest.simulate(s, flat("0.40", "0.44"), [], 0, "A", CFG)
    assert r["side"] == "no"
    assert r["entry_price"] == D("0.61")  # 1 - 0.40 + 0.01
    assert r["exit_price"] == 0


def test_kort_marknad_hoppas_over():
    r = backtest.simulate(sig(pm_end_ts=1000 + 1800), flat("0.4", "0.44"), [], 0, "A", CFG)
    assert r["skip_reason"] == "short_market"


def test_kort_marknad_raknas_fran_kalshis_stangning():
    # Gammas slutdatum ligger ofta en vecka efter matchen. Kalshis close_ts är rätt.
    s = sig(pm_end_ts=1000 + 7 * 86400, kalshi_close_ts=1000 + 1800)
    assert backtest.simulate(s, flat("0.4", "0.44"), [], 0, "A", CFG)["skip_reason"] == (
        "short_market"
    )
    # Signal efter att Kalshi stängt: får inte köpas till sista priset före stängningen.
    s = sig(pm_end_ts=1000 + 7 * 86400, kalshi_close_ts=1000 - 60)
    assert backtest.simulate(s, flat("0.4", "0.44"), [], 0, "A", CFG)["skip_reason"] == (
        "short_market"
    )
    s = sig(pm_end_ts=1000 + 1800, kalshi_close_ts=1000 + 86400)
    assert backtest.simulate(s, flat("0.4", "0.44"), [], 0, "A", CFG)["skip_reason"] is None


def test_gammalt_pris_markeras_stale():
    r = backtest.simulate(sig(), flat("0.4", "0.44", ts=1000 - 2000), [], 0, "A", CFG)
    assert r["stale"] == 1


def test_inget_pris_hoppas_over():
    r = backtest.simulate(sig(), [], [], 0, "A", CFG)
    assert r["skip_reason"] == "no_price"


def test_cap_hoppar_over_nar_priset_sprungit():
    r = backtest.simulate(sig(avg_price=0.30), flat("0.40", "0.44"), [], 0, "A_cap", CFG)
    assert r["skip_reason"] == "price_ran"
    assert backtest.simulate(sig(avg_price=0.30), flat("0.40", "0.44"), [], 0, "A", CFG)["pnl"]


def test_strategi_b_saljer_nar_tradern_saljer():
    c = flat("0.40", "0.44") + flat("0.60", "0.62", ts=5000)
    r = backtest.simulate(sig(), c, sells=[5100], delay=30, strategy="B", cfg=CFG)
    assert r["exit_kind"] == "sold"
    assert r["exit_price"] == D("0.59")  # bid 0.60 - slippage
    assert r["fee_out"] > 0


def test_oppen_marknad_varderas_med_bid():
    s = sig(kalshi_result="", pm_result_index=None)
    r = backtest.simulate(s, flat("0.40", "0.44"), [], 0, "A", CFG, open_bid=D("0.50"))
    assert r["exit_kind"] == "open" and r["exit_price"] == D("0.50")


def test_olika_avgorande_flaggas():
    r = backtest.simulate(sig(kalshi_result="no"), flat("0.40", "0.44"), [], 0, "A", CFG)
    assert r["mismatch"] == 1


def test_valj_traders_pa_traningsperioden():
    conn = db.connect(":memory:")
    for w, pnl, n in [("bra", 30, 60), ("dalig", -10, 60), ("fa", 90, 10), ("bot", 90, 60)]:
        db.upsert_trader(conn, w, w, "month:PNL", 0, 0)
        db.upsert_positions(conn, [
            {"proxy_wallet": w, "token_id": f"{w}{i}", "condition_id": f"c{i}", "avg_price": 0.5,
             "total_size": 200, "realized_pnl": pnl, "last_event_at": 500 if i else 5000}
            for i in range(n)
        ])  # fmt: skip
    conn.execute("UPDATE traders SET is_bot = 1 WHERE wallet = 'bot'")
    got = backtest.select_traders(conn, 0, 1000, min_markets=50, top=5)
    assert [w for w, *_ in got] == ["bra", "dalig"]
    assert got[0][1] == pytest.approx(30 / 100)  # vinst / insats
