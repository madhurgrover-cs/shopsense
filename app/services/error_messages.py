"""Turn any exception into a short, friendly message for a popup.

Lives in the services layer (not the GUI) because recognising database errors means
looking at SQLAlchemy exception types, and the GUI must never import SQLAlchemy.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.exc import DBAPIError, OperationalError

from app.exceptions import (
    AccountLockedError, AskDataError, EmptyCartError, InvalidCouponError,
    InvalidCredentialsError, NotFoundError, OutOfStockError, PermissionDeniedError,
    ShopSenseError, SqlRejectedError, ValidationError,
)

log = logging.getLogger(__name__)

_TITLES: list[tuple[type[ShopSenseError], str]] = [
    (OutOfStockError, "Out of stock"),
    (InvalidCouponError, "Coupon not accepted"),
    (EmptyCartError, "Cart is empty"),
    (InvalidCredentialsError, "Login failed"),
    (AccountLockedError, "Account locked"),
    (PermissionDeniedError, "Not allowed"),
    (NotFoundError, "Not found"),
    (ValidationError, "Please check your input"),
    (SqlRejectedError, "Query blocked"),  # before AskDataError: it's a subclass
    (AskDataError, "Couldn't answer"),
]


@dataclass(frozen=True)
class FriendlyError:
    title: str
    message: str
    expected: bool  # True for business rules (show as-is); False for real failures


def friendly_error(error: BaseException) -> FriendlyError:
    if isinstance(error, ShopSenseError):
        # Our own exceptions already carry a user-friendly message.
        title = next((t for cls, t in _TITLES if isinstance(error, cls)), "Couldn't do that")
        return FriendlyError(title, str(error), expected=True)

    # Anything else is unexpected: log the full details for developers, but never show
    # a stack trace or SQL to the user.
    log.error("Unexpected error", exc_info=error)
    if isinstance(error, OperationalError) or (
            isinstance(error, DBAPIError) and error.connection_invalidated):
        return FriendlyError(
            "Connection problem",
            "Couldn't reach the database. Check your internet connection and try again.",
            expected=False,
        )
    return FriendlyError(
        "Something went wrong",
        "An unexpected error occurred. Please try again. "
        "If it keeps happening, restart ShopSense.",
        expected=False,
    )
