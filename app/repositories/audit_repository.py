"""Queries for the audit_log table."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog


def add(session: Session, user_id: int | None, action: str, entity: str,
        entity_id: int | None = None, details: str | None = None) -> AuditLog:
    entry = AuditLog(user_id=user_id, action=action, entity=entity,
                     entity_id=entity_id, details=details)
    session.add(entry)
    session.flush()
    return entry


def list_recent(session: Session, limit: int = 100) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
    return list(session.scalars(stmt))
