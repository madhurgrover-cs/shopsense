"""Tests for the shopping cart."""

from decimal import Decimal

import pytest

from app.exceptions import (
    EmptyCartError, InvalidCouponError, NotFoundError, OutOfStockError,
    PermissionDeniedError, ValidationError,
)
from app.services import cart_service, catalog_service


def test_new_cart_is_empty(customer):
    cart = cart_service.get_cart(customer)
    assert cart.is_empty and cart.item_count == 0
    assert cart.subtotal == cart.total == Decimal("0.00") and cart.coupon is None


def test_add_to_cart_and_totals(factory, customer):
    a = factory.product(price="250.00")
    b = factory.product(price="99.50")
    cart_service.add_to_cart(customer, a, 2)
    cart = cart_service.add_to_cart(customer, b)

    assert [(l.product_id, l.qty, l.line_total) for l in cart.lines] == [
        (a, 2, Decimal("500.00")), (b, 1, Decimal("99.50"))]
    assert cart.subtotal == cart.total == Decimal("599.50")
    assert cart.item_count == 3


def test_adding_same_product_again_increases_quantity(factory, customer):
    pid = factory.product()
    cart_service.add_to_cart(customer, pid, 1)
    cart = cart_service.add_to_cart(customer, pid, 2)
    assert len(cart.lines) == 1 and cart.lines[0].qty == 3


def test_add_to_cart_respects_stock(factory, customer):
    pid = factory.product(stock=3)
    cart_service.add_to_cart(customer, pid, 2)
    with pytest.raises(OutOfStockError, match="Only 3 left"):
        cart_service.add_to_cart(customer, pid, 2)  # 2 + 2 > 3
    assert cart_service.get_cart(customer).lines[0].qty == 2  # unchanged


def test_add_out_of_stock_product(factory, customer):
    with pytest.raises(OutOfStockError, match="out of stock"):
        cart_service.add_to_cart(customer, factory.product(stock=0))


def test_add_unavailable_product(factory, customer):
    with pytest.raises(NotFoundError):
        cart_service.add_to_cart(customer, factory.product(active=False))
    with pytest.raises(NotFoundError):
        cart_service.add_to_cart(customer, -1)


@pytest.mark.parametrize("qty", [0, -1, 1.5, True])
def test_add_to_cart_rejects_bad_quantity(factory, customer, qty):
    with pytest.raises(ValidationError):
        cart_service.add_to_cart(customer, factory.product(), qty)


def test_update_quantity(factory, customer):
    pid = factory.product(price="10.00", stock=5)
    cart_service.add_to_cart(customer, pid)
    cart = cart_service.update_quantity(customer, pid, 4)
    assert cart.lines[0].qty == 4 and cart.total == Decimal("40.00")

    with pytest.raises(OutOfStockError):
        cart_service.update_quantity(customer, pid, 6)
    with pytest.raises(ValidationError):
        cart_service.update_quantity(customer, pid, -1)


def test_update_quantity_to_zero_removes_line(factory, customer):
    pid = factory.product()
    cart_service.add_to_cart(customer, pid)
    assert cart_service.update_quantity(customer, pid, 0).is_empty


def test_update_quantity_of_product_not_in_cart(factory, customer):
    with pytest.raises(NotFoundError):
        cart_service.update_quantity(customer, factory.product(), 1)


def test_remove_from_cart(factory, customer):
    a, b = factory.product(), factory.product()
    cart_service.add_to_cart(customer, a)
    cart_service.add_to_cart(customer, b)
    cart = cart_service.remove_from_cart(customer, a)
    assert [l.product_id for l in cart.lines] == [b]
    with pytest.raises(NotFoundError):
        cart_service.remove_from_cart(customer, a)


def test_carts_are_per_user(factory, customer):
    other = factory.user()
    cart_service.add_to_cart(customer, factory.product())
    assert cart_service.get_cart(other).is_empty


def test_cart_flags_product_removed_after_adding(factory, customer, admin):
    pid = factory.product()
    cart_service.add_to_cart(customer, pid)
    catalog_service.delete_product(admin, pid)
    assert cart_service.get_cart(customer).lines[0].is_active is False


def test_apply_coupon(factory, customer):
    factory.coupon("TESTTEN", percent_off=10)
    cart_service.add_to_cart(customer, factory.product(price="333.33"), 3)  # 999.99

    cart = cart_service.apply_coupon(customer, "testten")
    assert cart.coupon.code == "TESTTEN"
    assert (cart.subtotal, cart.discount, cart.total) == (
        Decimal("999.99"), Decimal("100.00"), Decimal("899.99"))
    # The same totals come back when the GUI passes the code to get_cart.
    assert cart_service.get_cart(customer, "TESTTEN").total == Decimal("899.99")


def test_apply_invalid_or_expired_coupon(factory, customer):
    factory.coupon("TESTOLD", days_valid=-1)
    cart_service.add_to_cart(customer, factory.product())
    with pytest.raises(InvalidCouponError):
        cart_service.apply_coupon(customer, "NOSUCHCODE")
    with pytest.raises(InvalidCouponError, match="expired"):
        cart_service.apply_coupon(customer, "TESTOLD")


def test_apply_coupon_to_empty_cart(factory, customer):
    factory.coupon("TESTEMPTY")
    with pytest.raises(EmptyCartError):
        cart_service.apply_coupon(customer, "TESTEMPTY")


@pytest.mark.parametrize("call", [
    lambda: cart_service.get_cart(None),
    lambda: cart_service.add_to_cart(None, 1),
    lambda: cart_service.update_quantity(None, 1, 1),
    lambda: cart_service.remove_from_cart(None, 1),
    lambda: cart_service.apply_coupon(None, "X"),
])
def test_cart_requires_login(db_session, call):
    with pytest.raises(PermissionDeniedError):
        call()
