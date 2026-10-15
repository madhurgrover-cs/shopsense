"""Unit tests for app/ai/sentiment.py without the real model.

- Most tests use the fake model from conftest (fake_sentiment_model).
- The loading / temperature tests (marked real_sentiment_code) install a tiny fake
  "transformers" package, so the real loading code runs (labels, lock, failure
  handling) without downloading anything.
The real model is tested once, in test_ai_integration.py.
"""

import logging
import math
import sys
import threading
import types

import pytest
import torch

from app.ai import model_lock, sentiment


# ---------------------------------------------------------------------------
# score / score_many with the fake model
# ---------------------------------------------------------------------------

def test_score_uses_the_model(fake_sentiment_model):
    assert sentiment.score("Absolutely love it, excellent quality!") > 0.5
    assert sentiment.score("Terrible. Broke after two days, total waste.") < -0.5
    assert fake_sentiment_model == [["Absolutely love it, excellent quality!"],
                                    ["Terrible. Broke after two days, total waste."]]


@pytest.mark.parametrize("text", [None, "", "   "])
def test_no_text_means_no_score_and_no_model_load(text, fake_sentiment_model):
    assert sentiment.score(text) is None
    assert fake_sentiment_model == []  # nothing to score: the model isn't even loaded


def test_score_many_keeps_positions_and_loads_once(fake_sentiment_model):
    scores, engine = sentiment.score_many_with_engine(["Love it", None, "  ", "Awful"])
    assert scores == [0.9, None, None, -0.9] and engine == sentiment.TRANSFORMER
    assert fake_sentiment_model == [["Love it", "Awful"]]  # one call, texts trimmed


def test_falls_back_to_vader_when_model_fails(monkeypatch, caplog):
    def broken(texts):
        raise OSError("could not download model")
    monkeypatch.setattr(sentiment, "transformer_scores", broken)
    with caplog.at_level(logging.WARNING, logger="app.ai.sentiment"):
        scores, engine = sentiment.score_many_with_engine(["I love it, excellent!"])
    assert engine == sentiment.VADER
    assert scores == [sentiment.vader_score("I love it, excellent!")] and scores[0] > 0.5
    assert "using VADER" in caplog.text


def test_vader_misses_the_sarcastic_review():
    """The talking point: VADER sees the word "better" and scores a complaint positive."""
    assert sentiment.vader_score(
        "Disappointed with this conditioner. Customer support was slow and unhelpful. "
        "It looks quite different from the photos. I expected much better.") > 0


# ---------------------------------------------------------------------------
# Loading, temperature, unloading (fake transformers package)
# ---------------------------------------------------------------------------

class FakeTokenizer:
    def __call__(self, texts, **kwargs):
        return {"input_ids": torch.zeros((len(texts), 1), dtype=torch.long)}


class FakeModel:
    """Returns logits [negative, positive] = [0, margin] for every text."""
    margin = 5.0
    config = types.SimpleNamespace(label2id={"NEGATIVE": 0, "POSITIVE": 1})

    def eval(self):
        return self

    def __call__(self, input_ids):
        rows = input_ids.shape[0]
        return types.SimpleNamespace(logits=torch.tensor([[0.0, self.margin]] * rows))


@pytest.fixture
def fake_transformers(monkeypatch):
    """A fake "transformers" package; records how often the model was loaded."""
    loads = []

    def load_model(name):
        loads.append(name)
        return FakeModel()
    module = types.SimpleNamespace(
        AutoTokenizer=types.SimpleNamespace(from_pretrained=lambda name: FakeTokenizer()),
        AutoModelForSequenceClassification=types.SimpleNamespace(from_pretrained=load_model))
    monkeypatch.setitem(sys.modules, "transformers", module)
    monkeypatch.setattr(sentiment, "_model", None)
    monkeypatch.setattr(sentiment, "_model_failed", False)
    return loads


@pytest.mark.real_sentiment_code
def test_score_is_temperature_scaled_probability_gap(fake_transformers):
    # P(pos) - P(neg) of softmax(logits / T) equals tanh(margin / (2T)).
    expected = round(math.tanh(FakeModel.margin / (2 * sentiment.TEMPERATURE)), 4)
    assert sentiment.score("anything") == expected
    assert fake_transformers == [sentiment.MODEL_NAME]


@pytest.mark.real_sentiment_code
def test_model_is_unloaded_after_scoring(fake_transformers):
    sentiment.score("first")
    assert not sentiment.is_model_loaded()   # memory freed straight away
    sentiment.score_many(["a", "b", "c"])
    assert len(fake_transformers) == 2       # loaded once per scoring job, not per text


@pytest.mark.real_sentiment_code
def test_failed_load_is_not_retried(fake_transformers, monkeypatch):
    attempts = []

    def offline(name):
        attempts.append(name)
        raise OSError("no internet")
    monkeypatch.setattr(sys.modules["transformers"].AutoModelForSequenceClassification,
                        "from_pretrained", offline)
    assert sentiment.score_many_with_engine(["Love it"])[1] == sentiment.VADER
    assert sentiment.score_many_with_engine(["Love it"])[1] == sentiment.VADER
    assert len(attempts) == 1  # the second review didn't wait for another failed download


@pytest.mark.real_sentiment_code
def test_never_loads_while_another_model_is_loading(fake_transformers):
    """model_lock.LOADING is shared with the search model: while it is held (the search
    model is loading), the sentiment model waits."""
    finished = threading.Event()
    with model_lock.LOADING:
        worker = threading.Thread(target=lambda: (sentiment.score("x"), finished.set()))
        worker.start()
        assert not finished.wait(0.3)   # blocked while the other model loads
        assert fake_transformers == []
    worker.join(5)
    assert finished.is_set() and fake_transformers == [sentiment.MODEL_NAME]


# ---------------------------------------------------------------------------
# scripts/compare_sentiment.py (its maths, on hand-made reviews)
# ---------------------------------------------------------------------------

def test_compare_script_evaluation():
    from collections import namedtuple

    from scripts import compare_sentiment as compare
    R = namedtuple("R", "id product_id rating comment")
    reviews = [R(1, 10, 5, "Love it"), R(2, 10, 4, "Nice"), R(3, 20, 1, "Broke"),
               R(4, 20, 2, "Poor. I expected much better."), R(5, 30, 3, "Decent")]
    vader = [0.9, 0.8, -0.9, 0.36, 0.0]     # wrong sign on review 4
    model = [0.9, 0.9, -0.9, -0.88, -0.6]

    v = compare.evaluate(reviews, vader, compare.VADER_FLAG, compare.VADER_BADGE)
    m = compare.evaluate(reviews, model, -0.75, 0.35)
    assert (v["agree"], v["decided"], m["agree"]) == (3, 4, 4)  # 3 stars not counted
    assert (v["flag_real"], v["flag_missed"]) == (1, 1)
    assert (m["flag_real"], m["flag_false"], m["flag_missed"]) == (2, 0, 0)
    # 10: Positive and 20: Negative match their stars. 30 has one mixed 3-star review
    # scored -0.6, which is below -0.35, so its badge is Negative, not the Mixed its
    # stars suggest: a known limitation (mixed reviews lean negative with this model).
    assert m["badges_ok"] == 2

    worst = compare.biggest_vader_mistakes(reviews, vader, model, count=1)
    assert worst[0][1].id == 4  # VADER's furthest-off review, which the model gets right
