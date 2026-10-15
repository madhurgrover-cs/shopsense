"""App-level checks the GUI needs, without importing the database or AI layers itself."""

import logging

from sqlalchemy import text

from app.ai import embeddings
from app.db import get_session

log = logging.getLogger(__name__)


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


def preload_search_model() -> bool:
    """Load the embedding model now, so the customer's first search doesn't wait ~30 s.

    The GUI calls this in a background thread right after a customer logs in (not at
    app startup: the login screen stays light, and admins never pay for it). Returns
    False if the model can't be loaded, e.g. no internet on the very first run; search
    then still works with keywords.
    """
    try:
        embeddings.get_model()
        return True
    except Exception:
        log.warning("Could not preload the embedding model.", exc_info=True)
        return False
