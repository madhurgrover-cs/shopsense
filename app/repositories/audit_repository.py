"""Queries for the audit_log table."""

from sqlalchemy import Row, select
from sqlalchemy.orm import Session

from app.models import AuditLog, User


def add(session: Session, user_id: int | None, action: str, entity: str,
        entity_id: int | None = None, details: str | None = None) -> AuditLog:
    entry = AuditLog(user_id=user_id, action=action, entity=entity,
                     entity_id=entity_id, details=details)
    session.add(entry)
    session.flush()
    return entry


def list_recent(session: Session, limit: int = 100) -> list[Row]:
    """(AuditLog, user_name) rows, newest first. LEFT JOIN: the user may be deleted
    (user_id SET NULL), and the entry must still be listed."""
    stmt = (
        select(AuditLog, User.name.label("user_name"))
        .outerjoin(User, User.id == AuditLog.user_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
    )
    return list(session.execute(stmt))
