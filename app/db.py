"""Database engine and session factory.

Usage (in services only — GUI code never touches sessions):

    from app.db import get_session

    with get_session() as session:
        ...            # commits on success, rolls back on any exception
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import DATABASE_URL, SQL_ECHO

# pool_pre_ping: Neon suspends idle compute and drops connections; pre-ping detects a
#   dead connection and replaces it instead of failing the first query.
# pool_size kept small: free tier + 4 GB dev machine, a desktop app needs few connections.
engine = create_engine(
    DATABASE_URL,
    echo=SQL_ECHO,
    pool_pre_ping=True,
    pool_size=3,
    max_overflow=2,
    pool_recycle=300,
)

# expire_on_commit=False lets services return ORM objects to the GUI after commit
# without triggering lazy reloads on a closed session.
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def get_session() -> Iterator[Session]:
    """Open a session as one unit of work: commit if the block succeeds, else roll back."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
