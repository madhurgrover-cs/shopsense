"""Shared test fixtures.

Rollback fixture — how tests avoid leaving data behind in the real (Neon) database:

1. Open ONE connection and BEGIN an outer transaction on it.
2. Point app.db.SessionLocal at that connection, with
   join_transaction_mode="create_savepoint". Now when a service does
   `with get_session(): ...` its commit only releases a SAVEPOINT; the outer
   transaction is still open.
3. After the test, roll back the outer transaction: everything the test (and the
   services it called) wrote disappears.

Services run their real code unchanged; they don't know they are being tested.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

import app.db
from app.db import engine
from app.services import auth_service


@pytest.fixture
def db_session(monkeypatch):
    connection = engine.connect()
    outer = connection.begin()
    TestSession = sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    monkeypatch.setattr(app.db, "SessionLocal", TestSession)

    session = TestSession()  # for tests to set up / inspect data directly
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch):
    """bcrypt at cost 12 takes ~0.25 s per hash; cost 4 is plenty for tests."""
    monkeypatch.setattr(auth_service, "BCRYPT_ROUNDS", 4)
    monkeypatch.setattr(auth_service, "_dummy_hash", None)


class FakeClock:
    """A clock the test controls: starts at a fixed time and only moves when told to."""

    def __init__(self) -> None:
        self.now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(auth_service, "utcnow", fake)
    return fake
