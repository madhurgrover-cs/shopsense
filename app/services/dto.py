"""Plain read-only result objects that services return to the GUI.

Why not return SQLAlchemy objects? Once the service's session closes, touching an
unloaded relationship on an ORM object raises an error (or silently runs a query).
These dataclasses hold exactly the data a screen needs, already loaded, so the GUI
never deals with sessions (architecture rule) and can't modify data by accident.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class CategoryInfo:
    id: int
    name: str
    product_count: int  # active products only


@dataclass(frozen=True)
class ProductSummary:
    id: int
    name: str
    category_id: int
    category: str
    price: Decimal
    stock: int
    avg_rating: float | None  # None when there are no reviews yet
    review_count: int
    is_active: bool

    @property
    def in_stock(self) -> bool:
        return self.stock > 0


@dataclass(frozen=True)
class ProductDetail(ProductSummary):
    description: str


@dataclass(frozen=True)
class CouponInfo:
    code: str
    percent_off: int
    valid_until: datetime
    is_active: bool


@dataclass(frozen=True)
class CartLine:
    product_id: int
    name: str
    unit_price: Decimal  # current price; it is copied into the order at checkout
    qty: int
    line_total: Decimal
    stock: int
    is_active: bool      # False if the admin removed the product after it was added


@dataclass(frozen=True)
class CartView:
    lines: list[CartLine]
    subtotal: Decimal
    coupon: CouponInfo | None
    discount: Decimal
    total: Decimal

    @property
    def item_count(self) -> int:
        return sum(line.qty for line in self.lines)

    @property
    def is_empty(self) -> bool:
        return not self.lines


@dataclass(frozen=True)
class OrderSummary:
    id: int
    created_at: datetime
    status: str
    total: Decimal
    item_count: int


@dataclass(frozen=True)
class OrderLine:
    product_id: int
    name: str
    qty: int
    unit_price: Decimal  # the price paid, which may differ from today's price
    line_total: Decimal


@dataclass(frozen=True)
class StatusChange:
    old_status: str | None
    new_status: str
    changed_at: datetime


@dataclass(frozen=True)
class PaymentInfo:
    method: str
    amount: Decimal
    status: str
    paid_at: datetime | None


@dataclass(frozen=True)
class OrderDetail:
    id: int
    user_id: int
    created_at: datetime
    status: str
    lines: list[OrderLine]
    subtotal: Decimal
    discount: Decimal
    total: Decimal
    coupon_code: str | None
    payment: PaymentInfo | None
    timeline: list[StatusChange]  # oldest first, written by the trg_order_status trigger
