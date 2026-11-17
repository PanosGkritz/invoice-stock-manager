"""Streamlit user interface. Run with:  streamlit run app.py"""
from datetime import date

import pandas as pd
import streamlit as st

import import_export
import reports
import stock
from db import DB_PATH, PROJECT_DIR, get_connection
from money import to_cents
from operations import add_expense, create_invoice
from validation import ValidationError

st.set_page_config(page_title="Invoice, Expense & Stock Manager", layout="wide")


def show_errors(error):
    for message in error.errors:
        st.error(message)


# ---------- pages ----------

def invoices_page(conn):
    st.header("Purchase invoices")
    invoices = pd.read_sql_query(
        """
        SELECT i.invoice_id, i.issue_date, s.name AS supplier, i.invoice_number,
               i.net_total_cents / 100.0 AS net_eur,
               i.vat_total_cents / 100.0 AS vat_eur,
               i.gross_total_cents / 100.0 AS gross_eur
        FROM invoices i JOIN suppliers s USING (supplier_id)
        ORDER BY i.issue_date DESC, i.invoice_id DESC
        """,
        conn,
    )
    st.dataframe(invoices, hide_index=True, width="stretch")

    if not invoices.empty:
        labels = dict(zip(invoices["invoice_id"],
                          invoices["invoice_number"] + " - " + invoices["supplier"]))
        selected = st.selectbox("Show lines of invoice", invoices["invoice_id"],
                                format_func=labels.get)
        lines = pd.read_sql_query(
            """
            SELECT p.sku, p.name, l.quantity, p.unit,
                   l.unit_price_cents / 100.0 AS unit_price_eur,
                   v.rate_percent AS vat_pct,
                   l.net_amount_cents / 100.0 AS net_eur,
                   l.vat_amount_cents / 100.0 AS vat_eur
            FROM invoice_lines l
            JOIN products p ON p.product_id = l.product_id
            JOIN vat_rates v ON v.vat_rate_id = l.vat_rate_id
            WHERE l.invoice_id = ?
            """,
            conn,
            params=(int(selected),),
        )
        st.dataframe(lines, hide_index=True, width="stretch")

    st.subheader("New invoice")
    suppliers = pd.read_sql_query("SELECT afm, name FROM suppliers ORDER BY name", conn)
    products = pd.read_sql_query("SELECT sku, name FROM products ORDER BY sku", conn)
    supplier_names = dict(zip(suppliers["afm"], suppliers["name"]))
    product_options = [f"{sku} | {name}" for sku, name in zip(products["sku"], products["name"])]

    with st.form("new_invoice"):
        afm = st.selectbox("Supplier", suppliers["afm"], format_func=supplier_names.get)
        number = st.text_input("Invoice number")
        issue_date = st.date_input("Issue date", value=date.today(), max_value=date.today())
        line_input = st.data_editor(
            pd.DataFrame({"product": pd.Series(dtype="str"),
                          "quantity": pd.Series(dtype="float"),
                          "unit_price_eur": pd.Series(dtype="float")}),
            num_rows="dynamic",
            width="stretch",
            column_config={
                "product": st.column_config.SelectboxColumn("Product", options=product_options),
                "quantity": st.column_config.NumberColumn("Quantity"),
                "unit_price_eur": st.column_config.NumberColumn("Unit price (EUR, net)",
                                                                format="%.2f"),
            },
        )
        submitted = st.form_submit_button("Save invoice")

    if submitted:
        rows = line_input.dropna(how="all")
        invoice = {
            "supplier_afm": afm,
            "invoice_number": number,
            "issue_date": issue_date.isoformat(),
            "lines": [
                {"sku": row["product"].split(" | ")[0] if pd.notna(row["product"]) else None,
                 "quantity": float(row["quantity"]) if pd.notna(row["quantity"]) else None,
                 "unit_price_cents": to_cents(row["unit_price_eur"])
                 if pd.notna(row["unit_price_eur"]) else None}
                for _, row in rows.iterrows()
            ],
        }
        try:
            create_invoice(conn, invoice)
            st.success(f"Invoice {number} saved, stock updated.")
        except ValidationError as e:
            show_errors(e)


def expenses_page(conn):
    st.header("Expenses")
    expenses = pd.read_sql_query(
        """
        SELECT e.expense_date, e.category, e.description,
               e.net_amount_cents / 100.0 AS net_eur, v.rate_percent AS vat_pct
        FROM expenses e LEFT JOIN vat_rates v USING (vat_rate_id)
        ORDER BY e.expense_date DESC, e.expense_id DESC
        """,
        conn,
    )
    st.dataframe(expenses, hide_index=True, width="stretch")

    st.subheader("New expense")
    vat_rates = {None: "No VAT"}
    vat_rates.update({r["vat_rate_id"]: f"{r['rate_percent']}%"
                      for r in conn.execute("SELECT vat_rate_id, rate_percent FROM vat_rates")})
    with st.form("new_expense"):
        expense_date = st.date_input("Date", value=date.today(), max_value=date.today())
        category = st.text_input("Category", placeholder="e.g. Electricity")
        description = st.text_input("Description (optional)")
        amount = st.text_input("Net amount (EUR)", placeholder="e.g. 120.50")
        vat_rate_id = st.selectbox("VAT", list(vat_rates), format_func=vat_rates.get)
        submitted = st.form_submit_button("Save expense")

    if submitted:
        cents = to_cents(amount)
        if cents is None:
            st.error(f"net amount: '{amount}' is not a valid amount")
            return
        try:
            add_expense(conn, expense_date.isoformat(), category, cents,
                        description=description or None, vat_rate_id=vat_rate_id)
            st.success("Expense saved.")
        except ValidationError as e:
            show_errors(e)


def stock_page(conn):
    st.header("Stock")
    only_low = st.checkbox("Only products at or below reorder level")
    st.dataframe(stock.stock_levels(conn, only_below_reorder=only_low),
                 hide_index=True, width="stretch")

    st.subheader("Record movement")
    st.caption("IN movements are created automatically from invoices. "
               "OUT = usage, ADJUST = correction (+/-).")
    skus = [r["sku"] for r in conn.execute("SELECT sku FROM products ORDER BY sku")]
    with st.form("new_movement"):
        sku = st.selectbox("Product", skus)
        movement_type = st.radio("Type", ["OUT", "ADJUST"], horizontal=True)
        quantity = st.number_input("Quantity", value=0.0, step=1.0, format="%.3f")
        movement_date = st.date_input("Date", value=date.today(), max_value=date.today())
        note = st.text_input("Note (optional)")
        submitted = st.form_submit_button("Save movement")

    if submitted:
        try:
            stock.record_movement(conn, sku, movement_date.isoformat(), movement_type,
                                  quantity, note=note or None)
            st.success("Movement saved.")
        except ValidationError as e:
            show_errors(e)

    st.subheader("Latest movements")
    st.dataframe(stock.recent_movements(conn), hide_index=True, width="stretch")


def import_export_page(conn):
    st.header("Import / Export invoices")

    st.subheader("Import")
    uploaded = st.file_uploader("JSON or XML file (see samples/ folder)", type=["json", "xml"])
    if uploaded is not None and st.button("Import file"):
        fmt = uploaded.name.rsplit(".", 1)[-1].lower()
        try:
            report = import_export.import_invoices(conn, uploaded.getvalue().decode("utf-8"), fmt)
        except ValueError as e:
            st.error(f"Could not read file: {e}")
        else:
            imported = sum(r["status"] == "imported" for r in report)
            st.write(f"Imported {imported} of {len(report)} invoices.")
            st.dataframe(pd.DataFrame(report), hide_index=True, width="stretch")

    st.subheader("Export")
    fmt = st.radio("Format", ["json", "xml"], horizontal=True)
    col1, col2 = st.columns(2)
    date_from = col1.date_input("From", value=date(2026, 1, 1))
    date_to = col2.date_input("To", value=date.today())
    export = import_export.export_json if fmt == "json" else import_export.export_xml
    content = export(conn, date_from.isoformat(), date_to.isoformat())
    st.download_button("Download", content, file_name=f"invoices_export.{fmt}",
                       mime="application/json" if fmt == "json" else "application/xml")


def reports_page(conn):
    st.header("Reports")
    name = st.selectbox("Report", list(reports.REPORTS))
    st.dataframe(reports.run_report(conn, name), hide_index=True, width="stretch")

    st.subheader("Power BI")
    out_dir = PROJECT_DIR / "exports"
    if st.button("Export CSV files for Power BI"):
        paths = reports.export_for_powerbi(conn, out_dir)
        st.success(f"{len(paths)} files written to {out_dir}")


# ---------- main ----------

st.title("Invoice, Expense & Stock Manager")
st.caption("Prototype with synthetic data for a fictional cafe-restaurant.")

if not DB_PATH.exists():
    st.info("No database found.")
    if st.button("Create demo database"):
        import seed_data
        seed_data.main()
        st.rerun()
    st.stop()

PAGES = {
    "Invoices": invoices_page,
    "Expenses": expenses_page,
    "Stock": stock_page,
    "Import / Export": import_export_page,
    "Reports": reports_page,
}
page = st.sidebar.radio("Page", list(PAGES))
connection = get_connection()
try:
    PAGES[page](connection)
finally:
    connection.close()
