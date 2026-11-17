"""Business rules checked before anything is written to the database.

Every validate_* function returns a list of error messages (empty list = valid).
The CHECK constraints in schema.sql are a second safety net, not the main check.
"""
import math
import re
from datetime import date

AFM_RE = re.compile(r"\d{9}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
UNITS = ("kg", "lt", "pcs")
MANUAL_MOVEMENT_TYPES = ("OUT", "ADJUST")  # IN movements come only from invoices


class ValidationError(Exception):
    """Raised when data fails validation. `errors` holds every message."""

    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


# ---------- small reusable checks ----------

def parse_date(value):
    """Strict YYYY-MM-DD. Returns a date or None."""
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:  # e.g. 2026-02-30
        return None


def check_date(value, field, errors):
    parsed = parse_date(value)
    if parsed is None:
        errors.append(f"{field}: '{value}' is not a valid date (YYYY-MM-DD)")
    elif parsed > date.today():
        errors.append(f"{field}: {value} is in the future")


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_quantity(value, unit, field, errors, allow_negative=False):
    if not is_number(value):
        errors.append(f"{field}: '{value}' is not a number")
        return
    if allow_negative and value == 0:
        errors.append(f"{field}: cannot be 0")
    elif not allow_negative and value <= 0:
        errors.append(f"{field}: must be greater than 0")
    if unit == "pcs" and value != int(value):
        errors.append(f"{field}: must be a whole number for pieces")
    elif round(value, 3) != value:
        errors.append(f"{field}: at most 3 decimals allowed")


def exists(conn, table, column, value):
    # table/column names come from our own code, never from user input
    row = conn.execute(f"SELECT 1 FROM {table} WHERE {column} = ?", (value,)).fetchone()
    return row is not None


# ---------- validators per entity ----------

def validate_supplier(conn, supplier):
    errors = []
    if not (supplier.get("name") or "").strip():
        errors.append("name: required")
    afm = supplier.get("afm") or ""
    if not AFM_RE.fullmatch(afm):
        errors.append(f"afm: '{afm}' must be exactly 9 digits")
    elif exists(conn, "suppliers", "afm", afm):
        errors.append(f"afm: a supplier with AFM {afm} already exists")
    email = supplier.get("email")
    if email and not EMAIL_RE.fullmatch(email):
        errors.append(f"email: '{email}' is not a valid email")
    return errors


def validate_product(conn, product):
    errors = []
    sku = (product.get("sku") or "").strip()
    if not sku:
        errors.append("sku: required")
    elif exists(conn, "products", "sku", sku):
        errors.append(f"sku: product {sku} already exists")
    if not (product.get("name") or "").strip():
        errors.append("name: required")
    if product.get("unit") not in UNITS:
        errors.append(f"unit: must be one of {', '.join(UNITS)}")
    if not exists(conn, "vat_rates", "vat_rate_id", product.get("vat_rate_id")):
        errors.append(f"vat_rate_id: {product.get('vat_rate_id')} does not exist")
    reorder = product.get("reorder_level", 0)
    if not is_number(reorder) or reorder < 0:
        errors.append("reorder_level: must be a number >= 0")
    return errors


def validate_expense(conn, expense):
    errors = []
    check_date(expense.get("expense_date"), "expense_date", errors)
    if not (expense.get("category") or "").strip():
        errors.append("category: required")
    amount = expense.get("net_amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        errors.append("net_amount: must be a positive amount")
    vat_id = expense.get("vat_rate_id")
    if vat_id is not None and not exists(conn, "vat_rates", "vat_rate_id", vat_id):
        errors.append(f"vat_rate_id: {vat_id} does not exist")
    supplier_id = expense.get("supplier_id")
    if supplier_id is not None and not exists(conn, "suppliers", "supplier_id", supplier_id):
        errors.append(f"supplier_id: {supplier_id} does not exist")
    return errors


def validate_invoice(conn, invoice):
    """Checks the invoice header and lines. Totals are checked in create_invoice."""
    errors = []
    supplier = conn.execute(
        "SELECT supplier_id FROM suppliers WHERE afm = ?", (invoice.get("supplier_afm"),)
    ).fetchone()
    if supplier is None:
        errors.append(f"supplier: no supplier with AFM '{invoice.get('supplier_afm')}'")

    number = (invoice.get("invoice_number") or "").strip()
    if not number:
        errors.append("invoice_number: required")
    elif supplier is not None:
        duplicate = conn.execute(
            "SELECT 1 FROM invoices WHERE supplier_id = ? AND invoice_number = ?",
            (supplier["supplier_id"], number),
        ).fetchone()
        if duplicate:
            errors.append(f"invoice_number: {number} already exists for this supplier")

    check_date(invoice.get("issue_date"), "issue_date", errors)

    lines = invoice.get("lines") or []
    if not lines:
        errors.append("lines: an invoice needs at least one line")
    for i, line in enumerate(lines, start=1):
        product = conn.execute(
            "SELECT unit FROM products WHERE sku = ?", (line.get("sku"),)
        ).fetchone()
        if product is None:
            errors.append(f"line {i}: product '{line.get('sku')}' does not exist")
        check_quantity(line.get("quantity"), product["unit"] if product else None,
                       f"line {i} quantity", errors)
        price = line.get("unit_price_cents")
        if not isinstance(price, int) or isinstance(price, bool) or price < 0:
            errors.append(f"line {i}: unit price must be an amount >= 0")
    return errors
