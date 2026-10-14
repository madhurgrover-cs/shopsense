"""The logged-in user, as seen by the GUI.

login() returns a UserSession. The GUI keeps it and passes it back to any service call
that needs to know who is acting (e.g. admin-only actions). It is a plain, frozen
dataclass rather than an ORM object, so the GUI never holds a SQLAlchemy object or a
database session (architecture rule), and it can't accidentally change its own role.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class UserSession:
    user_id: int
    name: str
    email: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"
