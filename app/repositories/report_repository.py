"""Queries for the admin dashboard and the reports.

Dashboard = the four SQL views from the first migration (v_daily_revenue,
v_sales_by_category, v_top_products, v_low_stock). The views keep the reporting rules
(e.g. "cancelled orders don't count as sales") in the database, in one place.

Date-range reports can only partly use them: v_sales_by_category and v_top_products
add up ALL orders and have no date column to filter on. So the report queries below
repeat the same rules as those views, plus "order placed inside the date range".
Times are compared as timestamps (start <= created_at < before), so the index on
orders.created_at can be used.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Row, column, func, select, table
from sqlalchemy.orm import Session

from app.models import Category, Inventory, Order, OrderItem, Payment, Product, User

# The views, described just enough for SQLAlchemy to query them (they have no ORM
# models: they are read-only results, not tables we insert into).
v_daily_revenue = table("v_daily_revenue", column("day"), column("order_count"),
                        column("gross"), column("discount"), column("revenue"))
v_sales_by_category = table("v_sales_by_category", column("category_id"), column("category"),
                            column("order_count"), column("units_sold"), column("revenue"))
v_top_products = table("v_top_products", column("product_id"), column("product"),
                       column("category"), column("units_sold"), column("revenue"),
                       column("revenue_rank"))
v_low_stock = table("v_low_stock", column("product_id"), column("product"),
                    column("category"), column("stock"))

NOT_CANCELLED = Order.status != "cancelled"


# ---------------------------------------------------------------------------
# Dashboard (views)
# ---------------------------------------------------------------------------

def total_revenue(session: Session) -> Decimal:
    return session.scalar(select(func.coalesce(func.sum(v_daily_revenue.c.revenue), 0)))


def daily_revenue_since(session: Session, first_day: date) -> list[Row]:
    """(day, order_count, revenue) from first_day (IST) on, oldest first. Days without
    orders are missing; the service fills them with zeros."""
    stmt = (select(v_daily_revenue.c.day, v_daily_revenue.c.order_count,
                   v_daily_revenue.c.revenue)
            .where(v_daily_revenue.c.day >= first_day)
            .order_by(v_daily_revenue.c.day))
    return list(session.execute(stmt))


def sales_by_category(session: Session) -> list[Row]:
    stmt = select(v_sales_by_category).order_by(v_sales_by_category.c.revenue.desc(),
                                                v_sales_by_category.c.category)
    return list(session.execute(stmt))


def top_products(session: Session, limit: int) -> list[Row]:
    stmt = (select(v_top_products)
            .order_by(v_top_products.c.revenue_rank, v_top_products.c.product)
            .limit(limit))
    return list(session.execute(stmt))


def low_stock_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(v_low_stock))


def count_orders(session: Session) -> int:
    return session.scalar(select(func.count(Order.id)))


def count_customers(session: Session) -> int:
    return session.scalar(select(func.count(User.id)).where(User.role == "customer"))


# ---------------------------------------------------------------------------
# Reports for a date range
# ---------------------------------------------------------------------------

def _items_in_range(start: datetime, before: datetime):
    """Order items of non-cancelled orders placed in [start, before), as a subquery."""
    return (
        select(OrderItem.order_id, OrderItem.product_id, OrderItem.qty, OrderItem.unit_price)
        .join(Order, Order.id == OrderItem.order_id)
        .where(NOT_CANCELLED, Order.created_at >= start, Order.created_at < before)
        .subquery()
    )


def sales_by_category_between(session: Session, start: datetime, before: datetime) -> list[Row]:
    """Like v_sales_by_category, for one period: (category, order_count, units_sold,
    revenue). LEFT JOINs keep categories that sold nothing (shown as 0)."""
    items = _items_in_range(start, before)
    revenue = func.coalesce(func.sum(items.c.qty * items.c.unit_price), 0)
    stmt = (
        select(Category.name.label("category"),
               func.count(func.distinct(items.c.order_id)).label("order_count"),
               func.coalesce(func.sum(items.c.qty), 0).label("units_sold"),
               revenue.label("revenue"))
        .select_from(Category)
        .outerjoin(Product, Product.category_id == Category.id)
        .outerjoin(items, items.c.product_id == Product.id)
        .group_by(Category.id, Category.name)
        .order_by(revenue.desc(), Category.name)
    )
    return list(session.execute(stmt))


def top_products_between(session: Session, start: datetime, before: datetime,
                         limit: int) -> list[Row]:
    """Like v_top_products, for one period: (rank, product_id, product, category,
    units_sold, revenue), best-selling by revenue first."""
    items = _items_in_range(start, before)
    revenue = func.sum(items.c.qty * items.c.unit_price)
    stmt = (
        select(func.rank().over(order_by=revenue.desc()).label("rank"),
               Product.id.label("product_id"), Product.name.label("product"),
               Category.name.label("category"),
               func.sum(items.c.qty).label("units_sold"), revenue.label("revenue"))
        .select_from(items)
        .join(Product, Product.id == items.c.product_id)
        .join(Category, Category.id == Product.category_id)
        .group_by(Product.id, Product.name, Category.name)
        .order_by(revenue.desc(), Product.name)
        .limit(limit)
    )
    return list(session.execute(stmt))


def orders_between(session: Session, start: datetime, before: datetime) -> list[Row]:
    """Every order (any status) placed in [start, before), oldest first, with the
    customer, item count and payment method."""
    item_count = (select(func.coalesce(func.sum(OrderItem.qty), 0))
                  .where(OrderItem.order_id == Order.id).scalar_subquery())
    payment_method = (select(Payment.method).where(Payment.order_id == Order.id)
                      .order_by(Payment.id.desc()).limit(1).scalar_subquery())
    stmt = (
        select(Order, User.name.label("customer_name"), User.email.label("customer_email"),
               item_count.label("item_count"), payment_method.label("payment_method"))
        .join(User, User.id == Order.user_id)
        .where(Order.created_at >= start, Order.created_at < before)
        .order_by(Order.created_at, Order.id)
    )
    return list(session.execute(stmt))


def low_stock_products(session: Session) -> list[Row]:
    """(product_id, product, category, stock) from v_low_stock, lowest stock first."""
    stmt = select(v_low_stock).order_by(v_low_stock.c.stock, v_low_stock.c.product)
    return list(session.execute(stmt))


# ---------------------------------------------------------------------------
# Stock-out forecast
# ---------------------------------------------------------------------------

def daily_units_sold(session: Session, start: datetime, before: datetime) -> list[Row]:
    """(product_id, day, units) for non-cancelled orders placed in [start, before).
    `day` is the India calendar day, like v_daily_revenue."""
    day = func.date(func.timezone("Asia/Kolkata", Order.created_at)).label("day")
    stmt = (
        select(OrderItem.product_id, day, func.sum(OrderItem.qty).label("units"))
        .join(Order, Order.id == OrderItem.order_id)
        .where(NOT_CANCELLED, Order.created_at >= start, Order.created_at < before)
        .group_by(OrderItem.product_id, day)
    )
    return list(session.execute(stmt))


def active_products_with_stock(session: Session) -> list[Row]:
    """(product_id, product, category, stock) of every active product."""
    stmt = (
        select(Product.id.label("product_id"), Product.name.label("product"),
               Category.name.label("category"),
               func.coalesce(Inventory.stock, 0).label("stock"))
        .join(Category, Category.id == Product.category_id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .where(Product.is_active)
    )
    return list(session.execute(stmt))
