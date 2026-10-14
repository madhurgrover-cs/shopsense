"""Tests for the user repository and the UserSession object."""

import dataclasses

import pytest

from app.repositories import user_repository
from app.services.user_session import UserSession


def test_create_and_get_user(db_session):
    user = user_repository.create(db_session, "Meera", "meera@example.com", "hash")
    assert user.id is not None                 # flush assigned an id
    assert user.role == "customer"             # default
    assert user_repository.get_by_id(db_session, user.id) is user
    assert user_repository.get_by_email(db_session, "meera@example.com").id == user.id
    assert user_repository.get_by_email(db_session, "meera@example.com", for_update=True).id == user.id


def test_get_missing_user_returns_none(db_session):
    assert user_repository.get_by_id(db_session, -1) is None
    assert user_repository.get_by_email(db_session, "ghost@example.com") is None


def test_user_session_is_admin():
    assert UserSession(1, "A", "a@example.com", "admin").is_admin
    assert not UserSession(2, "B", "b@example.com", "customer").is_admin


def test_user_session_is_read_only():
    session = UserSession(2, "B", "b@example.com", "customer")
    with pytest.raises(dataclasses.FrozenInstanceError):
        session.role = "admin"  # the GUI can't promote itself
