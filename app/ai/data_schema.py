"""What "Ask your data" may see: the schema description sent to Gemini, and the lists
the SQL safety check (sql_guard.py) enforces.

The description is written by hand rather than read from the database because the
model needs MEANING, not just names: "cancelled orders are not sales", "times are UTC
but the store's days are in India time", "is_active = false means deleted". That is
what makes the generated SQL give the same numbers as the dashboard and reports.

Private columns are left out of the description AND blocked by sql_guard AND not
granted to the read-only database role (migration 0002). Keep all three in sync.
"""

# Never shown to the AI and never allowed in a query: the password hash, and the
# login-lockout state (which reveals who is being attacked / locked out).
BLOCKED_COLUMNS = frozenset({"password_hash", "failed_logins", "locked_until"})

# Every table and view a query may read. Not here: product_embeddings (384 numbers
# per product, meaningless to people) and alembic_version (migration bookkeeping).
ALLOWED_TABLES = frozenset({
    "users", "addresses", "audit_log", "categories", "products", "inventory",
    "carts", "cart_items", "coupons", "orders", "order_items", "order_status_history",
    "payments", "reviews",
    "v_sales_by_category", "v_top_products", "v_daily_revenue", "v_low_stock",
})

SCHEMA_DESCRIPTION = """\
PostgreSQL database of ShopSense, an online store in India. Money is in Indian rupees
(numeric(10,2)). Every timestamp is timestamptz stored in UTC; the store's calendar day is
India time, so group by day with (created_at AT TIME ZONE 'Asia/Kolkata')::date.
"Today" is CURRENT_DATE in India time: (now() AT TIME ZONE 'Asia/Kolkata')::date.
For "the last N days" compare timestamps directly: created_at >= now() - interval 'N days'
(don't compare created_at with an AT TIME ZONE value: that mixes UTC and India time).

TABLES
users(id, name, email, role, created_at)
  role is 'admin' or 'customer'. "Customers" means role = 'customer'.
addresses(id, user_id -> users.id, line1, city, state, pincode)
categories(id, name)
products(id, category_id -> categories.id, name, description, price, is_active, created_at)
  is_active = false means the product was deleted (soft delete): leave those out unless
  the question asks about deleted products.
inventory(product_id -> products.id, stock)   -- units in stock now, one row per product
carts(id, user_id -> users.id)                -- one cart per customer
cart_items(id, cart_id -> carts.id, product_id -> products.id, qty)  -- not yet ordered
coupons(id, code, percent_off, valid_until, is_active)
orders(id, user_id -> users.id, status, subtotal, discount, total, coupon_code, created_at)
  status is one of 'placed', 'shipped', 'delivered', 'cancelled'.
  total = subtotal - discount (discount comes from coupon_code).
  Cancelled orders are NOT sales: exclude status = 'cancelled' from revenue, sales and
  units-sold figures.
order_items(id, order_id -> orders.id, product_id -> products.id, qty, unit_price)
  unit_price is the price paid at purchase time (products.price may have changed since).
  Product or category revenue = SUM(qty * unit_price), before order discounts.
order_status_history(id, order_id -> orders.id, old_status, new_status, changed_at)
  one row per status change; old_status is NULL for the first row (order placed).
payments(id, order_id -> orders.id, method, amount, status, paid_at)
  method: 'card', 'upi', 'cod', 'wallet'. status: 'pending', 'success', 'failed', 'refunded'.
reviews(id, user_id -> users.id, product_id -> products.id, rating, comment,
        sentiment_score, created_at)
  rating 1-5 stars. sentiment_score is the AI's reading of the comment, from -1 (very
  negative) to +1 (very positive); NULL without a comment. Reviews below -0.3 are
  "flagged" as negative.
audit_log(id, user_id -> users.id, action, entity, entity_id, details, created_at)
  admin actions: action is 'create', 'update', 'delete', 'restore' or 'status_change';
  entity is 'product', 'order', 'coupon' or 'stock'.

VIEWS (ready-made totals over ALL time; cancelled orders already excluded)
v_sales_by_category(category_id, category, order_count, units_sold, revenue)
v_top_products(product_id, product, category, units_sold, revenue, revenue_rank)
v_daily_revenue(day, order_count, gross, discount, revenue)  -- day in India time,
  revenue = order totals after discounts
v_low_stock(product_id, product, category, stock)            -- active products, stock < 10
For a date range, query the tables (the views have no date filter except v_daily_revenue).
"""
