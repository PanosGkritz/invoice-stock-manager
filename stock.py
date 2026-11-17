"""Stock movements and stock levels.

Stock is never stored in a column: it is always the sum of stock_movements.
"""
import pandas as pd

from validation import MANUAL_MOVEMENT_TYPES, ValidationError, check_date, check_quantity


def current_stock(conn, product_id):
    row = conn.execute(
        "SELECT ROUND(COALESCE(SUM(quantity), 0), 3) FROM stock_movements WHERE product_id = ?",
        (product_id,),
    ).fetchone()
    return row[0]


def insert_movement(conn, product_id, movement_date, movement_type, quantity,
                    invoice_line_id=None, note=None):
    """Plain insert without validation or commit. Used by record_movement and create_invoice."""
    cur = conn.execute(
        "INSERT INTO stock_movements (product_id, movement_date, movement_type, quantity, "
        "invoice_line_id, note) VALUES (?, ?, ?, ?, ?, ?)",
        (product_id, movement_date, movement_type, quantity, invoice_line_id, note),
    )
    return cur.lastrowid


def record_movement(conn, sku, movement_date, movement_type, quantity, note=None):
    """Manual OUT or ADJUST movement.

    OUT takes a positive quantity and stores it as negative.
    ADJUST takes a signed quantity (+ found extra stock, - damaged or lost).
    The movement is rejected if stock would go below zero.
    """
    errors = []
    product = conn.execute(
        "SELECT product_id, unit FROM products WHERE sku = ?", (sku,)
    ).fetchone()
    if product is None:
        errors.append(f"product '{sku}' does not exist")
    if movement_type not in MANUAL_MOVEMENT_TYPES:
        errors.append(f"movement_type: must be one of {', '.join(MANUAL_MOVEMENT_TYPES)}")
    check_date(movement_date, "movement_date", errors)
    if product is not None and movement_type in MANUAL_MOVEMENT_TYPES:
        check_quantity(quantity, product["unit"], "quantity", errors,
                       allow_negative=(movement_type == "ADJUST"))
    if errors:
        raise ValidationError(errors)

    signed_qty = -quantity if movement_type == "OUT" else quantity
    available = current_stock(conn, product["product_id"])
    if round(available + signed_qty, 3) < 0:
        raise ValidationError(
            [f"not enough stock for {sku}: available {available}, change {signed_qty}"]
        )

    with conn:  # commits on success, rolls back on error
        return insert_movement(conn, product["product_id"], movement_date,
                               movement_type, signed_qty, note=note)


def stock_levels(conn, only_below_reorder=False):
    sql = "SELECT sku, name, unit, current_stock, reorder_level, below_reorder FROM v_stock_levels"
    if only_below_reorder:
        sql += " WHERE below_reorder = 1"
    return pd.read_sql_query(sql + " ORDER BY sku", conn)


def recent_movements(conn, limit=50):
    return pd.read_sql_query(
        """
        SELECT m.movement_id, m.movement_date, p.sku, p.name, m.movement_type,
               m.quantity, p.unit, m.note
        FROM stock_movements m
        JOIN products p USING (product_id)
        ORDER BY m.movement_date DESC, m.movement_id DESC
        LIMIT ?
        """,
        conn,
        params=(limit,),
    )
