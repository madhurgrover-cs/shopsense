"""Categories, products, stock levels and product embeddings."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column

if TYPE_CHECKING:
    from app.models.review import Review

# all-MiniLM-L6-v2 produces 384-dimensional vectors.
EMBEDDING_DIM = 384


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)

    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price > 0", name="price_positive"),
        Index("ix_products_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # RESTRICT: a category that still has products cannot be deleted.
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, server_default="")
    # Numeric, not float: money must be exact (0.1 + 0.2 != 0.3 in floating point).
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # Soft delete: old orders still reference the product, so we hide it instead of deleting.
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = created_at_column()

    category: Mapped["Category"] = relationship(back_populates="products")
    inventory: Mapped["Inventory | None"] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    embedding: Mapped["ProductEmbedding | None"] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["Review"]] = relationship(back_populates="product")

    def __repr__(self) -> str:
        return f"<Product {self.id} {self.name!r} {self.price}>"


class Inventory(Base):
    """One row per product. Kept separate from products so checkout can lock
    just the stock rows (SELECT ... FOR UPDATE) without locking product details."""

    __tablename__ = "inventory"
    __table_args__ = (CheckConstraint("stock >= 0", name="stock_non_negative"),)

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    stock: Mapped[int] = mapped_column(Integer, server_default="0")

    product: Mapped["Product"] = relationship(back_populates="inventory")


class ProductEmbedding(Base):
    __tablename__ = "product_embeddings"
    __table_args__ = (
        # HNSW = approximate nearest-neighbour index. vector_cosine_ops makes it serve
        # queries that ORDER BY embedding <=> :query (cosine distance).
        Index(
            "ix_product_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))

    product: Mapped["Product"] = relationship(back_populates="embedding")
