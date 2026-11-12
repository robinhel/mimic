import json
from pathlib import Path

from copycheck import db, kalshi, matching, polymarket

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
    fee_rate, closed_ts = conn.execute(
        "SELECT fee_rate, closed_ts FROM pm_markets WHERE condition_id = ?",
        (closed["conditionId"],),
    ).fetchone()
    assert fee_rate == closed["feeSchedule"]["rate"]
    assert closed_ts == kalshi.iso_ts(closed["closedTime"])
    free = {**closed, "conditionId": "gratis", "feesEnabled": False}
    db.upsert_pm_markets(conn, [free])
    assert conn.execute(
        "SELECT fee_rate FROM pm_markets WHERE condition_id = 'gratis'"
    ).fetchone() == (0,)
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


def test_kandidater_fran_signalen_nar_pm_slutdatum_ar_sent():
    # Gammas endDate ligger ofta en vecka efter matchen (Angels-Mariners: 26 sep mot 4 okt).
    conn = setup()
    k = kalshi_rows()[0]
    close = kalshi.iso_ts(k["close_time"])
    pm = {"question": k["title"], "end_ts": close + 30 * 86400, "signal_ts": close - 3600}
    assert k["ticker"] in [c["ticker"] for c in matching.candidates(conn, pm)]
    pm["signal_ts"] = close + 60  # Kalshi stängde före signalen, går inte att kopiera
    assert k["ticker"] not in [c["ticker"] for c in matching.candidates(conn, pm)]


def test_kandidater_hogst_en_per_event():
    # Struff-Griekspoor: set- och resultatmarknader trängde ut matchvinnaren.
    conn = setup()
    pm = {"question": "Jaime Jaquez threes Isaiah Collier assists", "end_ts": 1794529800}
    events = [c["event_ticker"] for c in matching.candidates(conn, pm)]
    assert sorted(events) == ["KXNBA3PTPROT-26NOV10MILNYK", "KXNBAASTPROT-26NOV10MIAUTA"]


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
    assert matching.parse_judgement(None, {"A"}) == []


def test_tolka_svar_i_kodblock_med_text_runt():
    # Claude via Opper kan svara med text och ```json-block trots JSON-läge.
    inner = {"candidates": [{"ticker": "A", "level": "exact", "outcome0_side": "yes"}]}
    text = f"Här är bedömningen:\n```json\n{json.dumps(inner)}\n```\nKlart."
    got = matching.parse_judgement(text, {"A"})
    assert got == [{"ticker": "A", "level": "exact", "outcome0_side": "yes", "reason": ""}]


def test_kostnad_raknas_per_modell_och_summeras():
    conn = db.connect(":memory:")
    # Sonnet 5.5: 2 $ in och 10 $ ut per miljon tokens.
    matching.record_usage(conn, "anthropic:claude-sonnet-5-5", 1_000_000, 100_000, now=1)
    assert matching.spent(conn) == 3.0
    # Okänt pris räknas högt, så att gränsen hellre slår till för tidigt.
    matching.record_usage(conn, "berget:okand-modell", 1_000_000, 0, now=2)
    assert matching.spent(conn) > 3.0 + 2.0


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
    # Regler för oavgjort och uppskjuten match står i rules_secondary (Cowboys-Packers).
    assert k["rules_secondary"][:100] in calls[0][-1]["content"]
    row = conn.execute("SELECT kalshi_ticker, level, outcome0_side FROM matches").fetchone()
    assert row == (k["ticker"], "exact", "yes")


def test_match_anvander_forsta_signalen_for_sokfonstret():
    conn = setup()
    k = kalshi_rows()[0]
    close = kalshi.iso_ts(k["close_time"])
    conn.execute(
        """INSERT INTO signals (wallet, condition_id, token_id, outcome_index, avg_price, usdc,
                                first_ts, trigger_ts, last_ts, n_fills)
           VALUES ('w', 'c3', 't', 0, 0.5, 300, ?, ?, ?, 1)""",
        (close - 3600, close - 3600, close - 3600),
    )
    pm = {"condition_id": "c3", "question": k["title"], "description": "",
          "outcomes": ["Yes", "No"], "end_ts": close + 30 * 86400}  # fmt: skip
    calls = []
    matching.match_market(conn, pm, lambda m: calls.append(m) or "{}", model="m")
    assert calls and k["ticker"] in calls[0][-1]["content"]


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
