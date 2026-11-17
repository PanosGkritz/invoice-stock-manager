# Data mapping: invoice import / export

Invoices can be imported and exported as JSON or XML. The file formats use their
own field names, which are mapped to the database in `import_export.py`:

1. The file is read into a plain record (`read_json` / `read_xml`).
2. `map_invoice` converts the record to the internal format and collects format errors.
3. `create_invoice` validates the business rules and saves the invoice in one transaction.

Each invoice in a file is accepted or rejected on its own, and the import returns
a report with the reason for every rejection.

## Invoice header

| JSON field     | XML element     | Database column                            | Rules |
|----------------|-----------------|--------------------------------------------|-------|
| `supplier_vat` | `<SupplierVAT>` | `invoices.supplier_id` (lookup by `suppliers.afm`) | 9 digits, supplier must exist |
| `number`       | `<Number>`      | `invoices.invoice_number`                  | required, unique per supplier |
| `date`         | `<Date>`        | `invoices.issue_date`                      | `YYYY-MM-DD`, not in the future |

## Invoice lines (`lines` / `<Lines><Line>`)

| JSON field     | XML element     | Database column                              | Rules |
|----------------|-----------------|----------------------------------------------|-------|
| `product_code` | `<ProductCode>` | `invoice_lines.product_id` (lookup by `products.sku`) | product must exist |
| `quantity`     | `<Quantity>`    | `invoice_lines.quantity`                     | > 0, whole number for `pcs`, max 3 decimals |
| `unit_price`   | `<UnitPrice>`   | `invoice_lines.unit_price_cents` (euros x 100) | >= 0, max 2 decimals, `.` or `,` accepted |
| -              | -               | `invoice_lines.vat_rate_id`                  | copied from the product's current VAT rate |
| -              | -               | `invoice_lines.net_amount_cents`             | quantity x unit price, rounded half-up |
| -              | -               | `invoice_lines.vat_amount_cents`             | net x VAT rate, rounded half-up |
| -              | -               | `stock_movements` (type `IN`)                | one movement per line |

## Totals (`totals` / `<Totals>`, optional)

| JSON field | XML element | Database column                | Rules |
|------------|-------------|--------------------------------|-------|
| `net`      | `<Net>`     | `invoices.net_total_cents`     | must equal the sum of line net amounts |
| `vat`      | `<VAT>`     | `invoices.vat_total_cents`     | must equal the sum of line VAT amounts |
| `gross`    | `<Gross>`   | `invoices.gross_total_cents`   | must equal net + VAT |

Totals are always calculated by the application. When a file declares totals,
they are compared with the calculated ones and the invoice is rejected if they differ.

## Example files

See `samples/invoices_sample.json` and `samples/invoices_sample.xml`. Each contains
one valid invoice and one invalid invoice, to show the import report.

## Export

Export writes the same formats, so an exported file can be imported again
(this round trip is covered by `tests/test_import_export.py`). Amounts are
written as strings with two decimals (`"12.50"`) to avoid float rounding.
