"""GUI tests for the admin screens: the real (hidden) window with every service the
admin screens call replaced by fakes, so no database is needed and nothing is written.
They check each screen shows the service data, and that every action calls the right
service with the right values (the services themselves are tested separately)."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.exceptions import ValidationError
from app.gui.screens.admin import coupons as coupons_screen
from app.gui.screens.admin import products as products_screen
from app.gui.widgets.charts import compact_inr
from app.gui.widgets.dialogs import FormDialog
from app.gui.widgets.table import Column, DataTable
from app.services import (
    audit_service, catalog_service, coupon_service, order_service, report_service,
    review_service, user_service,
)
from app.services.dto import (
    AuditEntry, CategoryInfo, CategorySales, CouponInfo, CustomerSummary, Dashboard,
    DailyRevenue, OrderDetail, OrderLine, OrderSummary, PaymentInfo, ProductDetail,
    ProductSales, ProductSummary, Report, ReviewInfo, StatusChange,
)
from tests.test_gui_smoke import ADMIN, login_as, pump, texts

NOW = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
LAMP = ProductSummary(1, "Test Desk Lamp", 1, "Home", Decimal("999.00"), 40, 4.0, 3, True)
MUG = ProductSummary(2, "Test Coffee Mug", 1, "Home", Decimal("299.00"), 4, None, 0, True)
OLD = ProductSummary(3, "Test Old Radio", 2, "Gadgets", Decimal("1500.00"), 0, None, 0, False)
PLACED = OrderSummary(41, NOW, "placed", Decimal("999.00"), 1, "Tara Dhar", "tara@example.com")
DONE = OrderSummary(42, NOW, "delivered", Decimal("299.00"), 1, "Ravi Iyer", "ravi@example.com")
REPORT = Report("sales_by_category", "Sales by category", date(2026, 10, 1), date(2026, 10, 7),
                ["Category", "Orders", "Units sold", "Revenue"],
                [("Home", 2, 3, Decimal("1298.00")), ("Gadgets", 0, 0, Decimal("0"))],
                ("Total", None, 3, Decimal("1298.00")), money_columns=frozenset({3}))


def order_detail(summary: OrderSummary) -> OrderDetail:
    return OrderDetail(
        summary.id, 7, NOW, summary.status,
        [OrderLine(1, "Test Desk Lamp", 1, summary.total, summary.total)],
        summary.total, Decimal("0.00"), summary.total, None,
        PaymentInfo("upi", summary.total, "success", NOW),
        [StatusChange(None, "placed", NOW)])


class Calls(list):
    """Records (function name, args) of every faked service call that changes data."""

    def recorder(self, name, result=None):
        def fake(*args, **kwargs):
            self.append((name, args[1:], kwargs))  # args[0] is always the admin session
            return result(*args) if callable(result) else result
        return fake

    def names(self):
        return [name for name, _args, _kwargs in self]


@pytest.fixture
def calls(monkeypatch):
    calls = Calls()
    s = monkeypatch.setattr
    s(report_service, "get_dashboard", lambda admin: Dashboard(
        Decimal("123456.50"), 501, 50, 7,
        [DailyRevenue(date(2026, 10, d), 2, Decimal(d * 100)) for d in range(1, 31)],
        [CategorySales("Home", 10, 12, Decimal("5000")),
         CategorySales("Gadgets", 3, 3, Decimal("900"))],
        [ProductSales(1, 1, "Test Desk Lamp", "Home", 5, Decimal("4995"))]))
    # Products
    s(catalog_service, "list_categories",
      lambda: [CategoryInfo(1, "Home", 2), CategoryInfo(2, "Gadgets", 0)])
    s(catalog_service, "list_all_products", lambda admin: [LAMP, MUG, OLD])
    s(catalog_service, "get_product_detail",
      lambda pid: ProductDetail(**{**LAMP.__dict__, "description": "A bright lamp."}))
    s(catalog_service, "create_product", calls.recorder(
        "create_product", lambda *a: ProductDetail(**{**LAMP.__dict__, "id": 9})))
    s(catalog_service, "update_product", calls.recorder(
        "update_product", ProductDetail(**{**LAMP.__dict__, "description": ""})))
    s(catalog_service, "update_stock", calls.recorder("update_stock", 25))
    s(catalog_service, "delete_product", calls.recorder("delete_product"))
    s(catalog_service, "restore_product", calls.recorder("restore_product"))
    # Orders
    s(order_service, "list_all_orders", calls.recorder("list_all_orders", [PLACED, DONE]))
    s(order_service, "get_order_detail", lambda admin, oid: order_detail(
        PLACED if oid == PLACED.id else DONE))
    s(order_service, "update_order_status", calls.recorder(
        "update_order_status", lambda admin, oid, status: order_detail(
            OrderSummary(oid, NOW, status, PLACED.total, 1))))
    # Coupons, reviews, reports, users, audit
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    s(coupon_service, "list_coupons", lambda admin: [
        CouponInfo("WELCOME10", 10, future, True), CouponInfo("OLD5", 5, NOW, True),
        CouponInfo("GONE", 20, future, False)])
    s(coupon_service, "create_coupon", calls.recorder(
        "create_coupon", CouponInfo("SUMMER20", 20, future, True)))
    s(coupon_service, "deactivate_coupon", calls.recorder(
        "deactivate_coupon", CouponInfo("WELCOME10", 10, future, False)))
    s(review_service, "list_flagged_reviews", lambda admin: [
        ReviewInfo(5, 1, "Test Desk Lamp", 7, "Tara Dhar", 1,
                   "Broke on day one.\nTerrible.", -0.84, NOW)])
    s(report_service, "run_report", calls.recorder("run_report", REPORT))
    s(user_service, "list_customers", lambda admin: [
        CustomerSummary(7, "Tara Dhar", "tara@example.com", NOW, 18, Decimal("45000"), NOW,
                        False),
        CustomerSummary(8, "Ravi Iyer", "ravi@example.com", NOW, 0, Decimal("0"), None, True)])
    s(audit_service, "list_recent", lambda admin, limit: [
        AuditEntry(2, NOW, 1, "Admin One", "status_change", "order", 41, "placed -> shipped"),
        AuditEntry(1, NOW, 1, "Admin One", "update", "stock", 1, "stock: 3 -> 40")])
    return calls


@pytest.fixture
def admin_window(gui_app, calls, monkeypatch):
    """The shared window, logged in as an admin (and logged out afterwards)."""
    if gui_app.user:
        gui_app.logout()
    gui_app.confirm_answer = True
    login_as(gui_app, ADMIN, monkeypatch)
    yield gui_app
    gui_app.logout()


@pytest.fixture
def dialogs(monkeypatch):
    """Every FormDialog the screens open, so a test can fill it in and press Save."""
    opened = []

    def recording(*args, **kwargs):
        opened.append(FormDialog(*args, **kwargs))
        return opened[-1]
    monkeypatch.setattr(products_screen, "FormDialog", recording)
    monkeypatch.setattr(coupons_screen, "FormDialog", recording)
    return opened


def show(window, key, **kwargs):
    window.navigate(key, **kwargs)
    pump(window)
    return window._screens[key]


def select(window, table, key) -> None:
    """Select a row like a click does. The selection event is queued, so let Tk deliver
    it first, then wait for whatever background task it started."""
    table.select(key)
    window.update()
    pump(window)


# ---------------------------------------------------------------------------
# Login, sidebar, dashboard
# ---------------------------------------------------------------------------

def test_admin_gets_admin_screens_and_dashboard(admin_window):
    w = admin_window
    assert w._current == "admin_dashboard"
    assert list(w._screens) == ["admin_dashboard", "admin_products", "admin_orders",
                                "admin_coupons", "admin_reviews", "admin_reports",
                                "admin_users", "admin_audit"]
    assert w._ai_status.cget("text") == ""  # admins don't preload the search model
    dashboard = w._screens["admin_dashboard"]
    assert dashboard.kpis["revenue"].value.cget("text") == "₹123,456.50"
    assert dashboard.kpis["orders"].value.cget("text") == "501"
    assert dashboard.kpis["customers"].value.cget("text") == "50"
    assert dashboard.kpis["low_stock"].value.cget("text") == "7"
    for chart in (dashboard.trend, dashboard.categories, dashboard.top):
        assert len(chart.figure.axes) == 1  # each chart was drawn
    assert len(dashboard.trend.figure.axes[0].lines[0].get_xdata()) == 30


def test_customer_screens_are_gone_for_admin(admin_window):
    assert "shop" not in admin_window._screens and "cart" not in admin_window._screens


def test_logout_removes_admin_screens(admin_window):
    admin_window.logout()
    assert set(admin_window._screens) == {"login", "register"}


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

def test_products_table_and_filters(admin_window):
    screen = show(admin_window, "admin_products")
    assert [p.id for p in screen.table.items] == [1, 2, 3]  # inactive ones included
    assert screen._count.cget("text") == "3 of 3 products"

    screen._search.insert(0, "mug")
    screen._filter()
    assert [p.id for p in screen.table.items] == [MUG.id]
    screen._search.delete(0, "end")
    for show_value, expected in (("Deleted", [3]), ("Low stock", [2]), ("Active", [1, 2])):
        screen._show.set(show_value)
        screen._filter()
        assert [p.id for p in screen.table.items] == expected, show_value


def test_low_stock_card_opens_filtered_products(admin_window):
    screen = show(admin_window, "admin_products", show="Low stock")
    assert [p.id for p in screen.table.items] == [MUG.id]


def test_product_buttons_follow_selection(admin_window):
    screen = show(admin_window, "admin_products")
    assert screen._edit.cget("state") == "disabled"
    select(admin_window, screen.table, LAMP.id)
    assert screen._delete.cget("state") == "normal" and screen._restore.cget("state") == "disabled"
    select(admin_window, screen.table, OLD.id)
    assert screen._delete.cget("state") == "disabled" and screen._restore.cget("state") == "normal"


def test_add_product_sends_form_to_service(admin_window, calls, dialogs):
    screen = show(admin_window, "admin_products")
    screen._add()
    dialog = dialogs[-1]
    for key, value in {"name": "Test Lantern", "category": "Gadgets", "price": "450.50",
                       "stock": "12", "description": "Solar lantern."}.items():
        dialog.set_value(key, value)
    dialog.submit()
    pump(admin_window)
    assert calls[-1] == ("create_product", (2, "Test Lantern", "Solar lantern.", "450.50", "12"),
                         {})
    assert not dialog.winfo_exists() and admin_window.popups[-1] == "Product added"


def test_form_error_keeps_dialog_open(admin_window, dialogs, monkeypatch):
    def invalid(*args):
        raise ValidationError("Price must be greater than zero.")
    monkeypatch.setattr(catalog_service, "create_product", invalid)
    screen = show(admin_window, "admin_products")
    screen._add()
    dialog = dialogs[-1]
    dialog.set_value("name", "Test Freebie")
    dialog.set_value("price", "0")
    dialog.submit()
    pump(admin_window)
    assert admin_window.popups[-1] == "Please check your input"
    assert dialog.winfo_exists() and dialog.submit_button.cget("state") == "normal"
    assert dialog.values()["name"] == "Test Freebie"  # what was typed is kept
    dialog.destroy()


def test_edit_product_prefills_and_saves(admin_window, calls, dialogs):
    screen = show(admin_window, "admin_products")
    screen.table.select(LAMP.id)
    screen._edit_selected()
    pump(admin_window)
    dialog = dialogs[-1]
    assert dialog.values() == {"name": "Test Desk Lamp", "category": "Home",
                               "price": "999.00", "description": "A bright lamp."}
    dialog.set_value("price", "899")
    dialog.submit()
    pump(admin_window)
    name, args, kwargs = calls[-1]
    assert (name, args) == ("update_product", (LAMP.id,))
    assert kwargs == {"name": "Test Desk Lamp", "description": "A bright lamp.",
                      "price": "899", "category_id": 1}
    assert admin_window.popups[-1] == "Product saved"


def test_update_stock(admin_window, calls, dialogs):
    screen = show(admin_window, "admin_products")
    screen.table.select(MUG.id)
    screen._update_stock()
    dialogs[-1].set_value("stock", "25")
    dialogs[-1].submit()
    pump(admin_window)
    assert calls[-1][:2] == ("update_stock", (MUG.id, "25"))
    assert admin_window.popups[-1] == "Stock updated"


def test_delete_needs_confirmation_and_restore_does_not(admin_window, calls):
    screen = show(admin_window, "admin_products")
    screen.table.select(LAMP.id)
    admin_window.confirm_answer = False  # the admin clicks Cancel
    screen._delete_selected()
    pump(admin_window)
    assert admin_window.confirms[-1] == "Delete product?" and "delete_product" not in calls.names()

    admin_window.confirm_answer = True
    screen._delete_selected()
    pump(admin_window)
    assert calls[-1][:2] == ("delete_product", (LAMP.id,))

    screen.table.select(OLD.id)
    confirms = len(admin_window.confirms)
    screen._restore_selected()
    pump(admin_window)
    assert calls[-1][:2] == ("restore_product", (OLD.id,))
    assert len(admin_window.confirms) == confirms  # restoring asks nothing


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def test_orders_list_uses_filters(admin_window, calls):
    screen = show(admin_window, "admin_orders")
    name, _args, kwargs = calls[-1]
    assert name == "list_all_orders" and kwargs["status"] is None
    assert kwargs["date_from"] and kwargs["date_to"]  # default: last 30 days
    assert "2 orders" in screen._count.cget("text")
    assert [o.id for o in screen.table.items] == [PLACED.id, DONE.id]

    screen._status.set("Shipped")
    screen._dates.set("2026-10-01", "2026-10-07")
    screen.reload()
    pump(admin_window)
    assert calls[-1][2] == {"status": "shipped", "date_from": "2026-10-01",
                            "date_to": "2026-10-07"}
    screen._dates._preset("All")
    pump(admin_window)
    assert calls[-1][2]["date_from"] is None and calls[-1][2]["date_to"] is None


def test_order_detail_shows_allowed_next_statuses(admin_window):
    screen = show(admin_window, "admin_orders")
    select(admin_window, screen.table, PLACED.id)
    on_screen = texts(screen._detail)
    for expected in ("Order #41", "Tara Dhar · tara@example.com", "Mark as shipped",
                     "Cancel order", "Placed", "Test Desk Lamp"):
        assert expected in on_screen, expected
    assert "Mark as delivered" not in on_screen  # placed can't jump to delivered

    select(admin_window, screen.table, DONE.id)
    on_screen = texts(screen._detail)
    assert not {"Mark as shipped", "Mark as delivered", "Cancel order"} & set(on_screen)
    assert any("can't change" in t for t in on_screen)


def test_cancelling_an_order_needs_confirmation(admin_window, calls):
    screen = show(admin_window, "admin_orders")
    select(admin_window, screen.table, PLACED.id)
    detail = order_detail(PLACED)

    admin_window.confirm_answer = False
    screen._change_status(detail, "cancelled")
    pump(admin_window)
    assert admin_window.confirms[-1] == "Cancel order #41?"
    assert "update_order_status" not in calls.names()

    admin_window.confirm_answer = True
    screen._change_status(detail, "cancelled")
    pump(admin_window)
    assert ("update_order_status", (41, "cancelled"), {}) in calls


def test_shipping_an_order_needs_no_confirmation(admin_window, calls):
    screen = show(admin_window, "admin_orders")
    select(admin_window, screen.table, PLACED.id)
    confirms = len(admin_window.confirms)
    screen._change_status(order_detail(PLACED), "shipped")
    pump(admin_window)
    assert ("update_order_status", (41, "shipped"), {}) in calls
    assert len(admin_window.confirms) == confirms
    on_screen = texts(screen._detail)  # the detail shows the new status and next step
    assert " Shipped " in on_screen and "Mark as delivered" in on_screen


# ---------------------------------------------------------------------------
# Coupons, reviews, reports, customers, audit log
# ---------------------------------------------------------------------------

def test_coupons_list_create_and_deactivate(admin_window, calls, dialogs):
    screen = show(admin_window, "admin_coupons")
    states = {c.code: coupons_screen.coupon_state(c) for c in screen.table.items}
    assert states == {"WELCOME10": "Active", "OLD5": "Expired", "GONE": "Deactivated"}

    screen._create()
    dialog = dialogs[-1]
    assert dialog.values()["percent_off"] == "10" and dialog.values()["valid_until"]
    dialog.set_value("code", "summer20")
    dialog.set_value("percent_off", "20")
    dialog.set_value("valid_until", "2099-01-01")
    dialog.submit()
    pump(admin_window)
    assert calls[-1][:2] == ("create_coupon", ("summer20", "20", "2099-01-01"))
    assert admin_window.popups[-1] == "Coupon created"

    select(admin_window, screen.table, "GONE")
    assert screen._deactivate.cget("state") == "disabled"  # already inactive
    screen.table.select("WELCOME10")
    screen._deactivate_selected()
    pump(admin_window)
    assert admin_window.confirms[-1] == "Deactivate WELCOME10?"
    assert calls[-1][:2] == ("deactivate_coupon", ("WELCOME10",))


def test_flagged_reviews(admin_window):
    screen = show(admin_window, "admin_reviews")
    assert [r.id for r in screen.table.items] == [5]
    assert screen.table.tree.item("5")["values"][0] == "-0.84"
    select(admin_window, screen.table, 5)
    assert screen._detail_text.cget("text") == "Broke on day one.\nTerrible."
    assert "Test Desk Lamp" in screen._detail_title.cget("text")


def test_reports_run_and_export(admin_window, calls, tmp_path, monkeypatch):
    screen = show(admin_window, "admin_reports")
    assert calls[-1][:2] == ("run_report", ("sales_by_category", *screen._dates.get()))
    assert len(screen.table.items) == 2
    assert screen.table.tree.item("0")["values"][-1] == "₹1,298.00"
    assert "Revenue: ₹1,298.00" in screen._totals.cget("text")

    screen._kind.set("Order history")
    screen.run()
    pump(admin_window)
    assert calls[-1][1][0] == "order_history"

    monkeypatch.setattr(admin_window, "ask_folder", lambda title: "")  # picker cancelled
    screen._export("csv")
    pump(admin_window)
    assert list(tmp_path.iterdir()) == []

    monkeypatch.setattr(admin_window, "ask_folder", lambda title: str(tmp_path))
    screen._export("csv")
    pump(admin_window, timeout=30)
    screen._export("pdf")
    pump(admin_window, timeout=30)  # the first PDF loads reportlab and its font
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["sales_by_category_2026-10-01_to_2026-10-07.csv",
                     "sales_by_category_2026-10-01_to_2026-10-07.pdf"]
    assert admin_window.popups[-1] == "Report saved"


def test_customers_are_listed_read_only(admin_window):
    screen = show(admin_window, "admin_users")
    values = screen.table.tree.item("7")["values"]
    assert values[0] == "Tara Dhar" and values[3] == 18 and values[4] == "₹45,000.00"
    assert screen.table.tree.item("8")["values"][-1] == "Locked"
    screen._search.insert(0, "ravi")
    screen._filter()
    assert [c.id for c in screen.table.items] == [8]
    assert not [t for t in texts(screen) if t in ("Edit", "Delete", "Save")]  # read-only


def test_audit_log(admin_window):
    screen = show(admin_window, "admin_audit")
    first = screen.table.tree.item("2")["values"]
    assert first[1:5] == ["Admin One", "status change", "order", 41]
    screen._entity.set("Stock")
    screen._filter()
    assert [e.id for e in screen.table.items] == [1]


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

def test_data_table_sorting(gui_app):
    rows = [(1, "b", 3), (2, "a", None), (3, "c", 1)]
    table = DataTable(gui_app, [Column("Name", 100, lambda r: r[1]),
                                Column("Score", 100, lambda r: r[2], sort=lambda r: r[2])])
    table.set_items(rows, key=lambda r: r[0])
    table.sort_by(0)
    assert [r[0] for r in table.items] == [2, 1, 3]
    table.sort_by(0)  # same header again: reversed
    assert [r[0] for r in table.items] == [3, 1, 2]
    table.sort_by(1)
    assert [r[0] for r in table.items] == [3, 1, 2]   # empty score last
    table.sort_by(1)
    assert [r[0] for r in table.items] == [1, 3, 2]   # ...also when descending
    table.select(1)
    table.set_items(rows[:2], key=lambda r: r[0])     # reload keeps the selection
    assert table.selected == rows[0]
    table.destroy()


def test_compact_rupee_labels():
    assert [compact_inr(v) for v in (950, 12_500, 4_20_000, 1_30_00_000, 10_000)] == [
        "₹950", "₹12.5k", "₹4.2L", "₹1.3Cr", "₹10k"]
