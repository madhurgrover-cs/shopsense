"""Product reviews with a VADER sentiment score."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column

if TYPE_CHECKING:
    from app.models.catalog import Product
    from app.models.user import User


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
        # VADER's compound score is always in [-1, 1].
        CheckConstraint(
            "sentiment_score IS NULL OR sentiment_score BETWEEN -1 AND 1",
            name="sentiment_range",
        ),
        # One review per user per product. Also the index on user_id (leading column).
        UniqueConstraint("user_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    sentiment_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = created_at_column()

    user: Mapped["User"] = relationship(back_populates="reviews")
    product: Mapped["Product"] = relationship(back_populates="reviews")
