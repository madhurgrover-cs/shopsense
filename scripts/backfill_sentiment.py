"""Compute sentiment scores for reviews that don't have one yet (or for all reviews).

Run from the project root:
    venv\\Scripts\\python -m scripts.backfill_sentiment          # only unscored reviews
    venv\\Scripts\\python -m scripts.backfill_sentiment --all    # rescore every review

New reviews are scored by review_service when they are saved. This script is for
reviews that were inserted another way: the seed script leaves sentiment_score empty
on purpose, so every score in the database comes from the same function
(app.ai.sentiment). Use --all after changing how scores are computed.

The sentiment model (DistilBERT) is loaded ONCE for all reviews, then unloaded. If it
can't be loaded, VADER is used and the script says so.
"""

import argparse

from app.ai import sentiment
from app.db import get_session
from app.repositories import review_repository


def backfill(rescore_all: bool = False) -> tuple[int, int, str | None]:
    """Score reviews in one transaction.
    Returns (reviews scored, scores that changed, engine used: "distilbert" / "vader")."""
    with get_session() as session:
        rows = review_repository.list_for_scoring(session, only_unscored=not rescore_all)
        scores, engine = sentiment.score_many_with_engine([row.comment for row in rows])
        new_scores = {row.id: value for row, value in zip(rows, scores)}
        changed = sum(1 for row in rows if new_scores[row.id] != row.sentiment_score)
        review_repository.set_scores(session, new_scores)
    return len(rows), changed, engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="rescore every review")
    args = parser.parse_args()

    scored, changed, engine = backfill(rescore_all=args.all)
    print(f"Scored {scored} reviews with {engine or 'no model (nothing to score)'} "
          f"({changed} new or changed scores).")
    if engine == sentiment.VADER:
        print("WARNING: the DistilBERT model could not be loaded; VADER was used instead.")


if __name__ == "__main__":
    main()
