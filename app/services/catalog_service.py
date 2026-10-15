"""Browsing the catalog, and admin product / stock management."""

from decimal import Decimal, InvalidOperation

from sqlalchemy import Row

from app.ai import recommend, sentiment
from app.ai import search as ai_search  # aliased: this module defines its own search()
from app.db import get_session
from app.exceptions import NotFoundError, ValidationError
from app.repositories import product_repository
from app.services import audit_service
from app.services.validation import parse_int
from app.services.auth_service import require_admin
from app.services.dto import CategoryInfo, ProductDetail, ProductSummary, SearchResults
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
# Search and recommendations (AI module)
# ---------------------------------------------------------------------------

MAX_RESULTS = 50


def search(query: str, limit: int = 20, correct_spelling: bool = True) -> SearchResults:
    """Search active products: spelling correction, then semantic + keyword ranking
    (keyword only if the AI model or embeddings are unavailable).

    correct_spelling=False searches exactly the typed words (the GUI's "search instead
    for ..." link). If a typo was fixed, results.corrected_query says what was searched.

    Note for the GUI: if the embedding model isn't loaded yet, this loads it (~30 s on
    the dev laptop), so call it from a background thread.
    """
    query = query.strip()
    _validate_limit(limit)
    if not query:
        return SearchResults(query, [])
    with get_session() as session:
        result = ai_search.search(session, query, limit, correct_spelling=correct_spelling)
        return SearchResults(query, _summaries(session, result.ids), result.corrected_query)


def search_products(query: str, limit: int = 20) -> list[ProductSummary]:
    """Just the products of search() (with spelling correction)."""
    return search(query, limit).products


def frequently_bought_together(product_id: int, limit: int = 5) -> list[ProductSummary]:
    """Products most often in the same (non-cancelled) order as this one."""
    _validate_limit(limit)
    with get_session() as session:
        pairs = recommend.frequently_bought_together(session, product_id, limit)
        return _summaries(session, [pid for pid, _times in pairs])


def similar_products(product_id: int, limit: int = 5) -> list[ProductSummary]:
    """Products whose description means something close to this one's."""
    _validate_limit(limit)
    with get_session() as session:
        matches = recommend.similar_products(session, product_id, limit)
        return _summaries(session, [pid for pid, _distance in matches])


def _summaries(session, product_ids: list[int]) -> list[ProductSummary]:
    return [_to_summary(r) for r in product_repository.get_product_rows(session, product_ids)]


def _validate_limit(limit: int) -> None:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_RESULTS:
        raise ValidationError(f"Limit must be between 1 and {MAX_RESULTS}.")


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
    stock = _validate_stock(stock)
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
        ai_search.clear_vocabulary_cache()  # so the new name's words can be spell-corrected to
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
                ai_search.clear_vocabulary_cache()  # spelling vocabulary uses these words
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
            ai_search.clear_vocabulary_cache()


def restore_product(admin: UserSession, product_id: int) -> None:
    """Undo a soft delete: show the product in the shop again."""
    require_admin(admin)
    with get_session() as session:
        product = product_repository.get(session, product_id)
        if product is None:
            raise NotFoundError("Product not found.")
        if not product.is_active:
            product.is_active = True
            audit_service.record_admin_action(
                session, admin, audit_service.RESTORE, audit_service.PRODUCT, product.id,
                details=f"restored {product.name!r}",
            )
            ai_search.clear_vocabulary_cache()


def update_stock(admin: UserSession, product_id: int, new_stock: int | str) -> int:
    """Set the stock level (e.g. after a delivery from the supplier). Accepts the
    number as text too ("25"), as typed into the admin form."""
    require_admin(admin)
    new_stock = _validate_stock(new_stock)
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


MAX_STOCK = 1_000_000


def _validate_stock(stock: int | str) -> int:
    return parse_int(stock, "Stock", minimum=0, maximum=MAX_STOCK)


def _short(value) -> str:
    text = str(value)
    return text if len(text) <= 40 else text[:37] + "..."


def _avg(value) -> float | None:
    return None if value is None else round(float(value), 2)


def _summary_fields(row: Row) -> dict:
    p = row.Product
    avg_sentiment = None if row.avg_sentiment is None else float(row.avg_sentiment)
    return dict(id=p.id, name=p.name, category_id=p.category_id, category=row.category,
                price=p.price, stock=row.stock, avg_rating=_avg(row.avg_rating),
                review_count=row.review_count, is_active=p.is_active,
                # The badge comes from the same query (avg of review scores), so a page
                # of product cards needs no extra call per product.
                sentiment_badge=sentiment.badge(avg_sentiment))


def _to_summary(row: Row) -> ProductSummary:
    return ProductSummary(**_summary_fields(row))


def _to_detail(row: Row) -> ProductDetail:
    return ProductDetail(**_summary_fields(row), description=row.Product.description)
