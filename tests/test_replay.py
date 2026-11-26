import json
import sys
from pathlib import Path

import pytest

from mimic import replay
from mimic.fees import fee_usd

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import export_replay as ex  # noqa: E402
import pm_livetest  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "replay"
SAMPLE = Path(__file__).parents[1] / "dashboard" / "public" / "data" / "replay_trades.json"
T, D = 1795000000, 86400  # 2026-11-18T11:06:40Z


def buy(p, ts, price=0.5, size=600, token="111", cid="c1"):
    return {"p": p, "token": token, "cid": cid, "idx": 0, "side": "BUY", "price": price,
            "size": size, "usd": price * size, "ts": ts, "title": "Canadiens vs. Rangers"}  # fmt: skip


def sell(p, ts, price, size, token="111"):
    return buy(p, ts, price, size, token) | {"side": "SELL"}


def market(closed=True, prices=(1.0, 0.0), end=T + 10 * D):
    return {"c1": {"title": "Gamma-titel", "end": end, "closed": closed, "prices": list(prices)}}


def run(fills, markets=None, history=None):
    return replay.trades(fills, markets or market(), history or {})


def test_avgift_samma_som_livetestet():
    for shares, p in [(20, 0.5), (18.181818, 0.55), (5, 0.8), (100, 0.55), (0.3, 0.01)]:
        assert fee_usd(shares, p) == pm_livetest.fee(shares, p, True)


def test_fordrojt_pris_nar_priset_foll_och_steg():
    # 5 s: senaste punkt 0.48 < 0.50 -> spelarens pris. 30 s: 0.55. 120 s: 0.45 -> 0.50.
    # 0.50: 20 andelar, avgift ceil(0.07*20*0.25) = 0.35, kostnad 10.35, tillbaka 20 -> 9.65.
    # 0.55: 18.1818 andelar, avgift 0.315 -> 0.32, kostnad 10.32, tillbaka 18.18 -> 7.86.
    hist = {"111": [(T + 100, 0.45), (T - 30, 0.48), (T + 20, 0.55)]}
    [t] = run([buy(0, T)], history=hist)
    assert t["cost"] == {"5": 10.35, "30": 10.32, "120": 10.35}
    assert t["result"] == {"5": 9.65, "30": 7.86, "120": 9.65}
    assert t["trader_price"] == 0.5 and t["state"] == "settled"
    assert t["t"] == "2026-11-18T11:06:40Z" and t["title"] == "Canadiens vs. Rangers"


def test_utan_prishistorik_spelarens_pris():
    [t] = run([buy(0, T)])
    assert t["cost"] == {"5": 10.35, "30": 10.35, "120": 10.35}


def test_delsalj_sedan_avgorande():
    # Säljer 150 av 600 (en fjärdedel) à 0.80: 5 andelar -> 4.00 - avgift 0.06 = 3.94.
    # Resten (15) förlorar. 3.94 - 10.35 = -6.41.
    [t] = run([buy(0, T), sell(0, T + 3600, 0.8, 150)], market(prices=(0, 1)))
    assert t["result"] == {"5": -6.41, "30": -6.41, "120": -6.41}
    assert t["state"] == "settled"


def test_allt_salt():
    # Halva à 0.60: 10 andelar, 6.00 - 0.17. Resten à 0.70: 7.00 - 0.15. 12.68 - 10.35 = 2.33.
    fills = [buy(0, T), sell(0, T + 60, 0.6, 300), sell(0, T + 120, 0.7, 300)]
    [t] = run(fills, market(prices=(0, 1)))
    assert t["result"]["5"] == 2.33 and t["state"] == "sold"


def test_salj_fore_signalen_raknas_inte():
    [t] = run([buy(0, T - 7200, size=100), sell(0, T - 3600, 0.9, 100), buy(0, T)])
    assert t["result"]["5"] == 9.65


def test_oppen_marknad_vardas_till_dagens_pris():
    [t] = run([buy(0, T)], market(closed=False, prices=(0.6, 0.4)))
    assert t["result"]["5"] == 1.65 and t["state"] == "open"


def test_marknad_som_slutar_inom_en_timme_hoppas_over():
    assert run([buy(0, T)], market(end=T + 3599)) == []
    assert len(run([buy(0, T)], market(end=T + 3600))) == 1
    assert len(run([buy(0, T)], market(end=None))) == 1


def test_okand_marknad_hoppas_over():
    assert run([buy(0, T, cid="annan")]) == []


def test_signal_fran_flera_kop_inom_tio_minuter():
    # 200 $ + 100 $ inom 10 min: en signal, utlöst vid andra köpet. 100 $ tre timmar senare: ingen.
    fills = [buy(0, T, 0.5, 400), buy(0, T + 300, 0.4000001, 250), buy(0, T + 3 * 3600, 0.5, 200)]
    [t] = run(fills)
    assert t["t"] == "2026-11-18T11:11:40Z"
    assert t["trader_price"] == 0.4615  # (200 + 100) / 650


def test_others_inom_tre_dagar_men_inte_fyra():
    fills = [buy(0, T), buy(1, T - 3 * D), buy(2, T - 4 * D), buy(3, T - D, token="999")]
    trades = {t["p"]: t for t in run(fills)}
    assert trades[0]["others"] == [1]
    assert trades[1]["others"] == [2]  # en dag före
    assert trades[2]["others"] == []


# ---------------------------------------------------------------- export_replay.py


class FakeApi:
    """Data API v2, Gamma och CLOB prices-history från fixturerna i tests/fixtures/replay/."""

    def __init__(self, title=None):
        self.calls, self.title = [], title

    def get_json(self, url, params):
        self.calls.append((url, dict(params)))
        if "data-api" in url:
            assert url.endswith("/v2/activity")
            assert "offset" not in params and "market" not in params
            pages = json.loads((FIX / "activity.json").read_text())[params["user"]]
            body = pages[1] if params.get("cursor") == "c2" else pages[0]
            if self.title:
                for r in body["data"]:
                    r["title"] = self.title
            return body
        if "gamma" in url:
            markets = json.loads((FIX / "gamma.json").read_text())
            return [m for m in markets if str(m["closed"]).lower() == params["closed"]
                    and m["conditionId"] in params["condition_ids"]]  # fmt: skip
        assert url == ex.HISTORY and params["fidelity"] == 1
        return json.loads((FIX / "prices.json").read_text()).get(params["market"], {"history": []})


def export(tmp_path, http, days="7"):
    out = tmp_path / "out" / "replay_trades.json"
    argv = [str(out), "--players", str(FIX / "players.json"), "--days", days,
            "--cache", str(tmp_path / "cache")]  # fmt: skip
    ex.main(argv, http=http, now=T + 2 * D)
    return out


def test_export_enligt_kontraktet(tmp_path, capsys):
    out = export(tmp_path, FakeApi())
    doc = json.loads(out.read_text())
    assert doc["sample"] is False and doc["generated_at"] == "2026-11-20T11:06:40Z"
    assert (doc["from"], doc["to"]) == ("2026-11-13", "2026-11-20")
    assert doc["delays"] == [5, 30, 120] and doc["stake_usd"] == 10
    assert doc["players"] == [{"name": "Alice", "safe": True}, {"name": "Trader 1", "safe": False},
                              {"name": "Trader 2", "safe": False}]  # fmt: skip
    # B en dag före Alice, C:s marknad slutar inom en timme.
    b, a = doc["trades"]
    assert (b["p"], b["others"], b["trader_price"]) == (1, [], 0.4)
    assert (a["p"], a["others"], a["state"]) == (0, [1], "settled")
    assert a["cost"]["5"] == 10.35 and a["result"]["5"] == -6.41  # delsälj à 0.80, sedan förlust
    assert a["cost"]["30"] == 10.34 and a["result"]["30"] == -6.55  # 0.52 efter 30 s
    printed = capsys.readouterr().out
    assert "3 spelare" in printed and "0x" not in printed


def test_ingen_0x_i_utdata(tmp_path):
    out = export(tmp_path, FakeApi())
    assert "0x" not in out.read_text()


def test_cachen_ateranvands(tmp_path):
    first = FakeApi()
    export(tmp_path, first)
    assert len(first.calls) >= 6
    again = FakeApi()
    export(tmp_path, again)
    assert again.calls == []


def test_activity_med_cursor_och_start(tmp_path):
    api = FakeApi()
    export(tmp_path, api)
    act = [p for u, p in api.calls if "data-api" in u]
    assert [p.get("cursor") for p in act if p["user"].startswith("0xa")] == [None, "c2"]
    assert all(p["type"] == "TRADE" and p["start"] == (T + 2 * D) // D * D - 7 * D for p in act)


def test_lackkontrollen_stoppar_innan_nagot_skrivs(tmp_path):
    with pytest.raises(SystemExit, match="Stoppar"):
        export(tmp_path, FakeApi(title="köpt av 0x" + "d" * 40))
    assert not (tmp_path / "out").exists()


def test_exempelfilen():
    doc = json.loads(SAMPLE.read_text())
    assert doc["sample"] is True and doc["delays"] == [5, 30, 120]
    n = len(doc["players"])
    assert 6 <= n <= 10 and 250 <= len(doc["trades"]) <= 350
    for t in doc["trades"]:
        assert 0 <= t["p"] < n and all(0 <= o < n and o != t["p"] for o in t["others"])
        assert t["state"] in ("settled", "sold", "open")
        assert set(t["cost"]) == set(t["result"]) == {"5", "30", "120"}
        assert doc["from"] <= t["t"][:10] <= doc["to"] and t["t"].endswith("Z")
