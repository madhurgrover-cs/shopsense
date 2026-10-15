"""Product reviews with sentiment scores (DistilBERT, VADER fallback), product badges
and flagged reviews."""

from sqlalchemy.exc import IntegrityError

from app.ai import sentiment
from app.db import get_session
from app.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from app.repositories import product_repository, review_repository
from app.services.auth_service import require_admin, require_login
from app.services.dto import ProductSentiment, ReviewInfo
from app.services.user_session import UserSession

MAX_COMMENT_LENGTH = 2000


def can_review(user: UserSession, product_id: int) -> bool:
    """Should the GUI show the "Write a review" button for this product?"""
    require_login(user)
    with get_session() as session:
        return (
            review_repository.has_received_product(session, user.user_id, product_id)
            and review_repository.get_by_user_and_product(
                session, user.user_id, product_id) is None
        )


def reviewable_products(user: UserSession, order_id: int) -> set[int]:
    """Products in one of the user's orders that can be reviewed now (order delivered,
    not reviewed yet). One call for the whole order, so the order screen can show a
    "Write review" button per item without a query per item."""
    require_login(user)
    with get_session() as session:
        return set(review_repository.reviewable_in_order(session, user.user_id, order_id))


def add_review(user: UserSession, product_id: int, rating: int,
               comment: str | None = None) -> ReviewInfo:
    """Add a review. Only for a product the user received (a DELIVERED order), and
    only once per product. The sentiment score is computed here, when it is saved: this
    loads the sentiment model for a few seconds, so the GUI calls it in a background
    thread (it already does, like every service call)."""
    require_login(user)
    if not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5:
        raise ValidationError("Rating must be a whole number from 1 to 5.")
    comment = (comment or "").strip() or None
    if comment is not None and len(comment) > MAX_COMMENT_LENGTH:
        raise ValidationError(f"Review must be at most {MAX_COMMENT_LENGTH} characters.")

    try:
        with get_session() as session:
            if product_repository.get(session, product_id) is None:
                raise NotFoundError("Product not found.")
            if not review_repository.has_received_product(session, user.user_id, product_id):
                raise PermissionDeniedError(
                    "You can only review products from your delivered orders.")
            if review_repository.get_by_user_and_product(session, user.user_id, product_id):
                raise ValidationError("You have already reviewed this product.")
            review = review_repository.create(
                session, user.user_id, product_id, rating, comment, sentiment.score(comment)
            )
            return _to_info(review_repository.get_row(session, review.id))
    except IntegrityError as error:
        # Two submissions at the same moment: UNIQUE(user_id, product_id) stops the second.
        raise ValidationError("You have already reviewed this product.") from error


def list_product_reviews(product_id: int) -> list[ReviewInfo]:
    """Reviews of a product, newest first."""
    with get_session() as session:
        return [_to_info(r) for r in review_repository.list_for_product(session, product_id)]


def get_product_sentiment(product_id: int) -> ProductSentiment:
    """Review count, average rating, average sentiment and the badge for a product."""
    with get_session() as session:
        stats = review_repository.product_stats(session, product_id)
    avg_score = None if stats.avg_score is None else round(float(stats.avg_score), 4)
    avg_rating = None if stats.avg_rating is None else round(float(stats.avg_rating), 2)
    return ProductSentiment(product_id, stats.review_count, avg_rating, avg_score,
                            sentiment.badge(avg_score))


def list_flagged_reviews(admin: UserSession) -> list[ReviewInfo]:
    """Admin: reviews with a sentiment score below -0.3, most negative first."""
    require_admin(admin)
    with get_session() as session:
        rows = review_repository.list_flagged(session, sentiment.FLAG_THRESHOLD)
        return [_to_info(r) for r in rows]


def _to_info(row) -> ReviewInfo:
    r = row.Review
    return ReviewInfo(r.id, r.product_id, row.product_name, r.user_id, row.user_name,
                      r.rating, r.comment, r.sentiment_score, r.created_at)
