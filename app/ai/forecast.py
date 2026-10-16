"""Stock-out forecast: how many days until each product runs out, at its recent sales rate.

1. Daily sales: units sold per product per day (India time) over the last WINDOW_DAYS
   COMPLETE days, i.e. up to and including yesterday. Today is left out because it isn't
   over yet: half a day of sales would look like a slowdown. Cancelled orders don't count.

2. Velocity (units per day) = an EXPONENTIALLY WEIGHTED average of those daily sales.
   A day's weight halves every HALF_LIFE_DAYS days back:
       yesterday 1.0,  7 days ago 0.5,  14 days ago 0.25,  ...,  29 days ago ~0.06
   So a recent spike counts more than the same spike a month ago, but one busy day
   doesn't swing the forecast completely. Useful property for testing: if a product
   sells the same amount every day, the weighted average is exactly that amount.

3. days_left = stock / velocity. The run-out date is the first day on which the expected
   sales from tomorrow on add up to the stock: today + ceil(days_left). (Stock 0 that is
   still being sold: today.)

4. Suggested reorder = enough for the next REORDER_DAYS days at the same rate, minus
   what is in stock: ceil(velocity x 30 - stock), never below 0.

Products with no sales in the window get no forecast (None): there is no rate to
extrapolate from, and "infinite days left" would be misleading for a new product.
This module only does the maths; the sales come from report_repository via
report_service.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

WINDOW_DAYS = 30
HALF_LIFE_DAYS = 7
REORDER_DAYS = 30


@dataclass(frozen=True)
class Forecast:
    velocity: float      # expected units sold per day
    days_left: float     # stock / velocity
    run_out_date: date
    reorder_qty: int     # units to order to cover the next REORDER_DAYS days


def day_weight(days_ago: int, half_life: float = HALF_LIFE_DAYS) -> float:
    """Weight of a day `days_ago` days before today (yesterday = 1)."""
    return 0.5 ** ((days_ago - 1) / half_life)


def weighted_velocity(daily_units: list[float]) -> float:
    """Exponentially weighted average units per day. daily_units is oldest first and
    ends with yesterday: daily_units[-1] is yesterday, daily_units[-2] the day before."""
    if not daily_units:
        return 0.0
    weights = [day_weight(len(daily_units) - i) for i in range(len(daily_units))]
    return sum(w * u for w, u in zip(weights, daily_units)) / sum(weights)


def forecast(stock: int, daily_units: list[float], today: date) -> Forecast | None:
    """The forecast for one product, or None if it sold nothing in the window."""
    velocity = weighted_velocity(daily_units)
    if velocity <= 0:
        return None
    days_left = max(stock, 0) / velocity
    return Forecast(
        velocity=round(velocity, 3),
        days_left=round(days_left, 1),
        run_out_date=today + timedelta(days=math.ceil(round(days_left, 6))),
        reorder_qty=max(0, math.ceil(round(velocity * REORDER_DAYS - stock, 6))),
    )


def daily_series(sales_by_day: dict[date, float], today: date,
                 window: int = WINDOW_DAYS) -> list[float]:
    """{day: units} -> a list of `window` numbers, oldest first, ending yesterday
    (days without sales are 0)."""
    first = today - timedelta(days=window)
    return [sales_by_day.get(first + timedelta(days=i), 0) for i in range(window)]
