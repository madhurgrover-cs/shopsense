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

import math
import re
import zlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

import app.db
from app.ai import embeddings, search
from app.db import engine
from app.models import (
    AuditLog, Category, Coupon, Inventory, Order, OrderItem, Product, ProductEmbedding,
    Review, User,
)
from app.models.catalog import EMBEDDING_DIM
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
                name: str | None = None, active: bool = True,
                description: str = "A product created by a test.") -> int:
        product = Product(
            category_id=category_id or self.category(),
            name=name or f"Test Product {self._next()}",
            description=description, price=Decimal(price), is_active=active,
        )
        product.inventory = Inventory(stock=stock)
        return self._save(product).id

    def coupon(self, code: str, percent_off: int = 10, days_valid: float = 30,
               active: bool = True) -> None:
        """days_valid < 0 creates an already-expired coupon."""
        self._save(Coupon(code=code, percent_off=percent_off, is_active=active,
                          valid_until=datetime.now(timezone.utc) + timedelta(days=days_valid)))

    def review(self, user_id: int, product_id: int, rating: int, comment: str | None = None,
               score: float | None = None) -> int:
        return self._save(Review(user_id=user_id, product_id=product_id, rating=rating,
                                 comment=comment, sentiment_score=score)).id

    def order(self, user_id: int, product_ids: list[int], status: str = "delivered",
              unit_price: str = "1.00", created_at: datetime | None = None) -> int:
        """An order (one of each product at unit_price) inserted directly, already in
        `status`, placed now or at created_at."""
        price = Decimal(unit_price)
        total = price * len(product_ids)
        order = Order(user_id=user_id, status=status, subtotal=total, discount=0, total=total)
        if created_at is not None:
            order.created_at = created_at
        order.items = [OrderItem(product_id=pid, qty=1, unit_price=price)
                       for pid in product_ids]
        return self._save(order).id

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


def fake_vector(text: str) -> list[float]:
    """A tiny stand-in for the real embedding model: a "bag of words" vector.

    Each word switches on one of the 384 dimensions (chosen by a hash of the word), and
    the vector is scaled to length 1 like the real model's. So texts sharing more words
    have a smaller cosine distance. It's crude, but deterministic and instant, which is
    all the search/recommendation LOGIC tests need. Real meaning is tested separately in
    test_ai_integration.py.
    """
    vector = [0.0] * EMBEDDING_DIM
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        vector[zlib.crc32(word.encode()) % EMBEDDING_DIM] += 1.0
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


@pytest.fixture
def fake_embedder(monkeypatch):
    """Replace the real model with fake_vector for the duration of a test.
    get_model() returns a placeholder, so code that preloads the model still works
    without loading the real one."""
    monkeypatch.setattr(embeddings, "get_model", lambda: "fake-model")
    monkeypatch.setattr(embeddings, "embed_texts",
                        lambda texts, batch_size=32: [fake_vector(t) for t in texts])
    return fake_vector


@pytest.fixture
def no_seed_embeddings(db_session):
    """Delete every product embedding INSIDE the test transaction (rolled back after),
    so search results only contain the test's own products."""
    db_session.execute(delete(ProductEmbedding))
    db_session.commit()


@pytest.fixture(scope="session")
def gui_app():
    """ONE hidden ShopSense window for every GUI test in the whole run.

    On Windows with Python 3.14, creating a second Tk interpreter after the first one
    was destroyed intermittently fails ("Can't find a usable init.tcl / ttk.tcl"). So
    all GUI tests share this single window, created on first use and destroyed at the
    very end. Network-touching and popup functions are replaced: popups are recorded in
    app.popups (their titles) instead of opening windows.
    """
    from app.gui import app as app_module  # imported here: only GUI tests need Tk

    patch = pytest.MonkeyPatch()
    # The window gets its OWN stand-in for system_service. (Patching functions on the
    # real module would last for the whole session and leak into non-GUI tests.)
    # No database check, and customer logins never load the real AI model.
    patch.setattr(app_module, "system_service", SimpleNamespace(
        check_connection=lambda: None,
        preload_search_model=lambda: True,
        is_search_model_loaded=embeddings.is_model_loaded,
    ))
    popups: list[str] = []
    patch.setattr(app_module, "show_error", lambda parent, title, message: popups.append(title))
    patch.setattr(app_module, "MessageDialog",
                  lambda parent, title, message, kind="info": popups.append(title))
    # "Are you sure?" dialogs: record the title and answer with window.confirm_answer
    # (a test sets it to False to check that "Cancel" really does nothing).
    confirms: list[str] = []

    def fake_confirm(parent, title, message, on_confirm, confirm_text="", danger=True):
        confirms.append(title)
        if window.confirm_answer:
            on_confirm()
    patch.setattr(app_module, "ConfirmDialog", fake_confirm)
    window = app_module.ShopSenseApp()
    window.withdraw()
    window.popups = popups
    window.confirms = confirms
    window.confirm_answer = True
    yield window
    window._on_close()
    patch.undo()


NEGATIVE_WORDS = ("terrible", "awful", "horrible", "broke", "broken", "waste", "poor",
                  "bad", "disappointed", "not happy", "expected much better", "cheap")
POSITIVE_WORDS = ("love", "excellent", "great", "perfect", "perfectly", "amazing", "nice",
                  "happy")


def fake_sentiment(text: str) -> float:
    """A stand-in for DistilBERT: counts clearly positive / negative words. Negative
    phrases are checked first, so "not happy" is negative. Clear text scores +/-0.9,
    a tie (e.g. "decent, nothing special") -0.5, like a mixed review."""
    lowered = text.lower()
    negative = sum(lowered.count(w) for w in NEGATIVE_WORDS)
    positive = sum(lowered.count(w) for w in POSITIVE_WORDS) - lowered.count("not happy")
    if negative > positive:
        return -0.9
    if positive > negative:
        return 0.9
    return -0.5


@pytest.fixture(autouse=True)
def fake_sentiment_model(request, monkeypatch):
    """Unit tests never load the real sentiment model (~270 MB, seconds per load): its
    scoring function is replaced by fake_sentiment. Tests marked "integration" get the
    real model, and tests marked "real_sentiment_code" the real loading code (they
    install a fake transformers package themselves). The calls are recorded so tests
    can count model loads."""
    if (request.node.get_closest_marker("integration")
            or request.node.get_closest_marker("real_sentiment_code")):
        yield None
        return
    from app.ai import sentiment
    calls: list[list[str]] = []

    def fake_transformer_scores(texts):
        calls.append(list(texts))
        return [fake_sentiment(t) for t in texts]
    monkeypatch.setattr(sentiment, "transformer_scores", fake_transformer_scores)
    monkeypatch.setattr(sentiment, "_model_failed", False)
    yield calls


@pytest.fixture(autouse=True)
def fresh_spelling_vocabulary():
    """The spelling vocabulary is cached for 5 minutes. Clear it around every test, so
    a test's own products (inside its rollback transaction) are in the vocabulary and
    don't leak into the next test."""
    search.clear_vocabulary_cache()
    yield
    search.clear_vocabulary_cache()


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
