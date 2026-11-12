from decimal import Decimal

from copycheck.fees import fee, pm_fee


def test_exempel_fran_claude_md():
    assert fee(100, Decimal("0.55")) == Decimal("1.74")


def test_avrundar_uppat_till_hel_cent():
    assert fee(1, Decimal("0.50")) == Decimal("0.02")  # 0.0175 -> 0.02
    assert fee(0, Decimal("0.50")) == Decimal("0.00")


def test_polymarket_avgift_fran_dokumentationen():
    # docs.polymarket.com/trading/fees, sport (0.05): 100 andelar à 0.40 kostar 1.20 USDC.
    assert pm_fee(100, Decimal("0.40"), 0.05) == Decimal("1.2")
    # Avrundas till 5 decimaler, inte uppåt till hel cent som hos Kalshi.
    assert pm_fee(7, Decimal("0.33"), 0.03) == Decimal("0.04643")
    assert pm_fee(100, Decimal("0.40"), 0) == 0
