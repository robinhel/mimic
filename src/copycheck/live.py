"""Livetest (fas 6), pappershandel: hämtar nya affärer och sparar Kalshis orderbok direkt."""

import logging
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

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


def tick(conn, client, base, wallets, now):
    """En runda. Fel stoppar inte tjänsten, de skrivs i heartbeats."""
    try:
        books = set()
        for wallet in wallets:
            start = db.last_trade_ts(conn, wallet) or now - 3600
            rows, _ = polymarket.activity(client, wallet, start, max_pages=5)
            db.insert_activity(conn, rows, seen_ts=now)
            for r in rows:
                if r["side"] != "BUY":
                    continue
                match = conn.execute(EXACT_MATCH, (r["condition_id"],)).fetchone()
                if not match:
                    continue
                cur = conn.execute(
                    "INSERT OR IGNORE INTO live_seen VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        wallet,
                        r["transaction_hash"],
                        r["token_id"],
                        r["timestamp"],
                        now,
                        int(now - r["timestamp"] > LATE_AFTER),
                        match[0],
                    ),  # fmt: skip
                )
                if cur.rowcount and match[0] not in books:
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
