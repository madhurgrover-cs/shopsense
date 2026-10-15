"""Tests for the admin dashboard, the date-range reports and CSV / PDF export.

The database also holds the seed data, so dashboard tests compare BEFORE and AFTER
adding test orders (the difference must be exactly the test orders), and report tests
look at the test's own rows (a test category / product) or use a period with no seed
orders.
"""

import csv
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.exceptions import PermissionDeniedError, ValidationError
from app.services import report_service
from app.services.dto import Report
from app.services.validation import IST, today

FAR_FUTURE = date(2099, 1, 1)  # a period no seed order falls in


@pytest.fixture
def sales(factory, customer):
    """A test category with products A and B, and three orders placed today:
    delivered (A + B, ₹100 each), placed (A, ₹100) and cancelled (B, ₹999)."""
    cat_name = "Test Report Category"
    cat = factory.category(cat_name)
    a = factory.product(category_id=cat, name="Test Report Lamp", stock=50)
    b = factory.product(category_id=cat, name="Test Report Mug", stock=50)
    delivered = factory.order(customer.user_id, [a, b], unit_price="100.00")   # ₹200
    placed = factory.order(customer.user_id, [a], status="placed", unit_price="100.00")
    cancelled = factory.order(customer.user_id, [b], status="cancelled", unit_price="999.00")
    return {"category": cat_name, "a": a, "b": b, "delivered": delivered, "placed": placed,
            "cancelled": cancelled}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def test_dashboard_counts_new_orders_exactly(factory, admin, customer):
    before = report_service.get_dashboard(admin)
    pid = factory.product(stock=50)
    factory.order(customer.user_id, [pid], unit_price="250.00")
    factory.order(customer.user_id, [pid], status="cancelled", unit_price="999.00")
    after = report_service.get_dashboard(admin)

    assert after.total_revenue - before.total_revenue == Decimal("250.00")  # not cancelled
    assert after.order_count - before.order_count == 2                      # all orders
    assert after.daily_revenue[-1].day == today()
    assert after.daily_revenue[-1].revenue - before.daily_revenue[-1].revenue == 250
    assert after.customer_count == before.customer_count  # `customer` existed already


def test_dashboard_daily_revenue_has_every_day(admin):
    daily = report_service.get_dashboard(admin).daily_revenue
    assert len(daily) == report_service.DASHBOARD_DAYS
    assert [d.day for d in daily] == [today() - timedelta(days=29 - i) for i in range(30)]
    assert all(d.revenue >= 0 for d in daily)  # missing days are 0, not skipped


def test_dashboard_low_stock_and_top_products(factory, admin):
    before = report_service.get_dashboard(admin)
    factory.product(stock=3)                 # low
    factory.product(stock=3, active=False)   # deleted products don't count
    factory.product(stock=10)                # 10 is not "fewer than 10"
    after = report_service.get_dashboard(admin)
    assert after.low_stock_count == before.low_stock_count + 1
    assert len(after.top_products) <= report_service.DASHBOARD_TOP_PRODUCTS
    revenues = [p.revenue for p in after.top_products]
    assert revenues == sorted(revenues, reverse=True)


def test_dashboard_is_admin_only(customer):
    with pytest.raises(PermissionDeniedError):
        report_service.get_dashboard(customer)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def test_sales_by_category_report(admin, sales):
    report = report_service.sales_by_category_report(admin, today(), today())
    row = next(r for r in report.rows if r[0] == sales["category"])
    # Delivered + placed orders count; the cancelled ₹999 order does not.
    assert row == (sales["category"], 2, 3, Decimal("300.00"))
    assert report.columns == ["Category", "Orders", "Units sold", "Revenue"]
    assert report.totals[2] == sum(r[2] for r in report.rows)
    assert report.totals[3] == sum(r[3] for r in report.rows)
    assert report.money_columns == {3}


def test_sales_by_category_lists_categories_without_sales(admin, sales):
    report = report_service.sales_by_category_report(admin, FAR_FUTURE, FAR_FUTURE)
    row = next(r for r in report.rows if r[0] == sales["category"])
    assert row[1:] == (0, 0, Decimal("0"))


def test_report_date_range_uses_india_days(factory, admin, customer):
    """An order at 00:30 IST on day X belongs to day X, although it's still the
    previous day in UTC."""
    cat = factory.category("Test IST Category")
    pid = factory.product(category_id=cat)
    day = date(2099, 3, 10)
    factory.order(customer.user_id, [pid], unit_price="10.00",
                  created_at=datetime(2099, 3, 10, 0, 30, tzinfo=IST))  # 2099-03-09 19:00 UTC
    on_day = report_service.sales_by_category_report(admin, day, day)
    day_before = report_service.sales_by_category_report(admin, day - timedelta(days=1),
                                                         day - timedelta(days=1))
    assert next(r for r in on_day.rows if r[0] == "Test IST Category")[3] == Decimal("10.00")
    assert next(r for r in day_before.rows if r[0] == "Test IST Category")[3] == 0


def test_top_products_report(admin, sales):
    report = report_service.top_products_report(admin, today(), today(), limit=50)
    rows = {r[1]: r for r in report.rows}
    lamp, mug = rows["Test Report Lamp"], rows["Test Report Mug"]
    assert lamp[3:] == (2, Decimal("200.00"))   # delivered + placed order
    assert mug[3:] == (1, Decimal("100.00"))    # the cancelled one isn't counted
    assert lamp[0] < mug[0]                     # rank: higher revenue first
    assert len(report_service.top_products_report(admin, today(), today(), limit=1).rows) == 1


def test_order_history_report(admin, customer, sales):
    report = report_service.order_history_report(admin, today(), today())
    ours = {r[0]: r for r in report.rows
            if r[0] in (sales["delivered"], sales["placed"], sales["cancelled"])}
    assert len(ours) == 3                       # every status is listed
    row = ours[sales["delivered"]]
    assert (row[2], row[3], row[4], row[5], row[9]) == (
        customer.name, customer.email, "delivered", 2, Decimal("200.00"))
    kept = [r for r in report.rows if r[4] != "cancelled"]
    assert report.totals[9] == sum(r[9] for r in kept)  # cancelled excluded from the total
    created = [r[1] for r in report.rows]
    assert created == sorted(created)            # oldest first


def test_report_validation(admin, customer):
    with pytest.raises(ValidationError, match="on or before"):
        report_service.sales_by_category_report(admin, "2026-10-02", "2026-10-01")
    with pytest.raises(ValidationError, match="YYYY-MM-DD"):
        report_service.order_history_report(admin, "yesterday", "2026-10-01")
    with pytest.raises(ValidationError, match="3 years"):
        report_service.top_products_report(admin, "2020-01-01", "2026-01-01")
    with pytest.raises(ValidationError, match="Unknown report"):
        report_service.run_report(admin, "profits", "2026-10-01", "2026-10-02")
    with pytest.raises(PermissionDeniedError):
        report_service.sales_by_category_report(customer, "2026-10-01", "2026-10-02")


def test_run_report_by_name(admin):
    for kind in report_service.REPORTS:
        report = report_service.run_report(admin, kind, FAR_FUTURE, FAR_FUTURE)
        assert report.kind == kind and report.start == report.end == FAR_FUTURE


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

REPORT = Report(
    "sales_by_category", "Sales by category", date(2026, 10, 1), date(2026, 10, 7),
    ["Category", "Orders", "Units sold", "Revenue"],
    [("Books & Stationery", 3, 4, Decimal("1299.50")), ("Café <Specials>", 1, 1, Decimal("80"))],
    ("Total", None, 5, Decimal("1379.50")), money_columns=frozenset({3}), note="A note.")


def test_export_csv(admin, tmp_path):
    path = report_service.export_report(admin, REPORT, tmp_path, "csv")
    assert path.name == "sales_by_category_2026-10-01_to_2026-10-07.csv"
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM, so Excel reads UTF-8
    rows = list(csv.reader(raw.decode("utf-8-sig").splitlines()))
    assert rows == [["Category", "Orders", "Units sold", "Revenue"],
                    ["Books & Stationery", "3", "4", "1299.50"],  # raw numbers, no ₹
                    ["Café <Specials>", "1", "1", "80.00"],
                    ["Total", "", "5", "1379.50"]]


def test_export_pdf(admin, tmp_path):
    path = report_service.export_report(admin, REPORT, tmp_path, "pdf")
    assert path.suffix == ".pdf"
    data = path.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 1000


def test_export_never_overwrites(admin, tmp_path):
    first = report_service.export_report(admin, REPORT, tmp_path, "csv")
    second = report_service.export_report(admin, REPORT, tmp_path, "csv")
    assert first != second and second.name.endswith(" (2).csv")
    assert first.exists() and second.exists()


def test_export_errors(admin, customer, tmp_path):
    with pytest.raises(ValidationError, match="does not exist"):
        report_service.export_report(admin, REPORT, tmp_path / "missing", "csv")
    with pytest.raises(ValidationError, match="CSV or PDF"):
        report_service.export_report(admin, REPORT, tmp_path, "xlsx")
    with pytest.raises(PermissionDeniedError):
        report_service.export_report(customer, REPORT, tmp_path, "csv")
    assert list(tmp_path.iterdir()) == []


def test_export_empty_report(admin, tmp_path):
    empty = Report("top_products", "Top products", FAR_FUTURE, FAR_FUTURE,
                   ["Rank", "Product"], [])
    for file_format in ("csv", "pdf"):
        assert report_service.export_report(admin, empty, tmp_path, file_format).exists()
