"""Kalshi, bara läsning. Priser är text i *_dollars-fält och tolkas med Decimal."""

from datetime import datetime
from decimal import Decimal

# Lucka 39: marknader som stänger inom en timme kopieras inte, så de serierna hoppas över.
SKIP_FREQUENCIES = {"hourly", "fifteen_min"}


def dollars(s):
    return Decimal(s) if s not in (None, "") else None


def yes_ask_from_no_bid(best_no_bid):
    """yes_ask = 1 - bästa no_bid. Den enda platsen där detta räknas ut."""
    return None if best_no_bid is None else Decimal(1) - best_no_bid


def orderbook_yes_ask(book):
    bids = (book.get("orderbook_fp") or {}).get("no_dollars") or []
    best = max((Decimal(p) for p, _ in bids), default=None)
    return yes_ask_from_no_bid(best)


def series_of(event_ticker):
    # shortcut: serien är prefixet före första "-" (stämde för alla vi kollat), annars /events.
    return event_ticker.split("-", 1)[0]


def is_mve(market):
    return market.get("ticker", "").startswith("KXMVE")


def iso_ts(s):
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()) if s else None


def skipped_series(series):
    return {s["ticker"] for s in series if s.get("frequency") in SKIP_FREQUENCIES}


def series(client, base):
    return client.get_json(f"{base}/series").get("series") or []


def markets(client, base, historical, min_close_ts):
    """Ger en sida (lista) i taget, utan KXMVE. Live och historik har olika endpoints."""
    path = "/historical/markets" if historical else "/markets"
    params = {"limit": 1000, "mve_filter": "exclude", "min_close_ts": min_close_ts}
    while True:
        body = client.get_json(base + path, params)
        yield [m for m in body.get("markets") or [] if not is_mve(m)]
        if not body.get("cursor"):
            return
        params["cursor"] = body["cursor"]
