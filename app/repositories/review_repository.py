"""Queries for reviews."""

from sqlalchemy import Row, exists, func, select, update
from sqlalchemy.orm import Session

from app.models import Order, OrderItem, Product, Review, User


def has_received_product(session: Session, user_id: int, product_id: int) -> bool:
    """True if the user has a DELIVERED order containing this product."""
    stmt = select(exists().where(
        OrderItem.product_id == product_id,
        OrderItem.order_id == Order.id,
        Order.user_id == user_id,
        Order.status == "delivered",
    ))
    return session.scalar(stmt)


def reviewable_in_order(session: Session, user_id: int, order_id: int) -> list[int]:
    """Product ids in this user's DELIVERED order that the user hasn't reviewed yet."""
    already_reviewed = exists().where(
        Review.user_id == user_id, Review.product_id == OrderItem.product_id
    )
    stmt = (
        select(OrderItem.product_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.order_id == order_id, Order.user_id == user_id,
               Order.status == "delivered", ~already_reviewed)
        .order_by(OrderItem.id)
    )
    return list(session.scalars(stmt))


def get_by_user_and_product(session: Session, user_id: int, product_id: int) -> Review | None:
    return session.scalars(
        select(Review).where(Review.user_id == user_id, Review.product_id == product_id)
    ).first()


def create(session: Session, user_id: int, product_id: int, rating: int,
           comment: str | None, sentiment_score: float | None) -> Review:
    review = Review(user_id=user_id, product_id=product_id, rating=rating, comment=comment,
                    sentiment_score=sentiment_score)
    session.add(review)
    session.flush()
    return review


def _review_rows_query():
    """Reviews with the reviewer's and product's names (for display)."""
    return (
        select(Review, User.name.label("user_name"), Product.name.label("product_name"))
        .join(User, User.id == Review.user_id)
        .join(Product, Product.id == Review.product_id)
    )


def get_row(session: Session, review_id: int) -> Row | None:
    return session.execute(_review_rows_query().where(Review.id == review_id)).first()


def list_for_product(session: Session, product_id: int) -> list[Row]:
    stmt = (_review_rows_query().where(Review.product_id == product_id)
            .order_by(Review.created_at.desc(), Review.id.desc()))
    return list(session.execute(stmt))


def list_flagged(session: Session, threshold: float) -> list[Row]:
    """Reviews scoring below the threshold, most negative first."""
    stmt = (_review_rows_query().where(Review.sentiment_score < threshold)
            .order_by(Review.sentiment_score, Review.id))
    return list(session.execute(stmt))


def product_stats(session: Session, product_id: int) -> Row:
    """(review_count, scored_count, avg_score, avg_rating) for one product.
    avg() ignores NULL scores, i.e. reviews without a comment."""
    stmt = select(
        func.count(Review.id).label("review_count"),
        func.count(Review.sentiment_score).label("scored_count"),
        func.avg(Review.sentiment_score).label("avg_score"),
        func.avg(Review.rating).label("avg_rating"),
    ).where(Review.product_id == product_id)
    return session.execute(stmt).one()


def list_for_scoring(session: Session, only_unscored: bool = True) -> list[Row]:
    """(id, comment, sentiment_score) of reviews to (re)score."""
    stmt = select(Review.id, Review.comment, Review.sentiment_score).order_by(Review.id)
    if only_unscored:
        stmt = stmt.where(Review.sentiment_score.is_(None), Review.comment.is_not(None))
    return list(session.execute(stmt))


def set_scores(session: Session, scores: dict[int, float | None]) -> None:
    """Bulk update {review id: score} in one round trip."""
    if scores:
        session.execute(
            update(Review),
            [{"id": rid, "sentiment_score": s} for rid, s in scores.items()],
        )


def list_with_ratings(session: Session) -> list[Row]:
    """(id, product_id, rating, comment, sentiment_score) of every review with text, by
    id. Used to compare sentiment engines against the customers' own star ratings."""
    stmt = (select(Review.id, Review.product_id, Review.rating, Review.comment,
                   Review.sentiment_score)
            .where(Review.comment.is_not(None))
            .order_by(Review.id))
    return list(session.execute(stmt))
