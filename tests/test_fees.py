from decimal import Decimal

from copycheck.fees import fee


def test_exempel_fran_claude_md():
    assert fee(100, Decimal("0.55")) == Decimal("1.74")


def test_avrundar_uppat_till_hel_cent():
    assert fee(1, Decimal("0.50")) == Decimal("0.02")  # 0.0175 -> 0.02
    assert fee(0, Decimal("0.50")) == Decimal("0.00")
