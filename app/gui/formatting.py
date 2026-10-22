"""How values are shown on screen: money, dates, ratings, status colours."""

from datetime import datetime
from decimal import Decimal

from app.gui.theme import COLORS

# Colours for status / badge pills.
BADGE_COLORS = {
    "Positive": COLORS["success"],
    "Mixed": COLORS["warning"],
    "Negative": COLORS["danger"],
}
ORDER_STATUS_COLORS = {
    "placed": COLORS["accent"],
    "shipped": COLORS["warning"],
    "delivered": COLORS["success"],
    "cancelled": COLORS["danger"],
}
SENTIMENT_TEXT = {"Positive": "Customers love it", "Mixed": "Mixed reviews",
                  "Negative": "Mostly negative reviews"}
PAYMENT_METHOD_LABELS = {"upi": "UPI", "card": "Card", "cod": "Cash on delivery",
                         "wallet": "Wallet"}


def inr(amount: Decimal) -> str:
    """Rupee amount with thousands separators, e.g. Rs 1,299.00 -> "₹1,299.00"."""
    return f"₹{amount:,.2f}"


def when(moment: datetime | None) -> str:
    """Date and time in the computer's local time zone (IST on our machines)."""
    if moment is None:
        return "-"
    return moment.astimezone().strftime("%d %b %Y, %I:%M %p")


def day(moment: datetime) -> str:
    return moment.astimezone().strftime("%d %b %Y")


def now() -> datetime:
    return datetime.now().astimezone()


def days_left(days: float | None) -> str:
    """Stock-out forecast: "< 1 day", "1 day", "37 days" (whole days, rounded down so
    it never sounds better than it is); "-" when there is no forecast."""
    if days is None:
        return "-"
    if days < 1:
        return "< 1 day"
    whole = int(days)
    return "1 day" if whole == 1 else f"{whole} days"


def rating(avg: float | None, count: int) -> str:
    """"★ 4.3 (12)" or "No reviews yet"."""
    if not count or avg is None:
        return "No reviews yet"
    return f"★ {avg:.1f} ({count})"


def sentiment_text(badge: str) -> str:
    """The small sentiment line on product tiles, e.g. "Customers love it"."""
    return SENTIMENT_TEXT.get(badge, f"{badge} reviews")


def stars(value: int) -> str:
    """5 -> "★★★★★", 3 -> "★★★☆☆"."""
    return "★" * value + "☆" * (5 - value)


def stock_text(stock: int, active: bool = True) -> tuple[str, str]:
    """(text, colour) describing availability."""
    if not active:
        return "No longer available", COLORS["text_muted"]
    if stock <= 0:
        return "Out of stock", COLORS["danger"]
    if stock < 10:
        return f"Only {stock} left", COLORS["warning"]
    return "In stock", COLORS["success"]
