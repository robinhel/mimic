"""Slår ihop fyllningar till signaler (lucka 13-14). Bara köp, bara traders som inte är bottar."""

FILLS = """
SELECT a.wallet, a.condition_id, a.token_id, a.outcome_index, a.price, a.size, a.usdc_size,
       a.trade_ts
FROM pm_activity a JOIN traders t USING (wallet)
WHERE a.side = 'BUY' AND NOT t.is_bot
ORDER BY a.wallet, a.token_id, a.trade_ts
"""


def group_fills(rows, window):
    """Samma plånbok + token, och högst `window` sekunder sedan förra fyllningen."""
    group = []
    for r in rows:
        if group and (r[:3] != group[-1][:3] or r[7] - group[-1][7] > window):
            yield group
            group = []
        group.append(r)
    if group:
        yield group


def to_signal(group, min_usd):
    total, trigger = 0.0, None
    for r in group:
        total += r[6] if r[6] is not None else r[4] * r[5]
        if trigger is None and total >= min_usd:
            trigger = r[7]
    if trigger is None:
        return None
    wallet, condition, token, outcome_index = group[0][:4]
    size = sum(r[5] for r in group)
    avg = sum(r[4] * r[5] for r in group) / size
    return (wallet, condition, token, outcome_index, avg, total,
            group[0][7], trigger, group[-1][7], len(group))  # fmt: skip


def build(conn, min_usd, window):
    """Bygger om tabellen signals från pm_activity."""
    found = (to_signal(g, min_usd) for g in group_fills(conn.execute(FILLS), window))
    conn.execute("DELETE FROM signals")
    conn.executemany(
        """INSERT INTO signals (wallet, condition_id, token_id, outcome_index, avg_price, usdc,
                                first_ts, trigger_ts, last_ts, n_fills)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (s for s in found if s),
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
