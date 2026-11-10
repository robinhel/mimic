"""Kommandon: collect (fas 1), catalog och search (fas 2)."""

import argparse
import time

from copycheck import config, db, kalshi, polymarket, ranking
from copycheck.http import HttpClient

LISTS = [("month", "PNL"), ("month", "VOLUME"), ("all", "PNL"), ("all", "VOLUME")]


def collect(client, conn, per_list, days, now, log=print, max_pages=20):
    """Hämtar kandidater, deras affärer och stängda positioner, och flaggar bottar."""
    for period, order_by in LISTS:
        rows = polymarket.leaderboard(client, period, order_by, per_list)
        for r in rows:
            db.upsert_trader(
                conn, r["user_id"], r.get("user_name"), f"{period}:{order_by}",
                r.get("pnl"), r.get("volume"),
            )  # fmt: skip
        log(f"topplista {period}/{order_by}: {len(rows)}")

    since = now - days * 86400
    wallets = [w for (w,) in conn.execute("SELECT wallet FROM traders ORDER BY wallet")]
    for i, wallet in enumerate(wallets, 1):
        # start är inklusive, så senaste affären hämtas igen men ignoreras som dubblett.
        start = max(since, db.last_trade_ts(conn, wallet) or since)
        acts, act_trunc = polymarket.activity(client, wallet, start, max_pages)
        db.insert_activity(conn, acts, seen_ts=now)
        act_trunc = act_trunc or db.activity_truncated(conn, wallet)
        pos, pos_trunc = [], False
        if not act_trunc:  # avkortad aktivitet = bot, positionerna behövs inte
            pos, pos_trunc = polymarket.closed_positions(client, wallet, max_pages)
            db.upsert_positions(conn, pos)
        conn.execute(
            """UPDATE traders SET collected_ts = ?,
                 activity_truncated = MAX(activity_truncated, ?), positions_truncated = ?
               WHERE wallet = ?""",
            (now, int(act_trunc), int(pos_trunc), wallet),
        )
        conn.commit()
        log(f"[{i}/{len(wallets)}] {wallet}: {len(acts)} affärer, {len(pos)} positioner")

    bots, total = ranking.flag_bots(conn)
    log(f"klart: {total} traders, {bots} flaggade som bottar")


def catalog(client, conn, base, days, now, log=print):
    """Hämtar Kalshi-marknader som stänger efter periodens start, historik och live."""
    series = kalshi.series(client, base)
    categories = {x["ticker"]: x.get("category") for x in series}
    skip = kalshi.skipped_series(series)
    since = now - days * 86400
    for historical in (True, False):
        kept = pages = 0
        for page in kalshi.markets(client, base, historical, since):
            rows = [m for m in page if kalshi.series_of(m["event_ticker"]) not in skip]
            db.upsert_kalshi_markets(conn, rows, "historical" if historical else "live", categories)
            kept += len(rows)
            pages += 1
            if pages % 50 == 0:
                log(f"{'historik' if historical else 'live'}: {pages} sidor, {kept} sparade")
        log(f"{'historik' if historical else 'live'} klar: {pages} sidor, {kept} sparade")
    db.rebuild_kalshi_search(conn)
    total = conn.execute("SELECT COUNT(*) FROM kalshi_markets").fetchone()[0]
    log(f"klart: {total} Kalshi-marknader, sökindex byggt")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="copycheck")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="hämta Polymarket-traders till databasen")
    c.add_argument("--per-list", type=int, default=150, help="traders per topplista (4 listor)")
    c.add_argument("--days", type=int, default=config.TRAIN_DAYS + config.TEST_DAYS)
    c.add_argument("--db", default=config.DB_PATH)
    k = sub.add_parser("catalog", help="hämta Kalshi-marknader till databasen")
    k.add_argument("--days", type=int, default=config.TRAIN_DAYS + config.TEST_DAYS)
    k.add_argument("--db", default=config.DB_PATH)
    s = sub.add_parser("search", help="sök bland Kalshi-marknaderna")
    s.add_argument("text")
    s.add_argument("--db", default=config.DB_PATH)
    args = p.parse_args(argv)

    if args.cmd == "collect":
        conn = db.connect(args.db)
        collect(HttpClient(), conn, args.per_list, args.days, int(time.time()))
    elif args.cmd == "catalog":
        conn = db.connect(args.db)
        catalog(HttpClient(), conn, config.KALSHI_BASE_URL, args.days, int(time.time()))
    elif args.cmd == "search":
        for m in db.search_kalshi(db.connect(args.db), args.text):
            print(f"{m['ticker']:45} {m['status'] or '':10} {m['result'] or '-':4} {m['title']}")
