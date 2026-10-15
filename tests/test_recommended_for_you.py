"""Tests for "Recommended for you" (recommend.recommended_for_user and
catalog_service.recommended_for_you).

Product embeddings come from the fake bag-of-words embedder and the seed embeddings are
removed inside the test transaction, so the taste-vector search only sees the test's
own products. Product words are deliberately odd ("zorblax") to avoid seed matches.
"""

import pytest

from app.ai import recommend
from app.exceptions import PermissionDeniedError, ValidationError
from app.repositories import product_repository
from app.services import catalog_service
from app.services.dto import ProductSummary
from scripts.build_embeddings import build_missing_embeddings


@pytest.fixture
def shelf(factory, fake_embedder, no_seed_embeddings):
    """Test products with (fake) embeddings, keyed by a short name."""
    cat = factory.category()
    products = {
        "scarf": factory.product(category_id=cat, name="Zorblax Wool Scarf"),
        "gloves": factory.product(category_id=cat, name="Zorblax Wool Gloves"),
        "hat": factory.product(category_id=cat, name="Zorblax Wool Hat"),
        "mouse": factory.product(category_id=cat, name="Quindle Gaming Mouse"),
        "keyboard": factory.product(category_id=cat, name="Quindle Gaming Keyboard"),
    }
    build_missing_embeddings(product_ids=list(products.values()))
    return products


def ids_for(db_session, customer, limit=8):
    return recommend.recommended_for_user(db_session, customer.user_id, limit)


# ---------------------------------------------------------------------------
# Taste vector
# ---------------------------------------------------------------------------

def test_recommends_products_like_the_ones_bought(factory, db_session, customer, shelf):
    factory.order(customer.user_id, [shelf["scarf"]], status="delivered")
    ids = ids_for(db_session, customer, limit=2)
    # The two other "Zorblax Wool" items (never the scarf itself: they already have it).
    assert set(ids) == {shelf["gloves"], shelf["hat"]}


def test_taste_averages_everything_bought(factory, db_session, customer, shelf):
    """Bought wool AND gaming items: the top picks come from both, not just one."""
    factory.order(customer.user_id, [shelf["scarf"], shelf["mouse"]], status="delivered")
    ids = ids_for(db_session, customer, limit=3)
    assert shelf["keyboard"] in ids and ({shelf["gloves"], shelf["hat"]} & set(ids))


def test_which_orders_count(factory, db_session, customer, shelf):
    # Shipped counts for taste (it's on its way); placed doesn't shape the taste but
    # is excluded; cancelled neither shapes the taste nor is excluded.
    factory.order(customer.user_id, [shelf["mouse"]], status="shipped")
    factory.order(customer.user_id, [shelf["keyboard"]], status="placed")
    factory.order(customer.user_id, [shelf["gloves"]], status="cancelled")
    taste = product_repository.purchased_product_ids(db_session, customer.user_id,
                                                     recommend.TASTE_STATUSES)
    assert taste == [shelf["mouse"]]
    ids = ids_for(db_session, customer)
    assert shelf["mouse"] not in ids and shelf["keyboard"] not in ids
    assert shelf["gloves"] in ids  # cancelled: they never got it, so it may be suggested


def test_skips_inactive_and_out_of_stock(factory, db_session, customer, shelf, admin):
    factory.order(customer.user_id, [shelf["scarf"]])
    catalog_service.delete_product(admin, shelf["gloves"])
    catalog_service.update_stock(admin, shelf["hat"], 0)
    ids = ids_for(db_session, customer)
    assert shelf["gloves"] not in ids and shelf["hat"] not in ids


def test_average_embedding(db_session, shelf, fake_embedder):
    a = product_repository.get_embedding(db_session, shelf["scarf"])
    b = product_repository.get_embedding(db_session, shelf["mouse"])
    mean = product_repository.average_embedding(db_session, [shelf["scarf"], shelf["mouse"]])
    assert mean == pytest.approx([(x + y) / 2 for x, y in zip(a, b)], abs=1e-6)
    assert product_repository.average_embedding(db_session, []) is None
    assert product_repository.average_embedding(db_session, [-1]) is None  # no embedding


# ---------------------------------------------------------------------------
# Fallback: top rated
# ---------------------------------------------------------------------------

def test_new_customer_gets_top_rated(db_session, customer):
    assert ids_for(db_session, customer) == product_repository.top_rated_ids(db_session, 8)


def test_too_few_similar_products_are_filled_with_top_rated(factory, db_session, customer,
                                                             shelf):
    factory.order(customer.user_id, [shelf["scarf"]])
    ids = ids_for(db_session, customer, limit=8)
    assert len(ids) == 8 and len(set(ids)) == 8           # no duplicates
    test_ids = set(shelf.values())
    assert set(ids[:4]) == test_ids - {shelf["scarf"]}     # all similar ones first
    assert not test_ids & set(ids[4:])                     # then top-rated seed products


def test_top_rated_order_and_minimum_reviews(factory, db_session):
    reviewers = [factory.user() for _ in range(3)]
    best = factory.product(name="Test Best")        # 5, 5, 5
    good = factory.product(name="Test Good")        # 4, 4
    lucky = factory.product(name="Test Lucky")      # a single 5: not enough reviews
    gone = factory.product(name="Test Gone", stock=0)
    for user in reviewers:
        factory.review(user.user_id, best, 5)
        factory.review(user.user_id, gone, 5)
    for user in reviewers[:2]:
        factory.review(user.user_id, good, 4)
    factory.review(reviewers[0].user_id, lucky, 5)

    ranked = product_repository.top_rated_ids(db_session, 1000)
    assert ranked.index(best) < ranked.index(good)
    assert lucky not in ranked and gone not in ranked   # one review / out of stock
    assert best not in product_repository.top_rated_ids(db_session, 1000, exclude_ids=[best])


# ---------------------------------------------------------------------------
# catalog_service.recommended_for_you
# ---------------------------------------------------------------------------

def test_service_returns_up_to_8_product_summaries(factory, customer, shelf):
    factory.order(customer.user_id, [shelf["scarf"]])
    products = catalog_service.recommended_for_you(customer)
    assert 1 <= len(products) <= catalog_service.MAX_RECOMMENDED == 8
    assert all(isinstance(p, ProductSummary) for p in products)
    assert products[0].name.startswith("Zorblax Wool")
    assert len(catalog_service.recommended_for_you(customer, limit=3)) == 3


def test_service_validation(customer):
    for bad in (0, 9, "8", True):
        with pytest.raises(ValidationError):
            catalog_service.recommended_for_you(customer, limit=bad)
    with pytest.raises(PermissionDeniedError):
        catalog_service.recommended_for_you(None)
