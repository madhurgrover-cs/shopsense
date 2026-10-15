"""Queries for orders, order items, payments and status history."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Row, func, select
from sqlalchemy.orm import Session

from app.models import Order, OrderItem, OrderStatusHistory, Payment, Product, User


def create_order(session: Session, user_id: int, subtotal: Decimal, discount: Decimal,
                 coupon_code: str | None) -> Order:
    """Insert an order with status 'placed'. The trg_order_status trigger logs the
    first status-history row automatically."""
    order = Order(user_id=user_id, status="placed", subtotal=subtotal, discount=discount,
                  total=subtotal - discount, coupon_code=coupon_code)
    session.add(order)
    session.flush()
    return order


def add_item(session: Session, order_id: int, product_id: int, qty: int,
             unit_price: Decimal) -> None:
    session.add(OrderItem(order_id=order_id, product_id=product_id, qty=qty,
                          unit_price=unit_price))


def add_payment(session: Session, order_id: int, method: str, amount: Decimal,
                status: str, paid_at: datetime | None) -> Payment:
    payment = Payment(order_id=order_id, method=method, amount=amount, status=status,
                      paid_at=paid_at)
    session.add(payment)
    session.flush()
    return payment


def get(session: Session, order_id: int, for_update: bool = False) -> Order | None:
    stmt = select(Order).where(Order.id == order_id)
    if for_update:
        stmt = stmt.with_for_update()
    return session.scalars(stmt).first()


def list_orders(session: Session, user_id: int | None = None, status: str | None = None,
                created_from: datetime | None = None,
                created_before: datetime | None = None) -> list[Row]:
    """(Order, item_count, customer_name, customer_email) rows, newest first.
    Optional filters: one user, one status, created_from <= created_at < created_before."""
    item_count = (
        select(func.coalesce(func.sum(OrderItem.qty), 0))
        .where(OrderItem.order_id == Order.id)
        .scalar_subquery()
    )
    stmt = (
        select(Order, item_count.label("item_count"), User.name.label("customer_name"),
               User.email.label("customer_email"))
        .join(User, User.id == Order.user_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    )
    if user_id is not None:
        stmt = stmt.where(Order.user_id == user_id)  # uses ix_orders_user_id_created_at
    if status is not None:
        stmt = stmt.where(Order.status == status)
    if created_from is not None:
        stmt = stmt.where(Order.created_at >= created_from)
    if created_before is not None:
        stmt = stmt.where(Order.created_at < created_before)
    return list(session.execute(stmt))


def list_items(session: Session, order_id: int) -> list[Row]:
    stmt = (
        select(OrderItem.product_id, OrderItem.qty, OrderItem.unit_price, Product.name)
        .join(Product, Product.id == OrderItem.product_id)
        .where(OrderItem.order_id == order_id)
        .order_by(OrderItem.id)
    )
    return list(session.execute(stmt))


def list_history(session: Session, order_id: int) -> list[OrderStatusHistory]:
    # Rows are written by the trigger, so we always query them fresh.
    stmt = (
        select(OrderStatusHistory)
        .where(OrderStatusHistory.order_id == order_id)
        .order_by(OrderStatusHistory.changed_at, OrderStatusHistory.id)
    )
    return list(session.scalars(stmt))


def get_payment(session: Session, order_id: int) -> Payment | None:
    stmt = select(Payment).where(Payment.order_id == order_id).order_by(Payment.id.desc())
    return session.scalars(stmt).first()
