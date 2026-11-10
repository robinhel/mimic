"""Kalshis avgift per order: round_up(0.07 * C * P * (1 - P)) till hel cent."""

from decimal import ROUND_CEILING, Decimal

CENT = Decimal("0.01")


def fee(contracts, price):
    return (Decimal("0.07") * contracts * price * (1 - price)).quantize(CENT, ROUND_CEILING)
