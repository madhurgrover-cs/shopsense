"""Import every model here so Base.metadata knows all tables (Alembic relies on this)."""

from app.models.base import Base
from app.models.cart import Cart, CartItem
from app.models.catalog import Category, Inventory, Product, ProductEmbedding
from app.models.order import Coupon, Order, OrderItem, OrderStatusHistory, Payment
from app.models.review import Review
from app.models.user import Address, AuditLog, User

__all__ = [
    "Base",
    "User", "Address", "AuditLog",
    "Category", "Product", "Inventory", "ProductEmbedding",
    "Cart", "CartItem",
    "Coupon", "Order", "OrderItem", "OrderStatusHistory", "Payment",
    "Review",
]
