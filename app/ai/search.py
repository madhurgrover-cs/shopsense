"""Semantic product search with a keyword fallback.

Called by catalog_service.search_products(), which owns the database session. The
queries themselves live in product_repository; this module decides HOW to search.

Semantic search: embed the query with the same model used for products, then let
pgvector order products by cosine distance (<=>) to the query vector. Distance 0 means
same meaning; around 1 means unrelated.

Keyword fallback (ILIKE): used when no product has an embedding yet (e.g. right after
seeding, before scripts.build_embeddings has run) or when the model can't be loaded
(e.g. first run without internet to download it). Search must keep working either way.
"""

import logging
import re
from typing import Literal

from sqlalchemy.orm import Session

from app.ai import embeddings
from app.repositories import product_repository

log = logging.getLogger(__name__)

# Results further away than this are dropped. Measured on our seeded catalog:
#   "protect my phone screen"  -> 0.34   "warm winter wear" -> 0.47
#   "gift for a gamer"         -> 0.62   "morning coffee"   -> 0.74 (no coffee products!)
#   "pet food for dogs"        -> 0.73   gibberish "asdfgh qwerty" -> 0.80+
# So this cut-off only removes gibberish-level matches. It can NOT tell "related" from
# "unrelated" (pet food still returns cookbooks): MiniLM distances overlap too much
# for any single threshold to do that.
MAX_DISTANCE = 0.8

# Words that carry no meaning for keyword matching ("something for my coffee").
STOPWORDS = {
    "a", "an", "and", "the", "for", "to", "of", "in", "on", "with", "my", "me", "i",
    "is", "it", "some", "something", "that", "this", "best", "good", "buy", "need",
}

SearchMode = Literal["semantic", "keyword"]


def keywords(query: str) -> list[str]:
    """Lower-case words of at least 2 letters, without stopwords or duplicates."""
    words = re.findall(r"[a-z0-9]+", query.lower())
    return list(dict.fromkeys(w for w in words if len(w) >= 2 and w not in STOPWORDS))


def search(session: Session, query: str, limit: int) -> tuple[list[int], SearchMode]:
    """Return (product ids, best match first; which method was used)."""
    if not product_repository.has_any_embeddings(session):
        log.info("No product embeddings yet; using keyword search.")
        return keyword_search(session, query, limit), "keyword"
    try:
        query_vector = embeddings.embed_text(query)
    except Exception:  # model missing / failed to load: degrade, don't crash the shop
        log.warning("Embedding model unavailable; using keyword search.", exc_info=True)
        return keyword_search(session, query, limit), "keyword"

    matches = product_repository.nearest_by_vector(
        session, query_vector, limit, max_distance=MAX_DISTANCE
    )
    return [product_id for product_id, _distance in matches], "semantic"


def keyword_search(session: Session, query: str, limit: int) -> list[int]:
    words = keywords(query)
    if not words:
        return []
    return product_repository.keyword_search(session, words, limit)
