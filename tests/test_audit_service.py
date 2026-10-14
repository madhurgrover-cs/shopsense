"""Tests for the admin audit log helper."""

import pytest

from app.db import get_session
from app.exceptions import PermissionDeniedError
from app.models import AuditLog
from app.repositories import user_repository
from app.services import audit_service
from app.services.user_session import UserSession


@pytest.fixture
def admin(db_session) -> UserSession:
    user = user_repository.create(db_session, "Admin", "admin.test@example.com", "x", role="admin")
    db_session.commit()
    return UserSession(user.id, user.name, user.email, user.role)


CUSTOMER = UserSession(999_999, "Customer", "c@example.com", "customer")


def audit_rows(db_session) -> list[AuditLog]:
    db_session.expire_all()
    return list(db_session.query(AuditLog).order_by(AuditLog.id))


def test_record_admin_action_writes_entry(db_session, admin):
    before = len(audit_rows(db_session))
    with get_session() as session:
        audit_service.record_admin_action(
            session, admin, audit_service.UPDATE, audit_service.PRODUCT, 42, "price 499 -> 449"
        )
    rows = audit_rows(db_session)
    assert len(rows) == before + 1
    entry = rows[-1]
    assert (entry.user_id, entry.action, entry.entity, entry.entity_id, entry.details) == (
        admin.user_id, "update", "product", 42, "price 499 -> 449"
    )
    assert entry.created_at is not None


def test_record_admin_action_rejects_non_admin(db_session):
    before = len(audit_rows(db_session))
    with pytest.raises(PermissionDeniedError):
        with get_session() as session:
            audit_service.record_admin_action(
                session, CUSTOMER, audit_service.DELETE, audit_service.PRODUCT, 1
            )
    assert len(audit_rows(db_session)) == before


def test_audit_entry_rolls_back_with_failed_action(db_session, admin):
    """The entry shares the caller's transaction: if the action fails, no log entry."""
    before = len(audit_rows(db_session))
    with pytest.raises(RuntimeError):
        with get_session() as session:
            audit_service.record_admin_action(
                session, admin, audit_service.STATUS_CHANGE, audit_service.ORDER, 7
            )
            raise RuntimeError("the order update failed after logging")
    assert len(audit_rows(db_session)) == before


def test_list_recent_newest_first(db_session, admin):
    with get_session() as session:
        for coupon_id in (1, 2, 3):
            audit_service.record_admin_action(
                session, admin, audit_service.CREATE, audit_service.COUPON, coupon_id
            )
    recent = audit_service.list_recent(admin, limit=3)
    assert [e.entity_id for e in recent] == [3, 2, 1]


def test_list_recent_is_admin_only(db_session):
    with pytest.raises(PermissionDeniedError):
        audit_service.list_recent(CUSTOMER)
