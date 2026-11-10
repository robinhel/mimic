"""SQLite-schema och frågor. Alla tider i UTC unix-sekunder."""

import sqlite3

from copycheck.polymarket import price

SCHEMA = """
CREATE TABLE IF NOT EXISTS traders (
    wallet TEXT PRIMARY KEY,
    name TEXT,
    sources TEXT NOT NULL,          -- t.ex. "all:VOLUME,month:PNL"
    lb_pnl REAL,
    lb_volume REAL,
    activity_truncated INTEGER NOT NULL DEFAULT 0,
    positions_truncated INTEGER NOT NULL DEFAULT 0,
    is_bot INTEGER NOT NULL DEFAULT 0,
    bot_reason TEXT,
    collected_ts INTEGER
);
CREATE TABLE IF NOT EXISTS pm_activity (
    id INTEGER PRIMARY KEY,
    wallet TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    outcome TEXT,
    outcome_index INTEGER,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    usdc_size REAL,
    trade_ts INTEGER NOT NULL,      -- när affären hände
    seen_ts INTEGER NOT NULL,       -- när vi hämtade den
    tx_hash TEXT NOT NULL,
    title TEXT,
    slug TEXT,
    event_slug TEXT,
    -- shortcut: två helt lika fyllningar i samma transaktion blir en rad, ovanligt.
    UNIQUE (wallet, tx_hash, token_id, side, price, size)
);
CREATE INDEX IF NOT EXISTS pm_activity_wallet_ts ON pm_activity (wallet, trade_ts);
CREATE TABLE IF NOT EXISTS pm_positions (
    wallet TEXT NOT NULL,
    token_id TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    outcome TEXT,
    avg_price REAL,
    total_size REAL,
    realized_pnl REAL,
    first_entry_ts INTEGER,
    last_event_ts INTEGER,
    end_date TEXT,
    title TEXT,
    slug TEXT,
    PRIMARY KEY (wallet, token_id)
);
"""


def connect(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def upsert_trader(conn, wallet, name, source, lb_pnl, lb_volume):
    row = conn.execute("SELECT sources FROM traders WHERE wallet = ?", (wallet,)).fetchone()
    sources = set(row[0].split(",")) if row else set()
    sources.add(source)
    conn.execute(
        """INSERT INTO traders (wallet, name, sources, lb_pnl, lb_volume)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (wallet) DO UPDATE SET
             name = excluded.name, sources = excluded.sources,
             lb_pnl = COALESCE(excluded.lb_pnl, lb_pnl),
             lb_volume = COALESCE(excluded.lb_volume, lb_volume)""",
        (wallet, name, ",".join(sorted(sources)), lb_pnl, lb_volume),
    )
    conn.commit()


def insert_activity(conn, rows, seen_ts):
    conn.executemany(
        """INSERT OR IGNORE INTO pm_activity
           (wallet, condition_id, token_id, outcome, outcome_index, side, price, size,
            usdc_size, trade_ts, seen_ts, tx_hash, title, slug, event_slug)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                r["proxy_wallet"],
                r["condition_id"],
                r["token_id"],
                r.get("outcome"),
                r.get("outcome_index"),
                r["side"],
                float(price(r["price"])),
                r["size"],
                r.get("usdc_size"),
                r["timestamp"],
                seen_ts,
                r["transaction_hash"],
                r.get("title"),
                r.get("slug"),
                r.get("event_slug"),
            )  # fmt: skip
            for r in rows
        ],
    )
    conn.commit()


def upsert_positions(conn, rows):
    conn.executemany(
        """INSERT OR REPLACE INTO pm_positions
           (wallet, token_id, condition_id, outcome, avg_price, total_size, realized_pnl,
            first_entry_ts, last_event_ts, end_date, title, slug)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                r["proxy_wallet"],
                r["token_id"],
                r["condition_id"],
                r.get("outcome"),
                float(price(r["avg_price"])),
                r["total_size"],
                r["realized_pnl"],
                r.get("first_entry_at"),
                r.get("last_event_at"),
                r.get("end_date"),
                r.get("title"),
                r.get("slug"),
            )  # fmt: skip
            for r in rows
        ],
    )
    conn.commit()


def last_trade_ts(conn, wallet):
    return conn.execute(
        "SELECT MAX(trade_ts) FROM pm_activity WHERE wallet = ?", (wallet,)
    ).fetchone()[0]


def activity_truncated(conn, wallet):
    row = conn.execute(
        "SELECT activity_truncated FROM traders WHERE wallet = ?", (wallet,)
    ).fetchone()
    return bool(row and row[0])
