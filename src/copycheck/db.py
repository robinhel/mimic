"""SQLite-schema och frågor. Alla tider i UTC unix-sekunder."""

import json
import re
import sqlite3

from copycheck import fees, kalshi
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
CREATE TABLE IF NOT EXISTS kalshi_markets (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL UNIQUE,
    event_ticker TEXT NOT NULL,
    series_ticker TEXT NOT NULL,
    category TEXT,
    title TEXT,
    yes_sub_title TEXT,
    rules_primary TEXT,
    rules_secondary TEXT,
    market_type TEXT,
    open_ts INTEGER,
    close_ts INTEGER,
    status TEXT,
    result TEXT,
    source TEXT NOT NULL            -- live eller historical
);
CREATE INDEX IF NOT EXISTS kalshi_markets_close ON kalshi_markets (close_ts);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY,
    wallet TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    outcome_index INTEGER,
    avg_price REAL NOT NULL,        -- snittpris viktat med antal kontrakt
    usdc REAL NOT NULL,
    first_ts INTEGER NOT NULL,
    trigger_ts INTEGER NOT NULL,    -- när summan passerade minsta signal: då kopierar vi
    last_ts INTEGER NOT NULL,
    n_fills INTEGER NOT NULL,
    UNIQUE (wallet, token_id, first_ts)
);
CREATE TABLE IF NOT EXISTS pm_markets (
    condition_id TEXT PRIMARY KEY,
    question TEXT,
    description TEXT,
    end_ts INTEGER,
    closed INTEGER,
    result_index INTEGER,           -- vinnande utfall, NULL om inte avgjord
    outcomes TEXT,                  -- JSON-lista, t.ex. ["Yes", "No"]
    outcome0_token TEXT,
    outcome1_token TEXT,
    category TEXT,
    slug TEXT,
    fee_rate REAL,                  -- Polymarkets taker-ränta, 0 utan avgift, NULL = ej hämtad
    closed_ts INTEGER               -- när marknaden stängde (Gamma closedTime)
);
CREATE TABLE IF NOT EXISTS sim_trades (
    signal_id INTEGER NOT NULL,
    venue TEXT NOT NULL,            -- polymarket eller kalshi
    strategy TEXT NOT NULL,
    delay INTEGER NOT NULL,
    kalshi_ticker TEXT,
    side TEXT,
    entry_ts INTEGER,
    entry_price REAL,
    quote_age INTEGER,              -- sekunder sedan senaste candle (lucka 36)
    stale INTEGER,
    contracts INTEGER,
    fee_in REAL,
    exit_kind TEXT,                 -- settled, sold eller open
    exit_price REAL,
    fee_out REAL,
    pnl REAL,
    cost REAL,
    mismatch INTEGER,               -- PM och Kalshi avgjordes olika (lucka 28)
    skip_reason TEXT,               -- no_match, no_market, closed, no_price, price_ran, ...
    PRIMARY KEY (signal_id, venue, strategy, delay)
);
CREATE TABLE IF NOT EXISTS kalshi_quotes (
    ticker TEXT NOT NULL,
    ts INTEGER NOT NULL,
    yes_bid REAL,
    yes_ask REAL,
    source TEXT NOT NULL,           -- candle eller orderbook
    PRIMARY KEY (ticker, ts, source)
);
CREATE TABLE IF NOT EXISTS live_seen (
    wallet TEXT NOT NULL,
    tx_hash TEXT NOT NULL,
    token_id TEXT NOT NULL,
    trade_ts INTEGER NOT NULL,
    seen_ts INTEGER NOT NULL,
    late INTEGER NOT NULL,          -- upptäckt för sent (lucka 32), räknas separat
    kalshi_ticker TEXT,             -- NULL utan Kalshi-matchning
    PRIMARY KEY (wallet, tx_hash, token_id)
);
CREATE TABLE IF NOT EXISTS pm_quotes (  -- Polymarkets orderbok när livetestet såg en affär
    token_id TEXT NOT NULL,
    ts INTEGER NOT NULL,
    bid REAL,
    ask REAL,
    ask_size REAL,                  -- andelar till bästa pris
    PRIMARY KEY (token_id, ts)
);
CREATE TABLE IF NOT EXISTS heartbeats (
    ts INTEGER NOT NULL,
    component TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_usage (  -- varje AI-anrop, för kostnadsgränsen
    ts INTEGER NOT NULL,
    model TEXT NOT NULL,            -- "leverantör:modell"
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    usd REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS match_runs (
    pm_condition TEXT PRIMARY KEY,
    n_candidates INTEGER NOT NULL,
    judged_ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS matches (
    pm_condition TEXT NOT NULL,
    kalshi_ticker TEXT NOT NULL,
    level TEXT NOT NULL,            -- exact, near, related, none
    outcome0_side TEXT,             -- vilken Kalshi-sida som är PM:s utfall 0 (yes/no)
    reason TEXT,
    model TEXT,
    judged_ts INTEGER NOT NULL,
    review_ok INTEGER,              -- granskad för hand: 1 rätt, 0 fel, NULL ej granskad
    PRIMARY KEY (pm_condition, kalshi_ticker)
);
-- Externt innehåll: indexet byggs om med rebuild_kalshi_search efter hämtningen.
CREATE VIRTUAL TABLE IF NOT EXISTS kalshi_search USING fts5 (
    title, yes_sub_title, rules_primary, content = 'kalshi_markets', content_rowid = 'id'
);
"""


def _migrate(conn):
    """Ger en databas från en tidigare version de nya kolumnerna."""

    def cols(table):
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}

    if cols("sim_trades") and "venue" not in cols("sim_trades"):
        conn.execute("DROP TABLE sim_trades")  # bara härledda rader, backtest bygger om dem
    old = [r for r in conn.execute("PRAGMA table_info(live_seen)") if r[1] == "kalshi_ticker"]
    if old and old[0][3]:  # kalshi_ticker var NOT NULL; livetestet sparar nu alla affärer
        conn.execute("ALTER TABLE live_seen RENAME TO live_seen_v1")
    have = cols("pm_markets")
    for name, kind in (("fee_rate", "REAL"), ("closed_ts", "INTEGER")):
        if have and name not in have:
            conn.execute(f"ALTER TABLE pm_markets ADD COLUMN {name} {kind}")


def connect(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    _migrate(conn)
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


def upsert_kalshi_markets(conn, rows, source, categories):
    conn.executemany(
        """INSERT INTO kalshi_markets
           (ticker, event_ticker, series_ticker, category, title, yes_sub_title, rules_primary,
            rules_secondary, market_type, open_ts, close_ts, status, result, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (ticker) DO UPDATE SET
             category = excluded.category, title = excluded.title,
             yes_sub_title = excluded.yes_sub_title, rules_primary = excluded.rules_primary,
             rules_secondary = excluded.rules_secondary, close_ts = excluded.close_ts,
             status = excluded.status, result = excluded.result, source = excluded.source""",
        [
            (
                m["ticker"],
                m["event_ticker"],
                kalshi.series_of(m["event_ticker"]),
                categories.get(kalshi.series_of(m["event_ticker"])),
                m.get("title"),
                m.get("yes_sub_title"),
                m.get("rules_primary"),
                m.get("rules_secondary"),
                m.get("market_type"),
                kalshi.iso_ts(m.get("open_time")),
                kalshi.iso_ts(m.get("close_time")),
                m.get("status"),
                m.get("result"),
                source,
            )  # fmt: skip
            for m in rows
        ],
    )
    conn.commit()


def rebuild_kalshi_search(conn):
    conn.execute("INSERT INTO kalshi_search (kalshi_search) VALUES ('rebuild')")
    conn.commit()


def fts_query(text):
    """Gör fri text till en FTS5-fråga: orden med OR, inga specialtecken."""
    words = [w for w in re.findall(r"\w+", text) if len(w) > 1]
    return " OR ".join(f'"{w}"' for w in words)


def search_kalshi(conn, text, limit=20, min_close=None, max_close=None):
    q = fts_query(text)
    if not q:
        return []
    cur = conn.execute(
        """SELECT m.ticker, m.event_ticker, m.title, m.yes_sub_title, m.rules_primary,
                  m.rules_secondary, m.close_ts, m.status, m.result
           FROM kalshi_search s JOIN kalshi_markets m ON m.id = s.rowid
           WHERE kalshi_search MATCH ? AND m.close_ts BETWEEN ? AND ?
           ORDER BY bm25(kalshi_search) LIMIT ?""",
        (q, min_close or 0, max_close or 2**62, limit),
    )
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur]


def upsert_pm_markets(conn, gamma_rows):
    def row(m):
        outcomes = json.loads(m.get("outcomes") or "[]")
        tokens = json.loads(m.get("clobTokenIds") or "[]") + [None, None]
        prices = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
        result = prices.index(1.0) if m.get("closed") and 1.0 in prices else None
        category = next((e.get("category") for e in m.get("events") or []), None)
        fee_rate = 0.0
        if m.get("feesEnabled"):
            fee_rate = float((m.get("feeSchedule") or {}).get("rate", fees.PM_UNKNOWN_RATE))
        return (
            m["conditionId"], m.get("question"), m.get("description"),
            kalshi.iso_ts(m.get("endDate")), int(bool(m.get("closed"))), result,
            json.dumps(outcomes), tokens[0], tokens[1], category, m.get("slug"),
            fee_rate, kalshi.iso_ts(m.get("closedTime")),
        )  # fmt: skip

    conn.executemany(
        """INSERT OR REPLACE INTO pm_markets
           (condition_id, question, description, end_ts, closed, result_index, outcomes,
            outcome0_token, outcome1_token, category, slug, fee_rate, closed_ts)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [row(m) for m in gamma_rows],
    )
    conn.commit()


def pm_market(conn, condition_id):
    cur = conn.execute(
        """SELECT condition_id, question, description, outcomes, end_ts
           FROM pm_markets WHERE condition_id = ?""",
        (condition_id,),
    )
    r = cur.fetchone()
    if not r:
        return None
    return {"condition_id": r[0], "question": r[1], "description": r[2],
            "outcomes": json.loads(r[3]), "end_ts": r[4]}  # fmt: skip
