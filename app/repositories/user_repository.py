"""All database queries for users. Functions take the caller's session; they never
commit. The service that calls them owns the transaction."""

from sqlalchemy import Row, case, func, select
from sqlalchemy.orm import Session

from app.models import Order, User


def get_by_id(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def get_by_email(session: Session, email: str, for_update: bool = False) -> User | None:
    """Find a user by (already normalised, lower-case) email.

    for_update=True locks the row (SELECT ... FOR UPDATE) until the transaction ends.
    Login uses this so two simultaneous wrong attempts can't both read
    failed_logins = 3 and both write 4: the second waits for the first.
    """
    stmt = select(User).where(User.email == email)
    if for_update:
        stmt = stmt.with_for_update()
    return session.scalars(stmt).first()


def create(session: Session, name: str, email: str, password_hash: str,
           role: str = "customer") -> User:
    user = User(name=name, email=email, password_hash=password_hash, role=role)
    session.add(user)
    session.flush()  # sends the INSERT now, so user.id is set and unique errors surface here
    return user


def list_customers_with_stats(session: Session) -> list[Row]:
    """(User, order_count, total_spent, last_order_at) for every customer, by name.

    LEFT JOIN so customers without orders are listed too (count 0, spent 0). Cancelled
    orders count as orders but not as money spent (it was refunded).
    """
    spent = func.coalesce(
        func.sum(case((Order.status != "cancelled", Order.total), else_=0)), 0)
    stmt = (
        select(User, func.count(Order.id).label("order_count"), spent.label("total_spent"),
               func.max(Order.created_at).label("last_order_at"))
        .outerjoin(Order, Order.user_id == User.id)
        .where(User.role == "customer")
        .group_by(User.id)
        .order_by(User.name, User.id)
    )
    return list(session.execute(stmt))
