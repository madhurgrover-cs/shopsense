"""Product recommendations, used on the product page.

1. "Frequently bought together": pure SQL. Count in how many (non-cancelled) orders
   another product appears together with this one; highest count first. This is the
   simplest form of market-basket analysis. No model needed.

2. "Similar products": the nearest neighbours of this product's stored embedding in
   pgvector. The vectors already exist in the database, so this does NOT need the
   embedding model either (no 30 s load on the product page).

Called by catalog_service, which owns the session. Queries live in product_repository.
"""

from sqlalchemy.orm import Session

from app.repositories import product_repository

# A pair seen in only ONE order is often coincidence; require at least two orders.
MIN_TIMES_BOUGHT_TOGETHER = 2


def frequently_bought_together(session: Session, product_id: int, limit: int,
                               min_count: int = MIN_TIMES_BOUGHT_TOGETHER
                               ) -> list[tuple[int, int]]:
    """[(other product id, number of orders containing both)], most frequent first."""
    return product_repository.co_purchased_with(session, product_id, limit, min_count)


def similar_products(session: Session, product_id: int, limit: int) -> list[tuple[int, float]]:
    """[(product id, cosine distance)], most similar first; excludes the product itself
    and inactive products. Empty if this product has no embedding yet."""
    vector = product_repository.get_embedding(session, product_id)
    if vector is None:
        return []
    return product_repository.nearest_by_vector(session, vector, limit, exclude_id=product_id)
