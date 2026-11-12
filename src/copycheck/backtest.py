"""Backtest (fas 4): välj traders på träningsperioden, simulera kopiering på testperioden."""

from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal

import requests

from copycheck import db, kalshi, polymarket
from copycheck.fees import fee, pm_fee
from copycheck.matching import kalshi_side

DELAYS = [0, 30, 120, 600]  # 0 = jämförelse utan fördröjning (lucka 30)
STRATEGIES = ["A", "B", "A_cap"]  # A håll, B sälj med tradern, A_cap hoppa över om priset sprungit
# Ingen spärr för korta marknader (lucka 39): Gammas slutdatum är matchstart för sport, och
# spärren hoppade över alla köp under pågående match. Bottar tas bort av botfiltret.


@dataclass(frozen=True)
class Config:
    amount: Decimal = Decimal(10)
    slippage: Decimal = Decimal("0.01")
    max_gap: Decimal = Decimal("0.05")
    stale_after: int = 15 * 60


def select_traders(conn, start, end, min_markets=50, top=20):
    """Ranka på ROI för positioner stängda under [start, end). Bara traders som inte är bottar."""
    return conn.execute(
        """SELECT p.wallet, SUM(p.realized_pnl) / SUM(p.avg_price * p.total_size) AS roi,
                  COUNT(*) AS n, SUM(p.realized_pnl) / COUNT(*) AS pnl_per_market
           FROM pm_positions p JOIN traders t USING (wallet)
           WHERE NOT t.is_bot AND p.last_event_ts >= ? AND p.last_event_ts < ?
           GROUP BY p.wallet HAVING n >= ? AND SUM(p.avg_price * p.total_size) > 0
           ORDER BY roi DESC LIMIT ?""",
        (start, end, min_markets, top),
    ).fetchall()


def quote_at(candles, ts):
    """Senaste candle som slutar senast `ts`. Candles saknas där inget hänt (lucka 36)."""
    ends = [c["end_period_ts"] for c in candles]
    i = bisect_right(ends, ts)
    if i == 0:
        return None
    c = candles[i - 1]
    return {
        "yes_bid": kalshi.dollars(c["yes_bid"]["close_dollars"]),
        "yes_ask": kalshi.dollars(c["yes_ask"]["close_dollars"]),
        "age": ts - c["end_period_ts"],
    }


def pm_quote_at(history, ts):
    """(bid, ask, ålder) från Polymarkets prishistorik. Historiken har bara mittpris,
    så bid = ask = senaste mittpris före `ts`. Slippage står för halva spreaden."""
    i = bisect_right([h["t"] for h in history], ts)
    if i == 0:
        return None
    p = polymarket.price(history[i - 1]["p"])
    return p, p, ts - history[i - 1]["t"]


def _skip(s, strategy, delay, reason, venue="kalshi"):
    return {"signal_id": s["signal_id"], "venue": venue, "strategy": strategy, "delay": delay,
            "kalshi_ticker": s.get("kalshi_ticker") if venue == "kalshi" else None,
            "skip_reason": reason}  # fmt: skip


def simulate_pm(s, history, sells, delay, strategy, cfg, open_price=None):
    """Samma köp som tradern, på Polymarket, `delay` sekunder efter signalen."""
    if s["fee_rate"] is None:
        return _skip(s, strategy, delay, "no_market", "polymarket")  # saknas i Gamma
    entry_ts = s["trigger_ts"] + delay
    if s.get("pm_closed_ts") and entry_ts >= s["pm_closed_ts"]:
        return _skip(s, strategy, delay, "closed", "polymarket")
    q = pm_quote_at(history, entry_ts)
    if q is None:
        return _skip(s, strategy, delay, "no_price", "polymarket")
    price = q[1] + cfg.slippage
    if not 0 < price < 1:
        return _skip(s, strategy, delay, "no_price", "polymarket")
    if strategy == "A_cap" and price - Decimal(str(s["avg_price"])) > cfg.max_gap:
        return _skip(s, strategy, delay, "price_ran", "polymarket")
    contracts = int(cfg.amount / price)
    if contracts == 0:
        return _skip(s, strategy, delay, "too_expensive", "polymarket")
    fee_in, fee_out = pm_fee(contracts, price, s["fee_rate"]), Decimal(0)

    exit_kind, exit_price = None, None
    if strategy == "B" and sells:
        q2 = pm_quote_at(history, sells[0] + delay)
        if q2:
            exit_kind, exit_price = "sold", max(q2[0] - cfg.slippage, Decimal(0))
            fee_out = pm_fee(contracts, exit_price, s["fee_rate"])
    if exit_kind is None:
        if s["pm_result_index"] is not None:
            exit_kind = "settled"
            exit_price = Decimal(int(s["pm_result_index"] == s["outcome_index"]))
        else:
            exit_kind, exit_price = "open", open_price
    if exit_price is None:
        return _skip(s, strategy, delay, "no_exit_price", "polymarket")
    return {
        "signal_id": s["signal_id"], "venue": "polymarket", "strategy": strategy,
        "delay": delay, "kalshi_ticker": None, "side": None, "entry_ts": entry_ts,
        "entry_price": price, "quote_age": q[2], "stale": int(q[2] > cfg.stale_after),
        "contracts": contracts, "fee_in": fee_in, "exit_kind": exit_kind,
        "exit_price": exit_price, "fee_out": fee_out,
        "pnl": contracts * (exit_price - price) - fee_in - fee_out,
        "cost": contracts * price + fee_in, "mismatch": None, "skip_reason": None,
    }  # fmt: skip


def simulate(s, candles, sells, delay, strategy, cfg, open_bid=None):
    """En kopierad affär. `sells` = traderns säljtider för samma token efter signalen."""
    side = kalshi_side(s["outcome_index"], s["outcome0_side"])
    entry_ts = s["trigger_ts"] + delay
    if s.get("kalshi_close_ts") and entry_ts >= s["kalshi_close_ts"]:
        return _skip(s, strategy, delay, "closed")  # annars köp till sista priset före stängning
    q = quote_at(candles, entry_ts)
    if q is None or q["yes_bid"] is None or q["yes_ask"] is None:
        return _skip(s, strategy, delay, "no_price")
    price = kalshi.ask_for(side, q["yes_bid"], q["yes_ask"]) + cfg.slippage
    if not 0 < price < 1:
        return _skip(s, strategy, delay, "no_price")
    if strategy == "A_cap" and price - Decimal(str(s["avg_price"])) > cfg.max_gap:
        return _skip(s, strategy, delay, "price_ran")
    contracts = int(cfg.amount / price)
    if contracts == 0:
        return _skip(s, strategy, delay, "too_expensive")
    fee_in, fee_out = fee(contracts, price), Decimal(0)

    exit_kind, exit_price = None, None
    if strategy == "B" and sells:
        q2 = quote_at(candles, sells[0] + delay)
        if q2 and q2["yes_bid"] is not None and q2["yes_ask"] is not None:
            exit_kind = "sold"
            exit_price = max(kalshi.bid_for(side, q2["yes_bid"], q2["yes_ask"]) - cfg.slippage, 0)
            fee_out = fee(contracts, exit_price)
    if exit_kind is None:
        if s["kalshi_result"] in ("yes", "no"):
            exit_kind, exit_price = "settled", Decimal(int(s["kalshi_result"] == side))
        else:
            exit_kind, exit_price = "open", open_bid  # lucka 27
    if exit_price is None:
        return _skip(s, strategy, delay, "no_exit_price")

    mismatch = None
    if s["pm_result_index"] is not None and s["kalshi_result"] in ("yes", "no"):
        pm_won = s["pm_result_index"] == s["outcome_index"]
        mismatch = int(pm_won != (s["kalshi_result"] == side))
    return {
        "signal_id": s["signal_id"], "venue": "kalshi", "strategy": strategy, "delay": delay,
        "kalshi_ticker": s["kalshi_ticker"], "side": side, "entry_ts": entry_ts,
        "entry_price": price, "quote_age": q["age"], "stale": int(q["age"] > cfg.stale_after),
        "contracts": contracts, "fee_in": fee_in, "exit_kind": exit_kind,
        "exit_price": exit_price, "fee_out": fee_out,
        "pnl": contracts * (exit_price - price) - fee_in - fee_out,
        "cost": contracts * price + fee_in, "mismatch": mismatch, "skip_reason": None,
    }  # fmt: skip


TEST_SIGNALS = """
SELECT s.id, s.wallet, s.token_id, s.trigger_ts, s.avg_price, s.outcome_index,
       p.end_ts, p.result_index, p.category, p.fee_rate, p.closed_ts,
       mm.kalshi_ticker, m.outcome0_side, k.result, k.close_ts
FROM signals s
LEFT JOIN pm_markets p ON p.condition_id = s.condition_id
LEFT JOIN (SELECT pm_condition, MIN(kalshi_ticker) AS kalshi_ticker FROM matches
           WHERE level = 'exact' AND COALESCE(review_ok, 1) = 1
           GROUP BY pm_condition) mm ON mm.pm_condition = s.condition_id
LEFT JOIN matches m ON m.pm_condition = mm.pm_condition AND m.kalshi_ticker = mm.kalshi_ticker
LEFT JOIN kalshi_markets k ON k.ticker = mm.kalshi_ticker
WHERE s.wallet IN ({wallets}) AND s.trigger_ts >= ? AND s.trigger_ts < ?
ORDER BY s.id
"""
COLUMNS = ["signal_id", "venue", "strategy", "delay", "kalshi_ticker", "side", "entry_ts",
           "entry_price", "quote_age", "stale", "contracts", "fee_in", "exit_kind", "exit_price",
           "fee_out",
           "pnl", "cost", "mismatch", "skip_reason"]  # fmt: skip
CANDLE_LOOKBACK = 86400  # pris äldre än ett dygn räknas som saknat


def fetch_candles(client, base, ticker, start, end):
    body = client.get_json(
        f"{base}/markets/candlesticks",
        {"market_tickers": ticker, "start_ts": start, "end_ts": end, "period_interval": 1},
    )
    return next(iter(body.get("markets") or []), {}).get("candlesticks") or []


def open_bid(client, base, ticker, side):
    try:
        m = client.get_json(f"{base}/markets/{ticker}").get("market") or {}
    except requests.HTTPError:
        return None
    yes_bid, yes_ask = (
        kalshi.dollars(m.get("yes_bid_dollars")),
        kalshi.dollars(m.get("yes_ask_dollars")),
    )
    if yes_bid is None or yes_ask is None:
        return None
    return kalshi.bid_for(side, yes_bid, yes_ask)


def _merged(rows, key):
    return sorted({r[key]: r for r in rows}.values(), key=lambda r: r[key])


def pm_history(client, token, around):
    """Prishistorik runt varje tidpunkt i `around`, ihopslagen."""
    rows = []
    for ts in around:
        rows += polymarket.prices_history(client, token, ts - CANDLE_LOOKBACK,
                                          ts + max(DELAYS) + 60)  # fmt: skip
    return _merged(rows, "t")


def first_sell(conn, wallet, token, after, before):
    return conn.execute(
        """SELECT MIN(trade_ts) FROM pm_activity
           WHERE wallet = ? AND token_id = ? AND side = 'SELL' AND trade_ts > ? AND trade_ts < ?""",
        (wallet, token, after, before or 2**62),
    ).fetchone()[0]


def _db_row(r):
    return tuple(float(r[c]) if isinstance(r.get(c), Decimal) else r.get(c) for c in COLUMNS)


def run(conn, client, base, train_start, train_end, test_end, cfg, top=20, log=print):
    """Simulerar varje signal på Polymarket och, där en matchning finns, på Kalshi."""
    traders = select_traders(conn, train_start, train_end, top=top)
    log(f"{len(traders)} traders valda på träningsperioden")
    wallets = [t[0] for t in traders]
    marks = ",".join("?" * len(wallets)) or "NULL"
    period = (*wallets, train_end, test_end)
    todo = [c for (c,) in conn.execute(
        f"""SELECT DISTINCT s.condition_id FROM signals s
            LEFT JOIN pm_markets p ON p.condition_id = s.condition_id
            WHERE s.wallet IN ({marks}) AND s.trigger_ts >= ? AND s.trigger_ts < ?
            AND p.fee_rate IS NULL""", period,
    )]  # fmt: skip
    if todo:  # avgift och stängningstid saknas i äldre rader
        db.upsert_pm_markets(conn, polymarket.gamma_markets(client, todo))
        log(f"{len(todo)} PM-marknader hämtade från Gamma")
    rows = conn.execute(TEST_SIGNALS.format(wallets=marks), period).fetchall()
    log(f"{len(rows)} signaler i testperioden")
    conn.execute("DELETE FROM sim_trades")
    out = []
    for i, r in enumerate(rows, 1):
        (sid, wallet, token, trigger, avg, idx, pm_end, pm_res, cat, fee_rate, pm_closed,
         ticker, side0, k_res, close) = r  # fmt: skip
        s = {"signal_id": sid, "wallet": wallet, "trigger_ts": trigger, "avg_price": avg,
             "outcome_index": idx, "pm_end_ts": pm_end, "pm_result_index": pm_res,
             "kalshi_ticker": ticker, "outcome0_side": side0, "kalshi_result": k_res,
             "category": cat, "kalshi_close_ts": close, "fee_rate": fee_rate,
             "pm_closed_ts": pm_closed}  # fmt: skip

        # Polymarket: samma token som tradern köpte, ingen matchning behövs.
        sell = first_sell(conn, wallet, token, trigger, pm_closed)
        hist, open_price = [], None
        if fee_rate is not None:
            hist = pm_history(client, token, [trigger] + ([sell] if sell else []))
            if pm_res is None:  # öppen marknad värderas med senaste pris (lucka 27)
                last = polymarket.prices_history(client, token, test_end - CANDLE_LOOKBACK,
                                                 test_end)  # fmt: skip
                open_price = polymarket.price(last[-1]["p"]) if last else None
        for st in STRATEGIES:
            for d in DELAYS:
                out.append(simulate_pm(s, hist, [sell] if sell else [], d, st, cfg, open_price))
        if i % 100 == 0:
            log(f"{i}/{len(rows)} signaler simulerade")

        # Kalshi: bara där AI-matchningen hittade exakt samma fråga.
        if ticker is None or side0 is None:
            out += [_skip(s, st, d, "no_match") for st in STRATEGIES for d in DELAYS]
            continue
        candles = fetch_candles(client, base, ticker, trigger - CANDLE_LOOKBACK,
                                trigger + max(DELAYS) + 60)  # fmt: skip
        sell = first_sell(conn, wallet, token, trigger, close)
        if sell:
            later = fetch_candles(client, base, ticker, sell - CANDLE_LOOKBACK,
                                  sell + max(DELAYS) + 60)  # fmt: skip
            candles = _merged(candles + later, "end_period_ts")
        side = kalshi_side(idx, side0)
        bid = open_bid(client, base, ticker, side) if k_res not in ("yes", "no") else None
        for st in STRATEGIES:
            for d in DELAYS:
                out.append(simulate(s, candles, [sell] if sell else [], d, st, cfg, bid))
    conn.executemany(
        f"INSERT INTO sim_trades ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
        [_db_row(r) for r in out],
    )
    conn.commit()
    log(f"klart: {len(out)} rader i sim_trades")
