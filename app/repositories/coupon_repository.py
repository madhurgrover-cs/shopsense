"""Queries for coupons."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Coupon


def get_by_code(session: Session, code: str) -> Coupon | None:
    return session.scalars(select(Coupon).where(Coupon.code == code)).first()


def create(session: Session, code: str, percent_off: int, valid_until: datetime) -> Coupon:
    coupon = Coupon(code=code, percent_off=percent_off, valid_until=valid_until, is_active=True)
    session.add(coupon)
    session.flush()
    return coupon


def list_all(session: Session) -> list[Coupon]:
    return list(session.scalars(select(Coupon).order_by(Coupon.valid_until.desc())))
