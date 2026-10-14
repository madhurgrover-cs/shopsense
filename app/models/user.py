"""Users, their addresses, and the audit log."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column

if TYPE_CHECKING:
    from app.models.cart import Cart
    from app.models.order import Order
    from app.models.review import Review


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'customer')", name="role_valid"),
        CheckConstraint("failed_logins >= 0", name="failed_logins_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))  # bcrypt hash, never plain text
    role: Mapped[str] = mapped_column(String(20), server_default="customer")
    # Account lockout: after 5 failed logins, locked_until = now + 15 minutes.
    failed_logins: Mapped[int] = mapped_column(Integer, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()

    addresses: Mapped[list["Address"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    cart: Mapped["Cart | None"] = relationship(back_populates="user")
    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    reviews: Mapped[list["Review"]] = relationship(back_populates="user")

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email} ({self.role})>"


class Address(Base):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    line1: Mapped[str] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(100))
    pincode: Mapped[str] = mapped_column(String(10))  # text, not int: keeps leading zeros

    user: Mapped["User"] = relationship(back_populates="addresses")


class AuditLog(Base):
    """Who did what to which record, e.g. ("update", "product", 42)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    # SET NULL: deleting a user must not erase the history of what they did.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(50))
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int | None]
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
