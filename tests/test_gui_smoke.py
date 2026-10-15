"""GUI smoke tests: the real main window (hidden) with services replaced by fakes, so
no database or AI model is needed. They check the screens build, navigation and
login/logout work, and data from services ends up on screen."""

import time
from datetime import datetime, timezone
from decimal import Decimal

import customtkinter as ctk
import pytest

from app.exceptions import InvalidCredentialsError, OutOfStockError
from app.gui.screens import cart as cart_screen
from app.gui.screens import login as login_screen
from app.gui.screens import orders as orders_screen
from app.gui.screens import product as product_screen
from app.gui.screens import shop as shop_screen
from app.services.dto import (
    CartLine, CartView, CategoryInfo, OrderDetail, OrderLine, OrderSummary, PaymentInfo,
    ProductDetail, ProductSentiment, ProductSummary, ReviewInfo, StatusChange,
)
from app.services.user_session import UserSession

NOW = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
CUSTOMER = UserSession(7, "Tara Dhar", "tara@example.com", "customer")
ADMIN = UserSession(1, "Admin One", "admin1@example.com", "admin")
HOODIE = ProductSummary(1, "Test Fleece Hoodie", 1, "Clothing", Decimal("1299.00"), 5, 4.5, 2,
                        True, "Positive")
SOCKS = ProductSummary(2, "Test Sports Socks", 2, "Footwear", Decimal("339.00"), 40, None, 0,
                       True, None)


def pump(window, until=None, timeout=5.0) -> None:
    """Process events until until() is true (or, without until, until no task runs)."""
    until = until or (lambda: not window.tasks.busy)
    deadline = time.time() + timeout
    while not until():
        assert time.time() < deadline, "timed out"
        window.update()
        time.sleep(0.005)
    window.update()


def texts(widget) -> list[str]:
    """Every label/button text inside a widget (to check what is on screen)."""
    found = []
    for child in widget.winfo_children():
        if isinstance(child, (ctk.CTkLabel, ctk.CTkButton)):
            found.append(child.cget("text"))
        found += texts(child)
    return found


@pytest.fixture
def window(gui_app):
    """The shared session window (see conftest.gui_app)."""
    return gui_app


@pytest.fixture
def fake_services(monkeypatch):
    """Fake every service the customer screens call."""
    s = monkeypatch.setattr
    s(shop_screen.catalog_service, "list_categories",
      lambda: [CategoryInfo(1, "Clothing", 1), CategoryInfo(2, "Footwear", 1)])
    s(shop_screen.catalog_service, "browse_products",
      lambda category_id=None: [p for p in (HOODIE, SOCKS)
                                if category_id in (None, p.category_id)])
    s(shop_screen.catalog_service, "search_products", lambda query, limit: [SOCKS])
    s(shop_screen.system_service, "is_search_model_loaded", lambda: True)
    detail = ProductDetail(**{**HOODIE.__dict__, "description": "Warm fleece."})
    s(product_screen.catalog_service, "get_product_detail", lambda pid: detail)
    s(product_screen.catalog_service, "frequently_bought_together", lambda pid, n: [SOCKS])
    s(product_screen.catalog_service, "similar_products", lambda pid, n: [])
    s(product_screen.review_service, "get_product_sentiment",
      lambda pid: ProductSentiment(pid, 2, 4.5, 0.6, "Positive"))
    s(product_screen.review_service, "list_product_reviews",
      lambda pid: [ReviewInfo(1, pid, "Test Fleece Hoodie", 9, "Ravi", 5, "Very warm!", 0.6, NOW)])
    order = OrderDetail(
        42, CUSTOMER.user_id, NOW, "delivered",
        [OrderLine(1, "Test Fleece Hoodie", 1, Decimal("1299.00"), Decimal("1299.00"))],
        Decimal("1299.00"), Decimal("0.00"), Decimal("1299.00"), None,
        PaymentInfo("upi", Decimal("1299.00"), "success", NOW),
        [StatusChange(None, "placed", NOW), StatusChange("placed", "shipped", NOW),
         StatusChange("shipped", "delivered", NOW)])
    s(orders_screen.order_service, "list_orders",
      lambda user: [OrderSummary(42, NOW, "delivered", Decimal("1299.00"), 1)])
    s(orders_screen.order_service, "get_order_detail", lambda user, oid: order)
    s(orders_screen.review_service, "reviewable_products", lambda user, oid: {1})


def login_as(window, user, monkeypatch):
    monkeypatch.setattr(login_screen.auth_service, "login", lambda email, password: user)
    screen = window._screens["login"]
    screen._email.delete(0, "end")
    screen._email.insert(0, user.email)
    screen._password.insert(0, "password123")
    screen._submit()
    pump(window)


# ---------------------------------------------------------------------------

def test_guest_sees_login_and_register(window):
    if window.user:
        window.logout()
    assert set(window._screens) == {"login", "register"}
    assert window._current == "login"
    window.navigate("register")
    assert window._title.cget("text") == "Create account"
    window.navigate("login")


def test_wrong_password_shows_popup_and_stays_on_login(window, monkeypatch):
    def fail(email, password):
        raise InvalidCredentialsError()
    monkeypatch.setattr(login_screen.auth_service, "login", fail)
    screen = window._screens["login"]
    screen._email.insert(0, "x@example.com")
    screen._password.insert(0, "nope")
    screen._submit()
    pump(window)
    assert window.popups[-1] == "Login failed"
    assert window._current == "login" and screen._password.get() == ""


def test_customer_login_opens_shop_with_cards(window, fake_services, monkeypatch):
    login_as(window, CUSTOMER, monkeypatch)
    assert window.user == CUSTOMER and window._current == "shop"
    assert {"shop", "cart", "orders", "product"} <= set(window._screens)
    on_screen = texts(window._screens["shop"]._grid)
    assert "Test Fleece Hoodie" in on_screen and "₹1,299.00" in on_screen
    assert "★ 4.5 (2)" in on_screen and " Positive " in on_screen
    assert "No reviews yet" in on_screen  # the socks


def test_category_filter_and_search(window, fake_services):
    shop = window._screens["shop"]
    shop._category.set("Footwear (1)")
    shop._load_category()
    pump(window)
    assert [p.id for p in shop._products] == [SOCKS.id]

    shop._search.insert(0, "warm socks")
    shop._run_search()
    pump(window)
    assert shop._category.get() == shop_screen.ALL_CATEGORIES  # search covers all
    assert "1 results for \"warm socks\"" in shop._summary.cget("text")


def test_product_page_shows_details_reviews_and_recommendations(window, fake_services):
    window._screens["shop"]._open(HOODIE.id)
    pump(window)
    assert window._current == "product"
    on_screen = texts(window._screens["product"]._body)
    for expected in ("Test Fleece Hoodie", "Warm fleece.", "Add to cart",
                     "Frequently bought together", "Test Sports Socks", "Similar products",
                     "No similar products found.", "Very warm!"):
        assert expected in on_screen, expected


def test_add_to_cart_success_and_out_of_stock(window, fake_services, monkeypatch):
    product = window._screens["product"]
    detail = product_screen.catalog_service.get_product_detail(1)
    button = ctk.CTkButton(product)
    monkeypatch.setattr(product_screen.cart_service, "add_to_cart", lambda u, pid, qty: None)
    product._add_to_cart(detail, 2, button)
    pump(window)
    assert window.popups[-1] == "Added to cart"

    def no_stock(user, pid, qty):
        raise OutOfStockError("Test Fleece Hoodie", 1)
    monkeypatch.setattr(product_screen.cart_service, "add_to_cart", no_stock)
    product._add_to_cart(detail, 2, button)
    pump(window)
    assert window.popups[-1] == "Out of stock"


def test_cart_marks_problem_lines_and_blocks_checkout(window, monkeypatch):
    lines = [CartLine(1, "Test Fleece Hoodie", Decimal("1299.00"), 3, Decimal("3897.00"), 2, True),
             CartLine(2, "Test Sports Socks", Decimal("339.00"), 1, Decimal("339.00"), 40, True)]
    cart = CartView(lines, Decimal("4236.00"), None, Decimal("0.00"), Decimal("4236.00"))
    monkeypatch.setattr(cart_screen.cart_service, "get_cart", lambda user, coupon: cart)
    window.navigate("cart")
    pump(window)
    screen = window._screens["cart"]
    on_screen = texts(screen._lines)
    assert "Only 2 left. Please lower the quantity." in on_screen
    assert screen._checkout.cget("state") == "disabled"
    assert screen._total.cget("text") == "₹4,236.00"


def test_cart_line_problem_messages():
    ok = CartLine(1, "A", Decimal("1"), 1, Decimal("1"), 5, True)
    assert cart_screen.line_problem(ok) is None
    assert "Out of stock" in cart_screen.line_problem(ok.__class__(**{**ok.__dict__, "stock": 0}))
    assert "Only 5 left" in cart_screen.line_problem(ok.__class__(**{**ok.__dict__, "qty": 6}))
    assert "No longer available" in cart_screen.line_problem(
        ok.__class__(**{**ok.__dict__, "is_active": False}))


def test_checkout_goes_to_orders(window, fake_services, monkeypatch):
    lines = [CartLine(1, "Test Fleece Hoodie", Decimal("1299.00"), 1, Decimal("1299.00"), 5, True)]
    cart = CartView(lines, Decimal("1299.00"), None, Decimal("0.00"), Decimal("1299.00"))
    monkeypatch.setattr(cart_screen.cart_service, "get_cart", lambda user, coupon: cart)
    placed = []
    monkeypatch.setattr(cart_screen.order_service, "checkout",
                        lambda user, method, coupon: placed.append(method) or
                        orders_screen.order_service.get_order_detail(user, 42))
    window.navigate("cart")
    pump(window)
    screen = window._screens["cart"]
    screen._payment.set("COD")
    screen._place_order()
    pump(window)
    assert placed == ["cod"]
    assert window.popups[-1] == "Order placed" and window._current == "orders"


def test_orders_show_timeline_and_review_button(window, fake_services):
    window.navigate("orders")
    pump(window)
    pump(window)  # list, then the selected order's detail
    on_screen = texts(window._screens["orders"]._detail)
    for expected in ("Order #42", "Placed", "Shipped", "Delivered", "Write review"):
        assert expected in on_screen, expected


def test_logout_returns_to_login_and_clears_screens(window):
    window.cart_coupon = "WELCOME10"
    window.logout()
    assert window.user is None and window.cart_coupon is None
    assert set(window._screens) == {"login", "register"}
    assert window._screens["login"]._email.get() == CUSTOMER.email  # remembered for convenience


def test_admin_login_opens_admin_placeholder(window, monkeypatch):
    login_as(window, ADMIN, monkeypatch)
    assert window._current == "admin" and set(window._screens) == {"admin"}
    assert "Welcome, Admin One" in texts(window._screens["admin"])
    window.logout()
