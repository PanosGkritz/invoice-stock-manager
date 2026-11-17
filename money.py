"""Money helpers. Amounts are stored as integer cents to avoid float rounding errors."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENT = Decimal("0.01")
ONE = Decimal("1")


def to_cents(euros):
    """'12.50', '12,5' or 12.5 -> 1250. Returns None if invalid or more than 2 decimals."""
    if euros is None or isinstance(euros, bool):
        return None
    try:
        value = Decimal(str(euros).strip().replace(",", "."))
    except InvalidOperation:
        return None
    if not value.is_finite() or value != value.quantize(CENT):
        return None
    return int(value * 100)


def cents_to_euros(cents):
    """1250 -> '12.50'"""
    return str((Decimal(cents) / 100).quantize(CENT))


def line_net_cents(quantity, unit_price_cents):
    """Net amount of an invoice line, rounded half-up to the cent."""
    net = Decimal(str(quantity)) * unit_price_cents
    return int(net.quantize(ONE, rounding=ROUND_HALF_UP))


def vat_cents(net_cents, rate_percent):
    """VAT amount, rounded half-up to the cent."""
    vat = Decimal(net_cents) * rate_percent / 100
    return int(vat.quantize(ONE, rounding=ROUND_HALF_UP))
