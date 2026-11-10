"""Backtest (fas 4): välj traders på träningsperioden, simulera kopiering på testperioden."""

from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal

from copycheck import kalshi
from copycheck.fees import fee
from copycheck.matching import kalshi_side

DELAYS = [0, 30, 120, 600]  # 0 = jämförelse utan fördröjning (lucka 30)
STRATEGIES = ["A", "B", "A_cap"]  # A håll, B sälj med tradern, A_cap hoppa över om priset sprungit
SHORT_MARKET = 3600  # lucka 39


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


def _skip(s, strategy, delay, reason):
    return {"signal_id": s["signal_id"], "strategy": strategy, "delay": delay,
            "kalshi_ticker": s["kalshi_ticker"], "skip_reason": reason}  # fmt: skip


def simulate(s, candles, sells, delay, strategy, cfg, open_bid=None):
    """En kopierad affär. `sells` = traderns säljtider för samma token efter signalen."""
    if s["pm_end_ts"] and s["pm_end_ts"] - s["trigger_ts"] < SHORT_MARKET:
        return _skip(s, strategy, delay, "short_market")
    side = kalshi_side(s["outcome_index"], s["outcome0_side"])
    entry_ts = s["trigger_ts"] + delay
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
        "signal_id": s["signal_id"], "strategy": strategy, "delay": delay,
        "kalshi_ticker": s["kalshi_ticker"], "side": side, "entry_ts": entry_ts,
        "entry_price": price, "quote_age": q["age"], "stale": int(q["age"] > cfg.stale_after),
        "contracts": contracts, "fee_in": fee_in, "exit_kind": exit_kind,
        "exit_price": exit_price, "fee_out": fee_out,
        "pnl": contracts * (exit_price - price) - fee_in - fee_out,
        "cost": contracts * price + fee_in, "mismatch": mismatch, "skip_reason": None,
    }  # fmt: skip
