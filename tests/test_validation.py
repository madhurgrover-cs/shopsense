"""Tests for turning typed form text into checked values (app/services/validation.py)."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.exceptions import ValidationError
from app.services import validation
from app.services.validation import IST


@pytest.mark.parametrize("value, expected", [(5, 5), ("5", 5), (" 42 ", 42), ("0", 0),
                                             ("-3", -3)])
def test_parse_int_accepts_ints_and_digit_text(value, expected):
    assert validation.parse_int(value, "Stock") == expected


@pytest.mark.parametrize("value", ["", "abc", "2.5", "1e3", "5 kg", 2.5, True, None])
def test_parse_int_rejects_non_whole_numbers(value):
    with pytest.raises(ValidationError, match="Stock must be a whole number"):
        validation.parse_int(value, "Stock")


def test_parse_int_limits():
    assert validation.parse_int("90", "Discount", 1, 90) == 90
    with pytest.raises(ValidationError, match="at least 1"):
        validation.parse_int("0", "Discount", 1, 90)
    with pytest.raises(ValidationError, match="at most 90"):
        validation.parse_int(91, "Discount", 1, 90)


def test_parse_date():
    assert validation.parse_date(" 2026-10-31 ", "Expiry") == date(2026, 10, 31)
    assert validation.parse_date(date(2026, 1, 2), "Expiry") == date(2026, 1, 2)
    # A datetime counts as the IST calendar day it falls on.
    late_utc = datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)  # 01:30 on the 16th IST
    assert validation.parse_date(late_utc, "Expiry") == date(2026, 10, 16)
    for bad in ("31-10-2026", "2026-13-01", "tomorrow", "", 20261031):
        with pytest.raises(ValidationError, match="YYYY-MM-DD"):
            validation.parse_date(bad, "Expiry")


def test_date_range_order():
    assert validation.date_range("2026-10-01", "2026-10-01") == (date(2026, 10, 1),) * 2
    with pytest.raises(ValidationError, match="on or before"):
        validation.date_range("2026-10-02", "2026-10-01")


def test_day_bounds_cover_whole_days_in_ist():
    start, before = validation.day_bounds(date(2026, 10, 1), date(2026, 10, 2))
    assert start == datetime(2026, 10, 1, tzinfo=IST)
    assert before == datetime(2026, 10, 3, tzinfo=IST)   # end day included completely
    assert before - start == timedelta(days=2)
    assert start.astimezone(timezone.utc) == datetime(2026, 9, 30, 18, 30, tzinfo=timezone.utc)
