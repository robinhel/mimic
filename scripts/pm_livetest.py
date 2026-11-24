"""Livetest på Polymarket med låtsaspengar. Följer valda spelare och sparar riktiga priser.
Inga affärer och ingen inloggning: bara GET mot Polymarkets öppna API:er.

    python scripts/pm_livetest.py run DATADIR [--db copycheck.db] [--poll 15]
    python scripts/pm_livetest.py report DATADIR

DATADIR har players.json: [{"wallet", "name", "safe", "source"}], där source är "vår" (standard)
eller listan spelaren kom från, till exempel "polkyo". Programmet skriver fills.jsonl
(spelarnas affärer), events.jsonl (signaler, försäljningar, orderböcker) och heartbeat.json.
"""

import argparse
import json
import math
import os
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

from copycheck import config, polymarket
from copycheck.http import HttpClient
from copycheck.kalshi import iso_ts

DATA = config.POLYMARKET_DATA_URL + "/v2"
BOOK = "https://clob.polymarket.com/book"
MIN_USD, WINDOW = config.MIN_SIGNAL_USD, config.SIGNAL_WINDOW  # 250 $, 10 min: som backtestet
CONSENSUS = 3 * 86400
SNAP_DELAYS = [30, 120]  # extra orderböcker efter upptäckt, för manuellt godkännande
BASE, SHORT, DAY = 10.0, 3600, 86400
# Blockkedjan Polygon: affärerna syns inom sekunder, mot cirka 8 min i Data API.
# OrderFilled(orderHash, maker, taker; side, tokenId, makerAmount, takerAmount, fee, ...),
# en händelse per order. Vi läser bara rader där spelaren är maker, alltså spelarens egen order.
RPC = os.environ.get("POLYGON_RPC_URL", "https://polygon-bor-rpc.publicnode.com")
EXCHANGES = [
    "0xe111180000d2663c0091e4f400237545b87b996b",
    "0xe2222d279d744050d28e00520010520000310f59",
    "0xe3333700ca9d93003f00f0f71f8515005f6c00aa",
]
FILL = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"
API_PER_ROUND = 4  # spelare per varv mot Data API, som reserv för det kedjan missar
# Brett läge (fler än BIG spelare): bara kedjan, ingen databas, mindre på disk och i minnet.
BIG, BIG_LEVELS, PRUNE_EVERY = 500, 10, 3600


def jl(path, obj):
    with open(path, "a") as f:
        f.write(json.dumps(obj) + "\n")


def parse_jl(line):
    """En rad ur en .jsonl-fil, eller None. Efter ett strömavbrott kan raden vara nollbyte."""
    try:
        return json.loads(line.strip("\0").strip())
    except ValueError:
        return None


def read_jl(path):
    if not path.exists():
        return []
    with open(path, errors="replace") as f:
        return [o for o in map(parse_jl, f) if o is not None]


def fee(shares, p, on):
    return math.ceil(0.07 * shares * p * (1 - p) * 100 - 1e-9) / 100 if on else 0.0


def levels(book, side):
    lv = [(float(x["price"]), float(x["size"])) for x in book.get(side) or []]
    return sorted(lv, reverse=side == "bids")[:30]


def buy_fill(asks, usd):
    """Andelar för `usd` dollar mot säljarnas bud. None om boken inte räcker."""
    shares = 0.0
    for p, s in asks:
        take = min(usd, p * s)
        shares += take / p
        usd -= take
        if usd <= 1e-9:
            return shares
    return None


def sell_fill(bids, shares):
    """Dollar för `shares` andelar mot köparnas bud. Resten värderas till noll."""
    got = 0.0
    for p, s in bids:
        q = min(shares, s)
        got += q * p
        shares -= q
        if shares <= 1e-9:
            break
    return got


class Live:
    def __init__(self, d, db):
        self.d, self.http = Path(d), HttpClient()
        self.players = {p["wallet"]: p for p in json.loads((self.d / "players.json").read_text())}
        self.fills_path, self.events_path = self.d / "fills.jsonl", self.d / "events.jsonl"
        self.hold = defaultdict(float)  # (wallet, token) -> andelar spelaren har
        self.groups = {}  # (wallet, token) -> pågående köpgrupp
        self.triggers = defaultdict(list)  # token -> [(tid, wallet)]
        self.seen, self.last = set(), {}
        self.txsrc = {}  # (tx, token, side) -> "chain" eller "api"
        self.rpc, self.block, self.btime, self.tokens = requests.Session(), None, {}, {}
        self.open = {
            (e["wallet"], e["token"]) for e in read_jl(self.events_path) if e["type"] == "signal"
        }
        self.markets, self.pending = {}, []
        self.big, self.pruned = len(self.players) > BIG, time.time()
        self.wallet_set = set(self.players)
        self.seed(db)

    def seed(self, db):
        """Spelarnas innehav från databasen, sedan affärer från fills.jsonl och det som saknas."""
        if self.big:  # bara framåt: inget innehav från förr, bara det fills.jsonl har sparat
            now = int(time.time())
            self.last = dict.fromkeys(self.players, now)
            for f in read_jl(self.fills_path):
                if f.get("kind") == "hold":
                    self.hold[(f["wallet"], f["token"])] = f["size"]
                else:
                    self.apply(f, live=False)
            print(f"brett läge: {len(self.players)} spelare, bara kedjan", flush=True)
            return
        ph = ",".join("?" * len(self.players))
        conn = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
        for w, tok, n in conn.execute(
            f"""SELECT wallet, token_id, SUM(CASE side WHEN 'BUY' THEN size ELSE -size END)
                FROM pm_activity WHERE wallet IN ({ph}) GROUP BY wallet, token_id""",
            list(self.players),
        ):
            self.hold[(w, tok)] = max(n, 0.0)
        for w, ts in conn.execute(
            f"SELECT wallet, MAX(trade_ts) FROM pm_activity WHERE wallet IN ({ph}) GROUP BY wallet",
            list(self.players),
        ):
            self.last[w] = ts + 1
        now = int(time.time())
        for w in self.players:
            self.last.setdefault(w, now - CONSENSUS)
        for f in read_jl(self.fills_path):
            self.apply(f, live=False)
        print(f"ikapp: hämtar affärer sedan databasen, {len(self.players)} spelare", flush=True)
        for w in self.players:
            self.poll(w, live=False)
        print(f"ikapp klar, {len(self.seen)} affärer i minnet", flush=True)

    def poll(self, w, live):
        params = {"user": w, "type": "TRADE", "start": self.last[w], "limit": 1000}
        rows = []
        while True:
            body = self.http.get_json(DATA + "/activity", params)
            rows += body.get("data") or []
            cur = (body.get("pagination") or {}).get("next_cursor")
            if not cur:
                break
            params["cursor"] = cur
        now = int(time.time())
        for r in sorted(rows, key=lambda r: r["timestamp"]):
            f = {
                "wallet": w,
                "token": r["token_id"],
                "cid": r["condition_id"],
                "idx": r.get("outcome_index"),
                "side": r["side"],
                "price": float(polymarket.price(r["price"])),
                "size": float(r["size"]),
                "usd": float(r.get("usdc_size") or r["price"] * r["size"]),
                "ts": r["timestamp"],
                "seen": now,
                "tx": r["transaction_hash"],
                "title": r.get("title"),
            }
            if (
                self.key(f) in self.seen
                or self.txsrc.get((f["tx"], f["token"], f["side"])) == "chain"
            ):
                continue
            jl(self.fills_path, f)
            # Ett köp som syns först efter 15 min räknas inte som levande signal.
            self.apply(f, live=live and now - f["ts"] <= 900)

    def call(self, method, params):
        r = self.rpc.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                          timeout=20).json()  # fmt: skip
        if "error" in r:
            raise RuntimeError(r["error"])
        return r["result"]

    def token_info(self, token):
        """(condition_id, outcome_index, fråga) från Gamma. None om Gamma inte känner svaret."""
        if token not in self.tokens:
            self.tokens[token] = None
            for closed in ("false", "true"):
                url = config.POLYMARKET_GAMMA_URL + "/markets"
                for m in (
                    self.http.get_json(url, {"clob_token_ids": [token], "closed": closed}) or []
                ):
                    ids = json.loads(m.get("clobTokenIds") or "[]")
                    if token in ids:
                        self.tokens[token] = (m["conditionId"], ids.index(token), m.get("question"))
        return self.tokens[token]

    def poll_chain(self):
        head = int(self.call("eth_blockNumber", []), 16)
        if self.block is None:  # börja nu; det som hände före fångar Data API
            self.block = head
        if head <= self.block:
            return
        to = min(head, self.block + 500)
        if self.big:  # för många plånböcker för ett filter i noden: filtrera här
            to = min(head, self.block + 100)
        wallets = None if self.big else ["0x" + "0" * 24 + w[2:] for w in self.players]
        try:
            q = {"fromBlock": hex(self.block + 1), "toBlock": hex(to)}
            q |= {"address": EXCHANGES, "topics": [FILL, None, wallets]}
            logs = self.call("eth_getLogs", [q])
        except RuntimeError:  # noderna hos leverantören ligger ibland ett block efter
            return
        if self.big:
            logs = [lg for lg in logs if "0x" + lg["topics"][2][-40:] in self.wallet_set]
        agg = {}
        for lg in logs:
            x = [int(lg["data"][2 + 64 * i : 66 + 64 * i], 16) for i in range(4)]
            side = "BUY" if x[0] == 0 else "SELL"
            shares, usd = (x[3], x[2]) if side == "BUY" else (x[2], x[3])
            k = (lg["transactionHash"], "0x" + lg["topics"][2][-40:], str(x[1]), side)
            a = agg.setdefault(k, {"shares": 0, "usd": 0, "block": int(lg["blockNumber"], 16)})
            a["shares"] += shares / 1e6
            a["usd"] += usd / 1e6
        now = int(time.time())
        for (tx, w, token, side), a in sorted(agg.items(), key=lambda kv: kv[1]["block"]):
            if (tx, token, side) in self.txsrc or a["shares"] <= 0:
                continue
            info = self.token_info(token)
            if info is None:
                continue  # Data API tar den
            if a["block"] not in self.btime:
                b = self.call("eth_getBlockByNumber", [hex(a["block"]), False])
                self.btime[a["block"]] = int(b["timestamp"], 16)
            f = {
                "wallet": w,
                "token": token,
                "cid": info[0],
                "idx": info[1],
                "side": side,
                "price": float(polymarket.price(a["usd"] / a["shares"])),
                "size": a["shares"],
                "usd": a["usd"],
                "ts": self.btime[a["block"]],
                "seen": now,
                "tx": tx,
                "title": info[2],
                "src": "chain",
            }
            if not self.big:
                jl(self.fills_path, f)
            self.apply(f, live=now - f["ts"] <= 900)
            if self.big and (w, token) in self.open:  # bara affärer vi härmar sparas
                jl(self.fills_path, f)
        self.block = to

    @staticmethod
    def key(f):
        return (f["tx"], f["token"], f["side"], f["price"], f["size"])

    def apply(self, f, live):
        k = (f["wallet"], f["token"])
        if not self.big:  # dubbletter mellan kedjan och Data API finns bara i vanligt läge
            self.seen.add(self.key(f))
            self.txsrc.setdefault((f["tx"], f["token"], f["side"]), f.get("src", "api"))
        self.last[f["wallet"]] = max(self.last.get(f["wallet"], 0), f["ts"])
        if f["side"] == "BUY":
            self.hold[k] += f["size"]
            g = self.groups.get(k)
            if not g or f["ts"] - g["last"] > WINDOW:
                g = self.groups[k] = {
                    "usd": 0.0,
                    "size": 0.0,
                    "val": 0.0,
                    "last": f["ts"],
                    "trig": False,
                }
            g["usd"] += f["usd"]
            g["size"] += f["size"]
            g["val"] += f["price"] * f["size"]
            g["last"] = f["ts"]
            if not g["trig"] and g["usd"] >= MIN_USD:
                g["trig"] = True
                if live:
                    self.signal(f, g)
                self.triggers[f["token"]].append((f["ts"], f["wallet"]))
        else:
            before = self.hold[k]
            frac = 1.0 if before <= f["size"] + 1e-9 else f["size"] / before
            self.hold[k] = max(before - f["size"], 0.0)
            if live and k in self.open:
                self.event(
                    {
                        "type": "sell",
                        "wallet": f["wallet"],
                        "token": f["token"],
                        "frac": frac,
                        "trade_ts": f["ts"],
                        "seen": f["seen"],
                        "trader_price": f["price"],
                        "book": self.book(f["token"]),
                    }
                )

    def market(self, cid):
        if cid not in self.markets:
            m = (polymarket.gamma_markets(self.http, [cid]) or [{}])[0]
            self.markets[cid] = {"end": iso_ts(m.get("endDate")), "question": m.get("question")}
        return self.markets[cid]

    def book(self, token):
        try:
            b = self.http.get_json(BOOK, {"token_id": token})
            n = BIG_LEVELS if self.big else None
            asks, bids = levels(b, "asks")[:n], levels(b, "bids")[:n]
            return {"t": int(time.time()), "asks": asks, "bids": bids}
        except Exception as e:  # en bok som saknas ska inte stoppa testet
            return {"t": int(time.time()), "error": str(e)}

    def signal(self, f, g):
        others = sorted(
            {
                w
                for t, w in self.triggers[f["token"]]
                if w != f["wallet"] and f["ts"] - CONSENSUS <= t <= f["ts"]
            }
        )
        m = self.market(f["cid"])
        sid = f"{f['wallet'][:10]}-{f['token'][-10:]}-{f['ts']}"
        self.open.add((f["wallet"], f["token"]))
        if self.big:  # innehavet före signalen, så att försäljningar räknas rätt efter omstart
            jl(self.fills_path, {"kind": "hold", "wallet": f["wallet"], "token": f["token"],
                                 "size": self.hold[(f["wallet"], f["token"])]})  # fmt: skip
        self.event(
            {
                "type": "signal",
                "id": sid,
                "wallet": f["wallet"],
                "name": self.players[f["wallet"]]["name"],
                "safe": self.players[f["wallet"]].get("safe", False),
                "source": self.players[f["wallet"]].get("source", "vår"),
                "token": f["token"],
                "cid": f["cid"],
                "idx": f["idx"],
                "title": f["title"],
                "trade_ts": f["ts"],
                "seen": f["seen"],
                "trader_price": g["val"] / g["size"],
                "usd": g["usd"],
                "end": m["end"],
                "others": others,
                "book": self.book(f["token"]),
            }
        )
        now = int(time.time())
        if not self.big:
            self.pending += [(now + d, d, sid, f["token"]) for d in SNAP_DELAYS]

    def event(self, e):
        jl(self.events_path, e)
        if not self.big:
            print(json.dumps({k: v for k, v in e.items() if k != "book"}), flush=True)

    def prune(self):
        """Brett läge: glöm det som inte längre behövs, så att minnet räcker i veckor."""
        now = time.time()
        if not self.big or now - self.pruned < PRUNE_EVERY:
            return
        self.pruned = now
        for k in [k for k, g in self.groups.items() if now - g["last"] > WINDOW]:
            del self.groups[k]
        for tok in list(self.triggers):
            self.triggers[tok] = [x for x in self.triggers[tok] if now - x[0] <= CONSENSUS]
            if not self.triggers[tok]:
                del self.triggers[tok]
        keep = {k for k in self.hold if k in self.open or k in self.groups}
        self.hold = defaultdict(float, {k: v for k, v in self.hold.items() if k in keep and v > 0})
        self.btime.clear()

    def run(self, poll):
        errors, order, i = 0, list(self.players), 0
        while True:
            t0 = time.time()
            try:
                self.poll_chain()
            except Exception as e:
                errors += 1
                print(f"fel i kedjan: {e}", flush=True)
            for w in [] if self.big else order[i : i + API_PER_ROUND]:
                try:
                    self.poll(w, live=True)
                except Exception as e:
                    errors += 1
                    print(f"fel för {w[:10]}: {e}", flush=True)
            i = (i + API_PER_ROUND) % len(order)
            now = int(time.time())
            for item in [p for p in self.pending if p[0] <= now]:
                self.pending.remove(item)
                jl(
                    self.events_path,
                    {"type": "snap", "id": item[2], "after": item[1], "book": self.book(item[3])},
                )
            self.prune()
            took = time.time() - t0
            (self.d / "heartbeat.json").write_text(
                json.dumps(
                    {"t": now, "cycle_s": round(took, 1), "errors": errors, "open": len(self.open)}
                )
            )
            time.sleep(max(poll - took, 0))


# ---------------------------------------------------------------- rapport


def outcomes(d, http=None):
    """(signaler, lot). lot(s, label, fees_on) ger (resultat, kostnad, avgjord) för 10 $ köpt
    direkt (label 0) eller efter label sekunder, eller None. Slutpriser från Gamma."""
    ev = read_jl(Path(d) / "events.jsonl")
    sigs = [e for e in ev if e["type"] == "signal"]
    if not sigs:
        return [], None
    snaps = {(e["id"], e["after"]): e["book"] for e in ev if e["type"] == "snap"}
    sells = defaultdict(list)
    for e in ev:
        if e["type"] == "sell":
            sells[(e["wallet"], e["token"])].append(e)
    http = http or HttpClient()
    final = {}
    cids = sorted({s["cid"] for s in sigs})
    for m in polymarket.gamma_markets(http, cids):
        final[m["conditionId"]] = (
            [float(x) for x in json.loads(m.get("outcomePrices") or "[]")],
            bool(m.get("closed")),
        )

    def lot(s, label, fees_on):
        book = s["book"] if label == 0 else snaps.get((s["id"], label))
        if not book or "asks" not in book:
            return None
        sh = buy_fill(book["asks"], BASE)
        if not sh:
            return None
        p = BASE / sh
        cost, got = BASE + fee(sh, p, fees_on), 0.0
        for x in sorted(sells[(s["wallet"], s["token"])], key=lambda x: x["trade_ts"]):
            if x["trade_ts"] <= s["trade_ts"] or "bids" not in x["book"]:
                continue
            q = sh * x["frac"]
            v = sell_fill(x["book"]["bids"], q)
            got += v - (fee(q, v / q, fees_on) if q > 1e-9 and v > 0 else 0)
            sh -= q
        prices, closed = final.get(s["cid"], ([], False))
        if s["idx"] is None or s["idx"] >= len(prices):
            return None
        return got + sh * prices[s["idx"]] - cost, cost, closed

    return sigs, lot


def report(d):
    d = Path(d)
    sigs, lot = outcomes(d)
    if not sigs:
        print("Inga signaler än.")
        return
    out = [
        f"# Livetest Polymarket\n\n{len(sigs)} signaler. Skapad "
        f"{time.strftime('%Y-%m-%d %H:%M', time.localtime())}.\n"
    ]
    delays = [s["seen"] - s["trade_ts"] for s in sigs]
    fills = [(buy_fill(s["book"]["asks"], BASE), s) for s in sigs if "asks" in s["book"]]
    paid = [BASE / x - s["trader_price"] for x, s in fills if x]
    out.append(
        f"Fördröjning från spelarens köp till vi såg det: median "
        f"{statistics.median(delays):.0f} s, längsta {max(delays)} s."
    )
    if paid:
        out.append(
            f"Vårt pris minus spelarens pris: median {statistics.median(paid) * 100:+.1f} "
            f"cent, snitt {statistics.mean(paid) * 100:+.1f} cent.\n"
        )
    out += [
        "| spelare | filter | köp efter | affärer | avgjorda | ROI utan avgift | ROI med avgift |",
        "|---|---|---|---|---|---|---|",
    ]
    # Äldre signaler saknar "source". "Flera spelare" räknar bara spelare från samma lista.
    players = json.loads((d / "players.json").read_text())
    src = {p["wallet"]: p.get("source", "vår") for p in players}
    filters = {
        "alla köp": lambda s: True,
        "≥ 1 dag kvar": lambda s: bool(s["end"] and s["end"] - s["trade_ts"] >= DAY),
        "flera spelare": lambda s: any(src.get(w) == s.get("source", "vår") for w in s["others"]),
    }
    groups = [
        ("våra", lambda s: s.get("source", "vår") == "vår"),
        ("8 säkra", lambda s: s["safe"]),
    ] + [(x, lambda s, x=x: s.get("source") == x) for x in sorted(set(src.values()) - {"vår"})]
    for gname, gsel in groups:
        for fname, keep in filters.items():
            for label in [0] + SNAP_DELAYS:
                chosen = [
                    s
                    for s in sigs
                    if gsel(s) and keep(s) and not (s["end"] and s["end"] - s["trade_ts"] < SHORT)
                ]
                res = [r for s in chosen if (r := lot(s, label, False))]
                resf = [r for s in chosen if (r := lot(s, label, True))]
                if not res:
                    continue
                roi = sum(r[0] for r in res) / sum(r[1] for r in res)
                roif = sum(r[0] for r in resf) / sum(r[1] for r in resf)
                when = "direkt" if label == 0 else f"+{label} s"
                out.append(
                    f"| {gname} | {fname} | {when} | {len(res)} "
                    f"| {sum(r[2] for r in res)} | {roi:+.1%} | {roif:+.1%} |"
                )
    text = "\n".join(out)
    (d / "rapport.md").write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "report"])
    ap.add_argument("datadir")
    ap.add_argument("--db", default=config.DB_PATH)
    ap.add_argument("--poll", type=int, default=3)
    a = ap.parse_args()
    if a.cmd == "run":
        Live(a.datadir, a.db).run(a.poll)
    else:
        report(a.datadir)
    sys.exit(0)
