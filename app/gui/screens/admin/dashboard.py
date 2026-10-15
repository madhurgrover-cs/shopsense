"""Admin dashboard: four KPI cards and three charts.

All numbers come from ONE call, report_service.get_dashboard(), which reads the SQL
views (v_daily_revenue, v_sales_by_category, v_top_products, v_low_stock).
"""

import customtkinter as ctk

from app.gui import formatting as fmt
from app.gui import theme
from app.gui.screens.admin.common import button, toolbar
from app.gui.screens.base import Screen
from app.gui.theme import COLORS, PAD_L, PAD_M, PAD_S
from app.gui.widgets import charts
from app.gui.widgets.common import card, label, make_clickable, muted
from app.services import report_service
from app.services.dto import Dashboard


class KpiCard(ctk.CTkFrame):
    """A big number with a caption, e.g. "Revenue  ₹55,96,943.73"."""

    def __init__(self, parent, caption: str, color: str) -> None:
        super().__init__(parent, fg_color=COLORS["surface"], corner_radius=theme.CORNER_RADIUS)
        ctk.CTkFrame(self, height=4, width=40, fg_color=color, corner_radius=2).pack(
            anchor="w", padx=PAD_L, pady=(PAD_M, 0))
        muted(self, caption, size=13).pack(fill="x", padx=PAD_L, pady=(PAD_S, 0))
        self.value = label(self, "-", size=24, weight="bold")
        self.value.pack(fill="x", padx=PAD_L)
        self.note = muted(self, "", size=12)
        self.note.pack(fill="x", padx=PAD_L, pady=(0, PAD_M))


class DashboardScreen(Screen):
    title = "Dashboard"

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        bar = toolbar(self)
        self._updated = muted(bar, "")
        self._updated.pack(side="left")
        button(bar, "Refresh", self.on_show, width=100).pack(side="right")

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=PAD_L, pady=(0, PAD_M))
        body.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="kpi")

        self.kpis = {
            "revenue": KpiCard(body, "Total revenue", COLORS["accent"]),
            "orders": KpiCard(body, "Orders", COLORS["success"]),
            "customers": KpiCard(body, "Customers", "#B48CFF"),
            "low_stock": KpiCard(body, "Low-stock products", COLORS["warning"]),
        }
        for column, kpi in enumerate(self.kpis.values()):
            kpi.grid(row=0, column=column, sticky="nsew", padx=PAD_S, pady=PAD_S)
        # The low-stock card opens the product list filtered to those products.
        make_clickable(self.kpis["low_stock"],
                       lambda: self.app.navigate("admin_products", show="Low stock"))
        self.kpis["low_stock"].note.configure(text="Fewer than 10 left · click to view")

        self.trend = charts.ChartCard(body, "Revenue, last 30 days", height=230)
        self.trend.grid(row=1, column=0, columnspan=4, sticky="nsew", padx=PAD_S, pady=PAD_S)
        self.categories = charts.ChartCard(body, "Sales by category (all time)", height=250)
        self.categories.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=PAD_S,
                             pady=PAD_S)
        self.top = charts.ChartCard(body, "Top 5 products by revenue (all time)", height=250)
        self.top.grid(row=2, column=2, columnspan=2, sticky="nsew", padx=PAD_S, pady=PAD_S)
        self.dashboard: Dashboard | None = None

    def on_show(self, **kwargs) -> None:
        self.app.tasks.run(report_service.get_dashboard, self.app.user,
                           on_success=self._render, message="Loading dashboard...")

    def _render(self, data: Dashboard) -> None:
        self.dashboard = data
        k = self.kpis
        k["revenue"].value.configure(text=fmt.inr(data.total_revenue))
        k["revenue"].note.configure(text="All orders except cancelled")
        k["orders"].value.configure(text=f"{data.order_count:,}")
        last_30 = sum(d.order_count for d in data.daily_revenue)
        k["orders"].note.configure(text=f"{last_30} in the last 30 days")
        k["customers"].value.configure(text=f"{data.customer_count:,}")
        k["customers"].note.configure(text="Registered customer accounts")
        k["low_stock"].value.configure(
            text=str(data.low_stock_count),
            text_color=COLORS["warning"] if data.low_stock_count else COLORS["text"])

        days = [d.day for d in data.daily_revenue]
        self.trend.draw(charts.revenue_trend(days, [d.revenue for d in data.daily_revenue]))
        self.categories.draw(charts.horizontal_bars(
            [c.category for c in data.sales_by_category],
            [c.revenue for c in data.sales_by_category]))
        self.top.draw(charts.horizontal_bars(
            [p.product for p in data.top_products], [p.revenue for p in data.top_products]))
        self._updated.configure(text=f"Updated {fmt.when(fmt.now())}")
