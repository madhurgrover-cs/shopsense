"""Audit log of admin actions: who changed what, and when.

How services use it: call record_admin_action() with the SAME database session as the
change itself, inside the same `with get_session()` block. Then the change and its
audit entry commit together or roll back together, so the log can never claim
something happened that didn't (or miss something that did).

    with get_session() as session:
        product = product_repository.create(session, ...)
        audit_service.record_admin_action(
            session, actor, audit_service.CREATE, audit_service.PRODUCT, product.id,
            details=f"name={product.name!r}",
        )
"""

from sqlalchemy.orm import Session

from app.db import get_session
from app.exceptions import ValidationError
from app.models import AuditLog
from app.repositories import audit_repository
from app.services.auth_service import require_admin
from app.services.dto import AuditEntry
from app.services.user_session import UserSession

# Actions
CREATE = "create"
UPDATE = "update"
DELETE = "delete"            # products: soft delete (is_active = false)
RESTORE = "restore"          # products: undo a soft delete
STATUS_CHANGE = "status_change"

# Entities
PRODUCT = "product"
ORDER = "order"
COUPON = "coupon"
STOCK = "stock"


def record_admin_action(session: Session, actor: UserSession, action: str, entity: str,
                        entity_id: int | None = None, details: str | None = None) -> AuditLog:
    """Add an audit entry inside the caller's transaction. Only admins can be recorded,
    because only admins may perform these actions in the first place."""
    require_admin(actor)
    return audit_repository.add(session, actor.user_id, action, entity, entity_id, details)


MAX_ENTRIES = 1000


def list_recent(actor: UserSession, limit: int = 100) -> list[AuditEntry]:
    """Most recent audit entries with the admin's name, newest first (admin only)."""
    require_admin(actor)
    if not isinstance(limit, int) or not 1 <= limit <= MAX_ENTRIES:
        raise ValidationError(f"Limit must be between 1 and {MAX_ENTRIES}.")
    with get_session() as session:
        return [AuditEntry(r.AuditLog.id, r.AuditLog.created_at, r.AuditLog.user_id,
                           r.user_name, r.AuditLog.action, r.AuditLog.entity,
                           r.AuditLog.entity_id, r.AuditLog.details)
                for r in audit_repository.list_recent(session, limit)]
