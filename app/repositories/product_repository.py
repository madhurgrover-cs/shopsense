"""Queries for categories, products and inventory."""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import Row, delete, func, select
from sqlalchemy.orm import Session

from app.models import Category, Inventory, Product, ProductEmbedding, Review


def list_categories_with_counts(session: Session) -> list[Row]:
    """(id, name, product_count) for every category; count of active products only.
    The outer join keeps categories that have no products yet (count 0)."""
    stmt = (
        select(Category.id, Category.name, func.count(Product.id).label("product_count"))
        .outerjoin(Product, (Product.category_id == Category.id) & Product.is_active)
        .group_by(Category.id)
        .order_by(Category.name)
    )
    return list(session.execute(stmt))


def _product_rows_query():
    """Products with category name, stock, average rating and review count in ONE query
    (instead of one query per product, the classic "N+1 queries" problem)."""
    return (
        select(
            Product,
            Category.name.label("category"),
            func.coalesce(Inventory.stock, 0).label("stock"),
            func.avg(Review.rating).label("avg_rating"),
            func.count(Review.id).label("review_count"),
        )
        .join(Category, Category.id == Product.category_id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .outerjoin(Review, Review.product_id == Product.id)
        .group_by(Product.id, Category.name, Inventory.stock)
    )


def list_products(session: Session, category_id: int | None = None,
                  include_inactive: bool = False) -> list[Row]:
    stmt = _product_rows_query().order_by(Product.name)
    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)
    if not include_inactive:
        stmt = stmt.where(Product.is_active)
    return list(session.execute(stmt))


def get_product_row(session: Session, product_id: int) -> Row | None:
    return session.execute(_product_rows_query().where(Product.id == product_id)).first()


def get(session: Session, product_id: int) -> Product | None:
    return session.get(Product, product_id)


def category_exists(session: Session, category_id: int) -> bool:
    return session.get(Category, category_id) is not None


def create(session: Session, category_id: int, name: str, description: str,
           price: Decimal, stock: int) -> Product:
    product = Product(category_id=category_id, name=name, description=description, price=price)
    product.inventory = Inventory(stock=stock)  # every product gets its stock row
    session.add(product)
    session.flush()
    return product


def delete_embedding(session: Session, product_id: int) -> None:
    """Remove a stale embedding (after name/description change) so it gets rebuilt."""
    session.execute(delete(ProductEmbedding).where(ProductEmbedding.product_id == product_id))


def lock_inventory(session: Session, product_ids: Sequence[int]) -> dict[int, Inventory]:
    """SELECT ... FOR UPDATE on the stock rows of these products, ALWAYS in product_id order.

    Why the fixed order: if checkout A locks product 3 then 7 while checkout B locks
    7 then 3, each can end up waiting for the other forever (a deadlock). When every
    transaction locks in the same order, that cycle can't happen. Postgres applies
    the lock after the ORDER BY sort, so rows are locked in sorted order.

    populate_existing: if this session already holds an Inventory object, overwrite its
    cached stock with the fresh value Postgres returns after acquiring the lock.
    Otherwise we could check stock against a stale number.
    """
    stmt = (
        select(Inventory)
        .where(Inventory.product_id.in_(product_ids))
        .order_by(Inventory.product_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return {inv.product_id: inv for inv in session.scalars(stmt)}
