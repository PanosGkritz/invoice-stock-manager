import pytest

from db import create_database, get_connection
from operations import add_product, add_supplier


@pytest.fixture
def conn(tmp_path):
    """Fresh database with one supplier and two products for every test."""
    db_path = tmp_path / "test.db"
    create_database(db_path)
    connection = get_connection(db_path)
    add_supplier(connection, "Test Dairy", "123456789")
    add_product(connection, "MILK", "Milk", "lt", 2, reorder_level=10)   # 13% VAT
    add_product(connection, "CUP", "Paper cup", "pcs", 1, reorder_level=100)  # 24% VAT
    yield connection
    connection.close()


@pytest.fixture
def invoice():
    """A valid invoice: net 20.00, VAT 3.48, gross 23.48."""
    return {
        "supplier_afm": "123456789",
        "invoice_number": "INV-1",
        "issue_date": "2026-06-10",
        "lines": [
            {"sku": "MILK", "quantity": 10, "unit_price_cents": 120},  # 12.00 + 1.56 VAT
            {"sku": "CUP", "quantity": 100, "unit_price_cents": 8},    # 8.00 + 1.92 VAT
        ],
    }
