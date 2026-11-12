"""Livetest (fas 6), pappershandel: hämtar nya affärer och sparar orderböckerna direkt.

Polymarket: orderboken för varje token tradern köper eller säljer, för inköp och försäljning.
Kalshi: orderboken när ett köp har en exakt matchning."""

import logging
import sqlite3
import threading
import time
from datetime import UTC, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

from copycheck import db, fees, kalshi, polymarket, signals
from copycheck.config import MIN_SIGNAL_USD, SIGNAL_WINDOW

log = logging.getLogger(__name__)
LATE_AFTER = 120  # sekunder mellan affären och att vi såg den
INTERVAL = 2  # minsta tid per runda; 20 traders tar ändå ca 2-4 s (0,1 s mellan anrop)
SETTLE_EVERY = 600  # sekunder mellan kontroller av avgjorda marknader
# Låtsaskontot (Robin 2026-11-12: simuleringen ska göra som en riktig bot).
START_CASH = Decimal(1000)
BUY_USD = Decimal(10)  # per signal
MAX_GAP = Decimal("0.05")  # köp inte om vårt snittpris är mer än 5 cent över traderns
MIN_PRICE = 0.10  # köp under 10 cent gav -46 % i analysen 2026-11-12

EXACT_MATCH = """
SELECT kalshi_ticker FROM matches
WHERE pm_condition = ? AND level = 'exact' AND COALESCE(review_ok, 1) = 1
ORDER BY kalshi_ticker LIMIT 1
"""


def heartbeat(conn, now, status):
    conn.execute("INSERT INTO heartbeats (ts, component, status) VALUES (?, 'live', ?)",
                 (now, status))  # fmt: skip
    conn.commit()


def snapshot(conn, client, base, ticker, now):
    book = kalshi.orderbook(client, base, ticker)
    bid, ask = kalshi.orderbook_yes_bid(book), kalshi.orderbook_yes_ask(book)
    conn.execute(
        "INSERT OR IGNORE INTO kalshi_quotes VALUES (?, ?, ?, ?, 'orderbook')",
        (ticker, now, None if bid is None else float(bid), None if ask is None else float(ask)),
    )


def pm_snapshot(conn, client, token, now):
    """Sparar bästa bud och utbud och returnerar hela orderboken (None om den saknas)."""
    try:
        book = polymarket.book(client, token)
    except requests.HTTPError as e:  # stängd marknad har ingen orderbok
        log.warning("ingen orderbok för %s: %s", token, e)
        return None
    bid, ask, size = polymarket.best_bid_ask(book)
    conn.execute(
        "INSERT OR IGNORE INTO pm_quotes VALUES (?, ?, ?, ?, ?)",
        (token, now, *(None if x is None else float(x) for x in (bid, ask, size))),
    )
    return book


# --- Pappershandel. Gör som en riktig bot: köper mot orderboken i samma ögonblick som vi
# ser att traderns köp passerat signalgränsen, säljer mot buden när tradern säljer. ---

TRADER_FILLS = """
SELECT wallet, condition_id, token_id, outcome_index, price, size, usdc_size, trade_ts
FROM pm_activity WHERE wallet = ? AND token_id = ? AND side = 'BUY' ORDER BY trade_ts
"""


def cash(conn):
    """Låtsaskontots saldo: startbelopp minus köp plus försäljningar och utbetalningar."""
    total = START_CASH
    for cost, proceeds in conn.execute(
        "SELECT cost, proceeds FROM paper_trades WHERE status != 'skipped'"
    ):
        total += Decimal(str(proceeds)) - Decimal(str(cost))
    return total.quantize(fees.PM_PRECISION)


def fee_rate(conn, client, condition):
    """Avgiftsränta från Gamma, sparad i pm_markets. Okänd ränta: den högsta."""
    row = conn.execute(
        "SELECT fee_rate FROM pm_markets WHERE condition_id = ?", (condition,)
    ).fetchone()
    if row is None:
        db.upsert_pm_markets(conn, polymarket.gamma_markets(client, [condition]))
        row = conn.execute(
            "SELECT fee_rate FROM pm_markets WHERE condition_id = ?", (condition,)
        ).fetchone()
    return fees.PM_UNKNOWN_RATE if row is None or row[0] is None else row[0]


def paper_buy(conn, client, wallet, token, book, now):
    """Köp om traderns köp i token just passerat signalgränsen och vi inte redan köpt."""
    groups = list(signals.group_fills(conn.execute(TRADER_FILLS, (wallet, token)), SIGNAL_WINDOW))
    sig = groups and signals.to_signal(groups[-1], MIN_SIGNAL_USD)
    if not sig:
        return
    first_ts, trigger_ts, price = sig[6], sig[7], sig[4]
    if conn.execute(
        "SELECT 1 FROM paper_trades WHERE wallet = ? AND token_id = ? AND signal_ts = ?",
        (wallet, token, first_ts),
    ).fetchone():
        return
    row = {"wallet": wallet, "token_id": token, "signal_ts": first_ts, "trigger_ts": trigger_ts,
           "trader_price": price, "seen_ts": now, "status": "skipped"}  # fmt: skip
    if book:
        row["condition_id"] = book.get("market")
        row["book_ts"] = int(book["timestamp"]) // 1000 if book.get("timestamp") else None
    levels = polymarket.fill_buy(book or {}, BUY_USD)
    shares = sum((n for _, n in levels), Decimal(0))
    if now - trigger_ts > LATE_AFTER:
        row["skip_reason"] = "late"  # orben har pausat; en riktig bot hade köpt tidigare
    elif price < MIN_PRICE:
        row["skip_reason"] = "longshot"
    elif cash(conn) < BUY_USD:
        row["skip_reason"] = "no_cash"
    elif shares == 0:
        row["skip_reason"] = "no_book"
    elif sum(p * n for p, n in levels) / shares > Decimal(str(price)) + MAX_GAP:
        row["skip_reason"] = "price_ran"
    else:
        rate = fee_rate(conn, client, row["condition_id"])
        fee = sum(fees.pm_fee(n, p, rate) for p, n in levels)
        spent = sum(p * n for p, n in levels)
        row.update(status="open", shares=float(shares), shares_left=float(shares),
                   entry_price=float(spent / shares), fee_in=float(fee),
                   cost=float(spent + fee))  # fmt: skip
    cols = ", ".join(row)
    conn.execute(
        f"INSERT INTO paper_trades ({cols}) VALUES ({', '.join('?' * len(row))})",
        list(row.values()),
    )


def paper_sell(conn, client, wallet, token, book, trade_ts, now):
    """Tradern sålde: sälj allt vi har i token mot buden. Rester säljs vid nästa försäljning
    eller betalas ut när marknaden avgörs."""
    rows = conn.execute(
        """SELECT signal_ts, shares_left, proceeds, condition_id FROM paper_trades
           WHERE wallet = ? AND token_id = ? AND status = 'open'""",
        (wallet, token),
    ).fetchall()
    for signal_ts, left, proceeds, condition in rows:
        levels = polymarket.fill_sell(book or {}, Decimal(str(left)))
        if not levels:
            continue
        rate = fee_rate(conn, client, condition)
        got = sum(p * n - fees.pm_fee(n, p, rate) for p, n in levels)
        sold = sum(n for _, n in levels)
        left = Decimal(str(left)) - sold
        conn.execute(
            """UPDATE paper_trades SET shares_left = ?, proceeds = ?, exit_ts = ?,
                   trader_exit_ts = COALESCE(trader_exit_ts, ?), status = ?
               WHERE wallet = ? AND token_id = ? AND signal_ts = ?""",
            (float(left), float(Decimal(str(proceeds)) + got), now, trade_ts,
             "open" if left > 0 else "sold", wallet, token, signal_ts),
        )  # fmt: skip


def settle(conn, client, now):
    """Avgjorda marknader betalar 1 dollar per andel i det vinnande utfallet, annars 0."""
    open_ = [c for (c,) in conn.execute(
        "SELECT DISTINCT condition_id FROM paper_trades WHERE status = 'open'")]  # fmt: skip
    if not open_:
        return
    db.upsert_pm_markets(conn, polymarket.gamma_markets(client, open_))
    rows = conn.execute(
        """SELECT t.wallet, t.token_id, t.signal_ts, t.shares_left, t.proceeds,
                  p.result_index, p.outcome0_token, p.outcome1_token
           FROM paper_trades t JOIN pm_markets p USING (condition_id)
           WHERE t.status = 'open' AND p.result_index IS NOT NULL"""
    ).fetchall()
    for wallet, token, signal_ts, left, proceeds, result, tok0, tok1 in rows:
        won = token == (tok0 if result == 0 else tok1)
        conn.execute(
            """UPDATE paper_trades SET status = 'settled', shares_left = 0, proceeds = ?,
                   exit_ts = ? WHERE wallet = ? AND token_id = ? AND signal_ts = ?""",
            (proceeds + left * won, now, wallet, token, signal_ts),
        )
    conn.commit()


def tick(conn, client, base, wallets, now):
    """En runda. Fel stoppar inte tjänsten, de skrivs i heartbeats."""
    try:
        books, pm_books = set(), {}
        # Orben pausar i timmar. Börja vid senaste rundan, så hämtas affärer under pausen
        # också. De markeras late, eftersom vi inte såg dem i tid.
        last_round = conn.execute(
            "SELECT MAX(ts) FROM heartbeats WHERE component = 'live'"
        ).fetchone()[0]
        for wallet in wallets:
            start = db.last_trade_ts(conn, wallet) or last_round or now - 3600
            rows, _ = polymarket.activity(client, wallet, start, max_pages=5)
            db.insert_activity(conn, rows, seen_ts=now)
            for r in rows:
                match = None
                if r["side"] == "BUY":
                    match = conn.execute(EXACT_MATCH, (r["condition_id"],)).fetchone()
                cur = conn.execute(
                    "INSERT OR IGNORE INTO live_seen VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        wallet,
                        r["transaction_hash"],
                        r["token_id"],
                        r["timestamp"],
                        now,
                        int(now - r["timestamp"] > LATE_AFTER),
                        match and match[0],
                    ),  # fmt: skip
                )
                if not cur.rowcount:
                    continue
                token = r["token_id"]
                if token not in pm_books:
                    pm_books[token] = pm_snapshot(conn, client, token, now)
                if r["side"] == "BUY":
                    paper_buy(conn, client, wallet, token, pm_books[token], now)
                else:
                    paper_sell(conn, client, wallet, token, pm_books[token], r["timestamp"], now)
                if match and match[0] not in books:
                    snapshot(conn, client, base, match[0], now)
                    books.add(match[0])
        conn.commit()
        heartbeat(conn, now, "ok")
    except Exception as e:  # noqa: BLE001 - tjänsten ska leva vidare
        conn.rollback()
        log.exception("tick misslyckades")
        heartbeat(conn, now, f"error: {type(e).__name__}: {e}"[:300])


def backup(conn, path):
    """Lucka 34: en backup-fil per dag, den gamla skrivs över."""
    target = sqlite3.connect(path)
    with target:
        conn.backup(target)
    target.close()


def loop(conn, client, base, wallets, backup_path, interval=INTERVAL):
    last_day, last_settle = None, 0
    while True:
        now = int(time.time())
        tick(conn, client, base, wallets, now)
        if now - last_settle >= SETTLE_EVERY:
            try:
                settle(conn, client, now)
            except Exception:  # noqa: BLE001 - tjänsten ska leva vidare
                conn.rollback()
                log.exception("settle misslyckades")
            last_settle = now
        day = datetime.fromtimestamp(now, UTC).date()
        if day != last_day:
            Path(backup_path).parent.mkdir(parents=True, exist_ok=True)
            backup(conn, backup_path)
            last_day = day
        time.sleep(max(0, interval - (time.time() - now)))


STATUS = """SELECT (SELECT ts FROM heartbeats ORDER BY ts DESC LIMIT 1),
                  (SELECT status FROM heartbeats ORDER BY ts DESC LIMIT 1),
                  (SELECT COUNT(*) FROM live_seen), (SELECT COUNT(*) FROM live_seen WHERE late),
                  (SELECT COUNT(*) FROM pm_quotes)"""


def status_text(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        ts, status, seen, late, books = conn.execute(STATUS).fetchone()
        money = cash(conn)
        counts = dict(conn.execute("SELECT status, COUNT(*) FROM paper_trades GROUP BY 1"))
    finally:
        conn.close()
    when = "-" if ts is None else f"{datetime.fromtimestamp(ts, UTC):%Y-%m-%d %H:%M:%S} UTC"
    return (f"copycheck livetest (pappershandel)\nsenaste runda: {when} {status or ''}\n"
            f"affärer sedda: {seen} (sena: {late})\norderböcker Polymarket: {books}\n"
            f"låtsaskonto: {money} dollar (start {START_CASH})\n"
            f"köp: öppna {counts.get('open', 0)}, sålda {counts.get('sold', 0)}, "
            f"avgjorda {counts.get('settled', 0)}, "
            f"överhoppade {counts.get('skipped', 0)}\n")  # fmt: skip


def serve_status(path, port):
    """Statussida på `port` i en egen tråd. En Box-tjänst måste svara på $PORT."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = status_text(path).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
