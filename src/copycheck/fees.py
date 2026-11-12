"""Avgifter per order. Kalshi: round_up(0.07 * C * P * (1 - P)) till hel cent.
Polymarket: C * rate * P * (1 - P), avrundat till 5 decimaler, rate per marknad (Gamma)."""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
PM_PRECISION = Decimal("0.00001")
PM_UNKNOWN_RATE = 0.07  # högsta räntan (krypto), när feesEnabled saknar feeSchedule


def fee(contracts, price):
    return (Decimal("0.07") * contracts * price * (1 - price)).quantize(CENT, ROUND_CEILING)


def pm_fee(shares, price, rate):
    """Polymarkets taker-avgift (docs.polymarket.com/trading/fees, 2026-11-12)."""
    return (Decimal(str(rate)) * shares * price * (1 - price)).quantize(PM_PRECISION, ROUND_HALF_UP)
