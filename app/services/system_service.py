"""App-level checks the GUI needs, without importing the database or AI layers itself."""

from sqlalchemy import text

from app.ai import embeddings
from app.db import get_session


def check_connection() -> None:
    """Run a trivial query. The GUI calls this at startup in the background: Neon's free
    tier suspends idle databases, and the first connection can take a few seconds to
    wake it up, so it's better to pay that cost while the window is already showing."""
    with get_session() as session:
        session.execute(text("SELECT 1"))


def is_search_model_loaded() -> bool:
    """True once the embedding model is in memory. The GUI uses this to warn that the
    FIRST search will take ~30 s (model loading); later searches are fast."""
    return embeddings.is_model_loaded()
