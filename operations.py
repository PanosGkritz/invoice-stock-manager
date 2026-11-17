"""Create suppliers, products, expenses and invoices, always validating first."""
from money import line_net_cents, vat_cents
from stock import insert_movement
from validation import (
    ValidationError,
    validate_expense,
    validate_invoice,
    validate_product,
    validate_supplier,
)


def add_supplier(conn, name, afm, email=None, phone=None, address=None):
    supplier = {"name": name, "afm": afm, "email": email, "phone": phone, "address": address}
    errors = validate_supplier(conn, supplier)
    if errors:
        raise ValidationError(errors)
    with conn:
        cur = conn.execute(
            "INSERT INTO suppliers (name, afm, email, phone, address) VALUES (?, ?, ?, ?, ?)",
            (name.strip(), afm, email, phone, address),
        )
    return cur.lastrowid


def add_product(conn, sku, name, unit, vat_rate_id, reorder_level=0):
    product = {"sku": sku, "name": name, "unit": unit,
               "vat_rate_id": vat_rate_id, "reorder_level": reorder_level}
    errors = validate_product(conn, product)
    if errors:
        raise ValidationError(errors)
    with conn:
        cur = conn.execute(
            "INSERT INTO products (sku, name, unit, vat_rate_id, reorder_level) "
            "VALUES (?, ?, ?, ?, ?)",
            (sku.strip(), name.strip(), unit, vat_rate_id, reorder_level),
        )
    return cur.lastrowid


def add_expense(conn, expense_date, category, net_amount_cents,
                description=None, vat_rate_id=None, supplier_id=None):
    expense = {"expense_date": expense_date, "category": category,
               "net_amount_cents": net_amount_cents, "vat_rate_id": vat_rate_id,
               "supplier_id": supplier_id}
    errors = validate_expense(conn, expense)
    if errors:
        raise ValidationError(errors)
    with conn:
        cur = conn.execute(
            "INSERT INTO expenses (expense_date, category, description, net_amount_cents, "
            "vat_rate_id, supplier_id) VALUES (?, ?, ?, ?, ?, ?)",
            (expense_date, category.strip(), description, net_amount_cents,
             vat_rate_id, supplier_id),
        )
    return cur.lastrowid


def create_invoice(conn, invoice):
    """Save a purchase invoice with its lines and one IN stock movement per line.

    invoice = {
        "supplier_afm": "990000011",
        "invoice_number": "GV-00001",
        "issue_date": "2026-06-01",
        "lines": [{"sku": "DAI-01", "quantity": 60, "unit_price_cents": 120}, ...],
        "declared_totals_cents": {"net": ..., "vat": ..., "gross": ...},   # optional
    }
    Totals are always calculated here. If the source also declares totals
    (e.g. an imported file), they must match the calculated ones.
    Everything is saved in one transaction: all or nothing.
    """
    errors = validate_invoice(conn, invoice)
    if errors:
        raise ValidationError(errors)

    supplier_id = conn.execute(
        "SELECT supplier_id FROM suppliers WHERE afm = ?", (invoice["supplier_afm"],)
    ).fetchone()["supplier_id"]

    lines = []
    for line in invoice["lines"]:
        # VAT comes from the product's current rate and is copied onto the line
        product = conn.execute(
            "SELECT p.product_id, p.vat_rate_id, v.rate_percent "
            "FROM products p JOIN vat_rates v USING (vat_rate_id) WHERE p.sku = ?",
            (line["sku"],),
        ).fetchone()
        net = line_net_cents(line["quantity"], line["unit_price_cents"])
        vat = vat_cents(net, product["rate_percent"])
        lines.append((product, line["quantity"], line["unit_price_cents"], net, vat))

    net_total = sum(line[3] for line in lines)
    vat_total = sum(line[4] for line in lines)
    gross_total = net_total + vat_total

    declared = invoice.get("declared_totals_cents")
    if declared:
        calculated = {"net": net_total, "vat": vat_total, "gross": gross_total}
        mismatches = [
            f"{key} total: declared {declared[key]} cents, calculated {calculated[key]} cents"
            for key in ("net", "vat", "gross")
            if declared[key] != calculated[key]
        ]
        if mismatches:
            raise ValidationError(mismatches)

    with conn:  # one transaction for header, lines and stock movements
        cur = conn.execute(
            "INSERT INTO invoices (supplier_id, invoice_number, issue_date, "
            "net_total_cents, vat_total_cents, gross_total_cents) VALUES (?, ?, ?, ?, ?, ?)",
            (supplier_id, invoice["invoice_number"].strip(), invoice["issue_date"],
             net_total, vat_total, gross_total),
        )
        invoice_id = cur.lastrowid
        for product, quantity, unit_price, net, vat in lines:
            cur = conn.execute(
                "INSERT INTO invoice_lines (invoice_id, product_id, quantity, unit_price_cents, "
                "vat_rate_id, net_amount_cents, vat_amount_cents) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (invoice_id, product["product_id"], quantity, unit_price,
                 product["vat_rate_id"], net, vat),
            )
            insert_movement(conn, product["product_id"], invoice["issue_date"], "IN",
                            quantity, invoice_line_id=cur.lastrowid)
    return invoice_id
