"""Tests for VADER sentiment, review_service and the sentiment backfill script."""

import pytest

from app.ai import sentiment
from app.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from app.models import Review
from app.repositories import review_repository
from app.services import review_service
from scripts.backfill_sentiment import backfill


# ---------------------------------------------------------------------------
# app.ai.sentiment
# ---------------------------------------------------------------------------

def test_score_sign_matches_tone():
    assert sentiment.score("Absolutely love it, excellent quality!") > 0.5
    assert sentiment.score("Terrible. Broke after two days, total waste.") < -0.5
    assert -1 <= sentiment.score("It is a kettle.") <= 1


@pytest.mark.parametrize("text", [None, "", "   "])
def test_score_without_text_is_none(text):
    assert sentiment.score(text) is None


@pytest.mark.parametrize("average, expected", [
    (None, None),
    (0.25, "Positive"), (0.9, "Positive"),
    (0.2499, "Mixed"), (0.0, "Mixed"), (-0.2499, "Mixed"),
    (-0.25, "Negative"), (-0.9, "Negative"),
])
def test_badge_thresholds(average, expected):
    assert sentiment.badge(average) == expected


def test_is_flagged_is_strictly_below_threshold():
    assert sentiment.is_flagged(-0.31)
    assert not sentiment.is_flagged(-0.3)
    assert not sentiment.is_flagged(None)


# ---------------------------------------------------------------------------
# add_review / can_review
# ---------------------------------------------------------------------------

@pytest.fixture
def bought(factory, customer):
    """A product the customer received in a delivered order."""
    pid = factory.product(name="Test Reviewed Kettle")
    factory.order(customer.user_id, [pid], status="delivered")
    return pid


def test_add_review_scores_sentiment(bought, customer):
    review = review_service.add_review(customer, bought, 5, "  Excellent kettle, love it! ")
    assert review.comment == "Excellent kettle, love it!"     # trimmed
    assert review.rating == 5 and review.sentiment_score > 0.5
    assert review.sentiment_score == sentiment.score("Excellent kettle, love it!")
    assert (review.product_name, review.user_name) == ("Test Reviewed Kettle", customer.name)


def test_add_review_without_comment_has_no_score(bought, customer):
    assert review_service.add_review(customer, bought, 4, "   ").sentiment_score is None


@pytest.mark.parametrize("status", ["placed", "shipped", "cancelled"])
def test_cannot_review_product_not_yet_received(factory, customer, status):
    pid = factory.product()
    factory.order(customer.user_id, [pid], status=status)
    assert review_service.can_review(customer, pid) is False
    with pytest.raises(PermissionDeniedError, match="delivered"):
        review_service.add_review(customer, pid, 5, "Great")


def test_cannot_review_product_bought_by_someone_else(factory, bought):
    with pytest.raises(PermissionDeniedError):
        review_service.add_review(factory.user(), bought, 1, "Never bought it")


def test_one_review_per_product(bought, customer):
    assert review_service.can_review(customer, bought) is True
    review_service.add_review(customer, bought, 4, "Good")
    assert review_service.can_review(customer, bought) is False
    with pytest.raises(ValidationError, match="already reviewed"):
        review_service.add_review(customer, bought, 1, "Changed my mind")


def test_duplicate_caught_by_database_constraint(bought, customer, monkeypatch):
    review_service.add_review(customer, bought, 4, "Good")
    monkeypatch.setattr(review_repository, "get_by_user_and_product", lambda *a, **k: None)
    with pytest.raises(ValidationError, match="already reviewed"):
        review_service.add_review(customer, bought, 5, "Submitted twice")


@pytest.mark.parametrize("rating", [0, 6, 3.5, True, "5"])
def test_add_review_rating_validation(bought, customer, rating):
    with pytest.raises(ValidationError):
        review_service.add_review(customer, bought, rating, "ok")


def test_add_review_other_errors(bought, customer):
    with pytest.raises(ValidationError, match="at most"):
        review_service.add_review(customer, bought, 3, "x" * 2001)
    with pytest.raises(NotFoundError):
        review_service.add_review(customer, -1, 3, "ok")
    with pytest.raises(PermissionDeniedError):
        review_service.add_review(None, bought, 3, "ok")
    with pytest.raises(PermissionDeniedError):
        review_service.can_review(None, bought)


# ---------------------------------------------------------------------------
# Listing, product sentiment, flagged reviews
# ---------------------------------------------------------------------------

def test_list_product_reviews_newest_first(factory, bought, customer):
    first = factory.review(customer.user_id, bought, 5, "Nice")
    second = factory.review(factory.user().user_id, bought, 2, "Meh")
    reviews = review_service.list_product_reviews(bought)
    assert [r.id for r in reviews] == [second, first]   # same timestamp in a test: id breaks tie


def test_product_sentiment_badge(factory):
    pid = factory.product()
    users = [factory.user().user_id for _ in range(3)]
    factory.review(users[0], pid, 5, "Love it", score=0.9)
    factory.review(users[1], pid, 4, "Nice", score=0.5)
    factory.review(users[2], pid, 3, None, score=None)     # counted, but has no score

    result = review_service.get_product_sentiment(pid)
    assert result.review_count == 3
    assert result.avg_score == 0.7 and result.avg_rating == 4.0
    assert result.badge == "Positive"


def test_product_sentiment_mixed_negative_and_none(factory):
    mixed, negative, unreviewed = factory.product(), factory.product(), factory.product()
    a, b = factory.user().user_id, factory.user().user_id
    factory.review(a, mixed, 5, "Great", score=0.9)
    factory.review(b, mixed, 1, "Awful", score=-0.9)
    factory.review(a, negative, 1, "Broken", score=-0.8)

    assert review_service.get_product_sentiment(mixed).badge == "Mixed"
    assert review_service.get_product_sentiment(negative).badge == "Negative"
    empty = review_service.get_product_sentiment(unreviewed)
    assert (empty.review_count, empty.avg_score, empty.badge) == (0, None, None)


def test_list_flagged_reviews(factory, admin):
    pid = factory.product()
    users = [factory.user().user_id for _ in range(3)]
    worst = factory.review(users[0], pid, 1, "Awful", score=-0.95)
    bad = factory.review(users[1], pid, 2, "Bad", score=-0.31)
    borderline = factory.review(users[2], pid, 3, "Hmm", score=-0.3)   # not below -0.3

    flagged_ids = [r.id for r in review_service.list_flagged_reviews(admin)]
    assert worst in flagged_ids and bad in flagged_ids and borderline not in flagged_ids
    assert flagged_ids.index(worst) < flagged_ids.index(bad)          # most negative first


def test_list_flagged_reviews_is_admin_only(customer):
    with pytest.raises(PermissionDeniedError):
        review_service.list_flagged_reviews(customer)


# ---------------------------------------------------------------------------
# Backfill script
# ---------------------------------------------------------------------------

def test_backfill_scores_unscored_reviews_and_is_rerunnable(factory, db_session):
    pid = factory.product()
    a, b, c = (factory.user().user_id for _ in range(3))
    positive = factory.review(a, pid, 5, "Excellent, works perfectly!")
    negative = factory.review(b, pid, 1, "Horrible, broke immediately.")
    no_text = factory.review(c, pid, 3, None)

    scored, changed = backfill()
    assert scored >= 2 and changed >= 2  # also any unscored seed reviews, inside the rollback

    db_session.expire_all()
    assert db_session.get(Review, positive).sentiment_score > 0.5
    assert db_session.get(Review, negative).sentiment_score < -0.5
    assert db_session.get(Review, no_text).sentiment_score is None  # nothing to score

    assert backfill() == (0, 0)  # second run: nothing left to do


def test_backfill_all_rescores_and_reports_changes(factory, db_session):
    pid = factory.product()
    stale = factory.review(factory.user().user_id, pid, 5, "Excellent, works perfectly!",
                           score=-0.99)  # wrong on purpose
    backfill()  # make sure everything else is scored first

    total_reviews = db_session.query(Review).count()
    scored, changed = backfill(rescore_all=True)
    assert scored == total_reviews and changed == 1  # only the stale one changes
    db_session.expire_all()
    assert db_session.get(Review, stale).sentiment_score > 0.5


# ---------------------------------------------------------------------------
# reviewable_products (order screen)
# ---------------------------------------------------------------------------

def test_reviewable_products_in_delivered_order(factory, customer):
    a, b, c = factory.product(), factory.product(), factory.product()
    order = factory.order(customer.user_id, [a, b, c], status="delivered")
    factory.review(customer.user_id, b, 5, "Already reviewed")
    assert review_service.reviewable_products(customer, order) == {a, c}

    review_service.add_review(customer, a, 4, "Nice")
    assert review_service.reviewable_products(customer, order) == {c}


def test_reviewable_products_empty_for_undelivered_or_foreign_orders(factory, customer):
    pid = factory.product()
    shipped = factory.order(customer.user_id, [pid], status="shipped")
    someone_elses = factory.order(factory.user().user_id, [pid], status="delivered")
    assert review_service.reviewable_products(customer, shipped) == set()
    assert review_service.reviewable_products(customer, someone_elses) == set()
    with pytest.raises(PermissionDeniedError):
        review_service.reviewable_products(None, shipped)
