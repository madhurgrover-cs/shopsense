"""Compute embeddings for products that don't have one yet.

Run from the project root:   venv\\Scripts\\python -m scripts.build_embeddings

Re-runnable: only active products WITHOUT an embedding are processed. The catalog
service deletes a product's embedding when its name or description changes, so running
this again after edits re-embeds exactly the edited products (and new ones).

Run it after scripts.seed (which truncates product_embeddings) and after editing products.
"""

import time
from collections.abc import Sequence

from app.ai import embeddings
from app.db import get_session
from app.repositories import product_repository


def build_missing_embeddings(batch_size: int = embeddings.DEFAULT_BATCH_SIZE,
                             product_ids: Sequence[int] | None = None,
                             verbose: bool = False) -> int:
    """Embed every active product that has no embedding. Returns how many were embedded.

    product_ids limits the work to those products (used by tests).
    """
    # Nothing to do? Then don't load the model at all (it costs ~30 s and ~300 MB).
    with get_session() as session:
        if not product_repository.list_missing_embeddings(session, product_ids, limit=1):
            return 0

    # Load the model BEFORE opening the batch transactions: the first load takes ~30 s
    # and we don't want to hold database locks while it happens.
    embeddings.get_model()

    total = 0
    while True:
        # One short transaction per batch: read the texts (locking those rows),
        # embed them (~0.1 s for 32 products once the model is loaded), save, commit.
        # If the script is interrupted, finished batches are kept; re-running continues.
        with get_session() as session:
            rows = product_repository.list_missing_embeddings(
                session, product_ids, limit=batch_size, lock=True
            )
            if not rows:
                break
            texts = [embeddings.product_text(r.name, r.description) for r in rows]
            vectors = embeddings.embed_texts(texts, batch_size=batch_size)
            product_repository.save_embeddings(
                session, {r.id: v for r, v in zip(rows, vectors)}
            )
        total += len(rows)
        if verbose:
            print(f"  embedded {total} products...")
    return total


def main() -> None:
    started = time.perf_counter()
    print("Checking for products without embeddings "
          "(the model is loaded only if needed; ~30 s, first run downloads ~90 MB)...")
    count = build_missing_embeddings(verbose=True)
    with get_session() as session:
        done, active = product_repository.count_embeddings(session)
    print(f"Embedded {count} products in {time.perf_counter() - started:.1f}s. "
          f"Coverage: {done}/{active} active products.")


if __name__ == "__main__":
    main()
