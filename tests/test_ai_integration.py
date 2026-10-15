"""Integration test with the REAL embedding model (slow: ~30 s to load it once).

Every other AI test uses the fake bag-of-words embedder. This one checks the things a
fake can't: that the real model produces normalised 384-dim vectors, and that search
and "similar products" work on MEANING, with queries that share no words with the
product they should find. Skip it with:  pytest -m "not integration"
"""

import math

import pytest

from app.ai import embeddings
from app.models.catalog import EMBEDDING_DIM
from app.services import catalog_service
from scripts.build_embeddings import build_missing_embeddings


@pytest.mark.integration
def test_real_model_search_and_similar_products(factory, db_session, no_seed_embeddings):
    # 1. The model itself.
    vectors = embeddings.embed_texts(["a red cricket ball", "a cotton kurta"])
    for v in vectors:
        assert len(v) == EMBEDDING_DIM
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-5)

    # 2. Real embeddings for a few test products (seed embeddings removed for this test).
    cat = factory.category()
    scarf = factory.product(
        category_id=cat, name="Test Pashmina Shawl",
        description="A soft shawl woven from fine Kashmiri wool that keeps you cosy on "
                    "cold, snowy evenings.")
    grinder = factory.product(
        category_id=cat, name="Test Burr Grinder",
        description="Grinds espresso beans fresh for a rich, aromatic cup at breakfast.")
    headset = factory.product(
        category_id=cat, name="Test RGB Headset",
        description="Surround-sound headset with a noise-cancelling mic for PC and "
                    "console gaming sessions.")
    keyboard = factory.product(
        category_id=cat, name="Test Mechanical Keyboard",
        description="RGB-lit mechanical keyboard with fast switches for competitive "
                    "gaming and esports.")
    assert build_missing_embeddings(product_ids=[scarf, grinder, headset, keyboard]) == 4

    # 3. Queries sharing NO words with the product they should find. Only our four
    #    products are compared: seed products have no embedding here, but hybrid search
    #    still finds them by keyword (e.g. a seed "Winter ... Hoodie" for "winter").
    ours = {scarf, grinder, headset, keyboard}

    def top(query):
        results = catalog_service.search_products(query, limit=20)
        return next(p.id for p in results if p.id in ours)
    assert top("warm winter wear") == scarf
    assert top("something for my morning coffee") == grinder
    assert top("gift for a gamer") in {headset, keyboard}

    # 4. Similar products: the other gaming accessory is closest to the headset.
    assert catalog_service.similar_products(headset, limit=1)[0].id == keyboard


@pytest.mark.integration
@pytest.mark.parametrize("typed, meant", [
    ("sirt", "shirt"), ("shrt", "shirt"), ("hodie", "hoodie"),
    ("laptp", "laptop"), ("keybord", "keyboard"),
])
def test_real_catalog_typo_search(db_session, typed, meant):
    """On the seeded catalog (read-only): the typo is corrected, and the first results
    are the products whose NAME contains the word (hybrid ranking)."""
    result = catalog_service.search(typed, limit=10)
    assert result.corrected_query == meant
    assert meant in result.products[0].name.lower()
    assert all(meant in p.name.lower() for p in result.products[:4])


@pytest.mark.integration
@pytest.mark.parametrize("query", ["warm winter wear", "gift for a gamer",
                                   "protect my phone screen", "running shoes"])
def test_real_catalog_normal_queries_are_not_corrected(db_session, query):
    result = catalog_service.search(query, limit=5)
    assert result.corrected_query is None and result.products


@pytest.mark.integration
@pytest.mark.parametrize("query", ["asdfgh qwerty", "xkcdqz", "blorptang wuzzle",
                                   "jjjjj kkkk"])
def test_real_catalog_gibberish_returns_nothing(db_session, query):
    result = catalog_service.search(query, limit=10)
    assert result.products == [] and result.corrected_query is None


@pytest.mark.integration
def test_real_sentiment_model():
    """The real DistilBERT model, with the calibrated thresholds (sentiment.py)."""
    from app.ai import sentiment

    expected_better = ("Poor quality cricket ball. Customer support was slow and "
                       "unhelpful. I expected much better.")
    texts = [expected_better,
             "Excellent kettle, boils fast and looks great. Very happy with it.",
             "Average power bank. Some good points, some bad points. Mixed feelings overall.",
             "Terrible. Broke after two days, total waste of money."]
    (complaint, praise, mixed, angry), engine = sentiment.score_many_with_engine(texts)

    assert engine == sentiment.TRANSFORMER
    assert sentiment.vader_score(expected_better) > 0      # VADER: fooled by "better"
    assert sentiment.is_flagged(complaint)                 # the model: a complaint
    assert sentiment.is_flagged(angry)
    assert praise > sentiment.POSITIVE_THRESHOLD
    assert sentiment.FLAG_THRESHOLD < mixed < 0            # mixed: negative-ish, not flagged
    assert not sentiment.is_model_loaded()                 # unloaded right after scoring
