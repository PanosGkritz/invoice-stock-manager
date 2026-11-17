"""SQL reports shown in the app and exported as CSV for Power BI."""
from pathlib import Path

import pandas as pd

REPORTS = {
    "Purchases by month": """
        SELECT substr(issue_date, 1, 7)                 AS month,
               COUNT(*)                                 AS invoices,
               ROUND(SUM(net_total_cents)   / 100.0, 2) AS net_eur,
               ROUND(SUM(vat_total_cents)   / 100.0, 2) AS vat_eur,
               ROUND(SUM(gross_total_cents) / 100.0, 2) AS gross_eur
        FROM invoices
        GROUP BY month
        ORDER BY month
    """,
    "Purchases by supplier": """
        SELECT s.name                                       AS supplier,
               COUNT(i.invoice_id)                          AS invoices,
               ROUND(SUM(i.net_total_cents)   / 100.0, 2)   AS net_eur,
               ROUND(SUM(i.gross_total_cents) / 100.0, 2)   AS gross_eur,
               ROUND(100.0 * SUM(i.net_total_cents)
                     / (SELECT SUM(net_total_cents) FROM invoices), 1) AS share_pct
        FROM invoices i
        JOIN suppliers s USING (supplier_id)
        GROUP BY s.supplier_id
        ORDER BY net_eur DESC
    """,
    # Expenses store only the net amount, so their VAT is calculated here.
    "VAT by rate": """
        WITH vat_items AS (
            SELECT vat_rate_id, 'Invoices' AS source,
                   net_amount_cents AS net_cents, vat_amount_cents AS vat_cents
            FROM invoice_lines
            UNION ALL
            SELECT e.vat_rate_id, 'Expenses',
                   e.net_amount_cents, (e.net_amount_cents * v.rate_percent + 50) / 100
            FROM expenses e
            JOIN vat_rates v USING (vat_rate_id)
        )
        SELECT v.rate_percent                      AS vat_rate_pct,
               i.source,
               COUNT(*)                            AS items,
               ROUND(SUM(i.net_cents) / 100.0, 2)  AS net_eur,
               ROUND(SUM(i.vat_cents) / 100.0, 2)  AS vat_eur
        FROM vat_items i
        JOIN vat_rates v USING (vat_rate_id)
        GROUP BY v.rate_percent, i.source
        ORDER BY v.rate_percent DESC, i.source
    """,
    "Expenses by category": """
        SELECT substr(expense_date, 1, 7)               AS month,
               category,
               ROUND(SUM(net_amount_cents) / 100.0, 2)  AS net_eur
        FROM expenses
        GROUP BY month, category
        ORDER BY month, category
    """,
    # Stock valued at the average purchase cost of each product.
    "Stock value": """
        WITH avg_cost AS (
            SELECT product_id,
                   SUM(net_amount_cents) * 1.0 / SUM(quantity) AS cost_cents
            FROM invoice_lines
            GROUP BY product_id
        )
        SELECT s.sku, s.name, s.unit, s.current_stock,
               ROUND(c.cost_cents / 100.0, 2)                   AS avg_unit_cost_eur,
               ROUND(s.current_stock * c.cost_cents / 100.0, 2) AS stock_value_eur
        FROM v_stock_levels s
        LEFT JOIN avg_cost c USING (product_id)
        ORDER BY stock_value_eur DESC
    """,
}

# Detailed tables for Power BI, so the dashboard can slice by date, supplier, product.
POWERBI_TABLES = {
    "purchase_lines": """
        SELECT i.issue_date, s.name AS supplier, i.invoice_number,
               p.sku, p.name AS product, l.quantity, p.unit,
               l.unit_price_cents / 100.0                         AS unit_price_eur,
               v.rate_percent                                     AS vat_rate_pct,
               l.net_amount_cents / 100.0                         AS net_eur,
               l.vat_amount_cents / 100.0                         AS vat_eur,
               (l.net_amount_cents + l.vat_amount_cents) / 100.0  AS gross_eur
        FROM invoice_lines l
        JOIN invoices i  USING (invoice_id)
        JOIN suppliers s USING (supplier_id)
        JOIN products p  ON p.product_id = l.product_id
        JOIN vat_rates v ON v.vat_rate_id = l.vat_rate_id
        ORDER BY i.issue_date, i.invoice_id
    """,
    "expenses": """
        SELECT e.expense_date, e.category, e.description,
               e.net_amount_cents / 100.0 AS net_eur,
               v.rate_percent             AS vat_rate_pct
        FROM expenses e
        LEFT JOIN vat_rates v USING (vat_rate_id)
        ORDER BY e.expense_date
    """,
}


def run_report(conn, name):
    return pd.read_sql_query(REPORTS[name], conn)


def file_name(name):
    return name.lower().replace(" ", "_") + ".csv"


def export_for_powerbi(conn, out_dir):
    """Write every report and detailed table as CSV. Returns the written paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, sql in {**REPORTS, **POWERBI_TABLES}.items():
        path = out_dir / file_name(name)
        pd.read_sql_query(sql, conn).to_csv(path, index=False, encoding="utf-8")
        written.append(path)
    return written
