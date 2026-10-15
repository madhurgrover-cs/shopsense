"""Queries for categories, products and inventory."""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import Row, case, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, aliased

from app.models import (
    Category, Inventory, Order, OrderItem, Product, ProductEmbedding, Review,
)


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
            func.avg(Review.sentiment_score).label("avg_sentiment"),
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


def list_missing_embeddings(session: Session, product_ids: Sequence[int] | None = None,
                            limit: int | None = None, lock: bool = False) -> list[Row]:
    """(id, name, description) of ACTIVE products that have no embedding yet.
    Soft-deleted products are skipped: they never appear in search results.

    lock=True locks those product rows (FOR UPDATE OF products) until the transaction
    ends, so an admin can't edit the text between "read" and "save the vector".
    """
    stmt = (
        select(Product.id, Product.name, Product.description)
        .outerjoin(ProductEmbedding, ProductEmbedding.product_id == Product.id)
        .where(ProductEmbedding.product_id.is_(None), Product.is_active)
        .order_by(Product.id)
    )
    if product_ids is not None:
        stmt = stmt.where(Product.id.in_(product_ids))
    if limit is not None:
        stmt = stmt.limit(limit)
    if lock:
        stmt = stmt.with_for_update(of=Product)
    return list(session.execute(stmt))


def save_embeddings(session: Session, vectors: dict[int, list[float]]) -> None:
    """Insert or replace embeddings, {product_id: vector}, in one statement.
    ON CONFLICT DO UPDATE makes it safe to run twice for the same product."""
    if not vectors:
        return
    stmt = pg_insert(ProductEmbedding).values(
        [{"product_id": pid, "embedding": vec} for pid, vec in vectors.items()]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[ProductEmbedding.product_id],
        set_={"embedding": stmt.excluded.embedding},
    )
    session.execute(stmt)


def count_embeddings(session: Session) -> tuple[int, int]:
    """(active products with an embedding, active products in total)."""
    total = session.scalar(select(func.count()).select_from(Product).where(Product.is_active))
    done = session.scalar(
        select(func.count()).select_from(ProductEmbedding)
        .join(Product, Product.id == ProductEmbedding.product_id)
        .where(Product.is_active)
    )
    return done, total


def get_product_rows(session: Session, product_ids: Sequence[int]) -> list[Row]:
    """Full product rows (as list_products returns) for these ids, IN THE SAME ORDER as
    product_ids. Search and recommendations rank ids first, then fetch the details."""
    if not product_ids:
        return []
    rows = session.execute(_product_rows_query().where(Product.id.in_(product_ids)))
    by_id = {row.Product.id: row for row in rows}
    return [by_id[pid] for pid in product_ids if pid in by_id]


# ---------------------------------------------------------------------------
# Embedding / vector queries
# ---------------------------------------------------------------------------

def has_any_embeddings(session: Session) -> bool:
    return session.scalar(select(select(ProductEmbedding.product_id).exists()))


def get_embedding(session: Session, product_id: int) -> list[float] | None:
    vector = session.scalar(
        select(ProductEmbedding.embedding).where(ProductEmbedding.product_id == product_id)
    )
    return None if vector is None else list(vector)


def nearest_by_vector(session: Session, vector: Sequence[float], limit: int,
                      exclude_id: int | None = None,
                      max_distance: float | None = None,
                      exclude_ids: Sequence[int] = (),
                      in_stock_only: bool = False) -> list[tuple[int, float]]:
    """[(product id, cosine distance)] of ACTIVE products closest to `vector`.

    `ORDER BY embedding <=> :vector LIMIT n` is exactly the query shape the HNSW index
    (vector_cosine_ops) accelerates, so this stays fast as the catalog grows.
    """
    distance = ProductEmbedding.embedding.cosine_distance(vector)
    stmt = (
        select(ProductEmbedding.product_id, distance.label("distance"))
        .join(Product, Product.id == ProductEmbedding.product_id)
        .where(Product.is_active)
        .order_by(distance)
        .limit(limit)
    )
    if exclude_id is not None:
        stmt = stmt.where(ProductEmbedding.product_id != exclude_id)
    if exclude_ids:
        stmt = stmt.where(ProductEmbedding.product_id.not_in(exclude_ids))
    if in_stock_only:
        stmt = stmt.join(Inventory, Inventory.product_id == Product.id).where(Inventory.stock > 0)
    if max_distance is not None:
        stmt = stmt.where(distance <= max_distance)
    return [(row.product_id, float(row.distance)) for row in session.execute(stmt)]


def average_embedding(session: Session, product_ids: Sequence[int]) -> list[float] | None:
    """The average of these products' embeddings, computed by pgvector's avg(vector)
    aggregate in the database. None if none of them has an embedding."""
    if not product_ids:
        return None
    vector = session.scalar(
        # type_: tell SQLAlchemy the average is a vector too (else it arrives as text).
        select(func.avg(ProductEmbedding.embedding, type_=ProductEmbedding.embedding.type))
        .where(ProductEmbedding.product_id.in_(product_ids))
    )
    return None if vector is None else [float(x) for x in vector]


def distances_for(session: Session, vector: Sequence[float],
                  product_ids: Sequence[int]) -> dict[int, float]:
    """{product id: cosine distance to `vector`} for these products (those with an
    embedding). Hybrid search uses it for keyword matches the nearest-neighbour query
    didn't return, so every candidate has a semantic score."""
    if not product_ids:
        return {}
    distance = ProductEmbedding.embedding.cosine_distance(vector)
    stmt = select(ProductEmbedding.product_id, distance.label("distance")).where(
        ProductEmbedding.product_id.in_(product_ids))
    return {row.product_id: float(row.distance) for row in session.execute(stmt)}


# ---------------------------------------------------------------------------
# Keyword search and co-purchase
# ---------------------------------------------------------------------------

def _escape_like(word: str) -> str:
    """Treat % and _ typed by the user as literal characters, not wildcards."""
    return word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _contains_any(words: Sequence[str]):
    """(name conditions, description conditions): one ILIKE '%word%' per word."""
    patterns = [f"%{_escape_like(word)}%" for word in words]
    return ([Product.name.ilike(p, escape="\\") for p in patterns],
            [Product.description.ilike(p, escape="\\") for p in patterns])


def keyword_search(session: Session, words: Sequence[str], limit: int) -> list[int]:
    """Ids of active products whose name or description contains any of the words.

    Ranking: each word found in the NAME scores 2, in the DESCRIPTION scores 1;
    higher total first, then alphabetical.
    """
    in_name, in_description = _contains_any(words)
    score = sum((case((n, 2), else_=0) + case((d, 1), else_=0)
                 for n, d in zip(in_name, in_description)), start=0)
    stmt = (
        select(Product.id)
        .where(Product.is_active, or_(*in_name, *in_description))
        .order_by(score.desc(), Product.name)
        .limit(limit)
    )
    return list(session.scalars(stmt))


def keyword_matches(session: Session, words: Sequence[str], limit: int) -> list[Row]:
    """Rows (id, name, description) of active products containing any of the words.
    Hybrid search scores these in Python, so it needs the text, not just the ids."""
    in_name, in_description = _contains_any(words)
    stmt = (
        select(Product.id, Product.name, Product.description)
        .where(Product.is_active, or_(*in_name, *in_description))
        .order_by(Product.id)
        .limit(limit)
    )
    return list(session.execute(stmt))


def vocabulary_texts(session: Session) -> tuple[list[str], list[str]]:
    """(active product names + category names, active product descriptions): the text
    the spelling corrector learns its words from."""
    rows = session.execute(
        select(Product.name, Product.description).where(Product.is_active)
    ).all()
    categories = list(session.scalars(select(Category.name)))
    return [r.name for r in rows] + categories, [r.description for r in rows]


def purchased_product_ids(session: Session, user_id: int,
                          statuses: Sequence[str]) -> list[int]:
    """Distinct ids of products in this user's orders that have one of these statuses."""
    stmt = (
        select(OrderItem.product_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.user_id == user_id, Order.status.in_(statuses))
        .distinct()
        .order_by(OrderItem.product_id)
    )
    return list(session.scalars(stmt))


def top_rated_ids(session: Session, limit: int, exclude_ids: Sequence[int] = (),
                  min_reviews: int = 2) -> list[int]:
    """Active, in-stock products with the best average rating (at least `min_reviews`
    reviews, so one lucky 5-star review doesn't win); ties: more reviews first."""
    avg_rating = func.avg(Review.rating)
    stmt = (
        select(Product.id)
        .join(Review, Review.product_id == Product.id)
        .join(Inventory, Inventory.product_id == Product.id)
        .where(Product.is_active, Inventory.stock > 0)
        .group_by(Product.id, Product.name)
        .having(func.count(Review.id) >= min_reviews)
        .order_by(avg_rating.desc(), func.count(Review.id).desc(), Product.name)
        .limit(limit)
    )
    if exclude_ids:
        stmt = stmt.where(Product.id.not_in(exclude_ids))
    return list(session.scalars(stmt))


def co_purchased_with(session: Session, product_id: int, limit: int,
                      min_count: int = 1) -> list[tuple[int, int]]:
    """[(other product id, number of orders containing both)], most frequent first.

    Self-join of order_items on the same order:  a = this product, b = the others.
        SELECT b.product_id, COUNT(DISTINCT a.order_id) ...
        FROM order_items a JOIN order_items b ON b.order_id = a.order_id
                                             AND b.product_id <> a.product_id
    Cancelled orders are ignored (the customer didn't actually keep the pair), and
    only active products are recommended.
    """
    a, b = aliased(OrderItem), aliased(OrderItem)
    times = func.count(func.distinct(a.order_id)).label("times")
    stmt = (
        select(b.product_id, times)
        .select_from(a)
        .join(b, (b.order_id == a.order_id) & (b.product_id != a.product_id))
        .join(Order, (Order.id == a.order_id) & (Order.status != "cancelled"))
        .join(Product, (Product.id == b.product_id) & Product.is_active)
        .where(a.product_id == product_id)
        .group_by(b.product_id)
        .having(times >= min_count)
        .order_by(times.desc(), b.product_id)
        .limit(limit)
    )
    return [(row.product_id, row.times) for row in session.execute(stmt)]


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
