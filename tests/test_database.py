"""The CHECK constraints in schema.sql reject bad rows even if Python validation is bypassed."""
import sqlite3

import pytest

import seed_data
from db import get_connection
from reports import REPORTS, export_for_powerbi, run_report

BAD_INSERTS = [
    "INSERT INTO suppliers (name, afm) VALUES ('X', '12345')",
    "INSERT INTO products (sku, name, unit, vat_rate_id) VALUES ('P', 'P', 'box', 1)",
    "INSERT INTO products (sku, name, unit, vat_rate_id) VALUES ('P', 'P', 'kg', 99)",
    "INSERT INTO invoices (supplier_id, invoice_number, issue_date, net_total_cents, "
    "vat_total_cents, gross_total_cents) VALUES (1, 'A', '2026-06-01', 100, 24, 999)",
    "INSERT INTO invoices (supplier_id, invoice_number, issue_date, net_total_cents, "
    "vat_total_cents, gross_total_cents) VALUES (1, 'A', '01/06/2026', 100, 24, 124)",
    "INSERT INTO stock_movements (product_id, movement_date, movement_type, quantity) "
    "VALUES (1, '2026-06-01', 'OUT', 5)",
    "INSERT INTO expenses (expense_date, category, net_amount_cents) VALUES ('2026-06-01', 'X', -1)",
]


@pytest.mark.parametrize("sql", BAD_INSERTS)
def test_database_constraints(conn, sql):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql)


@pytest.fixture
def seeded(tmp_path):
    db_path = tmp_path / "seed.db"
    seed_data.main(db_path)
    connection = get_connection(db_path)
    yield connection
    connection.close()


def test_seed_data_is_consistent(seeded):
    mismatches = seeded.execute("""
        SELECT COUNT(*) FROM invoices i
        JOIN (SELECT invoice_id, SUM(net_amount_cents) AS net, SUM(vat_amount_cents) AS vat
              FROM invoice_lines GROUP BY invoice_id) l USING (invoice_id)
        WHERE i.net_total_cents <> l.net OR i.vat_total_cents <> l.vat
    """).fetchone()[0]
    negative = seeded.execute(
        "SELECT COUNT(*) FROM v_stock_levels WHERE current_stock < 0").fetchone()[0]
    assert mismatches == 0
    assert negative == 0
    assert seeded.execute("PRAGMA foreign_key_check").fetchall() == []


def test_reports_match_raw_tables(seeded):
    monthly = run_report(seeded, "Purchases by month")
    total = seeded.execute("SELECT SUM(gross_total_cents) FROM invoices").fetchone()[0]
    assert round(monthly["gross_eur"].sum() * 100) == total

    by_supplier = run_report(seeded, "Purchases by supplier")
    assert round(by_supplier["share_pct"].sum()) == 100

    vat = run_report(seeded, "VAT by rate")
    invoice_vat = seeded.execute("SELECT SUM(vat_total_cents) FROM invoices").fetchone()[0]
    assert round(vat[vat["source"] == "Invoices"]["vat_eur"].sum() * 100) == invoice_vat


def test_powerbi_export(seeded, tmp_path):
    paths = export_for_powerbi(seeded, tmp_path / "exports")
    assert len(paths) == len(REPORTS) + 2
    assert all(p.stat().st_size > 0 for p in paths)
