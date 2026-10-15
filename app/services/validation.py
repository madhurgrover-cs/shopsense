"""Turn what an admin typed into a form into checked values, or a clear ValidationError.

The GUI passes the raw text from its entry boxes; the services call these helpers, so
every rule (and every error message) lives in ONE place, next to the business logic,
and is covered by the service tests. Values that are already the right type (e.g. an
int from a test or a script) are accepted as they are.
"""

from datetime import date, datetime, time, timedelta, timezone

from app.exceptions import ValidationError

# India Standard Time. A fixed +05:30 offset (India has no daylight saving), so no
# time-zone database is needed on Windows. The SQL views use 'Asia/Kolkata' = the same.
IST = timezone(timedelta(hours=5, minutes=30), "IST")

DATE_FORMAT_HINT = "YYYY-MM-DD, e.g. 2026-10-31"


def parse_int(value, field: str, minimum: int | None = None,
              maximum: int | None = None) -> int:
    """A whole number from an int or from text like " 42 "."""
    if isinstance(value, bool):  # bool is a subclass of int; True is not a quantity
        raise ValidationError(f"{field} must be a whole number.")
    if isinstance(value, str):
        text = value.strip()
        if not text.lstrip("-").isdigit():
            raise ValidationError(f"{field} must be a whole number.")
        value = int(text)
    if not isinstance(value, int):
        raise ValidationError(f"{field} must be a whole number.")
    if minimum is not None and value < minimum:
        raise ValidationError(f"{field} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise ValidationError(f"{field} must be at most {maximum}.")
    return value


def parse_date(value, field: str) -> date:
    """A calendar date from a date or from text in YYYY-MM-DD form."""
    if isinstance(value, datetime):
        return value.astimezone(IST).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            raise ValidationError(f"{field} must be a date like {DATE_FORMAT_HINT}.") from None
    raise ValidationError(f"{field} must be a date like {DATE_FORMAT_HINT}.")


def date_range(start, end) -> tuple[date, date]:
    """Both ends of a date range (inclusive), checked."""
    start_day, end_day = parse_date(start, "Start date"), parse_date(end, "End date")
    if start_day > end_day:
        raise ValidationError("Start date must be on or before the end date.")
    return start_day, end_day


def day_bounds(start_day: date, end_day: date) -> tuple[datetime, datetime]:
    """The moments a date range covers, in IST: from start_day 00:00 up to (but not
    including) the day AFTER end_day 00:00, so the whole end day is included."""
    return (datetime.combine(start_day, time.min, IST),
            datetime.combine(end_day + timedelta(days=1), time.min, IST))


def today() -> date:
    return datetime.now(IST).date()
