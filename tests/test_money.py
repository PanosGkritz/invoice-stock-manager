import pytest

from money import cents_to_euros, line_net_cents, to_cents, vat_cents


@pytest.mark.parametrize("value, expected", [
    ("12.50", 1250),
    ("12,5", 1250),
    (12.5, 1250),
    (7, 700),
    ("0.01", 1),
    ("1.234", None),   # more than 2 decimals
    ("abc", None),
    ("", None),
    (None, None),
    ("nan", None),
])
def test_to_cents(value, expected):
    assert to_cents(value) == expected


def test_cents_to_euros():
    assert cents_to_euros(1250) == "12.50"
    assert cents_to_euros(5) == "0.05"


def test_vat_rounds_half_up():
    assert vat_cents(1050, 13) == 137   # 136.5 -> 137
    assert vat_cents(1000, 24) == 240


def test_line_net_with_decimal_quantity():
    assert line_net_cents(2.5, 333) == 833   # 832.5 -> 833
    assert line_net_cents(0.1, 3) == 0       # 0.3 -> 0
