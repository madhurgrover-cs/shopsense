"""Coupons, orders, order items, status history and (mock) payments."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column

if TYPE_CHECKING:
    from app.models.catalog import Product
    from app.models.user import User

ORDER_STATUSES = ("placed", "shipped", "delivered", "cancelled")
PAYMENT_METHODS = ("card", "upi", "cod", "wallet")
PAYMENT_STATUSES = ("pending", "success", "failed", "refunded")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    """Build the SQL text "column IN ('a', 'b')" from a Python tuple."""
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Coupon(Base):
    __tablename__ = "coupons"
    __table_args__ = (
        CheckConstraint("percent_off BETWEEN 1 AND 90", name="percent_off_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    percent_off: Mapped[int] = mapped_column(Integer)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(_in_list("status", ORDER_STATUSES), name="status_valid"),
        CheckConstraint("subtotal >= 0", name="subtotal_non_negative"),
        CheckConstraint("discount >= 0", name="discount_non_negative"),
        CheckConstraint("total = subtotal - discount", name="total_matches"),
        # Serves "my orders, newest first" and also acts as the index on user_id.
        Index("ix_orders_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # RESTRICT: never lose order history by deleting a customer.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(20), server_default="placed")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    discount: Mapped[Decimal] = mapped_column(Numeric(10, 2), server_default="0")
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # Plain text copy, not a FK: like unit_price, it records what was applied at
    # purchase time even if the coupon is later edited or removed.
    coupon_code: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = created_at_column()

    user: Mapped["User"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    status_history: Mapped[list["OrderStatusHistory"]] = relationship(
        back_populates="order", order_by="OrderStatusHistory.changed_at"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        # Also the index on order_id (leading column).
        UniqueConstraint("order_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    # RESTRICT: products are soft-deleted, so a sold product is never physically removed.
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )
    qty: Mapped[int] = mapped_column(Integer)
    # Price copied at purchase time, so later price changes don't rewrite old orders.
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    order: Mapped["Order"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()


class OrderStatusHistory(Base):
    """Filled ONLY by the database trigger trg_order_status (see the initial migration).
    Application code never inserts here directly."""

    __tablename__ = "order_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    old_status: Mapped[str | None] = mapped_column(String(20))  # NULL for the first entry
    new_status: Mapped[str] = mapped_column(String(20))
    changed_at: Mapped[datetime] = created_at_column()

    order: Mapped["Order"] = relationship(back_populates="status_history")


class Payment(Base):
    """Mock payment record. Never store card numbers, CVV or any card data."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(_in_list("method", PAYMENT_METHODS), name="method_valid"),
        CheckConstraint(_in_list("status", PAYMENT_STATUSES), name="status_valid"),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    method: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(String(20), server_default="success")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped["Order"] = relationship(back_populates="payments")
