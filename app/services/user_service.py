"""Admin view of customer accounts (read-only)."""

from decimal import Decimal

from app.db import get_session
from app.repositories import user_repository
from app.services import auth_service
from app.services.auth_service import require_admin
from app.services.dto import CustomerSummary
from app.services.user_session import UserSession


def list_customers(admin: UserSession) -> list[CustomerSummary]:
    """Every customer with their order count and total spent, sorted by name."""
    require_admin(admin)
    now = auth_service.utcnow()
    with get_session() as session:
        return [
            CustomerSummary(
                r.User.id, r.User.name, r.User.email, r.User.created_at,
                int(r.order_count), Decimal(r.total_spent), r.last_order_at,
                is_locked=r.User.locked_until is not None and r.User.locked_until > now,
            )
            for r in user_repository.list_customers_with_stats(session)
        ]
