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
