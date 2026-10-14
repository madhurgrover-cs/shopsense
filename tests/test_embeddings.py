"""Tests for the embedding model wrapper, embedding queries and the build script.

These are unit tests: the build-script tests use the fake embedder from conftest.
The real model is exercised in test_ai_integration.py."""

import math
import subprocess
import sys
import threading
import time

import pytest

from app.ai import embeddings
from app.models import ProductEmbedding
from app.models.catalog import EMBEDDING_DIM
from app.repositories import product_repository
from app.services import catalog_service
from scripts.build_embeddings import build_missing_embeddings


# ---------------------------------------------------------------------------
# Lazy loading (no real model needed)
# ---------------------------------------------------------------------------

def test_importing_the_app_does_not_load_torch():
    """Run in a FRESH Python process: this test process may already have torch loaded."""
    code = (
        "import sys\n"
        "import app.ai.embeddings, app.services.catalog_service, app.services.cart_service\n"
        "import app.services.order_service, app.services.auth_service\n"
        "print('torch' in sys.modules, 'sentence_transformers' in sys.modules)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            check=True)
    assert result.stdout.strip() == "False False"


class FakeModel:
    """Stands in for SentenceTransformer so loading logic can be tested instantly."""
    instances = 0

    def __init__(self, name, device, dim=EMBEDDING_DIM):
        FakeModel.instances += 1
        time.sleep(0.2)  # a slow load makes a double-load race likely if unprotected
        self.dim = dim

    def get_embedding_dimension(self):
        return self.dim


@pytest.fixture
def fake_model(monkeypatch):
    FakeModel.instances = 0
    monkeypatch.setattr(embeddings, "_model", None)  # restored after the test
    # String target: sentence_transformers is imported only when this fixture runs.
    monkeypatch.setattr("sentence_transformers.SentenceTransformer", FakeModel)
    return FakeModel


def test_model_is_loaded_once_even_from_many_threads(fake_model):
    assert not embeddings.is_model_loaded()
    results = []
    threads = [threading.Thread(target=lambda: results.append(embeddings.get_model()))
               for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert fake_model.instances == 1
    assert all(model is results[0] for model in results)
    assert embeddings.get_model() is results[0]  # later calls reuse it too
    assert embeddings.is_model_loaded()


def test_wrong_dimension_model_is_rejected(fake_model, monkeypatch):
    monkeypatch.setattr("sentence_transformers.SentenceTransformer",
                        lambda name, device: FakeModel(name, device, dim=768))
    with pytest.raises(RuntimeError, match="vector\\(384\\)"):
        embeddings.get_model()
    assert not embeddings.is_model_loaded()


def test_embed_empty_list_does_not_load_model(monkeypatch):
    def must_not_load():
        raise AssertionError("model loaded for an empty list")
    monkeypatch.setattr(embeddings, "get_model", must_not_load)
    assert embeddings.embed_texts([]) == []


def test_product_text():
    assert embeddings.product_text("Test Kettle", "Boils water fast.") == \
        "Test Kettle. Boils water fast."


# ---------------------------------------------------------------------------
# Repository functions
# ---------------------------------------------------------------------------

def add_embedding(db_session, product_id, value=0.1):
    db_session.add(ProductEmbedding(product_id=product_id, embedding=[value] * EMBEDDING_DIM))
    db_session.commit()


def test_list_missing_embeddings(factory, db_session):
    missing = factory.product()
    has_one = factory.product()
    inactive = factory.product(active=False)
    add_embedding(db_session, has_one)

    rows = product_repository.list_missing_embeddings(
        db_session, [missing, has_one, inactive])
    assert [r.id for r in rows] == [missing]          # skips embedded and inactive
    assert rows[0].description == "A product created by a test."

    more = [factory.product() for _ in range(3)]
    assert len(product_repository.list_missing_embeddings(db_session, more, limit=2)) == 2
    assert product_repository.list_missing_embeddings(db_session, more, lock=True)


def test_save_embeddings_inserts_then_replaces(factory, db_session):
    pid = factory.product()
    product_repository.save_embeddings(db_session, {pid: [0.1] * EMBEDDING_DIM})
    product_repository.save_embeddings(db_session, {pid: [0.2] * EMBEDDING_DIM})  # no error
    db_session.expire_all()
    stored = db_session.get(ProductEmbedding, pid).embedding
    assert math.isclose(float(stored[0]), 0.2, rel_tol=1e-6)
    product_repository.save_embeddings(db_session, {})  # empty: no-op


def test_count_embeddings(factory, db_session):
    done_before, total_before = product_repository.count_embeddings(db_session)
    pid = factory.product()
    factory.product()
    add_embedding(db_session, pid)
    assert product_repository.count_embeddings(db_session) == (done_before + 1, total_before + 2)


# ---------------------------------------------------------------------------
# Build script
# ---------------------------------------------------------------------------

def test_build_missing_embeddings_is_rerunnable(factory, db_session, admin, fake_embedder):
    ids = [factory.product(name=f"Test Lamp {i}") for i in range(3)]
    inactive = factory.product(active=False)

    assert build_missing_embeddings(batch_size=2, product_ids=[*ids, inactive]) == 3
    db_session.expire_all()
    for pid in ids:
        assert len(db_session.get(ProductEmbedding, pid).embedding) == EMBEDDING_DIM
    assert db_session.get(ProductEmbedding, inactive) is None

    # Second run: nothing to do.
    assert build_missing_embeddings(product_ids=ids) == 0

    # Editing the text clears the embedding, so only that product is re-embedded.
    catalog_service.update_product(admin, ids[0], description="Now a reading lamp.")
    assert build_missing_embeddings(product_ids=ids) == 1


def test_stored_vector_matches_product_text(factory, db_session, fake_embedder):
    pid = factory.product(name="Test Yoga Mat")
    build_missing_embeddings(product_ids=[pid])
    db_session.expire_all()
    stored = [float(x) for x in db_session.get(ProductEmbedding, pid).embedding]
    expected = fake_embedder(
        embeddings.product_text("Test Yoga Mat", "A product created by a test."))
    assert all(math.isclose(a, b, abs_tol=1e-6) for a, b in zip(stored, expected))


def test_build_does_not_load_model_when_nothing_is_missing(factory, db_session, monkeypatch):
    pid = factory.product()
    add_embedding(db_session, pid)

    def must_not_load():
        raise AssertionError("model loaded with nothing to embed")
    monkeypatch.setattr(embeddings, "get_model", must_not_load)
    assert build_missing_embeddings(product_ids=[pid]) == 0
