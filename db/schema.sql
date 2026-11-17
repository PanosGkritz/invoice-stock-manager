-- Invoice, Expense & Stock Manager - SQLite schema
--
-- Amounts are stored in cents (INTEGER), e.g. 12.50 EUR = 1250.
-- Quantities are REAL (e.g. 2.5 kg).
-- SQLite only enforces foreign keys when "PRAGMA foreign_keys = ON" is set
-- on the connection (see db.get_connection).

PRAGMA foreign_keys = ON;

CREATE TABLE vat_rates (
    vat_rate_id   INTEGER PRIMARY KEY,
    code          TEXT    NOT NULL UNIQUE,
    rate_percent  INTEGER NOT NULL UNIQUE
                  CHECK (rate_percent BETWEEN 0 AND 100),
    description   TEXT
);

INSERT INTO vat_rates (vat_rate_id, code, rate_percent, description) VALUES
    (1, 'STANDARD',      24, 'Standard rate'),
    (2, 'REDUCED',       13, 'Reduced rate'),
    (3, 'SUPER_REDUCED',  6, 'Super-reduced rate');

CREATE TABLE suppliers (
    supplier_id  INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    afm          TEXT NOT NULL UNIQUE                     -- Greek VAT number
                 CHECK (length(afm) = 9 AND afm NOT GLOB '*[^0-9]*'),
    email        TEXT,
    phone        TEXT,
    address      TEXT
);

CREATE TABLE products (
    product_id     INTEGER PRIMARY KEY,
    sku            TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    unit           TEXT NOT NULL CHECK (unit IN ('kg', 'lt', 'pcs')),
    vat_rate_id    INTEGER NOT NULL REFERENCES vat_rates(vat_rate_id),
    reorder_level  REAL NOT NULL DEFAULT 0 CHECK (reorder_level >= 0)
);

-- Purchase invoices only (no sales module).
-- "x IS date(x)" rejects anything that is not a valid YYYY-MM-DD date:
-- date() returns NULL for invalid input, and "= NULL" would let it pass.
CREATE TABLE invoices (
    invoice_id        INTEGER PRIMARY KEY,
    supplier_id       INTEGER NOT NULL REFERENCES suppliers(supplier_id),
    invoice_number    TEXT    NOT NULL,
    issue_date        TEXT    NOT NULL
                      CHECK (issue_date IS date(issue_date)),
    net_total_cents   INTEGER NOT NULL CHECK (net_total_cents >= 0),
    vat_total_cents   INTEGER NOT NULL CHECK (vat_total_cents >= 0),
    gross_total_cents INTEGER NOT NULL
                      CHECK (gross_total_cents = net_total_cents + vat_total_cents),
    UNIQUE (supplier_id, invoice_number)   -- same number is allowed for another supplier
);

CREATE TABLE invoice_lines (
    invoice_line_id   INTEGER PRIMARY KEY,
    invoice_id        INTEGER NOT NULL
                      REFERENCES invoices(invoice_id) ON DELETE CASCADE,
    product_id        INTEGER NOT NULL REFERENCES products(product_id),
    quantity          REAL    NOT NULL CHECK (quantity > 0),
    unit_price_cents  INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    -- VAT rate at the time of purchase, not affected by later product changes
    vat_rate_id       INTEGER NOT NULL REFERENCES vat_rates(vat_rate_id),
    net_amount_cents  INTEGER NOT NULL CHECK (net_amount_cents >= 0),
    vat_amount_cents  INTEGER NOT NULL CHECK (vat_amount_cents >= 0)
);

CREATE TABLE expenses (
    expense_id        INTEGER PRIMARY KEY,
    expense_date      TEXT    NOT NULL
                      CHECK (expense_date IS date(expense_date)),
    category          TEXT    NOT NULL,
    description       TEXT,
    net_amount_cents  INTEGER NOT NULL CHECK (net_amount_cents > 0),
    vat_rate_id       INTEGER REFERENCES vat_rates(vat_rate_id),   -- optional
    supplier_id       INTEGER REFERENCES suppliers(supplier_id)    -- optional
);

-- Sign convention: IN positive, OUT negative, ADJUST either (never 0).
-- Current stock = SUM(quantity) per product, see v_stock_levels.
CREATE TABLE stock_movements (
    movement_id      INTEGER PRIMARY KEY,
    product_id       INTEGER NOT NULL REFERENCES products(product_id),
    movement_date    TEXT    NOT NULL
                     CHECK (movement_date IS date(movement_date)),
    movement_type    TEXT    NOT NULL CHECK (movement_type IN ('IN', 'OUT', 'ADJUST')),
    quantity         REAL    NOT NULL,
    invoice_line_id  INTEGER UNIQUE      -- one invoice line creates at most one IN movement
                     REFERENCES invoice_lines(invoice_line_id) ON DELETE CASCADE,
    note             TEXT,
    CHECK (
        (movement_type = 'IN'     AND quantity > 0) OR
        (movement_type = 'OUT'    AND quantity < 0) OR
        (movement_type = 'ADJUST' AND quantity <> 0)
    ),
    CHECK (invoice_line_id IS NULL OR movement_type = 'IN')
);

-- Indexes on columns used in joins and date filters
CREATE INDEX idx_invoices_supplier    ON invoices(supplier_id);
CREATE INDEX idx_invoices_date        ON invoices(issue_date);
CREATE INDEX idx_lines_invoice        ON invoice_lines(invoice_id);
CREATE INDEX idx_lines_product        ON invoice_lines(product_id);
CREATE INDEX idx_expenses_date        ON expenses(expense_date);
CREATE INDEX idx_movements_product    ON stock_movements(product_id);

-- Current stock per product, calculated from the movements
CREATE VIEW v_stock_levels AS
SELECT
    p.product_id,
    p.sku,
    p.name,
    p.unit,
    -- ROUND hides float noise such as 5.3 + 4.1 - 9.4 = -0.0000000000000004,
    -- "+ 0.0" turns the resulting -0.0 into 0.0
    ROUND(COALESCE(SUM(m.quantity), 0), 3) + 0.0               AS current_stock,
    p.reorder_level,
    ROUND(COALESCE(SUM(m.quantity), 0), 3) <= p.reorder_level  AS below_reorder
FROM products p
LEFT JOIN stock_movements m ON m.product_id = p.product_id
GROUP BY p.product_id;
