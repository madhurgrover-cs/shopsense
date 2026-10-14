"""Review sentiment with VADER (a rule-based model: a word list with sentiment weights
plus rules for negation, "but", capitals, exclamation marks...).

VADER's "compound" score runs from -1 (very negative) to +1 (very positive). It is
tiny and fast (loads in ~0.02 s), unlike the embedding model, but we still create the
analyzer once and reuse it.
"""

import threading

# A single review is flagged for the admin below this score (CLAUDE.md).
FLAG_THRESHOLD = -0.3

# Product badge thresholds on the AVERAGE score of its reviews. VADER's usual cut-off
# for one sentence is +/-0.05, but for an average across many reviews that is too
# sensitive: one glowing review among neutral ones would already make it "Positive".
# +/-0.25 needs a clear lean either way; anything in between is "Mixed".
POSITIVE_THRESHOLD = 0.25
NEGATIVE_THRESHOLD = -0.25

POSITIVE, MIXED, NEGATIVE = "Positive", "Mixed", "Negative"

_analyzer = None
_lock = threading.Lock()


def _get_analyzer():
    global _analyzer
    if _analyzer is None:
        with _lock:
            if _analyzer is None:
                from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
                _analyzer = SentimentIntensityAnalyzer()
    return _analyzer


def score(text: str | None) -> float | None:
    """Compound sentiment score in [-1, 1], or None when there is no text to judge
    (a star rating without a comment says nothing about wording)."""
    if text is None or not text.strip():
        return None
    return round(_get_analyzer().polarity_scores(text)["compound"], 4)


def badge(average_score: float | None) -> str | None:
    """Positive / Mixed / Negative for a product's average review score."""
    if average_score is None:
        return None  # no scored reviews yet: show no badge
    if average_score >= POSITIVE_THRESHOLD:
        return POSITIVE
    if average_score <= NEGATIVE_THRESHOLD:
        return NEGATIVE
    return MIXED


def is_flagged(review_score: float | None) -> bool:
    return review_score is not None and review_score < FLAG_THRESHOLD
