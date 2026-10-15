"""Admin reports for a date range: sales by category, top products, order history.
The report is shown as a table and can be exported to CSV or PDF in a folder the admin
picks. Building and saving the files is done by report_service."""

import gc
from datetime import datetime
from decimal import Decimal

import customtkinter as ctk

from app.gui import formatting as fmt
from app.gui import theme
from app.gui.screens.admin.common import button, set_enabled, toolbar
from app.gui.screens.base import Screen
from app.gui.theme import COLORS, PAD_L, PAD_M, PAD_S, PAD_XL
from app.gui.widgets.common import label, muted
from app.gui.widgets.date_range import DateRangeBar
from app.gui.widgets.table import Column, DataTable
from app.services import report_service
from app.services.dto import Report

# Picker label -> report id (report_service.REPORTS).
REPORT_KINDS = {"Sales by category": "sales_by_category", "Top products": "top_products",
                "Order history": "order_history"}
# Relative column widths (any other column: 110 for numbers, 130 for text).
WIDTHS = {"Category": 260, "Product": 340, "Customer": 160, "Email": 230, "Placed": 190,
          "Order": 70, "Rank": 60, "Status": 95, "Items": 60, "Payment": 85, "Coupon": 110}


def cell_text(value, money: bool) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return fmt.when(value)
    if money and isinstance(value, Decimal):
        return fmt.inr(value)
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


class ReportsScreen(Screen):
    title = "Reports"

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self.report: Report | None = None
        self.table: DataTable | None = None

        bar = toolbar(self)
        self._kind = ctk.CTkSegmentedButton(
            bar, values=list(REPORT_KINDS), command=lambda _v: self.run(),
            font=theme.font(13), selected_color=COLORS["accent"],
            selected_hover_color=COLORS["accent_hover"], unselected_color=COLORS["surface"],
            unselected_hover_color=COLORS["surface_hover"], text_color=COLORS["text"])
        self._kind.set("Sales by category")
        self._kind.pack(side="left")
        self._dates = DateRangeBar(bar, on_change=self.run, default_days=30)
        self._dates.pack(side="left", padx=PAD_M)

        head = toolbar(self)
        self._title = label(head, "", size=16, weight="bold")
        self._title.pack(side="left")
        self._pdf = button(head, "Export PDF", lambda: self._export("pdf"), width=120)
        self._pdf.pack(side="right")
        self._csv = button(head, "Export CSV", lambda: self._export("csv"), width=120)
        self._csv.pack(side="right", padx=PAD_S)
        self._note = muted(self, "", size=12)
        self._note.pack(fill="x", padx=PAD_XL, pady=(0, PAD_S))

        self._table_area = ctk.CTkFrame(self, fg_color="transparent")
        self._table_area.pack(fill="both", expand=True, padx=PAD_XL)
        self._totals = label(self, "", size=13, weight="bold")
        self._totals.pack(fill="x", padx=PAD_XL, pady=(PAD_S, PAD_L))
        self._set_export_enabled(False)

    def on_show(self, **kwargs) -> None:
        self.run()

    def run(self) -> None:
        kind = REPORT_KINDS[self._kind.get()]
        start, end = self._dates.get()
        self.app.tasks.run(report_service.run_report, self.app.user, kind, start, end,
                           on_success=self._show, message="Running report...")

    # ------------------------------------------------------------------ display

    def _show(self, report: Report) -> None:
        self.report = report
        self._title.configure(text=f"{report.title}, {report.period}")
        self._note.configure(text="Cancelled orders are not counted as sales. " + report.note)
        # Each report has different columns, so the table is rebuilt for every run.
        if self.table is not None:
            self.table.destroy()
            gc.collect()  # free the old table on the main thread (see app._set_screens)
        columns = []
        for i, name in enumerate(report.columns):
            money = i in report.money_columns
            numeric = any(isinstance(r[i], (int, Decimal)) for r in report.rows[:1])
            columns.append(Column(
                name, WIDTHS.get(name, 110 if numeric else 130),
                lambda pair, i=i, money=money: cell_text(pair[1][i], money),
                sort=lambda pair, i=i: pair[1][i], anchor="e" if numeric else "w"))
        self.table = DataTable(self._table_area, columns,
                               empty_text="No orders in this period.")
        self.table.pack(fill="both", expand=True)
        # Items are (row number, row) pairs: rows aren't guaranteed unique on their own.
        self.table.set_items(list(enumerate(report.rows)), key=lambda pair: pair[0])
        self._set_export_enabled(True)
        self._totals.configure(text=self._totals_text(report))

    @staticmethod
    def _totals_text(report: Report) -> str:
        if not report.totals:
            return f"{len(report.rows)} rows"
        parts = [f"{name}: {cell_text(value, i in report.money_columns)}"
                 for i, (name, value) in enumerate(zip(report.columns, report.totals))
                 if value is not None and i > 0]
        return f"{report.totals[0]}   ·   " + "   ·   ".join(parts)

    def _set_export_enabled(self, enabled: bool) -> None:
        set_enabled(self._csv, enabled)
        set_enabled(self._pdf, enabled)

    # ------------------------------------------------------------------ export

    def _export(self, file_format: str) -> None:
        if self.report is None:
            return
        folder = self.app.ask_folder("Choose where to save the report")
        if not folder:
            return  # the admin closed the folder picker
        self.app.tasks.run(
            report_service.export_report, self.app.user, self.report, folder, file_format,
            on_success=lambda path: self.app.show_message(
                "Report saved", f"Saved as {path.name}\nin {path.parent}", kind="success"),
            message=f"Saving {file_format.upper()}...")
