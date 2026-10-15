"""Product recommendations: on the product page, and "Recommended for you" in the shop.

1. "Frequently bought together": pure SQL. Count in how many (non-cancelled) orders
   another product appears together with this one; highest count first. This is the
   simplest form of market-basket analysis. No model needed.

2. "Similar products": the nearest neighbours of this product's stored embedding in
   pgvector. The vectors already exist in the database, so this does NOT need the
   embedding model either (no 30 s load on the product page).

3. "Recommended for you": the customer's TASTE VECTOR = the average of the embeddings
   of everything they have received or is on its way (shipped / delivered orders).
   Products whose embedding is closest to that average are "like what they buy". Again
   only stored vectors are used, so no model load.

Called by catalog_service, which owns the session. Queries live in product_repository.
"""

from sqlalchemy.orm import Session

from app.repositories import product_repository

# A pair seen in only ONE order is often coincidence; require at least two orders.
MIN_TIMES_BOUGHT_TOGETHER = 2

# Orders that shape the taste vector: what the customer actually got (or will get).
TASTE_STATUSES = ("shipped", "delivered")
# Products never recommended: anything already ordered and not cancelled. A product
# ordered yesterday (still "placed") is not something to suggest again today.
OWNED_STATUSES = ("placed", "shipped", "delivered")


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


def recommended_for_user(session: Session, user_id: int, limit: int) -> list[int]:
    """Up to `limit` product ids for this customer, best first.

    1. Taste vector (average embedding of their shipped / delivered products), then the
       nearest active, in-stock products they haven't ordered.
    2. No such orders yet (or too few matches): fill up with the top-rated products
       they haven't ordered, so new customers see something useful too.
    """
    owned = product_repository.purchased_product_ids(session, user_id, OWNED_STATUSES)
    taste_products = product_repository.purchased_product_ids(session, user_id, TASTE_STATUSES)
    ids: list[int] = []
    taste = product_repository.average_embedding(session, taste_products)
    if taste is not None:
        ids = [pid for pid, _distance in product_repository.nearest_by_vector(
            session, taste, limit, exclude_ids=owned, in_stock_only=True)]
    if len(ids) < limit:
        ids += product_repository.top_rated_ids(session, limit - len(ids),
                                                exclude_ids=[*owned, *ids])
    return ids
