"""Tests for the admin customer list (user_service)."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.exceptions import PermissionDeniedError
from app.models import User
from app.services import auth_service, user_service


def find(customers, user_id):
    return next(c for c in customers if c.id == user_id)


def test_list_customers_with_order_stats(factory, admin, customer):
    pid, other = factory.product(), factory.product()
    factory.order(customer.user_id, [pid, other], unit_price="100.00")           # ₹200
    factory.order(customer.user_id, [pid], status="placed", unit_price="50.00")  # ₹50
    factory.order(customer.user_id, [pid], status="cancelled", unit_price="999.00")
    newcomer = factory.user()

    customers = user_service.list_customers(admin)
    mine = find(customers, customer.user_id)
    assert (mine.name, mine.email, mine.order_count) == (customer.name, customer.email, 3)
    assert mine.total_spent == Decimal("250.00")   # the cancelled order was refunded
    assert mine.last_order_at is not None and not mine.is_locked

    new = find(customers, newcomer.user_id)        # customers without orders are listed
    assert (new.order_count, new.total_spent, new.last_order_at) == (0, 0, None)
    assert admin.user_id not in {c.id for c in customers}  # only customers
    names = [(c.name, c.id) for c in customers]
    assert names == sorted(names)


def test_locked_customers_are_marked(db_session, admin, customer):
    user = db_session.get(User, customer.user_id)
    user.locked_until = auth_service.utcnow() + timedelta(minutes=10)
    db_session.commit()
    assert find(user_service.list_customers(admin), customer.user_id).is_locked
    user.locked_until = auth_service.utcnow() - timedelta(minutes=1)  # lock expired
    db_session.commit()
    assert not find(user_service.list_customers(admin), customer.user_id).is_locked


def test_list_customers_is_admin_only(customer):
    with pytest.raises(PermissionDeniedError):
        user_service.list_customers(customer)
