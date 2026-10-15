"""Product search: spelling correction, then hybrid (semantic + keyword) ranking, with
a keyword-only fallback.

Called by catalog_service.search(), which owns the database session. The queries
themselves live in product_repository; this module decides HOW to search.

1. Spelling correction (spelling.py): "sirt" -> "shirt" before anything else, so both
   the embedding and the keyword match use the word the user meant.

2. Hybrid ranking. Two signals per product:
   - semantic similarity = 1 - cosine distance between the query's embedding and the
     product's (pgvector <=>). Finds products by MEANING ("warm winter wear" -> shawl)
     but on its own can rank a product that merely sounds related above one that IS
     the thing asked for (MiniLM puts "Polo T-Shirt" and "Kurta" close together).
   - keyword score = how many query words appear in the product's name (1.0 each) or
     only in its description (0.3 each), averaged over the query words.
   score = semantic similarity + KEYWORD_WEIGHT * keyword score
   Semantic similarities on our catalog lie between ~0.2 and ~0.7, so a weight of 1.0
   puts products whose NAME contains every query word first, and semantic similarity
   orders products within each group (and finds those that share no words at all).

3. Keyword fallback (ILIKE): used when no product has an embedding yet (e.g. right after
   seeding, before scripts.build_embeddings has run) or when the model can't be loaded
   (e.g. first run without internet to download it). Search must keep working either way.
"""

import logging
import re
import threading
import time
from typing import Literal, NamedTuple

from sqlalchemy.orm import Session

from app.ai import embeddings, spelling
from app.repositories import product_repository

log = logging.getLogger(__name__)

# Results further away than this are dropped (unless they contain a query word).
# Measured on our seeded catalog:
#   "protect my phone screen"  -> 0.34   "warm winter wear" -> 0.47
#   "gift for a gamer"         -> 0.62   "morning coffee"   -> 0.74 (no coffee products!)
#   "pet food for dogs"        -> 0.73   gibberish               -> 0.73-0.86
# So this cut-off only removes the worst matches. It can NOT tell "related" from
# "unrelated" (pet food still returns cookbooks): MiniLM distances overlap too much
# for any single threshold to do that.
MAX_DISTANCE = 0.8

# Gibberish ("asdfgh qwerty": 0.80, "blorptang wuzzle": 0.74) lands in the same range
# as real but unrelated queries, so distance alone can't reject it. What gibberish
# lacks is any word the shop knows (from product names, categories or descriptions).
# For such queries we demand a closer match: the good matches measured above are
# 0.34-0.62, and no gibberish query we tried came closer than 0.73.
MAX_DISTANCE_UNKNOWN_WORDS = 0.7

KEYWORD_WEIGHT = 1.0
NAME_MATCH = 1.0         # query word found in the product name
DESCRIPTION_MATCH = 0.3  # ... only in the description
CANDIDATES = 60          # how many products each signal contributes before ranking

# The vocabulary is rebuilt from the database at most every 5 minutes (one query of
# ~200 names), not on every search. Admin product changes clear it immediately.
VOCABULARY_TTL_SECONDS = 300

# Words that carry no meaning for keyword matching ("something for my coffee").
STOPWORDS = {
    "a", "an", "and", "the", "for", "to", "of", "in", "on", "with", "my", "me", "i",
    "is", "it", "some", "something", "that", "this", "best", "good", "buy", "need",
}

SearchMode = Literal["hybrid", "keyword"]


class SearchResult(NamedTuple):
    ids: list[int]                 # best match first
    mode: SearchMode               # which method was used
    corrected_query: str | None    # the query actually searched, if spelling was fixed


def keywords(query: str) -> list[str]:
    """Lower-case words of at least 2 letters, without stopwords or duplicates."""
    words = re.findall(r"[a-z0-9]+", query.lower())
    return list(dict.fromkeys(w for w in words if len(w) >= 2 and w not in STOPWORDS))


def search(session: Session, query: str, limit: int,
           correct_spelling: bool = True) -> SearchResult:
    vocabulary = get_vocabulary(session)
    corrected_query = None
    if correct_spelling:
        correction = spelling.correct_query(query, vocabulary)
        if correction.changed:
            log.info("Search %r corrected to %r", query, correction.corrected)
            query = corrected_query = correction.corrected

    if not product_repository.has_any_embeddings(session):
        log.info("No product embeddings yet; using keyword search.")
        return SearchResult(keyword_search(session, query, limit), "keyword", corrected_query)
    try:
        query_vector = embeddings.embed_text(query)
    except Exception:  # model missing / failed to load: degrade, don't crash the shop
        log.warning("Embedding model unavailable; using keyword search.", exc_info=True)
        return SearchResult(keyword_search(session, query, limit), "keyword", corrected_query)

    words = keywords(query)
    recognised = any(word in vocabulary.known_words for word in words)
    max_distance = MAX_DISTANCE if recognised else MAX_DISTANCE_UNKNOWN_WORDS
    ids = hybrid_search(session, query_vector, words, limit, max_distance)
    return SearchResult(ids, "hybrid", corrected_query)


def hybrid_search(session: Session, query_vector: list[float], words: list[str],
                  limit: int, max_distance: float = MAX_DISTANCE) -> list[int]:
    """Product ids ranked by semantic similarity + KEYWORD_WEIGHT * keyword score."""
    # Candidates: the nearest products by meaning, plus every product containing a word.
    distances = dict(product_repository.nearest_by_vector(
        session, query_vector, CANDIDATES, max_distance=max_distance))
    keyword_scores = {}
    if words:
        for row in product_repository.keyword_matches(session, words, CANDIDATES):
            score = keyword_score(words, row.name, row.description)
            if score > 0:
                keyword_scores[row.id] = score
    # Keyword matches outside the nearest set still need a semantic score.
    missing = [pid for pid in keyword_scores if pid not in distances]
    distances.update(product_repository.distances_for(session, query_vector, missing))

    def total(pid: int) -> float:
        # A product without an embedding yet (just added) gets semantic similarity 0.
        semantic = 1 - distances[pid] if pid in distances else 0.0
        return semantic + KEYWORD_WEIGHT * keyword_scores.get(pid, 0.0)

    ranked = sorted(set(distances) | set(keyword_scores), key=lambda pid: (-total(pid), pid))
    return ranked[:limit]


def keyword_score(words: list[str], name: str, description: str) -> float:
    """0..1: the average over query words of NAME_MATCH / DESCRIPTION_MATCH / 0.

    A word matches at the START of a word in the text, so "shirt" matches "T-Shirt"
    and "shirts", but "men" does not match "women".
    """
    if not words:
        return 0.0
    total = 0.0
    for word in words:
        pattern = re.compile(r"\b" + re.escape(word), re.IGNORECASE)
        if pattern.search(name):
            total += NAME_MATCH
        elif pattern.search(description or ""):
            total += DESCRIPTION_MATCH
    return total / len(words)


def keyword_search(session: Session, query: str, limit: int) -> list[int]:
    words = keywords(query)
    if not words:
        return []
    return product_repository.keyword_search(session, words, limit)


# ---------------------------------------------------------------------------
# Spelling vocabulary cache
# ---------------------------------------------------------------------------

_vocabulary: spelling.Vocabulary | None = None
_vocabulary_built_at = 0.0
_vocabulary_lock = threading.Lock()  # GUI searches run in background threads


def get_vocabulary(session: Session) -> spelling.Vocabulary:
    global _vocabulary, _vocabulary_built_at
    with _vocabulary_lock:
        if _vocabulary is None or time.monotonic() - _vocabulary_built_at > VOCABULARY_TTL_SECONDS:
            names, descriptions = product_repository.vocabulary_texts(session)
            _vocabulary = spelling.build_vocabulary(names, descriptions)
            _vocabulary_built_at = time.monotonic()
        return _vocabulary


def clear_vocabulary_cache() -> None:
    """Called after admin product changes, so new names can be corrected to at once."""
    global _vocabulary
    with _vocabulary_lock:
        _vocabulary = None
