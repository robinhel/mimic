import json
from pathlib import Path

from copycheck import db, matching, polymarket

FIXTURES = Path(__file__).parent / "fixtures"
GAMMA = json.loads((FIXTURES / "pm_gamma_markets.json").read_text())


def kalshi_rows():
    return json.loads((FIXTURES / "kalshi_markets_no_mve.json").read_text())["markets"]


class FakeClient:
    def __init__(self):
        self.calls = []

    def get_json(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        want = params["closed"] == "true"
        return [
            m for m in GAMMA if m["closed"] == want and m["conditionId"] in params["condition_ids"]
        ]


def setup():
    conn = db.connect(":memory:")
    db.upsert_pm_markets(conn, GAMMA)
    db.upsert_kalshi_markets(conn, kalshi_rows(), source="live", categories={})
    db.rebuild_kalshi_search(conn)
    return conn


def test_gamma_hamtar_oppna_och_stangda_i_omgangar():
    ids = [m["conditionId"] for m in GAMMA]
    c = FakeClient()
    got = polymarket.gamma_markets(c, ids, batch=3)
    assert sorted(m["conditionId"] for m in got) == sorted(ids)
    assert len(c.calls) == 4  # 2 omgångar x öppna/stängda
    assert all(p["condition_ids"] and len(p["condition_ids"]) <= 3 for _, p in c.calls)


def test_pm_market_sparar_resultat_och_tokens():
    conn = setup()
    closed = next(m for m in GAMMA if m["closed"])
    row = conn.execute(
        "SELECT result_index, outcome0_token, end_ts FROM pm_markets WHERE condition_id = ?",
        (closed["conditionId"],),
    ).fetchone()
    assert row[0] == json.loads(closed["outcomePrices"]).index("1")
    assert row[1] == json.loads(closed["clobTokenIds"])[0]
    assert row[2] > 0
    still_open = next(m for m in GAMMA if not m["closed"])
    assert conn.execute(
        "SELECT result_index FROM pm_markets WHERE condition_id = ?", (still_open["conditionId"],)
    ).fetchone() == (None,)


def test_kandidater_filtreras_pa_stangningstid():
    conn = setup()
    k = kalshi_rows()[0]
    pm = {"question": k["title"], "end_ts": 1794529800}
    assert k["ticker"] in [c["ticker"] for c in matching.candidates(conn, pm)]
    far = {"question": k["title"], "end_ts": 1794529800 + 30 * 86400}
    assert matching.candidates(conn, far) == []


def test_tolka_svar_validerar():
    text = json.dumps({"candidates": [
        {"ticker": "A", "level": "exact", "outcome0_side": "no", "reason": "samma"},
        {"ticker": "B", "level": "konstig", "outcome0_side": "yes", "reason": ""},
        {"ticker": "OKAND", "level": "exact", "outcome0_side": "yes", "reason": ""},
        {"ticker": "C", "level": "near", "outcome0_side": "kanske", "reason": ""},
    ]})  # fmt: skip
    got = matching.parse_judgement(text, {"A", "B", "C"})
    assert got == [
        {"ticker": "A", "level": "exact", "outcome0_side": "no", "reason": "samma"},
        {"ticker": "B", "level": "none", "outcome0_side": "yes", "reason": ""},
        {"ticker": "C", "level": "none", "outcome0_side": None, "reason": ""},
    ]
    assert matching.parse_judgement("inte json", {"A"}) == []


def test_kalshi_sida_for_token():
    assert matching.kalshi_side(0, "yes") == "yes"
    assert matching.kalshi_side(1, "yes") == "no"
    assert matching.kalshi_side(1, "no") == "yes"
    assert matching.kalshi_side(0, None) is None


def test_match_sparar_och_kor_bara_en_gang():
    conn = setup()
    k = kalshi_rows()[0]
    pm = {"condition_id": "c1", "question": k["title"], "description": "d",
          "outcomes": ["Yes", "No"], "end_ts": 1794529800}  # fmt: skip
    calls = []

    def llm(messages):
        calls.append(messages)
        return json.dumps({"candidates": [
            {"ticker": k["ticker"], "level": "exact", "outcome0_side": "yes", "reason": "r"}
        ]})  # fmt: skip

    matching.match_market(conn, pm, llm, model="m")
    matching.match_market(conn, pm, llm, model="m")
    assert len(calls) == 1
    assert k["rules_primary"] in calls[0][-1]["content"]
    row = conn.execute("SELECT kalshi_ticker, level, outcome0_side FROM matches").fetchone()
    assert row == (k["ticker"], "exact", "yes")


def test_utan_kandidater_ingen_ai_men_markerad():
    conn = setup()
    pm = {"condition_id": "c2", "question": "zzz qqq", "description": "", "outcomes": ["Yes", "No"],
          "end_ts": 1}  # fmt: skip
    matching.match_market(conn, pm, lambda m: 1 / 0, model="m")
    assert conn.execute("SELECT n_candidates FROM match_runs").fetchone() == (0,)


def test_granskning_ger_traffsakerhet():
    conn = db.connect(":memory:")
    for i, ok in enumerate([1, 1, 0, None]):
        conn.execute(
            """INSERT INTO matches (pm_condition, kalshi_ticker, level, outcome0_side, reason,
                                    model, judged_ts, review_ok)
               VALUES (?, ?, 'exact', 'yes', '', 'm', 0, ?)""",
            (f"c{i}", f"k{i}", ok),
        )
    assert matching.accuracy(conn, "exact") == (2, 3)
