"""Matchning Polymarket <-> Kalshi (lucka 18-22): textsökning, sedan AI som jämför reglerna."""

import json
import time

from copycheck import db

LEVELS = {"exact", "near", "related", "none"}
SIDES = {"yes", "no"}
CLOSE_WINDOW = 7 * 86400  # Kalshi-marknaden måste stänga inom en vecka från PM:s slutdatum
MAX_CANDIDATES = 5

SYSTEM = """Du jämför kontrakt på prediktionsmarknader. Du får en Polymarket-marknad och
några Kalshi-marknader. Bedöm varje Kalshi-marknad för sig.

Nivåer:
- exact: samma händelse, samma källa, samma gränsvärde, samma datum och tidszon.
  De två avgörs alltid på samma sätt.
- near: samma händelse men någon skillnad i regler, datum, källa eller gränsvärde.
- related: samma ämne men en annan fråga.
- none: inget samband.

outcome0_side: vilken sida på Kalshi ("yes" eller "no") som vinner exakt när
Polymarkets första utfall vinner. Läs reglerna noga, sidan kan vara omvänd.

Svara bara med JSON:
{"candidates": [{"ticker": "...", "level": "...", "outcome0_side": "yes|no", "reason": "kort"}]}"""


def candidates(conn, pm):
    end = pm.get("end_ts") or 0
    return db.search_kalshi(
        conn, pm["question"], MAX_CANDIDATES, end - CLOSE_WINDOW, end + CLOSE_WINDOW
    )


def prompt(pm, cands):
    lines = [
        "POLYMARKET",
        f"Fråga: {pm['question']}",
        f"Utfall: {pm['outcomes']} (utfall 0 = {pm['outcomes'][0] if pm['outcomes'] else '?'})",
        f"Regler: {pm.get('description') or ''}",
        "",
        "KALSHI",
    ]
    for c in cands:
        lines += [
            f"- ticker: {c['ticker']}",
            f"  titel: {c['title']} / {c.get('yes_sub_title') or ''}",
            f"  regler: {c.get('rules_primary') or ''}",
        ]
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(lines)}]


def parse_judgement(text, tickers):
    """Validerar AI-svaret. Okända tickers tas bort, okända värden blir none/None."""
    try:
        items = json.loads(text).get("candidates") or []
    except (ValueError, AttributeError):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict) or it.get("ticker") not in tickers:
            continue
        side = it.get("outcome0_side") if it.get("outcome0_side") in SIDES else None
        level = it.get("level") if it.get("level") in LEVELS else "none"
        if side is None:
            level = "none"
        out.append({"ticker": it["ticker"], "level": level, "outcome0_side": side,
                    "reason": str(it.get("reason") or "")})  # fmt: skip
    return out


def kalshi_side(outcome_index, outcome0_side):
    """Vilken Kalshi-sida vi köper när tradern köper PM-utfallet `outcome_index`."""
    if outcome0_side is None:
        return None
    if outcome_index == 0:
        return outcome0_side
    return "no" if outcome0_side == "yes" else "yes"


def match_market(conn, pm, llm, model, now=None):
    """Bedömer en PM-marknad en gång. Resultatet sparas i matches och match_runs."""
    cid = pm["condition_id"]
    if conn.execute("SELECT 1 FROM match_runs WHERE pm_condition = ?", (cid,)).fetchone():
        return
    now = now or int(time.time())
    cands = candidates(conn, pm)
    judged = []
    if cands:
        judged = parse_judgement(llm(prompt(pm, cands)), {c["ticker"] for c in cands})
    conn.executemany(
        """INSERT OR REPLACE INTO matches
           (pm_condition, kalshi_ticker, level, outcome0_side, reason, model, judged_ts)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (cid, j["ticker"], j["level"], j["outcome0_side"], j["reason"], model, now)
            for j in judged
        ],  # fmt: skip
    )
    conn.execute(
        "INSERT INTO match_runs (pm_condition, n_candidates, judged_ts) VALUES (?, ?, ?)",
        (cid, len(cands), now),
    )
    conn.commit()


def accuracy(conn, level):
    """(rätt, granskade) för en nivå."""
    ok, n = conn.execute(
        """SELECT COALESCE(SUM(review_ok), 0), COUNT(review_ok) FROM matches
           WHERE level = ?""",
        (level,),
    ).fetchone()
    return ok, n


def groq_llm(model):
    """Groq med JSON-svar och temperatur 0. Nyckeln läses från GROQ_API_KEY."""
    from groq import Groq

    client = Groq(max_retries=5)

    def call(messages):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content

    return call
