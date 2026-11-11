"""Matchning Polymarket <-> Kalshi (lucka 18-22): textsökning, sedan AI som jämför reglerna."""

import json
import time

from copycheck import config, db

LEVELS = {"exact", "near", "related", "none"}
SIDES = {"yes", "no"}
CLOSE_WINDOW = 7 * 86400  # Kalshi-marknaden måste stänga inom en vecka från PM:s slutdatum
MAX_CANDIDATES = 6
SEARCH_HITS = 50  # hämtas innan vi behåller en per event
RULES_SECONDARY_CHARS = 600

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

Ta bara med kandidater som är exact eller near. Utelämna related och none.
reason: högst 20 ord. Finns ingen exact eller near: {"candidates": []}.

Svara bara med JSON:
{"candidates": [{"ticker": "...", "level": "...", "outcome0_side": "yes|no", "reason": "kort"}]}"""


def candidates(conn, pm):
    """Kalshi-marknader som liknar frågan, högst en per event.

    Gammas slutdatum ligger ofta en vecka efter matchen, så fönstret börjar vid första
    signalen när den finns: Kalshi-marknaden måste stänga efter att vi kan kopiera."""
    end = pm.get("end_ts") or 0
    start = pm.get("signal_ts") or end - CLOSE_WINDOW
    hits = db.search_kalshi(conn, pm["question"], SEARCH_HITS, start, end + CLOSE_WINDOW)
    seen, out = set(), []
    for h in hits:  # undermarknader i samma event (set, resultat) trängde annars ut huvudfrågan
        if h["event_ticker"] not in seen:
            seen.add(h["event_ticker"])
            out.append(h)
    return out[:MAX_CANDIDATES]


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
            f"  fler regler: {(c.get('rules_secondary') or '')[:RULES_SECONDARY_CHARS]}",
        ]
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(lines)}]


def parse_judgement(text, tickers):
    """Validerar AI-svaret. Okända tickers tas bort, okända värden blir none/None."""
    text = text or ""
    try:
        # Vissa modeller lägger text eller ```json runt svaret. Ta från första { till sista }.
        items = json.loads(text[text.find("{") : text.rfind("}") + 1]).get("candidates") or []
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
    if "signal_ts" not in pm:
        first = "SELECT MIN(trigger_ts) FROM signals WHERE condition_id = ?"
        pm = {**pm, "signal_ts": conn.execute(first, (cid,)).fetchone()[0]}
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


def record_usage(conn, model, tokens_in, tokens_out, now=None):
    """Sparar ett AI-anrops kostnad. `model` är "leverantör:modell"."""
    price_in, price_out = config.LLM_PRICES.get(model, config.LLM_PRICE_UNKNOWN)
    usd = (tokens_in * price_in + tokens_out * price_out) / 1_000_000
    conn.execute(
        "INSERT INTO llm_usage (ts, model, tokens_in, tokens_out, usd) VALUES (?, ?, ?, ?, ?)",
        (now or int(time.time()), model, tokens_in, tokens_out, usd),
    )
    conn.commit()


def spent(conn):
    """Total AI-kostnad i USD, alla körningar."""
    return conn.execute("SELECT COALESCE(SUM(usd), 0) FROM llm_usage").fetchone()[0]


def openai_llm(base_url, api_key, model, on_usage=None):
    """OpenAI-kompatibelt API (Anthropic, Opper eller Berget AI).

    Ingen temperature och inget JSON-läge: claude-sonnet-5-5 avvisar båda (400).
    Prompten kräver JSON, och parse_judgement tål text runt svaret."""
    from openai import OpenAI

    # Standard är 600 s per försök. En tyst död anslutning låste körningen i 38 min.
    client = OpenAI(base_url=base_url, api_key=api_key, max_retries=5, timeout=60)

    def call(messages):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=2000,  # fem kandidater får plats; Anthropic kräver ett tak
        )
        if on_usage and resp.usage:
            on_usage(resp.usage.prompt_tokens, resp.usage.completion_tokens)
        return resp.choices[0].message.content

    return call
