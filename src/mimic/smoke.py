"""Röktest: anropar varje endpoint en gång, sparar svaret i tests/fixtures/
och jämför fälten med de som verifierades 2026-11-10.

Kör: uv run python -m mimic.smoke
"""

import json
import sys
import time
from pathlib import Path

from mimic import config
from mimic.http import HttpClient

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"

# Fält vi väntar oss (PLAN/CLAUDE.md, test 2026-11-10). Inte facit: avvikelser rapporteras.
EXPECTED = {
    "pm_status": {"computed_at", "age_seconds", "serving"},
    "pm_leaderboard": {"rank", "user_id", "user_name", "pnl", "volume"},
    "pm_activity": {
        "timestamp", "type", "side", "price", "size", "usdc_size", "condition_id",
        "token_id", "title", "outcome", "outcome_index", "slug", "event_slug",
        "proxy_wallet", "transaction_hash",
    },
    "kalshi_markets": {
        "ticker", "event_ticker", "title", "rules_primary", "yes_bid_dollars",
        "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars", "close_time", "status",
        "result", "market_type", "mve_collection_ticker",
    },
    "kalshi_historical_cutoff": {
        "market_settled_ts", "trades_created_ts", "orders_updated_ts",
        "market_positions_last_updated_ts",
    },
    "kalshi_candlesticks": {
        "end_period_ts", "volume_fp", "open_interest_fp", "price", "yes_bid", "yes_ask",
    },
}  # fmt: skip


def first(items):
    return items[0] if items else {}


def check(name, sample, problems):
    if not sample:
        problems.append(f"{name}: tomt svar, kan inte kolla fälten")
        return
    missing = EXPECTED[name] - sample.keys()
    if missing:
        problems.append(f"{name}: saknar {sorted(missing)}. Finns: {sorted(sample.keys())}")


def save(name, data):
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    size = len(data.get("data") or data.get("markets") or data.get("candlesticks") or [])
    print(f"  sparad {name}.json ({size} rader)" if size else f"  sparad {name}.json")


def polymarket(c, problems):
    base = config.POLYMARKET_DATA_URL + "/v2"
    status = c.get_json(f"{base}/status")
    save("pm_status", status)
    check("pm_status", status.get("data", {}), problems)
    print(f"  lag_seconds = {status.get('data', {}).get('serving', {}).get('lag_seconds')}")

    lb = c.get_json(f"{base}/leaderboard", {"limit": 5})
    save("pm_leaderboard", lb)
    check("pm_leaderboard", first(lb.get("data")), problems)
    if "next_cursor" not in lb.get("pagination", {}):
        problems.append(f"pm_leaderboard: pagination saknar next_cursor: {lb.get('pagination')}")

    user = first(lb.get("data")).get("user_id")
    if not user:
        problems.append("pm_leaderboard: ingen user_id, hoppar över activity och positions")
        return
    act = c.get_json(f"{base}/activity", {"user": user, "type": "TRADE", "limit": 5})
    save("pm_activity", act)
    check("pm_activity", first(act.get("data")), problems)

    pos = c.get_json(f"{base}/positions", {"user": user, "status": "CLOSED", "limit": 5})
    save("pm_positions_closed", pos)
    print(f"  positions-fält: {sorted(first(pos.get('data')).keys())}")


def kalshi(c, problems):
    base = config.KALSHI_BASE_URL
    markets = c.get_json(f"{base}/markets", {"limit": 20, "status": "open"})
    save("kalshi_markets", markets)
    rows = markets.get("markets", [])
    mve = [m for m in rows if m.get("ticker", "").startswith("KXMVE")]
    print(f"  {len(mve)} av {len(rows)} marknader är KXMVE")
    if mve and "mve_collection_ticker" not in mve[0]:
        problems.append("kalshi_markets: KXMVE-marknad saknar mve_collection_ticker")
    normal = [m for m in rows if not m.get("ticker", "").startswith("KXMVE")]
    if not normal:
        # Lucka 37: prova filterparametern och spara svaret separat.
        markets = c.get_json(
            f"{base}/markets", {"limit": 20, "status": "open", "mve_filter": "exclude"}
        )
        save("kalshi_markets_no_mve", markets)
        normal = [m for m in markets.get("markets", []) if not m["ticker"].startswith("KXMVE")]
        print(f"  mve_filter=exclude gav {len(normal)} vanliga marknader")
    # mve_collection_ticker finns bara på KXMVE-marknader.
    sample = first(normal)
    if sample:
        sample = {**sample, "mve_collection_ticker": None}
    check("kalshi_markets", sample, problems)

    cutoff = c.get_json(f"{base}/historical/cutoff")
    save("kalshi_historical_cutoff", cutoff)
    check("kalshi_historical_cutoff", cutoff, problems)

    if not normal:
        problems.append("kalshi_markets: ingen vanlig marknad, hoppar över candlesticks")
        return
    m = traded_market(c, base) or normal[0]
    event = c.get_json(f"{base}/events/{m['event_ticker']}")
    series = event.get("event", {}).get("series_ticker")
    end = int(time.time())
    candles = c.get_json(
        f"{base}/series/{series}/markets/{m['ticker']}/candlesticks",
        {"start_ts": end - 7 * 86400, "end_ts": end, "period_interval": 60},
    )
    save("kalshi_candlesticks", candles)
    print(f"  candlesticks för {m['ticker']} (serie {series}), 7 dagar, 1 h")
    check("kalshi_candlesticks", first(candles.get("candlesticks")), problems)


def traded_market(c, base, pages=5):
    """Lucka 36: candles finns bara där det handlats. Bläddra tills en marknad har volym."""
    params = {"limit": 1000, "status": "open", "mve_filter": "exclude"}
    for _ in range(pages):
        page = c.get_json(f"{base}/markets", params)
        rows = page.get("markets", [])
        if rows:
            best = max(rows, key=lambda m: float(m.get("volume_fp") or 0))
            if float(best.get("volume_fp") or 0) > 0:
                return best
        if not page.get("cursor"):
            return None
        params["cursor"] = page["cursor"]
    return None


def main():
    c = HttpClient()
    problems = []
    for name, fn in [("Polymarket", polymarket), ("Kalshi", kalshi)]:
        print(name)
        try:
            fn(c, problems)
        except Exception as e:
            problems.append(f"{name}: {type(e).__name__}: {e}")
    print("\nAvvikelser:" if problems else "\nInga avvikelser.")
    for p in problems:
        print(f"  - {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
