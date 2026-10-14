"""Compute VADER sentiment scores for reviews that don't have one yet.

Run from the project root:
    venv\\Scripts\\python -m scripts.backfill_sentiment          # only unscored reviews
    venv\\Scripts\\python -m scripts.backfill_sentiment --all    # rescore every review

New reviews are scored by review_service when they are saved. This script is for
reviews that were inserted another way: the seed script leaves sentiment_score empty
on purpose, so every score in the database comes from the same function
(app.ai.sentiment.score). Use --all after changing how scores are computed.
"""

import argparse

from app.ai import sentiment
from app.db import get_session
from app.repositories import review_repository


def backfill(rescore_all: bool = False) -> tuple[int, int]:
    """Score reviews in one transaction. Returns (reviews scored, scores that changed)."""
    with get_session() as session:
        rows = review_repository.list_for_scoring(session, only_unscored=not rescore_all)
        new_scores = {row.id: sentiment.score(row.comment) for row in rows}
        changed = sum(1 for row in rows if new_scores[row.id] != row.sentiment_score)
        review_repository.set_scores(session, new_scores)
    return len(rows), changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="rescore every review")
    args = parser.parse_args()

    scored, changed = backfill(rescore_all=args.all)
    print(f"Scored {scored} reviews ({changed} new or changed scores).")


if __name__ == "__main__":
    main()
