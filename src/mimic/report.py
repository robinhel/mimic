"""Rapport (fas 5): ROI per trader, fördröjning, strategi och kategori, plus beslut."""

import random
from collections import Counter, defaultdict
from datetime import UTC, datetime
from statistics import mean
from zoneinfo import ZoneInfo

MIN_TRADES = 200  # lucka 29
HEADLINE = (120, "A")  # 2 minuters fördröjning, håll till avgörande

ROWS = """
SELECT s.id, s.wallet, COALESCE(p.category, 'okänd'), t.delay, t.strategy, t.pnl, t.cost,
       t.entry_price, s.avg_price, t.stale, t.exit_kind, t.mismatch, t.skip_reason
FROM sim_trades t
JOIN signals s ON s.id = t.signal_id
LEFT JOIN pm_markets p ON p.condition_id = s.condition_id
"""


def bootstrap_ci(pnl, cost, n=1000, seed=0):
    """95 % intervall för ROI = sum(pnl) / sum(cost), genom att dra affärer med återläggning."""
    if not pnl:
        return None, None
    rng = random.Random(seed)
    k = len(pnl)
    rois = []
    for _ in range(n):
        idx = [rng.randrange(k) for _ in range(k)]
        c = sum(cost[i] for i in idx)
        rois.append(sum(pnl[i] for i in idx) / c if c else 0.0)
    rois.sort()
    return rois[int(0.025 * n)], rois[int(0.975 * n) - 1]


def summary(conn, by):
    """by: wallet, category eller all. En rad per (grupp, fördröjning, strategi)."""
    groups = defaultdict(list)
    for r in conn.execute(ROWS):
        key = {"wallet": r[1], "category": r[2], "all": "alla"}[by]
        groups[(key, r[3], r[4])].append(r)
    out = []
    for (group, delay, strategy), rows in sorted(groups.items()):
        trades = [r for r in rows if r[12] is None]
        pnl, cost = [r[5] for r in trades], [r[6] for r in trades]
        lo, hi = bootstrap_ci(pnl, cost)
        out.append({
            "group": group, "delay": delay, "strategy": strategy, "signals": len(rows),
            "trades": len(trades),
            "coverage": sum(r[12] != "no_match" for r in rows) / len(rows),
            "roi": sum(pnl) / sum(cost) if sum(cost) else None, "ci": (lo, hi),
            "slippage": mean(r[7] - r[8] for r in trades) if trades else None,
            "stale": sum(r[9] or 0 for r in trades), "open": sum(r[10] == "open" for r in trades),
            "mismatch": sum(r[11] or 0 for r in trades),
        })  # fmt: skip
    return out


def pm_roi(conn, amount=10):
    """Jämförelse 1: tradern själv på Polymarket, samma signaler, samma summa per signal."""
    res = defaultdict(lambda: [0.0, 0.0])
    rows = conn.execute(
        """SELECT DISTINCT s.id, s.wallet, s.avg_price, s.outcome_index, p.result_index
           FROM signals s JOIN sim_trades t ON t.signal_id = s.id
           JOIN pm_markets p ON p.condition_id = s.condition_id
           WHERE p.result_index IS NOT NULL"""
    )
    for _, wallet, price, idx, result in rows:
        res[wallet][0] += amount / price * (result == idx) - amount
        res[wallet][1] += amount
    return {w: pnl / cost for w, (pnl, cost) in res.items()}


def verdict(lo, hi, n):
    if n < MIN_TRADES:
        return f"Oklart: för få affärer ({n} av minst {MIN_TRADES}) för att dra en slutsats."
    if hi is not None and hi < 0:
        return (
            "Tydligt negativt: hela intervallet ligger under noll. Projektet har gjort sitt jobb."
        )
    if lo is not None and lo > 0:
        return "Tydligt positivt: hela intervallet ligger över noll. Gå vidare till fas 6."
    return "Oklart: intervallet går över noll."


def _pct(x):
    return "-" if x is None else f"{x:+.1%}"


def _table(rows, label, names=None):
    names = names or {}
    lines = [
        f"| {label} | fördröjning | strategi | signaler | affärer | täckning | ROI "
        "| 95 % intervall | slippage | gamla priser | öppna | olika avgörande |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lo, hi = r["ci"]
        slip = "-" if r["slippage"] is None else f"{r['slippage'] * 100:+.1f} ¢"
        lines.append(
            f"| {names.get(r['group'], r['group'])} | {r['delay']} s | {r['strategy']} "
            f"| {r['signals']} | {r['trades']} | {r['coverage']:.0%} | {_pct(r['roi'])} "
            f"| {_pct(lo)} till {_pct(hi)} | {slip} | {r['stale']} | {r['open']} "
            f"| {r['mismatch']} |"
        )
    return "\n".join(lines)


def render(conn, now):
    names = dict(conn.execute("SELECT wallet, COALESCE(name, wallet) FROM traders"))
    total = summary(conn, "all")
    head = next((r for r in total if (r["delay"], r["strategy"]) == HEADLINE), None)
    when = datetime.fromtimestamp(now, UTC).astimezone(ZoneInfo("Europe/Stockholm"))
    parts = [f"# Mimic: resultat\n\nSkapad {when:%Y-%m-%d %H:%M} svensk tid.\n"]
    if head:
        lo, hi = head["ci"]
        parts.append(
            "## Svar\n\nHade du kopierat de valda traders med 2 minuters fördröjning, och hållit "
            f"till avgörande, hade du gått {_pct(head['roi'])} efter avgifter "
            f"({head['trades']} affärer, 95 % intervall {_pct(lo)} till {_pct(hi)}).\n\n"
            f"## Beslut\n\n{verdict(lo, hi, head['trades'])}\n"
        )
    else:
        parts.append("## Beslut\n\nInga affärer att räkna på.\n")
    parts.append("## Alla traders\n\n" + _table(total, "grupp") + "\n")
    pm = pm_roi(conn)
    if pm:
        lines = ["| trader | ROI på Polymarket |", "|---|---|"]
        lines += [f"| {names.get(w, w)} | {_pct(v)} |" for w, v in sorted(pm.items())]
        parts.append("## Jämförelse: tradern själv på Polymarket\n\n" + "\n".join(lines) + "\n")
    parts.append("## Per kategori\n\n" + _table(summary(conn, "category"), "kategori") + "\n")
    parts.append("## Per trader\n\n" + _table(summary(conn, "wallet"), "trader", names) + "\n")
    skips = Counter(r for (r,) in conn.execute("SELECT skip_reason FROM sim_trades") if r)
    if skips:
        lines = ["| skäl | rader |", "|---|---|"] + [f"| {k} | {v} |" for k, v in skips.items()]
        parts.append("## Överhoppade\n\n" + "\n".join(lines) + "\n")
    return "\n".join(parts)
