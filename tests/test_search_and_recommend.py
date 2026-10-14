"""Unit tests for semantic search, keyword fallback and recommendations.

They use the fake embedder (bag-of-words vectors, see conftest) and delete the seed
embeddings inside the rollback transaction, so only the test's own products compete.
Product words are deliberately odd ("zorblax") so seed products never match keywords.
"""

import pytest

from app.ai import embeddings, recommend, search
from app.exceptions import ValidationError
from app.models import Product
from app.repositories import product_repository
from app.services import catalog_service
from app.services.dto import ProductSummary
from scripts.build_embeddings import build_missing_embeddings


@pytest.fixture
def catalog(factory, fake_embedder, no_seed_embeddings):
    """Four test products with (fake) embeddings, keyed by a short name."""
    cat = factory.category()
    products = {
        "scarf": factory.product(category_id=cat, name="Zorblax Wool Scarf"),
        "gloves": factory.product(category_id=cat, name="Zorblax Wool Gloves"),
        "grinder": factory.product(category_id=cat, name="Quindle Coffee Grinder"),
        "mouse": factory.product(category_id=cat, name="Quindle Gaming Mouse"),
    }
    build_missing_embeddings(product_ids=list(products.values()))
    return products


# ---------------------------------------------------------------------------
# Keywords helper
# ---------------------------------------------------------------------------

def test_keywords_drops_stopwords_short_words_and_duplicates():
    assert search.keywords("Something for MY morning coffee, coffee!") == ["morning", "coffee"]
    assert search.keywords("a the for") == []


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------

def test_semantic_search_ranks_by_similarity(db_session, catalog):
    ids, mode = search.search(db_session, "zorblax wool scarf", limit=10)
    assert mode == "semantic"
    assert ids[0] == catalog["scarf"]          # shares 3 words
    assert ids[1] == catalog["gloves"]         # shares 2 words
    assert catalog["mouse"] not in ids         # shares none: beyond MAX_DISTANCE


def test_semantic_search_drops_unrelated_results(db_session, catalog):
    assert search.search(db_session, "xylophone", limit=10) == ([], "semantic")


def test_semantic_search_excludes_inactive_products(db_session, catalog, admin):
    catalog_service.delete_product(admin, catalog["scarf"])
    ids, _ = search.search(db_session, "zorblax wool scarf", limit=10)
    assert catalog["scarf"] not in ids and catalog["gloves"] in ids


def test_semantic_search_respects_limit(db_session, catalog):
    ids, _ = search.search(db_session, "zorblax quindle wool coffee gaming", limit=2)
    assert len(ids) == 2


# ---------------------------------------------------------------------------
# Keyword fallback
# ---------------------------------------------------------------------------

def test_falls_back_to_keywords_when_no_embeddings_exist(factory, db_session,
                                                         no_seed_embeddings, monkeypatch):
    def must_not_embed(*args, **kwargs):
        raise AssertionError("no point embedding the query without product embeddings")
    monkeypatch.setattr(embeddings, "embed_texts", must_not_embed)
    pid = factory.product(name="Zorblax Thermal Flask")

    assert search.search(db_session, "thermal zorblax", limit=5) == ([pid], "keyword")


def test_falls_back_to_keywords_when_model_fails(db_session, catalog, monkeypatch):
    def broken_model(*args, **kwargs):
        raise OSError("could not download model")
    monkeypatch.setattr(embeddings, "embed_texts", broken_model)

    ids, mode = search.search(db_session, "gaming quindle", limit=5)
    assert mode == "keyword"
    assert ids[0] == catalog["mouse"]  # matches both words in its name


def test_keyword_search_ranks_name_matches_above_description(factory, db_session):
    in_name = factory.product(name="Test Plorbix Lamp")
    in_description = factory.product(name="Test Desk Light")
    db_session.get(Product, in_description).description = "Works like a plorbix."
    db_session.commit()

    assert search.keyword_search(db_session, "plorbix", 10) == [in_name, in_description]


def test_keyword_search_treats_wildcards_literally(factory, db_session):
    """At the repository level a typed % or _ must match itself, not "anything"."""
    pid = factory.product(name="Test Zorblax 50 Pack")
    assert product_repository.keyword_search(db_session, ["zorblax"], 10) == [pid]
    assert product_repository.keyword_search(db_session, ["zorbl%"], 10) == []
    assert product_repository.keyword_search(db_session, ["zorbla_"], 10) == []


def test_keyword_search_with_only_stopwords(db_session):
    assert search.keyword_search(db_session, "for the", 10) == []


# ---------------------------------------------------------------------------
# catalog_service.search_products
# ---------------------------------------------------------------------------

def test_search_products_returns_product_summaries(db_session, catalog):
    results = catalog_service.search_products("  zorblax wool gloves ", limit=5)
    assert all(isinstance(r, ProductSummary) for r in results)
    assert results[0].id == catalog["gloves"] and results[0].name == "Zorblax Wool Gloves"
    assert results[0].stock == 10 and results[0].category.startswith("Test Category")


def test_search_products_validation(db_session):
    assert catalog_service.search_products("   ") == []
    for bad in (0, 51, "5"):
        with pytest.raises(ValidationError):
            catalog_service.search_products("scarf", limit=bad)


# ---------------------------------------------------------------------------
# Frequently bought together
# ---------------------------------------------------------------------------

def test_frequently_bought_together_counts_and_orders(factory, customer, db_session):
    phone, case, glass, charger = (factory.product() for _ in range(4))
    for _ in range(3):
        factory.order(customer.user_id, [phone, case])
    factory.order(customer.user_id, [phone, glass])
    factory.order(customer.user_id, [phone, glass])
    factory.order(customer.user_id, [phone, charger])          # only once: below minimum

    assert recommend.frequently_bought_together(db_session, phone, limit=5) == [
        (case, 3), (glass, 2)]
    # Works both ways: the case's top companion is the phone.
    assert recommend.frequently_bought_together(db_session, case, limit=5) == [(phone, 3)]
    assert recommend.frequently_bought_together(db_session, phone, 5, min_count=1)[-1] == (charger, 1)
    assert recommend.frequently_bought_together(db_session, phone, limit=1) == [(case, 3)]


def test_frequently_bought_together_ignores_cancelled_and_inactive(factory, customer,
                                                                   db_session):
    phone, case, hidden = factory.product(), factory.product(), factory.product(active=False)
    for _ in range(2):
        factory.order(customer.user_id, [phone, case], status="cancelled")
        factory.order(customer.user_id, [phone, hidden])
    assert recommend.frequently_bought_together(db_session, phone, limit=5) == []


def test_frequently_bought_together_service(factory, customer):
    bat, ball = factory.product(name="Test Bat"), factory.product(name="Test Ball")
    factory.order(customer.user_id, [bat, ball])
    factory.order(customer.user_id, [bat, ball], status="shipped")
    [result] = catalog_service.frequently_bought_together(bat)
    assert (result.id, result.name) == (ball, "Test Ball")


# ---------------------------------------------------------------------------
# Similar products
# ---------------------------------------------------------------------------

def test_similar_products_excludes_itself(db_session, catalog):
    results = recommend.similar_products(db_session, catalog["scarf"], limit=3)
    ids = [pid for pid, _distance in results]
    assert catalog["scarf"] not in ids
    assert ids[0] == catalog["gloves"]  # "Zorblax Wool ..." is closest
    distances = [d for _pid, d in results]
    assert distances == sorted(distances)


def test_similar_products_excludes_inactive(db_session, catalog, admin):
    catalog_service.delete_product(admin, catalog["gloves"])
    ids = [pid for pid, _ in recommend.similar_products(db_session, catalog["scarf"], 5)]
    assert catalog["gloves"] not in ids


def test_similar_products_without_embedding_is_empty(factory, db_session, no_seed_embeddings):
    assert recommend.similar_products(db_session, factory.product(), limit=5) == []


def test_similar_products_service(catalog):
    results = catalog_service.similar_products(catalog["grinder"], limit=1)
    assert [r.id for r in results] == [catalog["mouse"]]  # shares "Quindle"
    with pytest.raises(ValidationError):
        catalog_service.similar_products(catalog["grinder"], limit=0)
