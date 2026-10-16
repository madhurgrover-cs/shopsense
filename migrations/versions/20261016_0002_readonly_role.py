"""Read-only database role for "Ask your data".

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-16

AI-written SQL runs as this role (query_repository does SET LOCAL ROLE inside a
read-only transaction). The role:
- is NOLOGIN: nobody can connect with it, it has no password. The app's own user
  switches to it for one transaction and back.
- may SELECT the store's tables and views, nothing else (no INSERT/UPDATE/DELETE).
- on users may only read the non-private columns: password_hash, failed_logins and
  locked_until are not granted, so "SELECT password_hash FROM users" or even
  "SELECT * FROM users" fails with "permission denied".
- gets nothing on product_embeddings or alembic_version.

Neon allows this: its owner role (neondb_owner) has CREATEROLE. Since PostgreSQL 16 the
creator of a role must still be GRANTed it before it may SET ROLE to it, hence the last
GRANT. The table list here must match app/ai/data_schema.py (a test checks this).
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "shopsense_readonly"

READABLE = [
    "addresses", "audit_log", "categories", "products", "inventory", "carts", "cart_items",
    "coupons", "orders", "order_items", "order_status_history", "payments", "reviews",
    "v_sales_by_category", "v_top_products", "v_daily_revenue", "v_low_stock",
]
USER_COLUMNS = ["id", "name", "email", "role", "created_at"]


def upgrade() -> None:
    # IF NOT EXISTS: roles belong to the whole Neon branch, not to one database, so the
    # role may already exist (e.g. after a downgrade that couldn't drop it).
    op.execute(f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} NOLOGIN;
            END IF;
        END $$;
    """)
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
    op.execute(f"GRANT SELECT ON {', '.join(READABLE)} TO {ROLE}")
    op.execute(f"GRANT SELECT ({', '.join(USER_COLUMNS)}) ON users TO {ROLE}")
    op.execute(f"GRANT {ROLE} TO CURRENT_USER")


def downgrade() -> None:
    op.execute(f"REVOKE {ROLE} FROM CURRENT_USER")
    op.execute(f"REVOKE SELECT ({', '.join(USER_COLUMNS)}) ON users FROM {ROLE}")
    op.execute(f"REVOKE SELECT ON {', '.join(READABLE)} FROM {ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {ROLE}")
