from datetime import date, timedelta

import pytest

from operations import add_expense, add_product, add_supplier
from validation import ValidationError, check_quantity, parse_date, validate_invoice


@pytest.mark.parametrize("value", ["2026-02-30", "03/11/2026", "20261103", "", None])
def test_invalid_dates(value):
    assert parse_date(value) is None


def test_valid_date():
    assert parse_date("2026-11-03") == date(2026, 11, 3)


@pytest.mark.parametrize("afm", ["12345678", "1234567890", "12345678A", ""])
def test_supplier_afm_must_be_9_digits(conn, afm):
    with pytest.raises(ValidationError):
        add_supplier(conn, "Bad", afm)


def test_supplier_duplicate_afm(conn):
    with pytest.raises(ValidationError, match="already exists"):
        add_supplier(conn, "Copy", "123456789")


def test_supplier_bad_email(conn):
    with pytest.raises(ValidationError, match="email"):
        add_supplier(conn, "X", "111111111", email="not-an-email")


def test_product_rules(conn):
    with pytest.raises(ValidationError) as e:
        add_product(conn, "MILK", "", "box", 9)
    assert len(e.value.errors) == 4   # duplicate sku, no name, bad unit, bad VAT id


def test_quantity_rules():
    errors = []
    check_quantity(1.5, "pcs", "q", errors)
    check_quantity(1.2345, "kg", "q", errors)
    check_quantity(0, "kg", "q", errors)
    check_quantity("5", "kg", "q", errors)
    assert len(errors) == 4
    ok = []
    check_quantity(2.125, "kg", "q", ok)
    assert ok == []


def test_expense_rules(conn):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    with pytest.raises(ValidationError) as e:
        add_expense(conn, tomorrow, " ", 0, vat_rate_id=7)
    assert len(e.value.errors) == 4   # future date, no category, amount, VAT id


def test_valid_invoice_has_no_errors(conn, invoice):
    assert validate_invoice(conn, invoice) == []


def test_invoice_collects_all_errors(conn, invoice):
    invoice["supplier_afm"] = "000000000"
    invoice["issue_date"] = "2026-13-01"
    invoice["lines"][0]["sku"] = "UNKNOWN"
    invoice["lines"][1]["quantity"] = 1.5      # cups are pieces
    errors = validate_invoice(conn, invoice)
    assert len(errors) == 4


def test_invoice_without_lines(conn, invoice):
    invoice["lines"] = []
    assert validate_invoice(conn, invoice) == ["lines: an invoice needs at least one line"]
