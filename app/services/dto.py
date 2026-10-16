"""Plain read-only result objects that services return to the GUI.

Why not return SQLAlchemy objects? Once the service's session closes, touching an
unloaded relationship on an ORM object raises an error (or silently runs a query).
These dataclasses hold exactly the data a screen needs, already loaded, so the GUI
never deals with sessions (architecture rule) and can't modify data by accident.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
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
    sentiment_badge: str | None = None  # "Positive" / "Mixed" / "Negative" from reviews

    @property
    def in_stock(self) -> bool:
        return self.stock > 0


@dataclass(frozen=True)
class ProductDetail(ProductSummary):
    description: str = ""


@dataclass(frozen=True)
class SearchResults:
    query: str                    # what the user typed
    products: list[ProductSummary]  # best match first
    corrected_query: str | None = None  # what was searched instead, if spelling was fixed


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
    customer_name: str | None = None   # filled in admin lists only
    customer_email: str | None = None


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


@dataclass(frozen=True)
class ReviewInfo:
    id: int
    product_id: int
    product_name: str
    user_id: int
    user_name: str
    rating: int
    comment: str | None
    sentiment_score: float | None  # VADER compound score, -1..1; None if no comment
    created_at: datetime


@dataclass(frozen=True)
class ProductSentiment:
    product_id: int
    review_count: int
    avg_rating: float | None
    avg_score: float | None
    badge: str | None  # "Positive" / "Mixed" / "Negative"; None without scored reviews


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuditEntry:
    id: int
    created_at: datetime
    user_id: int | None
    user_name: str | None  # None if that user was deleted later
    action: str
    entity: str
    entity_id: int | None
    details: str | None


@dataclass(frozen=True)
class CustomerSummary:
    id: int
    name: str
    email: str
    joined_at: datetime
    order_count: int        # all orders, including cancelled
    total_spent: Decimal    # cancelled orders don't count
    last_order_at: datetime | None
    is_locked: bool         # locked out after too many failed logins


@dataclass(frozen=True)
class DailyRevenue:
    day: date
    order_count: int
    revenue: Decimal


@dataclass(frozen=True)
class CategorySales:
    category: str
    order_count: int
    units_sold: int
    revenue: Decimal


@dataclass(frozen=True)
class ProductSales:
    rank: int
    product_id: int
    product: str
    category: str
    units_sold: int
    revenue: Decimal


@dataclass(frozen=True)
class StockForecast:
    """When a product is expected to run out (see app/ai/forecast.py)."""
    product_id: int
    product: str
    category: str
    stock: int
    velocity: float          # expected units sold per day (recent days weigh more)
    days_left: float         # stock / velocity
    run_out_date: date
    reorder_qty: int         # units to order to cover the next 30 days


@dataclass(frozen=True)
class Dashboard:
    total_revenue: Decimal   # all non-cancelled orders
    order_count: int         # all orders
    customer_count: int
    low_stock_count: int     # active products with fewer than 10 in stock
    daily_revenue: list[DailyRevenue]   # one entry per day, oldest first, gaps = 0
    sales_by_category: list[CategorySales]
    top_products: list[ProductSales]
    run_out_soon_count: int = 0          # products expected to run out within 14 days
    running_out_soon: list[StockForecast] = field(default_factory=list)  # most urgent 5


@dataclass(frozen=True)
class Report:
    """A table of results the admin can view and export (CSV / PDF).

    rows hold raw values (int, Decimal, str, datetime), not display text, so a CSV
    opened in Excel gets real numbers. `kind` is the report's id, used in file names.
    """
    kind: str
    title: str
    start: date
    end: date
    columns: list[str]
    rows: list[tuple]
    totals: tuple | None = None   # optional last "Total" row, same length as columns
    money_columns: frozenset = field(default_factory=frozenset)  # column indexes in ₹
    note: str = ""                # extra explanation shown under the title

    @property
    def period(self) -> str:
        return f"{self.start:%d %b %Y} to {self.end:%d %b %Y}"
