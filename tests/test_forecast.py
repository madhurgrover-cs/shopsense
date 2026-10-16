"""Tests for the stock-out forecast, with hand-made sales whose answers are known.

Part 1: the maths in app/ai/forecast.py (no database).
Part 2: report_service.stock_forecasts / get_dashboard on test orders placed on chosen
        days (inside the rollback transaction, so nothing is left behind).
"""

from datetime import date, datetime, time, timedelta

import pytest

from app.ai import forecast
from app.exceptions import PermissionDeniedError
from app.services import catalog_service, report_service
from app.services.validation import IST, today

TODAY = date(2026, 10, 16)


# ---------------------------------------------------------------------------
# Part 1: maths
# ---------------------------------------------------------------------------

def test_weights_halve_every_seven_days():
    assert forecast.day_weight(1) == 1.0          # yesterday
    assert forecast.day_weight(8) == 0.5          # a week before yesterday
    assert forecast.day_weight(15) == 0.25


def test_steady_sales_give_exactly_that_velocity():
    """2 units every day for 30 days: velocity 2, so 20 in stock lasts 10 days."""
    f = forecast.forecast(stock=20, daily_units=[2] * 30, today=TODAY)
    assert f.velocity == 2.0
    assert f.days_left == 10.0
    assert f.run_out_date == date(2026, 10, 26)   # today + 10
    assert f.reorder_qty == 40                     # 30 days x 2 - 20 in stock


def test_part_days_round_the_run_out_date_up():
    """3 in stock at 2 a day: 2 sell tomorrow, the last one the day after."""
    f = forecast.forecast(stock=3, daily_units=[2] * 30, today=TODAY)
    assert f.days_left == 1.5
    assert f.run_out_date == TODAY + timedelta(days=2)
    assert f.reorder_qty == 57


def test_recent_spike_counts_more_than_an_old_one():
    recent = [0] * 29 + [10]          # 10 sold yesterday
    old = [10] + [0] * 29             # 10 sold 30 days ago
    weights = [forecast.day_weight(30 - i) for i in range(30)]
    assert forecast.weighted_velocity(recent) == pytest.approx(10 / sum(weights))
    assert forecast.weighted_velocity(recent) > 10 / 30 > forecast.weighted_velocity(old)
    # Exact ratio: yesterday weighs 1, 30 days ago 0.5^(29/7).
    assert forecast.weighted_velocity(old) / forecast.weighted_velocity(recent) == \
        pytest.approx(0.5 ** (29 / 7))


def test_out_of_stock_and_overstocked():
    sold_out = forecast.forecast(stock=0, daily_units=[1] * 30, today=TODAY)
    assert (sold_out.days_left, sold_out.run_out_date, sold_out.reorder_qty) == (0, TODAY, 30)
    plenty = forecast.forecast(stock=500, daily_units=[1] * 30, today=TODAY)
    assert plenty.days_left == 500 and plenty.reorder_qty == 0  # never a negative order


def test_no_sales_means_no_forecast():
    assert forecast.forecast(stock=5, daily_units=[0] * 30, today=TODAY) is None
    assert forecast.forecast(stock=5, daily_units=[], today=TODAY) is None


def test_daily_series_covers_the_30_days_before_today():
    sales = {TODAY - timedelta(days=1): 4,      # yesterday: last in the series
             TODAY - timedelta(days=30): 7,     # first day of the window
             TODAY - timedelta(days=31): 99,    # too old
             TODAY: 50}                         # today isn't over yet: ignored
    series = forecast.daily_series(sales, TODAY)
    assert len(series) == 30 and series[-1] == 4 and series[0] == 7
    assert sum(series) == 11


# ---------------------------------------------------------------------------
# Part 2: through the database and the service
# ---------------------------------------------------------------------------

def noon(days_ago: int) -> datetime:
    """12:00 India time, `days_ago` days before today."""
    return datetime.combine(today() - timedelta(days=days_ago), time(12), IST)


def ours(admin, product_id):
    return next((f for f in report_service.stock_forecasts(admin) if f.product_id == product_id),
                None)


def test_service_forecast_from_steady_sales(factory, admin, customer):
    pid = factory.product(name="Test Forecast Lamp", stock=20)
    for days_ago in range(1, 31):                  # 2 a day on each of the last 30 days
        factory.order(customer.user_id, [pid], qty=2, created_at=noon(days_ago))
    # None of these may change the forecast:
    factory.order(customer.user_id, [pid], qty=50, status="cancelled", created_at=noon(1))
    factory.order(customer.user_id, [pid], qty=50, created_at=noon(31))   # too old
    factory.order(customer.user_id, [pid], qty=50, created_at=noon(0))    # today

    f = ours(admin, pid)
    assert (f.product, f.stock, f.velocity, f.days_left) == ("Test Forecast Lamp", 20, 2.0, 10.0)
    assert f.run_out_date == today() + timedelta(days=10) and f.reorder_qty == 40


def test_service_uses_india_days(factory, admin, customer):
    """00:30 IST yesterday is still the day before in UTC; it must count as yesterday."""
    pid = factory.product(stock=7)
    yesterday_early = datetime.combine(today() - timedelta(days=1), time(0, 30), IST)
    factory.order(customer.user_id, [pid], qty=3, created_at=yesterday_early)
    weights = sum(forecast.day_weight(d) for d in range(1, 31))
    assert ours(admin, pid).velocity == round(3 / weights, 3)  # weight 1 = yesterday


def test_service_skips_unsold_and_inactive_products(factory, admin, customer):
    unsold = factory.product(stock=3)
    deleted = factory.product(stock=3)
    factory.order(customer.user_id, [deleted], created_at=noon(2))
    catalog_service.delete_product(admin, deleted)
    assert ours(admin, unsold) is None and ours(admin, deleted) is None


def test_service_orders_most_urgent_first(factory, admin, customer):
    slow = factory.product(stock=100)
    fast = factory.product(stock=1)
    for pid in (slow, fast):
        factory.order(customer.user_id, [pid], qty=3, created_at=noon(1))
    days = [f.days_left for f in report_service.stock_forecasts(admin)]
    assert days == sorted(days)
    ids = [f.product_id for f in report_service.stock_forecasts(admin)]
    assert ids.index(fast) < ids.index(slow)


def test_dashboard_counts_products_running_out_within_14_days(factory, admin, customer):
    before = report_service.get_dashboard(admin)
    soon = factory.product(stock=10)      # 1 a day -> 10 days: within 14
    later = factory.product(stock=20)     # 1 a day -> 20 days: not within 14
    for days_ago in range(1, 31):
        factory.order(customer.user_id, [soon, later], created_at=noon(days_ago))
    after = report_service.get_dashboard(admin)
    assert after.run_out_soon_count == before.run_out_soon_count + 1
    assert after.running_out_soon[0].product_id == soon   # seed products last 30+ days
    assert len(after.running_out_soon) <= report_service.RUNNING_OUT_LIST


def test_stock_forecasts_is_admin_only(customer):
    with pytest.raises(PermissionDeniedError):
        report_service.stock_forecasts(customer)
