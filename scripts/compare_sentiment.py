"""Compare VADER with the DistilBERT sentiment model on every review (read-only).

Run from the project root:
    venv\\Scripts\\python -m scripts.compare_sentiment

The customers' own star ratings are the yardstick:
- 4-5 stars should score positive, 1-2 stars negative. 3-star reviews are "mixed" and
  have no right sign, so they are left out of the agreement figure (their average is
  shown instead).
- Flagging: a flagged review should be a 1-2 star review.
- Badges: a product's badge should match its average star rating
  (4 or more: Positive, 2.5 or less: Negative, otherwise Mixed).

Each engine is judged with ITS OWN thresholds: VADER with the old ones (flag below -0.3,
badge +/-0.25), DistilBERT with the calibrated ones in app/ai/sentiment.py.

Nothing is written to the database: the new scores are computed in memory only.
"""

from collections import defaultdict

from app.ai import sentiment
from app.db import get_session
from app.repositories import review_repository

VADER_FLAG, VADER_BADGE = -0.3, 0.25    # the thresholds used with VADER before
SARCASTIC = "expected much better"


def expected_badge(average_rating: float) -> str:
    if average_rating >= 4:
        return "Positive"
    if average_rating <= 2.5:
        return "Negative"
    return "Mixed"


def badge_for(average_score: float, threshold: float) -> str:
    if average_score >= threshold:
        return "Positive"
    if average_score <= -threshold:
        return "Negative"
    return "Mixed"


def star_target(rating: int) -> int | None:
    """+1 / -1: the sign a review with this rating should have (None for 3 stars)."""
    return 1 if rating >= 4 else -1 if rating <= 2 else None


def evaluate(reviews, scores, flag_threshold, badge_threshold) -> dict:
    decided = [(r, s) for r, s in zip(reviews, scores) if star_target(r.rating)]
    agree = sum((s > 0) == (star_target(r.rating) > 0) for r, s in decided)
    complaints = sum(r.rating <= 2 for r in reviews)
    flagged = [r for r, s in zip(reviews, scores) if s < flag_threshold]
    by_product = defaultdict(list)
    for r, s in zip(reviews, scores):
        by_product[r.product_id].append((r.rating, s))
    badges_ok = sum(
        badge_for(sum(s for _, s in items) / len(items), badge_threshold)
        == expected_badge(sum(rating for rating, _ in items) / len(items))
        for items in by_product.values())
    return {
        "agree": agree, "decided": len(decided),
        "per_star": {star: sum(s for r, s in zip(reviews, scores) if r.rating == star)
                     / max(1, sum(r.rating == star for r in reviews)) for star in range(1, 6)},
        "flag_real": sum(r.rating <= 2 for r in flagged),
        "flag_false": sum(r.rating >= 3 for r in flagged),
        "flag_missed": complaints - sum(r.rating <= 2 for r in flagged),
        "complaints": complaints,
        "badges_ok": badges_ok, "products": len(by_product),
    }


def biggest_vader_mistakes(reviews, vader, model, count: int = 5):
    """Reviews where VADER is furthest from the star rating while DistilBERT has the
    right sign: (VADER error, review, vader score, model score), worst first. The
    sarcastic "...expected much better" review is always included (the talking point)."""
    cases = []
    for r, v, m in zip(reviews, vader, model):
        target = star_target(r.rating)
        if target is not None and (m > 0) == (target > 0):
            cases.append((abs(target - v), r, v, m))
    cases.sort(key=lambda case: -case[0])
    top = cases[:count]
    sarcastic = [c for c in cases if SARCASTIC in c[1].comment.lower() and c[2] > 0]
    if sarcastic and not any(SARCASTIC in c[1].comment.lower() and c[2] > 0 for c in top):
        top = top[:count - 1] + sarcastic[:1]
    return top


def main() -> None:
    with get_session() as session:
        reviews = review_repository.list_with_ratings(session)
    texts = [r.comment for r in reviews]
    print(f"Scoring {len(reviews)} reviews with VADER and with DistilBERT "
          "(loading the model takes a few seconds)...")
    vader = [sentiment.vader_score(t) for t in texts]
    try:
        model = sentiment.transformer_scores(texts)
    except Exception as error:
        raise SystemExit(f"Could not load the DistilBERT model: {error}") from None
    finally:
        sentiment.unload_model()

    results = {
        "VADER": evaluate(reviews, vader, VADER_FLAG, VADER_BADGE),
        "DistilBERT": evaluate(reviews, model, sentiment.FLAG_THRESHOLD,
                               sentiment.POSITIVE_THRESHOLD),
    }
    print()
    print(f"{'':34}{'VADER':>18}{'DistilBERT':>18}")
    rows = [
        ("Agrees with stars (1-2 vs 4-5)",
         lambda e: f"{e['agree']}/{e['decided']} {e['agree'] / e['decided']:.1%}"),
        *[(f"Average score, {star} star{'s' if star > 1 else ''}",
           lambda e, star=star: f"{e['per_star'][star]:+.2f}") for star in range(1, 6)],
        ("Complaints flagged (of 1-2 star)",
         lambda e: f"{e['flag_real']}/{e['complaints']}"),
        ("False alarms (3-5 stars flagged)", lambda e: str(e["flag_false"])),
        ("Badge matches star average",
         lambda e: f"{e['badges_ok']}/{e['products']}"),
    ]
    for name, show in rows:
        print(f"{name:34}{show(results['VADER']):>18}{show(results['DistilBERT']):>18}")
    print(f"\nThresholds: VADER flag < {VADER_FLAG}, badge +/-{VADER_BADGE}; DistilBERT "
          f"flag < {sentiment.FLAG_THRESHOLD}, badge +/-{sentiment.POSITIVE_THRESHOLD} "
          f"(temperature {sentiment.TEMPERATURE}).")

    print("\nThe 5 biggest cases where VADER got it wrong and DistilBERT got it right:")
    for number, (_error, review, v, m) in enumerate(
            biggest_vader_mistakes(reviews, vader, model), start=1):
        print(f"\n{number}. {review.rating} star{'s' if review.rating > 1 else ''}  "
              f"VADER {v:+.2f}  DistilBERT {m:+.2f}  (review #{review.id})")
        print(f"   \"{review.comment}\"")


if __name__ == "__main__":
    main()
