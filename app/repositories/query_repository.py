"""Run an "Ask your data" query: SQL written by the AI, already checked by sql_guard.

Three database-level safety settings are switched on first, for this transaction only:

- SET TRANSACTION READ ONLY: PostgreSQL itself refuses any INSERT / UPDATE / DELETE /
  CREATE ... in this transaction, whatever the SQL says.
- SET LOCAL statement_timeout: a query running longer than the limit is cancelled by the
  server, so a heavy query can't keep the free-tier Neon database busy.
- SET LOCAL ROLE shopsense_readonly: from here on the query runs with the rights of a
  role that may only SELECT the store's tables, and on users only the non-private
  columns (created in migration 0002). Even a query the parser wrongly let through
  can't read password_hash: Postgres answers "permission denied".

"LOCAL" means "until this transaction ends", and the service always rolls back, so the
connection goes back to the pool as normal (read-write, the app's own role).
"""

from sqlalchemy.orm import Session

READ_ONLY_ROLE = "shopsense_readonly"


def _cursor(session: Session):
    """The raw psycopg cursor of the session's connection (same transaction).

    Why not session.execute(text(sql))? SQLAlchemy would treat ":word" in the SQL as a
    parameter (breaking e.g. '10:30'), and exec_driver_sql hands "%" to the driver as a
    placeholder (breaking ILIKE '%shirt%'). A raw cursor with no parameters runs the
    SQL text exactly as written.
    """
    return session.connection().connection.cursor()


def begin_read_only(session: Session, timeout_ms: int) -> None:
    """Make the rest of this transaction read-only, time-limited and low-privilege."""
    with _cursor(session) as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
        cursor.execute(f"SET LOCAL ROLE {READ_ONLY_ROLE}")


def fetch(session: Session, sql: str, max_rows: int) -> tuple[list[str], list[tuple]]:
    """Run the query; return (column names, at most max_rows rows)."""
    with _cursor(session) as cursor:
        cursor.execute(sql)
        if cursor.description is None:  # the statement returned no result table
            return [], []
        columns = [c.name for c in cursor.description]
        return columns, cursor.fetchmany(max_rows)
