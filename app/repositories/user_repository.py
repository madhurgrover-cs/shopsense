"""All database queries for users. Functions take the caller's session; they never
commit. The service that calls them owns the transaction."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User


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
