import json
import sys
from pathlib import Path

import pytest

from copycheck import db

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import export_dashboard as ex  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
LIVE, ROBOT = FIX / "dashboard_live", FIX / "dashboard_robot"
T, D = 1780000000, 86400
NOW = T + 10 * D


class FakeGamma:
    """Gamma från fixturen: öppna marknader med closed=false, stängda med closed=true."""

    def get_json(self, url, params):
        markets = json.loads((FIX / "dashboard_gamma.json").read_text())
        return [m for m in markets if str(m["closed"]).lower() == params["closed"]]


def build(**kw):
    return ex.build(live=LIVE, http=FakeGamma(), now=NOW, **kw)


def iso(t):
    return ex.iso(t)


def test_summary_roi_raknad_for_hand():
    # s1: 20 andelar à 0.50, vinner 20 $: +10, med avgift 0.35: +9.65 på 10.35.
    # s2: 25 à 0.40, förlorar: -10, med avgift 0.42: -10.42 på 10.42.
    # s3: 40 à 0.25, säljer hälften för 10 $ (avgift 0.35), resten 20 × 0.60 öppet: +12,
    #     med köpavgift 0.53: 9.65 + 12 - 10.53 = +11.12 på 10.53.
    # s4: marknaden slutar inom en timme och räknas inte.
    s = build()["summary.json"]
    assert s["sample"] is False
    assert s["generated_at"] == iso(NOW)
    assert s["live_roi_pct"] == 40.0  # 12 / 30
    assert s["live_roi_fee_pct"] == 33.1  # 10.35 / 31.30
    assert (s["live_buys"], s["live_settled"]) == (3, 2)
    assert (s["players"], s["players_trusted"]) == (3, 1)
    assert (s["sim_trades"], s["kalshi_roi_pct"]) == (0, None)


def test_traders_namn_och_roi():
    tr = build()["traders.json"]
    assert [t["name"] for t in tr] == ["Alice", "Trader 1", "Trader 2"]
    assert [t["source"] for t in tr] == ["vår", "vår", "polkyo"]
    assert [t["safe"] for t in tr] == [True, False, False]
    assert [(t["copied"], t["settled"]) for t in tr] == [(1, 1), (1, 1), (1, 0)]
    assert [t["roi_pct"] for t in tr] == [100.0, -100.0, 120.0]
    assert [t["roi_fee_pct"] for t in tr] == [93.2, -100.0, 105.6]


def test_equity_borjar_pa_noll_och_raknar_med_avgift():
    eq = build()["equity.json"]
    assert eq == [
        {"t": iso(T), "pnl_usd": 0.0},
        {"t": iso(T), "pnl_usd": 9.65},
        {"t": iso(T + D), "pnl_usd": -0.77},
        {"t": iso(T + 3 * D), "pnl_usd": 10.35},
    ]


def test_latency():
    lat = build()["latency.json"]
    assert (lat["median_s"], lat["max_s"]) == (2.0, 10)
    counts = {b["label"]: b["count"] for b in lat["buckets"]}
    assert counts["0–1 s"] == 1 and counts["1–2 s"] == 1
    assert counts["2–5 s"] == 1 and counts["5–15 s"] == 1
    assert sum(counts.values()) == 4
    assert lat["price_diff_cent_median"] == 0.5


def test_runs_med_kalshi_i_tidsordning(tmp_path):
    path = tmp_path / "copycheck.db"
    conn = db.connect(path)
    for sid, ts in ((1, T - 40 * D), (2, T - 20 * D)):
        conn.execute(
            """INSERT INTO signals (id, wallet, condition_id, token_id, outcome_index, avg_price,
                   usdc, first_ts, trigger_ts, last_ts, n_fills)
               VALUES (?, 'w', ?, ?, 0, 0.5, 300, ?, ?, ?, 1)""",
            (sid, f"c{sid}", f"t{sid}", ts, ts, ts),
        )
    for sid, delay, pnl, kind, skip in (
        (1, 120, 5, "settled", None),
        (2, 120, -10, "open", None),
        (2, 0, None, None, "no_match"),
    ):
        conn.execute(
            """INSERT INTO sim_trades (signal_id, strategy, delay, pnl, cost, entry_price, stale,
                   exit_kind, mismatch, skip_reason)
               VALUES (?, 'A', ?, ?, 10, 0.52, 0, ?, 0, ?)""",
            (sid, delay, pnl, kind, skip),
        )
    conn.commit()
    conn.close()
    out = build(runs=[("Livetest 1", LIVE)], db_path=path)
    assert out["summary.json"]["sim_trades"] == 3
    assert out["summary.json"]["kalshi_roi_pct"] == -25.0
    assert out["runs.json"] == [
        {"name": "Kalshi backtest", "from": "2026-04-18", "to": "2026-05-08", "buys": 2,
         "settled": 1, "roi_pct": None, "roi_fee_pct": -25.0},
        {"name": "Livetest 1", "from": "2026-05-28", "to": "2026-05-31", "buys": 3,
         "settled": 2, "roi_pct": 40.0, "roi_fee_pct": 33.1},
    ]  # fmt: skip


def test_robot():
    r = build(robot=ROBOT)["robot.json"]
    assert (r["spent_usd"], r["back_usd"], r["open"]) == (5.0, 6.5, 1)
    assert [e["type"] for e in r["events"]] == ["buy", "skip", "sell", "settled"]
    assert r["events"][0] == {"t": iso(T + 2), "type": "buy", "title": "Market 1", "usd": 5.0}
    assert r["events"][1]["usd"] is None


def test_robot_med_torrkorning_stoppar(tmp_path):
    rob = tmp_path / "robot"
    rob.mkdir()
    lines = (ROBOT / "robot.jsonl").read_text().replace('"dry": false', '"dry": true', 1)
    (rob / "robot.jsonl").write_text(lines)
    with pytest.raises(ValueError, match="dry-run events; export only a --live robot dir"):
        ex.robot_file(rob)
    out = tmp_path / "out"
    with pytest.raises(SystemExit, match="dry-run"):
        ex.main([str(out), "--live", str(LIVE), "--robot", str(rob)], http=FakeGamma(), now=NOW)
    assert not out.exists()


def test_ingen_robot_json_utan_robot(tmp_path):
    (tmp_path / "robot.json").write_text("{}")  # kvar från en tidigare export
    ex.main([str(tmp_path), "--live", str(LIVE)], http=FakeGamma(), now=NOW)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["equity.json", "latency.json", "runs.json", "summary.json", "traders.json"]
    assert json.loads((tmp_path / "runs.json").read_text()) == []


def test_run_utan_signaler_hoppas_over(tmp_path):
    out = build(runs=[("Tom", tmp_path), ("Livetest 1", LIVE)])
    assert [r["name"] for r in out["runs.json"]] == ["Livetest 1"]


def test_live_run_namn():
    assert build()["summary.json"]["live_run"] == "dashboard_live"
    out = build(runs=[("Livetest 1", Path(str(LIVE) + "/"))])
    assert out["summary.json"]["live_run"] == "Livetest 1"


def test_kontrollen_hittar_forbjudet():
    with pytest.raises(ValueError, match=r"a\.json, fält \[0\]\.title: .*0x"):
        ex.check({"a.json": [{"title": "köpt av 0x1234abcd5678"}]})
    with pytest.raises(ValueError, match=r"b\.json, fält x\[0\]\.wallet: .*wallet"):
        ex.check({"a.json": {}, "b.json": {"x": [{"wallet": "w"}]}})
    with pytest.raises(ValueError, match="PRIVATE_KEY"):
        ex.check({"a.json": {"text": "POLYMARKET_PRIVATE_KEY saknas"}})
    ex.check(build(robot=ROBOT))


def test_exempeldatan_klarar_kontrollen():
    data = Path(__file__).parents[1] / "dashboard" / "public" / "data"
    files = {p.name: json.loads(p.read_text()) for p in sorted(data.glob("*.json"))}
    assert "summary.json" in files
    ex.check(files)


def test_kontrollen_stoppar_innan_nagot_skrivs(tmp_path):
    rob = tmp_path / "robot"
    rob.mkdir()
    (rob / "robot.jsonl").write_text(
        json.dumps({"type": "buy", "title": "0x" + "d" * 40, "usd": 5.0, "t": T}) + "\n"
    )
    out = tmp_path / "out"
    with pytest.raises(SystemExit):
        ex.main([str(out), "--live", str(LIVE), "--robot", str(rob)], http=FakeGamma(), now=NOW)
    assert not out.exists() or not any(out.iterdir())
