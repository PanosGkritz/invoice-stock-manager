"""Fill the database with reproducible synthetic data for a fictional cafe-restaurant.

All names, VAT numbers and prices are made up. VAT categories are illustrative,
not an official tax classification. The data goes through the same functions
as the app (operations.py, stock.py), so it is validated like any other input.
"""
import random
from datetime import date, timedelta

from db import DB_PATH, create_database, get_connection
from operations import add_expense, add_product, add_supplier, create_invoice
from stock import current_stock, record_movement

START = date(2026, 6, 1)
END = date(2026, 11, 15)

# key, name, afm, invoice number prefix
SUPPLIERS = [
    ("dairy",  "Galaktokomika Voreiou AE", "990000011", "GV"),
    ("coffee", "Kokkos Kafe OE",           "990000022", "KK"),
    ("bakery", "Fournos Anatoli",          "990000033", "FA"),
    ("meat",   "Kreopoleio Marinos",       "990000044", "KM"),
    ("veg",    "Lachanika Agros",          "990000055", "LA"),
    ("drinks", "Pota Aigaiou EPE",         "990000066", "PA"),
]

# vat_rate_id: 1 = 24%, 2 = 13%, 3 = 6% (see schema.sql)
# sku, name, unit, vat_rate_id, supplier key,
# base price in cents, typical order qty, typical weekly use, reorder level
PRODUCTS = [
    ("DAI-01", "Fresh milk",          "lt",  2, "dairy",   120,  60,  20,  15),
    ("DAI-02", "Strained yogurt",     "kg",  2, "dairy",   450,  15,   5,   4),
    ("DAI-03", "Feta cheese",         "kg",  2, "dairy",   950,  12,   4,   3),
    ("DAI-04", "Cooking cream",       "lt",  2, "dairy",   380,  10,   3,   3),
    ("DAI-05", "Butter",              "kg",  2, "dairy",   900,   6,   2,   2),
    ("COF-01", "Espresso beans",      "kg",  1, "coffee", 1800,  12,   4,   3),
    ("COF-02", "Filter coffee",       "kg",  1, "coffee", 1400,   6,   2,   2),
    ("COF-03", "Sugar",               "kg",  2, "coffee",  110,  15,   5,   4),
    ("COF-04", "Paper cups 12oz",     "pcs", 1, "coffee",    8, 1500, 500, 400),
    ("COF-05", "Napkins (pack)",      "pcs", 1, "coffee",  150,  30,  10,   8),
    ("BAK-01", "Village bread",       "pcs", 3, "bakery",  150,  90,  30,  20),
    ("BAK-02", "Sesame bread rings",  "pcs", 3, "bakery",   40, 150,  50,  30),
    ("BAK-03", "Croissant",           "pcs", 2, "bakery",   60, 150,  50,  30),
    ("BAK-04", "Toast bread",         "pcs", 3, "bakery",  220,  30,  10,   8),
    ("MEA-01", "Chicken fillet",      "kg",  2, "meat",    750,  30,  10,   8),
    ("MEA-02", "Minced beef",         "kg",  2, "meat",   1100,  24,   8,   6),
    ("MEA-03", "Bacon",               "kg",  2, "meat",   1300,   9,   3,   2),
    ("VEG-01", "Tomatoes",            "kg",  2, "veg",     180,  45,  15,  10),
    ("VEG-02", "Potatoes",            "kg",  2, "veg",      90,  60,  20,  15),
    ("VEG-03", "Lettuce",             "pcs", 2, "veg",      80,  60,  20,  15),
    ("VEG-04", "Lemons",              "kg",  2, "veg",     160,  12,   4,   3),
    ("VEG-05", "Olive oil",           "lt",  2, "veg",     750,  15,   5,   4),
    ("DRI-01", "Water 500ml",         "pcs", 2, "drinks",   20, 360, 120, 100),
    ("DRI-02", "Soft drink 330ml",    "pcs", 1, "drinks",   45, 240,  80,  60),
    ("DRI-03", "Orange juice",        "lt",  2, "drinks",  280,  30,  10,   8),
    ("DRI-04", "Beer 330ml",          "pcs", 1, "drinks",   90, 240,  80,  60),
    ("DRI-05", "White wine",          "lt",  1, "drinks",  600,  15,   5,   4),
]

# category, net amount in cents, vat_rate_id (None = no VAT)
MONTHLY_EXPENSES = [
    ("Rent",        150000, None),
    ("Electricity",  42000, 3),
    ("Water",         6500, 2),
    ("Telecom",       4500, 1),
    ("Accountant",   25000, 1),
]


def round_qty(qty, unit):
    """Pieces are whole numbers, kg/lt keep one decimal."""
    return round(qty) if unit == "pcs" else round(qty, 1)


def seed(conn):
    random.seed(42)  # same data on every run

    for key, name, afm, _prefix in SUPPLIERS:
        add_supplier(conn, name, afm, email=f"orders@{key}.example")

    products = {}
    for sku, name, unit, vat_id, supplier, price, order_qty, weekly_use, reorder in PRODUCTS:
        product_id = add_product(conn, sku, name, unit, vat_id, reorder)
        products[sku] = {"id": product_id, "unit": unit, "supplier": supplier,
                         "price": price, "order_qty": order_qty, "weekly_use": weekly_use}
        # opening stock, so the first weeks have something to consume
        record_movement(conn, sku, START.isoformat(), "ADJUST", order_qty, note="Opening stock")

    afm_of = {key: afm for key, _name, afm, _prefix in SUPPLIERS}
    prefix_of = {key: prefix for key, _name, _afm, prefix in SUPPLIERS}
    invoice_counter = {key: 0 for key in afm_of}

    week_start = START
    while week_start <= END:
        # 2-3 purchase invoices this week
        for day in sorted(random.sample(range(6), k=random.randint(2, 3))):
            issue_date = week_start + timedelta(days=day)
            if issue_date > END:
                continue
            supplier = random.choice(list(afm_of))
            own_products = [sku for sku, p in products.items() if p["supplier"] == supplier]
            chosen = random.sample(own_products, k=min(len(own_products), random.randint(2, 6)))
            invoice_counter[supplier] += 1
            create_invoice(conn, {
                "supplier_afm": afm_of[supplier],
                "invoice_number": f"{prefix_of[supplier]}-{invoice_counter[supplier]:05d}",
                "issue_date": issue_date.isoformat(),
                "lines": [
                    {"sku": sku,
                     "quantity": round_qty(products[sku]["order_qty"] * random.uniform(0.8, 1.2),
                                           products[sku]["unit"]),
                     "unit_price_cents": round(products[sku]["price"] * random.uniform(0.9, 1.1))}
                    for sku in chosen
                ],
            })

        # weekly consumption, never more than what is in stock
        usage_date = min(week_start + timedelta(days=6), END).isoformat()
        for sku, p in products.items():
            wanted = p["weekly_use"] * random.uniform(0.7, 1.3)
            used = round_qty(min(wanted, current_stock(conn, p["id"])), p["unit"])
            if used > 0:
                record_movement(conn, sku, usage_date, "OUT", used, note="Weekly usage")
        week_start += timedelta(days=7)

    month = START
    while month <= END:
        for category, amount, vat_id in MONTHLY_EXPENSES:
            # bills vary a little each month, rent does not
            net = amount if category == "Rent" else round(amount * random.uniform(0.85, 1.15))
            add_expense(conn, month.replace(day=5).isoformat(), category, net,
                        description=f"{category} {month:%m/%Y}", vat_rate_id=vat_id)
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)  # next month


def main(db_path=DB_PATH):
    create_database(db_path)
    conn = get_connection(db_path)
    try:
        seed(conn)
        for table in ["suppliers", "products", "invoices", "invoice_lines",
                      "expenses", "stock_movements"]:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table}: {count}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
