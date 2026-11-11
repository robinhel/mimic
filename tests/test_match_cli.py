import json
from pathlib import Path

from copycheck import cli, db, matching

FIXTURES = Path(__file__).parent / "fixtures"
GAMMA = json.loads((FIXTURES / "pm_gamma_markets.json").read_text())


class GammaClient:
    def get_json(self, url, params=None):
        want = params["closed"] == "true"
        return [
            m for m in GAMMA if m["closed"] == want and m["conditionId"] in params["condition_ids"]
        ]


def setup():
    conn = db.connect(":memory:")
    for i, m in enumerate(GAMMA):
        conn.execute(
            """INSERT INTO signals (wallet, condition_id, token_id, outcome_index, avg_price, usdc,
                                    first_ts, trigger_ts, last_ts, n_fills)
               VALUES ('w', ?, 't', 0, 0.5, 300, ?, ?, ?, 1)""",
            (m["conditionId"], i, i, i),
        )
    return conn


def test_match_hamtar_pm_marknader_och_bedomer_varje_en_gang():
    conn = setup()
    seen = []
    cli.match(conn, GammaClient(), llm=lambda m: seen.append(m) or '{"candidates": []}',
              model="m", log=lambda *a: None)  # fmt: skip
    cli.match(conn, GammaClient(), llm=lambda m: 1 / 0, model="m", log=lambda *a: None)
    assert conn.execute("SELECT COUNT(*) FROM pm_markets").fetchone()[0] == len(GAMMA)
    assert conn.execute("SELECT COUNT(*) FROM match_runs").fetchone()[0] == len(GAMMA)


def test_match_bara_valda_traders_i_testperioden():
    conn = setup()  # plånbok 'w', en signal per Gamma-marknad med trigger_ts 0, 1, 2 ...
    conn.execute("UPDATE signals SET wallet = 'x' WHERE trigger_ts = 2")
    cli.match(conn, GammaClient(), llm=lambda m: '{"candidates": []}', model="m",
              log=lambda *a: None, wallets=["w"], start=1)  # fmt: skip
    done = {c for (c,) in conn.execute("SELECT pm_condition FROM match_runs")}
    want = {r[0] for r in conn.execute(
        "SELECT condition_id FROM signals WHERE wallet = 'w' AND trigger_ts >= 1"
    )}  # fmt: skip
    assert want and done == want
    assert GAMMA[0]["conditionId"] not in done  # före testperioden
    assert GAMMA[2]["conditionId"] not in done  # annan plånbok


def test_match_stannar_vid_kostnadsgransen():
    conn = setup()
    matching.record_usage(conn, "anthropic:claude-sonnet-5-5", 2_000_000, 0, now=1)  # 4 $
    out = []
    cli.match(conn, GammaClient(), llm=lambda m: 1 / 0, model="m", log=out.append, max_usd=4)
    assert conn.execute("SELECT COUNT(*) FROM match_runs").fetchone()[0] == 0
    assert any("gräns" in line for line in out)
    cli.match(conn, GammaClient(), llm=lambda m: '{"candidates": []}', model="m",
              log=lambda *a: None, max_usd=5)  # fmt: skip
    assert conn.execute("SELECT COUNT(*) FROM match_runs").fetchone()[0] == len(GAMMA)


def test_review_sparar_svar_och_visar_traffsakerhet():
    conn = db.connect(":memory:")
    for i in range(3):
        conn.execute(
            """INSERT INTO matches (pm_condition, kalshi_ticker, level, outcome0_side, reason,
                                    model, judged_ts) VALUES (?, ?, 'exact', 'yes', 'r', 'm', 0)""",
            (f"c{i}", f"k{i}"),
        )
    answers = iter(["j", "n", "q"])
    out = []
    cli.review(conn, ask=lambda _: next(answers), log=out.append)
    oks = [r for (r,) in conn.execute("SELECT review_ok FROM matches ORDER BY pm_condition")]
    assert oks == [1, 0, None]
    assert any("1 av 2" in line for line in out)
