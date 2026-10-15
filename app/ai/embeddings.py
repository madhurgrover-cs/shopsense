"""Text embeddings with sentence-transformers all-MiniLM-L6-v2 (CPU only).

An embedding turns a piece of text into 384 numbers so that texts with similar MEANING
get similar vectors, even with no words in common ("protect my phone screen" is close
to "9H tempered glass guard"). Semantic search and "similar products" compare these
vectors in PostgreSQL with pgvector.

Memory rule (4 GB RAM laptop): the model is loaded LAZILY, ONCE.
- Importing this module does NOT import torch / sentence-transformers. Measured on the
  dev machine, that import alone takes ~25 s and ~400 MB, so the app must not pay it at
  startup, only the first time a feature actually needs an embedding.
- The loaded model is cached in a module-level variable and reused for every call.
  A lock makes sure two threads (e.g. GUI background tasks) can't load it twice.
"""

import os

from app.ai import model_lock
from app.models.catalog import EMBEDDING_DIM

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_BATCH_SIZE = 32  # small batches keep peak memory low

_model = None


def get_model():
    """Return the shared model, loading it on the first call only."""
    global _model
    if _model is None:
        # model_lock.LOADING is shared with the sentiment model: never load two at once.
        with model_lock.LOADING:
            if _model is None:  # re-check: another thread may have loaded it meanwhile
                # Windows can't create the symlinks Hugging Face's cache prefers; it
                # falls back to copying files and warns every time. Silence that.
                os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
                # Imported here, not at the top of the file: this is the slow, heavy part.
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer(MODEL_NAME, device="cpu")
                if model.get_embedding_dimension() != EMBEDDING_DIM:
                    raise RuntimeError(
                        f"{MODEL_NAME} returns {model.get_embedding_dimension()}-dim vectors, "
                        f"but the database column is vector({EMBEDDING_DIM})."
                    )
                _model = model
    return _model


def is_model_loaded() -> bool:
    return _model is not None


def product_text(name: str, description: str) -> str:
    """The text we embed for a product: its name, then its description."""
    return f"{name}. {description}".strip()


def embed_texts(texts: list[str], batch_size: int = DEFAULT_BATCH_SIZE) -> list[list[float]]:
    """Embed many texts. Returns one 384-number list per text.

    normalize_embeddings=True scales every vector to length 1. Cosine distance
    (pgvector's <=> operator) then depends only on direction, i.e. on meaning, and
    results are comparable across queries.
    """
    if not texts:
        return []
    vectors = get_model().encode(
        texts, batch_size=batch_size, normalize_embeddings=True,
        show_progress_bar=False, convert_to_numpy=True,
    )
    return vectors.tolist()


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
