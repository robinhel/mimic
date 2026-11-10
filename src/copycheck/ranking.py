"""Botfilter (lucka 11). Ranking per period kommer i fas 4."""

# Gränserna är första gissningar. Kolla fördelningen efter en körning och justera.
MAX_TRADES_PER_DAY = 100
MAX_BOTH_SIDES_SHARE = 0.2  # andel marknader där plånboken köpt båda utfallen
MIN_MARGIN = 0.01  # realiserad vinst / insats, under detta = market maker
MIN_POSITIONS_FOR_MARGIN = 50

STATS = """
WITH act AS (
    SELECT wallet,
           COUNT(*) AS n,
           (MAX(trade_ts) - MIN(trade_ts)) / 86400.0 AS days
    FROM pm_activity GROUP BY wallet
),
sides AS (
    SELECT wallet, AVG(n_sides > 1) AS both_share
    FROM (SELECT wallet, condition_id, COUNT(DISTINCT outcome_index) AS n_sides
          FROM pm_activity WHERE side = 'BUY' GROUP BY wallet, condition_id)
    GROUP BY wallet
),
pos AS (
    SELECT wallet, COUNT(*) AS n_pos,
           SUM(realized_pnl) / NULLIF(SUM(avg_price * total_size), 0) AS margin
    FROM pm_positions GROUP BY wallet
)
SELECT t.wallet, t.activity_truncated, act.n, act.days, sides.both_share, pos.n_pos, pos.margin
FROM traders t
LEFT JOIN act USING (wallet)
LEFT JOIN sides USING (wallet)
LEFT JOIN pos USING (wallet)
"""


def bot_reasons(truncated, n, days, both_share, n_pos, margin):
    reasons = []
    if truncated:
        reasons.append("avkortad aktivitet (för många affärer)")
    if n and n / max(days or 0, 1) > MAX_TRADES_PER_DAY:
        reasons.append(f"{n / max(days, 1):.0f} affärer/dag")
    if both_share is not None and both_share > MAX_BOTH_SIDES_SHARE:
        reasons.append(f"båda sidor i {both_share:.0%} av marknaderna")
    if (n_pos or 0) >= MIN_POSITIONS_FOR_MARGIN and margin is not None and 0 <= margin < MIN_MARGIN:
        reasons.append(f"marginal {margin:.2%}")
    return reasons


def flag_bots(conn):
    rows = conn.execute(STATS).fetchall()
    updates = []
    for wallet, *stats in rows:
        reasons = bot_reasons(*stats)
        updates.append((1 if reasons else 0, "; ".join(reasons) or None, wallet))
    conn.executemany("UPDATE traders SET is_bot = ?, bot_reason = ? WHERE wallet = ?", updates)
    conn.commit()
    return sum(u[0] for u in updates), len(updates)
