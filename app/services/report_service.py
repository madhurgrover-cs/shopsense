"""Admin dashboard figures and the date-range reports (with CSV / PDF export).

Dashboard: KPI numbers plus the data for its three charts, read from the SQL views.
Reports: sales by category, top products and order history for a chosen period,
returned as a Report (columns + rows of raw values) that the GUI shows as a table and
report_export writes to a file.
"""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from app.db import get_session
from app.exceptions import ValidationError
from app.repositories import report_repository
from app.services import report_export
from app.services.auth_service import require_admin
from app.services.dto import CategorySales, Dashboard, DailyRevenue, ProductSales, Report
from app.services.user_session import UserSession
from app.services.validation import date_range, day_bounds, today

DASHBOARD_DAYS = 30         # revenue trend chart
DASHBOARD_TOP_PRODUCTS = 5
REPORT_TOP_PRODUCTS = 20
MAX_REPORT_DAYS = 366 * 3   # keeps one report to a sensible size
# Category / product revenue = price x quantity of the items sold. Coupon discounts
# apply to a whole order, not to single items, so they are not subtracted here (the
# order history report shows them).
ITEM_REVENUE_NOTE = "Revenue is item price x quantity, before coupon discounts."


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def get_dashboard(admin: UserSession) -> Dashboard:
    require_admin(admin)
    first_day = today() - timedelta(days=DASHBOARD_DAYS - 1)
    with get_session() as session:
        found = {r.day: r for r in report_repository.daily_revenue_since(session, first_day)}
        # One point per day, so days without sales show as 0 instead of being skipped
        # (a skipped day would make the line chart join two distant days directly).
        daily = []
        for offset in range(DASHBOARD_DAYS):
            day = first_day + timedelta(days=offset)
            row = found.get(day)
            daily.append(DailyRevenue(day, int(row.order_count) if row else 0,
                                      Decimal(row.revenue) if row else Decimal("0.00")))
        return Dashboard(
            total_revenue=Decimal(report_repository.total_revenue(session)),
            order_count=report_repository.count_orders(session),
            customer_count=report_repository.count_customers(session),
            low_stock_count=report_repository.low_stock_count(session),
            daily_revenue=daily,
            sales_by_category=[
                CategorySales(r.category, int(r.order_count), int(r.units_sold),
                              Decimal(r.revenue))
                for r in report_repository.sales_by_category(session)
            ],
            top_products=[
                ProductSales(int(r.revenue_rank), r.product_id, r.product, r.category,
                             int(r.units_sold), Decimal(r.revenue))
                for r in report_repository.top_products(session, DASHBOARD_TOP_PRODUCTS)
            ],
        )


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def _period(start, end):
    """Validated (start day, end day, start moment, moment after the end day)."""
    start_day, end_day = date_range(start, end)
    if (end_day - start_day).days >= MAX_REPORT_DAYS:
        raise ValidationError("Please choose a period of at most 3 years.")
    return (start_day, end_day, *day_bounds(start_day, end_day))


def sales_by_category_report(admin: UserSession, start, end) -> Report:
    """Orders, units and revenue per category for orders placed start..end (IST,
    both days included). Cancelled orders are left out, as in v_sales_by_category."""
    require_admin(admin)
    start_day, end_day, since, before = _period(start, end)
    with get_session() as session:
        rows = [(r.category, int(r.order_count), int(r.units_sold), Decimal(r.revenue))
                for r in report_repository.sales_by_category_between(session, since, before)]
    totals = ("Total", None, sum(r[2] for r in rows), sum((r[3] for r in rows), Decimal("0")))
    # Order count total is left empty: one order can contain several categories, so
    # adding up the per-category counts would count such orders more than once.
    return Report("sales_by_category", "Sales by category", start_day, end_day,
                  ["Category", "Orders", "Units sold", "Revenue"], rows, totals,
                  money_columns=frozenset({3}), note=ITEM_REVENUE_NOTE)


def top_products_report(admin: UserSession, start, end,
                        limit: int = REPORT_TOP_PRODUCTS) -> Report:
    """Best-selling products by revenue for orders placed start..end."""
    require_admin(admin)
    start_day, end_day, since, before = _period(start, end)
    with get_session() as session:
        rows = [(int(r.rank), r.product, r.category, int(r.units_sold), Decimal(r.revenue))
                for r in report_repository.top_products_between(session, since, before, limit)]
    return Report("top_products", f"Top {limit} products", start_day, end_day,
                  ["Rank", "Product", "Category", "Units sold", "Revenue"], rows,
                  money_columns=frozenset({4}), note=ITEM_REVENUE_NOTE)


def order_history_report(admin: UserSession, start, end) -> Report:
    """Every order placed start..end (any status), oldest first."""
    require_admin(admin)
    start_day, end_day, since, before = _period(start, end)
    with get_session() as session:
        rows = [
            (r.Order.id, r.Order.created_at, r.customer_name, r.customer_email,
             r.Order.status, int(r.item_count), r.payment_method or "", r.Order.coupon_code or "",
             r.Order.discount, r.Order.total)
            for r in report_repository.orders_between(session, since, before)
        ]
    # Revenue counts non-cancelled orders only, like everywhere else in the reports.
    kept = [r for r in rows if r[4] != "cancelled"]
    totals = (f"{len(rows)} orders", None, None, None, f"{len(kept)} not cancelled",
              sum(r[5] for r in kept), None, None,
              sum((r[8] for r in kept), Decimal("0")), sum((r[9] for r in kept), Decimal("0")))
    return Report("order_history", "Order history", start_day, end_day,
                  ["Order", "Placed", "Customer", "Email", "Status", "Items", "Payment",
                   "Coupon", "Discount", "Total"], rows, totals,
                  money_columns=frozenset({8, 9}))


REPORTS = {
    "sales_by_category": sales_by_category_report,
    "top_products": top_products_report,
    "order_history": order_history_report,
}


def run_report(admin: UserSession, kind: str, start, end) -> Report:
    """Run a report by its id (the GUI's report picker uses this)."""
    if kind not in REPORTS:
        raise ValidationError("Unknown report.")
    return REPORTS[kind](admin, start, end)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_report(admin: UserSession, report: Report, folder: str | Path,
                  file_format: str) -> Path:
    """Save the report as "csv" or "pdf" in `folder`; returns the file's path.
    An existing file is never overwritten: a number is added to the name instead."""
    require_admin(admin)
    if file_format not in report_export.WRITERS:
        raise ValidationError("Choose CSV or PDF.")
    folder = Path(folder)
    if not folder.is_dir():
        raise ValidationError(f"The folder {folder} does not exist.")
    path = report_export.free_path(folder, report_export.file_name(report, file_format))
    try:
        report_export.WRITERS[file_format](report, path)
    except OSError as error:  # read-only folder, disk full, file open in Excel, ...
        raise ValidationError(f"Could not save {path.name}: {error.strerror or error}.") from None
    return path
