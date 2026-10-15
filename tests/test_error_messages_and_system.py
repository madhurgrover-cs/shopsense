"""Tests for friendly error messages and the system service."""

import pytest
from sqlalchemy.exc import OperationalError

from app.ai import embeddings
from app.exceptions import (
    AccountLockedError, EmptyCartError, InvalidCouponError, InvalidCredentialsError,
    NotFoundError, OutOfStockError, PermissionDeniedError, ValidationError,
)
from app.services import system_service
from app.services.error_messages import friendly_error


@pytest.mark.parametrize("error, title", [
    (OutOfStockError("Test Phone", 2), "Out of stock"),
    (InvalidCouponError("This coupon has expired."), "Coupon not accepted"),
    (EmptyCartError(), "Cart is empty"),
    (InvalidCredentialsError(), "Login failed"),
    (AccountLockedError(None), "Account locked"),
    (PermissionDeniedError(), "Not allowed"),
    (NotFoundError("Order not found."), "Not found"),
    (ValidationError("Price must be greater than zero."), "Please check your input"),
])
def test_business_errors_keep_their_message(error, title):
    info = friendly_error(error)
    assert (info.title, info.message, info.expected) == (title, str(error), True)


def test_database_connection_error_is_explained_without_details():
    error = OperationalError("SELECT secret FROM users", {}, Exception("timeout to host xyz"))
    info = friendly_error(error)
    assert info.title == "Connection problem" and not info.expected
    assert "internet" in info.message
    assert "SELECT" not in info.message and "xyz" not in info.message  # nothing leaked


def test_unexpected_error_gets_generic_message():
    info = friendly_error(KeyError("internal detail"))
    assert info.title == "Something went wrong" and not info.expected
    assert "internal detail" not in info.message


def test_check_connection(db_session):
    system_service.check_connection()  # no error


def test_is_search_model_loaded(monkeypatch):
    monkeypatch.setattr(embeddings, "_model", None)
    assert system_service.is_search_model_loaded() is False
    monkeypatch.setattr(embeddings, "_model", object())
    assert system_service.is_search_model_loaded() is True


def test_preload_search_model(monkeypatch):
    loads = []
    monkeypatch.setattr(embeddings, "get_model", lambda: loads.append(1) or "model")
    assert system_service.preload_search_model() is True
    assert loads == [1]


def test_preload_search_model_failure_is_reported_not_raised(monkeypatch):
    def offline():
        raise OSError("could not download model")
    monkeypatch.setattr(embeddings, "get_model", offline)
    assert system_service.preload_search_model() is False
