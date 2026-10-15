"""Tests for checkout, order history and admin order-status updates."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.exceptions import (
    EmptyCartError, InvalidCouponError, NotFoundError, OutOfStockError,
    PermissionDeniedError, ValidationError,
)
from app.models import Order
from app.repositories import order_repository
from app.services import cart_service, catalog_service, order_service
from app.services.validation import today


def history(detail) -> list[tuple]:
    return [(c.old_status, c.new_status) for c in detail.timeline]


def order_count(db_session, user_id: int) -> int:
    db_session.expire_all()
    return db_session.query(Order).filter_by(user_id=user_id).count()


# ---------------------------------------------------------------------------
# Checkout: success paths
# ---------------------------------------------------------------------------

def test_checkout_creates_order_and_updates_everything(factory, customer):
    a = factory.product(price="250.00", stock=5)
    b = factory.product(price="99.50", stock=2)
    cart_service.add_to_cart(customer, a, 2)
    cart_service.add_to_cart(customer, b, 1)

    order = order_service.checkout(customer, "upi")

    assert order.user_id == customer.user_id and order.status == "placed"
    assert [(l.product_id, l.qty, l.unit_price) for l in order.lines] == [
        (a, 2, Decimal("250.00")), (b, 1, Decimal("99.50"))]
    assert (order.subtotal, order.discount, order.total) == (
        Decimal("599.50"), Decimal("0.00"), Decimal("599.50"))
    assert order.payment.method == "upi" and order.payment.status == "success"
    assert order.payment.amount == order.total and order.payment.paid_at is not None
    assert history(order) == [(None, "placed")]           # written by the trigger
    assert factory.stock(a) == 3 and factory.stock(b) == 1  # decremented
    assert cart_service.get_cart(customer).is_empty         # cart cleared


def test_checkout_cash_on_delivery_is_pending(factory, customer):
    cart_service.add_to_cart(customer, factory.product())
    payment = order_service.checkout(customer, "cod").payment
    assert payment.status == "pending" and payment.paid_at is None


def test_checkout_with_coupon(factory, customer):
    factory.coupon("TESTCHECKOUT", percent_off=20)
    cart_service.add_to_cart(customer, factory.product(price="1000.00"), 2)
    order = order_service.checkout(customer, "card", coupon_code="testcheckout")
    assert (order.subtotal, order.discount, order.total, order.coupon_code) == (
        Decimal("2000.00"), Decimal("400.00"), Decimal("1600.00"), "TESTCHECKOUT")
    assert order.payment.amount == Decimal("1600.00")


def test_order_keeps_price_paid_after_price_change(factory, customer, admin):
    pid = factory.product(price="500.00")
    cart_service.add_to_cart(customer, pid)
    order = order_service.checkout(customer, "upi")

    catalog_service.update_product(admin, pid, price="650.00")
    line = order_service.get_order_detail(customer, order.id).lines[0]
    assert line.unit_price == Decimal("500.00")


def test_checkout_can_buy_exactly_the_last_units(factory, customer):
    pid = factory.product(stock=2)
    cart_service.add_to_cart(customer, pid, 2)
    order_service.checkout(customer, "upi")
    assert factory.stock(pid) == 0


# ---------------------------------------------------------------------------
# Checkout: failures roll back EVERYTHING
# ---------------------------------------------------------------------------

def test_checkout_empty_cart(customer):
    with pytest.raises(EmptyCartError):
        order_service.checkout(customer, "upi")


def test_checkout_out_of_stock_changes_nothing(factory, customer, admin, db_session):
    ok = factory.product(stock=5)
    scarce = factory.product(stock=3, name="Test Scarce Item")
    cart_service.add_to_cart(customer, ok, 1)
    cart_service.add_to_cart(customer, scarce, 3)
    catalog_service.update_stock(admin, scarce, 1)  # stock drops after it was added

    with pytest.raises(OutOfStockError, match="Only 1 left of 'Test Scarce Item'"):
        order_service.checkout(customer, "upi")
    assert factory.stock(ok) == 5 and factory.stock(scarce) == 1   # nothing decremented
    assert order_count(db_session, customer.user_id) == 0
    assert cart_service.get_cart(customer).item_count == 4         # cart intact


def test_checkout_invalid_coupon_changes_nothing(factory, customer, db_session):
    pid = factory.product(stock=5)
    cart_service.add_to_cart(customer, pid)
    with pytest.raises(InvalidCouponError):
        order_service.checkout(customer, "upi", coupon_code="NOSUCHCOUPON")
    assert factory.stock(pid) == 5 and order_count(db_session, customer.user_id) == 0


def test_checkout_failure_after_writes_rolls_back(factory, customer, db_session, monkeypatch):
    """Simulate a crash at the very last step (payment), after stock was decremented
    and the order and items were inserted. All of it must be undone."""
    pid = factory.product(stock=5)
    cart_service.add_to_cart(customer, pid, 2)

    def broken_payment(*args, **kwargs):
        raise RuntimeError("payment gateway down")
    monkeypatch.setattr(order_repository, "add_payment", broken_payment)

    with pytest.raises(RuntimeError):
        order_service.checkout(customer, "upi")
    assert factory.stock(pid) == 5
    assert order_count(db_session, customer.user_id) == 0
    assert cart_service.get_cart(customer).item_count == 2


def test_checkout_with_removed_product(factory, customer, admin):
    pid = factory.product()
    cart_service.add_to_cart(customer, pid)
    catalog_service.delete_product(admin, pid)
    with pytest.raises(NotFoundError, match="no longer available"):
        order_service.checkout(customer, "upi")


def test_checkout_rejects_bad_payment_method_and_anonymous(factory, customer):
    cart_service.add_to_cart(customer, factory.product())
    with pytest.raises(ValidationError):
        order_service.checkout(customer, "bitcoin")
    with pytest.raises(PermissionDeniedError):
        order_service.checkout(None, "upi")


# ---------------------------------------------------------------------------
# Order history
# ---------------------------------------------------------------------------

def place_order(customer, factory, price="100.00", qty=1, method="upi"):
    cart_service.add_to_cart(customer, factory.product(price=price), qty)
    return order_service.checkout(customer, method)


def test_list_orders_newest_first_and_only_own(factory, customer):
    first = place_order(customer, factory, qty=2)
    second = place_order(customer, factory)
    place_order(factory.user(), factory)  # someone else's order

    orders = order_service.list_orders(customer)
    assert [o.id for o in orders] == [second.id, first.id]
    assert orders[1].item_count == 2 and orders[1].total == Decimal("200.00")


def test_get_order_detail_visibility(factory, customer, admin):
    order = place_order(customer, factory)
    assert order_service.get_order_detail(customer, order.id).id == order.id
    assert order_service.get_order_detail(admin, order.id).id == order.id  # admins see all
    with pytest.raises(NotFoundError):  # another customer: looks like it doesn't exist
        order_service.get_order_detail(factory.user(), order.id)
    with pytest.raises(NotFoundError):
        order_service.get_order_detail(customer, -1)


def test_list_all_orders_for_admin(factory, customer, admin):
    placed = place_order(customer, factory)
    shipped = place_order(customer, factory)
    order_service.update_order_status(admin, shipped.id, "shipped")

    ids = {o.id for o in order_service.list_all_orders(admin, status="shipped")}
    assert shipped.id in ids and placed.id not in ids
    with pytest.raises(ValidationError):
        order_service.list_all_orders(admin, status="lost")
    with pytest.raises(PermissionDeniedError):
        order_service.list_all_orders(customer)


# ---------------------------------------------------------------------------
# Admin: status updates
# ---------------------------------------------------------------------------

def test_status_flow_builds_timeline_and_audit(factory, customer, admin):
    order = place_order(customer, factory, method="cod")
    order_service.update_order_status(admin, order.id, "shipped")
    detail = order_service.update_order_status(admin, order.id, "delivered")

    assert detail.status == "delivered"
    assert history(detail) == [(None, "placed"), ("placed", "shipped"), ("shipped", "delivered")]
    # Cash on delivery is collected on delivery.
    assert detail.payment.status == "success" and detail.payment.paid_at is not None

    entries = factory.audit_entries("order", order.id)
    assert [(e.action, e.details, e.user_id) for e in entries] == [
        ("status_change", "placed -> shipped", admin.user_id),
        ("status_change", "shipped -> delivered", admin.user_id),
    ]


def test_cancel_restocks_and_refunds(factory, customer, admin):
    pid = factory.product(stock=5)
    cart_service.add_to_cart(customer, pid, 3)
    order = order_service.checkout(customer, "card")
    assert factory.stock(pid) == 2

    detail = order_service.update_order_status(admin, order.id, "cancelled")
    assert factory.stock(pid) == 5
    assert detail.payment.status == "refunded"
    assert history(detail)[-1] == ("placed", "cancelled")


def test_cancel_cod_order_marks_payment_failed(factory, customer, admin):
    order = place_order(customer, factory, method="cod")
    detail = order_service.update_order_status(admin, order.id, "cancelled")
    assert detail.payment.status == "failed"


@pytest.mark.parametrize("path, bad_next", [
    ([], "delivered"),                          # placed -> delivered skips shipping
    (["shipped"], "cancelled"),                 # already on its way
    (["shipped", "delivered"], "placed"),       # final state
    (["cancelled"], "shipped"),                 # final state
])
def test_invalid_status_transitions(factory, customer, admin, path, bad_next):
    order = place_order(customer, factory)
    for status in path:
        order_service.update_order_status(admin, order.id, status)
    with pytest.raises(ValidationError, match="Cannot change"):
        order_service.update_order_status(admin, order.id, bad_next)


def test_update_order_status_errors(factory, customer, admin):
    order = place_order(customer, factory)
    with pytest.raises(ValidationError, match="Unknown"):
        order_service.update_order_status(admin, order.id, "lost")
    with pytest.raises(NotFoundError):
        order_service.update_order_status(admin, -1, "shipped")
    with pytest.raises(PermissionDeniedError):
        order_service.update_order_status(customer, order.id, "shipped")
    assert factory.audit_entries("order", order.id) == []


def test_list_all_orders_includes_customer_and_filters_by_date(factory, customer, admin):
    order = place_order(customer, factory)
    todays = order_service.list_all_orders(admin, date_from=today(), date_to=today())
    mine = next(o for o in todays if o.id == order.id)
    assert (mine.customer_name, mine.customer_email) == (customer.name, customer.email)

    as_text = order_service.list_all_orders(admin, date_from=today().isoformat(),
                                            date_to=today().isoformat())
    assert order.id in {o.id for o in as_text}
    yesterday = today() - timedelta(days=1)
    earlier = order_service.list_all_orders(admin, date_from=yesterday, date_to=yesterday)
    assert order.id not in {o.id for o in earlier}
    both = order_service.list_all_orders(admin, status="placed", date_from=today(),
                                         date_to=today())
    assert order.id in {o.id for o in both} and all(o.status == "placed" for o in both)


def test_list_all_orders_date_errors(admin):
    with pytest.raises(ValidationError, match="both"):
        order_service.list_all_orders(admin, date_from="2026-10-01")
    with pytest.raises(ValidationError, match="on or before"):
        order_service.list_all_orders(admin, date_from="2026-10-02", date_to="2026-10-01")
    with pytest.raises(ValidationError, match="YYYY-MM-DD"):
        order_service.list_all_orders(admin, date_from="01/10/2026", date_to="2026-10-01")


def test_next_statuses_follow_allowed_flow():
    assert order_service.next_statuses("placed") == ["shipped", "cancelled"]
    assert order_service.next_statuses("shipped") == ["delivered"]
    assert order_service.next_statuses("delivered") == []
    assert order_service.next_statuses("cancelled") == []
    with pytest.raises(ValidationError):
        order_service.next_statuses("lost")
