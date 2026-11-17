import pytest

from operations import create_invoice
from validation import ValidationError


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_totals_are_calculated(conn, invoice):
    invoice_id = create_invoice(conn, invoice)
    row = conn.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)).fetchone()
    assert (row["net_total_cents"], row["vat_total_cents"], row["gross_total_cents"]) == (2000, 348, 2348)


def test_line_keeps_vat_rate_of_purchase(conn, invoice):
    create_invoice(conn, invoice)
    conn.execute("UPDATE products SET vat_rate_id = 1 WHERE sku = 'MILK'")  # VAT changes later
    rate = conn.execute(
        "SELECT v.rate_percent FROM invoice_lines l JOIN vat_rates v USING (vat_rate_id) "
        "JOIN products p ON p.product_id = l.product_id WHERE p.sku = 'MILK'"
    ).fetchone()[0]
    assert rate == 13


def test_invoice_creates_in_movements(conn, invoice):
    create_invoice(conn, invoice)
    rows = conn.execute(
        "SELECT movement_type, quantity FROM stock_movements ORDER BY movement_id"
    ).fetchall()
    assert [tuple(r) for r in rows] == [("IN", 10), ("IN", 100)]


def test_duplicate_invoice_rejected(conn, invoice):
    create_invoice(conn, invoice)
    with pytest.raises(ValidationError, match="already exists"):
        create_invoice(conn, invoice)
    assert count(conn, "invoices") == 1


def test_invalid_invoice_writes_nothing(conn, invoice):
    invoice["lines"][1]["sku"] = "UNKNOWN"
    with pytest.raises(ValidationError):
        create_invoice(conn, invoice)
    for table in ("invoices", "invoice_lines", "stock_movements"):
        assert count(conn, table) == 0


def test_declared_totals_must_match(conn, invoice):
    invoice["declared_totals_cents"] = {"net": 2000, "vat": 350, "gross": 2350}
    with pytest.raises(ValidationError) as e:
        create_invoice(conn, invoice)
    assert len(e.value.errors) == 2   # vat and gross differ
    assert count(conn, "invoices") == 0


def test_declared_totals_that_match_are_accepted(conn, invoice):
    invoice["declared_totals_cents"] = {"net": 2000, "vat": 348, "gross": 2348}
    assert create_invoice(conn, invoice)
