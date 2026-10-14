"""Tests for coupon validation, discount maths and admin coupon management."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.exceptions import (
    InvalidCouponError, NotFoundError, PermissionDeniedError, ValidationError,
)
from app.services import coupon_service

NEXT_MONTH = datetime.now(timezone.utc) + timedelta(days=30)


def test_normalise_code():
    assert coupon_service.normalise_code("  diwali25 ") == "DIWALI25"


@pytest.mark.parametrize("subtotal, percent, expected", [
    ("1000.00", 10, "100.00"),
    ("999.99", 15, "150.00"),   # 149.9985 rounds half-up to 150.00
    ("333.33", 25, "83.33"),    # 83.3325 -> 83.33
    ("0.10", 5, "0.01"),        # 0.005 rounds half-up to 0.01
])
def test_calculate_discount_rounds_to_paise(subtotal, percent, expected):
    assert coupon_service.calculate_discount(Decimal(subtotal), percent) == Decimal(expected)


def test_validate_coupon_accepts_valid_code_case_insensitively(factory):
    factory.coupon("TESTSAVE15", percent_off=15)
    info = coupon_service.validate_coupon("testsave15")
    assert (info.code, info.percent_off, info.is_active) == ("TESTSAVE15", 15, True)


@pytest.mark.parametrize("setup, message", [
    ({}, "does not exist"),
    ({"active": False}, "no longer active"),
    ({"days_valid": -1}, "expired"),
])
def test_validate_coupon_rejects(factory, setup, message):
    if setup:
        factory.coupon("TESTBAD", **setup)
    with pytest.raises(InvalidCouponError, match=message):
        coupon_service.validate_coupon("TESTBAD")


def test_get_valid_coupon_uses_callers_session(factory, db_session):
    factory.coupon("TESTINSESSION", percent_off=20)
    assert coupon_service.get_valid_coupon(db_session, "testinsession").percent_off == 20


def test_create_coupon(factory, admin):
    info = coupon_service.create_coupon(admin, " testnew30 ", 30, NEXT_MONTH)
    assert (info.code, info.percent_off, info.is_active) == ("TESTNEW30", 30, True)
    assert coupon_service.validate_coupon("TESTNEW30").percent_off == 30

    [entry] = factory.audit_entries("coupon")
    assert (entry.user_id, entry.action) == (admin.user_id, "create")
    assert entry.details.startswith("TESTNEW30: 30% off")


@pytest.mark.parametrize("code, percent, valid_until", [
    ("AB", 10, NEXT_MONTH),                          # too short
    ("HAS SPACE", 10, NEXT_MONTH),
    ("TESTOK", 0, NEXT_MONTH),                       # below 1%
    ("TESTOK", 91, NEXT_MONTH),                      # above 90%
    ("TESTOK", 10.5, NEXT_MONTH),                    # not a whole number
    ("TESTOK", 10, datetime.now(timezone.utc) - timedelta(days=1)),  # in the past
    ("TESTOK", 10, datetime(2030, 1, 1)),            # no time zone
])
def test_create_coupon_validation(admin, code, percent, valid_until):
    with pytest.raises(ValidationError):
        coupon_service.create_coupon(admin, code, percent, valid_until)


def test_create_coupon_duplicate_code(factory, admin):
    factory.coupon("TESTDUP")
    with pytest.raises(ValidationError, match="already exists"):
        coupon_service.create_coupon(admin, "testdup", 10, NEXT_MONTH)


def test_create_coupon_requires_admin(customer):
    with pytest.raises(PermissionDeniedError):
        coupon_service.create_coupon(customer, "TESTHACK", 90, NEXT_MONTH)


def test_deactivate_coupon(factory, admin):
    factory.coupon("TESTOFF")
    assert coupon_service.deactivate_coupon(admin, "testoff").is_active is False
    coupon_service.deactivate_coupon(admin, "TESTOFF")  # second time: no-op

    with pytest.raises(InvalidCouponError, match="no longer active"):
        coupon_service.validate_coupon("TESTOFF")
    entries = factory.audit_entries("coupon")
    assert [(e.action, e.details) for e in entries] == [("update", "TESTOFF: deactivated")]


def test_deactivate_coupon_errors(factory, admin, customer):
    with pytest.raises(NotFoundError):
        coupon_service.deactivate_coupon(admin, "TESTNOPE")
    factory.coupon("TESTKEEP")
    with pytest.raises(PermissionDeniedError):
        coupon_service.deactivate_coupon(customer, "TESTKEEP")


def test_list_coupons(factory, admin, customer):
    factory.coupon("TESTLISTED")
    assert "TESTLISTED" in {c.code for c in coupon_service.list_coupons(admin)}
    with pytest.raises(PermissionDeniedError):
        coupon_service.list_coupons(customer)
