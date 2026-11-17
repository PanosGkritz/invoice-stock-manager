"""Import and export purchase invoices as JSON or XML.

External files use their own field names (see docs/data_mapping.md).
Both formats are first read into the same plain dict ("external record"),
then map_invoice() turns that into the internal format of create_invoice().
"""
import json
import xml.etree.ElementTree as ET

from money import cents_to_euros, to_cents
from operations import create_invoice
from validation import ValidationError

# XML element -> key of the external record (same keys as the JSON format)
XML_HEADER = {"SupplierVAT": "supplier_vat", "Number": "number", "Date": "date"}
XML_LINE = {"ProductCode": "product_code", "Quantity": "quantity", "UnitPrice": "unit_price"}
XML_TOTALS = {"Net": "net", "VAT": "vat", "Gross": "gross"}


# ---------- reading ----------

def read_json(text):
    data = json.loads(text)  # raises ValueError on malformed JSON
    if not isinstance(data, dict) or not isinstance(data.get("invoices"), list):
        raise ValueError('JSON must be an object with an "invoices" list')
    return data["invoices"]


def read_xml(text):
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"malformed XML: {e}") from e
    if root.tag != "Invoices":
        raise ValueError("XML root element must be <Invoices>")

    records = []
    for inv in root.findall("Invoice"):
        record = {key: inv.findtext(tag) for tag, key in XML_HEADER.items()}
        record["lines"] = [
            {key: line.findtext(tag) for tag, key in XML_LINE.items()}
            for line in inv.findall("Lines/Line")
        ]
        totals = inv.find("Totals")
        if totals is not None:
            record["totals"] = {key: totals.findtext(tag) for tag, key in XML_TOTALS.items()}
        records.append(record)
    return records


def to_number(value):
    """JSON gives numbers, XML gives text. Returns a float/int or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


# ---------- mapping external record -> internal invoice ----------

def map_invoice(record):
    """Returns (invoice, errors). errors lists problems found while mapping."""
    errors = []
    for field in ("supplier_vat", "number", "date"):
        if record.get(field) in (None, ""):
            errors.append(f"missing field '{field}'")

    lines = []
    for i, line in enumerate(record.get("lines") or [], start=1):
        quantity = to_number(line.get("quantity"))
        price = to_cents(line.get("unit_price"))
        if not line.get("product_code"):
            errors.append(f"line {i}: missing 'product_code'")
        if quantity is None:
            errors.append(f"line {i}: quantity '{line.get('quantity')}' is not a number")
        if price is None:
            errors.append(f"line {i}: unit_price '{line.get('unit_price')}' is not a valid amount")
        lines.append({"sku": line.get("product_code"), "quantity": quantity,
                      "unit_price_cents": price})

    invoice = {
        "supplier_afm": str(record.get("supplier_vat") or "").strip(),
        "invoice_number": str(record.get("number") or "").strip(),
        "issue_date": str(record.get("date") or "").strip(),
        "lines": lines,
    }

    totals = record.get("totals")
    if totals:
        declared = {key: to_cents(totals.get(key)) for key in ("net", "vat", "gross")}
        bad = [key for key, value in declared.items() if value is None]
        if bad:
            errors.append(f"totals: invalid or missing {', '.join(bad)}")
        else:
            invoice["declared_totals_cents"] = declared
    return invoice, errors


def import_invoices(conn, text, fmt):
    """Import every invoice in the file. Each invoice is accepted or rejected on its own.

    Returns a report: one dict per invoice with status 'imported' or 'rejected'.
    Raises ValueError if the file itself cannot be read.
    """
    if fmt == "json":
        records = read_json(text)
    elif fmt == "xml":
        records = read_xml(text)
    else:
        raise ValueError(f"unknown format '{fmt}', use json or xml")

    report = []
    for record in records:
        invoice, errors = map_invoice(record)
        if not errors:
            try:
                create_invoice(conn, invoice)
            except ValidationError as e:
                errors = e.errors
        report.append({
            "supplier_vat": invoice["supplier_afm"],
            "number": invoice["invoice_number"],
            "status": "rejected" if errors else "imported",
            "errors": "; ".join(errors),
        })
    return report


# ---------- exporting ----------

def format_quantity(quantity):
    return int(quantity) if float(quantity).is_integer() else quantity


def load_invoices(conn, date_from=None, date_to=None):
    """Invoices in the external record format, optionally filtered by issue date."""
    headers = conn.execute(
        """
        SELECT i.invoice_id, s.afm, i.invoice_number, i.issue_date,
               i.net_total_cents, i.vat_total_cents, i.gross_total_cents
        FROM invoices i
        JOIN suppliers s USING (supplier_id)
        WHERE i.issue_date BETWEEN COALESCE(?, '0000-01-01') AND COALESCE(?, '9999-12-31')
        ORDER BY i.issue_date, i.invoice_id
        """,
        (date_from, date_to),
    ).fetchall()

    records = []
    for h in headers:
        lines = conn.execute(
            """
            SELECT p.sku, l.quantity, l.unit_price_cents
            FROM invoice_lines l
            JOIN products p USING (product_id)
            WHERE l.invoice_id = ?
            ORDER BY l.invoice_line_id
            """,
            (h["invoice_id"],),
        ).fetchall()
        records.append({
            "supplier_vat": h["afm"],
            "number": h["invoice_number"],
            "date": h["issue_date"],
            "lines": [
                {"product_code": l["sku"], "quantity": format_quantity(l["quantity"]),
                 "unit_price": cents_to_euros(l["unit_price_cents"])}
                for l in lines
            ],
            "totals": {
                "net": cents_to_euros(h["net_total_cents"]),
                "vat": cents_to_euros(h["vat_total_cents"]),
                "gross": cents_to_euros(h["gross_total_cents"]),
            },
        })
    return records


def export_json(conn, date_from=None, date_to=None):
    records = load_invoices(conn, date_from, date_to)
    return json.dumps({"invoices": records}, ensure_ascii=False, indent=2)


def export_xml(conn, date_from=None, date_to=None):
    root = ET.Element("Invoices")
    for record in load_invoices(conn, date_from, date_to):
        inv = ET.SubElement(root, "Invoice")
        for tag, key in XML_HEADER.items():
            ET.SubElement(inv, tag).text = str(record[key])
        lines = ET.SubElement(inv, "Lines")
        for line in record["lines"]:
            line_el = ET.SubElement(lines, "Line")
            for tag, key in XML_LINE.items():
                ET.SubElement(line_el, tag).text = str(line[key])
        totals = ET.SubElement(inv, "Totals")
        for tag, key in XML_TOTALS.items():
            ET.SubElement(totals, tag).text = record["totals"][key]
    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)
