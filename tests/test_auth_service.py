"""Tests for registration, login, lockout and role checks."""

from datetime import timedelta

import bcrypt
import pytest

from app.exceptions import (
    AccountLockedError, EmailTakenError, InvalidCredentialsError, PermissionDeniedError,
    ValidationError,
)
from app.models import User
from app.repositories import user_repository
from app.services import auth_service
from app.services.auth_service import (
    LOCKOUT_DURATION, MAX_FAILED_LOGINS, login, register, require_admin, require_login,
)
from app.services.user_session import UserSession

PASSWORD = "correct-horse"


@pytest.fixture
def make_user(db_session):
    """Create a user directly in the test transaction and return its id."""
    def _make(email="asha@example.com", password=PASSWORD, role="customer", name="Asha Rao"):
        user = user_repository.create(
            db_session, name, email, auth_service.hash_password(password), role=role
        )
        db_session.commit()
        return user.id
    return _make


def reload(db_session, user_id: int) -> User:
    """Read the user fresh from the database (not from the session's cache)."""
    return db_session.get(User, user_id, populate_existing=True)


# ---------------------------------------------------------------------------
# Helpers: hashing, email normalisation, validation
# ---------------------------------------------------------------------------

def test_hash_password_is_salted_bcrypt():
    h1 = auth_service.hash_password(PASSWORD)
    h2 = auth_service.hash_password(PASSWORD)
    assert h1 != h2                      # different random salt each time
    assert h1.startswith("$2b$")         # bcrypt format
    assert PASSWORD not in h1


def test_verify_password():
    h = auth_service.hash_password(PASSWORD)
    assert auth_service.verify_password(PASSWORD, h)
    assert not auth_service.verify_password("wrong-password", h)
    assert not auth_service.verify_password("x" * 73, h)  # too long: False, not a crash


def test_normalise_email():
    assert auth_service.normalise_email("  Asha.Rao@Example.COM ") == "asha.rao@example.com"


def test_validate_registration_accepts_valid_input():
    auth_service.validate_registration("Asha", "asha@example.com", "12345678")  # no error


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

def test_register_creates_customer(db_session):
    session = register("  Asha Rao ", "Asha@Example.com", PASSWORD)

    assert isinstance(session, UserSession)
    assert session.name == "Asha Rao"
    assert session.email == "asha@example.com"   # stored lower-case
    assert session.role == "customer"

    user = reload(db_session, session.user_id)
    assert user.password_hash != PASSWORD
    assert bcrypt.checkpw(PASSWORD.encode(), user.password_hash.encode())
    assert user.failed_logins == 0 and user.locked_until is None


def test_register_duplicate_email_is_case_insensitive(db_session):
    register("Asha", "asha@example.com", PASSWORD)
    with pytest.raises(EmailTakenError):
        register("Someone Else", "ASHA@example.com", "another-password")


def test_register_duplicate_caught_by_database_constraint(db_session, monkeypatch):
    """Simulate two registrations racing: the friendly pre-check sees nothing, so the
    UNIQUE constraint must still stop the duplicate."""
    register("Asha", "asha@example.com", PASSWORD)
    monkeypatch.setattr(user_repository, "get_by_email", lambda *args, **kwargs: None)
    with pytest.raises(EmailTakenError):
        register("Asha Again", "asha@example.com", PASSWORD)


@pytest.mark.parametrize("email", [
    "", "plainaddress", "no-at-sign.com", "missing@tld", "two@@example.com",
    "spaces in@example.com", "@example.com", "asha@",
])
def test_register_rejects_invalid_email(db_session, email):
    with pytest.raises(ValidationError, match="valid email"):
        register("Asha", email, PASSWORD)


def test_register_password_length_rules(db_session):
    with pytest.raises(ValidationError, match="at least 8"):
        register("Asha", "asha@example.com", "1234567")          # 7 chars
    with pytest.raises(ValidationError, match="too long"):
        register("Asha", "asha@example.com", "a" * 73)           # over bcrypt's 72 bytes
    assert register("Asha", "asha@example.com", "12345678").user_id  # exactly 8 is fine


def test_register_requires_name(db_session):
    with pytest.raises(ValidationError, match="Name"):
        register("   ", "asha@example.com", PASSWORD)


def test_failed_register_leaves_no_user(db_session):
    with pytest.raises(ValidationError):
        register("Asha", "asha@example.com", "short")
    assert user_repository.get_by_email(db_session, "asha@example.com") is None


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------

def test_login_success(db_session, make_user, clock):
    user_id = make_user(role="admin")
    session = login("asha@example.com", PASSWORD)
    assert session == UserSession(user_id, "Asha Rao", "asha@example.com", "admin")


def test_login_email_is_case_insensitive(db_session, make_user, clock):
    make_user()
    assert login("  ASHA@example.com ", PASSWORD).email == "asha@example.com"


def test_wrong_password_and_unknown_email_give_identical_errors(db_session, make_user, clock):
    make_user()
    with pytest.raises(InvalidCredentialsError) as wrong_password:
        login("asha@example.com", "wrong-password")
    with pytest.raises(InvalidCredentialsError) as unknown_email:
        login("nobody@example.com", PASSWORD)
    assert str(wrong_password.value) == str(unknown_email.value) == "Invalid email or password."


def test_wrong_password_increments_counter(db_session, make_user, clock):
    user_id = make_user()
    with pytest.raises(InvalidCredentialsError):
        login("asha@example.com", "wrong-password")
    assert reload(db_session, user_id).failed_logins == 1


def test_successful_login_resets_counter(db_session, make_user, clock):
    user_id = make_user()
    for _ in range(MAX_FAILED_LOGINS - 1):
        with pytest.raises(InvalidCredentialsError):
            login("asha@example.com", "wrong-password")
    assert reload(db_session, user_id).failed_logins == 4

    login("asha@example.com", PASSWORD)
    assert reload(db_session, user_id).failed_logins == 0


def test_too_long_password_at_login_is_just_invalid(db_session, make_user, clock):
    make_user()
    with pytest.raises(InvalidCredentialsError):
        login("asha@example.com", "x" * 100)


# ---------------------------------------------------------------------------
# Lockout
# ---------------------------------------------------------------------------

def fail_login(times: int) -> None:
    for _ in range(times):
        with pytest.raises((InvalidCredentialsError, AccountLockedError)):
            login("asha@example.com", "wrong-password")


def test_fifth_failure_locks_account_for_15_minutes(db_session, make_user, clock):
    user_id = make_user()
    fail_login(MAX_FAILED_LOGINS - 1)
    assert reload(db_session, user_id).locked_until is None   # 4 failures: not locked yet

    with pytest.raises(AccountLockedError) as error:
        login("asha@example.com", "wrong-password")            # 5th failure
    assert error.value.locked_until == clock.now + LOCKOUT_DURATION
    assert reload(db_session, user_id).locked_until == clock.now + timedelta(minutes=15)


def test_locked_account_rejects_correct_password(db_session, make_user, clock):
    make_user()
    fail_login(MAX_FAILED_LOGINS)
    clock.advance(minutes=5)
    with pytest.raises(AccountLockedError):
        login("asha@example.com", PASSWORD)


def test_attempts_while_locked_do_not_extend_lock(db_session, make_user, clock):
    user_id = make_user()
    fail_login(MAX_FAILED_LOGINS)
    locked_until = reload(db_session, user_id).locked_until

    clock.advance(minutes=10)
    fail_login(3)
    user = reload(db_session, user_id)
    assert user.locked_until == locked_until
    assert user.failed_logins == 0


def test_account_unlocks_after_15_minutes(db_session, make_user, clock):
    user_id = make_user()
    fail_login(MAX_FAILED_LOGINS)

    clock.advance(minutes=14, seconds=59)
    with pytest.raises(AccountLockedError):         # one second early: still locked
        login("asha@example.com", PASSWORD)

    clock.advance(seconds=1)                        # exactly 15 minutes: unlocked
    session = login("asha@example.com", PASSWORD)
    assert session.user_id == user_id
    user = reload(db_session, user_id)
    assert user.locked_until is None and user.failed_logins == 0


def test_after_lock_expires_user_gets_fresh_attempts(db_session, make_user, clock):
    make_user()
    fail_login(MAX_FAILED_LOGINS)
    clock.advance(minutes=16)

    # One typo after the lock expires must NOT immediately re-lock the account.
    with pytest.raises(InvalidCredentialsError):
        login("asha@example.com", "wrong-password")
    assert login("asha@example.com", PASSWORD).email == "asha@example.com"


def test_lockout_is_per_account(db_session, make_user, clock):
    make_user()
    make_user(email="ravi@example.com", name="Ravi")
    fail_login(MAX_FAILED_LOGINS)
    assert login("ravi@example.com", PASSWORD).name == "Ravi"


# ---------------------------------------------------------------------------
# require_admin
# ---------------------------------------------------------------------------

def test_require_admin_allows_admin():
    require_admin(UserSession(1, "Admin", "admin@example.com", "admin"))  # no error


@pytest.mark.parametrize("user", [
    UserSession(2, "Customer", "c@example.com", "customer"),
    None,  # not logged in
])
def test_require_admin_rejects_others(user):
    with pytest.raises(PermissionDeniedError):
        require_admin(user)


# ---------------------------------------------------------------------------
# require_login
# ---------------------------------------------------------------------------

def test_require_login():
    require_login(UserSession(2, "Customer", "c@example.com", "customer"))  # no error
    with pytest.raises(PermissionDeniedError, match="log in"):
        require_login(None)
