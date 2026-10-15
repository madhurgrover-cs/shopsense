"""Checkout, order history and admin order-status management."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db import get_session
from app.exceptions import EmptyCartError, NotFoundError, OutOfStockError, ValidationError
from app.models import Order
from app.models.order import ORDER_STATUSES, PAYMENT_METHODS
from app.repositories import cart_repository, order_repository, product_repository
from app.services import audit_service, coupon_service
from app.services.auth_service import require_admin, require_login
from app.services.dto import (
    OrderDetail, OrderLine, OrderSummary, PaymentInfo, StatusChange,
)
from app.services.user_session import UserSession
from app.services.validation import date_range, day_bounds

# Which status can follow which. Delivered and cancelled are final.
# A shipped parcel can't be cancelled from the shop side (it is already on its way).
ALLOWED_TRANSITIONS = {
    "placed": {"shipped", "cancelled"},
    "shipped": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

def checkout(user: UserSession, payment_method: str,
             coupon_code: str | None = None) -> OrderDetail:
    """Turn the user's cart into an order, as ONE transaction.

    Steps (all inside a single `with get_session()` block):
      1. Lock the cart row, so the same cart can't be checked out twice at once.
      2. Lock the stock rows of every product in the cart (SELECT ... FOR UPDATE,
         in product_id order to avoid deadlocks). Another checkout for the same
         product now has to WAIT until we commit or roll back.
      3. Verify stock under the lock, then decrement it.
      4. Create the order, its items (copying today's price) and a mock payment.
      5. Empty the cart.
    If anything raises (out of stock, bad coupon, a database error...), get_session()
    rolls back and NOTHING is saved: no order, stock and cart unchanged.
    """
    require_login(user)
    if payment_method not in PAYMENT_METHODS:
        raise ValidationError(f"Payment method must be one of: {', '.join(PAYMENT_METHODS)}.")

    with get_session() as session:
        # 1. Lock the cart.
        cart = cart_repository.lock_cart(session, user.user_id)
        lines = cart_repository.list_lines(session, cart.id) if cart else []
        if not lines:
            raise EmptyCartError()
        for line in lines:
            if not line.is_active:
                raise NotFoundError(
                    f"'{line.name}' is no longer available. Please remove it from your cart."
                )

        # 2. Lock stock rows (sorted by product_id inside lock_inventory).
        stock = product_repository.lock_inventory(session, [line.product_id for line in lines])

        # 3. Check every line BEFORE changing anything, then decrement.
        #    (line.stock was read before the lock and may be stale; stock[...] is fresh.)
        for line in lines:
            available = stock[line.product_id].stock if line.product_id in stock else 0
            if available < line.qty:
                raise OutOfStockError(line.name, available)
        for line in lines:
            stock[line.product_id].stock -= line.qty

        # 4. Order, items, payment.
        subtotal = sum(line.price * line.qty for line in lines)
        discount, applied_code = Decimal("0.00"), None
        if coupon_code:
            coupon = coupon_service.get_valid_coupon(session, coupon_code)
            discount = coupon_service.calculate_discount(subtotal, coupon.percent_off)
            applied_code = coupon.code
        order = order_repository.create_order(session, user.user_id, subtotal, discount,
                                              applied_code)
        for line in lines:
            # unit_price is COPIED: if the admin changes the price tomorrow, this order
            # still shows what the customer actually paid.
            order_repository.add_item(session, order.id, line.product_id, line.qty, line.price)
        status, paid_at = _mock_payment(payment_method)
        order_repository.add_payment(session, order.id, payment_method, order.total,
                                     status, paid_at)

        # 5. Empty the cart.
        cart_repository.clear(session, cart.id)
        session.flush()
        return _build_detail(session, order)


def _mock_payment(method: str) -> tuple[str, datetime | None]:
    """Pretend payment. Cash on delivery is collected later; everything else
    "succeeds" immediately. No card details are ever asked for or stored."""
    if method == "cod":
        return "pending", None
    return "success", utcnow()


# ---------------------------------------------------------------------------
# Order history
# ---------------------------------------------------------------------------

def list_orders(user: UserSession) -> list[OrderSummary]:
    """The logged-in user's orders, newest first."""
    require_login(user)
    with get_session() as session:
        return [_to_summary(r) for r in order_repository.list_orders(session, user.user_id)]


def get_order_detail(user: UserSession, order_id: int) -> OrderDetail:
    """Items, payment and status timeline of one order.

    Customers can only see their own orders. Someone else's order gives the same
    "not found" as a missing one, so order ids can't be probed. Admins see all.
    """
    require_login(user)
    with get_session() as session:
        order = order_repository.get(session, order_id)
        if order is None or (order.user_id != user.user_id and not user.is_admin):
            raise NotFoundError("Order not found.")
        return _build_detail(session, order)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

def list_all_orders(admin: UserSession, status: str | None = None,
                    date_from=None, date_to=None) -> list[OrderSummary]:
    """Every customer's orders, newest first, with the customer's name.

    Optional filters: a status, and a date range (dates in IST, both days included;
    date objects or "YYYY-MM-DD" text). Give both dates or neither.
    """
    require_admin(admin)
    if status is not None and status not in ORDER_STATUSES:
        raise ValidationError("Unknown order status.")
    created_from = created_before = None
    if date_from is not None or date_to is not None:
        if date_from is None or date_to is None:
            raise ValidationError("Please give both a start and an end date.")
        created_from, created_before = day_bounds(*date_range(date_from, date_to))
    with get_session() as session:
        rows = order_repository.list_orders(session, status=status, created_from=created_from,
                                            created_before=created_before)
        return [_to_summary(r) for r in rows]


def next_statuses(status: str) -> list[str]:
    """The statuses an order can move to from `status`, in flow order (for the admin
    screen's buttons). update_order_status enforces the same rules."""
    if status not in ALLOWED_TRANSITIONS:
        raise ValidationError("Unknown order status.")
    return [s for s in ORDER_STATUSES if s in ALLOWED_TRANSITIONS[status]]


def update_order_status(admin: UserSession, order_id: int, new_status: str) -> OrderDetail:
    """Move an order to its next status. The trg_order_status trigger records the change
    in order_status_history; this function writes the admin audit entry.

    Cancelling puts the items back in stock and refunds (or voids) the payment.
    """
    require_admin(admin)
    if new_status not in ORDER_STATUSES:
        raise ValidationError("Unknown order status.")

    with get_session() as session:
        order = order_repository.get(session, order_id, for_update=True)
        if order is None:
            raise NotFoundError("Order not found.")
        old_status = order.status
        if new_status not in ALLOWED_TRANSITIONS[old_status]:
            raise ValidationError(f"Cannot change an order from {old_status} to {new_status}.")

        order.status = new_status
        if new_status == "cancelled":
            _restock_and_refund(session, order)
        if new_status == "delivered":
            _collect_cash_on_delivery(session, order)
        session.flush()  # sends the UPDATE -> trigger fires -> history row written

        audit_service.record_admin_action(
            session, admin, audit_service.STATUS_CHANGE, audit_service.ORDER, order.id,
            details=f"{old_status} -> {new_status}",
        )
        return _build_detail(session, order)


def _restock_and_refund(session: Session, order: Order) -> None:
    items = order_repository.list_items(session, order.id)
    # Same lock order as checkout (by product_id), so the two can't deadlock.
    stock = product_repository.lock_inventory(session, [i.product_id for i in items])
    for item in items:
        stock[item.product_id].stock += item.qty

    payment = order_repository.get_payment(session, order.id)
    if payment is not None:
        if payment.status == "success":
            payment.status = "refunded"
        elif payment.status == "pending":  # COD that was never collected
            payment.status = "failed"


def _collect_cash_on_delivery(session: Session, order: Order) -> None:
    payment = order_repository.get_payment(session, order.id)
    if payment is not None and payment.method == "cod" and payment.status == "pending":
        payment.status, payment.paid_at = "success", utcnow()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_summary(row) -> OrderSummary:
    o = row.Order
    return OrderSummary(o.id, o.created_at, o.status, o.total, int(row.item_count),
                        row.customer_name, row.customer_email)


def _build_detail(session: Session, order: Order) -> OrderDetail:
    session.refresh(order)  # pick up database defaults (created_at) and latest status
    lines = [
        OrderLine(i.product_id, i.name, i.qty, i.unit_price, i.unit_price * i.qty)
        for i in order_repository.list_items(session, order.id)
    ]
    payment = order_repository.get_payment(session, order.id)
    payment_info = (
        PaymentInfo(payment.method, payment.amount, payment.status, payment.paid_at)
        if payment else None
    )
    timeline = [
        StatusChange(h.old_status, h.new_status, h.changed_at)
        for h in order_repository.list_history(session, order.id)
    ]
    return OrderDetail(order.id, order.user_id, order.created_at, order.status, lines,
                       order.subtotal, order.discount, order.total, order.coupon_code,
                       payment_info, timeline)
