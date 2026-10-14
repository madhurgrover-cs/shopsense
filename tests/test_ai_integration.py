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

    # 3. Queries sharing NO words with the product they should find.
    def top(query):
        return catalog_service.search_products(query, limit=4)[0].id
    assert top("warm winter wear") == scarf
    assert top("something for my morning coffee") == grinder
    assert top("gift for a gamer") in {headset, keyboard}

    # 4. Similar products: the other gaming accessory is closest to the headset.
    assert catalog_service.similar_products(headset, limit=1)[0].id == keyboard
