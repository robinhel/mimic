"""Livetest (fas 6), pappershandel: hämtar nya affärer och sparar orderböckerna direkt.

Polymarket: orderboken för varje token tradern köper eller säljer, för inköp och försäljning.
Kalshi: orderboken när ett köp har en exakt matchning."""

import logging
import sqlite3
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

from copycheck import db, kalshi, polymarket

log = logging.getLogger(__name__)
LATE_AFTER = 120  # sekunder mellan affären och att vi såg den
INTERVAL = 30

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
    try:
        bid, ask, size = polymarket.best_bid_ask(polymarket.book(client, token))
    except requests.HTTPError as e:  # stängd marknad har ingen orderbok
        log.warning("ingen orderbok för %s: %s", token, e)
        return
    conn.execute(
        "INSERT OR IGNORE INTO pm_quotes VALUES (?, ?, ?, ?, ?)",
        (token, now, *(None if x is None else float(x) for x in (bid, ask, size))),
    )


def tick(conn, client, base, wallets, now):
    """En runda. Fel stoppar inte tjänsten, de skrivs i heartbeats."""
    try:
        books, pm_books = set(), set()
        for wallet in wallets:
            start = db.last_trade_ts(conn, wallet) or now - 3600
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
                if cur.rowcount and r["token_id"] not in pm_books:
                    pm_snapshot(conn, client, r["token_id"], now)
                    pm_books.add(r["token_id"])
                if cur.rowcount and match and match[0] not in books:
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
    last_day = None
    while True:
        now = int(time.time())
        tick(conn, client, base, wallets, now)
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
    finally:
        conn.close()
    when = "-" if ts is None else f"{datetime.fromtimestamp(ts, UTC):%Y-%m-%d %H:%M:%S} UTC"
    return (f"copycheck livetest (pappershandel)\nsenaste runda: {when} {status or ''}\n"
            f"affärer sedda: {seen} (sena: {late})\norderböcker Polymarket: {books}\n")  # fmt: skip


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
