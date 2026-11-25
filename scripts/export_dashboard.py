"""Skriver JSON-filerna till dashboarden (se kontraktet för dashboard/public/data/).

    python scripts/export_dashboard.py OUTDIR --live DATADIR [--run NAME=DATADIR ...]
        [--db copycheck.db] [--robot ROBOTDIR | --robot-api]

--live: senaste livetestet (summary, equity, traders, latency). --run: en rad per testkörning
i runs.json (mappar utan signaler hoppas över); live_run i summary är namnet på den --run som
har samma mapp som --live, annars mappens namn. --db: antal sim_trades och Kalshi-backtestens
ROI. --robot: en kopia av robotens mapp (robot.jsonl, gärna state.json) där roboten bara körts
med --live; torrkörda händelser stoppar exporten. --robot-api: robotens riktiga köp, försäljningar
och inlösen från Polymarkets Data API v2, för adressen i POLYMARKET_WALLET_ADDRESS (.env, bara
lokalt; adressen skrivs aldrig ut). Utan båda tas en gammal robot.json bort.
Räknar som pm_livetest.py report: 10 $ per köp direkt, utan marknader som slutar inom en timme.
Innan något skrivs letar programmet efter plånböcker, nycklar och hemligheter och stoppar.
"""

import argparse
import json
import os
import re
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import requests

from copycheck import polymarket, report
from copycheck.http import HttpClient

sys.path.insert(0, str(Path(__file__).parent))
from pm_livetest import BASE, SHORT, buy_fill, outcomes, read_jl  # noqa: E402

FORBIDDEN_KEYS = {"wallet", "tx_hash", "token", "cid", "address"}
FORBIDDEN = re.compile(r"0x[0-9a-fA-F]{8,}|POLYMARKET_\w*|GROQ_API_KEY|PRIVATE_KEY")
BUCKETS = [(1, "0–1 s"), (2, "1–2 s"), (5, "2–5 s"), (15, "5–15 s"), (60, "15–60 s"),
           (300, "1–5 min"), (float("inf"), "> 5 min")]  # fmt: skip
ROBOT_TYPES = ("buy", "sell", "settled", "skip")


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def day(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d")


def pct(pnl, cost):
    return round(pnl / cost * 100, 1) if cost else None


def results(d, http):
    """[(signal, utan avgift, med avgift)] som i rapporten: direkt, inga korta marknader."""
    sigs, lot = outcomes(d, http)
    out = []
    for s in sigs:
        if s["end"] and s["end"] - s["trade_ts"] < SHORT:
            continue
        r, rf = lot(s, 0, False), lot(s, 0, True)
        if r and rf:
            out.append((s, r, rf))
    return sigs, out


def totals(res):
    return {
        "buys": len(res),
        "settled": sum(bool(r[2]) for _, r, _ in res),
        "roi_pct": pct(sum(r[0] for _, r, _ in res), sum(r[1] for _, r, _ in res)),
        "roi_fee_pct": pct(sum(f[0] for _, _, f in res), sum(f[1] for _, _, f in res)),
    }


def live_files(d, http):
    sigs, res = results(d, http)
    players = json.loads((Path(d) / "players.json").read_text())
    tot = totals(res)
    summary = {
        "live_roi_pct": tot["roi_pct"],
        "live_roi_fee_pct": tot["roi_fee_pct"],
        "live_buys": tot["buys"],
        "live_settled": tot["settled"],
        "players": len(players),
        "players_trusted": sum(bool(p.get("safe")) for p in players),
    }
    pnl, equity = 0.0, []
    for s, _, f in sorted(res, key=lambda x: x[0]["trade_ts"]):
        if not equity:
            equity.append({"t": iso(s["trade_ts"]), "pnl_usd": 0.0})
        pnl += f[0]
        equity.append({"t": iso(s["trade_ts"]), "pnl_usd": round(pnl, 2)})
    per = defaultdict(list)
    for x in res:
        per[x[0]["wallet"]].append(x)
    traders, unnamed = [], 0
    for p in players:  # bara spelare vi har härmat, i ordningen i players.json
        if p["wallet"] not in per:
            continue
        name = p.get("name") or ""
        if not name or name.startswith("0x"):
            unnamed += 1
            name = f"Trader {unnamed}"
        t = totals(per[p["wallet"]])
        traders.append({"name": name, "source": p.get("source", "vår"),
                        "safe": bool(p.get("safe")), "copied": t["buys"],
                        "settled": t["settled"], "roi_pct": t["roi_pct"],
                        "roi_fee_pct": t["roi_fee_pct"]})  # fmt: skip
    delays = [s["seen"] - s["trade_ts"] for s in sigs]
    fills = [(buy_fill(s["book"]["asks"], BASE), s) for s in sigs if "asks" in s["book"]]
    paid = [BASE / x - s["trader_price"] for x, s in fills if x]
    counts = {label: 0 for _, label in BUCKETS}
    for x in delays:
        counts[next(label for top, label in BUCKETS if x < top)] += 1
    latency = {
        "median_s": statistics.median(delays) if delays else None,
        "max_s": max(delays) if delays else None,
        "buckets": [{"label": k, "count": v} for k, v in counts.items()],
        "price_diff_cent_median": round(statistics.median(paid) * 100, 1) if paid else None,
    }
    return summary, equity, traders, latency


def run_row(name, d, http):
    """Rad för runs.json, eller None om mappen saknar signaler."""
    sigs, res = results(d, http)
    ts = [s["trade_ts"] for s in sigs]
    if not ts:
        return None
    return {"name": name, "from": day(min(ts)), "to": day(max(ts)), **totals(res)}


def kalshi(path):
    """(antal sim_trades, rad för runs.json eller None). ROI efter avgift vid 2 min, strategi A."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    n = conn.execute("SELECT COUNT(*) FROM sim_trades").fetchone()[0]
    head = next(
        (r for r in report.summary(conn, "all") if (r["delay"], r["strategy"]) == report.HEADLINE),
        None,
    )
    if not head or head["roi"] is None:
        conn.close()
        return n, None
    lo, hi, settled = conn.execute(
        """SELECT MIN(s.trigger_ts), MAX(s.trigger_ts), SUM(t.exit_kind != 'open')
           FROM sim_trades t JOIN signals s ON s.id = t.signal_id
           WHERE t.skip_reason IS NULL AND t.delay = ? AND t.strategy = ?""",
        report.HEADLINE,
    ).fetchone()
    conn.close()
    return n, {"name": "Kalshi backtest", "from": day(lo), "to": day(hi), "buys": head["trades"],
               "settled": settled or 0, "roi_pct": None,
               "roi_fee_pct": round(head["roi"] * 100, 1)}  # fmt: skip


def robot_file(d):
    d = Path(d)
    ev = read_jl(d / "robot.jsonl")
    if any(e.get("dry") is True for e in ev):
        raise ValueError("robot.jsonl contains dry-run events; export only a --live robot dir")
    ev = [e for e in ev if e.get("type") in ROBOT_TYPES]
    state = d / "state.json"
    buys = sum(e["type"] == "buy" for e in ev)
    settled = sum(e["type"] == "settled" for e in ev)
    return {
        "spent_usd": round(sum(e.get("usd") or 0 for e in ev if e["type"] == "buy"), 2),
        "back_usd": round(
            sum(e.get("usd") or 0 for e in ev if e["type"] in ("sell", "settled")), 2
        ),
        # Utan state.json: köp som inte är avgjorda (försäljningar kan vara delvisa).
        "open": len(json.loads(state.read_text())["pos"]) if state.exists() else buys - settled,
        "events": [
            {"t": iso(e["t"]), "type": e["type"], "title": e.get("title"), "usd": e.get("usd")}
            for e in ev
        ],
    }


def robot_api(address, http):
    """robot.json från Data API v2. TRADE BUY/SELL och REDEEM; andra typer hoppas över.
    Öppna: positioner med andelar kvar som inte är avgjorda (förlorade ligger kvar som
    redeemable). Felmeddelanden får inte innehålla adressen (den står i URL:en)."""
    try:
        rows, _ = polymarket.fetch_all(http, "/activity", {"user": address, "limit": 500})
        pos, _ = polymarket.fetch_all(http, "/positions", {"user": address, "limit": 500})
    except requests.RequestException as e:
        status = getattr(e.response, "status_code", None) or type(e).__name__
        raise ValueError(f"Polymarkets Data API svarade inte ({status})") from None
    kinds = {("TRADE", "BUY"): "buy", ("TRADE", "SELL"): "sell", ("REDEEM", ""): "settled"}
    ev = sorted(
        ((r["timestamp"], kinds[k], r.get("title") or None, float(r["usdc_size"]))
         for r in rows if (k := (r.get("type"), r.get("side") or "")) in kinds),
        key=lambda e: e[0],
    )  # fmt: skip
    return {
        "spent_usd": round(sum(e[3] for e in ev if e[1] == "buy"), 2),
        "back_usd": round(sum(e[3] for e in ev if e[1] != "buy"), 2),
        "open": sum(p["current_size"] > 0 and not p.get("redeemable") for p in pos),
        "events": [{"t": iso(t), "type": k, "title": ti, "usd": round(u, 2)} for t, k, ti, u in ev],
    }


def build(live, http=None, now=None, runs=(), db_path=None, robot=None, robot_address=None):
    http = http or HttpClient()
    summary, equity, traders, latency = live_files(live, http)
    rows = [r for name, d in runs if (r := run_row(name, d, http))]
    live_run = next((name for name, d in runs if Path(d).resolve() == Path(live).resolve()), None)
    sim_trades, kalshi_roi = 0, None
    if db_path:
        sim_trades, row = kalshi(db_path)
        if row:
            rows.append(row)
            kalshi_roi = row["roi_fee_pct"]
    rows.sort(key=lambda r: (r["from"], r["to"]))
    out = {
        "summary.json": {"generated_at": iso(now or time.time()), "sample": False,
                         "sim_trades": sim_trades, "kalshi_roi_pct": kalshi_roi,
                         "live_run": live_run or Path(live).resolve().name, **summary},
        "runs.json": rows,
        "equity.json": equity,
        "traders.json": traders,
        "latency.json": latency,
    }  # fmt: skip
    if robot:
        out["robot.json"] = robot_file(robot)
    elif robot_address:
        out["robot.json"] = robot_api(robot_address, http)
    return out


def check(files):
    """ValueError om något förbjudet finns: nycklar, adresser eller namn på hemligheter."""

    def walk(x, name, field):
        where = f"{name}, fält {field or '(roten)'}"
        if isinstance(x, dict):
            for k, v in x.items():
                sub = f"{field}.{k}" if field else str(k)
                if k in FORBIDDEN_KEYS or FORBIDDEN.search(str(k)):
                    raise ValueError(f"{name}, fält {sub}: förbjuden nyckel {k!r}")
                walk(v, name, sub)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, name, f"{field}[{i}]")
        elif isinstance(x, str) and (m := FORBIDDEN.search(x)):
            what = "0x-adress" if m.group().startswith("0x") else m.group()
            raise ValueError(f"{where}: förbjudet innehåll ({what})")

    for name, data in files.items():
        walk(data, name, "")


def main(argv=None, http=None, now=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("outdir")
    ap.add_argument("--live", required=True)
    ap.add_argument("--run", action="append", default=[], metavar="NAME=DATADIR")
    ap.add_argument("--db")
    who = ap.add_mutually_exclusive_group()
    who.add_argument("--robot")
    who.add_argument("--robot-api", action="store_true")
    a = ap.parse_args(argv)
    runs = []
    for r in a.run:
        name, sep, d = r.partition("=")
        if not sep:
            ap.error(f"--run ska vara NAME=DATADIR: {r}")
        runs.append((name, d))
    address = None
    if a.robot_api:
        address = os.environ.get("POLYMARKET_WALLET_ADDRESS", "").strip()
        if not address:
            sys.exit("Stoppar, inget skrivet: POLYMARKET_WALLET_ADDRESS saknas (sätt den i .env)")
    try:
        files = build(a.live, http, now, runs, a.db, a.robot, address)
        check(files)
    except ValueError as e:
        sys.exit(f"Stoppar, inget skrivet: {e}")
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (out / name).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    if "robot.json" not in files:  # en gammal robot.json får inte bli kvar
        (out / "robot.json").unlink(missing_ok=True)
    print(f"Skrev {len(files)} filer till {out}.")


if __name__ == "__main__":
    main()
