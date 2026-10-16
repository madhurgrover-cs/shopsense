""""Ask your data" (admin only): a question in plain English -> SQL -> table + summary.

Flow of ask():
    question --Gemini--> SQL --sql_guard--> safe SQL --read-only transaction--> rows
             --Gemini--> one-sentence summary

Safety layers, outermost first (any one of them alone stops a write):
1. Only admins can call this (require_admin).
2. sql_guard parses the SQL: one SELECT, allowed tables only, no private columns, no
   dangerous functions, LIMIT 200 (see app/ai/sql_guard.py).
3. The transaction is READ ONLY, with a 5-second statement timeout.
4. The query runs as the database role shopsense_readonly, which can only SELECT the
   allowed tables and the non-private columns of users (migration 0002).

Every question an admin asks is written to the audit log with its outcome (answered,
blocked or failed), so unusual questions can be reviewed later.
"""

import logging

import psycopg

from app.ai import sql_guard, text_to_sql
from app.db import get_session
from app.exceptions import AskDataError, SqlRejectedError, ValidationError
from app.repositories import query_repository
from app.services import audit_service
from app.services.auth_service import require_admin
from app.services.dto import DataAnswer
from app.services.user_session import UserSession

log = logging.getLogger(__name__)

MAX_ROWS = sql_guard.MAX_ROWS   # 200
QUERY_TIMEOUT_MS = 5_000
MAX_QUESTION_LENGTH = 500

# Shown as one-click example buttons under the question box (for the demo).
EXAMPLE_QUESTIONS = [
    "Which category made the most revenue last month?",
    "Top 5 customers by total spent",
    "How many orders were cancelled this month?",
    "Which products have no reviews?",
]


def ask(admin: UserSession, question: str) -> DataAnswer:
    require_admin(admin)
    question = " ".join((question or "").split())
    if not question:
        raise ValidationError("Type a question first.")
    if len(question) > MAX_QUESTION_LENGTH:
        raise ValidationError(f"Please keep the question under {MAX_QUESTION_LENGTH} characters.")

    try:
        answer = _answer(question)
    except SqlRejectedError as error:
        _record_question(admin, question, f"blocked: {error}")
        raise
    except Exception as error:
        # AskDataError has a readable message; anything else is logged by its type only.
        reason = str(error) if isinstance(error, AskDataError) else type(error).__name__
        _record_question(admin, question, f"failed: {reason}")
        raise
    _record_question(admin, question, f"answered: {answer.row_count_text}")
    return answer


def _answer(question: str) -> DataAnswer:
    generated = text_to_sql.generate_sql(question)
    sql = sql_guard.check_sql(generated)        # raises SqlRejectedError if unsafe
    columns, rows = run_query(sql)
    cut_off = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    return DataAnswer(question, sql, columns, rows, cut_off,
                      _summary(question, columns, rows, cut_off))


def _record_question(admin: UserSession, question: str, outcome: str) -> None:
    """Audit entry for one question, in its own small transaction. (The query itself ran
    in a read-only transaction that is always rolled back, so it can't hold the entry.)
    If the entry can't be written, e.g. the database is unreachable, the admin still
    gets the answer or the original error: the log is not worth hiding them for."""
    try:
        with get_session() as session:
            audit_service.record_admin_action(
                session, admin, audit_service.ASK, audit_service.DATA,
                details=f"question={question!r} -> {outcome}")
    except Exception:
        log.warning("Couldn't write the audit entry for an Ask your data question",
                    exc_info=True)


def run_query(sql: str) -> tuple[list[str], list[tuple]]:
    """Run already-checked SQL in a read-only, time-limited, low-privilege transaction.
    Returns up to MAX_ROWS + 1 rows (the extra one shows the result was cut off)."""
    try:
        with get_session() as session:
            try:
                try:
                    query_repository.begin_read_only(session, QUERY_TIMEOUT_MS)
                except psycopg.errors.InvalidParameterValue:  # role doesn't exist
                    raise AskDataError("The read-only database role is missing. Run "
                                       "'alembic upgrade head' once to create it.") from None
                return query_repository.fetch(session, sql, MAX_ROWS + 1)
            finally:
                # Nothing to keep. Rolling back also ends READ ONLY, the timeout and the
                # role switch (they were SET LOCAL, i.e. for this transaction only).
                session.rollback()
    except psycopg.errors.QueryCanceled:
        raise AskDataError(f"The query took longer than {QUERY_TIMEOUT_MS // 1000} seconds "
                           "and was stopped. Try a simpler or narrower question.",
                           sql=sql) from None
    except psycopg.OperationalError:
        log.warning("Database connection failed during Ask your data", exc_info=True)
        raise AskDataError("Couldn't reach the database. Check your internet connection "
                           "and try again.", sql=sql) from None
    except psycopg.Error as error:
        # The SQL itself was wrong (unknown column, bad type, permission denied, ...).
        # The database's own one-line message helps the admin rephrase the question.
        detail = (error.diag.message_primary or str(error)).strip()
        raise AskDataError(f"The database couldn't run this query: {detail}",
                           sql=sql) from None


def _summary(question: str, columns: list[str], rows: list[tuple], cut_off: bool) -> str:
    if not rows:
        return "No data matched this question."  # no need to ask the AI
    try:
        return text_to_sql.summarize(question, columns, rows, cut_off)
    except AskDataError as error:
        # The table is the real answer; a missing summary shouldn't hide it.
        log.warning("Summary failed: %s", error)
        found = f"more than {MAX_ROWS}" if cut_off else str(len(rows))
        return f"Found {found} rows. (The AI summary isn't available right now.)"
