"""Tests for catalog browsing and admin product / stock management."""

from decimal import Decimal

import pytest

from app.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from app.models import Product, ProductEmbedding
from app.services import catalog_service


# ---------------------------------------------------------------------------
# Browsing
# ---------------------------------------------------------------------------

def test_list_categories_counts_only_active_products(factory):
    cat = factory.category("Test Gadgets")
    factory.product(category_id=cat)
    factory.product(category_id=cat)
    factory.product(category_id=cat, active=False)
    empty = factory.category("Test Empty")

    by_id = {c.id: c for c in catalog_service.list_categories()}
    assert by_id[cat].name == "Test Gadgets" and by_id[cat].product_count == 2
    assert by_id[empty].product_count == 0  # categories with no products still listed


def test_browse_products_filters_by_category_and_hides_inactive(factory):
    cat = factory.category()
    a = factory.product(category_id=cat, name="Test A")
    b = factory.product(category_id=cat, name="Test B", stock=0)
    factory.product(category_id=cat, name="Test Hidden", active=False)
    factory.product(name="Test Other Category")

    products = catalog_service.browse_products(cat)
    assert [p.id for p in products] == [a, b]  # sorted by name, inactive hidden
    assert products[1].stock == 0 and not products[1].in_stock


def test_browse_products_without_category_returns_all_active(factory):
    pid = factory.product()
    hidden = factory.product(active=False)
    ids = {p.id for p in catalog_service.browse_products()}
    assert pid in ids and hidden not in ids


def test_product_detail_includes_stock_and_avg_rating(factory, customer):
    cat = factory.category("Test Detail Category")
    pid = factory.product(price="1299.00", stock=7, category_id=cat, name="Test Phone")
    other = factory.user()
    factory.review(customer.user_id, pid, 5)
    factory.review(other.user_id, pid, 2)

    detail = catalog_service.get_product_detail(pid)
    assert (detail.name, detail.category, detail.price, detail.stock) == (
        "Test Phone", "Test Detail Category", Decimal("1299.00"), 7)
    assert detail.avg_rating == 3.5 and detail.review_count == 2
    assert detail.description == "A product created by a test."


def test_product_detail_without_reviews(factory):
    detail = catalog_service.get_product_detail(factory.product())
    assert detail.avg_rating is None and detail.review_count == 0


def test_product_detail_of_soft_deleted_product_still_works(factory):
    detail = catalog_service.get_product_detail(factory.product(active=False))
    assert detail.is_active is False


def test_product_detail_not_found(db_session):
    with pytest.raises(NotFoundError):
        catalog_service.get_product_detail(-1)


# ---------------------------------------------------------------------------
# Admin: list / create
# ---------------------------------------------------------------------------

def test_list_all_products_includes_inactive_for_admin(factory, admin):
    cat = factory.category()
    active, hidden = factory.product(category_id=cat), factory.product(category_id=cat, active=False)
    assert {p.id for p in catalog_service.list_all_products(admin, cat)} == {active, hidden}


def test_list_all_products_is_admin_only(factory, customer):
    with pytest.raises(PermissionDeniedError):
        catalog_service.list_all_products(customer)


def test_create_product(factory, admin):
    cat = factory.category()
    detail = catalog_service.create_product(admin, cat, "  Test Kettle ", "Boils water.",
                                            "899.50", stock=12)
    assert (detail.name, detail.price, detail.stock, detail.is_active) == (
        "Test Kettle", Decimal("899.50"), 12, True)

    [entry] = factory.audit_entries("product", detail.id)
    assert (entry.user_id, entry.action) == (admin.user_id, "create")
    assert "Test Kettle" in entry.details


def test_create_product_float_price_is_exact(factory, admin):
    detail = catalog_service.create_product(admin, factory.category(), "Test", "", 499.99)
    assert detail.price == Decimal("499.99")


@pytest.mark.parametrize("price", [0, -5, "abc", "1.234", "NaN", 100_000_000])
def test_create_product_rejects_bad_price(factory, admin, price):
    with pytest.raises(ValidationError):
        catalog_service.create_product(admin, factory.category(), "Test", "", price)


@pytest.mark.parametrize("kwargs", [
    {"name": "   "},
    {"name": "x" * 201},
    {"stock": -1},
    {"stock": 2.5},
])
def test_create_product_rejects_bad_input(factory, admin, kwargs):
    args = {"category_id": factory.category(), "name": "Test", "description": "",
            "price": "10.00", **kwargs}
    with pytest.raises(ValidationError):
        catalog_service.create_product(admin, **args)


def test_create_product_unknown_category(factory, admin):
    with pytest.raises(ValidationError, match="Category"):
        catalog_service.create_product(admin, -1, "Test", "", "10.00")


def test_create_product_requires_admin_and_writes_nothing(factory, customer, db_session):
    cat = factory.category()
    with pytest.raises(PermissionDeniedError):
        catalog_service.create_product(customer, cat, "Test Sneaky", "", "10.00")
    assert db_session.query(Product).filter_by(name="Test Sneaky").count() == 0


# ---------------------------------------------------------------------------
# Admin: update / delete / stock
# ---------------------------------------------------------------------------

def test_update_product_changes_fields_and_audits(factory, admin):
    pid = factory.product(price="100.00", name="Test Old Name")
    new_cat = factory.category("Test New Category")

    detail = catalog_service.update_product(admin, pid, name="Test New Name", price="120",
                                            category_id=new_cat)
    assert (detail.name, detail.price, detail.category) == (
        "Test New Name", Decimal("120.00"), "Test New Category")

    [entry] = factory.audit_entries("product", pid)
    assert entry.action == "update"
    assert "name: Test Old Name -> Test New Name" in entry.details
    assert "price: 100.00 -> 120.00" in entry.details


def test_update_product_with_no_real_change_writes_no_audit(factory, admin):
    pid = factory.product(price="100.00", name="Test Same")
    catalog_service.update_product(admin, pid, name="Test Same", price="100")
    assert factory.audit_entries("product", pid) == []


def test_update_product_text_change_removes_stale_embedding(factory, admin, db_session):
    pid = factory.product()
    db_session.add(ProductEmbedding(product_id=pid, embedding=[0.1] * 384))
    db_session.commit()

    catalog_service.update_product(admin, pid, price="55.00")  # price only: keep it
    assert db_session.get(ProductEmbedding, pid) is not None

    catalog_service.update_product(admin, pid, description="Completely new text")
    db_session.expire_all()
    assert db_session.get(ProductEmbedding, pid) is None


def test_update_product_errors(factory, admin, customer):
    pid = factory.product()
    with pytest.raises(NotFoundError):
        catalog_service.update_product(admin, -1, name="X")
    with pytest.raises(ValidationError):
        catalog_service.update_product(admin, pid, price="0")
    with pytest.raises(ValidationError):
        catalog_service.update_product(admin, pid, category_id=-1)
    with pytest.raises(PermissionDeniedError):
        catalog_service.update_product(customer, pid, name="X")


def test_delete_product_is_soft_and_audited_once(factory, admin):
    pid = factory.product()
    catalog_service.delete_product(admin, pid)
    catalog_service.delete_product(admin, pid)  # second call: no-op

    assert pid not in {p.id for p in catalog_service.browse_products()}
    assert catalog_service.get_product_detail(pid).is_active is False  # row still exists
    assert [e.action for e in factory.audit_entries("product", pid)] == ["delete"]


def test_delete_product_errors(factory, customer, admin):
    with pytest.raises(NotFoundError):
        catalog_service.delete_product(admin, -1)
    with pytest.raises(PermissionDeniedError):
        catalog_service.delete_product(customer, factory.product())


def test_update_stock(factory, admin):
    pid = factory.product(stock=3)
    assert catalog_service.update_stock(admin, pid, 50) == 50
    assert factory.stock(pid) == 50
    [entry] = factory.audit_entries("stock", pid)
    assert (entry.action, entry.details) == ("update", "stock: 3 -> 50")


def test_update_stock_errors(factory, admin, customer):
    pid = factory.product()
    with pytest.raises(ValidationError):
        catalog_service.update_stock(admin, pid, -1)
    with pytest.raises(NotFoundError):
        catalog_service.update_stock(admin, -1, 5)
    with pytest.raises(PermissionDeniedError):
        catalog_service.update_stock(customer, pid, 5)
    assert factory.stock(pid) == 10


def test_products_carry_sentiment_badge(factory):
    cat = factory.category()
    liked, disliked, unreviewed = (factory.product(category_id=cat, name=f"Test {n}")
                                   for n in ("A Liked", "B Disliked", "C Unreviewed"))
    a, b = factory.user().user_id, factory.user().user_id
    factory.review(a, liked, 5, "Love it", score=0.9)
    factory.review(b, liked, 4, "Good", score=0.6)
    factory.review(a, disliked, 1, "Broken", score=-0.8)

    badges = {p.id: p.sentiment_badge for p in catalog_service.browse_products(cat)}
    assert badges == {liked: "Positive", disliked: "Negative", unreviewed: None}
    assert catalog_service.get_product_detail(liked).sentiment_badge == "Positive"
