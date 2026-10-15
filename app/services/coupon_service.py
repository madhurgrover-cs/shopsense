"""Coupon validation, discount maths, and admin coupon management."""

import re
from datetime import date, datetime, time, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.exceptions import InvalidCouponError, NotFoundError, ValidationError
from app.models import Coupon
from app.repositories import coupon_repository
from app.services import audit_service
from app.services.auth_service import require_admin
from app.services.dto import CouponInfo
from app.services.user_session import UserSession
from app.services.validation import IST, parse_date, parse_int

CODE_PATTERN = re.compile(r"^[A-Z0-9]{3,30}$")
MIN_PERCENT, MAX_PERCENT = 1, 90  # same range as the CHECK constraint on coupons


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalise_code(code: str) -> str:
    """Codes are stored upper-case; customers can type "diwali25"."""
    return code.strip().upper()


def calculate_discount(subtotal: Decimal, percent_off: int) -> Decimal:
    """The ONE place discount maths lives, used by both the cart view and checkout,
    so the price the customer sees is exactly the price they pay. Rounded to paise."""
    return (subtotal * percent_off / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def get_valid_coupon(session: Session, code: str) -> Coupon:
    """Look up a coupon inside the caller's transaction and check it can be used now."""
    coupon = coupon_repository.get_by_code(session, normalise_code(code))
    if coupon is None:
        raise InvalidCouponError("This coupon code does not exist.")
    if not coupon.is_active:
        raise InvalidCouponError("This coupon is no longer active.")
    if coupon.valid_until <= utcnow():
        raise InvalidCouponError("This coupon has expired.")
    return coupon


def validate_coupon(code: str) -> CouponInfo:
    """Check a coupon code (e.g. when the customer types it in)."""
    with get_session() as session:
        return _to_info(get_valid_coupon(session, code))


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

def list_coupons(admin: UserSession) -> list[CouponInfo]:
    require_admin(admin)
    with get_session() as session:
        return [_to_info(c) for c in coupon_repository.list_all(session)]


def create_coupon(admin: UserSession, code: str, percent_off: int | str,
                  valid_until: datetime | date | str) -> CouponInfo:
    """percent_off may be text ("15"). valid_until may be an exact moment (datetime
    with a time zone) or just a day (date or "YYYY-MM-DD"): then the coupon works until
    the END of that day, India time."""
    require_admin(admin)
    code = normalise_code(code)
    if not CODE_PATTERN.match(code):
        raise ValidationError("Coupon code must be 3-30 letters or digits, no spaces.")
    try:
        percent_off = parse_int(percent_off, "Discount", MIN_PERCENT, MAX_PERCENT)
    except ValidationError:  # one message for every kind of bad discount
        raise ValidationError(f"Discount must be a whole number from {MIN_PERCENT} "
                              f"to {MAX_PERCENT}%.") from None
    if not isinstance(valid_until, datetime):
        day = parse_date(valid_until, "Expiry date")
        valid_until = datetime.combine(day, time(23, 59, 59), IST)
    if valid_until.tzinfo is None:
        raise ValidationError("Expiry date must include a time zone.")
    if valid_until <= utcnow():
        raise ValidationError("Expiry date must be in the future.")

    try:
        with get_session() as session:
            if coupon_repository.get_by_code(session, code) is not None:
                raise ValidationError(f"Coupon {code} already exists.")
            coupon = coupon_repository.create(session, code, percent_off, valid_until)
            audit_service.record_admin_action(
                session, admin, audit_service.CREATE, audit_service.COUPON, coupon.id,
                details=f"{code}: {percent_off}% off until {valid_until:%Y-%m-%d}",
            )
            return _to_info(coupon)
    except IntegrityError as error:  # two admins creating the same code at once
        raise ValidationError(f"Coupon {code} already exists.") from error


def deactivate_coupon(admin: UserSession, code: str) -> CouponInfo:
    require_admin(admin)
    with get_session() as session:
        coupon = coupon_repository.get_by_code(session, normalise_code(code))
        if coupon is None:
            raise NotFoundError("Coupon not found.")
        if coupon.is_active:  # deactivating twice is harmless and not logged twice
            coupon.is_active = False
            audit_service.record_admin_action(
                session, admin, audit_service.UPDATE, audit_service.COUPON, coupon.id,
                details=f"{coupon.code}: deactivated",
            )
        return _to_info(coupon)


def _to_info(coupon: Coupon) -> CouponInfo:
    return CouponInfo(coupon.code, coupon.percent_off, coupon.valid_until, coupon.is_active)
