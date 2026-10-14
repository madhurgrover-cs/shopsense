"""Initial schema: tables, constraints, indexes, pgvector, order-status trigger, report views.

Revision ID: 0001
Revises:
Create Date: 2026-10-14
"""
from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Raw SQL: trigger and views (CLAUDE.md: "write triggers/views as raw SQL")
# ---------------------------------------------------------------------------

# Logs every order status change into order_status_history.
# - On INSERT we log (NULL -> 'placed') so every order's timeline has a starting point.
#   We use NEW.created_at so seeded orders dated in the past get a matching history time.
# - On UPDATE we only log when the status actually changed (IS DISTINCT FROM also
#   handles NULLs correctly, unlike <>).
ORDER_STATUS_FUNCTION = """
CREATE OR REPLACE FUNCTION log_order_status_change() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO order_status_history (order_id, old_status, new_status, changed_at)
        VALUES (NEW.id, NULL, NEW.status, NEW.created_at);
    ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
        INSERT INTO order_status_history (order_id, old_status, new_status, changed_at)
        VALUES (NEW.id, OLD.status, NEW.status, now());
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# "UPDATE OF status" means the trigger doesn't even fire for updates to other columns.
ORDER_STATUS_TRIGGER = """
CREATE TRIGGER trg_order_status
AFTER INSERT OR UPDATE OF status ON orders
FOR EACH ROW EXECUTE FUNCTION log_order_status_change();
"""

# Cancelled orders are excluded from every sales figure.
# Category/product revenue = sum of qty * unit_price (before coupon discount, since a
# discount applies to the whole order, not to one product).

# LEFT JOINs keep categories with zero sales in the result (shown as 0).
# The parenthesised join filters to non-cancelled order lines *before* the LEFT JOIN,
# otherwise lines from cancelled orders would still be counted.
V_SALES_BY_CATEGORY = """
CREATE VIEW v_sales_by_category AS
SELECT
    c.id                                               AS category_id,
    c.name                                             AS category,
    COUNT(DISTINCT o.id)                               AS order_count,
    COALESCE(SUM(oi.qty), 0)                           AS units_sold,
    COALESCE(SUM(oi.qty * oi.unit_price), 0)::numeric(12, 2) AS revenue
FROM categories c
LEFT JOIN products p ON p.category_id = c.id
LEFT JOIN (order_items oi
           JOIN orders o ON o.id = oi.order_id AND o.status <> 'cancelled')
       ON oi.product_id = p.id
GROUP BY c.id, c.name;
"""

V_TOP_PRODUCTS = """
CREATE VIEW v_top_products AS
SELECT
    p.id                                         AS product_id,
    p.name                                       AS product,
    c.name                                       AS category,
    SUM(oi.qty)                                  AS units_sold,
    SUM(oi.qty * oi.unit_price)::numeric(12, 2)  AS revenue,
    RANK() OVER (ORDER BY SUM(oi.qty * oi.unit_price) DESC) AS revenue_rank
FROM order_items oi
JOIN orders o     ON o.id = oi.order_id AND o.status <> 'cancelled'
JOIN products p   ON p.id = oi.product_id
JOIN categories c ON c.id = p.category_id
GROUP BY p.id, p.name, c.name;
"""

# Days are counted in India time (the store's local time), not UTC, so an order placed
# at 1 a.m. IST lands on the correct calendar day.
V_DAILY_REVENUE = """
CREATE VIEW v_daily_revenue AS
SELECT
    (o.created_at AT TIME ZONE 'Asia/Kolkata')::date  AS day,
    COUNT(*)                                          AS order_count,
    SUM(o.subtotal)                                   AS gross,
    SUM(o.discount)                                   AS discount,
    SUM(o.total)                                      AS revenue
FROM orders o
WHERE o.status <> 'cancelled'
GROUP BY 1;
"""

# Threshold of 10 units; soft-deleted products are ignored.
V_LOW_STOCK = """
CREATE VIEW v_low_stock AS
SELECT
    p.id     AS product_id,
    p.name   AS product,
    c.name   AS category,
    i.stock
FROM inventory i
JOIN products p   ON p.id = i.product_id
JOIN categories c ON c.id = p.category_id
WHERE p.is_active AND i.stock < 10;
"""

VIEWS = ["v_sales_by_category", "v_top_products", "v_daily_revenue", "v_low_stock"]


def _created_at(name: str = "created_at") -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    # Note on op.f("ck_..."): our naming convention builds CHECK names as
    # "ck_<table>_<name>". op.f() marks a name as already final; without it Alembic
    # would apply the convention again and produce "ck_orders_ck_orders_status_valid".

    # pgvector must exist before any table uses the vector type. Neon supports it.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ---------------- users ----------------
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(100), nullable=False),
        sa.Column("role", sa.String(20), server_default="customer", nullable=False),
        sa.Column("failed_logins", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint("role IN ('admin', 'customer')", name=op.f("ck_users_role_valid")),
        sa.CheckConstraint("failed_logins >= 0", name=op.f("ck_users_failed_logins_non_negative")),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "addresses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("line1", sa.String(255), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("state", sa.String(100), nullable=False),
        sa.Column("pincode", sa.String(10), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_addresses"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_addresses_user_id_users", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_addresses_user_id", "addresses", ["user_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("entity", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_audit_log_user_id_users", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])

    # ---------------- catalog ----------------
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        sa.UniqueConstraint("name", name="uq_categories_name"),
    )

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        _created_at(),
        sa.CheckConstraint("price > 0", name=op.f("ck_products_price_positive")),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"],
            name="fk_products_category_id_categories", ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_products_category_id", "products", ["category_id"])
    op.create_index("ix_products_name", "products", ["name"])

    op.create_table(
        "inventory",
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("stock", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("stock >= 0", name=op.f("ck_inventory_stock_non_negative")),
        sa.PrimaryKeyConstraint("product_id", name="pk_inventory"),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"],
            name="fk_inventory_product_id_products", ondelete="CASCADE",
        ),
    )

    op.create_table(
        "product_embeddings",
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(384), nullable=False),
        sa.PrimaryKeyConstraint("product_id", name="pk_product_embeddings"),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"],
            name="fk_product_embeddings_product_id_products", ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_product_embeddings_embedding_hnsw",
        "product_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # ---------------- cart ----------------
    op.create_table(
        "carts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_carts"),
        sa.UniqueConstraint("user_id", name="uq_carts_user_id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_carts_user_id_users", ondelete="CASCADE"
        ),
    )

    op.create_table(
        "cart_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cart_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.CheckConstraint("qty > 0", name=op.f("ck_cart_items_qty_positive")),
        sa.PrimaryKeyConstraint("id", name="pk_cart_items"),
        sa.UniqueConstraint("cart_id", "product_id", name="uq_cart_items_cart_id_product_id"),
        sa.ForeignKeyConstraint(
            ["cart_id"], ["carts.id"], name="fk_cart_items_cart_id_carts", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"],
            name="fk_cart_items_product_id_products", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_cart_items_product_id", "cart_items", ["product_id"])

    # ---------------- orders ----------------
    op.create_table(
        "coupons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("percent_off", sa.Integer(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.CheckConstraint("percent_off BETWEEN 1 AND 90", name=op.f("ck_coupons_percent_off_range")),
        sa.PrimaryKeyConstraint("id", name="pk_coupons"),
        sa.UniqueConstraint("code", name="uq_coupons_code"),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default="placed", nullable=False),
        sa.Column("subtotal", sa.Numeric(10, 2), nullable=False),
        sa.Column("discount", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.Column("total", sa.Numeric(10, 2), nullable=False),
        sa.Column("coupon_code", sa.String(30), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "status IN ('placed', 'shipped', 'delivered', 'cancelled')",
            name=op.f("ck_orders_status_valid"),
        ),
        sa.CheckConstraint("subtotal >= 0", name=op.f("ck_orders_subtotal_non_negative")),
        sa.CheckConstraint("discount >= 0", name=op.f("ck_orders_discount_non_negative")),
        sa.CheckConstraint("total = subtotal - discount", name=op.f("ck_orders_total_matches")),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_orders_user_id_users", ondelete="RESTRICT"
        ),
    )
    op.create_index("ix_orders_user_id_created_at", "orders", ["user_id", "created_at"])

    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.CheckConstraint("qty > 0", name=op.f("ck_order_items_qty_positive")),
        sa.CheckConstraint("unit_price >= 0", name=op.f("ck_order_items_unit_price_non_negative")),
        sa.PrimaryKeyConstraint("id", name="pk_order_items"),
        sa.UniqueConstraint(
            "order_id", "product_id", name="uq_order_items_order_id_product_id"
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_order_items_order_id_orders", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"],
            name="fk_order_items_product_id_products", ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])

    op.create_table(
        "order_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("old_status", sa.String(20), nullable=True),
        sa.Column("new_status", sa.String(20), nullable=False),
        _created_at("changed_at"),
        sa.PrimaryKeyConstraint("id", name="pk_order_status_history"),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"],
            name="fk_order_status_history_order_id_orders", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_order_status_history_order_id", "order_status_history", ["order_id"])

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", sa.String(20), server_default="success", nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "method IN ('card', 'upi', 'cod', 'wallet')", name=op.f("ck_payments_method_valid")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'success', 'failed', 'refunded')",
            name=op.f("ck_payments_status_valid"),
        ),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_payments_amount_non_negative")),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_payments_order_id_orders", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])

    # ---------------- reviews ----------------
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        _created_at(),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name=op.f("ck_reviews_rating_range")),
        sa.CheckConstraint(
            "sentiment_score IS NULL OR sentiment_score BETWEEN -1 AND 1",
            name=op.f("ck_reviews_sentiment_range"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reviews"),
        sa.UniqueConstraint("user_id", "product_id", name="uq_reviews_user_id_product_id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_reviews_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"],
            name="fk_reviews_product_id_products", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_reviews_product_id", "reviews", ["product_id"])

    # ---------------- trigger + views (raw SQL) ----------------
    op.execute(ORDER_STATUS_FUNCTION)
    op.execute(ORDER_STATUS_TRIGGER)
    op.execute(V_SALES_BY_CATEGORY)
    op.execute(V_TOP_PRODUCTS)
    op.execute(V_DAILY_REVENUE)
    op.execute(V_LOW_STOCK)


def downgrade() -> None:
    # Reverse order: views and trigger depend on tables, children depend on parents.
    for view in reversed(VIEWS):
        op.execute(f"DROP VIEW IF EXISTS {view}")
    op.execute("DROP TRIGGER IF EXISTS trg_order_status ON orders")
    op.execute("DROP FUNCTION IF EXISTS log_order_status_change()")

    for table in [
        "reviews", "payments", "order_status_history", "order_items", "orders", "coupons",
        "cart_items", "carts", "product_embeddings", "inventory", "products", "categories",
        "audit_log", "addresses", "users",
    ]:
        op.drop_table(table)
    # The vector extension is left installed: dropping an extension is a database-wide
    # change and harmless to keep.
