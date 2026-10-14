"""Concurrency test: two customers race to buy the LAST unit of a product.

This test does NOT use the rollback fixture: two threads need two separate database
connections that really commit, exactly like two users on two computers. So it
creates real rows and deletes them all again in a `finally` block, then checks that
every table has the same row count as before.

How the race is made deterministic: create_order is wrapped to sleep 1 second. Both
threads start checkout at the same moment (a Barrier). Whichever locks the stock row
first holds the lock while it sleeps; the other is stuck at SELECT ... FOR UPDATE.
When the first commits, the second gets the row with the NEW stock (0) and fails
with OutOfStockError. Without FOR UPDATE, both would read stock = 1 and both would
succeed, selling a unit that doesn't exist.
"""

import threading
import time

from sqlalchemy import text

from app.db import engine, get_session
from app.exceptions import OutOfStockError
from app.models import Base, Category, Inventory, Product, User
from app.repositories import order_repository
from app.services import cart_service, order_service
from app.services.user_session import UserSession

HOLD_LOCK_SECONDS = 1.0


def table_counts() -> dict[str, int]:
    with engine.connect() as conn:
        return {t: conn.scalar(text(f"SELECT COUNT(*) FROM {t}")) for t in Base.metadata.tables}


def test_two_buyers_race_for_the_last_unit(monkeypatch):
    counts_before = table_counts()
    user_ids, product_id, category_id = [], None, None
    try:
        # --- Setup: one product with stock 1, two customers each with it in their cart.
        with get_session() as session:
            category = Category(name="ZZ Concurrency Test Category")
            product = Product(category=category, name="ZZ Last Unit", description="",
                              price=999, inventory=Inventory(stock=1))
            users = [User(name=f"ZZ Racer {i}", email=f"zz.racer.{i}@example.com",
                          password_hash="x", role="customer") for i in (1, 2)]
            session.add_all([product, *users])
            session.flush()
            category_id, product_id = category.id, product.id
            user_ids = [u.id for u in users]
            buyers = [UserSession(u.id, u.name, u.email, u.role) for u in users]
        for buyer in buyers:
            cart_service.add_to_cart(buyer, product_id, 1)

        # --- Hold the lock for a while inside checkout, to force the overlap.
        original_create_order = order_repository.create_order

        def slow_create_order(*args, **kwargs):
            time.sleep(HOLD_LOCK_SECONDS)
            return original_create_order(*args, **kwargs)
        monkeypatch.setattr(order_repository, "create_order", slow_create_order)

        # --- Race.
        start_line = threading.Barrier(len(buyers))
        results: dict[int, tuple[str, float]] = {}

        def attempt(buyer: UserSession) -> None:
            start_line.wait()
            started = time.perf_counter()
            try:
                order_service.checkout(buyer, "upi")
                outcome = "bought"
            except OutOfStockError:
                outcome = "out of stock"
            except Exception as error:  # anything else is a bug; report it, don't hang
                outcome = f"error: {error!r}"
            results[buyer.user_id] = (outcome, time.perf_counter() - started)

        threads = [threading.Thread(target=attempt, args=(b,)) for b in buyers]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert not any(t.is_alive() for t in threads), "a checkout hung"

        # --- Exactly one winner, stock exactly 0, exactly one order.
        outcomes = sorted(outcome for outcome, _ in results.values())
        assert outcomes == ["bought", "out of stock"], results

        with engine.connect() as conn:
            stock = conn.scalar(text("SELECT stock FROM inventory WHERE product_id = :p"),
                                {"p": product_id})
            orders = conn.scalar(text(
                "SELECT COUNT(*) FROM order_items WHERE product_id = :p"), {"p": product_id})
        assert stock == 0
        assert orders == 1

        # The loser really WAITED for the lock (it couldn't just read stock = 1).
        loser_time = next(t for outcome, t in results.values() if outcome == "out of stock")
        assert loser_time >= HOLD_LOCK_SECONDS * 0.9, results

        # The loser's cart is untouched (their transaction rolled back).
        loser_id = next(uid for uid, (outcome, _) in results.items() if outcome == "out of stock")
        loser = next(b for b in buyers if b.user_id == loser_id)
        assert cart_service.get_cart(loser).item_count == 1

        print(f"\n  race results: {results}")
    finally:
        # --- Clean up everything this test created (children before parents).
        with engine.begin() as conn:
            if user_ids:
                # orders -> order_items, payments, order_status_history (ON DELETE CASCADE)
                conn.execute(text("DELETE FROM orders WHERE user_id = ANY(:u)"), {"u": user_ids})
                # users -> carts -> cart_items (ON DELETE CASCADE)
                conn.execute(text("DELETE FROM users WHERE id = ANY(:u)"), {"u": user_ids})
            if product_id:
                conn.execute(text("DELETE FROM products WHERE id = :p"), {"p": product_id})
            if category_id:
                conn.execute(text("DELETE FROM categories WHERE id = :c"), {"c": category_id})

    assert table_counts() == counts_before, "concurrency test left data behind"
