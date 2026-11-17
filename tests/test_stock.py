import pytest

from operations import create_invoice
from stock import current_stock, record_movement, stock_levels
from validation import ValidationError


def milk_stock(conn):
    product_id = conn.execute("SELECT product_id FROM products WHERE sku = 'MILK'").fetchone()[0]
    return current_stock(conn, product_id)


def test_out_reduces_stock(conn, invoice):
    create_invoice(conn, invoice)
    record_movement(conn, "MILK", "2026-06-11", "OUT", 4)
    assert milk_stock(conn) == 6


def test_out_is_stored_as_negative(conn, invoice):
    create_invoice(conn, invoice)
    record_movement(conn, "MILK", "2026-06-11", "OUT", 4)
    qty = conn.execute("SELECT quantity FROM stock_movements WHERE movement_type = 'OUT'").fetchone()[0]
    assert qty == -4


def test_out_more_than_stock_rejected(conn, invoice):
    create_invoice(conn, invoice)
    with pytest.raises(ValidationError, match="not enough stock"):
        record_movement(conn, "MILK", "2026-06-11", "OUT", 11)
    assert milk_stock(conn) == 10


def test_adjust_can_be_negative(conn, invoice):
    create_invoice(conn, invoice)
    record_movement(conn, "MILK", "2026-06-11", "ADJUST", -2.5)
    assert milk_stock(conn) == 7.5


def test_manual_in_not_allowed(conn):
    with pytest.raises(ValidationError, match="movement_type"):
        record_movement(conn, "MILK", "2026-06-11", "IN", 5)


def test_unknown_product(conn):
    with pytest.raises(ValidationError, match="does not exist"):
        record_movement(conn, "NOPE", "2026-06-11", "OUT", 1)


def test_float_noise_is_rounded(conn, invoice):
    create_invoice(conn, invoice)
    for qty in (5.3, 4.1, 0.6):
        record_movement(conn, "MILK", "2026-06-12", "OUT", qty)
    assert milk_stock(conn) == 0


def test_below_reorder_list(conn, invoice):
    create_invoice(conn, invoice)   # MILK 10 (reorder 10), CUP 100 (reorder 100)
    record_movement(conn, "CUP", "2026-06-11", "ADJUST", 50)
    low = stock_levels(conn, only_below_reorder=True)
    assert list(low["sku"]) == ["MILK"]
