"""Custom exceptions raised by services.

The GUI catches these and shows str(error) to the user, so every message is written
to be safe and readable for an end user.
"""

from datetime import datetime


class ShopSenseError(Exception):
    """Base class: catching this catches every expected business error."""


class ValidationError(ShopSenseError):
    """Input failed a business rule (bad email format, short password, ...)."""


class InvalidCredentialsError(ShopSenseError):
    """Wrong email or password. The message is deliberately the same for both cases."""

    def __init__(self) -> None:
        super().__init__("Invalid email or password.")


class AccountLockedError(ShopSenseError):
    """Too many failed logins; the account is temporarily locked."""

    def __init__(self, locked_until: datetime) -> None:
        self.locked_until = locked_until
        super().__init__(
            "Account locked after too many failed login attempts. "
            "Please try again in a few minutes."
        )


class EmailTakenError(ShopSenseError):
    def __init__(self) -> None:
        super().__init__("An account with this email already exists.")


class PermissionDeniedError(ShopSenseError):
    def __init__(self, message: str = "You do not have permission to do this.") -> None:
        super().__init__(message)


class NotFoundError(ShopSenseError):
    """A product, order or coupon doesn't exist (or isn't visible to this user)."""


class OutOfStockError(ShopSenseError):
    """Not enough stock for the requested quantity."""

    def __init__(self, product_name: str, available: int) -> None:
        self.product_name = product_name
        self.available = available
        if available == 0:
            message = f"'{product_name}' is out of stock."
        else:
            message = f"Only {available} left of '{product_name}'."
        super().__init__(message)


class InvalidCouponError(ShopSenseError):
    """Coupon code doesn't exist, is disabled, or has expired."""


class EmptyCartError(ShopSenseError):
    def __init__(self) -> None:
        super().__init__("Your cart is empty.")


class AskDataError(ShopSenseError):
    """"Ask your data" couldn't answer: no API key, offline, the AI failed, or the query
    failed. `sql` is the query involved, if one was generated, so the screen can show it."""

    def __init__(self, message: str, sql: str | None = None) -> None:
        self.sql = sql
        super().__init__(message)


class SqlRejectedError(AskDataError):
    """The AI's SQL failed a safety check (see app/ai/sql_guard.py) and was NOT run."""
