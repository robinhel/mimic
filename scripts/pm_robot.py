"""Robot som härmar Polymarket-spelare. Torrkörning som standard; riktiga order bara med --live.

Läser signaler och försäljningar som pm_livetest.py skriver i LIVEDIR/events.jsonl, köper
enligt reglerna nedan mot en färsk orderbok och skriver allt i ROBOTDIR.

    python scripts/pm_robot.py run LIVEDIR ROBOTDIR [--bank 90] [--live]
    python scripts/pm_robot.py report ROBOTDIR
    python scripts/pm_robot.py check            plånbok, saldo, godkännanden och land, inga order
    python scripts/pm_robot.py testbuy TOKEN     köper 5 andelar för högst 1,50 $ och säljer dem

--live, check och testbuy läser POLYMARKET_PRIVATE_KEY (och valfritt POLYMARKET_WALLET_ADDRESS)
från .env. Nyckeln skrivs aldrig ut. --live vägrar starta om Polymarket spärrar landet.

Regler: bara våra spelare (source "vår") och bara när en annan av dem köpt samma svar inom
3 dagar. Undantag: spelare med "safe" i players.json härmas vid alla köp.
2 % av kassan per köp, men minst 5 andelar och högst 5 $. Högst 40 öppna köp. Inget
nytt köp om kassan efter köpet blir under 20 % av startkassan. Inget köp om priset stigit mer
än 5 cent sedan spelarens köp. Finns filen ROBOTDIR/STOP köper roboten inget.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from copycheck import polymarket
from copycheck.http import HttpClient

sys.path.insert(0, str(Path(__file__).parent))
from pm_livetest import BOOK, SHORT, buy_fill, fee, jl, levels, sell_fill  # noqa: E402

MIN_SHARES, MAX_USD, SHARE, MAX_OPEN, RESERVE, MAX_SLIP = 5, 5.0, 0.02, 40, 0.20, 0.05
MAX_AGE, SETTLE_EVERY = 900, 600
MIN_USD = 1.0  # Polymarket: ett köp direkt mot boken måste vara minst 1 $
GEOBLOCK, UNIT = "https://polymarket.com/api/geoblock", 1e6  # saldon kommer i 6 decimaler


def secure_client():
    """Inloggad klient från .env. Stoppar om landet är spärrat."""
    geo = HttpClient().get_json(GEOBLOCK, {})
    if geo.get("blocked"):
        sys.exit(f"Polymarket spärrar {geo.get('country')}: inga riktiga order härifrån.")
    from dataclasses import replace

    from pm_livetest import RPC
    from polymarket import RelayerApiKey, SecureClient
    from polymarket.environments import PRODUCTION, _create_environment

    key = os.environ.get("POLYMARKET_PRIVATE_KEY")
    if not key:
        sys.exit("POLYMARKET_PRIVATE_KEY saknas i .env")
    # Bibliotekets nod (polygon.drpc.org) nekar en del frågor. Vi använder livetestets nod.
    env = _create_environment(name="production", config=replace(PRODUCTION._config, rpc_url=RPC))
    wallet = os.environ.get("POLYMARKET_WALLET_ADDRESS") or None
    # Plånböcker utan gas (deposit wallet) behöver en relayer-nyckel för godkännanden och inlösen.
    rk, ra = (
        os.environ.get("POLYMARKET_RELAYER_API_KEY"),
        os.environ.get("POLYMARKET_RELAYER_ADDRESS"),
    )
    api_key = RelayerApiKey(key=rk, address=ra) if rk and ra else None
    return SecureClient.create(private_key=key, wallet=wallet, environment=env, api_key=api_key)


def amounts(r):
    """(det vi gav, det vi fick) ur ett godkänt svar. Avräkningen sker senare, så saldot kan
    släpa; svaret är sanningen. Belopp över 10 000 tolkas som basenheter (6 decimaler)."""
    return tuple(float(x) / UNIT if float(x) > 1e4 else float(x)
                 for x in (r.making_amount, r.taking_amount))  # fmt: skip


def balance(pm, token=None):
    if token is None:
        return pm.get_balance_allowance(asset_type="COLLATERAL").balance / UNIT
    return pm.get_balance_allowance(asset_type="CONDITIONAL", token_id=token).balance / UNIT


class Robot:
    def __init__(self, live_dir, d, bank, live=False):
        self.live, self.d, self.http = Path(live_dir), Path(d), HttpClient()
        self.pm = secure_client() if live else None
        self.d.mkdir(parents=True, exist_ok=True)
        self.state_path = self.d / "state.json"
        if self.state_path.exists():
            self.s = json.loads(self.state_path.read_text())
        else:  # börja vid slutet av events.jsonl: gamla signaler är för gamla
            ev = self.live / "events.jsonl"
            self.s = {"bank": bank, "cash": bank, "pos": {}, "offset": ev.stat().st_size,
                      "realized": 0.0}  # fmt: skip
        players = json.loads((self.live / "players.json").read_text())
        self.ours = {p["wallet"] for p in players if p.get("source", "vår") == "vår"}
        self.safe = {p["wallet"] for p in players if p["wallet"] in self.ours and p.get("safe")}

    def save(self):
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.s, indent=1))
        tmp.replace(self.state_path)

    def log(self, e):
        e["t"] = int(time.time())
        jl(self.d / "robot.jsonl", e)
        print(json.dumps(e, ensure_ascii=False), flush=True)

    def book(self, token):
        b = self.http.get_json(BOOK, {"token_id": token})
        return levels(b, "asks"), levels(b, "bids")

    def skip(self, sig, why):
        self.log({"type": "skip", "id": sig["id"], "title": sig.get("title"), "why": why})

    def on_signal(self, sig, now):
        if sig.get("source", "vår") != "vår" or sig["wallet"] not in self.ours:
            return  # Polyranks spelare följs bara i livetestet
        if sig["wallet"] not in self.safe and not any(w in self.ours for w in sig["others"]):
            return  # bara när flera av våra spelare köper; de 8 säkra härmas alltid
        s = self.s
        why = None
        if (self.d / "STOP").exists():
            why = "STOP-filen finns"
        elif now - sig["trade_ts"] > MAX_AGE:
            why = f"för gammal ({now - sig['trade_ts']} s)"
        elif sig["end"] and sig["end"] - now < SHORT:
            why = "frågan avgörs inom 1 timme"
        elif sig["token"] in s["pos"]:
            why = "har redan detta svar"
        elif len(s["pos"]) >= MAX_OPEN:
            why = f"redan {MAX_OPEN} öppna köp"
        if why:
            return self.skip(sig, why)
        asks, _ = self.book(sig["token"])
        if not asks:
            return self.skip(sig, "inga säljare i boken")
        best = asks[0][0]
        if best > sig["trader_price"] + MAX_SLIP:
            return self.skip(sig, f"priset {best:.3f} mot spelarens {sig['trader_price']:.3f}")
        usd = min(max(SHARE * s["cash"], MIN_SHARES * best * 1.001, MIN_USD), MAX_USD)
        shares = buy_fill(asks, usd)
        if not shares or shares < MIN_SHARES:
            return self.skip(sig, "minsta köp kostar över 5 $ eller boken räcker inte")
        cost = usd + fee(shares, usd / shares, True)
        if self.pm:
            s["cash"] = balance(self.pm)
        if s["cash"] - cost < RESERVE * s["bank"]:
            return self.skip(sig, "kassan skulle bli under 20 %")
        if self.pm:  # FOK: hela köpet eller inget, aldrig dyrare än spelarens pris + 5 cent
            r = self.pm.place_market_order(token_id=sig["token"], side="BUY", amount=round(usd, 2),
                                           max_price=round(sig["trader_price"] + MAX_SLIP, 3),
                                           order_type="FOK")  # fmt: skip
            if not r.ok:
                return self.skip(sig, f"ordern nekades: {r.code} {r.message}")
            usd, shares = amounts(r)
            cost = usd
            s["cash"] -= cost
        else:
            s["cash"] -= cost
        s["pos"][sig["token"]] = {"wallet": sig["wallet"], "name": sig["name"], "cid": sig["cid"],
                                  "idx": sig["idx"], "title": sig["title"], "shares": shares,
                                  "cost": cost, "opened": now}  # fmt: skip
        self.log({"type": "buy", "dry": not self.pm, "id": sig["id"], "title": sig["title"],
                  "name": sig["name"], "usd": round(cost, 2), "price": round(usd / shares, 4),
                  "trader_price": sig["trader_price"], "delay": now - sig["trade_ts"]})  # fmt: skip

    def on_sell(self, e, now):
        p = self.s["pos"].get(e["token"])
        if not p or p["wallet"] != e["wallet"]:
            return
        q = min(max(p["shares"] * e["frac"], MIN_SHARES), p["shares"])
        if p["shares"] - q < MIN_SHARES:
            q = p["shares"]  # en rest under minsta köp går inte att sälja senare
        if self.pm:  # FAK: säljer det som går nu, resten ligger kvar till nästa försäljning
            r = self.pm.place_market_order(token_id=e["token"], side="SELL",
                                           shares=round(q, 2), order_type="FAK")  # fmt: skip
            if not r.ok:
                return self.log({"type": "error", "event": "sell", "title": p["title"],
                                 "error": f"{r.code} {r.message}"})  # fmt: skip
            q, got = amounts(r)
        else:
            _, bids = self.book(e["token"])
            got = sell_fill(bids, q)
            got -= fee(q, got / q, True) if got > 0 else 0
        part = q / p["shares"]
        self.s["cash"] += got
        self.s["realized"] += got - p["cost"] * part
        p["cost"] *= 1 - part
        p["shares"] -= q
        if p["shares"] <= 1e-9:
            del self.s["pos"][e["token"]]
        self.log({"type": "sell", "dry": not self.pm, "title": p["title"], "name": p["name"],
                  "shares": round(q, 3), "usd": round(got, 2)})  # fmt: skip

    def settle(self):
        pos = self.s["pos"]
        if not pos:
            return
        cids = sorted({p["cid"] for p in pos.values()})
        closed = {
            m["conditionId"]: [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
            for m in polymarket.gamma_markets(self.http, cids)
            if m.get("closed")
        }
        for token, p in list(pos.items()):
            prices = closed.get(p["cid"])
            if prices is None or p["idx"] is None or p["idx"] >= len(prices):
                continue
            got = p["shares"] * prices[p["idx"]]
            if self.pm and got > 0:  # lös in vinsten till USDC
                self.pm.redeem_positions(condition_id=p["cid"]).wait()
            self.s["cash"] = balance(self.pm) if self.pm else self.s["cash"] + got
            self.s["realized"] += got - p["cost"]
            del pos[token]
            self.log({"type": "settled", "title": p["title"], "usd": round(got, 2),
                      "pnl": round(got - p["cost"], 2)})  # fmt: skip

    def run(self, poll):
        ev, last_settle = self.live / "events.jsonl", 0
        while True:
            with open(ev, "rb") as f:
                f.seek(self.s["offset"])
                chunk = f.read()
            end = chunk.rfind(b"\n") + 1  # bara hela rader
            for line in chunk[:end].splitlines():
                e, now = json.loads(line), int(time.time())
                try:
                    if e["type"] == "signal":
                        self.on_signal(e, now)
                    elif e["type"] == "sell":
                        self.on_sell(e, now)
                except Exception as x:  # ett fel i en händelse ska inte stoppa roboten
                    self.log({"type": "error", "event": e.get("id") or e["type"], "error": str(x)})
            self.s["offset"] += end
            if time.time() - last_settle > SETTLE_EVERY:
                try:
                    self.settle()
                except Exception as x:
                    self.log({"type": "error", "event": "settle", "error": str(x)})
                last_settle = time.time()
            self.save()
            time.sleep(poll)


def report(d):
    d = Path(d)
    s = json.loads((d / "state.json").read_text())
    ev = [json.loads(x) for x in open(d / "robot.jsonl")] if (d / "robot.jsonl").exists() else []
    n = {k: sum(e["type"] == k for e in ev) for k in ("buy", "sell", "settled", "skip", "error")}
    held = sum(p["cost"] for p in s["pos"].values())
    print(f"Kassa {s['cash']:.2f} $ av {s['bank']:.2f} $. Öppna köp: {len(s['pos'])} "
          f"för {held:.2f} $. Avgjort resultat: {s['realized']:+.2f} $.")  # fmt: skip
    print(f"Köp {n['buy']}, försäljningar {n['sell']}, avgjorda {n['settled']}, "
          f"överhoppade {n['skip']}, fel {n['error']}.")  # fmt: skip
    for e in ev[-10:]:
        print(
            f"  {time.strftime('%d/%m %H:%M', time.localtime(e['t']))} {e['type']}: "
            f"{e.get('title') or e.get('event')} {e.get('why') or e.get('usd') or ''}"
        )


def check():
    pm = secure_client()
    approvals = pm.get_trading_approvals_state()
    print(f"Plånbok: {pm.wallet} ({pm.wallet_type}). Saldo: {balance(pm):.2f} USDC.")
    print(f"Godkännanden klara: {approvals.is_fully_approved}.")


def testbuy(token):
    """Ett riktigt köp av 5 andelar, högst 1,50 $, och sälj direkt. För att prova kedjan."""
    pm = secure_client()
    price = levels(HttpClient().get_json(BOOK, {"token_id": token}), "asks")[0][0]
    usd = max(round(MIN_SHARES * price * 1.02, 2), MIN_USD)
    if usd > 1.5:
        sys.exit(f"5 andelar kostar {usd:.2f} $. Välj ett billigare svar.")
    r = pm.place_market_order(
        token_id=token, side="BUY", amount=usd, max_price=round(price + 0.02, 3), order_type="FOK"
    )
    print("köp:", r)
    if not r.ok:
        return
    time.sleep(10)
    r = pm.place_market_order(token_id=token, side="SELL", shares=amounts(r)[1], order_type="FAK")
    print("sälj:", r, f"Saldo nu: {balance(pm):.2f} USDC.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "report", "check", "testbuy"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--bank", type=float, default=90.0)
    ap.add_argument("--poll", type=int, default=5)
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()
    if a.cmd == "run":
        Robot(a.args[0], a.args[1], a.bank, a.live).run(a.poll)
    elif a.cmd == "report":
        report(a.args[0])
    elif a.cmd == "check":
        check()
    else:
        testbuy(a.args[0])
