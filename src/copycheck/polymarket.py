"""Polymarket Data API. Bara v2: cursor-paginering, svar i `data`, snake_case."""

from decimal import ROUND_DOWN, Decimal

from copycheck import config

BASE = config.POLYMARKET_DATA_URL + "/v2"
FOUR = Decimal("0.0001")


def price(x) -> Decimal:
    """Priser kommer som flyttal med brus (0.4900001785). Avrunda till 4 decimaler."""
    return Decimal(str(x)).quantize(FOUR)


def fetch_all(client, path, params, max_pages=None):
    """Följer pagination.next_cursor. Returnerar (rader, avkortad)."""
    params = dict(params)
    rows, pages = [], 0
    while True:
        body = client.get_json(BASE + path, params)
        rows.extend(body.get("data") or [])
        pages += 1
        cursor = (body.get("pagination") or {}).get("next_cursor")
        if not cursor:
            return rows, False
        if max_pages is not None and pages >= max_pages:
            return rows, True
        params["cursor"] = cursor


def leaderboard(client, period, order_by, limit):
    """period: day/week/month/all. order_by: PNL/VOLUME. Testat 2026-11-10."""
    params = {"time_period": period, "order_by": order_by, "limit": limit}
    return client.get_json(BASE + "/leaderboard", params).get("data") or []


def activity(client, wallet, start, max_pages=None):
    """Alla affärer (även limit-order) sedan `start` (unix-sekunder), nyast först."""
    params = {"user": wallet, "type": "TRADE", "start": start, "limit": 1000}
    return fetch_all(client, "/activity", params, max_pages)


def closed_positions(client, wallet, max_pages=None):
    params = {"user": wallet, "status": "CLOSED", "limit": 500}
    return fetch_all(client, "/positions", params, max_pages)


def gamma_markets(client, condition_ids, batch=50):
    """Frågetext, regler och resultat från Gamma. Stängda kommer bara med closed=true."""
    out = []
    for i in range(0, len(condition_ids), batch):
        ids = list(condition_ids[i : i + batch])
        for closed in ("false", "true"):
            params = {"condition_ids": ids, "closed": closed, "limit": len(ids)}
            out.extend(client.get_json(config.POLYMARKET_GAMMA_URL + "/markets", params) or [])
    return out


def prices_history(client, token, start, end):
    """Mittpris ungefär en gång per minut: [{"t": unix, "p": pris}]. Provat 2026-11-12."""
    params = {"market": token, "startTs": start, "endTs": end, "fidelity": 1}
    body = client.get_json(config.POLYMARKET_CLOB_URL + "/prices-history", params)
    return body.get("history") or []


def book(client, token):
    """Orderboken för en token. 404 när marknaden saknar orderbok (stängd)."""
    return client.get_json(config.POLYMARKET_CLOB_URL + "/book", {"token_id": token})


SHARE = Decimal("0.01")


def fill_buy(book, usd):
    """Marknadsköp för `usd` dollar: billigaste utbudet först, nivå för nivå.
    [(pris, andelar)], andelar avrundade nedåt till hundradelar."""
    out = []
    asks = sorted((Decimal(a["price"]), Decimal(a["size"])) for a in book.get("asks") or [])
    for p, size in asks:
        n = min(size, usd / p).quantize(SHARE, ROUND_DOWN)
        if n <= 0:
            break
        out.append((p, n))
        usd -= p * n
    return out


def fill_sell(book, shares):
    """Marknadsförsäljning av `shares` andelar: högsta budet först. [(pris, andelar)]."""
    out = []
    bids = sorted(((Decimal(b["price"]), Decimal(b["size"])) for b in book.get("bids") or []),
                  reverse=True)  # fmt: skip
    for p, size in bids:
        if shares <= 0:
            break
        n = min(size, shares)
        out.append((p, n))
        shares -= n
    return out


def best_bid_ask(book):
    """(bästa bud, bästa utbud, antal till bästa utbud). Listorna är inte sorterade
    som man tror (bud stigande, utbud fallande), så ta max och min."""
    bids = [Decimal(b["price"]) for b in book.get("bids") or []]
    asks = {Decimal(a["price"]): Decimal(a["size"]) for a in book.get("asks") or []}
    ask = min(asks, default=None)
    return max(bids, default=None), ask, asks.get(ask)
