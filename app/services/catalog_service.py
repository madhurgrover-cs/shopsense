"""Browsing the catalog, and admin product / stock management."""

from decimal import Decimal, InvalidOperation

from sqlalchemy import Row

from app.db import get_session
from app.exceptions import NotFoundError, ValidationError
from app.repositories import product_repository
from app.services import audit_service
from app.services.auth_service import require_admin
from app.services.dto import CategoryInfo, ProductDetail, ProductSummary
from app.services.user_session import UserSession

MAX_NAME_LENGTH = 200


# ---------------------------------------------------------------------------
# Customer-facing
# ---------------------------------------------------------------------------

def list_categories() -> list[CategoryInfo]:
    with get_session() as session:
        return [CategoryInfo(r.id, r.name, r.product_count)
                for r in product_repository.list_categories_with_counts(session)]


def browse_products(category_id: int | None = None) -> list[ProductSummary]:
    """Active products, optionally in one category, sorted by name."""
    with get_session() as session:
        return [_to_summary(r) for r in product_repository.list_products(session, category_id)]


def get_product_detail(product_id: int) -> ProductDetail:
    """One product with stock and average rating. Soft-deleted products are still
    returned (is_active=False) so links from old orders keep working."""
    with get_session() as session:
        row = product_repository.get_product_row(session, product_id)
        if row is None:
            raise NotFoundError("Product not found.")
        return _to_detail(row)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

def list_all_products(admin: UserSession, category_id: int | None = None) -> list[ProductSummary]:
    """Like browse_products, but includes soft-deleted products (admin screen)."""
    require_admin(admin)
    with get_session() as session:
        rows = product_repository.list_products(session, category_id, include_inactive=True)
        return [_to_summary(r) for r in rows]


def create_product(admin: UserSession, category_id: int, name: str, description: str,
                   price, stock: int = 0) -> ProductDetail:
    require_admin(admin)
    name = _validate_name(name)
    price = _validate_price(price)
    _validate_stock(stock)
    with get_session() as session:
        if not product_repository.category_exists(session, category_id):
            raise ValidationError("Category does not exist.")
        product = product_repository.create(
            session, category_id, name, description.strip(), price, stock
        )
        audit_service.record_admin_action(
            session, admin, audit_service.CREATE, audit_service.PRODUCT, product.id,
            details=f"name={name!r}, price={price}, stock={stock}",
        )
        return _to_detail(product_repository.get_product_row(session, product.id))


def update_product(admin: UserSession, product_id: int, *, name: str | None = None,
                   description: str | None = None, price=None,
                   category_id: int | None = None) -> ProductDetail:
    """Change any of name / description / price / category. Only the arguments that are
    passed are changed. The audit entry lists each change as "field: old -> new"."""
    require_admin(admin)
    with get_session() as session:
        product = product_repository.get(session, product_id)
        if product is None:
            raise NotFoundError("Product not found.")

        changes = {}
        if name is not None:
            changes["name"] = _validate_name(name)
        if description is not None:
            changes["description"] = description.strip()
        if price is not None:
            changes["price"] = _validate_price(price)
        if category_id is not None:
            if not product_repository.category_exists(session, category_id):
                raise ValidationError("Category does not exist.")
            changes["category_id"] = category_id
        # Keep only real changes, so saving an unchanged form writes no audit entry.
        changes = {k: v for k, v in changes.items() if getattr(product, k) != v}

        if changes:
            details = "; ".join(
                f"{field}: {_short(getattr(product, field))} -> {_short(value)}"
                for field, value in changes.items()
            )
            for field, value in changes.items():
                setattr(product, field, value)
            # Semantic search embeds "name + description"; if either changed, the stored
            # vector describes the old text, so delete it and let it be rebuilt.
            if "name" in changes or "description" in changes:
                product_repository.delete_embedding(session, product.id)
            audit_service.record_admin_action(
                session, admin, audit_service.UPDATE, audit_service.PRODUCT, product.id,
                details=details,
            )
        session.flush()
        return _to_detail(product_repository.get_product_row(session, product.id))


def delete_product(admin: UserSession, product_id: int) -> None:
    """Soft delete: hide the product from the shop. It is never physically deleted
    because past orders still reference it."""
    require_admin(admin)
    with get_session() as session:
        product = product_repository.get(session, product_id)
        if product is None:
            raise NotFoundError("Product not found.")
        if product.is_active:
            product.is_active = False
            audit_service.record_admin_action(
                session, admin, audit_service.DELETE, audit_service.PRODUCT, product.id,
                details=f"soft-deleted {product.name!r}",
            )


def update_stock(admin: UserSession, product_id: int, new_stock: int) -> int:
    """Set the stock level (e.g. after a delivery from the supplier)."""
    require_admin(admin)
    _validate_stock(new_stock)
    with get_session() as session:
        # Lock the row so this doesn't overwrite a checkout that is decrementing it.
        locked = product_repository.lock_inventory(session, [product_id])
        if product_id not in locked:
            raise NotFoundError("Product not found.")
        inventory = locked[product_id]
        old_stock = inventory.stock
        if old_stock != new_stock:
            inventory.stock = new_stock
            audit_service.record_admin_action(
                session, admin, audit_service.UPDATE, audit_service.STOCK, product_id,
                details=f"stock: {old_stock} -> {new_stock}",
            )
        return new_stock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValidationError("Product name is required.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValidationError(f"Product name must be at most {MAX_NAME_LENGTH} characters.")
    return name


def _validate_price(price) -> Decimal:
    """Accept Decimal, int or a string like "499.00". Floats go through str() so that
    499.99 doesn't become 499.990000000000009094947017729282379150390625."""
    try:
        value = Decimal(str(price))
    except InvalidOperation:
        raise ValidationError("Price must be a number.") from None
    if not value.is_finite() or value <= 0:
        raise ValidationError("Price must be greater than zero.")
    if value != value.quantize(Decimal("0.01")):
        raise ValidationError("Price can have at most 2 decimal places.")
    if value >= Decimal("100000000"):  # Numeric(10, 2) limit
        raise ValidationError("Price is too large.")
    return value.quantize(Decimal("0.01"))


def _validate_stock(stock: int) -> None:
    if not isinstance(stock, int) or isinstance(stock, bool) or stock < 0:
        raise ValidationError("Stock must be a whole number, 0 or more.")


def _short(value) -> str:
    text = str(value)
    return text if len(text) <= 40 else text[:37] + "..."


def _avg(value) -> float | None:
    return None if value is None else round(float(value), 2)


def _to_summary(row: Row) -> ProductSummary:
    p = row.Product
    return ProductSummary(p.id, p.name, p.category_id, row.category, p.price, row.stock,
                          _avg(row.avg_rating), row.review_count, p.is_active)


def _to_detail(row: Row) -> ProductDetail:
    p = row.Product
    return ProductDetail(p.id, p.name, p.category_id, row.category, p.price, row.stock,
                         _avg(row.avg_rating), row.review_count, p.is_active, p.description)
