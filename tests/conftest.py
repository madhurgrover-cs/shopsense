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
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

import app.db
from app.db import engine
from app.models import AuditLog, Category, Coupon, Inventory, Product, Review, User
from app.services import auth_service
from app.services.user_session import UserSession


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


class Factory:
    """Creates test data inside the rollback transaction (so it vanishes afterwards).
    Names use a counter so they never clash with seed data or each other."""

    def __init__(self, session) -> None:
        self.session = session
        self.counter = 0

    def _next(self) -> int:
        self.counter += 1
        return self.counter

    def _save(self, obj):
        self.session.add(obj)
        self.session.commit()  # releases a savepoint; the outer transaction stays open
        return obj

    def user(self, role: str = "customer") -> UserSession:
        n = self._next()
        user = self._save(User(name=f"Test User {n}", email=f"test.user.{n}@example.com",
                               password_hash="not-a-real-hash", role=role))
        return UserSession(user.id, user.name, user.email, user.role)

    def category(self, name: str | None = None) -> int:
        return self._save(Category(name=name or f"Test Category {self._next()}")).id

    def product(self, price="100.00", stock: int = 10, category_id: int | None = None,
                name: str | None = None, active: bool = True) -> int:
        product = Product(
            category_id=category_id or self.category(),
            name=name or f"Test Product {self._next()}",
            description="A product created by a test.", price=Decimal(price), is_active=active,
        )
        product.inventory = Inventory(stock=stock)
        return self._save(product).id

    def coupon(self, code: str, percent_off: int = 10, days_valid: float = 30,
               active: bool = True) -> None:
        """days_valid < 0 creates an already-expired coupon."""
        self._save(Coupon(code=code, percent_off=percent_off, is_active=active,
                          valid_until=datetime.now(timezone.utc) + timedelta(days=days_valid)))

    def review(self, user_id: int, product_id: int, rating: int) -> None:
        self._save(Review(user_id=user_id, product_id=product_id, rating=rating))

    def stock(self, product_id: int) -> int:
        return self.session.get(Inventory, product_id, populate_existing=True).stock

    def audit_entries(self, entity: str, entity_id: int | None = None) -> list[AuditLog]:
        self.session.expire_all()
        query = self.session.query(AuditLog).filter(AuditLog.entity == entity)
        if entity_id is not None:
            query = query.filter(AuditLog.entity_id == entity_id)
        return query.order_by(AuditLog.id).all()


@pytest.fixture
def factory(db_session) -> Factory:
    return Factory(db_session)


@pytest.fixture
def admin(factory) -> UserSession:
    return factory.user(role="admin")


@pytest.fixture
def customer(factory) -> UserSession:
    return factory.user()


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
