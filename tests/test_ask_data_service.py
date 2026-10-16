""""Ask your data": the service (against the real database, inside the rollback
fixture) with Gemini replaced by fakes, plus the Gemini error handling in text_to_sql.

The database-layer tests call run_query() directly with SQL the guard would block, to
prove the LAST lines of defence work on their own: if sql_guard ever missed something,
the read-only transaction and the read-only role would still stop it.
"""

from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors
from sqlalchemy import text

from app import config
from app.ai import data_schema, text_to_sql
from app.exceptions import (
    AskDataError, PermissionDeniedError, SqlRejectedError, ValidationError,
)
from app.models import Category
from app.repositories import query_repository
from app.services import ask_data_service, audit_service


@pytest.fixture
def fake_gemini(monkeypatch):
    """Gemini replaced: generate_sql returns whatever the test puts in fake.sql, and
    summarize records its calls. No network, no API key needed."""
    fake = SimpleNamespace(sql="SELECT 1", summaries=[], summary_error=None)

    def summarize(question, columns, rows, cut_off):
        fake.summaries.append((question, columns, rows, cut_off))
        if fake.summary_error:
            raise fake.summary_error
        return "Here is the answer."
    monkeypatch.setattr(text_to_sql, "generate_sql", lambda question: fake.sql)
    monkeypatch.setattr(text_to_sql, "summarize", summarize)
    return fake


# ---------------------------------------------------------------------------
# ask()
# ---------------------------------------------------------------------------

def test_ask_returns_rows_summary_and_checked_sql(admin, factory, fake_gemini):
    category = factory.category("Test Lamps")
    factory.product(price="250.00", category_id=category, name="Test Lamp A")
    factory.product(price="999.00", category_id=category, name="Test Lamp B")
    fake_gemini.sql = ("SELECT p.name, p.price FROM products p JOIN categories c "
                       "ON c.id = p.category_id WHERE c.name = 'Test Lamps' ORDER BY p.price")

    answer = ask_data_service.ask(admin, "  Which   lamps do we sell? ")

    assert answer.question == "Which lamps do we sell?"
    assert answer.columns == ["name", "price"]
    assert answer.rows == [("Test Lamp A", Decimal("250.00")), ("Test Lamp B", Decimal("999.00"))]
    assert answer.summary == "Here is the answer."
    assert not answer.cut_off
    assert "LIMIT 201" in answer.sql  # the checked SQL is what ran, and is shown
    assert fake_gemini.summaries[0][3] is False


def test_ask_is_admin_only(customer, fake_gemini):
    with pytest.raises(PermissionDeniedError):
        ask_data_service.ask(customer, "How many orders?")
    with pytest.raises(PermissionDeniedError):
        ask_data_service.ask(None, "How many orders?")


@pytest.mark.parametrize("question", ["", "   ", "x" * 501])
def test_ask_validates_the_question(admin, fake_gemini, question):
    with pytest.raises(ValidationError):
        ask_data_service.ask(admin, question)


def test_there_are_four_example_questions():
    assert len(ask_data_service.EXAMPLE_QUESTIONS) == 4


@pytest.mark.parametrize("attack", [
    "DROP TABLE orders",
    "UPDATE products SET price = 1",
    "SELECT name FROM products; DELETE FROM orders",       # two statements
    "SELECT name, password_hash FROM users",
])
def test_attacks_from_the_llm_are_blocked_and_never_run(admin, fake_gemini, monkeypatch,
                                                        factory, attack):
    """The (fake) AI returns something dangerous: it is rejected before reaching the
    database, the admin sees what was blocked, and the attempt is in the audit log."""
    ran = []
    monkeypatch.setattr(ask_data_service, "run_query", lambda sql: ran.append(sql))
    fake_gemini.sql = attack
    with pytest.raises(SqlRejectedError) as caught:
        ask_data_service.ask(admin, "Do something bad")
    assert caught.value.sql == attack
    assert ran == []
    [entry] = factory.audit_entries(audit_service.DATA)
    assert entry.action == audit_service.ASK and entry.user_id == admin.user_id
    assert entry.details.startswith("question='Do something bad' -> blocked:")


def test_answered_questions_are_audited(admin, fake_gemini, factory):
    fake_gemini.sql = "SELECT 1 AS one"
    ask_data_service.ask(admin, "One?")
    [entry] = factory.audit_entries(audit_service.DATA)
    assert entry.details == "question='One?' -> answered: 1 row"


def test_failed_questions_are_audited(admin, factory, monkeypatch):
    def offline(question):
        raise AskDataError("Couldn't reach Gemini.")
    monkeypatch.setattr(text_to_sql, "generate_sql", offline)
    with pytest.raises(AskDataError):
        ask_data_service.ask(admin, "How many orders?")
    [entry] = factory.audit_entries(audit_service.DATA)
    assert entry.details == "question='How many orders?' -> failed: Couldn't reach Gemini."


def test_invalid_questions_are_not_audited(admin, fake_gemini, factory):
    with pytest.raises(ValidationError):
        ask_data_service.ask(admin, "   ")
    assert factory.audit_entries(audit_service.DATA) == []


def test_audit_failure_does_not_hide_the_answer(admin, fake_gemini, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("audit table unavailable")
    monkeypatch.setattr(audit_service, "record_admin_action", broken)
    fake_gemini.sql = "SELECT 1 AS one"
    assert ask_data_service.ask(admin, "One?").rows == [(1,)]


def test_results_are_cut_off_at_200_rows(admin, fake_gemini):
    fake_gemini.sql = "SELECT n FROM generate_series(1, 500) AS n"
    answer = ask_data_service.ask(admin, "Count to 500")
    assert len(answer.rows) == 200
    assert answer.rows[-1] == (200,)
    assert answer.cut_off
    assert answer.row_count_text == "First 200 rows shown (there are more)"


def test_exactly_200_rows_is_not_cut_off(admin, fake_gemini):
    fake_gemini.sql = "SELECT n FROM generate_series(1, 200) AS n"
    answer = ask_data_service.ask(admin, "Count to 200")
    assert len(answer.rows) == 200 and not answer.cut_off


def test_no_rows_skips_the_ai_summary(admin, fake_gemini):
    fake_gemini.sql = "SELECT name FROM products WHERE price < 0"
    answer = ask_data_service.ask(admin, "Free products?")
    assert answer.rows == []
    assert answer.summary == "No data matched this question."
    assert fake_gemini.summaries == []


def test_failed_summary_still_returns_the_table(admin, fake_gemini):
    fake_gemini.sql = "SELECT 1 AS one"
    fake_gemini.summary_error = AskDataError("Gemini is busy.")
    answer = ask_data_service.ask(admin, "One?")
    assert answer.rows == [(1,)]
    assert answer.summary.startswith("Found 1 rows.")


def test_gemini_errors_reach_the_admin(admin, monkeypatch):
    def offline(question):
        raise AskDataError("Couldn't reach Gemini.")
    monkeypatch.setattr(text_to_sql, "generate_sql", offline)
    with pytest.raises(AskDataError, match="Couldn't reach Gemini"):
        ask_data_service.ask(admin, "How many orders?")


# ---------------------------------------------------------------------------
# run_query(): the database layers on their own (sql_guard bypassed on purpose)
# ---------------------------------------------------------------------------

def test_writes_are_refused_by_the_read_only_transaction(db_session):
    with pytest.raises(AskDataError, match="read-only transaction"):
        ask_data_service.run_query("INSERT INTO categories (name) VALUES ('Test Hacked')")
    assert db_session.query(Category).filter_by(name="Test Hacked").count() == 0


def test_private_columns_are_refused_by_the_read_only_role(db_session):
    for sql in ["SELECT password_hash FROM users", "SELECT * FROM users",
                "SELECT failed_logins FROM users", "SELECT * FROM product_embeddings"]:
        with pytest.raises(AskDataError, match="permission denied"):
            ask_data_service.run_query(sql)


def test_read_only_role_can_read_every_allowed_table(db_session):
    """Keeps migration 0002's GRANTs in step with data_schema.ALLOWED_TABLES."""
    for table in sorted(data_schema.ALLOWED_TABLES - {"users"}):
        assert ask_data_service.run_query(f"SELECT * FROM {table} LIMIT 0")[1] == []
    columns, _rows = ask_data_service.run_query(
        "SELECT id, name, email, role, created_at FROM users LIMIT 1")
    assert columns == ["id", "name", "email", "role", "created_at"]


def test_slow_queries_are_stopped(db_session, monkeypatch):
    monkeypatch.setattr(ask_data_service, "QUERY_TIMEOUT_MS", 300)
    with pytest.raises(AskDataError, match="took longer") as caught:
        ask_data_service.run_query("SELECT pg_sleep(3)")
    assert caught.value.sql == "SELECT pg_sleep(3)"


def test_sql_errors_are_explained(db_session):
    with pytest.raises(AskDataError, match='column "nosuch" does not exist'):
        ask_data_service.run_query("SELECT nosuch FROM products")


def test_special_characters_reach_the_database_unchanged(db_session):
    """% and :word must not be treated as parameters (see query_repository._cursor)."""
    _columns, rows = ask_data_service.run_query("SELECT 'a%b' LIKE '%b' AS m, '10:30' AS t")
    assert rows == [(True, "10:30")]


def test_missing_role_gives_a_clear_message(db_session, monkeypatch):
    monkeypatch.setattr(query_repository, "READ_ONLY_ROLE", "shopsense_no_such_role")
    with pytest.raises(AskDataError, match="alembic upgrade head"):
        ask_data_service.run_query("SELECT 1")


def test_the_session_is_normal_again_afterwards(db_session, factory):
    """READ ONLY, the timeout and the role were SET LOCAL and rolled back: later work
    in the same connection can write and runs as the app's own user."""
    ask_data_service.run_query("SELECT 1")
    with pytest.raises(AskDataError):
        ask_data_service.run_query("SELECT nosuch FROM products")
    factory.category("Test After Ask")  # a write: would fail if still read-only
    assert db_session.execute(text("SELECT current_user")).scalar() != "shopsense_readonly"


# ---------------------------------------------------------------------------
# text_to_sql: talking to Gemini (with a fake client)
# ---------------------------------------------------------------------------

class FakeModels:
    def __init__(self, replies):
        self.replies = list(replies)  # one per call: reply text, or an exception
        self.models_used = []

    def generate_content(self, model, contents, config):
        self.models_used.append(model)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(text=reply)


@pytest.fixture
def gemini(monkeypatch):
    def install(*replies):
        models = FakeModels(replies)
        monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
        monkeypatch.setattr(config, "GEMINI_MODEL", "main-model")
        monkeypatch.setattr(config, "GEMINI_FALLBACK_MODEL", "fallback-model")
        monkeypatch.setattr(text_to_sql, "_client", SimpleNamespace(models=models))
        return models
    return install


def api_error(code: int, message: str = "error") -> errors.APIError:
    return errors.APIError(code, {"error": {"code": code, "message": message}})


def test_generate_sql_reads_the_json_reply(gemini):
    gemini('{"sql": "SELECT COUNT(*) FROM orders", "reason": ""}')
    assert text_to_sql.generate_sql("How many orders?") == "SELECT COUNT(*) FROM orders"


def test_generate_sql_explains_unanswerable_questions(gemini):
    gemini('{"sql": "", "reason": "There is no weather data."}')
    with pytest.raises(AskDataError, match="no weather data"):
        text_to_sql.generate_sql("Weather in Delhi?")


def test_summarize_sends_only_the_first_rows(gemini):
    models = gemini('{"summary": "Lamps sell best.\\nReally."}')
    calls = []
    original = models.generate_content
    models.generate_content = lambda **kw: calls.append(kw["contents"]) or original(**kw)
    rows = [(i, f"Product {i}") for i in range(50)]
    assert text_to_sql.summarize("Best?", ["id", "name"], rows, False) == \
        "Lamps sell best. Really."
    assert "Product 19" in calls[0] and "Product 20" not in calls[0]


def test_missing_api_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(AskDataError, match="GEMINI_API_KEY"):
        text_to_sql.generate_sql("How many orders?")


def test_overloaded_model_falls_back_once(gemini):
    models = gemini(api_error(503, "high demand"), '{"sql": "SELECT 1", "reason": ""}')
    assert text_to_sql.generate_sql("?") == "SELECT 1"
    assert models.models_used == ["main-model", "fallback-model"]


def test_used_up_quota_falls_back_once(gemini):
    """Each model has its own free-tier quota, so the fallback model can still answer."""
    models = gemini(api_error(429, "quota"), '{"sql": "SELECT 1", "reason": ""}')
    assert text_to_sql.generate_sql("?") == "SELECT 1"
    assert models.models_used == ["main-model", "fallback-model"]


def test_both_quotas_used_up(gemini):
    gemini(api_error(429), api_error(429))
    with pytest.raises(AskDataError, match="free-tier limit"):
        text_to_sql.generate_sql("?")


def test_both_models_overloaded(gemini):
    gemini(api_error(503), api_error(503))
    with pytest.raises(AskDataError, match="busy or unavailable"):
        text_to_sql.generate_sql("?")


@pytest.mark.parametrize("error, message", [
    (api_error(400, "API key not valid. Please pass a valid API key."), "rejected the API key"),
    (api_error(404, "not found"), "'main-model' isn't available"),
    (httpx.ConnectError("no internet"), "internet connection"),
    (httpx.ReadTimeout("slow"), "internet connection"),
])
def test_gemini_failures_become_friendly_messages(gemini, error, message):
    models = gemini(error)
    with pytest.raises(AskDataError, match=message):
        text_to_sql.generate_sql("?")
    assert models.models_used == ["main-model"]  # no pointless retry


@pytest.mark.parametrize("reply", ["not json", "[1, 2]", ""])
def test_unreadable_replies(gemini, reply):
    gemini(reply)
    with pytest.raises(AskDataError, match="couldn't be read"):
        text_to_sql.generate_sql("?")
