"""Registration, login with account lockout, and role checks."""

import re
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy.exc import IntegrityError

from app.db import get_session
from app.exceptions import (
    AccountLockedError, EmailTakenError, InvalidCredentialsError, PermissionDeniedError,
    ShopSenseError, ValidationError,
)
from app.repositories import user_repository
from app.services.user_session import UserSession

MAX_FAILED_LOGINS = 5
LOCKOUT_DURATION = timedelta(minutes=15)
MIN_PASSWORD_LENGTH = 8
# bcrypt only uses the first 72 bytes of a password (and bcrypt 5 raises an error
# beyond that), so we reject longer passwords instead of silently ignoring the rest.
MAX_PASSWORD_BYTES = 72
# Cost factor: each +1 doubles the time to hash. 12 takes ~0.25 s, slow enough to make
# brute-forcing stolen hashes expensive. Tests lower it to keep the suite fast.
BCRYPT_ROUNDS = 12

# Simple, readable check: something@something.tld, no spaces. Full RFC 5322
# validation is far more complex and not worth it here.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def utcnow() -> datetime:
    """Current time. A separate function so tests can replace it with a fake clock."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        return False  # could never have been registered, so it can't be right
    return bcrypt.checkpw(password.encode(), password_hash.encode())


_dummy_hash: str | None = None


def _waste_time_like_bcrypt(password: str) -> None:
    """Run a bcrypt check against a dummy hash when the email doesn't exist.

    Without this, "unknown email" would answer instantly while "wrong password" takes
    ~0.25 s (bcrypt), and an attacker could measure the difference to find out which
    emails are registered, defeating the generic error message.
    """
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("dummy-password")
    verify_password(password, _dummy_hash)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def normalise_email(email: str) -> str:
    """Emails are stored lower-case so "Asha@Example.com" and "asha@example.com" are
    the same account."""
    return email.strip().lower()


def validate_registration(name: str, email: str, password: str) -> None:
    if not name.strip():
        raise ValidationError("Name is required.")
    if not EMAIL_PATTERN.match(email):
        raise ValidationError("Please enter a valid email address.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        raise ValidationError("Password is too long (maximum 72 bytes).")


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def register(name: str, email: str, password: str) -> UserSession:
    """Create a customer account and return it as a logged-in session.

    Self-registration always creates a *customer*; admins are never created this way.
    """
    email = normalise_email(email)
    validate_registration(name, email, password)
    try:
        with get_session() as session:
            # Check first for a friendly error in the normal case...
            if user_repository.get_by_email(session, email) is not None:
                raise EmailTakenError()
            user = user_repository.create(
                session, name.strip(), email, hash_password(password), role="customer"
            )
            return _to_user_session(user)
    except IntegrityError as error:
        # ...but two people registering the same email at the same moment could both
        # pass the check. The UNIQUE constraint in the database is the real guarantee.
        raise EmailTakenError() from error


def login(email: str, password: str) -> UserSession:
    """Check credentials and return the user's session.

    Raises InvalidCredentialsError (same message for unknown email and wrong password)
    or AccountLockedError.
    """
    email = normalise_email(email)
    error: ShopSenseError | None = None
    result: UserSession | None = None

    # The failed-login counter must be SAVED even when login fails. get_session() rolls
    # back if an exception escapes the block, so inside the block we only decide the
    # outcome; the error is raised after the block has committed.
    with get_session() as session:
        user = user_repository.get_by_email(session, email, for_update=True)
        now = utcnow()

        if user is None:
            _waste_time_like_bcrypt(password)
            error = InvalidCredentialsError()

        elif user.locked_until is not None and user.locked_until > now:
            # Locked: reject even the correct password, and don't count this attempt.
            # Note: this does reveal the email exists. That is the usual trade-off:
            # telling a real user why they can't log in matters more.
            error = AccountLockedError(user.locked_until)

        elif verify_password(password, user.password_hash):
            user.failed_logins = 0
            user.locked_until = None
            result = _to_user_session(user)

        else:
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.locked_until = now + LOCKOUT_DURATION
                # Start counting from zero again, so after the lock expires the user
                # gets a fresh 5 attempts instead of being re-locked on the first typo.
                user.failed_logins = 0
                error = AccountLockedError(user.locked_until)
            else:
                error = InvalidCredentialsError()

    if error is not None:
        raise error
    assert result is not None
    return result


def require_login(user: UserSession | None) -> None:
    """Call at the start of every service function that needs a logged-in user."""
    if user is None:
        raise PermissionDeniedError("Please log in first.")


def require_admin(user: UserSession | None) -> None:
    """Call at the start of every admin-only service function."""
    if user is None or not user.is_admin:
        raise PermissionDeniedError("Only administrators can do this.")


def _to_user_session(user) -> UserSession:
    return UserSession(user_id=user.id, name=user.name, email=user.email, role=user.role)
