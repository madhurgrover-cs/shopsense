"""The SQL safety check for "Ask your data" (app/ai/sql_guard.py). Pure parsing: no
database or AI needed. Each blocked example is a real way an AI-written (or tricked)
query could try to write data or read something private."""

import pytest

from app.ai import data_schema, sql_guard
from app.exceptions import SqlRejectedError

check = sql_guard.check_sql


def flat(sql: str) -> str:
    """The checked SQL on one line, upper-case, for easy asserts."""
    return " ".join(sql.split()).upper()


# ---------------------------------------------------------------------------
# Allowed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sql", [
    "SELECT name, price FROM products WHERE is_active ORDER BY price DESC",
    "SELECT c.name, SUM(oi.qty * oi.unit_price) AS revenue FROM order_items oi "
    "JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id "
    "GROUP BY c.name",
    "WITH recent AS (SELECT * FROM orders WHERE created_at >= now() - interval '30 days') "
    "SELECT status, COUNT(*) FROM recent GROUP BY status",
    "SELECT name FROM categories UNION SELECT name FROM products",
    "SELECT * FROM v_top_products",
    "SELECT id, name, email FROM users WHERE role = 'customer'",
    "SELECT COUNT(*) FROM users",
    "SELECT u.name, COUNT(o.id) FROM users u JOIN orders o ON o.user_id = u.id GROUP BY u.name",
    "SELECT name FROM public.products",
    "SELECT d::date AS day FROM generate_series(now() - interval '6 days', now(), "
    "interval '1 day') AS d",
    "SELECT age(created_at) FROM orders",
    "SELECT name FROM products WHERE name ILIKE '%shirt%' AND description LIKE '10:30%'",
    "SELECT 1;",  # one trailing semicolon is still one statement
])
def test_safe_queries_pass(sql):
    assert flat(check(sql)).startswith(("SELECT", "WITH"))


def test_limit_is_added_when_missing():
    assert flat(check("SELECT name FROM products")).endswith("LIMIT 201")


def test_large_limit_is_lowered():
    assert flat(check("SELECT name FROM products LIMIT 5000")).endswith("LIMIT 201")
    assert flat(check("SELECT name FROM products FETCH FIRST 900 ROWS ONLY")).endswith(
        "LIMIT 201")


def test_small_limit_is_kept():
    assert flat(check("SELECT name FROM products LIMIT 10")).endswith("LIMIT 10")


def test_limit_applies_to_a_whole_union():
    assert flat(check("SELECT name FROM categories UNION SELECT name FROM products")) \
        .endswith("UNION SELECT NAME FROM PRODUCTS LIMIT 201")


def test_comments_are_removed():
    sql = check("SELECT name /* note */ FROM products -- the end")
    assert "/*" not in sql and "--" not in sql and "note" not in sql


# ---------------------------------------------------------------------------
# Blocked
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sql, reason", [
    # not a single SELECT
    ("", "exactly one"),
    ("SELECT 1; SELECT 2", "exactly one"),
    ("SELECT 1; DROP TABLE orders", "exactly one"),
    ("SELEC name FRM products", "not valid SQL"),
    ("DELETE FROM orders", "only SELECT"),
    ("UPDATE products SET price = 1", "only SELECT"),
    ("INSERT INTO categories (name) VALUES ('x')", "only SELECT"),
    ("DROP TABLE orders", "only SELECT"),
    ("TRUNCATE orders", "only SELECT"),
    ("SET ROLE neondb_owner", "only SELECT"),
    ("GRANT SELECT ON users TO public", "only SELECT"),
    # writes / locks hidden inside a SELECT
    ("WITH gone AS (DELETE FROM orders RETURNING id) SELECT COUNT(*) FROM gone",
     "change or lock"),
    ("SELECT name INTO TEMP copy FROM products", "change or lock"),
    ("SELECT id FROM inventory FOR UPDATE", "change or lock"),
    # private columns, however they are written
    ("SELECT password_hash FROM users", "private"),
    ('SELECT "password_hash" FROM users', "private"),
    ("SELECT name FROM users WHERE PASSWORD_HASH LIKE '$2b%'", "private"),
    ("SELECT failed_logins, locked_until FROM users", "private"),
    ("SELECT name FROM users ORDER BY locked_until", "private"),
    ("SELECT 1 AS password_hash", "private"),
    # every column of users without naming them
    ("SELECT * FROM users", "list the columns"),
    ("SELECT u.* FROM users u", "list the columns"),
    ("SELECT * FROM orders o JOIN users u ON u.id = o.user_id", "list the columns"),
    ("SELECT u FROM users u", "whole users row"),
    ("SELECT users FROM users", "whole users row"),
    ("SELECT d FROM users AS u(a, b, c, d)", "renamed"),
    # outside the store's tables
    ("SELECT * FROM pg_catalog.pg_roles", "outside"),
    ("SELECT * FROM information_schema.columns", "outside"),
    ("SELECT * FROM pg_shadow", "not available"),
    ("SELECT * FROM product_embeddings", "not available"),
    ("SELECT * FROM alembic_version", "not available"),
    # dangerous functions
    ("SELECT set_config('role', 'neondb_owner', true)", "set_config"),
    ("SELECT pg_sleep(60)", "pg_sleep"),
    ("SELECT pg_read_file('/etc/passwd')", "pg_read_file"),
    ("SELECT query_to_xml('SELECT password_hash FROM users', true, true, '')", "query_to_xml"),
    ("SELECT * FROM dblink('host=evil', 'SELECT 1') AS t(x int)", "dblink"),
    ("SELECT to_jsonb(o) FROM orders o", "to_jsonb"),
    ("SELECT to_jsonb(u) FROM users u", "whole users row"),
])
def test_unsafe_queries_are_blocked(sql, reason):
    with pytest.raises(SqlRejectedError) as caught:
        check(sql)
    assert reason in str(caught.value)
    assert caught.value.sql == sql  # the original, so the admin can see what was blocked


def test_schema_description_never_mentions_private_columns():
    text = data_schema.SCHEMA_DESCRIPTION.lower()
    for column in data_schema.BLOCKED_COLUMNS:
        assert column not in text


def test_schema_description_covers_every_allowed_table():
    for table in data_schema.ALLOWED_TABLES:
        assert f"{table}(" in data_schema.SCHEMA_DESCRIPTION, table
