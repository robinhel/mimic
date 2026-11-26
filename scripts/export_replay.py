"""Skriver replay_trades.json till fliken Replay: hur det hade gått att härma spelarna i efterhand.

    python scripts/export_replay.py OUTFILE --players PLAYERS_JSON [--days 90] [--cache DIR]

PLAYERS_JSON: [{"wallet", "name", "safe", "source"}] som i pm_livetest.py. Hämtar spelarnas affärer
(Data API v2 /activity) från midnatt UTC för --days + 3 dagar sedan, så att innehav och "others"
blir rätt, men skriver bara signaler från de senaste --days dagarna. Högst
--max-signals-per-player signaler per spelare (de nyaste). Marknaderna hämtas från Gamma i
omgångar om 50, prishistoriken från CLOB en gång per token och tidsspann (högst 14 dagar per
anrop). Räkningen finns i mimic.replay. Resultaten är
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
from collections import Counter, defaultdict
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
AFTER = max(replay.DELAYS) + 60
SPAN = 14 * DAY  # prices-history tar högst 15 dagar per anrop (sett 2026-11-26)
GAP = DAY  # signaler i samma token med mer än en dag emellan hämtas var för sig


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


def windows(times):
    """[start, slut] som täcker varje signal, ihopslagna om de ligger nära, högst SPAN långa."""
    out = []
    for t in sorted(times):
        a, b = t - BEFORE, t + AFTER
        if out and a - out[-1][1] <= GAP and b - out[-1][0] <= SPAN:
            out[-1][1] = b
        else:
            out.append([a, b])
    return out


def history(cache, sigs):
    """token -> [(t, p)] för signalerna. Saknad historik ger spelarens pris."""
    times = defaultdict(list)
    for s in sigs:
        times[s["token"]].append(s["t"])
    out = defaultdict(list)
    for token, ts in times.items():
        for a, b in windows(ts):
            params = {"market": token, "startTs": a, "endTs": b, "fidelity": 1}
            try:
                body = cache.get_json(HISTORY, params)
            except requests.HTTPError:
                continue
            out[token] += [(x["t"], x["p"]) for x in body.get("history") or []]
    return out


def cap(sigs, n):
    """De n nyaste signalerna per spelare, och vilka spelare som kapades."""
    by = defaultdict(list)
    for s in sigs:
        by[s["p"]].append(s)
    kept, capped = [], set()
    for p, xs in by.items():
        xs.sort(key=lambda s: s["t"], reverse=True)
        kept += xs[:n]
        if len(xs) > n:
            capped.add(p)
    return sorted(kept, key=lambda s: (s["t"], s["p"])), capped


def build(players, cache, now, days, max_signals):
    start = (now // DAY - days) * DAY
    fills = []
    for i, p in enumerate(players):
        rows, _ = polymarket.activity(cache, p["wallet"], start - replay.CONSENSUS)
        fills += [replay.fill(r, i) for r in rows if r.get("type", "TRADE") == "TRADE"]
    sigs = [s for s in replay.signals(fills) if s["t"] >= start]
    cids = sorted({s["cid"] for s in sigs})
    markets = {m["conditionId"]: replay.market(m) for m in polymarket.gamma_markets(cache, cids)}
    skipped = Counter(r for s in sigs if (r := replay.skip_reason(s, markets.get(s["cid"]))))
    chosen, capped = cap([s for s in sigs if replay.keep(s, markets.get(s["cid"]))], max_signals)
    trades = replay.trades(fills, markets, history(cache, chosen), chosen)
    who = names(players)
    stats = {"signals": len(sigs), "skipped": skipped,
             "capped": [who[p]["name"] for p in sorted(capped)]}  # fmt: skip
    return stats, {
        "generated_at": iso(now),
        "sample": False,
        "from": day(start),
        "to": day(now),
        "delays": replay.DELAYS,
        "stake_usd": int(replay.STAKE),
        "players": who,
        "trades": trades,
    }


def summary(players, stats, doc, size, calls, took):
    skipped = ", ".join(f"{k} {v}" for k, v in sorted(stats["skipped"].items())) or "inga"
    capped = ", ".join(stats["capped"]) or "inga"
    return (f"{len(players)} spelare, {stats['signals']} signaler, {len(doc['trades'])} köp, "
            f"{size} byte ({size / 1e6:.1f} MB), {calls} anrop, {took:.0f} s.\n"
            f"Bortfall: {skipped}. Kapade spelare: {capped}.")  # fmt: skip


def main(argv=None, http=None, now=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("outfile")
    ap.add_argument("--players", required=True)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--cache", default=".replay-cache")
    ap.add_argument("--max-signals-per-player", type=int, default=2000)
    a = ap.parse_args(argv)
    players = json.loads(Path(a.players).read_text())
    now = int(now or time.time())
    http = http or HttpClient(min_interval=dict.fromkeys(HOSTS, 0.2))
    cache = Cache(http, a.cache, day(now))
    t0 = time.monotonic()
    out = Path(a.outfile)
    try:
        stats, doc = build(players, cache, now, a.days, a.max_signals_per_player)
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
    print(summary(players, stats, doc, size, cache.calls, time.monotonic() - t0))
    print(f"Skrev {out.name}.")


if __name__ == "__main__":
    main()
