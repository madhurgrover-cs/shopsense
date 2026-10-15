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


def rating(avg: float | None, count: int) -> str:
    """"★ 4.3 (12)" or "No reviews yet"."""
    if not count or avg is None:
        return "No reviews yet"
    return f"★ {avg:.1f} ({count})"


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
