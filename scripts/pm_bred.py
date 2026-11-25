"""Rapport för det breda livetestet: vilka spelare går att härma, vecka för vecka.

Läser events.jsonl från pm_livetest.py i brett läge. Varje signal härmas på låtsas med 10 $
mot orderboken när vi såg köpet, med avgift, och säljs när spelaren säljer. Bara frågor som
är avgjorda räknas. Bara GET mot Gamma.

    python scripts/pm_bred.py DATADIR [--min 10] [--topp 30]
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from mimic import polymarket
from mimic.http import HttpClient

sys.path.insert(0, str(Path(__file__).parent))
from pm_livetest import BASE, SHORT, buy_fill, fee, read_jl, sell_fill  # noqa: E402

WEEK = 7 * 86400


def copy(s, sells, prices):
    """(vinst, insats) för 10 $ med avgift, eller None om boken saknas eller frågan är öppen."""
    if "asks" not in s["book"] or s["idx"] is None or s["idx"] >= len(prices):
        return None
    sh = buy_fill(s["book"]["asks"], BASE)
    if not sh:
        return None
    cost, got = BASE + fee(sh, BASE / sh, True), 0.0
    for x in sorted(sells, key=lambda x: x["trade_ts"]):
        if x["trade_ts"] <= s["trade_ts"] or "bids" not in x["book"] or sh <= 1e-9:
            continue
        q = sh * x["frac"]
        v = sell_fill(x["book"]["bids"], q)
        got += v - (fee(q, v / q, True) if v > 0 else 0)
        sh -= q
    return got + sh * prices[s["idx"]] - cost, cost


def main(d, min_n, top):
    ev = read_jl(Path(d) / "events.jsonl")
    sigs = [e for e in ev if e["type"] == "signal"]
    sigs = [s for s in sigs if not (s["end"] and s["end"] - s["trade_ts"] < SHORT)]
    sells = defaultdict(list)
    for e in ev:
        if e["type"] == "sell":
            sells[(e["wallet"], e["token"])].append(e)
    closed = {}
    for m in polymarket.gamma_markets(HttpClient(), sorted({s["cid"] for s in sigs})):
        if m.get("closed"):
            closed[m["conditionId"]] = [
                float(x) for x in json.loads(m.get("outcomePrices") or "[]")
            ]
    start = min((s["trade_ts"] for s in sigs), default=0)
    per = defaultdict(lambda: defaultdict(list))  # spelare -> vecka -> resultat
    names, n_sig = {}, defaultdict(int)
    for s in sigs:
        names[s["wallet"]], n_sig[s["wallet"]] = s["name"], n_sig[s["wallet"]] + 1
        if s["cid"] not in closed:
            continue
        if r := copy(s, sells[(s["wallet"], s["token"])], closed[s["cid"]]):
            per[s["wallet"]][(s["trade_ts"] - start) // WEEK].append(r)

    def roi(rs):
        return sum(r[0] for r in rs) / sum(r[1] for r in rs)

    rows = []
    for w, weeks in per.items():
        allr = [r for rs in weeks.values() for r in rs]
        if len(allr) < min_n:
            continue
        good = [k for k, rs in weeks.items() if len(rs) >= 3]
        plus = sum(1 for k in good if roi(weeks[k]) > 0)
        rows.append((roi(allr), w, len(allr), plus, len(good), n_sig[w]))
    allres = [r for weeks in per.values() for rs in weeks.values() for r in rs]
    days = (time.time() - start) / 86400 if start else 0
    print(f"# Brett livetest\n\n{len(sigs)} signaler från {len(n_sig)} spelare på "
          f"{days:.1f} dagar. {len(allres)} avgjorda köp.")  # fmt: skip
    if allres:
        print(f"Alla spelare tillsammans: ROI med avgift {roi(allres):+.1%}.")
    print(f"{len(rows)} spelare har minst {min_n} avgjorda köp.\n")
    print("| spelare | avgjorda | signaler | ROI med avgift | veckor plus |")
    print("|---|---|---|---|---|")
    for r, w, n, plus, weeks, ns in sorted(rows, reverse=True)[:top]:
        print(f"| {names[w][:24]} ({w[:8]}) | {n} | {ns} | {r:+.1%} | {plus} av {weeks} |")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("datadir")
    ap.add_argument("--min", type=int, default=10)
    ap.add_argument("--topp", type=int, default=30)
    a = ap.parse_args()
    main(a.datadir, a.min, a.topp)
