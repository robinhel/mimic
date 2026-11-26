"""Skriver replay_trades.json till fliken Replay: hur det hade gått att härma spelarna i efterhand.

    python scripts/export_replay.py OUTFILE --players PLAYERS_JSON [--days 90] [--cache DIR]

PLAYERS_JSON: [{"wallet", "name", "safe", "source"}] som i pm_livetest.py. Hämtar spelarnas affärer
(Data API v2 /activity) sedan midnatt UTC för --days dagar sedan, marknaderna från Gamma och
prishistoriken från CLOB runt varje signal. Räkningen finns i mimic.replay. Resultaten är
uppskattade: priset efter fördröjningen kommer från en prishistorik med en punkt per minut.
Alla svar sparas i --cache (standard .replay-cache/), så att en omkörning inte hämtar dem igen.
Gamma för öppna marknader sparas per dag. Max cirka 5 anrop/s per värd.
Innan något skrivs letar programmet efter plånböcker och hemligheter och stoppar.
"""

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

from mimic import polymarket, replay
from mimic.http import HttpClient

sys.path.insert(0, str(Path(__file__).parent))
from export_dashboard import check, day, iso  # noqa: E402

HISTORY = "https://clob.polymarket.com/prices-history"
HOSTS = ("data-api.polymarket.com", "gamma-api.polymarket.com", "clob.polymarket.com")
DAY = 86400
BEFORE = 600  # sekunder prishistorik före signalen


class Cache:
    """get_json som sparar svaren på disk. Filnamnen är hashar, så inga adresser syns."""

    def __init__(self, http, folder, today):
        self.http, self.folder, self.today, self.calls = http, Path(folder), today, 0

    def get_json(self, url, params):
        fresh = "gamma" in url and params.get("closed") == "false"  # öppna marknader: per dag
        key = json.dumps([url, sorted(params.items()), self.today if fresh else None])
        path = self.folder / (hashlib.sha256(key.encode()).hexdigest() + ".json")
        if path.exists():
            return json.loads(path.read_text())
        body = self.http.get_json(url, params)
        self.calls += 1
        self.folder.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body))
        return body


def names(players):
    out, unnamed = [], 0
    for p in players:
        name = p.get("name") or ""
        if not name or name.startswith("0x"):
            unnamed += 1
            name = f"Trader {unnamed}"
        out.append({"name": name, "safe": bool(p.get("safe"))})
    return out


def history(cache, sigs, markets):
    """token -> [(t, p)] runt varje signal som räknas. Saknad historik ger spelarens pris."""
    out, end = defaultdict(list), max(replay.DELAYS) + 60
    for s in sigs:
        if not replay.keep(s, markets.get(s["cid"])):
            continue
        params = {"market": s["token"], "startTs": s["t"] - BEFORE, "endTs": s["t"] + end,
                  "fidelity": 1}  # fmt: skip
        try:
            body = cache.get_json(HISTORY, params)
        except requests.HTTPError:
            continue
        out[s["token"]] += [(x["t"], x["p"]) for x in body.get("history") or []]
    return out


def build(players, cache, now, days):
    start = (now // DAY - days) * DAY
    fills = []
    for i, p in enumerate(players):
        rows, _ = polymarket.activity(cache, p["wallet"], start)
        fills += [replay.fill(r, i) for r in rows if r.get("type", "TRADE") == "TRADE"]
    sigs = replay.signals(fills)
    cids = sorted({s["cid"] for s in sigs})
    markets = {m["conditionId"]: replay.market(m) for m in polymarket.gamma_markets(cache, cids)}
    trades = replay.trades(fills, markets, history(cache, sigs, markets))
    return len(sigs), {
        "generated_at": iso(now),
        "sample": False,
        "from": day(start),
        "to": day(now),
        "delays": replay.DELAYS,
        "stake_usd": int(replay.STAKE),
        "players": names(players),
        "trades": trades,
    }


def main(argv=None, http=None, now=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("outfile")
    ap.add_argument("--players", required=True)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--cache", default=".replay-cache")
    a = ap.parse_args(argv)
    players = json.loads(Path(a.players).read_text())
    now = int(now or time.time())
    http = http or HttpClient(min_interval=dict.fromkeys(HOSTS, 0.2))
    cache = Cache(http, a.cache, day(now))
    t0 = time.monotonic()
    out = Path(a.outfile)
    try:
        n, doc = build(players, cache, now, a.days)
        check({out.name: doc})
    except requests.RequestException as e:  # URL:en kan innehålla en adress: visa den inte
        status = getattr(e.response, "status_code", None) or type(e).__name__
        sys.exit(f"Stoppar, inget skrivet: API:et svarade inte ({status})")
    except ValueError as e:
        sys.exit(f"Stoppar, inget skrivet: {e}")
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    size = len(text.encode())
    print(f"{len(players)} spelare, {n} signaler, {len(doc['trades'])} köp, {size} byte, "
          f"{cache.calls} anrop, {time.monotonic() - t0:.0f} s. Skrev {out.name}.")  # fmt: skip


if __name__ == "__main__":
    main()
