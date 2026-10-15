"""Review sentiment: a transformer model, with VADER as the fallback.

Model: distilbert-base-uncased-finetuned-sst-2-english, a small BERT ("DistilBERT",
66 M parameters, ~270 MB) fine-tuned on movie-review sentences labelled positive or
negative (SST-2). Unlike VADER, which adds up word weights from a fixed list, it reads
the whole sentence in context. Example: "Poor quality. ... I expected much better."
VADER scores it POSITIVE (+0.36) because "better" is a positive word in its list; the
model scores it -0.88. Limitation: real sarcasm still fools it ("Great, it broke on
day two. Just what I needed." scores +0.85); that needs a model trained on sarcasm.

Score = P(positive) - P(negative), from -1 (surely negative) to +1 (surely positive),
the same range as VADER's compound score, so badges and flagging work unchanged.

Calibration (measured on the 300 seed reviews, see scripts/compare_sentiment.py):
- SST-2 has only two labels and the raw model is extremely over-confident: 293 of 300
  reviews scored beyond +/-0.9, and "Decent, nothing special. Mixed feelings" (3 stars)
  scored -0.99, the same as "Broke in a week" (1 star). No threshold can separate them.
- But the model's raw outputs (logits) DO differ: the gap between the positive and the
  negative logit is about -8.5 for 1-star reviews and about -5 for mixed 3-star ones.
  Softmax squashes both to ~1.0. Dividing the logits by a TEMPERATURE before softmax
  ("temperature scaling", a standard way to calibrate over-confident classifiers) keeps
  that difference visible: score = tanh(gap / (2 * T)). With T = 3: 1 star -0.89 on
  average, 3 stars -0.60, 4-5 stars +0.87 to +0.90.
- Thresholds were then re-chosen on that scale (below). Compared with VADER at -0.3,
  flagging catches 61 instead of 53 of the 63 one- and two-star reviews, with 11 false
  alarms instead of 18; badges match the products' star average for 117 of 133
  products instead of 105.

Memory (4 GB laptop):
- Loaded lazily, only to score: when a review is saved (in the GUI's background
  thread) and in scripts.backfill_sentiment. Never at app startup or login.
- Unloaded again right after scoring (~270 MB freed): reviews are written rarely, so
  keeping it in memory all session would waste RAM for nothing.
- Loaded under model_lock.LOADING, so it is never loaded at the same moment as the
  search embedding model.

Fallback: if the model can't be loaded (e.g. no internet on the very first run, when it
must be downloaded), VADER is used instead, and is kept for the rest of the session
rather than retrying (and waiting for a network timeout) on every review.
"""

import gc
import logging
import os
import threading

from app.ai import model_lock

log = logging.getLogger(__name__)

MODEL_NAME = "distilbert/distilbert-base-uncased-finetuned-sst-2-english"
TEMPERATURE = 3.0   # calibration, see above
BATCH_SIZE = 16     # reviews per forward pass; small batches keep peak memory low
MAX_TOKENS = 256    # longer reviews are cut (the model's limit is 512)

TRANSFORMER, VADER = "distilbert", "vader"

# Thresholds, on the calibrated scale (see above).
# A single review is flagged for the admin below this score. -0.75 sits between mixed
# 3-star reviews (around -0.6) and real complaints (around -0.89). It errs towards
# flagging: at -0.8 six real complaints were missed, at -0.75 two.
FLAG_THRESHOLD = -0.75
# Product badge thresholds on the AVERAGE score of its reviews (was +/-0.25 for VADER).
# Scores now cluster near +/-0.9, so an average of 0.25 can be just "two positive
# reviews, one mixed"; +/-0.35 needs a clearer lean and matched the star ratings best
# (results were the same anywhere from 0.35 to 0.4).
# Note: if the model can't load, VADER scores are stored on these same thresholds.
# VADER is milder (it rarely goes below -0.75), so then fewer reviews get flagged;
# run "python -m scripts.backfill_sentiment --all" once the model works again.
POSITIVE_THRESHOLD = 0.35
NEGATIVE_THRESHOLD = -0.35

POSITIVE, MIXED, NEGATIVE = "Positive", "Mixed", "Negative"

_model = None             # (tokenizer, model, positive index, negative index) while loaded
_model_failed = False     # True after a failed load: use VADER for the rest of the session
_vader = None
_scoring = threading.Lock()  # one scoring job at a time (it loads and unloads the model)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score(text: str | None) -> float | None:
    """Sentiment of one review in [-1, 1], or None when there is no text to judge
    (a star rating without a comment says nothing about wording)."""
    return score_many([text])[0]


def score_many(texts: list[str | None]) -> list[float | None]:
    """Score several reviews with ONE model load (used by the backfill)."""
    return score_many_with_engine(texts)[0]


def score_many_with_engine(texts: list[str | None]) -> tuple[list[float | None], str | None]:
    """(scores, engine used: TRANSFORMER or VADER; None if there was nothing to score)."""
    todo = [(i, text.strip()) for i, text in enumerate(texts) if text and text.strip()]
    scores: list[float | None] = [None] * len(texts)
    if not todo:
        return scores, None
    with _scoring:
        try:
            values, engine = transformer_scores([t for _, t in todo]), TRANSFORMER
        except Exception:  # model missing or broken: degrade, don't lose the review
            log.warning("Sentiment model unavailable; using VADER.", exc_info=True)
            values, engine = [vader_score(t) for _, t in todo], VADER
        finally:
            unload_model()
    for (index, _text), value in zip(todo, values):
        scores[index] = value
    return scores, engine


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


# ---------------------------------------------------------------------------
# The two engines
# ---------------------------------------------------------------------------

def transformer_scores(texts: list[str]) -> list[float]:
    """P(positive) - P(negative) for each text, using DistilBERT (loads it if needed),
    with the logits divided by TEMPERATURE before softmax (calibration, see above).
    Raises if the model can't be loaded. Callers outside this module should use
    score() / score_many(), which add the fallback and the unloading."""
    import torch

    tokenizer, model, positive, negative = _get_model()
    results = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = tokenizer(texts[start:start + BATCH_SIZE], padding=True, truncation=True,
                          max_length=MAX_TOKENS, return_tensors="pt")
        with torch.inference_mode():  # no gradient bookkeeping: faster, less memory
            probabilities = (model(**batch).logits / TEMPERATURE).softmax(dim=-1)
        results += [round(float(p[positive] - p[negative]), 4) for p in probabilities]
    return results


def vader_score(text: str) -> float:
    """VADER's compound score in [-1, 1] (word-list based, tiny and instant)."""
    global _vader
    if _vader is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _vader = SentimentIntensityAnalyzer()
    return round(_vader.polarity_scores(text)["compound"], 4)


def is_model_loaded() -> bool:
    return _model is not None


def _get_model():
    global _model, _model_failed
    if _model is not None:
        return _model
    if _model_failed:
        raise RuntimeError("The sentiment model failed to load earlier in this session.")
    with model_lock.LOADING:  # never at the same moment as another big model
        try:
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
            model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
            model.eval()  # inference mode: no dropout
            labels = {name.upper(): index for name, index in model.config.label2id.items()}
            _model = (tokenizer, model, labels["POSITIVE"], labels["NEGATIVE"])
        except Exception:
            _model_failed = True
            raise
    return _model


def unload_model() -> None:
    """Drop the model so its ~270 MB can be freed straight away."""
    global _model
    if _model is not None:
        _model = None
        gc.collect()
