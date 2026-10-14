"""Queries for carts and cart items."""

from sqlalchemy import Row, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import Cart, CartItem, Inventory, Product


def get_or_create_cart_id(session: Session, user_id: int) -> int:
    """Return the user's cart id, creating the cart on first use.

    INSERT ... ON CONFLICT DO NOTHING is safe even if two requests for the same user
    arrive together: the UNIQUE(user_id) constraint lets only one insert win, and both
    then read the same cart.
    """
    session.execute(pg_insert(Cart).values(user_id=user_id).on_conflict_do_nothing(
        index_elements=[Cart.user_id]))
    return session.scalar(select(Cart.id).where(Cart.user_id == user_id))


def lock_cart(session: Session, user_id: int) -> Cart | None:
    """Lock the user's cart row (SELECT ... FOR UPDATE). Checkout does this first so a
    double-clicked "Place order" can't run twice on the same cart in parallel."""
    return session.scalars(
        select(Cart).where(Cart.user_id == user_id).with_for_update()
    ).first()


def get_item(session: Session, cart_id: int, product_id: int) -> CartItem | None:
    return session.scalars(
        select(CartItem).where(CartItem.cart_id == cart_id, CartItem.product_id == product_id)
    ).first()


def add_item(session: Session, cart_id: int, product_id: int, qty: int) -> CartItem:
    item = CartItem(cart_id=cart_id, product_id=product_id, qty=qty)
    session.add(item)
    session.flush()
    return item


def delete_item(session: Session, item: CartItem) -> None:
    session.delete(item)
    session.flush()


def list_lines(session: Session, cart_id: int) -> list[Row]:
    """Cart items with the product's current name, price, stock and active flag."""
    stmt = (
        select(
            CartItem.product_id, CartItem.qty, Product.name, Product.price,
            Product.is_active, func.coalesce(Inventory.stock, 0).label("stock"),
        )
        .join(Product, Product.id == CartItem.product_id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .where(CartItem.cart_id == cart_id)
        .order_by(CartItem.id)  # order in which items were added
    )
    return list(session.execute(stmt))


def clear(session: Session, cart_id: int) -> None:
    session.execute(delete(CartItem).where(CartItem.cart_id == cart_id))
