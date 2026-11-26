"""Efterhandsräkning för fliken Replay: hur det hade gått att härma spelarna.

Ren räkning utan nätanrop. Kontraktet för utdata: replay_trades.json (se scripts/export_replay.py).
Fills: {"p", "token", "cid", "idx", "side", "price", "size", "usd", "ts", "title"}, p = spelarens
index. Marknader: cid -> {"title", "end", "closed", "prices"}. Prishistorik: token -> [(t, p)].
"""

import json
from bisect import bisect_right
from collections import defaultdict
from datetime import UTC, datetime

from mimic import config, polymarket
from mimic.fees import fee_usd
from mimic.kalshi import iso_ts
from mimic.signals import group_fills

DELAYS = [5, 30, 120]
STAKE = 10.0
SHORT = 3600  # marknader som slutar inom en timme efter signalen hoppas över
CONSENSUS = 3 * 86400  # "others": andra spelare som köpt samma utfall inom 3 dagar före


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fill(row, p):
    """En rad från Data API v2 /activity (type TRADE)."""
    return {
        "p": p,
        "token": row["token_id"],
        "cid": row["condition_id"],
        "idx": row.get("outcome_index"),
        "side": row["side"],
        "price": float(polymarket.price(row["price"])),
        "size": float(row["size"]),
        "usd": float(row.get("usdc_size") or row["price"] * row["size"]),
        "ts": row["timestamp"],
        "title": row.get("title"),
    }


def market(m):
    """En marknad från Gamma."""
    return {
        "title": m.get("question"),
        "end": iso_ts(m.get("endDate")),
        "closed": bool(m.get("closed")),
        "prices": [float(x) for x in json.loads(m.get("outcomePrices") or "[]")],
    }


def signals(fills, min_usd=config.MIN_SIGNAL_USD, window=config.SIGNAL_WINDOW):
    """Köp av en spelare i en token, ihopslagna som i signals.build. Sorterade på tid. Priset är
    snittet av köpen fram till och med utlösningen, som i livetestet."""
    rows = sorted(
        ((f["p"], f["cid"], f["token"], f["idx"], f["price"], f["size"], f["usd"], f["ts"])
         for f in fills if f["side"] == "BUY"),
        key=lambda r: (r[0], r[2], r[7]),
    )  # fmt: skip
    out = []
    for g in group_fills(rows, window):
        total = val = size = 0.0
        for r in g:
            total, val, size = total + r[6], val + r[4] * r[5], size + r[5]
            if total >= min_usd:
                out.append({"p": r[0], "cid": r[1], "token": r[2], "idx": r[3],
                            "price": float(polymarket.price(val / size)), "t": r[7]})  # fmt: skip
                break
    return sorted(out, key=lambda s: (s["t"], s["p"]))


def skip_reason(s, m):
    """Varför signalen inte räknas, eller None om den räknas."""
    if m is None:
        return "saknar Gamma"
    if m["end"] and m["end"] - s["t"] < SHORT:
        return "slutar inom 1 h"
    if s["idx"] is None or s["idx"] >= len(m["prices"]):
        return "annat"
    return None


def entry(s, points, delay):
    """max(spelarens pris, senaste punkten i prishistoriken vid t + delay)."""
    i = bisect_right(points, (s["t"] + delay, float("inf")))
    step = points[i - 1][1] if i else s["price"]
    return float(polymarket.price(max(s["price"], step)))


def sells(fills):
    """(p, token) -> [(tid, andel av innehavet, pris)] för varje försäljning."""
    by = defaultdict(list)
    for f in sorted(fills, key=lambda f: f["ts"]):
        by[(f["p"], f["token"])].append(f)
    out = {}
    for k, fs in by.items():
        hold, xs = 0.0, []
        for f in fs:
            if f["side"] == "BUY":
                hold += f["size"]
                continue
            xs.append((f["ts"], 1.0 if hold <= f["size"] + 1e-9 else f["size"] / hold, f["price"]))
            hold = max(hold - f["size"], 0.0)
        out[k] = xs
    return out


def copy(price, xs, t, final, stake):
    """(kostnad, resultat, andelar kvar) för `stake` dollar köpt till `price` vid tiden t.
    Bara sälj efter t följs: kopian äger inget före sitt köp."""
    sh = stake / price
    cost, got = stake + fee_usd(sh, price), 0.0
    for ts, frac, p in xs:
        if ts <= t:
            continue
        q = sh * frac
        got += q * p - fee_usd(q, p)
        sh -= q
    return cost, got + sh * final - cost, sh


def trades(fills, markets, history, sigs, chosen=None, delays=DELAYS, stake=STAKE):
    """Trades enligt kontraktet. `sigs`: alla signaler i fills (från signals), `others` räknas
    mot dem. `chosen`: de signaler som skrivs, standard alla i sigs som inte hoppas över."""
    if chosen is None:
        chosen = [s for s in sigs if skip_reason(s, markets.get(s["cid"])) is None]
    by_token = defaultdict(list)
    for s in sigs:
        by_token[s["token"]].append(s)
    xs = sells(fills)
    titles = {f["cid"]: f["title"] for f in fills if f.get("title")}
    out = []
    for s in chosen:
        m = markets[s["cid"]]
        points = sorted(history.get(s["token"]) or [])
        cost, result, left = {}, {}, 0.0
        for d in delays:
            c, r, left = copy(entry(s, points, d), xs.get((s["p"], s["token"]), []), s["t"] + d,
                              m["prices"][s["idx"]], stake)  # fmt: skip
            cost[str(d)], result[str(d)] = round(c, 2), round(r, 2)
        others = {o["p"] for o in by_token[s["token"]] if s["t"] - CONSENSUS <= o["t"] <= s["t"]}
        out.append({
            "p": s["p"],
            "t": iso(s["t"]),
            "title": titles.get(s["cid"]) or m["title"],
            "trader_price": s["price"],
            "others": sorted(others - {s["p"]}),
            "state": "sold" if left <= 1e-9 else "settled" if m["closed"] else "open",
            "cost": cost,
            "result": result,
        })  # fmt: skip
    return out
