"""Admin orders: every customer's orders with status and date filters. Selecting an
order shows its items, status timeline and payment, plus buttons for the statuses it
may move to next (order_service.next_statuses). Cancelling asks for confirmation,
because it restocks the items and refunds the payment and can't be undone.
"""

import customtkinter as ctk

from app.gui import formatting as fmt
from app.gui.screens.admin.common import button, dropdown, toolbar
from app.gui.screens.base import Screen
from app.gui.theme import PAD_L, PAD_M, PAD_S, PAD_XL
from app.gui.widgets import order_parts
from app.gui.widgets.common import (
    auto_wrap, card, clear, empty_state, label, muted, pill, section_title,
)
from app.gui.widgets.date_range import DateRangeBar
from app.gui.widgets.table import Column, DataTable
from app.services import order_service
from app.services.dto import OrderDetail, OrderSummary

ALL_STATUSES = "All statuses"
STATUSES = ["placed", "shipped", "delivered", "cancelled"]
# Button text for moving an order to each status.
ACTION_TEXT = {"shipped": "Mark as shipped", "delivered": "Mark as delivered",
               "cancelled": "Cancel order"}


class AdminOrdersScreen(Screen):
    title = "Orders"

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self._selected: int | None = None
        self._summaries: dict[int, OrderSummary] = {}

        bar = toolbar(self)
        self._status = dropdown(bar, [ALL_STATUSES] + [s.capitalize() for s in STATUSES],
                                lambda _v: self.reload(), width=150)
        self._status.pack(side="left")
        self._dates = DateRangeBar(bar, on_change=self.reload, default_days=30, allow_all=True)
        self._dates.pack(side="left", padx=PAD_M)
        self._count = muted(bar, "")
        self._count.pack(side="right")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=PAD_XL, pady=(0, PAD_L))
        body.grid_columnconfigure(0, weight=3, uniform="orders")
        body.grid_columnconfigure(1, weight=2, uniform="orders")
        body.grid_rowconfigure(0, weight=1)

        self.table = DataTable(body, [
            Column("Order", 60, lambda o: f"#{o.id}", sort=lambda o: o.id, anchor="e"),
            Column("Placed", 185, lambda o: fmt.when(o.created_at), sort=lambda o: o.created_at),
            Column("Customer", 150, lambda o: o.customer_name),
            Column("Status", 85, lambda o: o.status.capitalize()),
            Column("Items", 50, lambda o: o.item_count, sort=lambda o: o.item_count, anchor="e"),
            Column("Total", 100, lambda o: fmt.inr(o.total), sort=lambda o: o.total, anchor="e"),
        ], on_select=lambda o: self._select(o.id),
            row_color=lambda o: "text_muted" if o.status == "cancelled" else None,
            empty_text="No orders match these filters.")
        self.table.grid(row=0, column=0, sticky="nsew", padx=(0, PAD_S))

        self._detail = ctk.CTkScrollableFrame(body, fg_color="transparent")
        self._detail.grid(row=0, column=1, sticky="nsew", padx=(PAD_S, 0))
        empty_state(self._detail, "Select an order to see its details.").pack(
            fill="x", padx=PAD_S, pady=PAD_M)

    # ------------------------------------------------------------------ list

    def on_show(self, **kwargs) -> None:
        self.reload()

    def _filters(self) -> dict:
        status = self._status.get()
        date_from, date_to = self._dates.get()
        return {"status": None if status == ALL_STATUSES else status.lower(),
                "date_from": date_from, "date_to": date_to}

    def reload(self) -> None:
        self.app.tasks.run(order_service.list_all_orders, self.app.user, **self._filters(),
                           on_success=self._show_orders, message="Loading orders...")

    def _show_orders(self, orders: list[OrderSummary]) -> None:
        self._summaries = {o.id: o for o in orders}
        self.table.set_items(orders, key=lambda o: o.id)
        total = sum((o.total for o in orders if o.status != "cancelled"), start=0)
        self._count.configure(text=f"{len(orders)} orders · {fmt.inr(total)} not cancelled")
        if self._selected in self._summaries:
            self.table.select(self._selected)

    # ------------------------------------------------------------------ detail

    def _select(self, order_id: int) -> None:
        if order_id == self._selected and self._detail.winfo_children():
            return  # already showing (e.g. re-selected after a reload)
        self._selected = order_id
        self._load_detail(order_id)

    def _load_detail(self, order_id: int) -> None:
        self.app.tasks.run(order_service.get_order_detail, self.app.user, order_id,
                           on_success=self._render_detail, message="Loading order...")

    def _render_detail(self, order: OrderDetail) -> None:
        if order.id != self._selected:
            return  # the admin clicked another order meanwhile
        clear(self._detail)
        summary = self._summaries.get(order.id)

        head = card(self._detail)
        head.pack(fill="x", padx=PAD_S, pady=(0, PAD_M))
        head.grid_columnconfigure(0, weight=1)
        label(head, f"Order #{order.id}", size=20, weight="bold").grid(
            row=0, column=0, sticky="w", padx=PAD_L, pady=(PAD_L, 0))
        pill(head, order.status.capitalize(), fmt.ORDER_STATUS_COLORS[order.status]).grid(
            row=0, column=1, padx=PAD_L, pady=(PAD_L, 0))
        customer = (f"{summary.customer_name} · {summary.customer_email}" if summary
                    else f"Customer #{order.user_id}")
        muted(head, customer, size=13).grid(row=1, column=0, columnspan=2, sticky="w",
                                            padx=PAD_L)
        muted(head, f"Placed {fmt.when(order.created_at)}", size=13).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=PAD_L, pady=(0, PAD_M))

        actions = ctk.CTkFrame(head, fg_color="transparent")
        actions.grid(row=3, column=0, columnspan=2, sticky="w", padx=PAD_L, pady=(0, PAD_L))
        next_statuses = order_service.next_statuses(order.status)
        for status in next_statuses:
            kind = "danger" if status == "cancelled" else "primary"
            button(actions, ACTION_TEXT[status], lambda s=status: self._change_status(order, s),
                   kind=kind, width=150).pack(side="left", padx=(0, PAD_S))
        if not next_statuses:
            muted(actions, f"This order is {order.status}; its status can't change any more.",
                  size=12).pack(side="left")

        order_parts.timeline(self._detail, order)
        self._render_items(order)
        order_parts.totals(self._detail, order)

    def _render_items(self, order: OrderDetail) -> None:
        section_title(self._detail, "Items").pack(fill="x", padx=PAD_S, pady=(0, PAD_S))
        box = card(self._detail)
        box.pack(fill="x", padx=PAD_S, pady=(0, PAD_M))
        box.grid_columnconfigure(0, weight=1)
        for row, line in enumerate(order.lines):
            pady = (PAD_M if row == 0 else PAD_S, PAD_M if row == len(order.lines) - 1 else 0)
            info = ctk.CTkFrame(box, fg_color="transparent")
            info.grid(row=row, column=0, sticky="ew", padx=PAD_L, pady=pady)
            name = label(info, line.name, size=13, weight="bold", wraplength=200)
            name.pack(fill="x")
            auto_wrap(name, info)  # wrap to the real width (display scaling)
            muted(info, f"{line.qty} × {fmt.inr(line.unit_price)}", size=12).pack(fill="x")
            label(box, fmt.inr(line.line_total), size=13, weight="bold").grid(
                row=row, column=1, padx=PAD_L, pady=pady)

    # ------------------------------------------------------------------ status change

    def _change_status(self, order: OrderDetail, new_status: str) -> None:
        def run() -> None:
            def done(updated: OrderDetail) -> None:
                self._render_detail(updated)
                self.reload()  # the list shows the new status (and may filter it out)
            self.app.tasks.run(order_service.update_order_status, self.app.user, order.id,
                               new_status, on_success=done, on_error=self._status_failed,
                               message="Updating order...")

        if new_status == "cancelled":
            refund = "refunded" if order.payment and order.payment.status == "success" \
                else "voided"
            self.app.confirm(
                f"Cancel order #{order.id}?",
                f"The items go back into stock and the payment of {fmt.inr(order.total)} is "
                f"{refund}. This can't be undone.",
                run, confirm_text="Cancel order")
        else:
            run()

    def _status_failed(self, error) -> None:
        # E.g. another admin changed this order meanwhile: show why, then reload it.
        self.app.show_error(error)
        if self._selected is not None:
            self._load_detail(self._selected)
        self.reload()
