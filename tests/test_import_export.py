import json
from pathlib import Path

import pytest

from db import create_database, get_connection
from import_export import export_json, export_xml, import_invoices, map_invoice
from operations import add_product, add_supplier, create_invoice

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

JSON_OK = json.dumps({"invoices": [{
    "supplier_vat": "123456789", "number": "J-1", "date": "2026-06-10",
    "lines": [{"product_code": "MILK", "quantity": 10, "unit_price": "1.20"}],
    "totals": {"net": "12.00", "vat": "1.56", "gross": "13.56"},
}]})

XML_OK = """<?xml version="1.0" encoding="utf-8"?>
<Invoices>
  <Invoice>
    <SupplierVAT>123456789</SupplierVAT><Number>X-1</Number><Date>2026-06-10</Date>
    <Lines>
      <Line><ProductCode>CUP</ProductCode><Quantity>100</Quantity><UnitPrice>0,08</UnitPrice></Line>
    </Lines>
    <Totals><Net>8.00</Net><VAT>1.92</VAT><Gross>9.92</Gross></Totals>
  </Invoice>
</Invoices>"""


def test_import_json(conn):
    report = import_invoices(conn, JSON_OK, "json")
    assert report[0]["status"] == "imported"
    assert conn.execute("SELECT gross_total_cents FROM invoices").fetchone()[0] == 1356


def test_import_xml_with_greek_decimal_comma(conn):
    report = import_invoices(conn, XML_OK, "xml")
    assert report[0]["status"] == "imported"


def test_each_invoice_is_accepted_or_rejected_on_its_own(conn):
    data = json.loads(JSON_OK)
    bad = dict(data["invoices"][0], number="J-2", totals={"net": "12.00", "vat": "9.99", "gross": "21.99"})
    data["invoices"].append(bad)
    report = import_invoices(conn, json.dumps(data), "json")
    assert [r["status"] for r in report] == ["imported", "rejected"]
    assert "vat total" in report[1]["errors"]


def test_mapping_reports_missing_fields():
    _, errors = map_invoice({"number": "A-1", "lines": [{"quantity": "x", "unit_price": "1.2"}]})
    assert "missing field 'supplier_vat'" in errors
    assert "missing field 'date'" in errors
    assert "line 1: missing 'product_code'" in errors
    assert "line 1: quantity 'x' is not a number" in errors


@pytest.mark.parametrize("text, fmt", [
    ("{not json", "json"),
    ('{"data": []}', "json"),
    ("<Invoices><Invoice>", "xml"),
    ("<Orders/>", "xml"),
])
def test_unreadable_files_raise(conn, text, fmt):
    with pytest.raises(ValueError):
        import_invoices(conn, text, fmt)


def test_unknown_format(conn):
    with pytest.raises(ValueError):
        import_invoices(conn, JSON_OK, "csv")


@pytest.mark.parametrize("export, fmt", [(export_json, "json"), (export_xml, "xml")])
def test_round_trip(conn, invoice, tmp_path, export, fmt):
    """Export from one database, import into an empty one: same totals."""
    create_invoice(conn, invoice)
    text = export(conn)

    other_path = tmp_path / "other.db"
    create_database(other_path)
    other = get_connection(other_path)
    add_supplier(other, "Test Dairy", "123456789")
    add_product(other, "MILK", "Milk", "lt", 2)
    add_product(other, "CUP", "Paper cup", "pcs", 1)

    report = import_invoices(other, text, fmt)
    assert [r["status"] for r in report] == ["imported"]
    totals = "SELECT net_total_cents, vat_total_cents, gross_total_cents FROM invoices"
    assert tuple(other.execute(totals).fetchone()) == tuple(conn.execute(totals).fetchone())
    other.close()


def test_export_date_filter(conn, invoice):
    create_invoice(conn, invoice)
    assert json.loads(export_json(conn, "2026-07-01", "2026-07-31")) == {"invoices": []}


def test_sample_files_are_readable(conn):
    for name, fmt in (("invoices_sample.json", "json"), ("invoices_sample.xml", "xml")):
        report = import_invoices(conn, (SAMPLES / name).read_text(encoding="utf-8"), fmt)
        assert len(report) == 2   # suppliers are missing in this test db, so both are rejected
