"""Shopping cart: add, change quantity, remove, view totals, apply a coupon.

The cart does not store a coupon (the schema has no column for it). The GUI keeps the
code the customer applied and passes it to get_cart() and checkout(); both validate
it again, because a coupon can expire while it sits in a cart.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.db import get_session
from app.exceptions import EmptyCartError, NotFoundError, OutOfStockError, ValidationError
from app.repositories import cart_repository, product_repository
from app.services import coupon_service
from app.services.auth_service import require_login
from app.services.dto import CartLine, CartView, CouponInfo
from app.services.user_session import UserSession


def get_cart(user: UserSession, coupon_code: str | None = None) -> CartView:
    """The cart with line totals, subtotal, discount and total."""
    require_login(user)
    with get_session() as session:
        cart_id = cart_repository.get_or_create_cart_id(session, user.user_id)
        return build_cart_view(session, cart_id, coupon_code)


def add_to_cart(user: UserSession, product_id: int, qty: int = 1) -> CartView:
    """Add qty of a product; if it's already in the cart, the quantities are added up."""
    require_login(user)
    _validate_qty(qty, allow_zero=False)
    with get_session() as session:
        product = product_repository.get(session, product_id)
        if product is None or not product.is_active:
            raise NotFoundError("This product is not available.")
        cart_id = cart_repository.get_or_create_cart_id(session, user.user_id)
        item = cart_repository.get_item(session, cart_id, product_id)
        new_qty = qty + (item.qty if item else 0)
        _check_stock(product.name, product.inventory.stock if product.inventory else 0, new_qty)
        if item:
            item.qty = new_qty
        else:
            cart_repository.add_item(session, cart_id, product_id, qty)
        session.flush()
        return build_cart_view(session, cart_id)


def update_quantity(user: UserSession, product_id: int, qty: int) -> CartView:
    """Set the quantity of a product already in the cart. qty = 0 removes it."""
    require_login(user)
    _validate_qty(qty, allow_zero=True)
    with get_session() as session:
        cart_id = cart_repository.get_or_create_cart_id(session, user.user_id)
        item = cart_repository.get_item(session, cart_id, product_id)
        if item is None:
            raise NotFoundError("This product is not in your cart.")
        if qty == 0:
            cart_repository.delete_item(session, item)
        else:
            product = item.product
            _check_stock(product.name, product.inventory.stock if product.inventory else 0, qty)
            item.qty = qty
            session.flush()
        return build_cart_view(session, cart_id)


def remove_from_cart(user: UserSession, product_id: int) -> CartView:
    require_login(user)
    with get_session() as session:
        cart_id = cart_repository.get_or_create_cart_id(session, user.user_id)
        item = cart_repository.get_item(session, cart_id, product_id)
        if item is None:
            raise NotFoundError("This product is not in your cart.")
        cart_repository.delete_item(session, item)
        return build_cart_view(session, cart_id)


def apply_coupon(user: UserSession, code: str) -> CartView:
    """Validate a coupon against the current cart and return the discounted totals.
    Raises InvalidCouponError or EmptyCartError."""
    require_login(user)
    with get_session() as session:
        cart_id = cart_repository.get_or_create_cart_id(session, user.user_id)
        view = build_cart_view(session, cart_id, code)
        if view.is_empty:
            raise EmptyCartError()
        return view


def build_cart_view(session: Session, cart_id: int, coupon_code: str | None = None) -> CartView:
    """Compute the cart totals inside the caller's transaction."""
    lines = [
        CartLine(r.product_id, r.name, r.price, r.qty, r.price * r.qty, r.stock, r.is_active)
        for r in cart_repository.list_lines(session, cart_id)
    ]
    subtotal = sum((line.line_total for line in lines), Decimal("0.00"))

    coupon_info, discount = None, Decimal("0.00")
    if coupon_code:
        coupon = coupon_service.get_valid_coupon(session, coupon_code)
        coupon_info = CouponInfo(coupon.code, coupon.percent_off, coupon.valid_until,
                                 coupon.is_active)
        discount = coupon_service.calculate_discount(subtotal, coupon.percent_off)
    return CartView(lines, subtotal, coupon_info, discount, subtotal - discount)


def _validate_qty(qty: int, allow_zero: bool) -> None:
    minimum = 0 if allow_zero else 1
    if not isinstance(qty, int) or isinstance(qty, bool) or qty < minimum:
        raise ValidationError(f"Quantity must be a whole number, at least {minimum}.")


def _check_stock(name: str, available: int, wanted: int) -> None:
    """Early, friendly check while shopping. It is NOT the real guarantee: stock can
    change before checkout, which re-checks under a row lock."""
    if wanted > available:
        raise OutOfStockError(name, available)
